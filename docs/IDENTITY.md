# Local service credentials and roles

The Access view lets an administrator issue a named credential with a role and a lifetime of 1 to 720 hours. The token is displayed once, and the dialog clears it when closed. The listing returns metadata only, pages 50 at a time, and supports revocation. Use an issued token in the dashboard Access token field or an HTTP Bearer header.

| Role | Permitted operations |
| --- | --- |
| Viewer | Read device/package inventory, job history, and control-plane health |
| Operator | Viewer permissions plus queue inventory refreshes |
| Administrator | Operator permissions plus enrollment/token management, device revocation, audit history, and service credential issuance/revocation |

Roles apply across the entire local fleet. Device-specific scopes, user identity federation, SSO/MFA, rotation with recovery, and OS secret-store integration are not yet implemented. This is the first M3 slice, not completion of M3 or a production identity system.

The server enforces permissions on each HTTP route. Hiding controls in the dashboard is only presentation. Issued service credentials cannot authenticate as device agents or use device heartbeat/completion routes. Device credentials cannot access management routes. Viewer/operator dashboard responses omit audit events; the protected audit, enrollment and access-history routes return 403 to those roles.

## API

- `POST /api/credentials` with `name`, `role`, and integer `hours`: administrator only; returns `id`, `token`, `name`, `role`, and `expires` once.
- `GET /api/credentials`: administrator-only metadata plus `next_cursor`. Supply `cursor` to retrieve older credentials.
- `POST /api/credentials/revoke` with `id`: administrator only. Subsequent requests using that token are rejected. An already authorized in-flight request may finish.
- `GET /api/dashboard`: includes the authenticated identity name, id, role and permissions. Never includes bearer secrets.

There is no plaintext credential recovery endpoint. If an issuance response is lost, identify and revoke the orphan credential in Access, then issue a replacement. Names are labels, not unique account identifiers; audit events reference the stable credential id. Authorized management actions record that id as actor. Authentication failures are rejected but are not yet recorded as rate-limited security events.

The database stores only SHA-256 digests of random 256-bit service tokens. A database backup includes those digests and credential metadata. Restoring an older backup may restore authorization state from before a revocation, so reapply revocations before restoring access. The browser retains the active login token in memory until lock/reload, and shows newly issued secrets only in the issuance dialog. Secure storage of issued credentials is the operator's responsibility in this release.

## Local administrator compatibility

The existing `.protec/admin-token` remains a separate bootstrap/recovery credential with administrator permissions. It does not expire, is not listed among service credentials, and cannot be revoked by the service-credential endpoint. Its audit actor id is `local-administrator`. File ownership and owner-only permissions remain its protection. Keep it local; use expiring service credentials for narrower access. Replacing the local token file requires restarting the control plane and is not an implemented automatic rotation workflow.

Schema version 2 introduces the credentials table. Upgrade from schema 0 or 1 is transactional and preserves device credentials and inventory. Take a backup and verify a copy before upgrading a live service. None of this makes the loopback development HTTP server suitable for remote production exposure.
