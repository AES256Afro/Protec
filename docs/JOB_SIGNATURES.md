# Unreleased: pinned signatures for inventory delivery

Source after 0.5.0 adds optional Ed25519 signatures to protocol-1 inventory delivery. Operators explicitly provision a signing key on the server and a public trust file on each agent. An agent started with `--job-trust` refuses unsigned, altered, expired, wrongly targeted or untrusted deliveries before recording a local attempt or forcing inventory collection. Normal heartbeat inventory is still sent before the delivery response is checked.

This is an unreleased source feature. The deployed 0.4.0 pilot and the published 0.5.0 release do not include it. It does not enable package changes, configuration writes, network operations or remote shells, and it does not complete M4 or native agent deployment acceptance.

## Local setup in a disposable environment

Use a project virtual environment for the optional signing dependency. The implementation calls PyCA's Ed25519 signing and verification APIs, including raw key serialization; it does not implement elliptic-curve cryptography itself. See the [PyCA Ed25519 documentation](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/ed25519/).

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-signing.txt
.venv/bin/python -m protec.job_signatures \
  --directory .protec/job-signing \
  --server http://127.0.0.1:8765
```

The output directory must be new. The command writes `signing-key.json` and `job-trust.json` with mode 0600 inside a new mode-0700 directory. It prints only the public key fingerprint. It never overwrites an existing identity. If creation is interrupted, inspect the partial directory before trying a different destination; do not assume the two-file creation is atomic. Both filenames are ignored by Git.

Start the local control plane with the private file:

```sh
.venv/bin/python -m protec.server \
  --job-signing-key .protec/job-signing/signing-key.json
```

Provision only `job-trust.json` to the agent over an independently trusted administrative channel, with a mode-0700 parent directory and mode-0600 file. The private signing file belongs only on the control plane. Use an existing disposable enrollment, or enroll the disposable agent through the normal token flow. Then require pinned signatures:

```sh
.venv/bin/python -m protec.agent \
  --state .protec/test-agent.json \
  --job-trust .protec/job-signing/job-trust.json \
  --once
```

For remote agents, generate files bound to the exact HTTPS portal origin, including its port. The origin in the trust file must match the agent state. Do not use these commands to replace the existing BigBox or Mac identities. Enrollment does not automatically learn a signing key, and the server cannot silently replace an agent's pinned trust file.

## Container and key lifecycle

The source Docker build installs the pinned signing dependency. Set `PROTEC_JOB_SIGNING_KEY` to a protected private key path inside the container when opting in. The key's origin must match `PROTEC_PUBLIC_URL`. The file must be readable only by the container's effective user, currently UID 10001, with a private parent directory. Provision it through an appropriate secret mount or protected persistent location. Configuration errors stop startup; the server does not fall back to unsigned operation after a configured key fails to load.

The BoxPilot catalog does not yet provision these signing files or expose a key-rotation workflow. Existing catalog installs remain compatible and unchanged. Do not interpret this environment variable as completed catalog or production signing rollout support.

A trust file can hold one to eight distinct public keys. Planned rotation requires adding the new public key to agent trust files and restarting those agents, switching the server private key and restarting the server, then removing the old public key and restarting agents after the transition. The implementation loads keys at startup; it does not watch files or fetch replacements remotely. Removing a key from disk alone does not revoke trust in an already running process. No automated rotation, key expiration, emergency revocation distribution, hardware-backed key store or key recovery procedure is claimed by this slice. Keep the private key out of browser storage, source and logs.

## Signed contract and compatibility

The heartbeat response keeps the existing job envelope and adds `job_signatures`, a map from job ID to a detached proof:

```json
{
  "version": 1,
  "algorithm": "Ed25519",
  "key_id": "SHA256_OF_RAW_PUBLIC_KEY",
  "signature": "UNPADDED_BASE64URL_SIGNATURE"
}
```

The signed bytes are the ASCII domain prefix `Protec inventory job signature v1` followed by a zero byte, then the UTF-8 JSON object `{ "server": ORIGIN, "job": ENVELOPE }`. JSON uses sorted keys, compact separators, ASCII escapes and no non-finite numbers, matching Python's `json.dumps` settings in `message()`. Every envelope field is covered, including device, job ID, job kind/version, payload, attempt, creation time, lease token and deadline. Key IDs are the SHA-256 digest of the raw public key. Encodings are canonical unpadded base64url. This serialization is a Protec-specific contract, not a claim of RFC 8785 compatibility; other-language agents require shared byte-level fixtures before adoption.

The server signs within the inventory/lease transaction. Signing failure rolls back the inventory update and lease attempt together. Signatures and lease proofs are delivered only to the authenticated device; the private key is never transmitted. Detached proofs are not added to dashboard, audit, database job records or the local receipt journal. The returned server completion receipt remains an unsigned acknowledgement and must not be presented as a cryptographically verifiable execution record.

Pinned agents require exactly one valid proof for every delivered job. Missing/extra proofs, duplicate delivered IDs, unsupported algorithms/versions, unknown public keys, wrong origins, changed envelopes and expired leases are rejected. Pinned agents also reject legacy protocol-0 jobs. The existing local journal suppresses replay of a recorded attempt; signature validity alone does not establish freshness after cancellation or guarantee exactly-once execution. Current inventory work is read-only, and the server still enforces active leases and cancellation at completion.

Agents without `--job-trust` retain the existing unsigned read-only mode. Servers with a key still support legacy agents, which do not gain signature verification merely by receiving signed responses. HTTPS, device identity, operator authorization, capability admission, cancellation and local replay evidence remain separate checks. Signed mode is opt-in for this pilot and must become an explicit admission requirement before privileged job types are introduced.

## Verification limits

Tests exercise field-by-field tampering, wrong device/origin/key, expired and superseded leases, downgrade/missing proofs, strict encodings, key overlap/removal, secure file loading, generation without overwrite and rollback on signing failure. Disposable HTTP and WSGI tests exercise configured signing, public trust verification, local acknowledgement receipts and server restart. A subprocess test uses the actual key-generation and agent CLIs, then removes server signing and verifies the pinned agent refuses the next job.

These tests do not establish BigBox signing deployment, durable trust provisioning on the existing Mac agent, native service reboot/update behavior or signature security for privileged job types. Live rollout remains tied to its exact released image and the matching public mock assets.
