# One-shot inventory maintenance windows (0.6)

Version 0.6 adds optional maintenance windows to inventory refresh requests. The dashboard and API can create a scheduled refresh, and Activity and job history show its window in the browser's local time. The public mock source includes scheduled examples and a simulated window lifecycle. These changes are absent from 0.5.0; actual rollout is tracked in WORK_SESSION.md.

## Dashboard scheduling

On an active device, choose **Schedule refresh**, select local start/end times, review the UTC preview and choose **Schedule refresh** in the dialog. The form defaults to a window starting about ten minutes ahead and lasting thirty minutes. Cancel or close the draft to discard it. A pending refresh disables another schedule for that device; use Activity to review or cancel the existing job.

The dashboard shows scheduling only when its response advertises `job_windows: 1` and the current identity has `jobs.write`. This prevents a newer UI from offering schedules against an older server that would ignore the window. The server remains authoritative for permission and time-bound checks.

Inputs use the browser's timezone. The preview shows the exact UTC bounds submitted to the API. A local time skipped by spring-forward is rejected rather than silently shifted. A repeated fall-back time uses its first occurrence, stated in the dialog and shown in the UTC preview. This follows the browser's [Date offset-transition behavior](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date#date_components_and_time_zones); choosing the second occurrence requires the API in this slice.

Submission rechecks current time, visible device state, permission and pending jobs. While a request is in flight, repeated submission and dialog dismissal are blocked. If the queue succeeds but the dashboard reload fails, the dialog closes and reports that scheduling succeeded; it does not offer a retry that could create another job. A lost request response keeps the draft and directs the operator to check Activity before retrying. The API's duplicate-pending guard still applies. This is not a general idempotency guarantee once an earlier job becomes terminal.

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

Back up before deployment. Older binaries cannot open schema 6; rollback requires the pre-upgrade database and matching older image. Do not run unreleased main against the production database to test this migration. Deploy the exact intended release and publish its matching public export only after the private image is verified.

## Mock and verification

The browser-only mock includes a scheduled queued refresh. Its request transport accepts the same window shape. Reading mock state simulates a device check-in: an eligible scheduled job gets a simulated receipt inside its window, or a failed status after a missed window. No real fleet endpoint or clock-driven background service is contacted. Reloading resets these fictional records.

Browser workflow tests cover UTC conversion, skipped/repeated local times, unsupported servers, permission loss, duplicate submission, cancellation and lost/reload response handling. Headless Chrome checks exercised native form submission using mock state and verified desktop and 390-pixel viewport layouts. Native date-picker keyboard use, Safari, Firefox and actual mobile devices were not tested.

Backend tests cover start/end boundaries, missed windows without delivery, clipped signed leases, legacy completion, capability withdrawal, concurrent polls, restart, cancellation/revocation, scoped HTTP access, retained historical receipts, invalid-window atomicity and audit rollback. Migration checks use disposable fixtures and a fresh consistent copy of the live schema-4 database. The copy upgraded to schema 6 with integrity checks passing and all original device, job, audit, enrollment and credential records preserved. The live database was not migrated. Native service and live scheduling verification remain open.
