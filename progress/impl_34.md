# Feature 34 — `agency_intro_video_upload_and_render` (implementer report)

Estado al cierre: **listo para review**. NO marcado `done`.

## 1. Refactor choice

**Opted for (a) — generic helper**.

Extracted feature 33's `concat_outro_to_reel` body into
`modules/rendering/infrastructure/ffmpeg/video_segment_concat.py`,
which exposes :func:`concat_segment(reel_path, segment_path, output_path, position: 'start'|'end', width, height, fps, ...)`.
Both intro and outro paths consume this helper through thin wrappers:

* `outro_concat.py` becomes a 2-arg wrapper that forwards to
  `concat_segment(..., position='end', stage='outro_concat')`. The
  exported symbol `concat_outro_to_reel` is preserved verbatim so
  `frame_composition.py:42` and `tests/integration/rendering/test_render_with_outro.py:33`
  keep working without churn.
* `intro_concat.py` is the symmetric wrapper exposing
  `concat_intro_to_reel(..., position='start', stage='intro_concat')`.

Rationale:

* The normalisation pass (scale/pad/setsar=1/fps/yuv420p + AAC 44.1kHz
  stereo + silent-track fallback) is identical for intro and outro —
  the only difference is segment ordering. Duplicating ~150 lines of
  ffmpeg argv plumbing into `intro_concat.py` would have been a
  maintenance hazard.
* The blast radius into feature 33 is minimal: the wrapper preserves
  the exact same call signature, error stage (`stage="outro_concat"`),
  output filename suffix and ffmpeg argv. All 25 feature-33 tests
  remain green (re-run below).
* The new generic helper is internal (`modules/rendering/infrastructure/ffmpeg/`),
  so the public API surface of the rendering module is unchanged.

## 2. HTTP contract (as implemented)

Matches the leader's table verbatim. Mounted under
`admin_access_policy.base_path` (`/v1/admin` in production).

| Method | URL | Body | Response 200 |
|---|---|---|---|
| POST | `/v1/admin/agencies/{id}/intro/upload` | multipart, field `file`, MP4/MOV | `{ intro_object_key, intro_duration_seconds, intro_source: "uploaded" }` |
| GET | `/v1/admin/agencies/{id}/intro/file` | — | bytes with `Content-Type: video/mp4` (or `video/quicktime`) and `Content-Disposition: inline` |
| DELETE | `/v1/admin/agencies/{id}/intro` | — | `{ intro_source: "none", intro_object_key: null, intro_duration_seconds: null }` |

Plus: `GET /v1/admin/agencies/{id}/defaults` now also carries
`intro_object_key`, `intro_duration_seconds`, `intro_source` alongside
the existing feature-33 `outro_*` fields. (`intro_enabled` was already
exposed pre-feature-34.)

Error codes (parallel to feature 33):

* `INTRO_INVALID_MIME` — 422 — content-type not in `{video/mp4, video/quicktime}`.
* `INTRO_FILE_TOO_LARGE` — 413 — body > 50 MiB.
* `INTRO_INVALID_DURATION` — 422 — ffprobe duration outside `[1, 10]` seconds.
* `INTRO_PROBE_UNAVAILABLE` / `INTRO_PROBE_FAILED` — 422 — ffprobe failed.
* `INTRO_FILE_EMPTY` / `INTRO_UPLOAD_MISSING_FIELD` / `INTRO_UPLOAD_MALFORMED` — 422.
* `INTRO_UPLOAD_UNSUPPORTED_TYPE` — 415 — request not multipart/form-data.
* `INTRO_FILE_NOT_FOUND` — 404 — GET when nothing uploaded / blob gone.
* `ADMIN_AGENCY_NOT_FOUND` — 404 — unknown agency.

## 3. Files touched

