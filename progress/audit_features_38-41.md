# Audit — Features 38-41 (back) + 39-40 (front)

Date: 2026-05-18
Scope: backend feature_list.json ids 38, 39, 40, 41; frontend feature_list.json ids 39, 40.
Method: read acceptance criteria → locate production code → locate tests → run targeted pytest / Playwright. Read-only audit, no fixes applied, no migrations/restarts run.

## Summary

All 6 features (4 back + 2 front) PASS the acceptance criteria as currently
implemented and tested. 21 targeted tests are green (14 backend pytest +
7 frontend Playwright on the desktop project). One minor deviation
documented in feature 39 frontend (singleton store instead of
ToastProvider+Context); does not break any acceptance bullet and is
explained inline in the source.

## Per-feature table

| ID | Side | Title | Status | Tests run | Result |
|----|------|-------|--------|-----------|--------|
| 38 | back  | DB-backed webhook signing secret | PASS | `tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py` (4 cases) + `tests/integration/ingestion/test_wordpress_webhook_flow.py` (4 new cases) | 8/8 |
| 39 | back  | Reels list ordering guard | PASS | `tests/integration/reels/test_list_reels_ordering.py` (2 cases) | 2/2 |
| 40 | back  | POST /reels/.../regenerate manual mode | PASS | `tests/integration/reels/test_regenerate_reel_manual.py` (8 cases) | 8/8 |
| 41 | back  | `auto_subtitles_snapshot` column + exposure | PASS | `tests/integration/reels/test_auto_subtitles_snapshot.py` + `tests/integration/rendering/test_render_persists_auto_subtitles.py` | 13/13 |
| 39 | front | Toaster + Dashboard live sync | PASS (with deviation, see findings) | `tests/reels_dashboard_live_sync.spec.js` desktop | 3/3 |
| 40 | front | "Render again" button | PASS | `tests/manual_reel_regenerate.spec.js` desktop | 4/4 |

Backend pytest commands run (all green):

- `.venv/bin/python -m pytest tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py tests/integration/ingestion/test_wordpress_webhook_flow.py::test_webhook_accepts_with_db_persisted_secret tests/integration/ingestion/test_wordpress_webhook_flow.py::test_webhook_rejects_wrong_signature_for_db_secret tests/integration/ingestion/test_wordpress_webhook_flow.py::test_webhook_fallbacks_to_env_secret_with_warning tests/integration/ingestion/test_wordpress_webhook_flow.py::test_webhook_accepts_two_distinct_sites_for_same_agency -q` → 8 passed.
- `.venv/bin/python -m pytest tests/integration/reels/test_list_reels_ordering.py -q` → 2 passed.
- `.venv/bin/python -m pytest tests/integration/reels/test_regenerate_reel_manual.py -q` → 8 passed.
- `.venv/bin/python -m pytest tests/integration/reels/test_auto_subtitles_snapshot.py tests/integration/rendering/test_render_persists_auto_subtitles.py -q` → 13 passed.

Frontend Playwright commands run (all green):

- `PW_DEV=1 npx playwright test reels_dashboard_live_sync.spec.js manual_reel_regenerate.spec.js --project=desktop` → 7 passed.

## Per-feature findings

### Feature 38 — DB-backed webhook secrets (back) — PASS

- `_resolve_expected_secret(uow, site_id, env_site_secrets, logger)` lives
  in `modules/ingestion/transport/http/wordpress_webhook_router.py:67-102`.
  Priority is `DB (decrypt_text) → env (with warning) → None`, exactly as
  the spec requires.
- The webhook handler calls it at
  `modules/ingestion/transport/http/wordpress_webhook_router.py:217-244`,
  inside its own UoW for the lookup. Behaviour on `None` is still the
  documented 401 INVALID_WEBHOOK_CREDENTIALS.
- Unit tests cover all four branches of the decision tree (DB hit, DB
  row without secret + env fallback warning, no DB no env → None, no DB
  row but env → warning).
- Integration tests cover: DB secret 202, wrong signature 401, env
  fallback 202+warning, two sites/same agency both 202 via direct
  ingestion_sources insert with `encrypt_text(secret)`.

### Feature 39 — Reels list ordering guard (back) — PASS

- `modules/reels/infrastructure/reel_query.py:298` confirms
  `ORDER BY r.updated_at DESC NULLS LAST, p.fetched_at DESC NULLS LAST`.
- `tests/integration/reels/test_list_reels_ordering.py` uses a SQL
  helper `_force_updated_at` to pin three reels at T0, T0+1h, T0+2h.
  Test 1 asserts initial order; test 2 promotes the oldest reel and
  asserts it moves to position 1. The test bypasses a public PATCH (the
  spec preferred PATCH but accepted "via SQL directly in the fixture")
  to keep determinism — acceptable per spec wording.

### Feature 40 — POST /reels/.../regenerate (back) — PASS

- Endpoint registered at
  `modules/reels/transport/http/admin_reels_router.py:447-571`. Body
  optional, parsed manually because FastAPI marks body-as-argument as
  required.
