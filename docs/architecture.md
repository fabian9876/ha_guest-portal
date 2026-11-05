# Central guest access architecture

## Goal

The guest dashboard is a client of a central guest management service. It is
not the place where authorization decisions are made.

## Trust boundaries

- Home Assistant remains the identity provider for administrators. Management
  endpoints and services require an authenticated HA administrator.
- Guest Portal identities are separate integration identities. Password hashes,
  enabled state and entity allowlists are stored by the integration.
- Guest sessions are integration-issued bearer sessions. Disabling or deleting
  a guest revokes active sessions.
- Every guest entity read and control request is authorized on the server.
  Hiding a card or button in the browser is never authorization.
- The policy manager governs only routes implemented by this integration. It
  does not restrict native HA frontend, mobile app, WebSocket API, REST API or
  other integrations.

## Components

| Layer | Responsibility |
| --- | --- |
| Admin control plane | HA-admin-only guest CRUD, approval and policy configuration |
| Identity/session | Password verification, OTP/approval, expiry and revocation |
| Policy decision point | Effective read/control allowlists, alone-mode additions, access decisions |
| Adapters | Guest HTTP API, guest portal, admin panel and HA services |
| Persistence | HA Store holds guest records and password hashes; sessions/challenges are runtime-only |
| Audit | guest_portal_access_decision event contains guest, entity, operation and decision; never credentials or tokens |

## Policy model

- read_entities: entities whose state can be returned.
- write_entities: entities the guest can control.
- alone_entities: extra readable entities while alone mode is active.
- alone_write_entities: extra controllable entities while alone mode is active.

The central policy manager calculates effective permissions and authorizes
integration-managed reads and controls. The existing domain/service allowlist
still applies to control requests. Read permission never implies control
permission. Unknown permissions are denied.

## Runtime lifecycle

1. The integration loads the persisted guest store at config-entry setup.
2. It creates one GuestAccessManager shared by guest API handlers.
3. Login verifies the guest password and applies OTP or administrator approval.
4. Each guest API request resolves its session, checks enabled state and asks
   the central policy manager before returning state or calling an HA service.
5. Disabling or deleting a guest revokes active sessions. Unloading the config
   entry removes integration panels and runtime state.

## Meaning of “system-wide”

The central service is authoritative for every guest access path exposed by
this integration. It is not a replacement for Home Assistant's native user
and permission system. A custom integration has no general supported hook to
transparently filter every native frontend, REST, WebSocket and mobile-app
request by entity. We must not imply that a person is globally restricted if
they also have an unrestricted native HA account or token.

For an isolated guest experience, guests must use only the Guest Portal routes
and must not receive an unrestricted HA account or long-lived HA token.

## Next implementation stages

1. Move guest CRUD, session revocation, approval and audit persistence behind
   manager methods instead of allowing HTTP handlers to mutate runtime dicts.
2. Add guest groups, reusable policy profiles, access schedules and expiry.
3. Add an admin overview for active sessions, pending approvals, recent access
   decisions and emergency revoke-all.
4. Add tests for denied reads/controls, disabled guests, alone-mode additions,
   expired sessions and revocation.
5. Evaluate native HA identity integration separately; never claim full native
   API enforcement without a supported HA hook and integration tests.

## Security requirements

- Never log plaintext passwords, session tokens or OTP values.
- Keep authorization deny-by-default.
- Unknown/unavailable presence must not grant alone-mode permissions.
- All authorization decisions remain server-side.
