# HA Guest Portal

A Home Assistant custom integration for a controlled guest portal. Version 0.4.0 adds native sidebar entries for the guest portal and administrator dashboard.

## Zentrale Gastverwaltung

Alle von dieser Integration angebotenen Gastzugriffe laufen über einen zentralen
Policy-Entscheidungspunkt. Lese- und Steuerrechte werden serverseitig geprüft;
Zugriffsentscheidungen werden als Home-Assistant-Event
`guest_portal_access_decision` veröffentlicht.

Die Admin-Oberfläche zeigt außerdem aktive Sitzungen und letzte Zugriffsereignisse.
Administratoren können einzelne Sitzungen, alle Sitzungen eines Gastes oder
sämtliche Gastsitzungen beenden. Gastkonten unterstützen optionale Ablaufdaten,
Kategorien und wiederverwendbare Berechtigungsprofile.

**Systemgrenze:** Das filtert nicht die native Home-Assistant-Oberfläche,
REST-/WebSocket-API oder Companion-App. Gäste dürfen deshalb keinen
uneingeschränkten HA-Account oder dauerhaften HA-Token erhalten und müssen
ausschließlich die Gastzugänge dieser Integration verwenden.

Details: [Architekturdokumentation](docs/architecture.md).

## Features in 0.4.0

- HACS custom integration and Home Assistant config/options flow.
- Guest accounts persisted in Home Assistant storage. Passwords are hashed with PBKDF2-HMAC-SHA256 (310,000 iterations); plaintext passwords are not stored.
- Login with either administrator approval or a one-time six-digit code.
- Short-lived bearer sessions; sessions are kept in memory and are revoked on logout, account disable/removal or integration reload.
- Rate limiting of login attempts by client IP.
- Server-side read and write allowlists. The browser cannot request arbitrary entity states or arbitrary Home Assistant services.
- Extra read/write entities can be assigned to a guest and become available only while alone mode is active.
- Optional automatic alone mode from configured person/device_tracker entities, with an absence delay. Unknown/unavailable presence fails closed.
- **Gäste** sidebar panel with the integration's separate guest login and restricted portal.
- **Gastverwaltung** sidebar panel, visible only to Home Assistant administrators.
- Direct routes `/guest-portal` and `/guest-portal/admin` remain available.

## Installation via HACS

1. Open HACS → Integrations → three-dot menu → Custom repositories.
2. Add `https://github.com/fabian9876/ha_guest-portal` as an **Integration**.
3. Install **HA Guest Portal**, restart Home Assistant and add the integration under Settings → Devices & services.
4. Configure the home zone, monitored people/devices, authentication mode and notification service.

## Sidebar access and guest accounts

After the integration is configured, Home Assistant registers two sidebar entries:

- **Gäste** is available to signed-in Home Assistant users. It opens the guest login page. Guests sign in there with the separate username/password created in this integration, then see only the entities allowed for that guest.
- **Gastverwaltung** is restricted to Home Assistant administrators and opens the management dashboard.

**Important authentication boundary:** Home Assistant requires a Home Assistant frontend login before anyone can see its sidebar. The integration's guest username/password is a separate login inside the Gäste panel; it does not replace the initial Home Assistant login or create a restricted Home Assistant user. A guest using the sidebar therefore still needs a Home Assistant account to enter the frontend. Hiding other sidebar entries does not reduce the permissions of that Home Assistant account.

If guests must not receive Home Assistant accounts, use the standalone `/guest-portal` route instead of the sidebar panel, and do not expose the Home Assistant administration interface to guests.

## Managing guests

Use Home Assistant's Developer Tools → Actions (older versions: Services). The management services require an authenticated Home Assistant administrator.

### Create a guest

Action: `guest_portal.add_guest`

```yaml
username: Alex
guest_id: alex
password: "use-a-unique-password-at-least-12-chars"
read_entities:
  - light.living_room
  - sensor.living_room_temperature
write_entities:
  - light.living_room
alone_entities:
  - switch.office_socket
alone_write_entities:
  - switch.office_socket
```

The guest can always read `read_entities` and control only `write_entities`. The extra `alone_entities` and `alone_write_entities` are added only while alone mode is active. A guest ID may contain letters, numbers, underscore and hyphen.

### Approve a login

In approval mode, a login notification contains a request ID. Approve or reject it with:

```yaml
action: guest_portal.approve_request
data:
  request_id: "REQUEST_ID_FROM_NOTIFICATION"
  approved: true
```

Set `approved: false` to reject. The request expires after 10 minutes.

### Other management actions

- `guest_portal.remove_guest`: `guest_id`
- `guest_portal.set_guest_enabled`: `guest_id`, `enabled`
- `guest_portal.set_alone_mode`: `enabled`

Disabling/removing a guest revokes their active sessions.

## Authentication modes

- **Administrator approval:** correct password creates a pending request. An administrator must approve it in Home Assistant.
- **One-time code:** correct password triggers a six-digit code through the configured Home Assistant notify service. The guest enters that code on the portal page. Configure a notification destination that the guest can actually receive, or use an administrator-controlled relay.

The OTP is valid for five minutes. Approval requests expire after ten minutes. Sessions expire according to the configured duration.

## Guest controls

The portal page is available at `/guest-portal` on the same Home Assistant host. It shows only explicitly allowed entities. In this version the supported controls are on/off/toggle for light, switch and fan entities (and the restricted Home Assistant generic turn_on/turn_off/toggle services). Lock, alarm, cover, climate and arbitrary service calls are deliberately not exposed.

## Security notes and limitations

- Do not expose Home Assistant directly to the public internet. Use a trusted HTTPS reverse proxy or Home Assistant Cloud.
- The portal does not implement its own TLS. HTTPS must be provided by the Home Assistant deployment.
- The login API is unauthenticated by design; use HTTPS and network-level protections.
- OTP delivery depends on the configured notify service being correctly targeted.
- Guest sessions and pending approval/challenge state are in memory; a Home Assistant restart logs guests out and clears pending requests.
- The guest and administrator sidebar entries wrap the existing portal pages. The administrator panel is hidden from non-admin Home Assistant users, and its API independently checks administrator status.
- The integration has not yet been tested against your specific Home Assistant version or hardware. Review the code and test with non-critical entities before use.

## Roadmap

- [x] 0.1.0 — HACS scaffold and configuration flow
- [x] 0.2.0 — Guest records, authentication, approvals/OTP and server-side allowlists
- [x] 0.3.0 — Initial visual administrator dashboard
- [ ] 0.4.0 — Audit log, automated integration tests and security review
- [ ] 1.0.0 — Stable release
