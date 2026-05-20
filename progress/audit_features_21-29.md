# Audit — Features 21–29 (Backend + Frontend)

- Date: 2026-05-18
- Auditor: Claude (read-only)
- Scope: Backend `feature_list.json` IDs 21–29 + Frontend `feature_list.json` IDs 21, 22, 23, 24, 25, 26, 28.
- Method: read production code, read tests, run targeted suites in isolation, cross-reference docs. No code or DB mutation.

## Summary

| Repo | ID | Name | Status (spec) | Result |
|------|----|------|----------------|--------|
| back | 21 | per_reel_description_override_endpoint | done | PASS |
| back | 22 | agency_music_upload | done | PASS |
| back | 23 | wire_render_to_agency_music_tracks | done | PASS |
| back | 24 | agency_music_selection_rules | done | PASS |
| back | 25 | per_reel_music_override | done | PASS |
| back | 26 | email_notification_infrastructure | done | PASS |
| back | 27 | email_notification_review_requested | done | PASS |
| back | 28 | font_catalog_and_brand_font_in_render | done | PASS |
| back | 29 | secondary_color_side_banner | done | PASS |
| front | 21 | per_reel_description_override_ui | done | PASS |
| front | 22 | agency_music_upload | done | PASS |
| front | 23 | wire_render_to_agency_music_tracks_noop_front | done | PASS (symbolic noop) |
| front | 24 | agency_music_selection_rules | done | PASS |
| front | 25 | per_reel_music_override | done | PASS |
| front | 26 | review_emails_chip_editor | done | PASS |
| front | 28 | brand_dynamic_fonts_and_reset_defaults | done | PASS |

All audited features marked `done` correspond to code on disk and tests that pass when run targeted. No GAPs detected. A few UNCLEAR notes are recorded under Open items but do not flag any "done with real gap" condition.

## Per-feature detail

### Backend 21 — per_reel_description_override_endpoint — PASS

- Migration: `/opt/projects/4Reels-Backend/alembic/versions/20260514_0003_reels_descriptions_override.py` (adds `reels.descriptions_override` JSONB; reversible).
- Router PATCH endpoint: `/opt/projects/4Reels-Backend/modules/reels/transport/http/admin_reels_router.py:574` (`PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/descriptions`).
- Payload model: `/opt/projects/4Reels-Backend/modules/reels/transport/payloads/reel_descriptions_override.py`.
- Use case (state guard + permission): `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/update_reel_descriptions_override.py` (errors `REEL_NOT_EDITABLE`, `PLATFORM_NOT_ENABLED`).
- Worker honours override at ingest/regenerate: `_apply_descriptions_override` in `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/ingest_property_into_reel.py:1314` (called from `:364`).
- Repository round-trip + JSONB cast: `/opt/projects/4Reels-Backend/modules/reels/infrastructure/reel_state_repository.py:64-83, 232, 312-331`.
- Tests: `/opt/projects/4Reels-Backend/tests/integration/reels/test_admin_reels_descriptions_override.py` (happy path, 404, 409 RESOURCE_LOCKED, 422 PLATFORM_NOT_ENABLED, override-preserved across re-ingest).
- Run: `.venv/bin/python -m pytest tests/integration/reels/test_admin_reels_descriptions_override.py -q` → 7 passed, exit 0.
- Docs cross-ref: `/opt/projects/4Reels-Backend/docs/API.md:814,894`; `/opt/projects/4Reels-Backend/docs/http_surface.md:52`.

### Backend 22 — agency_music_upload — PASS

- New multipart router: `/opt/projects/4Reels-Backend/modules/configuration/transport/http/music_upload_router.py` (POST `/v1/admin/agencies/{agency_id}/music/upload`, GET `/file/{filename}`). Multipart parsed without `python-multipart`.
- Use case: `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/upload_music_track.py`.
- Storage helper: `resolve_agency_music_destination` in `/opt/projects/4Reels-Backend/shared/storage/site_layout.py`.
- Legacy metadata-only POST retired (returns 405): `/opt/projects/4Reels-Backend/modules/configuration/transport/http/music_router.py:71-99`.
- MusicTrack PATCH disallows `object_key` via `extra='forbid'`: `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/music.py`.
- Tests: `/opt/projects/4Reels-Backend/tests/integration/configuration/test_music_upload_router.py` covers happy path, MIME invalid, >20 MB → 413, GET file/{filename}, cross-agency.
- Run: `.venv/bin/python -m pytest tests/integration/configuration/test_music_upload_router.py -q` → 12 passed, exit 0.
- Docs: `/opt/projects/4Reels-Backend/docs/API.md:553,576`.