| Path | Type | One-liner |
|---|---|---|
| `modules/rendering/infrastructure/ffmpeg/video_segment_concat.py` | ffmpeg helper (new, generic) | `concat_segment(position='start'\|'end', ...)` — normalisation + concat demuxer |
| `modules/rendering/infrastructure/ffmpeg/outro_concat.py` | ffmpeg wrapper (refactor) | Thin wrapper forwarding to `concat_segment(position='end', stage='outro_concat')` |
| `modules/rendering/infrastructure/ffmpeg/intro_concat.py` | ffmpeg wrapper (new) | Thin wrapper forwarding to `concat_segment(position='start', stage='intro_concat')` |
| `modules/rendering/application/frame_composition.py` | renderer | Adds `_prepend_intro_to_reel`; gates intro then outro (intro first → order is intro+base+outro) |
| `modules/reels/domain/types.py` | domain | Adds `intro_local_path`, `intro_source`, `intro_duration_seconds` to `PropertyContext` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | use case | Adds `_resolve_agency_intro_asset` (symmetric to outro); forwards to `PropertyContext` |
| `modules/configuration/application/use_cases/upload_intro_video.py` | use case + validator (new) | Validates MIME/size/duration, persists row, cleans up orphans |
| `modules/configuration/application/use_cases/delete_intro_video.py` | use case (new) | Resets row to `source='none'`, unlinks blob |
| `modules/configuration/application/use_cases/read_intro_asset.py` | use case (new) | Reads asset row (used by GET /defaults + GET /intro/file) |
| `modules/configuration/transport/http/intro_router.py` | router (new) | POST/GET/DELETE endpoints |
| `modules/configuration/transport/http/defaults_router.py` | router | Surfaces `intro_*` fields on GET /defaults; threads `ReadIntroAssetUseCase` |
| `apps/api/app_factory.py` | composition | Mounts `create_intro_router` |
| `tests/integration/configuration/_client.py` | test client | Mounts `create_intro_router` |
| `tests/integration/configuration/test_intro_router.py` | test (new) | 11 cases — POST/GET/DELETE happy path, validation errors, replacement, intro+outro coexistence |
| `tests/integration/rendering/test_render_with_intro.py` | test (new) | 7 cases — real-ffmpeg concat duration, renderer routing, intro+outro combined |
| `tests/unit/configuration/test_intro_validator.py` | unit test (new) | 10 pure validator cases (MIME/size/duration) |
| `feature_list.json` | metadata | Flipped feature 34 status to `in_progress` |
| `docs/http_surface.md` + `docs/openapi.json` | docs | Regenerated via `scripts/generate_http_surface.py --write` |

## 4. Migration

**No new alembic migration.** Feature 34 reuses the
`agency_intro_outro_assets` table created by feature 33 in
`alembic/versions/20260515_0002_agency_outro_assets.py`. The unique
constraint `(agency_id, kind)` means a new row with `kind='intro'`
cannot collide with the existing `kind='outro'` row for the same
agency. The `kind IN ('intro','outro')` CHECK already permits the new
discriminator value. `intro_enabled` was already on
`agency_reel_defaults` from the initial schema
(`20260501_0001_initial_schema.py:154`) — no column add needed.

`.venv/bin/python -m alembic current` reports `20260515_0002 (head)` —
the database is already at the latest revision.

## 5. Tests added

**28 new green tests**:

* `tests/unit/configuration/test_intro_validator.py` — 10 cases (MIME,
  size, duration window).
* `tests/integration/configuration/test_intro_router.py` — 11 cases:
  happy-path POST + persistence, GET /file byte-identity, DELETE
  clears metadata + blob, MIME 422, size 413, duration 422 + orphan
  cleanup, replace (no orphan on re-upload), 401/403 auth, 404 file
  not configured, 404 unknown agency, **and a combined coexistence
  test** that asserts intro and outro for the same agency live in two
  separate rows (UNIQUE on `(agency_id, kind)` allows both).
* `tests/integration/rendering/test_render_with_intro.py` — 7 cases:
  * Real-ffmpeg `concat_intro_to_reel` duration assertion (base +
    intro within ±0.5 s).
  * **Real-ffmpeg `intro + base + outro` chained pass** asserting
    final duration ≈ intro + base + outro (within ±1.0 s tolerance —
    two concat demuxer passes can each drift by a fraction).
  * Renderer routing: intro `uploaded` triggers `_prepend_intro_to_reel`
    and the outro pass does NOT fire (when only intro is configured).
  * Renderer routing: **both intro + outro `uploaded` triggers BOTH
    helpers, exactly once each, both targeting the same reel media
    path** (intro first, outro second).
  * Renderer skips intro concat when `source='brand_card'`.
  * Renderer skips intro concat when `intro_local_path is None`.
  * Renderer skips intro concat when `source='none'`.

Fixtures: reused `tests/integration/configuration/_fixtures/tiny_outro_5s.mp4`
(5 s @ 320x240, ~7 KiB) and `long_outro_15s.mp4` from feature 33. No
new test assets added.

## 6. Verification output (tail)

