# Review — feature 33 (`agency_outro_video_upload_and_render`)

**Verdict:** APPROVED

Reviewer: Claude Opus 4.7 (1M ctx), running as the reviewer subagent for the
4Reels backend, on 2026-05-15.

---

## 1. Per-decision audit table

| # | Leader decision | Verdict | Evidence (file:line) |
|---|---|---|---|
| 1 | `POST /v1/admin/agencies/{id}/outro/upload` multipart `file` → `{outro_object_key, outro_duration_seconds, outro_source:"uploaded"}` | ✅ | `modules/configuration/transport/http/outro_router.py:154-253` (route + happy-path JSONResponse); serializer at `:361-372`; `tests/integration/configuration/test_outro_router.py:50-105`. |
| 2 | `GET /v1/admin/agencies/{id}/outro/file` returns bytes w/ appropriate `Content-Type` | ✅ | `outro_router.py:255-321` (`StreamingResponse` with `media_type` from `_MEDIA_TYPE_BY_EXTENSION` at `:62-65` and `:303-304`); `tests/integration/configuration/test_outro_router.py:108-136`. |
| 3 | `DELETE /v1/admin/agencies/{id}/outro` returns `{outro_source:"none", outro_object_key:null}` AND deletes the blob | ✅ | `outro_router.py:323-356`; use case `modules/configuration/application/use_cases/delete_outro_video.py:35-63` (calls `reset_to_none` + best-effort `path.unlink(missing_ok=True)`); test `tests/integration/configuration/test_outro_router.py:138-186` asserts both the response shape AND `persisted_path.exists() == False`. |
| 4 | `GET /v1/admin/agencies/{id}/defaults` includes `outro_object_key`, `outro_duration_seconds`, `outro_source`, `outro_enabled` | ✅ | `modules/configuration/transport/http/defaults_router.py:181-246` (`_serialize_defaults` + `_serialize_outro_asset`); fields emitted even when no row exists (`:200-205`). Verified by `test_outro_delete_clears_metadata_and_removes_blob` re-fetching `/defaults` (`test_outro_router.py:177-186`). |
| 5 | MIME validation → 422 `OUTRO_INVALID_MIME` | ✅ | `modules/configuration/application/use_cases/upload_outro_video.py:94-104` raises `ValidationError(code="OUTRO_INVALID_MIME")`; router maps to 422 (default branch at `outro_router.py:221-229`). Test: `test_outro_router.py:189-207`. |
| 6 | Size > 50MB → 413 `OUTRO_FILE_TOO_LARGE` | ✅ | Defensive gate at `outro_router.py:185-194` (router-level 413 short-circuit before parsing); duplicate guard at `upload_outro_video.py:110-118`. Router maps `OUTRO_FILE_TOO_LARGE` to 413 (`outro_router.py:222`). Test: `test_outro_router.py:210-227`. |
| 7 | Duration outside [1, 10] s → 422 `OUTRO_INVALID_DURATION`; uses ffprobe (not client metadata) | ✅ | `upload_outro_video.py:125-138` (`validate_outro_duration`); ffprobe invoked at `:188` via `_run_ffprobe_duration` (`:246-279`), which calls a real binary via `shutil.which("ffprobe")`. Orphan blob cleaned on rejection at `:212-214`. Tests: `test_outro_router.py:230-255` (incl. orphan cleanup assert) + unit `tests/unit/configuration/test_outro_validator.py:70-91`. |
| 8 | New table `agency_intro_outro_assets`, UNIQUE `(agency_id, kind)`, `kind` enum/check incl. `'intro'` and `'outro'` | ✅ | `alembic/versions/20260515_0002_agency_outro_assets.py:41-79` — `UniqueConstraint("agency_id","kind")` (`:61-65`), `CheckConstraint("kind IN ('intro','outro')")` (`:66-69`), `CheckConstraint("source IN ('uploaded','brand_card','none')")` (`:70-73`). FK to `agencies(id)` ON DELETE CASCADE (`:46-49`). |
| 9 | `brand_card` outro: render skips concat AND logs a warning | ✅ skip + ✅ warning logged in ingest (not renderer) | Skip: `modules/rendering/application/frame_composition.py:155-163` — concat only runs when `outro_source == "uploaded" AND outro_local_path is not None`. Warning: `modules/reels/application/use_cases/ingest_property_into_reel.py:1090-1095` — emits `logger.warning("Outro source 'brand_card' is reserved for a future feature; ...")` and returns `(None, "brand_card", 0)` so the renderer never sees a path. Renderer-level test for skip: `tests/integration/rendering/test_render_with_outro.py:309-326`. **NOTE:** the warning emission is covered by the ingest call site, not by a dedicated `caplog` assertion in the test; the log line is grep-verified and lives at the only point of truth. Non-blocking nit. |
| 10 | Concat path `concat_outro_to_reel` in `modules/rendering/infrastructure/ffmpeg/outro_concat.py` pre-normalizes geometry/SAR/fps/audio BEFORE concat demuxer | ✅ | `outro_concat.py:35-114`. Normalization at `_normalize_outro` (`:117-190`): `scale=...,pad=...,setsar=1,fps={fps},format=yuv420p`, AAC 44.1kHz stereo, silent-track fallback when source has no audio (`:178-181`). Concat demuxer at `_run_concat_demuxer` (`:202-227`) uses `-f concat -safe 0 -i list -c copy`. |
| 11 | Concat invoked only when `outro_source='uploaded' AND outro_enabled=true AND blob present` | ✅ | Conditional in renderer: `frame_composition.py:155-163` (`outro_source == "uploaded" and outro_local_path is not None`). Upstream gate in ingest (`ingest_property_into_reel.py:1086-1111`): both `defaults.outro_enabled` AND `asset.source == "uploaded"` AND `resolve_agency_intro_outro_local_path` returning a real path are required; otherwise `outro_local_path` stays `None` and the renderer skip path runs. |
| 12 | Storage: `{site_layout_root}/{agency_id}/outro/...`; DELETE removes the blob; re-upload replaces (no orphan) | ✅ | `shared/storage/site_layout.py:173-198` (`resolve_agency_intro_outro_destination`) → `workspace/generated_media/_agency_{kind}/{safe_agency}/<filename>`; object_key shaped `agencies/{safe_agency}/{kind}/{filename}`. Replace-no-orphan: `upload_outro_video.py:224-230` unlinks prior blob when `previous.object_key != new object_key`. Test verifies "only the new one remains": `test_outro_router.py:258-294`. |
| 13 | Migration `20260515_0002` chained on `20260515_0001`; `upgrade head && downgrade -1 && upgrade head` clean | ✅ | `down_revision = "20260515_0001"` at `alembic/versions/20260515_0002_agency_outro_assets.py:26`. Re-run live against `miapp_test` Postgres: see §3 below. |