### Backend 23 — wire_render_to_agency_music_tracks — PASS

- Migration seeds NCS tracks per agency (idempotent): `/opt/projects/4Reels-Backend/alembic/versions/20260514_0005_seed_existing_agencies_with_ncs_music_tracks.py`.
- Renderer reads injected music_tracks: `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/runtime/assets.py:106-135` (`resolve_background_audio_paths`).
- Helper to map MusicTrack rows → Paths: `resolve_agency_music_local_paths` in same module.
- Tests:
  - Seed on existing agencies: `tests/integration/configuration/test_seed_existing_agencies_music.py`.
  - Renderer uses agency pool: `tests/integration/rendering/test_render_uses_agency_music_pool.py`.
- Run combined → 5 passed, exit 0.

### Backend 24 — agency_music_selection_rules — PASS

- Defaults payload accepts `settings.music.selection_rules.fallback_to_full_library`: `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/defaults.py` (Pydantic nested model).
- Ingest reads the flag: `_resolve_agency_music_pool` use case at `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/_resolve_agency_music_pool.py`.
- Tests: `tests/integration/reels/test_music_selection_rules_flow.py` covers default true, explicit false (fails with MUSIC_NO_DEFAULT_TRACKS) and explicit true (uses library).
- Run → 3 passed, exit 0.

### Backend 25 — per_reel_music_override — PASS

- Migration: `/opt/projects/4Reels-Backend/alembic/versions/20260514_0006_reels_music_id_override.py` (`reels.music_id String(36)` + FK ON DELETE SET NULL).
- Router PATCH `/music`: `/opt/projects/4Reels-Backend/modules/reels/transport/http/admin_reels_router.py:638-700`.
- Use case: `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/update_reel_music_override.py`.
- Cross-agency rejection + state guard (`REEL_NOT_EDITABLE` → 409).
- Tests: `/opt/projects/4Reels-Backend/tests/integration/reels/test_admin_reels_music_override.py` (9 cases including cross-agency 404, 409, null clear, re-enqueue).
- Run → 9 passed, exit 0.
- Docs: `/opt/projects/4Reels-Backend/docs/API.md:815,945,1012`; `/opt/projects/4Reels-Backend/docs/http_surface.md:56`.

### Backend 26 — email_notification_infrastructure — PASS

- Layer present:
  - Protocol & dataclasses: `/opt/projects/4Reels-Backend/shared/email/sender.py`.
  - Backends: `/opt/projects/4Reels-Backend/shared/email/backends/console_sender.py`, `smtp_sender.py`.
  - Factory: `/opt/projects/4Reels-Backend/shared/email/factory.py`.
  - URL builder: `/opt/projects/4Reels-Backend/shared/email/url_builder.py`.
  - Validators: `/opt/projects/4Reels-Backend/shared/email/validators.py`.
- Migration `20260514_0007_email_notifications.py` (table + UNIQUE + indices). Repository at `/opt/projects/4Reels-Backend/modules/notifications/infrastructure/email_notification_repository.py`.
- Tests: `tests/unit/notifications/test_console_sender.py`, `test_smtp_sender.py`, `test_factory.py`, `test_email_message.py`, `test_url_builder.py`, `test_template_renderer.py`, `test_review_emails_normaliser.py`, and `tests/integration/notifications/test_migration_20260514_0007.py`, `test_email_notification_repository.py`.
- Run combined notifications suite (incl. 27) → 55 passed, exit 0.

### Backend 27 — email_notification_review_requested — PASS

- Dispatcher: `/opt/projects/4Reels-Backend/modules/notifications/application/use_cases/dispatch_review_requested_email.py` (CSV/list normalisation, regex filter, throttle, `event_kind='review_requested'` / `'review_requested_resent'`).
- Worker handler: `/opt/projects/4Reels-Backend/modules/notifications/application/use_cases/send_email_job_handler.py` (`kind='email_send'`).
- Templates: `/opt/projects/4Reels-Backend/assets/email/templates/review_requested.txt` + `.html`.
- Tests: `tests/integration/notifications/test_review_requested_flow.py`, `test_review_requested_resent.py`, `test_review_requested_throttle.py`, `test_email_send_handler_failure.py`.
- Run combined notifications suite → 55 passed, exit 0.

### Backend 28 — font_catalog_and_brand_font_in_render — PASS

