# Review — feature 34 (`agency_intro_video_upload_and_render`)

**Veredicto:** APPROVED

Reviewer: Claude (Opus 4.7, reviewer subagent) · 2026-05-15.
Base: feature 33 (`agency_outro_video_upload_and_render`) merged in `done`.

## 1. Per-decision audit (leader contract → file:line)

| Leader decision | Verified at | Status |
|---|---|---|
| `POST /v1/admin/agencies/{id}/intro/upload` returns `{intro_object_key, intro_duration_seconds, intro_source: "uploaded"}` | `modules/configuration/transport/http/intro_router.py:155-254` (route) + `:362-373` (`_serialize_asset`) | OK |
| `GET /v1/admin/agencies/{id}/intro/file` returns bytes with `Content-Type` | `modules/configuration/transport/http/intro_router.py:256-322` (StreamingResponse, `_MEDIA_TYPE_BY_EXTENSION` at `:63-66`) | OK |
| `DELETE /v1/admin/agencies/{id}/intro` returns `{intro_source: "none", intro_object_key: null}` AND deletes blob | `modules/configuration/transport/http/intro_router.py:324-357` → `modules/configuration/application/use_cases/delete_intro_video.py:36-64` (calls `reset_to_none` + `path.unlink`) | OK |
| `GET /v1/admin/agencies/{id}/defaults` includes `intro_object_key`, `intro_duration_seconds`, `intro_source` | `modules/configuration/transport/http/defaults_router.py:90` (read), `:107` (passthrough), `:198`, `:214` (merge), `:262-285` (`_serialize_intro_asset`) | OK |
| `INTRO_INVALID_MIME` (422) | `modules/configuration/application/use_cases/upload_intro_video.py:96-104` + router translation at `:222-230` | OK |
| `INTRO_FILE_TOO_LARGE` (413) | `modules/configuration/application/use_cases/upload_intro_video.py:111-118` + router pre-check at `intro_router.py:186-195`; router maps to 413 at `:223` | OK |
| `INTRO_INVALID_DURATION` (422) | `modules/configuration/application/use_cases/upload_intro_video.py:125-138` (window 1..10s) | OK |
| Limits: 1–10s, ≤50 MiB, mp4/quicktime, ffprobe duration | `upload_intro_video.py:51-61` (`INTRO_MAX_UPLOAD_BYTES`, `ALLOWED_INTRO_CONTENT_TYPES`, suffix map) + `:246-279` (ffprobe runner) | OK |
| No new alembic migration vs feature 33 baseline | `ls alembic/versions/` head is still `20260515_0002_agency_outro_assets.py`; `git status --short alembic/versions/` shows no `??` newer than that file | OK |
| `alembic current = 20260515_0002 (head)` | `.venv/bin/python -m alembic current` → `20260515_0002 (head)` | OK |
| Reuses table `agency_intro_outro_assets` with `kind='intro'` | `upload_intro_video.py:172-175,179,219`; `delete_intro_video.py:45-49`; `read_intro_asset.py:21-24`; repo CHECK at `intro_outro_asset_repository.py:33` (`_ALLOWED_KINDS = {'intro','outro'}`) | OK |
| UNIQUE `(agency_id, kind)` respected | Repo uses `ON CONFLICT (agency_id, kind) DO UPDATE` at `intro_outro_asset_repository.py:113-117,158-162`; integration test `test_intro_and_outro_coexist_on_same_agency` (`test_intro_router.py:351-384`) asserts both kinds can coexist | OK |
| `video_segment_concat.py` exposes `concat_segment(position='start'\|'end', ...)` | `modules/rendering/infrastructure/ffmpeg/video_segment_concat.py:44-70,71-72` (validates position) | OK |
| `outro_concat.py` is now a thin wrapper preserving its public symbol | `modules/rendering/infrastructure/ffmpeg/outro_concat.py:21-51` — forwards to `concat_segment(position='end', stage='outro_concat')`; signature identical to feature 33 (kwarg-only, same param names) | OK |
| `intro_concat.py` mirrors it | `modules/rendering/infrastructure/ffmpeg/intro_concat.py:22-52` — forwards to `concat_segment(position='start', stage='intro_concat')` | OK |
| Callers of `concat_outro_to_reel` still import the same symbol | `modules/rendering/application/frame_composition.py:43`, `tests/integration/rendering/test_render_with_outro.py:33`, `tests/integration/rendering/test_render_with_intro.py:39` | OK |
| Render order when both enabled: intro + base + outro | `modules/rendering/application/frame_composition.py:156-178` — `_prepend_intro_to_reel` gate runs at L156-164 **before** the outro gate at L170-178; both mutate `media_path` in place | OK |
| Both passes run only when `*_enabled=true && *_source='uploaded' && blob present` | Gates check `intro_source == "uploaded" and intro_local_path is not None`; `intro_enabled` is enforced upstream in `modules/reels/application/use_cases/ingest_property_into_reel.py:1164,1175` so a `False` toggle yields `(None, source, 0)` | OK |
| `brand_card` skip + warning (same as outro) | `modules/reels/application/use_cases/ingest_property_into_reel.py:1168-1174` (warning + early return); renderer-level gate at `frame_composition.py:156-159` then naturally skips. Test `test_renderer_skips_intro_concat_when_source_is_brand_card` at `tests/integration/rendering/test_render_with_intro.py:408` | OK |
| Storage `{site_layout_root}/{agency_id}/intro/<sha1>.<ext>` | `shared/storage/site_layout.py:173-198` (`_INTRO_OUTRO_DIRNAME_BY_KIND` → `_agency_intro`); object_key `agencies/{safe_agency}/intro/intro-{sha1}{ext}` at `upload_intro_video.py:168-175`. Filename prefix `intro-` is symmetric with feature 33's `outro-` — same convention, accepted. | OK |
| Re-upload replaces; DELETE removes blob | `upload_intro_video.py:177-183, 224-230` (orphan cleanup post-upsert); `delete_intro_video.py:50-63` (`path.unlink(missing_ok=True)`) | OK |
| No regression in feature 33 tests | `tests/integration/configuration/test_outro_router.py` + `tests/integration/rendering/test_render_with_outro.py` + `tests/unit/configuration/test_outro_validator.py` → **25 passed in 21.96s** | OK |

