#!/usr/bin/env python3

import logging
from random import choices
from string import ascii_uppercase, digits

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, WaitingStatus, BlockedStatus

from serialized_data_interface import (
    get_interfaces,
    NoVersionsListed,
    NoCompatibleVersions,
)
from oci_image import OCIImageResource, OCIImageResourceError

log = logging.getLogger()


def gen_pass() -> str:
    return "".join(choices(ascii_uppercase + digits, k=30))


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        self._stored.set_default(secret_key=gen_pass())
        try:
            self.interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            self.model.unit.status = WaitingStatus(str(err))
            return
        except NoCompatibleVersions as err:
            self.model.unit.status = BlockedStatus(str(err))
            return

        self.image = OCIImageResource(self, "oci-image")

        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)

        self.framework.observe(self.on.config_changed, self.send_info)
        self.framework.observe(
            self.on["object-storage"].relation_joined, self.send_info
        )
        self.framework.observe(
            self.on["object-storage"].relation_changed, self.send_info
        )

    def send_info(self, event):
        secret_key = self.model.config["secret-key"] or self._stored.secret_key

        if self.interfaces["object-storage"]:
            self.interfaces["object-storage"].send_data(
                {
                    "access-key": self.model.config["access-key"],
                    "namespace": self.model.name,
                    "port": self.model.config["port"],
                    "secret-key": secret_key,
                    "secure": True,
                    "service": self.model.app.name,
                }
            )

    def set_pod_spec(self, event):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            log.info(e)
            return

        secret_key = self.model.config["secret-key"] or self._stored.secret_key

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "containers": [
                    {
                        "name": "minio",
                        "args": ["server", "/data"],
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "minio",
                                "containerPort": int(self.model.config["port"]),
                            }
                        ],
                        "envConfig": {
                            "MINIO_ACCESS_KEY": self.model.config["access-key"],
                            "MINIO_SECRET_KEY": secret_key,
                        },
                    }
                ],
            }
        )
        self.model.unit.status = ActiveStatus()


if __name__ == "__main__":
    main(Operator)
