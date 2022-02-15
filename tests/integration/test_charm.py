# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
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


async def test_connect_client_to_server(ops_test: OpsTest):
    """
    Tests a deployed MinIO app by trying to connect to it from a pod and do trivial actions with it
    """
    # TODO: This presumes we're using microk8s.  Fix that.
    #  could just call kubectl and count on the outside environment aliasing it for us?
    #  or could pass kubectl path in as a variable?

    application = ops_test.model.applications[APP_NAME]
    config = await application.get_config()
    port = config["port"]["value"]
    alias = "ci"
    bucket = "testbucket"
    # TODO: how do I dynamically retrieve the minio k8s service name?
    service_name = APP_NAME
    model_name = ops_test.model_name
    log.info(f"ops_test.model_name = {ops_test.model_name}")

    url = f"http://{service_name}.{model_name}.svc.cluster.local:{port}"

    minio_cmd = (
        f"mc alias set {alias} {url} {MINIO_CONFIG['access-key']} {MINIO_CONFIG['secret-key']}"
        f"&& mc mb {alias}/{bucket}"
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

    assert (
        ret_code == 0
    ), f"Test returned code {ret_code} with stdout:\n{stdout}\nstderr:\n{stderr}"


async def test_connect_to_console(ops_test: OpsTest):
    """
    Tests a deployed MinIO app by trying to connect to the MinIO console
    """
    # TODO: This presumes we're using microk8s.  Fix that.
    #  could just call kubectl and count on the outside environment aliasing it for us?
    #  or could pass kubectl path in as a variable?

    application = ops_test.model.applications[APP_NAME]
    config = await application.get_config()
    port = config["console-port"]["value"]
    # TODO: how do I dynamically retrieve the minio k8s service name?
    service_name = APP_NAME
    model_name = ops_test.model_name
    log.info(f"ops_test.model_name = {ops_test.model_name}")

    url = f"http://{service_name}.{model_name}.svc.cluster.local:{port}"

    cmd = f"curl -I {url}"

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
