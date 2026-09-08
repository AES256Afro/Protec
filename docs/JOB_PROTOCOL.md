# Inventory job delivery protocol (0.5)

This first M4 slice applies only to `refresh_inventory`, a repeatable read-only operation. It adds delivery negotiation, attempt-specific leases, a maximum of three deliveries and stored completion receipts. It does not enable package installation, shell commands, configuration writes, VPN changes or other privileged operations.

## Delivery and compatibility

A new agent sends integer `job_protocol: 1` alongside inventory in `POST /api/heartbeat`. The server returns `job_protocol: 1` and versioned job envelopes. A lease includes the target device, job kind, empty payload, attempt number, original creation time, a random one-time delivery token and a deadline 120 seconds after delivery. Only the token hash is stored. Inventory and lease allocation commit together.

Missing `job_protocol` means legacy protocol 0. Older agents continue receiving only `id` and `kind` and can finish their leased inventory refreshes. New agents also support an older server's legacy response, so either side can be upgraded first. Once a job is delivered through protocol 1, it cannot be redelivered or completed through protocol 0. An expired legacy job can move to protocol 1 when a new agent polls. Compatibility is specifically for this read-only job; legacy delivery must not become a path for privileged operations.

Each eligible poll allocates a new attempt and token. Concurrent polls have one winner. Repeated polls during an active lease do not redeliver it. After three deliveries, the next device heartbeat following lease expiry marks the job failed and records `inventory.delivery_exhausted`. The operator can then request a new refresh. An offline device does not trigger background failure processing in this slice.

The agent rejects unsupported versions and kinds, extra payload fields, wrong-device envelopes, malformed tokens, invalid attempts and expired leases before acknowledging them. It rescans package inventory when required and posts that inventory before completion. Only read-only inventory collection can be repeated after an uncertain response. Certificate-verified HTTPS remains the control-plane transport authentication.

## Completion receipts

A protocol-1 completion posts the following to `POST /api/complete` using the device's existing bearer credential:

```json
{
  "job": "JOB_ID",
  "version": 1,
  "attempt": 1,
  "lease_token": "TOKEN_FROM_THIS_DELIVERY",
  "result": {
    "outcome": "succeeded",
    "inventory_sha256": "SHA256_OF_CANONICAL_INVENTORY_JSON"
  }
}
```

Canonical inventory JSON uses sorted keys, compact separators, ASCII escaping, UTF-8 bytes and no non-finite numbers. The server compares the digest to the latest inventory received for that device. A receipt confirms which self-reported inventory was accepted; it does not independently verify the device's security posture or package-query success.

The server checks the job's active device, protocol, current attempt, token hash, deadline and inventory digest in one write transaction. A completion for an expired, superseded, wrong-device or revoked-device lease is rejected. Accepted completion stores a receipt with the job, device, kind, version, attempt, inventory digest and server recording time, together with the audit event. An identical replay returns the existing receipt and `duplicate: true` without creating another audit event. A conflicting replay is rejected. Replay acknowledgement after completion may outlive the lease; it cannot execute or change the recorded result.

Dashboard and paginated job history expose the receipt, delivery count, protocol and requesting actor, but never the lease token or its hash. Historical jobs and legacy-agent completions have no retroactively invented receipt. A lease and its accepted receipt survive control-plane restart. Receipts follow existing job-retention policy; this is not a permanent audit export.

## Upgrade and remaining work

Schema 5 adds job metadata without changing earlier job records. Take a backup and validate a copy before upgrade. Existing running legacy leases remain compatible. An older server cannot open schema 5; rollback requires its pre-upgrade database. Continue using BoxPilot's managed app workflow for the live portal and keep the public mock dashboard matched to the running image.

On the development Mac, restart the existing inventory agent from the updated checkout after verifying the new control plane. Preserve `.protec/agent.json`, its device credential and the HTTPS origin. Verify a newly queued inventory refresh has a protocol-1 receipt; merely seeing a heartbeat does not prove the new job protocol is active.

Remaining M4 work includes independently verifiable job signatures, durable local execution receipts, capability admission for additional job kinds, cancellation, approvals, maintenance windows and side-effect-specific recovery. This milestone does not claim exactly-once execution or a privileged execution framework. Native agent service installation and protected credential storage remain separate milestones.
