"""Constants for the HA Guest Portal integration."""

DOMAIN = "guest_portal"

CONF_PRESENCE_ZONE = "presence_zone"
CONF_PRESENCE_ENTITIES = "presence_entities"
CONF_ABSENCE_DELAY = "absence_delay"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_SESSION_MINUTES = "session_minutes"

DEFAULT_ABSENCE_DELAY = 5
DEFAULT_SESSION_MINUTES = 480

SERVICE_SET_ALONE_MODE = "set_alone_mode"
ATTR_ENABLED = "enabled"

EVENT_ALONE_MODE_CHANGED = "guest_portal_alone_mode_changed"
