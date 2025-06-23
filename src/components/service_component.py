import logging
from typing import List

from charmed_kubeflow_chisme.components import Component
from lightkube import Client
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from lightkube.types import PatchType
from ops import ActiveStatus, BlockedStatus, CharmBase, StatusBase

logger = logging.getLogger(__name__)


class KubernetesServicePatchComponent(Component):
    """Kubernetes Service Patch Component."""

    def __init__(
        self,
        charm: CharmBase,
        name: str,
        ports: List[ServicePort],
    ):
        """Initialize the KubernetesServiceComponent."""
        super().__init__(charm=charm, name=name)
        self._charm = charm
        self._lightkube_client = Client()
        self._service_name = self._charm.app.name
        self._service_object = self._get_service_object(
            service_name=self._service_name,
            ports=ports,
            namespace=self._charm.model.name,
            app_name=self._charm.app.name,
        )

    def _configure_app_leader(self, event):
        """Execute everything this Component should do at the Application level for leaders."""
        logger.info("Checking if K8s Service needs to be updated.")
        if self._is_patched():
            logger.info("K8s Service %s is already patched, skipping", self._service_name)
            return

        logger.info("K8s Service %s is not patched, applying patch", self._service_name)
        self._lightkube_client.patch(
            Service, self._service_name, self._service_object, patch_type=PatchType.MERGE
        )

    def get_status(self) -> StatusBase:
        """Returns the status of this Component."""
        logger.info("Checking the status of the Kubernetes Service Patch Component.")
        if not self._is_patched():
            return BlockedStatus("K8s Service was not patched correctly. Check logs for details.")

        return ActiveStatus()

    def _is_patched(self) -> bool:
        """Check if the service is already patched."""
        fetched_service_object = self._lightkube_client.get(
            Service, name=self._service_name, namespace=self._charm.model.name
        )
        expected_ports = [(p.port, p.targetPort) for p in self._service_object.spec.ports]
        fetched_ports = [(p.port, p.targetPort) for p in fetched_service_object.spec.ports]
        return expected_ports == fetched_ports

    def _get_service_object(
        self, service_name: str, ports: List[ServicePort], namespace: str, app_name: str
    ) -> Service:
        """Creates a valid Service representation.

        Args:
            service_name (str): The name of the service.
            ports (List[ServicePort]): A list of ServicePort objects defining the service ports.
            namespace (str): The namespace in which the service will be created.
            app_name (str): The name of the application to which this service belongs.
        Returns:
            Service: A valid representation of a Kubernetes Service with the correct ports.
        """
        for port in ports:
            port.targetPort = port.targetPort or port.port

        return Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace=namespace,
                name=service_name,
                labels={"app.kubernetes.io/name": app_name},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": app_name},
                ports=ports,
                type="ClusterIP",
            ),
        )
