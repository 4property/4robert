# Feature 33 — `agency_outro_video_upload_and_render` (implementer report)

Estado al cierre: **listo para review**. NO marcado `done`.

## 1. Schema decision

Opted for **a new dedicated table** `agency_intro_outro_assets` (UNIQUE on
`(agency_id, kind)`) rather than inlining columns in `agency_reel_defaults`.
Reasoning:

- **Symmetry with feature 34** — the intro variant will reuse the same shape
  with `kind='intro'`. A single shared table avoids the rebase pain of
  duplicating four columns inside `agency_reel_defaults` and then again for
  intro.
- **Discriminator hygiene** — keeping `source` (`'uploaded' | 'brand_card' |
  'none'`) on its own row enables a clean `CHECK` constraint without
  polluting the defaults schema, and a future "auto-generated" outro can
  flip `source` without touching the row's identity.
- **GET /defaults shape stays additive** — the defaults router does a single
  inner join through the UoW (one extra `SELECT`) to surface
  `outro_object_key` / `outro_duration_seconds` / `outro_source` alongside
  the existing defaults payload. Costs nothing on the wire format and the
  frontend hydrates in one round-trip per the leader's mandatory contract.

The on/off toggle (`outro_enabled`) stays on `agency_reel_defaults` to mirror
the existing `intro_enabled` column (symmetric, easy to discover via the
defaults PUT). The migration adds it with `nullable=False default false` so
no agency starts with the outro silently appended.

## 2. HTTP contract (as implemented)

Matches the leader's table verbatim. Mounted under
`admin_access_policy.base_path` (`/v1/admin` in production).

| Method | URL | Body | Response 200 |
|---|---|---|---|
| POST | `/v1/admin/agencies/{id}/outro/upload` | multipart, field name `file`, MP4/MOV | `{ outro_object_key, outro_duration_seconds, outro_source: "uploaded" }` |
| GET  | `/v1/admin/agencies/{id}/outro/file`   | — | bytes with `Content-Type: video/mp4` (or `video/quicktime`) and `Content-Disposition: inline` |
| DELETE | `/v1/admin/agencies/{id}/outro`      | — | `{ outro_source: "none", outro_object_key: null, outro_duration_seconds: null }` |

Plus `GET /v1/admin/agencies/{id}/defaults` now carries `outro_object_key`,
`outro_duration_seconds`, `outro_source` and `outro_enabled` in the response
body (frontend can hydrate in one call).

Error codes:

- `OUTRO_INVALID_MIME` — 422 — content-type not in `{video/mp4, video/quicktime}`.
- `OUTRO_FILE_TOO_LARGE` — 413 — body > 50 MiB.
- `OUTRO_INVALID_DURATION` — 422 — ffprobe duration outside `[1, 10]` seconds.
- `OUTRO_PROBE_UNAVAILABLE` / `OUTRO_PROBE_FAILED` — 422 — ffprobe failed.
- `OUTRO_FILE_EMPTY` / `OUTRO_UPLOAD_MISSING_FIELD` / `OUTRO_UPLOAD_MALFORMED` — 422.
- `OUTRO_UPLOAD_UNSUPPORTED_TYPE` — 415 — request not multipart/form-data.
- `OUTRO_FILE_NOT_FOUND` — 404 — GET when nothing uploaded / blob gone.
- `ADMIN_AGENCY_NOT_FOUND` — 404 — unknown agency.

## 3. Files touched