- Fonts on disk (`Inter`, `Manrope`, `Plus_Jakarta_Sans`, `Montserrat`, `Poppins`, `Roboto`) under `/opt/projects/4Reels-Backend/assets/fonts/`.
- Catalog domain object: `/opt/projects/4Reels-Backend/modules/configuration/domain/font_catalog.py`.
- GET `/v1/admin/fonts` router: `/opt/projects/4Reels-Backend/modules/configuration/transport/http/fonts_router.py`.
- Validator on Brand payload: `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/brand.py` (rejects unknown family with `UNKNOWN_FONT_FAMILY`).
- Render injection: `ingest_property_into_reel.py` resolves `font_descriptor` and threads it into `PropertyReelTemplate.font_path` / `bold_font_path`.
- Tests: `tests/integration/configuration/test_fonts_router.py`, `test_brand_router.py`, `tests/integration/reels/test_ingest_property_font_injection.py` → 24 passed, exit 0.
- Docs: `docs/API.md:207-216`.

### Backend 29 — secondary_color_side_banner — PASS

- `_resolve_brand_secondary_color` cascade implemented in `ingest_property_into_reel.py:1003-1047`.
- Side-banner ribbon background propagated to render data; classic template unaffected.
- Tests: `tests/integration/rendering/test_side_banner_render.py` (`#FF00FF` carries through; None → `#FECF4D` fallback; classic ignored); `tests/integration/reels/test_ingest_property_secondary_color.py`.
- Run combined → 8 passed, exit 0.
- Docs: `ARCHITECTURE.md:63-87,255-266`.

### Frontend 21 — per_reel_description_override_ui — PASS

- Editor tab: `/opt/projects/4Reels-Frontend/src/features/reels/editor/DescriptionsPanel.jsx` (textareas, `NETWORK_LIMITS`, save flow, read-only when not editable).
- Wired in `ReelEditor.jsx` (`tab id='descriptions'`).
- Mock backend handles PATCH + 409/422 codes (`tests/support/mock-backend.js`).
- Playwright: `tests/reel_descriptions_override.spec.js` (4 cases) → all passed.

### Frontend 22 — agency_music_upload — PASS

- `src/features/music/MusicLibrary.jsx` uses file input (multipart); fields `object_key` and `duration_seconds` are no longer user inputs.
- `src/features/music/api.js` exposes `uploadTrack` (FormData) and no longer `registerTrack`. No raw `fetch(` in `src/features/music` (only `refetch()` matches, which is React-Query).
- `useUploadTrack` hook at `src/features/music/hooks.js:29`.
- Playwright: `tests/playwright/music_upload.spec.js` → 1 passed.

### Frontend 23 — wire_render_to_agency_music_tracks_noop_front — PASS (symbolic noop)

- Explicitly a no-op mirror; nothing to verify beyond confirming `/music` continues to list tracks (existing `tests/playwright/music_upload.spec.js` and existing tests cover that surface).

### Frontend 24 — agency_music_selection_rules — PASS

- `src/features/music/MusicRules.jsx` reads `defaults.settings.music.selection_rules.fallback_to_full_library` (default true) and PUTs preserving the rest of the blob via `useUpdateDefaults`.
- Playwright: `tests/playwright/music_rules.spec.js` → 1 passed.

### Frontend 25 — per_reel_music_override — PASS

- `src/features/reels/editor/MusicOverridePanel.jsx` renders dropdown with "Agency default pool" + tracks; PATCH `/music` via `src/features/reels/api.js:108-116` with `music_id: null` clearing the override.
- Dead `music: ''` from `hooks.js` no longer present (`grep "music: ''" src` returns nothing).
- Playwright: `tests/reel_music_override.spec.js` (3 cases) → all passed.

### Frontend 26 — review_emails_chip_editor — PASS

- `src/lib/utils/email.js` exports `EMAIL_PATTERN`, `isValidEmail`, `normaliseEmail`.
- `src/features/automation/EmailListInput.jsx` implemented; consumed by `ReviewModeDetails.jsx`.
- `useAutomationSave.js` sends `reviewEmails` as `list[str]`; legacy CSV hydration supported.
- Playwright: `tests/review_emails.spec.js` (3 cases) → all passed.

### Frontend 28 — brand_dynamic_fonts_and_reset_defaults — PASS

