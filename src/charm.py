#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from random import choices
from string import ascii_uppercase, digits
from typing import List, Optional

from charmed_kubeflow_chisme.components import (
    CharmReconciler,
    LazyContainerFileTemplate,
    LeadershipGateComponent,
    SdiRelationBroadcasterComponent,
)
from charmed_kubeflow_chisme.exceptions import ErrorWithStatus
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from charms.velero_libs.v0.velero_backup_config import VeleroBackupProvider, VeleroBackupSpec
from lightkube.models.core_v1 import ServicePort
from ops import BlockedStatus, CharmBase, StoredState, main

from components.owasp_logging import OWASPLoggerComponent
from components.pebble_component import MinIOInputs, MinIOPebbleService
from components.service_component import KubernetesServicePatchComponent

logger = logging.getLogger(__name__)


class MinIOOperator(CharmBase):
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        try:
            minio_args = self._get_minio_args()
            secret_key = self._get_secret_key()
        except ErrorWithStatus as e:
            self.unit.status = e.status
            return

        self.model.unit.set_ports(
            int(self.model.config["port"]),
            int(self.model.config["console-port"]),
        )

        self.charm_reconciler = CharmReconciler(self)

        self.leadership_gate = self.charm_reconciler.add(
            component=LeadershipGateComponent(
                charm=self,
                name="leadership-gate",
            ),
            depends_on=[],
        )

        self.owasp_logger = self.charm_reconciler.add(
            component=OWASPLoggerComponent(charm=self, stored=self._stored),
            depends_on=[self.leadership_gate],
        )

        self.service_patcher = self.charm_reconciler.add(
            component=KubernetesServicePatchComponent(
                charm=self,
                name="kubernetes-service-patch",
                ports=[
                    ServicePort(int(self.model.config["port"]), name="minio"),
                    ServicePort(int(self.model.config["console-port"]), name="minio-console"),
                ],
            ),
            depends_on=[self.leadership_gate],
        )

        self.object_storage_relation = self.charm_reconciler.add(
            component=SdiRelationBroadcasterComponent(
                charm=self,
                name="relation:object_storage",
                relation_name="object-storage",
                data_to_send={
                    "port": self.model.config["port"],
                    "secure": False,
                    "access-key": self.model.config["access-key"],
                    "secret-key": secret_key,
                    "namespace": self.model.name,
                    "service": self.model.app.name,
                },
            ),
            depends_on=[self.leadership_gate, self.service_patcher],
        )

        self.minio_container = self.charm_reconciler.add(
            component=MinIOPebbleService(
                charm=self,
                name="container:minio",
                container_name="minio",
                service_name="minio",
                files_to_push=self._get_files_to_push(),
                inputs_getter=lambda: MinIOInputs(
                    MINIO_ARGS=minio_args,
                    MINIO_ROOT_USER=self.model.config["access-key"],
                    MINIO_ROOT_PASSWORD=secret_key,
                    MINIO_PORT=int(self.model.config["port"]),
                ),
            ),
            depends_on=[
                self.leadership_gate,
                self.service_patcher,
                self.object_storage_relation,
            ],
        )

        self.prometheus_provider = MetricsEndpointProvider(
            charm=self,
            jobs=[
                {
                    "job_name": "minio_metrics",
                    "scrape_interval": "30s",
                    "metrics_path": "/minio/v2/metrics/cluster",
                    "static_configs": [{"targets": [f"*:{self.model.config['port']}"]}],
                }
            ],
        )
        self.velero_backup_config = VeleroBackupProvider(
            charm=self,
            relation_name="velero-backup-config",
            spec=VeleroBackupSpec(
                include_namespaces=[self.model.name],
                include_resources=["persistentvolumeclaims", "persistentvolumes"],
                label_selector={
                    "app.kubernetes.io/name": self.app.name,
                },
            ),
        )
        self.dashboard_provider = GrafanaDashboardProvider(self)

        self.charm_reconciler.install_default_event_handlers()

    def _get_minio_args(self) -> List[str]:
        """
        Build command line arguments for MinIO based on configuration mode.

        Returns:
            List[str]: Command line arguments for MinIO

        Raises:
            ErrorWithStatus: If mode is invalid or required configurations are missing
        """
        model_mode = self.model.config.get("mode")

        if model_mode == "server":
            return self._with_console_address(
                ["server", "/data", "--certs-dir", "/minio/.minio/certs"]
            )
        elif model_mode == "gateway":
            return self._with_console_address(self._get_minio_args_gateway())

        error_msg = f"Invalid mode '{model_mode}'. Supported values: 'server', 'gateway'"
        logger.error(error_msg)
        raise ErrorWithStatus(error_msg, BlockedStatus)

    def _with_console_address(self, minio_args: List[str]) -> List[str]:
        """
        Append console address configuration to MinIO arguments.

        Args:
            minio_args (List[str]): Existing MinIO command line arguments

        Returns:
            List[str]: Updated command line arguments with console address
        """
        console_port = self.model.config["console-port"]
        return [*minio_args, "--console-address", f":{console_port}"]

    def _get_minio_args_gateway(self) -> List[str]:
        """
        Build command line arguments for MinIO in gateway mode.

        Returns:
            List[str]: Command line arguments for MinIO in gateway mode

        Raises:
            ErrorWithStatus: If required gateway configuration is missing
        """
        storage = self.model.config.get("gateway-storage-service")
        if not storage and storage not in ["s3", "azure"]:
            raise ErrorWithStatus(
                "MinIO gateway mode requires 'gateway-storage-service' configuration. "
                "Supported values: 's3', 'azure'",
                BlockedStatus,
            )

        logger.debug(f"MinIO gateway mode configured for: {storage}")
        endpoint = self.model.config.get("storage-service-endpoint")

        if endpoint:
            return ["gateway", storage, endpoint]
        return ["gateway", storage]

    def _get_secret_key(self) -> str:
        """
        Get the secret key for MinIO from the model configuration or stored state.
        Returns:
            str: The secret key to be used by MinIO
        Raises:
            ErrorWithStatus: If the secret key is too short
        """
        config_secret = self.model.config.get("secret-key")
        if config_secret:
            if len(config_secret) < 8:
                raise ErrorWithStatus(
                    "The 'secret-key' config value must be at least 8 characters long.",
                    BlockedStatus,
                )
            secret = config_secret
        else:
            try:
                secret = self._stored.secret_key
                logger.info("Using existing secret key from stored state.")
            except AttributeError:
                logger.debug("No secret key provided in config, generating a new one.")
                secret = "".join(choices(ascii_uppercase + digits, k=30))
                self._stored.set_default(secret_key=secret)

        return secret

    def _get_files_to_push(self) -> Optional[List[LazyContainerFileTemplate]]:
        """
        Get the list of files to push to the MinIO container.
        This includes SSL certificate files if configured for MinIO to use secure connections.

        Returns:
            List[ContainerFileTemplate]: List of files to be pushed
        """
        files: LazyContainerFileTemplate = []
        if self.model.config.get("ssl-key") and self.model.config.get("ssl-cert"):
            ssl_config = [
                LazyContainerFileTemplate(
                    source_template=self.model.config["ssl-key"],
                    destination_path="/minio/.minio/certs/private.key",
                    permissions=0o511,
                ),
                LazyContainerFileTemplate(
                    source_template=self.model.config["ssl-cert"],
                    destination_path="/minio/.minio/certs/public.crt",
                    permissions=0o511,
                ),
            ]
            if self.model.config.get("ssl-ca"):
                ssl_config.append(
                    LazyContainerFileTemplate(
                        source_template=self.model.config["ssl-ca"],
                        destination_path="/minio/.minio/certs/CAs/root.cert",
                        permissions=0o511,
                    )
                )
            logger.info("SSL configuration provided, pushing SSL files to MinIO container.")
            files.extend(ssl_config)
        logger.info("No SSL configuration provided, skipping file push.")
        return files if files else None


if __name__ == "__main__":  # pragma: nocover
    main(MinIOOperator)