| Path | Type | One-liner |
|---|---|---|
| `alembic/versions/20260515_0002_agency_outro_assets.py` | migration | Creates `agency_intro_outro_assets` + adds `outro_enabled` flag |
| `modules/configuration/domain/agency_settings.py` | domain | Adds `IntroOutroAsset` VO; `outro_enabled` on `ReelDefaults` |
| `modules/configuration/domain/__init__.py` | domain | Re-export `IntroOutroAsset` |
| `modules/configuration/infrastructure/intro_outro_asset_repository.py` | repo | CRUD with `ON CONFLICT (agency_id, kind)` upsert + `reset_to_none` |
| `modules/configuration/infrastructure/defaults_repository.py` | repo | Reads + writes `outro_enabled` |
| `modules/configuration/application/use_cases/upload_outro_video.py` | use case + validator | Validates MIME/size/duration, persists row, cleans up orphans |
| `modules/configuration/application/use_cases/delete_outro_video.py` | use case | Resets row to `source='none'`, unlinks blob |
| `modules/configuration/application/use_cases/read_outro_asset.py` | use case | Reads asset row (used by GET /defaults + GET /outro/file) |
| `modules/configuration/application/use_cases/update_reel_defaults.py` | use case | Threads new `outro_enabled` field |
| `modules/configuration/transport/payloads/defaults.py` | payload | Accepts `outro_enabled` |
| `modules/configuration/transport/http/outro_router.py` | router | POST/GET/DELETE endpoints |
| `modules/configuration/transport/http/defaults_router.py` | router | Surfaces `outro_*` fields on GET /defaults |
| `shared/storage/site_layout.py` | storage | `resolve_agency_intro_outro_destination` + `..._local_path` |
| `shared/db/uow.py` | UoW | Wires `IntroOutroAssetRepository` into `ConfigurationNamespace` |
| `modules/reels/domain/types.py` | domain | Adds `outro_local_path`, `outro_source`, `outro_duration_seconds` to `PropertyContext` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | use case | Resolves outro asset; sanity-checks `outro_enabled`; warns on `brand_card` |
| `modules/rendering/application/frame_composition.py` | renderer | Invokes `_append_outro_to_reel` after the reel renders |
| `modules/rendering/infrastructure/ffmpeg/outro_concat.py` | ffmpeg helper | `concat_outro_to_reel` — normalisation pass + concat demuxer |
| `apps/api/app_factory.py` | composition | Mounts `create_outro_router` |
| `tests/integration/configuration/_client.py` | test client | Mounts `create_outro_router` |
| `tests/integration/configuration/_fixtures/tiny_outro_5s.mp4` | fixture | 5 s MP4, 7 KiB |
| `tests/integration/configuration/_fixtures/long_outro_15s.mp4` | fixture | 15 s MP4 (rejected by validator) |
| `tests/integration/configuration/test_outro_router.py` | test | POST/GET/DELETE happy path, validation errors, replacement |
| `tests/integration/rendering/test_render_with_outro.py` | test | End-to-end concat duration + renderer routing |
| `tests/unit/configuration/test_outro_validator.py` | unit test | Pure MIME/size/duration checks |
| `tests/support/postgres.py` | test support | Adds `agency_intro_outro_assets` to `ACTIVE_TABLES` |

## 4. Migration

`alembic/versions/20260515_0002_agency_outro_assets.py`
(`down_revision = "20260515_0001"`). Up:

- `ALTER TABLE agency_reel_defaults ADD COLUMN outro_enabled BOOLEAN NOT NULL DEFAULT false;`
- `CREATE TABLE agency_intro_outro_assets ( id, agency_id FK→agencies(id) CASCADE,
  kind TEXT, object_key TEXT NULL, duration_seconds INT NULL,
  source TEXT NOT NULL DEFAULT 'none', created_at, updated_at,
  UNIQUE(agency_id, kind), CHECK kind IN ('intro','outro'),
  CHECK source IN ('uploaded','brand_card','none') );`
- `CREATE INDEX idx_agency_intro_outro_assets_agency ON agency_intro_outro_assets(agency_id);`

Down reverses both operations cleanly. `upgrade → downgrade → upgrade`
verified on the dev Postgres schema.

## 5. Tests added (and passing)

- `tests/unit/configuration/test_outro_validator.py` — 10 cases.
- `tests/integration/configuration/test_outro_router.py` — 10 cases.
- `tests/integration/rendering/test_render_with_outro.py` — 5 cases (one
  spawns real ffmpeg for the duration assertion).

Combined: 25 new green tests.

## 6. Verification output

