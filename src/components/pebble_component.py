import dataclasses
import logging
from typing import List

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from charmed_kubeflow_chisme.exceptions import GenericCharmRuntimeError
from ops import ActiveStatus, StatusBase, WaitingStatus
from ops.model import ModelError
from ops.pebble import CheckStatus, Layer

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class MinIOInputs:
    """Defines the required inputs for MinIOPebbleService."""

    MINIO_ARGS: List[str]
    MINIO_ROOT_USER: str
    MINIO_ROOT_PASSWORD: str
    MINIO_PORT: int


class MinIOPebbleService(PebbleServiceComponent):
    """Pebble Service for MinIO Container."""

    # Override method
    def get_status(self) -> StatusBase:
        """Returns the status of this Component."""
        if not self.pebble_ready:
            return WaitingStatus("Waiting for Pebble to be ready.")

        try:
            for check_name in ["minio-ready", "minio-alive"]:
                check = self._charm.unit.get_container(self.container_name).get_check(check_name)
                if check != CheckStatus.UP:
                    return WaitingStatus(
                        f"Workload failed health check {check_name}. It will be restarted."
                    )
        except ModelError as error:
            raise GenericCharmRuntimeError(
                "Failed to run health check on workload container"
            ) from error

        return ActiveStatus()

    def get_layer(self) -> Layer:
        """Pebble configuration layer for MinIO.

        This method is required for subclassing PebbleServiceComponent
        """
        try:
            inputs: MinIOInputs = self._inputs_getter()
        except Exception as err:  # pragma: no cover
            raise ValueError("Failed to get inputs for Pebble container.") from err

        layer = Layer(
            {
                "services": {
                    self.service_name: {
                        "override": "replace",
                        "summary": "minio service",
                        "command": f"minio {' '.join(inputs.MINIO_ARGS)}",
                        "startup": "enabled",
                        "on-check-failure": {"minio-ready": "restart", "minio-alive": "restart"},
                        "environment": {
                            # To allow public access without authentication for prometheus
                            # metrics set environment as follows.
                            "MINIO_PROMETHEUS_AUTH_TYPE": "public",
                            "MINIO_ROOT_USER": inputs.MINIO_ROOT_USER,
                            "MINIO_ROOT_PASSWORD": inputs.MINIO_ROOT_PASSWORD,
                        },
                    }
                },
                "checks": {
                    "minio-ready": {
                        "override": "replace",
                        "period": "30s",
                        "level": "ready",
                        "http": {
                            "url": f"http://localhost:{inputs.MINIO_PORT}/minio/health/ready"
                        },
                    },
                    "minio-alive": {
                        "override": "replace",
                        "period": "30s",
                        "level": "alive",
                        "http": {"url": f"http://localhost:{inputs.MINIO_PORT}/minio/health/live"},
                    },
                },
            }
        )

        logger.debug("computed layer as:")
        logger.debug(layer.to_dict())

        return layer
