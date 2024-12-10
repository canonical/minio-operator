# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json
from base64 import b64decode
from unittest.mock import MagicMock, PropertyMock

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import Operator


@pytest.fixture
def harness():
    return Harness(Operator)


def test_not_leader(harness):
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == WaitingStatus("Waiting for leadership")


def test_missing_image(harness):
    harness.set_leader(True)
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == BlockedStatus("Missing resource: oci-image")


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
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)


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
        "--certs-dir",
        "/minio/.minio/certs",
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
    pod_spec_secret_key = b64decode(pod_spec_secrets[0]["data"]["MINIO_SECRET_KEY"]).decode(
        "utf-8"
    )
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
        "--certs-dir",
        "/minio/.minio/certs",
        "--console-address",
        ":9999",
    ]


@pytest.mark.parametrize(
    "config,hash_salt,expected_hash",
    [
        (  # Standard working case
            {"access-key": "access-key-value", "secret-key": "secret-key-value"},
            "hash-salt",
            "9b25665b7652ab845b909c718f6c66dccb0946a7ef8ddd607b85198d6deabe5f",
        ),
        (  # Vary the sorted order of keys
            {
                "x_last_alphabetical_order": "access-key-value",
                "secret-key": "secret-key-value",
            },
            "hash-salt",
            "a33e4682a38734508a9c8cb6971761636fefb0225eab0cb897443f1cf1317a07",
        ),
        (  # Vary the access-key
            {"access-key": "access-key-value1", "secret-key": "secret-key-value"},
            "hash-salt",
            "162ba72393a4993626d553f2e64255f0998a70ef1b8ed4ea73652920d014898d",
        ),
        (  # Vary the salt
            {"access-key": "access-key-value", "secret-key": "secret-key-value"},
            "hash-salt1",
            "82c0d902422d085cfc5d5d652d7ebd78175042705542fe7db9866a259bd06528",
        ),
    ],
)
# skipped because tests fail with ops 1.4
# https://github.com/canonical/minio-operator/issues/58
@pytest.mark.skip
def test_generate_config_hash(config, hash_salt, expected_hash, harness):
    ##################
    # Setup test

    harness.begin()

    # Mock config to use a controlled subset of keys.  This avoids the expected hash changing
    # whenever someone adds a new config option

    # Use tuple(generator) instead of generator directly - if we use the bare generator directly
    # it'll raise an exception in update_config because update_config will be editing the object
    # we're taking keys() from
    old_keys = tuple(harness.charm.config.keys())
    harness.update_config(unset=old_keys)
    assert len(harness.charm.config.keys()) == 0, "Failed to delete default config keys"

    # Avoid triggering config_changed as hooks may have unexpected failures due to reduced config
    # data
    with harness.hooks_disabled():
        harness.update_config(config)

    # Mock away _stored with known values
    harness.charm._stored = MagicMock()
    mocked_salt = PropertyMock(return_value=hash_salt)
    type(harness.charm._stored).hash_salt = mocked_salt

    ##################
    # Execute test

    hashed_config = harness.charm._generate_config_hash()

    ##################
    # Check results
    assert expected_hash == hashed_config


# TODO: test get_secret_key
# TODO: How can I test whether the hash/password gets randomly generated if respective config is
#  omitted?  Or can/should I at all?


def test_prometheus_data_set(harness, mocker):
    harness.set_leader(True)
    harness.set_model_name("kubeflow")
    harness.begin()

    rel_id = harness.add_relation("metrics-endpoint", "otherapp")
    harness.add_relation_unit(rel_id, "otherapp/0")
    harness.update_relation_data(rel_id, "otherapp", {})

    assert json.loads(harness.get_relation_data(rel_id, harness.model.app.name)["scrape_jobs"])[0][
        "static_configs"
    ][0]["targets"] == ["*:9000"]