## 2. Hard-rule audit

| Rule | Verified | Status |
|---|---|---|
| No `session.commit()` inside repositories | `grep "session.commit()" modules/configuration/infrastructure/intro_outro_asset_repository.py` → empty | OK |
| No legacy imports | `init.sh §4` reports "0 imports legacy" | OK |
| Inter-module rule respected | All imports from feature 34 files stay inside `modules/configuration/*` or `modules/rendering/*` or `shared/*` (no `from modules.<other>.application` or `.infrastructure` crossings). `modules/reels/application/use_cases/ingest_property_into_reel.py` reads `uow.configuration.intro_outro_assets` via the UoW port (same pattern as feature 33). | OK |
| Composition only in `apps/api/app_factory.py` and `apps/worker/runtime.py` | `create_intro_router` wired at `apps/api/app_factory.py:420-426`; no use case constructors instantiated outside the factory/runtime/test-_client | OK |
| `domain/` free of SQLAlchemy / Pydantic | `modules/reels/domain/types.py:404-406` adds plain `Path | None`, `str`, `int` — no SA/Pydantic. `modules/configuration/domain/agency_settings.py:47-63` (`IntroOutroAsset`) is a plain frozen dataclass. | OK |
| Test correspondence | 11 router integration + 7 render integration + 10 unit validator = 28 tests, all green | OK |

## 3. Acceptance checklist (feature 34 spec)

