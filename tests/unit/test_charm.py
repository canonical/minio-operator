# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import json

import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.testing import Harness

from charm import MinIOOperator

CONTAINER_NAME = "minio"


@pytest.fixture
def harness() -> Harness:
    return Harness(MinIOOperator)


def test_not_leader(harness):
    """Test when we are not the leader."""
    harness.begin_with_initial_hooks()
    # Assert that we are not Active, and that the leadership-gate is the cause.
    assert not isinstance(harness.charm.model.unit.status, ActiveStatus)
    assert harness.charm.model.unit.status.message.startswith("[leadership-gate]")


def test_no_relation(harness):
    """Test that the charm enters ActiveStatus if there is no relation."""
    # Arrange
    harness.set_leader(True)

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == ActiveStatus("")
    container = harness.charm.unit.get_container(CONTAINER_NAME)
    assert container.get_service(CONTAINER_NAME).is_running()


def test_object_storage_relation_incompatible_version(harness):
    """Test that the charm enters BlockedStatus if the object-storage relation is incompatible."""
    # Arrange
    harness.set_leader(True)
    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.update_relation_data(
        rel_id,
        "argo-controller",
        {"_supported_versions": yaml.dump(["v2"])},
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == BlockedStatus(
        "[relation:object_storage] No compatible object-storage versions found for apps: "
        "argo-controller"
    )


def test_object_storage_relation_unversioned(harness):
    """Test that the charm is in WaitingStatus if the object-storage relation is unversioned."""
    # Arrange
    harness.set_leader(True)
    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert isinstance(harness.charm.model.unit.status, WaitingStatus)


def test_object_storage_relation(harness):
    """Test that the object-storage relation is set up correctly."""
    # Arrange
    harness.set_leader(True)

    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.update_relation_data(
        rel_id,
        "argo-controller",
        {"_supported_versions": yaml.dump(["v1"])},
    )

    # rel_id = harness.add_relation("object-storage", "foobar")
    # harness.add_relation_unit(rel_id, "foobar/0")
    # harness.update_relation_data(
    #     rel_id,
    #     "foobar",
    #     {"_supported_versions": yaml.dump(["v1"])},
    # )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == ActiveStatus("")
    data = yaml.safe_load(harness.get_relation_data(rel_id, "minio")["data"])
    secret_key = data["secret-key"]
    assert data["access-key"] == "minio"
    assert data["port"] == 9000
    assert data["secure"] is False
    assert len(secret_key) == 30
    assert data["service"] == "minio"


def test_object_storage_relation_with_manual_secret(harness):
    """Test that the object-storage relation is set up correctly with a manual secret key."""
    # Arrange
    harness.set_leader(True)
    harness.update_config({"secret-key": "test-key"})

    rel_id = harness.add_relation("object-storage", "argo-controller")
    harness.add_relation_unit(rel_id, "argo-controller/0")
    harness.update_relation_data(
        rel_id,
        "argo-controller",
        {"_supported_versions": yaml.dump(["v1"])},
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == ActiveStatus("")
    data = yaml.safe_load(harness.get_relation_data(rel_id, "minio")["data"])
    assert data == {
        "access-key": "minio",
        "port": 9000,
        "secret-key": "test-key",
        "secure": False,
        "service": "minio",
    }
    assert harness.charm.model.unit.status == ActiveStatus("")


def test_server_minio_args(harness):
    """Test that the server minio args are set correctly."""
    # Arrange
    harness.set_leader(True)
    harness.update_config({"access-key": "minio", "secret-key": "test-key"})

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    container = harness.charm.unit.get_container(CONTAINER_NAME)
    assert container.get_service(CONTAINER_NAME).is_running()
    command = container.get_plan().services[CONTAINER_NAME].command
    environment = container.get_plan().services[CONTAINER_NAME].environment

    # Assert the environment variables are set correctly
    assert environment["MINIO_ROOT_USER"] == "minio"
    assert environment["MINIO_ROOT_PASSWORD"] == "test-key"
    assert environment["MINIO_PROMETHEUS_AUTH_TYPE"] == "public"

    # Assert the command includes the console address with the specified port
    expected_args = [
        "server",
        "/data",
        "--certs-dir",
        "/minio/.minio/certs",
        "--console-address",
        ":9001",
    ]
    assert command == f"minio {' '.join(expected_args)}"


def test_gateway_minio_args(harness):
    """Test that the gateway minio args are set correctly."""
    # Arrange
    harness.set_leader(True)
    harness.update_config(
        {
            "access-key": "minio",
            "secret-key": "test-key",
            "mode": "gateway",
            "gateway-storage-service": "azure",
        }
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    container = harness.charm.unit.get_container(CONTAINER_NAME)
    assert container.get_service(CONTAINER_NAME).is_running()
    command = container.get_plan().services[CONTAINER_NAME].command

    # Assert the command includes the console address with the specified port
    expected_args = [
        "gateway",
        "azure",
        "--console-address",
        ":9001",
    ]
    assert command == f"minio {' '.join(expected_args)}"


def test_gateway_minio_missing_args(harness):
    """Test that charm is blocked if required args for gateway mode are missing."""
    # Arrange
    harness.set_leader(True)
    harness.update_config(
        {
            "secret-key": "test-key",
            "mode": "gateway",
        }
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == BlockedStatus(
        "MinIO gateway mode requires 'gateway-storage-service' configuration. "
        "Supported values: 's3', 'azure'"
    )


def test_invalid_minio_mode(harness):
    """Test that charm is blocked if an invalid minio mode is set."""
    # Arrange
    harness.set_leader(True)
    harness.update_config(
        {
            "access-key": "minio",
            "secret-key": "test-key",
            "mode": "invalid-mode",
        }
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == BlockedStatus(
        "Invalid mode 'invalid-mode'. Supported values: 'server', 'gateway'"
    )


def test_invalid_secret_key_length(harness):
    """Test that charm is blocked if the secret key length is invalid."""
    # Arrange
    harness.set_leader(True)
    harness.update_config(
        {
            "access-key": "minio",
            "secret-key": "short",
        }
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    assert harness.charm.model.unit.status == BlockedStatus(
        "The 'secret-key' config value must be at least 8 characters long."
    )


def test_gateway_minio_with_private_endpoint(harness):
    """Test that the gateway minio args are set correctly with a private endpoint."""
    minio_mode = "gateway"
    storage_service = "azure"
    storage_service_endpoint = "http://someendpoint"

    # Arrange
    harness.set_leader(True)
    harness.update_config(
        {
            "access-key": "minio",
            "secret-key": "test-key",
            "mode": minio_mode,
            "gateway-storage-service": storage_service,
            "storage-service-endpoint": storage_service_endpoint,
        }
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    container = harness.charm.unit.get_container(CONTAINER_NAME)
    assert container.get_service(CONTAINER_NAME).is_running()
    command = container.get_plan().services[CONTAINER_NAME].command

    # Assert the command includes the console address with the specified port
    expected_args = [
        minio_mode,
        storage_service,
        storage_service_endpoint,
        "--console-address",
        ":9001",
    ]
    assert command == f"minio {' '.join(expected_args)}"


def test_minio_console_port_args(harness):
    """Test that the console port is set correctly in the args."""
    # Arrange
    harness.set_leader(True)
    harness.update_config(
        {
            "access-key": "minio",
            "secret-key": "test-key",
            "console-port": 9999,
        }
    )

    # Act
    harness.begin_with_initial_hooks()

    # Assert
    container = harness.charm.unit.get_container(CONTAINER_NAME)
    assert container.get_service(CONTAINER_NAME).is_running()
    command = container.get_plan().services[CONTAINER_NAME].command

    # Assert the command includes the console address with the specified port
    expected_args = [
        "server",
        "/data",
        "--certs-dir",
        "/minio/.minio/certs",
        "--console-address",
        ":9999",
    ]
    assert command == f"minio {' '.join(expected_args)}"


def test_prometheus_data_set(harness, mocker):
    """Test that the prometheus scrape jobs are set correctly in the relation data."""
    # Arrange
    harness.set_leader(True)
    harness.set_model_name("kubeflow")

    # Act
    harness.begin()
    rel_id = harness.add_relation("metrics-endpoint", "otherapp")
    harness.add_relation_unit(rel_id, "otherapp/0")
    harness.update_relation_data(rel_id, "otherapp", {})

    # Assert
    assert json.loads(harness.get_relation_data(rel_id, harness.model.app.name)["scrape_jobs"])[0][
        "static_configs"
    ][0]["targets"] == ["*:9000"]
