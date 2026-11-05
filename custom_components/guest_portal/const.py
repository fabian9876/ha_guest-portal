"""Constants for HA Guest Portal."""

DOMAIN = "guest_portal"

CONF_PRESENCE_ZONE = "presence_zone"
CONF_PRESENCE_ENTITIES = "presence_entities"
CONF_ABSENCE_DELAY = "absence_delay"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_SESSION_MINUTES = "session_minutes"
CONF_AUTH_MODE = "auth_mode"
CONF_AUTO_ALONE_MODE = "auto_alone_mode"

DEFAULT_ABSENCE_DELAY = 5
DEFAULT_SESSION_MINUTES = 480

SERVICE_SET_ALONE_MODE = "set_alone_mode"
SERVICE_ADD_GUEST = "add_guest"
SERVICE_REMOVE_GUEST = "remove_guest"
SERVICE_SET_GUEST_ENABLED = "set_guest_enabled"
SERVICE_APPROVE_REQUEST = "approve_request"
SERVICE_REVOKE_ALL_SESSIONS = "revoke_all_sessions"
SERVICE_REVOKE_GUEST_SESSIONS = "revoke_guest_sessions"

ATTR_ENABLED = "enabled"
EVENT_ALONE_MODE_CHANGED = "guest_portal_alone_mode_changed"
EVENT_GUEST_REQUEST = "guest_portal_login_requested"