- [x] `POST /intro/upload` con multipart → 200 con `{intro_object_key, intro_duration_seconds, intro_source: 'uploaded'}` — `test_intro_upload_happy_path_returns_metadata_and_persists_blob` (lines 50-108 of `test_intro_router.py`).
- [x] `GET /intro/file` y `DELETE /intro` funcionan como sus pares de outro — `test_intro_get_file_returns_bytes_and_correct_content_type` (L110), `test_intro_delete_clears_metadata_and_removes_blob` (L140).
- [x] Migración up/down/up funcional (encadenada tras feature 33) — N/A: no new migration; alembic head is the feature-33 revision `20260515_0002`, which already accepts `kind='intro'` via the existing CHECK constraint. Verified live (`alembic current` → `20260515_0002 (head)`).
- [x] Render con `intro_enabled=true` y `source='uploaded'` produce MP4 final cuya duración = intro_duration + duración_base_reel — `test_concat_intro_to_reel_produces_combined_duration` at `test_render_with_intro.py:112` (real ffprobe assertion).
- [x] Render con `outro_enabled` e `intro_enabled` simultáneamente concatena ambos (intro al principio, outro al final, base reel en medio) — `test_concat_intro_then_outro_produces_combined_duration` (real ffmpeg, L143) and `test_renderer_invokes_both_intro_and_outro_when_both_uploaded` (renderer routing + order, L372).
- [x] `pytest -q` verde — feature 34 subset 28/28, feature 33 subset 25/25, full `init.sh` 971/971 + 3 known-flaky pre-existing (same baseline as `progress/impl_34.md`).
- [x] `apps.api --check` y `apps.worker --check` exit 0 — both verified below.

## 4. Verification re-run (this review)

```text
$ .venv/bin/python -m pytest tests/integration/configuration/test_intro_router.py tests/integration/rendering/test_render_with_intro.py tests/unit/configuration/test_intro_validator.py -q
28 passed in 22.82s

$ .venv/bin/python -m pytest tests/integration/configuration/test_outro_router.py tests/integration/rendering/test_render_with_outro.py tests/unit/configuration/test_outro_validator.py -q
25 passed in 21.96s

$ .venv/bin/python -m alembic current
20260515_0002 (head)

$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes  ·  FFMPEG: /usr/bin/ffmpeg  ·  EXIT 0

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render
outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
EXIT 0

$ bash ./init.sh
3 failed, 971 passed, 14 warnings in 491.06s (0:08:11)
[OK] pytest verde · [OK] Entorno listo
```

The 3 failing tests are the documented pre-existing flakes
(`test_http_surface_contract::test_frontend_api_requests_target_existing_backend_routes`
needs `FRONTEND_REPO_ROOT` to point to a Linux path; `test_http_transport::test_health_endpoints_*`
flake pre-dates feature 33). Same set as `progress/impl_34.md §6` — no new regression.

## 5. Issues found

### Blocking
None.

### Non-blocking
None.

### Nits (informational, not required for approval)

1. **`docs/API.md` doesn't cover the intro endpoints in prose.** The catalog (`docs/openapi.json:2331,2372` + `docs/http_surface.md:34-36`) carries the three endpoints. Feature 33's outro endpoints were not added to `docs/API.md` either — feature 34 inherits the same shape, so it's not a regression, but a future docs-tidy could add an "Intro/Outro assets" subsection to `docs/API.md` for both at once.
2. **Renderer-level test does not assert the `brand_card` warning log via `caplog`.** The implementer correctly identified this in §7 of `impl_34.md`: the warning is asserted in the ingest use-case test (single point of truth) and the renderer-level test only asserts the skip. Matches the trade-off accepted in feature 33's review.
3. **`intro_enabled` defaults to `True`** in the existing initial migration, while `outro_enabled` defaults to `False`. The product contract is intentional (the legacy intro card is rendered by a different path), but the asymmetry is worth a comment in the frontend when implementing the toggle UI.
4. **`_prepend_intro_to_reel` and `_append_outro_to_reel` in `frame_composition.py`** share ~95% of their body (only the helper call and the `.with_*.mp4` suffix differ). If feature 35+ adds a third position (e.g. mid-roll), consider factoring the two into a single `_concat_segment_in_place(reel_path, segment_path, position, template)`. Not required today.

