# Email notifications — operations guide

This document is the runbook for operating the email notification
pipeline shipped in features 26 (infrastructure) and 27 (`review_requested`
flow). It is intentionally short — the design and contracts live in:

* `progress/design_email_notifications_and_brand_customisation.md` §A
* `docs/API.md` §7b (infrastructure) and §7c (review_requested flow)
* `progress/impl_26_email_notification_infrastructure.md`
* `progress/impl_27_email_notification_review_requested.md`

## 1. Backends + env

| Env var                | Default                       | Notes |
|------------------------|-------------------------------|-------|
| `EMAIL_BACKEND`        | `console`                     | `console` (stdout, dev/test) or `smtp` (prod). |
| `SMTP_HOST`            | `localhost`                   | Required when `EMAIL_BACKEND=smtp`. |
| `SMTP_PORT`            | `587`                         | |
| `SMTP_USER`            | unset                         | If unset, the sender skips `login()`. |
| `SMTP_PASSWORD`        | unset                         | Paired with `SMTP_USER`. |
| `SMTP_USE_TLS`         | `true`                        | When `false`, `starttls()` is skipped. |
| `SMTP_FROM_ADDRESS`    | `notifications@4reels.ie`     | Envelope From + RFC 5322 `From:`. |
| `SMTP_FROM_NAME`       | `4Reels Notifications`        | Display name. |
| `FRONTEND_BASE_URL`    | `http://localhost:5173`       | Used to build the reel deep link in email bodies. Set to the admin host on test/prod. |

## 2. Dev workflow

```bash
EMAIL_BACKEND=console .venv/bin/python -m apps.worker
```

`ConsoleEmailSender` prints every message to stdout prefixed by
`[email/console]` lines. The worker log captures the output verbatim
so you can `grep` for `Subject:` and `To:` while reproducing a
notification scenario.

## 3. Verifying delivery on test

```sql
-- Latest 20 notifications for an agency, with status + provider id.
SELECT id, event_kind, recipient_email, status, provider_message_id,
       sent_at, error_message
FROM email_notifications
WHERE agency_id = '<uuid>'
ORDER BY created_at DESC
LIMIT 20;
```

The dispatcher writes one row per recipient. Rows from the same
dispatch share `provider_message_id` once the worker delivers the
job (`provider_message_id` is `NULL` for `ConsoleEmailSender`).

## 4. Debugging a missing email

1. Check that the agency has at least one valid email in
   `defaults.settings['automation.reviewEmails']`:
   ```sql
   SELECT settings->'automation.reviewEmails'
   FROM agency_reel_defaults
   WHERE agency_id = '<uuid>';
   ```
   If `NULL`, the dispatcher logs `no recipients configured` and marks
   the outbox event `dispatched` without enqueuing anything.
2. Confirm the outbox event was emitted:
   ```sql
   SELECT event_id, status, payload, last_error
   FROM outbox_events
   WHERE event_type = 'review_requested'
     AND external_source_id = '<site>'
     AND source_property_id = <pid>;
   ```
   * `status='pending'` → the subscriber has not run yet (worker
     stopped?).
   * `status='processing'` → claimed but the handler did not finish
     (worker crash; the row stays claimed until the worker restarts
     and re-attempts).
   * `status='dispatched'` → handed off successfully.
   * `status='failed'` → see `last_error`.
3. Look for the `email_send` job:
   ```sql
   SELECT job_id, status, last_error, attempt_count
   FROM jobs
   WHERE kind = 'email_send'
     AND property_id = <pid>
   ORDER BY created_at DESC LIMIT 5;
   ```
4. Tail the worker log:
   ```bash
   tail -f /opt/projects/4Reels-Backend/logs/test-worker.log | \
     grep -E 'email_send|email_notification|dispatch_review_requested'
   ```

## 5. Throttle

The default throttle is **1 email per (agency, recipient) per 60
seconds**. Tuning is hard-coded today in
`DispatchReviewRequestedEmailUseCase(throttle_seconds=60)`; a future
PR can expose it as an env var if product needs faster cadence
during incidents.

## 6. Re-render → `review_requested_resent`

When the admin regenerates a reel and it lands back on
`pending_review`, `publish_reel` emits a fresh `review_requested`
outbox event. The dispatcher detects that the recipient already has
a `review_requested` row for the slot and inserts the new row with
`event_kind='review_requested_resent'` — coexisting cleanly with the
original under the UNIQUE constraint.
