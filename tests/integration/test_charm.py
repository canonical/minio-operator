# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from charmed_kubeflow_chisme.testing import (
    assert_alert_rules,
    assert_grafana_dashboards,
    assert_metrics_endpoint,
    deploy_and_assert_grafana_agent,
    get_alert_rules,
    get_grafana_dashboards,
)
from pytest_operator.plugin import OpsTest
from tenacity import Retrying, stop_after_delay, wait_exponential

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
APP_NAME = METADATA["name"]
CHARM_ROOT = "."
MINIO_CONFIG = {
    "access-key": "minio",
    "secret-key": "minio-secret-key",
}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest):
    built_charm_path = await ops_test.build_charm(CHARM_ROOT)
    log.info(f"Built charm {built_charm_path}")

    image_path = METADATA["resources"]["minio"]["upstream-source"]
    resources = {"minio": image_path}

    await ops_test.model.deploy(
        entity_url=built_charm_path,
        resources=resources,
        config=MINIO_CONFIG,
    )
    await ops_test.model.wait_for_idle(timeout=60 * 10)

    # Deploying grafana-agent-k8s and add all relations
    await deploy_and_assert_grafana_agent(
        ops_test.model, APP_NAME, metrics=True, dashboard=True, logging=False, channel="1/stable"
    )


async def test_metrics_enpoint(ops_test: OpsTest):
    """Test metrics_endpoints are defined in relation data bag and their accessibility.
    This function gets all the metrics_endpoints from the relation data bag, checks if
    they are available from the grafana-agent-k8s charm and finally compares them with the
    ones provided to the function.
    """
    app = ops_test.model.applications[APP_NAME]
    await assert_metrics_endpoint(app, metrics_port=9000, metrics_path="/minio/v2/metrics/cluster")


async def test_alert_rules(ops_test: OpsTest):
    """Test check charm alert rules and rules defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    alert_rules = get_alert_rules()
    log.info("found alert_rules: %s", alert_rules)
    await assert_alert_rules(app, alert_rules)


async def test_grafana_dashboards(ops_test: OpsTest):
    """Test Grafana dashboards are defined in relation data bag."""
    app = ops_test.model.applications[APP_NAME]
    dashboards = get_grafana_dashboards()
    log.info("found dashboards: %s", dashboards)
    await assert_grafana_dashboards(app, dashboards)


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