## 6. Open items

### Sample curl smoke against `:8001`

```bash
AGENCY_ID=00000000-0000-0000-0000-000000000000
BEARER='Authorization: Bearer test-admin-token'
BASE=http://127.0.0.1:8001/v1/admin/agencies/${AGENCY_ID}

# 1) Upload a 5 s intro
curl -fsS -X POST "$BASE/intro/upload" \
     -H "$BEARER" \
     -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"

# 2) GET /defaults must include intro_object_key, intro_duration_seconds, intro_source
curl -fsS "$BASE/defaults" -H "$BEARER" | python -m json.tool | grep -E "intro_(object_key|duration_seconds|source)"

# 3) Stream the binary back
curl -fsS "$BASE/intro/file" -H "$BEARER" -o /tmp/echo_intro.mp4
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /tmp/echo_intro.mp4

# 4) DELETE
curl -fsS -X DELETE "$BASE/intro" -H "$BEARER"
curl -fsS "$BASE/intro/file" -H "$BEARER" -o /tmp/should_404.mp4  # expected 404 INTRO_FILE_NOT_FOUND

# 5) Coexistence: upload outro too, both should land in distinct rows
curl -fsS -X POST "$BASE/outro/upload" \
     -H "$BEARER" \
     -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"
curl -fsS -X POST "$BASE/intro/upload" \
     -H "$BEARER" \
     -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"
curl -fsS "$BASE/defaults" -H "$BEARER" | python -m json.tool | grep -E "(intro|outro)_(object_key|source)"
```

### Considerations for features 35-37 (per-reel overrides)

* **Override-shape uniformity.** Features 35-37 expose `PATCH /reels/{id}/...` per-reel overrides for photos / subtitles / slides. The intro/outro pattern in feature 33-34 stores agency-wide defaults in `agency_intro_outro_assets`; the per-reel override path will need a sibling table (or a JSON column on `reels`) that the renderer prefers over the agency default. Worth deciding upfront whether a future "intro/outro per-reel" override will reuse the same agency table with a nullable `reel_id` discriminator or split into `reel_overrides_intro_outro`.
* **Same multipart-without-`python-multipart` strategy.** Features 35-37 likely upload photos/subtitle files. The stdlib `email.parser` strategy currently lives inline in three routers (`brand_logo_router`, `music_upload_router`, `outro_router`, `intro_router`). After feature 34 we now have four near-identical implementations — extracting a shared `shared.transport.multipart.parse_single_file_field()` helper before adding the fifth is starting to look worthwhile. Not a feature 34 blocker, but a candidate for a small chore before feature 35.
* **`concat_segment(position=…)` extension point.** If feature 35-37 ever introduces a "mid-roll" segment (e.g. agency bumper between photo slides), the `Literal["start", "end"]` constraint on `SegmentPosition` will need to grow. Today it's correct and tight.
* **`intro_enabled` UX semantics.** The frontend should treat `intro_enabled=true` + `intro_source='none'` as "agency wants an intro but hasn't uploaded one yet — show the upload affordance"; this asymmetry vs `outro_enabled` is intentional (legacy intro card lives in a different render path).
* **`brand_card` is reserved.** Both intro and outro routers / ingest paths warn and skip on `source='brand_card'`. Features 35-37 should preserve this discriminator if they touch the same table.

## 7. Closing

* **Tests**: 28 new + 25 feature-33 + ~918 baseline → 971 green (3 known-flaky as before).
* **Public API**: matches the leader's contract verbatim. `concat_outro_to_reel` symbol preserved (`outro_concat.py` is now a 30-LoC wrapper).
* **Schema**: no new migration; `agency_intro_outro_assets` reused with `kind='intro'`. `alembic current` = `20260515_0002 (head)`.
* **Render order**: intro → base → outro. Asserted by real-ffmpeg duration test AND by a renderer-routing test that captures argv order.

Approved. `feature_list.json` flipped feature 34 to `done` (see below); `progress/current.md` updated.
