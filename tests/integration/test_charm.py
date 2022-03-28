# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
from tenacity import retry, stop_after_delay, wait_exponential
import yaml
from pytest_operator.plugin import OpsTest

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

MINIO_CONFIG = {
    "access-key": "minio",
    "secret-key": "minio-secret-key",
}

APP_NAME = "minio"
CHARM_ROOT = "."


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


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_delay(60),
    reraise=True,
)
async def connect_client_to_server_with_retry(
    ops_test: OpsTest, application, access_key=None, secret_key=None
):
    ret_code, stdout, stderr = await connect_client_to_server(
        ops_test=ops_test,
        application=application,
        access_key=access_key,
        secret_key=secret_key,
    )
    log.info("Trying to connect to minio via mc client")

    if ret_code != 0:
        msg = (
            f"Connection to Minio returned code {ret_code} with stdout:\n{stdout}\n"
            f"stderr:\n{stderr}."
        )
        log.warning(msg + "  If this persists, this may be an error")

        raise ValueError(msg)

    else:
        return ret_code, stdout, stderr


async def connect_client_to_server(
    ops_test: OpsTest, application, access_key=None, secret_key=None
):
    """Connects to the minio server using a minio client
    Args:
        ops_test: fixture
        application: Minio application to connect to
        access_key (str): (Optional) access-key for minio login.  If omitted, will be pulled from
                          application's config
        secret_key (str): (Optional) secret-key for minio login.  If omitted, will be pulled from
                          application's config

    Returns:
        Tuple of return code, stderr, and stdout from kubectl call from launching the test pod
        using kubectl
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
    log.info(f"ops_test.model_name = {ops_test.model_name}")

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
    return ret_code, stdout, stderr


async def test_connect_client_to_server(ops_test: OpsTest):
    """
    Tests a deployed MinIO app by trying to connect to it from a pod and do trivial actions with it
    """

    application = ops_test.model.applications[APP_NAME]
    ret_code, stdout, stderr = await connect_client_to_server_with_retry(
        ops_test=ops_test, application=application
    )

    assert (
        ret_code == 0
    ), f"Test returned code {ret_code} with stdout:\n{stdout}\nstderr:\n{stderr}"


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
