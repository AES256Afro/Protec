# Inventory capability admission (0.6)

Version 0.6 adds a bounded capability report to agent heartbeats. This is a compatibility check for dispatching read-only inventory refreshes. It is not device attestation, an operator permission, proof of administrator privileges or approval to execute privileged jobs. It is not in the published 0.5.0 image.

## Heartbeat contract

The command-line agent sends this alongside `inventory` and `job_protocol: 1` on every heartbeat, including a forced inventory refresh:

```json
{
  "job_capabilities": {
    "version": 1,
    "jobs": [{"kind": "refresh_inventory", "versions": [1]}]
  }
}
```

The report version is separate from the job protocol. Report version 1 accepts up to 32 distinct job kinds, each with one to eight distinct integer contract versions between 0 and 65535. Names use lowercase letters, digits and underscores, start with a letter and have at most 64 characters. Boolean versions, duplicates, unknown fields, malformed entries, null reports and oversized lists are rejected before changing inventory, last-seen time or jobs.

A well-formed future kind or version can be advertised without enabling it. The server admits the intersection of the current report, the requested job protocol and its explicit handler allowlist. The only available handler remains `refresh_inventory`, protocols 0 and 1. Adding a name to a report cannot create an executable handler, select a shell command or bypass role/device authorization.

An explicit empty `jobs` list reports no available job handlers for that poll. Missing inventory support or a version mismatch similarly withholds delivery. Queued jobs remain queued; an expired lease below its retry limit remains eligible for a later compatible poll. No new attempt or lease token is consumed while delivery is withheld. Regular inventory and last-seen updates continue for valid reports. The server finalizes an already exhausted inventory lease as failed even if the latest poll no longer admits another delivery.

Capability withdrawal affects new delivery only. It does not cancel a lease already issued or reject its otherwise valid completion. Operators use the scoped cancellation API when they intend to cancel work. The capability report is evaluated independently on every poll; it is not cached, persisted as inventory or included in the inventory digest. No database migration is needed. Queue creation can precede a compatible poll, so a queued job does not promise that an agent currently supports it.

## Compatibility and agent checks

Omitting the field preserves only the pre-existing read-only inventory compatibility path, including old protocol-0 agents and protocol-1 agents from 0.5.0. Explicit null is an error. Future handler registrations must not expand the omission fallback. A job already delivered using protocol 1 still cannot be downgraded to protocol 0.

A supporting server returns `capability_admission: 1`. The new agent rejects unknown admission versions and checks delivered contracts against its own advertised report before recording a journal attempt, forcing collection or submitting completion. Existing envelope checks still reject unknown job kinds, extra payloads, wrong targets and expired leases.

An older server may omit the admission marker and ignore the report. The agent then retains the narrow legacy inventory fallback and its existing local envelope allowlist. This compatibility path must not be used to introduce package, configuration, network or remote-shell execution. TLS and device credentials still protect transport; independent job signatures and trust provisioning remain separate work.

## Verification and rollout limits

Automated tests cover malformed-report atomicity, explicit empty reports, unknown/future kinds, version mismatches, independent polls after restart, concurrent compatible/incompatible polls, preservation of attempt budgets, exhausted leases, active completion after capability withdrawal, legacy no-downgrade behavior, operator/device separation and agent-side refusal before local job processing. A real HTTP agent cycle advertises both polls and saves a matching local receipt using disposable state.

No live Mac agent restart or BigBox rollout was performed for this source checkpoint. There is no new dashboard feature to simulate: this admission handshake operates between the real agent and control plane. Public dashboard assets stay at the actual deployed release. Native service, signed-job, privileged-operation and rollback acceptance gates remain open.
