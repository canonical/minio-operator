#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from random import choices
from string import ascii_uppercase, digits
from base64 import b64encode

from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import (
    NoCompatibleVersions,
    NoVersionsListed,
    get_interfaces,
)


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.log = logging.getLogger()

        self._stored.set_default(secret_key=_gen_pass())

        self.image = OCIImageResource(self, "oci-image")

        for event in [
            self.on.config_changed,
            self.on.install,
            self.on.upgrade_charm,
            self.on["object-storage"].relation_changed,
            self.on["object-storage"].relation_joined,
        ]:
            self.framework.observe(event, self.main)

    def main(self, event):
        try:
            self._check_leader()

            interfaces = self._get_interfaces()

            image_details = self._check_image_details()

            minio_args = self._get_minio_args()

        except CheckFailed as error:
            self.model.unit.status = error.status
            return

        secret_key = self.model.config["secret-key"] or self._stored.secret_key
        self._send_info(interfaces, secret_key)

        self.model.unit.status = MaintenanceStatus("Setting pod spec")
        self.model.pod.set_spec(
            {
                "version": 3,
                "containers": [
                    {
                        "name": "minio",
                        "args": minio_args,
                        "imageDetails": image_details,
                        "ports": [
                            {
                                "name": "minio",
                                "containerPort": int(self.model.config["port"]),
                            },
                            {
                                "name": "console",
                                "containerPort": int(self.model.config["console-port"]),
                            },
                        ],
                        "envConfig": {
                            "minio-secret": {"secret": {"name": "minio-secret"}},
                        },
                    }
                ],
                "kubernetesResources": {
                    "secrets": [
                        {
                            "name": "minio-secret",
                            "type": "Opaque",
                            "data": {
                                k: b64encode(v.encode("utf-8")).decode("utf-8")
                                for k, v in {
                                    "MINIO_ACCESS_KEY": self.model.config["access-key"],
                                    "MINIO_SECRET_KEY": secret_key,
                                }.items()
                            },
                        }
                    ]
                },
            }
        )
        self.model.unit.status = ActiveStatus()

    def _check_leader(self):
        if not self.unit.is_leader():
            self.log.info("Not a leader, skipping set_pod_spec")
            raise CheckFailed("", ActiveStatus)

    def _get_interfaces(self):
        try:
            interfaces = get_interfaces(self)
        except NoVersionsListed as err:
            raise CheckFailed(str(err), WaitingStatus)
        except NoCompatibleVersions as err:
            raise CheckFailed(str(err), BlockedStatus)
        return interfaces

    def _check_image_details(self):
        try:
            image_details = self.image.fetch()
        except OCIImageResourceError as e:
            raise CheckFailed(f"{e.status_message}: oci-image", e.status_type)
        return image_details

    def _send_info(self, interfaces, secret_key):
        if interfaces["object-storage"]:
            interfaces["object-storage"].send_data(
                {
                    "access-key": self.model.config["access-key"],
                    "namespace": self.model.name,
                    "port": self.model.config["port"],
                    "secret-key": secret_key,
                    "secure": False,
                    "service": self.model.app.name,
                }
            )

    def _get_minio_args(self):
        model_mode = self.model.config["mode"]
        if model_mode == "server":
            return self._with_console_address(["server", "/data"])
        elif model_mode == "gateway":
            return self._with_console_address(self._get_minio_args_gateway())
        else:
            error_msg = (
                f"Model mode {model_mode} is not supported. "
                "Possible values server, gateway"
            )
            self.log.error(error_msg)
            raise CheckFailed(error_msg, BlockedStatus)

    def _get_minio_args_gateway(self):
        storage = self.model.config.get("gateway-storage-service")
        if storage:
            self.log.debug(f"Minio args: gateway, {storage}")
            endpoint = self.model.config.get("storage-service-endpoint")
            if endpoint:
                return ["gateway", storage, endpoint]
            else:
                return ["gateway", storage]
        else:
            raise CheckFailed(
                "Minio in gateway mode requires gateway-storage-service "
                "configuration. Possible values: s3, azure",
                BlockedStatus,
            )

    def _with_console_address(self, minio_args):
        console_port = str(self.model.config["console-port"])
        return [*minio_args, "--console-address", ":" + console_port]


def _gen_pass() -> str:
    return "".join(choices(ascii_uppercase + digits, k=30))


class CheckFailed(Exception):
    """ Raise this exception if one of the checks in main fails. """

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = msg
        self.status_type = status_type
        self.status = status_type(msg)


if __name__ == "__main__":
    main(Operator)