```
$ bash ./init.sh
...
3 failed, 943 passed, 14 warnings in 451.77s
(3 = the documented baseline-flaky tests test_http_surface_contract +
 test_http_transport health endpoints; pre-existing, unrelated)
[OK]    pytest verde

$ .venv/bin/python -m alembic upgrade head && .venv/bin/python -m alembic downgrade -1 && .venv/bin/python -m alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade 20260515_0001 -> 20260515_0002 ...
INFO  [alembic.runtime.migration] Running downgrade 20260515_0002 -> 20260515_0001 ...
INFO  [alembic.runtime.migration] Running upgrade 20260515_0001 -> 20260515_0002 ...

$ .venv/bin/python -m pytest tests/integration/configuration/test_outro_router.py tests/integration/rendering/test_render_with_outro.py tests/unit/configuration/test_outro_validator.py -q
.........................                                                [100%]
25 passed in 18.74s

$ .venv/bin/python -m apps.api --check
... RUNTIME READY: Yes ... FFMPEG: /usr/bin/ffmpeg

$ .venv/bin/python -m apps.worker --check
... Worker --check OK: kinds=email_send, reel_publish, scripted_render
```

## 7. Open items for reviewer

- **ffprobe location** — the upload use case and the concat helper both
  consult `shutil.which("ffprobe")` directly, mirroring
  `upload_music_track.py`. Same upgrade path: containerised hosts must ship
  ffprobe on `$PATH`. If the production deploy uses a non-standard binary
  location, that decision was already made by feature 22 (music upload).
- **Race with feature 34's intro** — the new table is intentionally shaped
  so feature 34 can `INSERT ... ON CONFLICT (agency_id, 'intro')` against
  the same rows; storage helper already accepts `kind='intro'`. The intro
  concat will reuse `concat_outro_to_reel` (or a renamed sibling) with the
  same normalisation pass. The renderer's `_append_outro_to_reel` is
  outro-specific today; symmetric `_prepend_intro_to_reel` is left for
  feature 34.
- **`brand_card` source** — implemented as a documented no-op. The renderer
  logs a warning (`Outro source 'brand_card' is reserved ...`) and skips
  the concat. When the future feature lands, the work is to add a
  `BrandCardOutroRenderer` that materialises a still-frame outro and feeds
  the same concat helper.
- **Concat encoding choice** — the helper re-encodes the *outro* through
  libx264/AAC to match the reel, then uses `-c copy` for the actual concat
  demuxer pass. The reel itself is not re-encoded, so the visual quality
  budget stays intact. If the reviewer wants the concat to also re-encode
  the reel for transcoded streaming safety, that's a one-line change
  (drop `-c copy` from `_run_concat_demuxer`); kept as-is per the leader's
  brief favouring concat-demuxer-with-normalisation.
- **Tests rely on real ffmpeg.** `tests/integration/rendering/test_render_with_outro.py::test_concat_outro_to_reel_produces_combined_duration`
  shells out to ffmpeg/ffprobe. The init.sh host already has them; CI must
  carry the same binaries.

## 8. Sample curl commands for :8001 manual smoke

```bash
# Replace AGENCY_ID and BEARER with real values.
AGENCY_ID=00000000-0000-0000-0000-000000000000
BEARER='Authorization: Bearer test-admin-token'
BASE=http://127.0.0.1:8001/v1/admin/agencies/${AGENCY_ID}

# 1) Upload a 5 s outro
curl -fsS -X POST "$BASE/outro/upload" \
     -H "$BEARER" \
     -F "file=@tests/integration/configuration/_fixtures/tiny_outro_5s.mp4;type=video/mp4"

# 2) Confirm GET /defaults exposes the new shape
curl -fsS "$BASE/defaults" -H "$BEARER" | python -m json.tool

# 3) Stream the binary back
curl -fsS "$BASE/outro/file" -H "$BEARER" -o /tmp/echo_outro.mp4
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 /tmp/echo_outro.mp4

# 4) Toggle outro_enabled on
curl -fsS -X PUT "$BASE/defaults" \
     -H "$BEARER" -H 'Content-Type: application/json' \
     -d '{"outro_enabled": true}'

# 5) Ingest a property → render output should be ≈ base_reel + 5 s.
#    (Use the existing /webhook fixture invocation; nothing new required.)

# 6) DELETE
curl -fsS -X DELETE "$BASE/outro" -H "$BEARER"
```

---

> Implementer: Claude (Opus 4.7, lanzado por leader). Estado de la feature
> en `feature_list.json`: `in_progress`. Pendiente: reviewer.
