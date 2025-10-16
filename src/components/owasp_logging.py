import logging

from charmed_kubeflow_chisme.components import Component
from ops import ActiveStatus, BoundStoredState, CharmBase, StatusBase
from ops.charm import ConfigChangedEvent
from owasp_logger import OWASPLogger

logger = logging.getLogger(__name__)


class OWASPLoggerComponent(Component):
    def __init__(self, charm: CharmBase, stored: BoundStoredState, name="owasp-logger"):
        super().__init__(charm, name)
        self._charm = charm
        self._owasp_logger = OWASPLogger(appid="minio.owasp-logger")
        self._stored = stored
        self._stored.set_default(last_secret_key_config="")

    def _configure_app_leader(self, event):
        if not isinstance(event, ConfigChangedEvent):
            logger.info("Event is not a config-changed one. Skipping this component.")
            return

        logger.info("Got a config-changed event. Will compare with previous value of secret-key")
        config_secret = self.model.config.get("secret-key")
        stored_secret = self._stored.last_secret_key_config

        if config_secret != stored_secret:
            logger.info("Config value for secret-key has changed! Creating OWASP event.")
            access_key = str(self.model.config.get("access-key"))
            desc = f"The secret-key for access-key '{access_key}' was changed."
            self._owasp_logger.authn_password_change(userid=access_key, description=desc)

        self._stored.last_secret_key_config = config_secret

    def get_status(self) -> StatusBase:
        return ActiveStatus()