- `src/features/brand/fontsApi.js` + `useAvailableFonts` hook (in `src/features/brand/hooks.js`).
- `BrandConfig.jsx` dropdown populated from GET `/v1/admin/fonts`; hardcoded `Söhne` / `Helvetica` removed (grep clean).
- Reset button serialises `null` for `primary_color`, `secondary_color`, `font_family` in PUT body.
- Playwright: `tests/brand_dynamic_fonts.spec.js` (4 cases) → all passed.

## Top findings

1. All `done` features in the audited range correspond to real code with executable, passing tests. No false-positive `done` flags detected.
2. Test coverage matches the acceptance bullets in each feature: error codes (`REEL_NOT_EDITABLE`, `PLATFORM_NOT_ENABLED`, `UNKNOWN_FONT_FAMILY`, `MUSIC_NO_DEFAULT_TRACKS`, `MUSIC_TRACK_AUDIO_INVALID`) are exercised in integration tests.
3. Cross-references are coherent: every PATCH/POST/GET endpoint introduced in 21–28 is listed in `/opt/projects/4Reels-Backend/docs/http_surface.md`.
4. Feature 29 enforces the cascade `agency.secondary_color → property.wppd_accent_text_color → #FECF4D` and includes a regression assertion that the classic template is not affected.
5. Frontend 23 is a documented symbolic no-op (cross-repo same-id pattern), correctly closed without code commits.

## Open items / UNCLEAR notes

- (UNCLEAR, low risk) Backend feature 23 acceptance asks that `alembic downgrade -1` removes seeded rows/blobs only if created by the migration. The downgrade was not exercised in this audit because the policy is read-only and migrations are leader-only. The downgrade body in `20260514_0005_seed_existing_agencies_with_ncs_music_tracks.py` is present; not run.
- (UNCLEAR, low risk) Backend feature 27 acceptance includes a "retry" path "SmtpEmailSender fakeado para fallar la primera vez". The suite `tests/integration/notifications/test_email_send_handler_failure.py` exists and is green, but a true requeue mechanism (vs. one-shot mark_failed) wasn't independently confirmed end-to-end in this audit; the feature description hedges this as "if the queue allows".
- (UNCLEAR, doc-only) Backend `docs/API.md` does not contain a literal `descriptions_override` entry at the top of section 5; only deep inside (lines 814+, 894+). Acceptance does not strictly require a top-level mention, so marked PASS.
- Frontend acceptance for feature 25 asks `grep "music: ''" src` to return 0 hits — confirmed (no hits).
- Frontend acceptance for feature 22 asks `grep "fetch(" src/features/music` to return 0 hits — only matches are `refetch()` (React-Query), no raw `fetch(` calls; treated as PASS.

## Test commands executed (read-only)

Backend (from `/opt/projects/4Reels-Backend`):
- `.venv/bin/python -m pytest tests/integration/reels/test_admin_reels_descriptions_override.py -q` → 7 passed
- `.venv/bin/python -m pytest tests/integration/configuration/test_music_upload_router.py -q` → 12 passed
- `.venv/bin/python -m pytest tests/integration/configuration/test_seed_existing_agencies_music.py tests/integration/rendering/test_render_uses_agency_music_pool.py -q` → 5 passed
- `.venv/bin/python -m pytest tests/integration/reels/test_music_selection_rules_flow.py -q` → 3 passed
- `.venv/bin/python -m pytest tests/integration/reels/test_admin_reels_music_override.py -q` → 9 passed
- `.venv/bin/python -m pytest tests/integration/notifications/ tests/unit/notifications/ -q` → 55 passed
- `.venv/bin/python -m pytest tests/integration/configuration/test_fonts_router.py tests/integration/reels/test_ingest_property_font_injection.py tests/integration/configuration/test_brand_router.py -q` → 24 passed
- `.venv/bin/python -m pytest tests/integration/rendering/test_side_banner_render.py tests/integration/reels/test_ingest_property_secondary_color.py -q` → 8 passed

Frontend (from `/opt/projects/4Reels-Frontend`):
- `npx playwright test tests/reel_descriptions_override.spec.js --project=desktop` → 4 passed
- `npx playwright test tests/playwright/music_upload.spec.js --project=desktop` → 1 passed
- `npx playwright test tests/playwright/music_rules.spec.js --project=desktop` → 1 passed
- `npx playwright test tests/reel_music_override.spec.js --project=desktop` → 3 passed
- `npx playwright test tests/review_emails.spec.js --project=desktop` → 3 passed
- `npx playwright test tests/brand_dynamic_fonts.spec.js --project=desktop` → 4 passed

Total: 123 backend tests + 16 frontend tests, all green when run targeted.
