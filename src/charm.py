#!/usr/bin/env python3

import logging
from pathlib import Path
from random import choices
from string import ascii_uppercase, digits
from typing import Optional
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus

from oci_image import OCIImageResource, OCIImageResourceError

log = logging.getLogger()


def get_or_set(name: str, *, configured: Optional[str], default: str) -> str:
    if configured:
        Path(f"/run/{name}").write_text(configured)
        return configured

    try:
        path = Path(f"/run/{name}")
        return path.read_text()
    except FileNotFoundError:
        path.write_text(default)
        return default


def gen_pass() -> str:
    return "".join(choices(ascii_uppercase + digits, k=30))


class MinioCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.image = OCIImageResource(self, "oci-image")
        self.framework.observe(self.on.install, self.set_pod_spec)
        self.framework.observe(self.on.upgrade_charm, self.set_pod_spec)
        self.framework.observe(self.on.config_changed, self.set_pod_spec)
        self.framework.observe(self.on.minio_relation_joined, self.send_info)

    def send_info(self, event):
        secret_key = get_or_set("password", default=gen_pass)
        event.relation.data[self.unit]["service"] = self.model.app.name
        event.relation.data[self.unit]["port"] = self.model.config["port"]
        event.relation.data[self.unit]["access-key"] = self.model.config["access-key"]
        event.relation.data[self.unit]["secret-key"] = secret_key

    def set_pod_spec(self, event):
        if not self.model.unit.is_leader():
            log.info("Not a leader, skipping set_pod_spec")
            self.model.unit.status = ActiveStatus()
            return

        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            self.model.unit.status = e.status
            log.info(e)
            return

        secret_key = get_or_set(
            "password",
            configured=self.model.config["secret-key"],
            default=gen_pass(),
        )

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
    main(MinioCharm)
