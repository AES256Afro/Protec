# Local service credentials and roles

The Access view lets an administrator issue a named credential with a role and a lifetime of 1 to 720 hours. The token is displayed once, and the dialog clears it when closed. The listing returns metadata only, pages 50 at a time, and supports revocation. Use an issued token in the dashboard Access token field or an HTTP Bearer header.

| Role | Permitted operations |
| --- | --- |
| Viewer | Read device/package inventory, job history, and control-plane health |
| Operator | Viewer permissions plus queue inventory refreshes |
| Administrator | Operator permissions plus enrollment/token management, device revocation, audit history, and service credential issuance/revocation |

Roles apply to the whole fleet unless a viewer/operator credential has an explicit device scope. Scoped credentials omit fleet-wide health access. User identity federation, SSO/MFA, rotation with recovery, and OS secret-store integration remain future M3 work.

The server enforces permissions on each HTTP route. Hiding controls in the dashboard is only presentation. Issued service credentials cannot authenticate as device agents or use device heartbeat/completion routes. Device credentials cannot access management routes. Viewer/operator dashboard responses omit audit events; the protected audit, enrollment and access-history routes return 403 to those roles.

## API

- `POST /api/credentials` with `name`, `role`, integer `hours`, and optional `device_ids`: administrator only; returns `id`, `token`, `name`, `role`, and `expires` once.
- `GET /api/credentials`: administrator-only metadata plus `next_cursor`. Supply `cursor` to retrieve older credentials.
- `POST /api/credentials/revoke` with `id`: administrator only. Subsequent requests using that token are rejected. An already authorized in-flight request may finish.
- `GET /api/dashboard`: includes the authenticated identity name, id, role, permissions and device scope. Never includes bearer secrets.

There is no plaintext credential recovery endpoint. If an issuance response is lost, identify and revoke the orphan credential in Access, then issue a replacement. Names are labels, not unique account identifiers; audit events reference the stable credential id. Authorized management actions record that id as actor. Authentication failures are rejected but are not yet recorded as rate-limited security events.

The database stores only SHA-256 digests of random 256-bit service tokens. A database backup includes those digests and credential metadata. Restoring an older backup may restore authorization state from before a revocation, so reapply revocations before restoring access. The browser retains the active login token in memory until lock/reload, and shows newly issued secrets only in the issuance dialog. Secure storage of issued credentials is the operator's responsibility in this release.

## Local administrator compatibility

The existing `.protec/admin-token` remains a separate bootstrap/recovery credential with administrator permissions. It does not expire, is not listed among service credentials, and cannot be revoked by the service-credential endpoint. Its audit actor id is `local-administrator`. File ownership and owner-only permissions remain its protection. Keep it local; use expiring service credentials for narrower access. Replacing the local token file requires restarting the control plane and is not an implemented automatic rotation workflow.

Schema version 2 introduces the credentials table. Upgrade from schema 0 or 1 is transactional and preserves device credentials and inventory. Take a backup and verify a copy before upgrading a live service. None of this makes the loopback development HTTP server suitable for remote production exposure.

## Device-scoped credentials (0.3)

An administrator can issue a viewer or operator credential for the whole fleet or an explicit list of 1 to 100 active device IDs. Choose **Selected devices** in Access, then select the devices before issuance. The selector shows the latest 100 loaded devices; the API accepts active older IDs too. Scope membership is fixed at issuance. Revoke and reissue the credential to change membership. New enrollments are not automatically included.

Send `device_ids: ["DEVICE_ID"]` when creating the credential, or omit it/use null for fleet access. Empty, duplicate, unknown, malformed and revoked-device lists are rejected. Administrator credentials cover the fleet and cannot have a device scope. Only an existing administrator can issue credentials.

The server filters dashboard inventory, jobs, fleet counters and history queries before limiting or paging. Refresh jobs check both the operator permission and the target device ID before insertion. Scoped credentials cannot access fleet health counts, audit, enrollments or credential administration. Device revocation remains an administrator action; previously scoped historical inventory remains visible for those selected records. Scope metadata appears in credential listings, but secret tokens and hashes do not. Corrupt stored scopes fail authentication instead of falling back to fleet access.

Schema 3 adds a nullable scope column. Existing schema-2 credentials retain their fleet scope. Back up before updating; an older image cannot open schema 3. Use a pre-upgrade backup for rollback. SSO/MFA, recoverable rotation, and protected native secret stores remain separate work.
