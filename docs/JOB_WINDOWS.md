# Unreleased: one-shot inventory maintenance windows

Source after the 0.5.0 tag adds optional maintenance windows to inventory refresh requests. The API can create a scheduled refresh, and the dashboard and job history show its window in the browser's local time. The scheduling form is not yet implemented; this slice exposes creation through the authenticated API. The public mock source includes scheduled examples and a simulated window lifecycle. These changes are not deployed or included in the published 0.5.0 image.

## Request and timing

An operator or administrator with `jobs.write` for the target device can send `POST /api/jobs` with a `window`:

```python
import time
start = int(time.time()) + 600
body = {
    "device": "ENROLLED_DEVICE_ID",
    "window": {"start": start, "end": start + 1800},
}
```

`start` and `end` are integer Unix seconds in UTC, independent of browser timezone or daylight-saving time. Start must be now or later, end must be after start and within 30 days of request time, and duration cannot exceed 24 hours. Allow time for the request to arrive; the example starts ten minutes ahead. Boolean/fractional timestamps, invalid bounds and extra window fields are rejected. Omitting `window` or setting it to null retains immediate refresh behavior.

The window is fixed when the job is queued. Changing it requires cancelling the pending job and creating another. Duplicate pending refreshes for the same device remain prohibited. Scheduling does not grant additional permissions, satisfy an approval or create a recurring policy.

The start boundary is inclusive and the end boundary exclusive. Before start, no delivery lease or retry attempt is consumed. Inside the window, all existing device, capability, protocol and retry checks still apply. A new lease ends at the earlier of the normal 120-second deadline and the window's end. Optional pinned signatures cover that clipped lease deadline. Legacy protocol-0 completion is also bounded by the server lease.

At or after the end, completion of a still-running attempt is rejected. On the next heartbeat from that device, a queued/running job with an expired window becomes failed and records one `inventory.window_expired` audit event. The lease proof is invalidated. This also happens if the device currently advertises no compatible handlers. Expiration and heartbeat inventory update are one transaction; audit failure rolls them back together.

Offline devices do not receive a separate timer callback in this slice. Their job can remain labelled queued or running until the next heartbeat observes expiration; the displayed window still shows its actual deadline. Expiration consumes no additional retry. A completed or cancelled job keeps its terminal state. Replaying an identical acknowledgement of a completion already accepted inside the window still returns its existing receipt after the window closes.

A running read may finish after the deadline, even though the server refuses its completion. The window does not forcibly terminate a local process and is not sufficient admission or rollback policy for package, configuration or network mutations. Recurring windows, timezone-aware calendar rules, group assignment and approval requirements remain separate work.

## Data and rollback

Schema 6 adds nullable `jobs.not_before` and `jobs.not_after` fields. Existing schema-5 jobs keep all original values and receive null bounds, preserving immediate delivery. Dashboard and paginated history expose the fields. The migration is transactional and repeatable. Tests also cover a failed schema-6 upgrade rolling back the new column and leaving the original version intact.

Back up before a future deployment. Older binaries cannot open schema 6; rollback requires the pre-upgrade database and matching older image. Do not run unreleased main against the production database to test this migration. The currently pending 0.5.0 rollout still requires its exact schema-5 release source and matching public export.

## Mock and verification

The browser-only mock includes a scheduled queued refresh. Its request transport accepts the same window shape. Reading mock state simulates a device check-in: an eligible scheduled job gets a simulated receipt inside its window, or a failed status after a missed window. No real fleet endpoint or clock-driven background service is contacted. Reloading resets these fictional records.

Tests cover start/end boundaries, missed windows without delivery, clipped signed leases, legacy completion, capability withdrawal, concurrent polls, restart, cancellation/revocation, scoped HTTP access, retained historical receipts, invalid-window atomicity and audit rollback. Migration checks use disposable fixtures and a fresh consistent copy of the live schema-4 database. The copy upgraded to schema 6 with integrity checks passing and all original device, job, audit, enrollment and credential records preserved. The live database was not migrated. Native service and live scheduling verification remain open.