- Use case `RegenerateReelUseCase` accepts
  `mode: Literal["approve_and_regenerate","manual_only"]` (default
  `approve_and_regenerate` — preserves existing approve handler). In
  `manual_only` mode it skips the workflow/publish setattrs (see
  `regenerate_reel.py:234-263, 405-412`).
- Two custom exceptions `RegeneratePublishedForbidden` /
  `RegenerateAlreadyInFlight` are raised and surfaced as 409 with the
  documented codes.
- Integration tests cover: happy path with workflow/publish invariance,
  empty body, 404, 409 published, 409 active-job, 409 queued-job,
  photos_override preserved, and a regression guard that the approve
  handler still replays the queued job after the mode parameter was
  added.
- docs/API.md got the new section (`docs/API.md:813,820`).

### Feature 41 — auto_subtitles_snapshot for editor (back) — PASS

- Migration `alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py`
  adds the JSONB nullable column with `down_revision="20260515_0005"`,
  upgrade/downgrade clean.
- ORM column added at `shared/db/orm.py:239`.
- Domain ReelState gains the field
  (`modules/reels/domain/reel_state.py:100`); `RenderedMediaArtifact`
  carries the cues (`modules/reels/domain/types.py:319-355`).
- Repository writes / forwards the snapshot in INSERT, ON CONFLICT and
  the three helper methods (verified `modules/reels/infrastructure/reel_state_repository.py`).
- `frame_composition.py:217-262` computes the snapshot only when
  `context.subtitles_override is None`, otherwise leaves the row's
  previous snapshot intact (the "lesson from feature 35" forward).
- Query exposes it in `_REEL_COLUMNS` and the `AgencyReelSummary`
  dataclass (`reel_query.py:163, 282-334`).
- Transport: `_serialize_agency_reel` adds
  `"publish_subtitles_snapshot": item.auto_subtitles_snapshot`
  (`modules/reels/transport/http/admin_reels_assets.py:70-77`). The
  payload model also lists the field (`admin_reels.py:64`). Note: the
  serializer is shared by **both** list (`GET /reels`) and item
  (`GET /reels/{site}/{prop}`) endpoints in
  `admin_reels_router.py:316, 358, 427`, so the snapshot is exposed in
  both responses as expected.
- Front mapper at `src/features/reels/hooks.js:147-159` reads
  `raw.publish_subtitles_snapshot` as a TOP-LEVEL field (NOT the old
  nested `publish_target_snapshot.subtitles`). Comment in the file
  explicitly notes the migration.
- Tests: render-without-override populates the snapshot; re-ingest
  preserves it; GET item returns it; render-with-override does not
  overwrite the prior snapshot.

### Feature 39 — Toaster + live sync (front) — PASS (deviation noted)

- Deviation: spec called for `ToastProvider` + Context wrapping the app
  in Shell.jsx; the implementer chose a module-level singleton store
  (`src/lib/hooks/useToast.js`) with the `<Toaster>` mounted once at the
  bottom of Shell.jsx. The rationale is documented at the top of
  `useToast.js` (allows non-React modules to emit, cleaner imperative
  ergonomics, single rendering point). This satisfies the user-visible
  acceptance bullets:
  - `<Toaster>` global in Shell.jsx (line 117) — yes.
  - `useToast()` hook reusable — yes (used by the Toaster; feature code
    uses `toast.success/error/info` directly from the module export).
  - role='alert'/'status' a11y — verified by Playwright spec
    `Approve failure surfaces an error toast (role="alert")` and
    `success toast (role="status")`.
- DashboardRefetchContext: defined in
  `src/features/reels/DashboardRefetchContext.js`. ReelsRoute in
  Shell.jsx lifts the Dashboard's `refetch` via a ref and provides it
  to the Outlet (lines 141-161). ReelEditor consumes it
  (`ReelEditor.jsx:120-138`) and only invokes it if `hasMutatedRef`
  is true — matches the "do not refetch when nothing changed" bullet.
- Per-panel `onMutate={markMutated}` wired to Photos, Music, Subtitles,
  Slides, Descriptions panels (ReelEditor.jsx:290, 307, 335, 347, 355,
  366). Approve/Reject inside the editor also `markMutated()` (lines
  240, 263).
- Dashboard handlers wrap approve/reject in try/catch and surface
  toasts (`Dashboard.jsx:158-189`).
- Playwright spec covers: editor close after a music override
  refetches Dashboard and modified reel rises to top; Approve success
  toast role="status"; Approve failure toast role="alert".

### Feature 40 — "Render again" button (front) — PASS

- `RegenerateReelButton.jsx`: visible when `renderStatus in
  {"completed","done"}` (the latter is the mock backend's terminal
  bucket); hidden when `failed`; disabled with tooltip when published.
- Confirm modal → `triggerRegenerate()` (via `useRegenerateReel`) →
  toast 'Re-rendering the reel…' on success; 409 codes mapped to
  specific toast strings.
- `reelsApi.regenerateReel(agencyId,siteId,sourcePropertyId, reason)`
  defined in `src/features/reels/api.js:187-200`. Sends body `{}` when
  no reason (POST without body acceptable on the backend).
