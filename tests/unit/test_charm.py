# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
import yaml
from base64 import b64decode
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import Operator


@pytest.fixture
def harness():
    return Harness(Operator)


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_missing_image(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "Missing resource: oci-image"
    )


def test_main_no_relation(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.begin_with_initial_hooks()
    pod_spec = harness.get_pod_spec()

    # confirm that we can serialize the pod spec
    yaml.safe_dump(pod_spec)

    assert harness.charm.model.unit.status == ActiveStatus("")


def test_incompatible_version(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.update_relation_data(
        rel_id,
        "argo-controller",
        {"_supported_versions": yaml.dump(["v2"])},
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus(
        "No compatible object-storage versions found for apps: argo-controller"
    )


def test_unversioned(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus(
        "List of object-storage versions not found for apps: argo-controller"
    )


def test_main_with_relation(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.update_relation_data(
        rel_id,
        "argo-controller",
        {"_supported_versions": yaml.dump(["v1"])},
    )
    rel_id = harness.add_relation("object-storage", "foobar")
    harness.add_relation_unit(rel_id, "foobar/0")
    harness.update_relation_data(
        rel_id,
        "foobar",
        {"_supported_versions": yaml.dump(["v1"])},
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")

    data = yaml.safe_load(harness.get_relation_data(rel_id, "minio")["data"])
    assert data["access-key"] == "minio"
    assert data["namespace"] is None
    assert data["port"] == 9000
    assert data["secure"] is False
    assert len(data["secret-key"]) == 30
    assert data["service"] == "minio"


def test_main_with_manual_secret(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.update_relation_data(
        rel_id,
        "argo-controller",
        {"_supported_versions": yaml.dump(["v1"])},
    )
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")

    harness.update_config({"secret-key": "test-key"})
    data = yaml.safe_load(harness.get_relation_data(rel_id, "minio")["data"])
    assert data == {
        "access-key": "minio",
        "namespace": None,
        "port": 9000,
        "secret-key": "test-key",
        "secure": False,
        "service": "minio",
    }
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_server_minio_args(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.update_config({"secret-key": "test-key"})
    harness.begin_with_initial_hooks()
    pod_spec = harness.get_pod_spec()

    pod_spec_secrets = pod_spec[0]["kubernetesResources"]["secrets"]
    pod_spec_secret_key = pod_spec_secrets[0]["data"]["MINIO_SECRET_KEY"]
    pod_spec_secret_name = pod_spec_secrets[0]["name"]

    assert b64decode(pod_spec_secret_key).decode("utf-8") == "test-key"
    assert pod_spec[0]["containers"][0]["args"] == [
        "server",
        "/data",
        "--console-address",
        ":9001",
    ]
    assert pod_spec_secret_name == f"{harness.model.app.name}-secret"


def test_gateway_minio_args(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.update_config(
        {
            "secret-key": "test-key",
            "mode": "gateway",
            "gateway-storage-service": "azure",
        }
    )
    harness.begin_with_initial_hooks()
    pod_spec = harness.get_pod_spec()

    pod_spec_secrets = pod_spec[0]["kubernetesResources"]["secrets"]
    pod_spec_secret_key = pod_spec_secrets[0]["data"]["MINIO_SECRET_KEY"]

    assert b64decode(pod_spec_secret_key).decode("utf-8") == "test-key"
    assert pod_spec[0]["containers"][0]["args"] == [
        "gateway",
        "azure",
        "--console-address",
        ":9001",
    ]


def test_gateway_minio_missing_args(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.update_config(
        {
            "secret-key": "test-key",
            "mode": "gateway",
        }
    )
    harness.begin_with_initial_hooks()

    assert harness.charm.model.unit.status == BlockedStatus(
        "Minio in gateway mode requires gateway-storage-service configuration. "
        "Possible values: s3, azure"
    )


def test_gateway_minio_with_private_endpoint(harness):
    harness.set_leader(True)

    secret_key = "test-key"
    minio_mode = "gateway"
    storage_service = "azure"
    storage_service_endpoint = "http://someendpoint"

    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.update_config(
        {
            "secret-key": secret_key,
            "mode": minio_mode,
            "gateway-storage-service": storage_service,
            "storage-service-endpoint": storage_service_endpoint,
        }
    )
    harness.begin_with_initial_hooks()
    pod_spec = harness.get_pod_spec()

    expected_container_args = [
        minio_mode,
        storage_service,
        storage_service_endpoint,
        "--console-address",
        ":9001",
    ]
    assert pod_spec[0]["containers"][0]["args"] == expected_container_args

    pod_spec_secrets = pod_spec[0]["kubernetesResources"]["secrets"]
    pod_spec_secret_key = b64decode(
        pod_spec_secrets[0]["data"]["MINIO_SECRET_KEY"]
    ).decode("utf-8")
    assert pod_spec_secret_key == secret_key


def test_minio_console_port_args(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.update_config(
        {
            "secret-key": "test-key",
            "console-port": 9999,
        }
    )
    harness.begin_with_initial_hooks()
    pod_spec = harness.get_pod_spec()

    assert pod_spec[0]["containers"][0]["args"] == [
        "server",
        "/data",
        "--console-address",
        ":9999",
    ]

def test_install_with_all_inputs(harness):
    harness.set_leader(True)
    harness.add_oci_resource(
        "oci-image",
        {
            "registrypath": "ci-test",
            "username": "",
            "password": "",
        },
    )
    harness.update_config(
        {
            "secret-key": "test-secret-key",
            "access-key": "test-access-key",
            "mode": "gateway",
            "gateway-storage-service": "azure",
        }
    )

    # object storage
    os_rel_id = harness.add_relation("object-storage", "foobar")
    harness.add_relation_unit(os_rel_id, "foobar/0")
    harness.update_relation_data(
        os_rel_id,
        "foobar",
        {"_supported_versions": yaml.dump(["v1"])},
    )

    # ingress
    ingress_relation_name = "ingress"
    relation_version_data = {"_supported_versions": "- v1"}
    ingress_rel_id = harness.add_relation(
        ingress_relation_name, f"{ingress_relation_name}-subscriber"
    )
    harness.add_relation_unit(ingress_rel_id, f"{ingress_relation_name}-subscriber/0")
    harness.update_relation_data(
        ingress_rel_id, f"{ingress_relation_name}-subscriber", relation_version_data
    )

    harness.begin_with_initial_hooks()

    pod_spec = harness.get_pod_spec()
    yaml.safe_dump(pod_spec)
    assert harness.charm.model.unit.status == ActiveStatus()

    charm_name = harness.model.app.name
    secrets = pod_spec[0]["kubernetesResources"]["secrets"]
    env_config = pod_spec[0]["containers"][0]["envConfig"]

    pod_spec_secrets = pod_spec[0]["kubernetesResources"]["secrets"]
    pod_spec_secret_key = pod_spec_secrets[0]["data"]["MINIO_SECRET_KEY"]
    pod_spec_access_key = pod_spec_secrets[0]["data"]["MINIO_ACCESS_KEY"]

    assert b64decode(pod_spec_secret_key).decode("utf-8") == "test-secret-key"
    assert b64decode(pod_spec_access_key).decode("utf-8") == "test-access-key"
    assert pod_spec[0]["containers"][0]["args"] == [
        "gateway",
        "azure",
        "--console-address",
        ":9001",
    ]