# HA Guest Portal

A Home Assistant custom integration for a controlled guest portal. The project is in early development.

## Current status — 0.1.0

This first scaffold provides:

- HACS-compatible custom integration structure
- UI configuration for a Home Assistant zone and presence entities
- Settings for an absence delay, optional notification service and default session duration
- A service to manually toggle the alone-at-home mode:
  - Service: `guest_portal.set_alone_mode`
  - Data: `{"enabled": true}` or `{"enabled": false}`
- An event when the mode changes: `guest_portal_alone_mode_changed`

**Not implemented yet:** guest accounts, guest login, password storage, OTP, admin approval, entity permissions, guest-facing UI, automatic presence evaluation, and additional-device rules. Do not expose this scaffold as a guest login system.

## Installation via HACS

1. Open HACS in Home Assistant.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/fabian9876/ha_guest-portal` as an **Integration**.
4. Install **HA Guest Portal**.
5. Restart Home Assistant.
6. Add **HA Guest Portal** under Settings → Devices & services.

## Manual installation

Copy the `custom_components/guest_portal` directory into the `custom_components` directory of your Home Assistant configuration, then restart Home Assistant.

## Planned roadmap

- [x] 0.1.0 — Integration scaffold and configuration flow
- [ ] 0.2.0 — Guest records and administrator management
- [ ] 0.3.0 — Secure guest authentication, one-time codes and approval workflow
- [ ] 0.4.0 — Server-side entity allowlists and guest dashboard
- [ ] 0.5.0 — Automatic alone-at-home mode with configurable absence delay
- [ ] 0.6.0 — Additional devices and permissions limited to alone mode
- [ ] 1.0.0 — Tests, security review and stable release

## Security principles

- Never put a Home Assistant long-lived access token in browser code.
- Enforce entity permissions on the server for every request; hiding UI controls is not authorization.
- Store passwords using a modern password-hashing scheme, never reversible encryption or plaintext.
- Use short-lived, revocable guest sessions and rate-limit authentication attempts.
- Fail closed if presence state is unknown or unavailable.
- Require HTTPS for remote access and avoid exposing Home Assistant directly to the public internet.

## Development

The integration is intentionally limited to configuration and a manual mode service in this release. Authentication and guest entity access must be implemented and tested before real guests use the system.