- Hook `useRegenerateReel` (`hooks.js:311+`) polls render_status after
  the POST.
- Playwright cases verified: happy path, published disabled,
  in-flight 409, cancel modal does not POST.

## Top findings (priority order)

1. **Feature 38 fully delivered**: webhook secret resolution path matches
   the spec verbatim. Multi-WP-per-agency works without restart, env
   fallback only fires a warning and only when DB lacks the secret.
2. **Feature 41 snapshot exposed in both list and item responses**: the
   shared `_serialize_agency_reel` covers both endpoints (the spec only
   explicitly mentioned the item endpoint in one bullet, the listing
   endpoint in another — both paths are covered).
3. **Feature 41 frontend mapper migrated**: `publishSubtitlesSnapshot`
   reads top-level `raw.publish_subtitles_snapshot`. The legacy nested
   `publish_target_snapshot.subtitles` is no longer consulted, matching
   the user-reported finding that drove this feature.
4. **Feature 39 front uses a singleton instead of Provider/Context for
   toasts** — documented deviation, no acceptance impact. Worth a
   leader review at the next sweep if the architecture doc prefers
   Provider patterns, but the Playwright a11y checks confirm the user
   experience matches what the spec asked for.
5. **Feature 40 back: 409 response payload shape** — the manual handler
   returns `{"error": "REGENERATE_*", "detail": "…"}` rather than the
   `json_error` envelope (`{"message","code","hint","details"}`). The
   spec text gives the codes but does not pin the envelope. The
   frontend reads `err.body.error || err.body.code` so it works either
   way. Worth noting for future consistency only.

## Open items / UNCLEAR

- **None blocking.** All acceptance bullets across the 6 features are
  satisfied by the current code + tests.
- Feature 41 `docs/API.md` was not updated to mention
  `publish_subtitles_snapshot` in the GET responses. The spec did not
  list `docs/API.md` in scope (it explicitly only listed schema,
  modules, alembic and tests), so this is **not a gap** — but if the
  team's policy is "every response-shape change touches API.md", a
  follow-up doc note would be a 5-line patch.
- Frontend Playwright was run only against the `desktop` project. The
  pre-existing tablet flakiness mentioned in feature 39 leader notes is
  unrelated and not exercised here.

## Verification artefacts

Files inspected (absolute paths):

- `/opt/projects/4Reels-Backend/modules/ingestion/transport/http/wordpress_webhook_router.py`
- `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/regenerate_reel.py`
- `/opt/projects/4Reels-Backend/modules/reels/transport/http/admin_reels_router.py`
- `/opt/projects/4Reels-Backend/modules/reels/transport/http/admin_reels_assets.py`
- `/opt/projects/4Reels-Backend/modules/reels/transport/payloads/admin_reels.py`
- `/opt/projects/4Reels-Backend/modules/reels/infrastructure/reel_query.py`
- `/opt/projects/4Reels-Backend/modules/reels/infrastructure/reel_state_repository.py`
- `/opt/projects/4Reels-Backend/modules/reels/domain/reel_state.py`
- `/opt/projects/4Reels-Backend/modules/reels/domain/types.py`
- `/opt/projects/4Reels-Backend/modules/rendering/application/frame_composition.py`
- `/opt/projects/4Reels-Backend/shared/db/orm.py`
- `/opt/projects/4Reels-Backend/alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py`
- `/opt/projects/4Reels-Backend/tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py`
- `/opt/projects/4Reels-Backend/tests/integration/ingestion/test_wordpress_webhook_flow.py`
- `/opt/projects/4Reels-Backend/tests/integration/reels/test_list_reels_ordering.py`
- `/opt/projects/4Reels-Backend/tests/integration/reels/test_regenerate_reel_manual.py`
- `/opt/projects/4Reels-Backend/tests/integration/reels/test_auto_subtitles_snapshot.py`
- `/opt/projects/4Reels-Backend/tests/integration/rendering/test_render_persists_auto_subtitles.py`
- `/opt/projects/4Reels-Backend/docs/API.md`
- `/opt/projects/4Reels-Frontend/src/app/Shell.jsx`
- `/opt/projects/4Reels-Frontend/src/lib/hooks/useToast.js`
- `/opt/projects/4Reels-Frontend/src/shared/Toaster.jsx`
- `/opt/projects/4Reels-Frontend/src/features/reels/Dashboard.jsx`
- `/opt/projects/4Reels-Frontend/src/features/reels/DashboardRefetchContext.js`
- `/opt/projects/4Reels-Frontend/src/features/reels/editor/ReelEditor.jsx`
- `/opt/projects/4Reels-Frontend/src/features/reels/editor/RegenerateReelButton.jsx`
- `/opt/projects/4Reels-Frontend/src/features/reels/api.js`
- `/opt/projects/4Reels-Frontend/src/features/reels/hooks.js`
- `/opt/projects/4Reels-Frontend/tests/reels_dashboard_live_sync.spec.js`
- `/opt/projects/4Reels-Frontend/tests/manual_reel_regenerate.spec.js`
- `/opt/projects/4Reels-Frontend/DOCS.md`