---

## 2. Hard-rule audit

| Rule | Verdict | Evidence |
|---|---|---|
| No `session.commit()` inside repositories | ✅ | `grep -n "session.commit" modules/configuration/infrastructure/intro_outro_asset_repository.py modules/configuration/application/use_cases/upload_outro_video.py modules/configuration/application/use_cases/delete_outro_video.py modules/configuration/application/use_cases/read_outro_asset.py` → 0 hits. |
| No legacy imports | ✅ | `init.sh` step 4: `0 imports legacy en apps|modules|shared|tests`. New code uses only `modules.{configuration,reels,rendering}.{domain,application,infrastructure,transport}`, `shared.{db,errors,storage,observability}`, `apps.api.*`. |
| Inter-module rule (no module imports from another module's `application/`/`infrastructure/`) | ✅ for new code | All imports inside the new files (`outro_router.py`, `upload_outro_video.py`, `delete_outro_video.py`, `read_outro_asset.py`, `intro_outro_asset_repository.py`, `outro_concat.py`) stay within their own bounded context or hit `shared/`. `frame_composition.py:42` imports `from modules.rendering.infrastructure.ffmpeg.outro_concat` (intra-rendering, fine). `ingest_property_into_reel.py` was already crossing into `modules.rendering.infrastructure` pre-feature-33 (lines 81, 739); feature 33 adds no new violation — the outro asset is read via `uow.configuration.intro_outro_assets`/`uow.configuration.defaults` (UoW namespace, not a direct cross-module import). |
| Composition only in `apps/api/app_factory.py` and `apps/worker/runtime.py` | ✅ | Outro router wired only at `apps/api/app_factory.py:410-416`; renderer wiring inside `frame_composition.py` (rendering's own composition site, not cross-app). |
| ORM model + migration must agree (no drift) | ✅ (vacuously) | `agency_intro_outro_assets` is **not** mapped in `shared/db/orm.py`, consistent with siblings `agency_reel_defaults`, `agency_music_tracks`, etc. The repository uses raw SQL via `sqlalchemy.text(...)` (see `intro_outro_asset_repository.py:53-167`), so there is no Python ORM contract that could drift from the DDL. Implementer's report calling out an "ORM model" in §3 is misleading (no `sa.Table`/declarative is added); the repository column list matches the migration verbatim. |
| Migration reversible | ✅ | `downgrade()` at `20260515_0002_agency_outro_assets.py:82-88` drops the index, drops the table, drops the `outro_enabled` column. Verified end-to-end (§3). |
| No test deleted or weakened | ✅ | `git status -s tests/ \| grep -E '^\s?D '` → empty. Only additions to `tests/integration/configuration/_client.py` (mount outro router) and `tests/support/postgres.py` (add table to `ACTIVE_TABLES`); 25 new tests added. |

---

## 3. Verification re-run (live, by reviewer)

### 3.1 Outro-focused pytest

```
$ .venv/bin/python -m pytest tests/integration/configuration/test_outro_router.py \
    tests/integration/rendering/test_render_with_outro.py \
    tests/unit/configuration/test_outro_validator.py -q -v
...
tests/integration/configuration/test_outro_router.py ..........          [ 40%]
tests/integration/rendering/test_render_with_outro.py .....              [ 60%]
tests/unit/configuration/test_outro_validator.py ..........              [100%]
25 passed in 20.05s
```

Coverage spot-check (test names confirm leader's MIME / size / duration /
replace / delete / render-with / without / brand_card-skip matrix):

- MIME 422: `test_outro_upload_rejects_unsupported_mime_with_422`
- Size 413: `test_outro_upload_rejects_payload_over_50mb_with_413`
- Duration 422 + orphan cleanup: `test_outro_upload_rejects_duration_above_10_seconds`
- Replace (no orphan): `test_outro_upload_replaces_previous_blob`
- Delete (metadata + blob): `test_outro_delete_clears_metadata_and_removes_blob`
- Render-with: `test_renderer_invokes_outro_concat_when_uploaded_and_enabled`,
  `test_concat_outro_to_reel_produces_combined_duration` (real ffmpeg)
- Render-without: `test_renderer_skips_outro_concat_when_path_is_none`,
  `test_renderer_skips_outro_concat_when_source_is_none`
- `brand_card` skip: `test_renderer_skips_outro_concat_when_source_is_brand_card`
- Auth: `test_outro_endpoints_require_auth`
- 404s: `test_outro_file_returns_404_when_nothing_uploaded`,
  `test_outro_upload_returns_404_for_unknown_agency`
- Validator unit: MIME (mp4, mov, case-insensitive, invalid, empty),
  size (>50MB), duration (boundaries, zero, above max, negative).

### 3.2 Alembic round-trip

```
$ .venv/bin/python -m alembic upgrade head
...

$ .venv/bin/python -m alembic downgrade -1
INFO  [alembic.runtime.migration] Running downgrade 20260515_0002 -> 20260515_0001,
      Create ``agency_intro_outro_assets`` table + ``outro_enabled`` flag.

$ .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 20260515_0001 -> 20260515_0002,
      Create ``agency_intro_outro_assets`` table + ``outro_enabled`` flag.
```

Clean.

### 3.3 Readiness

```
$ .venv/bin/python -m apps.api --check
... FFMPEG: /usr/bin/ffmpeg
EXIT 0

$ .venv/bin/python -m apps.worker --check
... Worker --check OK: kinds=email_send, reel_publish, scripted_render
... outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
EXIT 0
```

### 3.4 Full `init.sh`

```
$ bash ./init.sh
...
3 failed, 943 passed, 14 warnings in 477.39s (0:07:57)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

The 3 baseline-flaky tests
(`test_http_surface_contract::test_frontend_api_requests_target_existing_backend_routes`,
`test_http_transport::test_health_endpoints_*`) match the documented pre-existing
flakes (REFACTOR_STATUS.md §324 baseline). Total **943 passed** matches the
implementer's report verbatim.

---

## 4. Acceptance checklist (from `feature_list.json` id=33)

- ✅ `POST /outro/upload` con multipart MP4 5s → 200 con `{outro_object_key, outro_duration_seconds, outro_source: 'uploaded'}`.
  - Evidence: `test_outro_router.py:50-105` (`test_outro_upload_happy_path_returns_metadata_and_persists_blob`).
- ✅ `GET /outro/file` devuelve los bytes del último upload.
  - Evidence: `test_outro_router.py:108-136` asserts payload byte-equality + `Content-Type: video/mp4`.
- ✅ `DELETE /outro` limpia metadata (source → `'none'`, object_key NULL) y borra blob.
  - Evidence: `test_outro_router.py:138-186`; also re-fetches `/defaults` and confirms `outro_*` reset.
- ✅ Validación: mime no video → 422; duración >10s → 422; tamaño >50MB → 413.
  - Evidence: `test_outro_router.py:189-255` + unit tests.
- ✅ Migración up/down/up funcional.
  - Evidence: §3.2 above.
- ✅ Render con `outro_enabled=true` y `source='uploaded'` produce MP4 final cuya duración = duración_base_reel + outro_duration.
  - Evidence: `tests/integration/rendering/test_render_with_outro.py:106-281` (`test_concat_outro_to_reel_produces_combined_duration`, shells real ffmpeg/ffprobe).
- ✅ Render con `outro_enabled=false` o `source='none'` NO concatena nada.
  - Evidence: `test_render_with_outro.py:329-357`.
- ✅ `pytest -q` verde.
  - Evidence: §3.1 + §3.4.
- ✅ `apps.api --check` y `apps.worker --check` exit 0.
  - Evidence: §3.3.

---

## 5. Issues found

### Blocking

None.

### Non-blocking

1. **Implementer §3 mentions an "ORM model in `shared/db/orm.py`" — it does
   not exist.** `agency_intro_outro_assets` is accessed via raw `text(...)`
   SQL in the repository; no declarative `sa.Table` is added. This matches
   the pattern of the sibling tables and is fine, but the wording in the
   implementer report is misleading and should be tightened before the
   intro symmetry of feature 34 picks the same path. The migration is the
   single source of truth, which is what the leader's "no drift" rule
   demands (vacuously true).
2. **`brand_card` warning is logged in the ingest use case, not in the
   renderer.** `frame_composition.py` silently skips when
   `outro_source != "uploaded"`. The renderer-level test
   (`test_renderer_skips_outro_concat_when_source_is_brand_card`) verifies
   the skip but does NOT assert the warning is emitted. The warning lives
   at `ingest_property_into_reel.py:1090-1095` and is wired in the only
   place that resolves the asset, so the requirement is met — but a
   future intro feature should add a `caplog.records` assertion when
   `brand_card` lands to make the contract regression-proof.

### Nit

3. `upload_outro_video.py:340-342` has a `_ = safe_site_dirname` line whose
   only purpose is to silence an unused-import warning. The cleaner fix is
   to drop the import from line 46 (it is genuinely unused — the canonical
   path already comes from `resolve_agency_intro_outro_local_path`). Not
   worth blocking on; tightens on feature 34 rebase.
4. The renderer's `_append_outro_to_reel` (`frame_composition.py:353-390`)
   uses `combined_path.replace(reel_path)` followed by a `finally`-branch
   that re-checks `combined_path.exists()`. After a successful `replace`,
   `combined_path` is gone, so the `if` branch is a defensive no-op. Fine
   to leave, but it's the kind of zombie cleanup that's easy to delete in
   the next pass.

---

## 6. Open items for the leader

### 6.1 Manual smoke against `:8001`

```bash
AGENCY_ID=00000000-0000-0000-0000-000000000000
BEARER='Authorization: Bearer test-admin-token'
BASE=http://127.0.0.1:8001/v1/admin/agencies/${AGENCY_ID}

# Upload (5s fixture from the test suite)
curl -fsS -X POST "$BASE/outro/upload" \
  -H "$BEARER" \
  -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"

# /defaults round-trip
curl -fsS "$BASE/defaults" -H "$BEARER" | python -m json.tool

# Stream back + verify duration via ffprobe
curl -fsS "$BASE/outro/file" -H "$BEARER" -o /tmp/echo_outro.mp4
ffprobe -v error -show_entries format=duration \
  -of default=noprint_wrappers=1:nokey=1 /tmp/echo_outro.mp4

# Toggle outro_enabled and ingest a property → render output ≈ base_reel + 5s
curl -fsS -X PUT "$BASE/defaults" -H "$BEARER" \
  -H 'Content-Type: application/json' -d '{"outro_enabled": true}'

# Cleanup
curl -fsS -X DELETE "$BASE/outro" -H "$BEARER"
```

Reminder per `CLAUDE.md`: do NOT restart `:8001` yourself; the leader must
defer to the user for service restarts.

### 6.2 Considerations for feature 34 (intro)

- The new table `agency_intro_outro_assets` is shaped for symmetric reuse:
  `INSERT ... ON CONFLICT (agency_id, 'intro') ...` lands directly. The
  helper `resolve_agency_intro_outro_destination` (`shared/storage/site_layout.py:173`)
  already accepts `kind='intro'` and writes under `_agency_intro/{safe_agency}/`.
- The renderer concat helper `concat_outro_to_reel` is outro-named but
  semantically a "normalised-segment concat". Feature 34 should either:
  (a) extract `concat_segments_to_reel(prefix=None, suffix=None)` or
  (b) duplicate-with-rename to `concat_intro_to_reel` and concat in the
  reverse order. Option (a) is cleaner if the leader wants
  `intro+outro` simultaneous (acceptance criterion in `feature_list.json`
  id=34 explicitly demands this).
- `outro_enabled` lives on `agency_reel_defaults`; `intro_enabled` already
  exists there too — the symmetry is intentional. No new column needed
  on the defaults table for intro.
- The renderer-level test for the `brand_card` skip would gain a
  `caplog.set_level(logging.WARNING)` + record assertion when intro adds
  its own `brand_card`-pending branch. Pick that up as a tightening
  during feature 34 review.

---

## Closing

Feature 33 is **APPROVED**. The HTTP contract, validation matrix,
storage layout, concat pipeline, schema migration round-trip, and full
`init.sh` baseline all check out. Two non-blocking nits and two cosmetic
items are listed in §5 for follow-up alongside feature 34.