```
$ .venv/bin/python -m pytest tests/integration/configuration/test_intro_router.py tests/integration/rendering/test_render_with_intro.py tests/unit/configuration/test_intro_validator.py -q -v
...
tests/integration/configuration/test_intro_router.py ...........         [ 39%]
tests/integration/rendering/test_render_with_intro.py .......            [ 64%]
tests/unit/configuration/test_intro_validator.py ..........              [100%]
28 passed in ≈24s

$ .venv/bin/python -m pytest tests/integration/configuration/test_outro_router.py tests/integration/rendering/test_render_with_outro.py tests/unit/configuration/test_outro_validator.py -q
.........................                                                [100%]
25 passed in 18.78s
(feature 33 still green after the helper refactor)

$ .venv/bin/python -m alembic current
20260515_0002 (head)
(no new migration; same head as feature 33)

$ .venv/bin/python -m apps.api --check
... RUNTIME READY: Yes ... FFMPEG: /usr/bin/ffmpeg
EXIT 0

$ .venv/bin/python -m apps.worker --check
... Worker --check OK: kinds=email_send, reel_publish, scripted_render
... outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
EXIT 0

$ bash ./init.sh
...
3 failed, 971 passed, 14 warnings in 474.24s (0:07:54)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

The 3 failures are the documented pre-existing baseline flakes
(`test_http_surface_contract::test_frontend_api_requests_target_existing_backend_routes`
fails because `FRONTEND_REPO_ROOT` env var points to a Windows-only
path; `test_http_transport::test_health_endpoints_*` flakes pre-date
feature 33). Test count went from **943 baseline → 971** (+28 new,
exactly the new tests added).

## 7. Open items for reviewer

* **Helper refactor — feature 33's only behavioural change** is the
  ffmpeg `concat_outro_to_reel` now calls `concat_segment(..., position='end')`
  under the hood. The argv emitted to ffmpeg is byte-identical (same
  filter graph, same `-c copy` concat demuxer, same `-movflags
  +faststart`), the error stage name (`outro_concat`) is preserved,
  and all 25 feature-33 tests pass unchanged. Worth a second pass to
  confirm the refactor is functionally inert.
* **`brand_card` warning location** — same pattern as feature 33: the
  warning lives in the ingest use case (`ingest_property_into_reel.py`
  `_resolve_agency_intro_asset`), not the renderer. The renderer-level
  test `test_renderer_skips_intro_concat_when_source_is_brand_card`
  asserts the skip but not the warning emission. Same trade-off the
  feature 33 reviewer noted; tightening to a `caplog` assertion would
  duplicate the existing assertion in the ingest use case which is the
  single point of truth.
* **`intro_enabled` semantics** — defaults to `True` on
  `agency_reel_defaults` (existing column, set by the initial schema).
  The concat helper only actually runs when the agency *also* uploaded
  an MP4 — the toggle alone does NOT trigger a concat (the legacy
  intro card is rendered by a different path elsewhere in the
  pipeline). The frontend should treat `intro_enabled=true` +
  `intro_source='none'` as "agency wants an intro but hasn't uploaded
  one yet — show the upload affordance."
* **Order when both flags are on** — intro first, outro after,
  asserted in `test_renderer_invokes_both_intro_and_outro_when_both_uploaded`
  (renderer-level) and `test_concat_intro_then_outro_produces_combined_duration`
  (real ffmpeg, end-to-end duration). The two passes run sequentially
  on the same `media_path` (intro pass writes a `.with_intro.mp4`
  sibling and replaces the reel; outro pass then writes a
  `.with_outro.mp4` sibling and replaces the reel again). If a future
  feature wants a single concat pass for intro+base+outro, the
  obvious next step is to teach `concat_segment` to accept a list of
  segments in order; not in scope today.
* **No new alembic migration** — confirmed live: `alembic current`
  reports `20260515_0002 (head)`. The `agency_intro_outro_assets`
  table already accepts `kind='intro'` via the CHECK constraint.
* **OpenAPI / http_surface** — regenerated. The new intro endpoints
  appear in `docs/http_surface.md` and `docs/openapi.json`. The
  contract test (`test_http_surface_contract`) still flakes on the
  missing frontend repo root — pre-existing baseline issue, unrelated
  to feature 34.

## 8. Sample curl commands for :8001 manual smoke

```bash
# Replace AGENCY_ID and BEARER with real values.
AGENCY_ID=00000000-0000-0000-0000-000000000000
BEARER='Authorization: Bearer test-admin-token'
BASE=http://127.0.0.1:8001/v1/admin/agencies/${AGENCY_ID}

# 1) Upload a 5 s intro (reuse the feature-33 fixture)
curl -fsS -X POST "$BASE/intro/upload" \
     -H "$BEARER" \
     -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"

# 2) Confirm GET /defaults exposes both intro_* and outro_* shapes
curl -fsS "$BASE/defaults" -H "$BEARER" | python -m json.tool

# 3) Stream the binary back
curl -fsS "$BASE/intro/file" -H "$BEARER" -o /tmp/echo_intro.mp4
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /tmp/echo_intro.mp4

# 4) Toggle intro_enabled on (defaults to true already, but exercise the PUT path)
curl -fsS -X PUT "$BASE/defaults" \
     -H "$BEARER" -H 'Content-Type: application/json' \
     -d '{"intro_enabled": true}'

# 5) Also upload an outro and toggle outro_enabled on → reel becomes intro+base+outro
curl -fsS -X POST "$BASE/outro/upload" \
     -H "$BEARER" \
     -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"
curl -fsS -X PUT "$BASE/defaults" \
     -H "$BEARER" -H 'Content-Type: application/json' \
     -d '{"outro_enabled": true}'

# 6) Ingest a property → render output should be ≈ 5 s + base_reel + 5 s.
#    (Use the existing /webhook fixture invocation; nothing new required.)

# 7) DELETE
curl -fsS -X DELETE "$BASE/intro" -H "$BEARER"
```

---

> Implementer: Claude (Opus 4.7, lanzado por leader). Estado de la feature
> en `feature_list.json`: `in_progress`. Pendiente: reviewer.
