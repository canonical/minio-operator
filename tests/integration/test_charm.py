# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
import requests
import json
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_exponential

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MINIO_CONFIG = {
    "access-key": "minio",
    "secret-key": "minio-secret-key",
}

APP_NAME = "minio"
CHARM_ROOT = "."
PROMETHEUS = "prometheus-k8s"
GRAFANA = "grafana-k8s"
PROMETHEUS_SCRAPE = "prometheus-scrape-config-k8s"


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    built_charm_path = await ops_test.build_charm(CHARM_ROOT)
    log.info(f"Built charm {built_charm_path}")

    image_path = METADATA["resources"]["oci-image"]["upstream-source"]
    resources = {"oci-image": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        resources=resources,
        config=MINIO_CONFIG,
    )
    await ops_test.model.wait_for_idle(timeout=60 * 10)


async def connect_client_to_server(
    ops_test: OpsTest, application, access_key=None, secret_key=None
):
    """Connects to the minio server using a minio client. raising a ConnectionError if failed
    Args:
        ops_test: fixture
        application: Minio application to connect to
        access_key (str): (Optional) access-key for minio login.  If omitted, will be pulled from
                          application's config
        secret_key (str): (Optional) secret-key for minio login.  If omitted, will be pulled from
                          application's config

    Returns:
        None
    """
    config = await application.get_config()

    if access_key is None:
        access_key = config["access-key"]["value"]
    if secret_key is None:
        secret_key = config["secret-key"]["value"]

    port = config["port"]["value"]
    alias = "ci"
    bucket = "testbucket"
    service_name = APP_NAME
    model_name = ops_test.model_name

    url = f"http://{service_name}.{model_name}.svc.cluster.local:{port}"

    minio_cmd = (
        f"mc alias set {alias} {url} {access_key} {secret_key}"
        f"&& mc mb {alias}/{bucket}"
        f"&& mc rb {alias}/{bucket}"
    )

    kubectl_cmd = (
        "microk8s",
        "kubectl",
        "run",
        "--rm",
        "-i",
        "--restart=Never",
        "--command",
        f"--namespace={ops_test.model_name}",
        "minio-deployment-test",
        "--image=minio/mc",
        "--",
        "sh",
        "-c",
        minio_cmd,
    )

    ret_code, stdout, stderr = await ops_test.run(*kubectl_cmd)

    if ret_code != 0:
        raise ConnectionError(
            f"Connection to Minio returned code {ret_code} with stdout:\n{stdout}\n"
            f"stderr:\n{stderr}."
        )
    else:
        return


async def test_connect_client_to_server(ops_test: OpsTest):
    """
    Tests a deployed MinIO by connecting with mc (MinIO client) via a Pod.
    """

    application = ops_test.model.applications[APP_NAME]

    for attempt in retry_for_60_seconds:
        log.info(
            f"Test attempting to connect to minio using mc client (attempt "
            f"{attempt.retry_state.attempt_number})"
        )
        with attempt:
            await connect_client_to_server(ops_test=ops_test, application=application)


# Helper to retry calling a function over 60 seconds
retry_for_60_seconds = Retrying(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    reraise=True,
)


async def test_connect_to_console(ops_test: OpsTest):
    """
    Tests a deployed MinIO app by trying to connect to the MinIO console
    """

    application = ops_test.model.applications[APP_NAME]
    config = await application.get_config()
    port = config["console-port"]["value"]
    service_name = APP_NAME
    model_name = ops_test.model_name
    log.info(f"ops_test.model_name = {ops_test.model_name}")

    url = f"http://{service_name}.{model_name}.svc.cluster.local:{port}"

    kubectl_cmd = (
        "microk8s",
        "kubectl",
        "run",
        "--rm",
        "-i",
        "--restart=Never",
        "--command",
        f"--namespace={ops_test.model_name}",
        "minio-deployment-test",
        "--image=curlimages/curl",
        "--",
        "curl",
        "-I",
        url,
    )

    ret_code, stdout, stderr = await ops_test.run(*kubectl_cmd)

    assert (
        ret_code == 0
    ), f"Test returned code {ret_code} with stdout:\n{stdout}\nstderr:\n{stderr}"


async def test_refresh_credentials(ops_test: OpsTest):
    """Tests that changing access/secret correctly gets reflected in workload

    Note: This test is not idempotent - it leaves the charm with different credentials than how it
          started.  We could move credential changing and resetting to a fixture so it always
          restored them if that becomes a problem.

    Note: Untested here is whether setting the config to the current value (eg: a no-op) correctly
          avoids restarting the workload.
    """
    # Update credentials in deployed Minio's config
    application = ops_test.model.applications[APP_NAME]
    old_config = await application.get_config()
    config = {
        "access-key": old_config["access-key"]["value"] + "modified",
        "secret-key": old_config["secret-key"]["value"] + "modified",
    }
    await application.set_config(config)

    for attempt in retry_for_60_seconds:
        log.info(
            f"Test attempting to connect to minio using mc client (attempt "
            f"{attempt.retry_state.attempt_number})"
        )
        with attempt:
            await connect_client_to_server(
                ops_test=ops_test,
                application=application,
                access_key=config["access-key"],
                secret_key=config["secret-key"],
            )


async def test_deploy_with_prometheus_and_grafana(ops_test):
    scrape_config = {"scrape_interval": "30s"}
    await ops_test.model.deploy(PROMETHEUS, channel="latest/beta")
    await ops_test.model.deploy(GRAFANA, channel="latest/beta")
    await ops_test.model.deploy(
        PROMETHEUS_SCRAPE, channel="latest/beta", config=scrape_config
    )
    await ops_test.model.add_relation(APP_NAME, PROMETHEUS_SCRAPE)
    await ops_test.model.add_relation(PROMETHEUS, PROMETHEUS_SCRAPE)
    await ops_test.model.add_relation(PROMETHEUS, GRAFANA)
    await ops_test.model.add_relation(APP_NAME, GRAFANA)

    await ops_test.model.wait_for_idle(
        [APP_NAME, PROMETHEUS, GRAFANA, PROMETHEUS_SCRAPE], status="active"
    )


async def test_correct_observability_setup(ops_test):
    status = await ops_test.model.get_status()
    prometheus_unit_ip = status["applications"][PROMETHEUS]["units"][f"{PROMETHEUS}/0"][
        "address"
    ]
    r = requests.get(
        f'http://{prometheus_unit_ip}:9090/api/v1/query?query=up{{juju_application="{APP_NAME}"}}'
    )
    response = json.loads(r.content.decode("utf-8"))
    assert response["status"] == "success"
    assert len(response["data"]["result"]) == len(
        ops_test.model.applications[APP_NAME].units
    )

    response_metric = response["data"]["result"][0]["metric"]
    assert response_metric["juju_application"] == APP_NAME
    assert response_metric["juju_charm"] == APP_NAME
    assert response_metric["juju_model"] == ops_test.model_name
    assert response_metric["juju_unit"] == f"{APP_NAME}/0"
