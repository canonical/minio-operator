import dataclasses
import logging
from typing import List

from charmed_kubeflow_chisme.components.pebble_component import PebbleServiceComponent
from ops.pebble import Layer

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
                        "environment": {
                            # To allow public access without authentication for prometheus
                            # metrics set environment as follows.
                            "MINIO_PROMETHEUS_AUTH_TYPE": "public",
                            "MINIO_ROOT_USER": inputs.MINIO_ROOT_USER,
                            "MINIO_ROOT_PASSWORD": inputs.MINIO_ROOT_PASSWORD,
                        },
                    }
                }
            }
        )

        logger.debug("computed layer as:")
        logger.debug(layer.to_dict())

        return layer
