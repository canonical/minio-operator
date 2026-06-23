# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Component for interacting with S3-compatible object storage via the s3 interface.

This component uses the S3Provider interface, provided by the object-storage-charmlib library.
See: https://github.com/canonical/object-storage-integrator/tree/main/s3
"""

import dataclasses
import logging

from charmed_kubeflow_chisme.components import Component
from object_storage import (
    PrematureDataAccessError,
    S3Provider,
    StorageConnectionInfoRequestedEvent,
)
from ops import ActiveStatus, BlockedStatus, StatusBase, WaitingStatus

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class S3ProviderInputs:
    """Defines the required inputs for S3ProviderComponent."""

    ENDPOINT: str
    ACCESS_KEY: str
    SECRET_KEY: str


class S3ProviderComponent(Component):
    """Component that manages an S3-compatible object storage relation.

    Publishes endpoint and credentials to related requirers using the `s3` interface.
    """

    def __init__(
        self,
        *args,
        relation_name: str,
        is_optional: bool = False,
        **kwargs,
    ):
        """Initialise the component.

        Args:
            relation_name: Name of the S3 relation endpoint.
            is_optional: When True, the component is Active even if no relation is present.
        """
        super().__init__(*args, **kwargs)
        self.relation_name = relation_name
        self.is_optional = is_optional
        self.s3_provider = S3Provider(
            charm=self._charm,
            relation_name=relation_name,
        )
        self._events_to_observe = [
            self._charm.on[self.relation_name].relation_changed,
            self._charm.on[self.relation_name].relation_broken,
            self.s3_provider.on.storage_connection_info_requested,
        ]

    def _configure_unit(self, event):
        """Execute everything this Component should do for every Unit."""
        if not self._charm.unit.is_leader():
            return

        inputs: S3ProviderInputs = self._inputs_getter()
        data = {
            "endpoint": inputs.ENDPOINT,
            "access-key": inputs.ACCESS_KEY,
            "secret-key": inputs.SECRET_KEY,
        }

        if isinstance(event, StorageConnectionInfoRequestedEvent):
            relation_ids = [event.relation.id]
        else:
            relation_ids = list(self.s3_provider.fetch_relation_data().keys())

        for relation_id in relation_ids:
            try:
                self.s3_provider.set_storage_connection_info(relation_id=relation_id, data=data)
            except PrematureDataAccessError:
                logger.warning("Relation %s not yet initialised, skipping.", relation_id)

    def get_status(self) -> StatusBase:
        """Return the status of this component.

        - Blocked: no relation present and component is not optional.
        - Active: no relation present and component is optional.
        - Waiting: relation is present but no requirer has initialised the protocol yet.
        - Active: at least one relation is fully initialised.
        """
        relations = self._charm.model.relations[self.relation_name]

        if not relations:
            if self.is_optional:
                return ActiveStatus()
            return BlockedStatus(f"Please add the missing relation: {self.relation_name}")

        if not any(self.s3_provider.is_protocol_ready(relation) for relation in relations):
            return WaitingStatus(f"Waiting for {self.relation_name} relation to be initialised")

        return ActiveStatus()
