# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Component for interacting with S3-compatible object storage via the s3 interface.

This component uses the provider side of the object-storage charm library.
See: https://github.com/canonical/object-storage-integrator/tree/main/s3
"""

import dataclasses
import logging

from charmed_kubeflow_chisme.components.component import Component
from object_storage import (
    PrematureDataAccessError,
    S3Provider,
    StorageConnectionInfoRequestedEvent,
)
from ops import ActiveStatus, BlockedStatus, RelationBrokenEvent, StatusBase

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class S3ProviderInputs:
    """Defines the required inputs for S3ProviderComponent."""

    ENDPOINT: str
    ACCESS_KEY: str
    SECRET_KEY: str


class S3ProviderComponent(Component):
    """Component that manages an S3-compatible object storage relation.

    ``get_data()`` returns connection info for every related application that has published
    at least some relation data. ``get_status()`` returns Active only when all related
    applications have published all required relation fields.
    """

    def __init__(
        self,
        *args,
        relation_name: str,
        is_optional: bool = False,
        required_relation_fields: frozenset[str] = frozenset({"access-key", "secret-key"}),
        **kwargs,
    ):
        """Initialise the component.

        Args:
            relation_name: Name of the S3 relation endpoint.
            is_optional: When True, the component is Active even if no relation is present.
            required_relation_fields: Set of databag keys that must all be present for a
                relation to be considered fully populated. Defaults to the standard S3
                fields ``{"access-key", "secret-key"}``. See:
                https://github.com/canonical/object-storage-integrator/blob/dcbe3071598e599a7874373e2c93459b14436a94/lib/object_storage/s3.py#L20-L23
        """
        super().__init__(*args, **kwargs)
        self.relation_name = relation_name
        self.is_optional = is_optional
        self.required_relation_fields = required_relation_fields
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
        """Return Active if all related applications have published required data, Blocked if not.

        For optional relations, Active is returned when no relation is present.
        If any related application has not yet published all required relation fields,
        Blocked is returned.
        """
        relations = self._charm.model.relations[self.relation_name]

        if not relations:
            if self.is_optional:
                return ActiveStatus()
            return BlockedStatus(f"Please add the missing relation: {self.relation_name}")

        return ActiveStatus()
