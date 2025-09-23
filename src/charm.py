#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from base64 import b64encode
from hashlib import sha256
from random import choices
from string import ascii_uppercase, digits

from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from oci_image import OCIImageResource, OCIImageResourceError
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from serialized_data_interface import NoCompatibleVersions, NoVersionsListed, get_interfaces


class Operator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self.log = logging.getLogger()

        # Random salt used for hashing config
        self._stored.set_default(hash_salt=_gen_pass())

        self._minio_service_name = self.app.name

        self.image = OCIImageResource(self, "oci-image")

        self.prometheus_provider = MetricsEndpointProvider(
            charm=self,
            jobs=[
                {
                    "job_name": "minio_metrics",
                    "scrape_interval": "30s",
                    "metrics_path": "/minio/v2/metrics/cluster",
                    "static_configs": [{"targets": ["*:{}".format(self.config["port"])]}],
                }
            ],
        )
        self.dashboard_provider = GrafanaDashboardProvider(self)

        for event in [
            self.on.config_changed,
            self.on.install,
            self.on.upgrade_charm,
            self.on.update_status,
            self.on.leader_elected,
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

        secret_key = self._get_secret_key()

        if len(secret_key) < 8:
            self.model.unit.status = BlockedStatus(
                "The `secret-key` config value must be at least 8 characters long."
            )
            return

        self._send_info(interfaces, secret_key)

        configmap_hash = self._generate_config_hash()

        self.model.unit.status = MaintenanceStatus("Setting pod spec")

        spec = {
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
                        "minio-secret": {"secret": {"name": f"{self.model.app.name}-secret"}},
                        # This hash forces a restart for pods whenever we change the config.
                        # This would ideally be a spec.template.metadata.annotation rather
                        # than an environment variable, but we cannot use that using podspec.
                        # (see https://stackoverflow.com/questions/37317003/restart-pods-when-configmap-updates-in-kubernetes/51421527#51421527)  # noqa E403
                        "configmap-hash": configmap_hash,
                        # To allow public access without authentication for prometheus
                        # metrics set environment as follows.
                        "MINIO_PROMETHEUS_AUTH_TYPE": "public",
                    },
                    "volumeConfig": [
                        {
                            "name": "ssl-ca",
                            "mountPath": "/minio/.minio/certs/CAs",
                            "emptyDir": {},
                        },
                    ],
                }
            ],
            "kubernetesResources": {
                "secrets": [
                    {
                        "name": f"{self.model.app.name}-secret",
                        "type": "Opaque",
                        "data": {
                            k: b64encode(v.encode("utf-8")).decode("utf-8")
                            for k, v in {
                                "MINIO_ACCESS_KEY": self.model.config["access-key"],
                                "MINIO_SECRET_KEY": secret_key,
                                # Needed to ensure the Pod won't accidentally assume
                                # other IAM credentials (relevant for gateway mode on EKS only)
                                # https://github.com/canonical/kfp-operators/issues/785
                                "AWS_ACCESS_KEY_ID": self.model.config["access-key"],
                                "AWS_SECRET_ACCESS_KEY": secret_key,
                            }.items()
                        },
                    },
                ]
            },
        }

        self.model.unit.status = MaintenanceStatus("Checking for SSL secret.")
        if self._has_ssl_config():
            spec["containers"][0]["volumeConfig"].append(self._get_ssl_volume_config())
            spec["kubernetesResources"]["secrets"].append(self._get_ssl_secret())
        else:
            self.log.info("SSL: No secret specified in charm config. Proceeding without SSL.")

        self.model.pod.set_spec(spec)
        self.model.unit.status = ActiveStatus()

    def _check_leader(self):
        if not self.unit.is_leader():
            self.log.info("Not a leader, skipping set_pod_spec")
            raise CheckFailed("Waiting for leadership", WaitingStatus)

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
            self.log.error(f"Failed to fetch oci-image with: {e.status_message}")
            raise CheckFailed(f"{e.status_message}: oci-image", WaitingStatus)
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
                    "service": self._minio_service_name,
                }
            )

    def _generate_config_hash(self):
        """Returns a hash of the current config state"""
        # Add a randomly generated salt to the config to make it hard to reverse engineer the
        # secret-key from the password.
        salt = self._stored.hash_salt
        all_config = tuple(
            str(self.model.config[name]) for name in sorted(self.model.config.keys())
        ) + (salt,)
        config_hash = sha256(".".join(all_config).encode("utf-8"))
        return config_hash.hexdigest()

    def _get_minio_args(self):
        model_mode = self.model.config["mode"]
        if model_mode == "server":
            return self._with_console_address(
                ["server", "/data", "--certs-dir", "/minio/.minio/certs"]
            )
        elif model_mode == "gateway":
            return self._with_console_address(self._get_minio_args_gateway())
        else:
            error_msg = (
                f"Model mode {model_mode} is not supported. " "Possible values server, gateway"
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

    def _get_secret_key(self):
        """Returns the secret key set by config, else returns the randomly generated secret"""
        config_secret = self.model.config["secret-key"]
        if config_secret != "":
            # Use secret specified in config
            secret = config_secret
        else:
            try:
                # Try to use a randomly generated default key from the past
                secret = self._stored.secret_key
            except AttributeError:
                # Create and store a randomly generated default key to reuse in future
                secret = _gen_pass()
                self._stored.set_default(secret_key=secret)

        return secret

    def _with_console_address(self, minio_args):
        console_port = str(self.model.config["console-port"])
        return [*minio_args, "--console-address", ":" + console_port]

    def _get_ssl_volume_config(self):
        files = [
            {
                "path": "private.key",
                "key": "PRIVATE_KEY",
            },
            {
                "path": "public.crt",
                "key": "PUBLIC_CRT",
            },
        ]
        if self.model.config["ssl-ca"] != "":
            files.append({"path": "CAs/root.cert", "key": "ROOT_CERT"})
        return {
            "name": "minio-ssl",
            "mountPath": "/minio/.minio/certs/",
            "secret": {
                "name": "minio-ssl",
                "defaultMode": 511,
                "files": files,
            },
        }

    def _get_ssl_secret(self):
        data = {
            "PRIVATE_KEY": self.model.config["ssl-key"],
            "PUBLIC_CRT": self.model.config["ssl-cert"],
        }
        if self.model.config["ssl-ca"] != "":
            data["ROOT_CERT"] = self.model.config["ssl-ca"]
        return {
            "name": "minio-ssl",
            "type": "Opaque",
            "data": data,
        }

    def _has_ssl_config(self):
        return self.model.config["ssl-key"] != "" and self.model.config["ssl-cert"] != ""


def _gen_pass() -> str:
    return "".join(choices(ascii_uppercase + digits, k=30))


class CheckFailed(Exception):
    """Raise this exception if one of the checks in main fails."""

    def __init__(self, msg, status_type=None):
        super().__init__()

        self.msg = str(msg)
        self.status_type = status_type
        self.status = status_type(self.msg)


if __name__ == "__main__":
    main(Operator)
