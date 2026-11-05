# Central guest access architecture

## Goal

HA Guest Portal is moving from a dashboard-centred design to a central guest
management service. The dashboard is a client of that service; it is not the
place where permissions are decided.

## Trust boundaries

- Home Assistant remains the identity provider for administrators. Management
  endpoints and services require an authenticated HA administrator.
- Guest Portal guest identities are separate integration identities. Their
  password hashes, enabled state and allowlists are stored by the integration.
- Guest sessions are short-lived bearer sessions issued by the integration.
  Disabling or deleting a guest revokes its active sessions.
- Every guest entity read and control request is checked on the server. Hiding
  a card or button in the browser is never treated as authorization.
- The policy manager governs only routes and services implemented by this
  integration. It does **not** restrict a normal Home Assistant user's native
  frontend, mobile app, WebSocket API, REST API, or other integrations.

## Components

| Layer | Responsibility |
| --- | --- |
| Admin control plane | HA-admin-only guest creation, editing, disable/delete, approval and policy configuration |
| Identity and session layer | Guest password verification, OTP/approval flow, session expiry and revocation |
| Central policy decision point | Computes effective read/control allowlists, applies alone-mode additions, records allow/deny decisions |
| Integration adapters | Guest HTTP API, guest web portal, admin panel and HA services |
| Persistence | HA Store holds guest records and password hashes; runtime sessions and pending challenges remain in memory |
| Audit events | guest_portal_access_decision reports guest, entity, operation and decision without credentials or tokens |

## Policy model

Each guest has four explicit entity lists:

- read_entities: entities whose state can be returned.
- write_entities: entities that can be controlled.
- alone_entities: additional readable entities while alone mode is active.
- alone_write_entities: additional controllable entities while alone mode is active.

The central policy manager calculates the effective lists and makes the final
decision for each integration-managed read or control request. Control requests
also retain the existing domain/service allowlist. An entity being readable
does not imply that it is controllable.

## Runtime lifecycle

1. The integration loads the single persisted guest store during config-entry setup.
2. It creates one GuestAccessManager and shares it with the guest API runtime.
3. Guest login verifies the password and applies the configured OTP or approval
   flow before issuing a session.
4. Each guest API request resolves the session, checks that the guest is still
   enabled, and asks the policy manager before returning state or calling an HA
   service.
5. Disabling or deleting a guest revokes active sessions. Unloading the config
   entry removes the integration panels and runtime state.

## What “system-wide” means — and does not mean

The central service is the single authority for **all guest access paths that
this integration itself exposes**. It is not a replacement for Home Assistant's
native user and permission system. Home Assistant does not expose a general
supported per-entity permission hook that lets a custom integration transparently
filter every native frontend, REST, WebSocket and mobile-app request. Therefore
this integration must not create the impression that a guest is globally
restricted if that person also has an unrestricted native HA account or token.

For a genuinely isolated guest experience, guests must use the Guest Portal
entry points and must not be given a separate unrestricted Home Assistant
account or long-lived HA token. Administrators continue to use normal HA
accounts.

## Next implementation stages

1. Move guest CRUD, session revocation, approval and audit persistence behind
   manager methods rather than letting HTTP handlers mutate runtime dictionaries.
2. Add explicit guest groups/roles and reusable policy profiles.
3. Add time windows, expiry dates, schedules and per-guest session limits.
4. Add a central admin overview for active sessions, pending approvals, recent
   access decisions and emergency revoke-all.
5. Add tests for denied reads, denied controls, disabled guests, alone-mode
   additions, expired sessions and session revocation.
6. Evaluate supported HA-native identity integration separately; do not claim
   full native API enforcement unless Home Assistant provides a supported hook
   and it is covered by integration tests.

## Security notes

- Never store plaintext passwords, session tokens or OTP values in the audit log.
- Keep the default policy deny-by-default: an entity absent from an allowlist is
  not available to a guest.
- Treat unavailable presence data as not-alone; do not grant alone-mode access
  when presence cannot be determined.
- Keep all permission checks on the server, independent of the frontend.
