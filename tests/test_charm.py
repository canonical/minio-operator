import pytest
import yaml
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import Operator


@pytest.fixture
def harness():
    return Harness(Operator)


def test_not_leader(harness):
    harness.begin()
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
    rel_id = harness.add_relation("object-storage", "object-storage")
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")
    harness.add_relation_unit(rel_id, "argo-controller/0")

    data = yaml.safe_load(harness.get_relation_data(rel_id, "minio")["data"])
    assert data["access-key"] == "minio"
    assert data["namespace"] is None
    assert data["port"] == 9000
    assert data["secure"] is True
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
    rel_id = harness.add_relation("object-storage", "object-storage")
    harness.begin_with_initial_hooks()
    assert harness.charm.model.unit.status == ActiveStatus("")

    harness.update_config({"secret-key": "test-key"})
    data = yaml.safe_load(harness.get_relation_data(rel_id, "minio")["data"])
    assert data == {
        "access-key": "minio",
        "namespace": None,
        "port": 9000,
        "secret-key": "test-key",
        "secure": True,
        "service": "minio",
    }
    assert harness.charm.model.unit.status == ActiveStatus("")
