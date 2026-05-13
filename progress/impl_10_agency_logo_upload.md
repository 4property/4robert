# Implementation report — Feature 10 `agency_logo_upload`

Status: implementation complete, **review pending** (NOT marked `done`).

## Scope delivered

1. **New multipart endpoint** `POST /v1/admin/agencies/{agency_id}/brand/logo`
   that accepts JPG/PNG <= 5 MB, persists the binary under
   `workspace/generated_media/_agency_branding/<safe_agency>/` and
   returns `{object_key, url}`.
2. **Companion GET endpoint** `GET /v1/admin/agencies/{agency_id}/brand/logo/file/{filename}`
   that streams the persisted logo back for previews (used by the `url`
   returned by POST).
3. **Rendering preference wiring**: when the agency has an uploaded
   logo, the reel renderer prefers it over the WordPress webhook URL;
   when not, falls back to the existing behaviour.
4. **Docs**: `docs/API.md` documents the new endpoint, the limits,
   and the "delete via empty string" contract.
5. **Tests**: 4 unit tests for the rendering preference + 10 integration
   tests for the upload/stream endpoints.

## Files created

| File | Kind |
|---|---|
| `modules/configuration/transport/http/brand_logo_router.py` | Router (POST upload + GET stream) |
| `tests/unit/rendering/test_branding_preference.py` | Unit tests |
| `tests/integration/configuration/test_brand_logo_router.py` | Integration tests |

## Files modified

| File | Change |
|---|---|
| `shared/storage/site_layout.py` | Added `resolve_agency_branding_destination` (returns `(object_key, Path)`) and `resolve_agency_branding_local_path` helpers + `AGENCY_BRANDING_UPLOAD_DIRNAME` constant. |
| `modules/rendering/infrastructure/runtime/branding.py` | `prepare_cover_logo_image` now prefers `property_data.agency_logo_local_path` before falling back to the webhook URL. |
| `modules/rendering/infrastructure/models.py` | Added `agency_logo_local_path: Path \| None` to `PropertyRenderData`. |
| `modules/rendering/application/frame_composition.py` | Forward `context.agency_logo_local_path` into `PropertyRenderData`. |
| `modules/reels/domain/types.py` | Added `agency_logo_local_path: Path \| None` to `PropertyContext`. |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | New `_resolve_agency_logo_local_path` helper that reads `agency_brand_settings.logo_object_key` from the UoW and resolves it to a real path; tolerates stubbed UoWs without the configuration namespace. |
| `apps/api/app_factory.py` | Register `create_brand_logo_router`. |
| `tests/integration/configuration/_client.py` | Mount the new router in the shared configuration test client. |
| `docs/API.md` | New section "Brand logo upload (feature 10)" with the full request/response/error reference and the deletion contract. |
| `feature_list.json` | Feature 10 moved to `in_progress`. |
| `progress/current.md` | Session log. |

## Decisions (non-obvious)

- **Router placement.** A new file `brand_logo_router.py` rather than
  extending `brand_router.py`. The logo upload is the project's first
  multipart endpoint, ships its own constants (`BRAND_LOGO_MAX_UPLOAD_BYTES`,
  allowed-suffix sets, custom error codes), and includes the GET streamer.
  Keeping the JSON-only Brand GET/PUT pair clean of multipart concerns
  makes the new router easier to grep for and easier to retire if S3
  eventually replaces the FS persistence.
- **FS-only helper, FS-agnostic signature.**
  `resolve_agency_branding_destination(*, workspace_dir, agency_id, filename)`
  returns the tuple `(object_key, local_path)` so the call site never
  has to know whether the backing store is the filesystem or, in the
  future, S3. A future remote backend swaps the helper's body without
  touching the router. The helper lives in `shared/storage/site_layout.py`
  because both the configuration transport (writer) and the reels
  application layer (reader, via `ingest_property_into_reel`) need it,
  and the inter-module rule forbids `modules/reels/application` from
  importing `modules/rendering/infrastructure`.
- **object_key format.** `agencies/<safe_agency>/logo-<sha1-12><ext>`
  where the digest is taken over the upload bytes. Same bytes
  ⇒ same key ⇒ same path, so a re-upload of an identical file is a
  no-op write. `safe_site_dirname` strips path-traversal characters
  from the agency identifier (re-using the existing site sanitiser).
- **`url` shape.** The endpoint returns an admin-served stream URL
  rather than a filesystem path because (a) nothing in the repo serves
  workspace folders via nginx today, (b) admin clients already use the
  bearer auth header so the GET handler can reuse
  `authorize_admin_request`, and (c) the URL is stable enough to embed
  in the agency UI as a `<img src=...>` preview.
- **Deletion via empty string.** The brand PUT already treats `None`
  as "do not touch"; trying to repurpose `null` as a delete signal
  would break every existing partial PUT call. The `agency_brand_settings`
  columns are `TEXT NOT NULL DEFAULT ''` so the empty string is the
  natural "no logo" sentinel — documented explicitly in
  `docs/API.md`.
- **No `python-multipart` dependency added.** The leader's rule
  prohibits new deps. FastAPI's `UploadFile` requires `python-multipart`,
  which is not pinned in `requirements.txt`. To keep the dep surface
  intact the router parses `multipart/form-data` with the stdlib
  `email.parser` module — adequate for the single-field upload contract.
- **Inter-module boundary.** `modules/reels/application` cannot import
  from `modules/rendering/infrastructure`. The helper that resolves
  an `object_key` to a local `Path` therefore lives in
  `shared/storage/site_layout.py`, not in `runtime/assets.py`. The
  resolver in `assets.py` (`resolve_cached_branding_destination`) is
  unrelated — it caches *downloaded* logos from webhook URLs, not
  admin uploads.

## Focal pytest output

```
$ .venv/bin/python -m pytest tests/unit/configuration/ tests/integration/configuration/ tests/unit/rendering/ -q
........................................................................ [ 42%]
........................................................................ [ 84%]
..........................                                               [100%]
170 passed in 71.81s (0:01:11)
```

```
$ FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh
...
[OK]    feature_list.json válido (12 features)
[OK]    Sin directorios legacy (services|application|repositories|core|domain)
[OK]    0 imports legacy en apps|modules|shared|tests
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
2 failed, 497 passed, 14 warnings in 218.01s (0:03:38)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

The only failures are the **2 preexisting health-router contract
mismatches** flagged by the leader; they live in `tests/integration/
test_http_transport.py` and predate this feature (the `/health`
payload now also reports `configured_worker_count`, which those tests
don't expect — orthogonal to feature 10).

`.venv/bin/python -m apps.api --check` and `.venv/bin/python -m
apps.worker --check` both exit 0.

## Cross-repo coordination

The frontend implementer (feature 9 `agency_logo_upload`) is running in
parallel. The leader noted that the initial front-end instruction
mentioned `null` as the delete operator; the back-end contract is
**empty-string `""`** (documented in `docs/API.md`). Coordination point
flagged in the impl report so the leader can request a CHANGES action
on the front side if needed.

## Out of scope (per leader)

- No alembic migration (`logo_object_key` and `intro_logo_object_key`
  already exist as `Text NOT NULL DEFAULT ''`).
- No changes to `BrandSettingsUpsertPayload` (spike confirmed the
  payload already accepts both keys).
- No S3 wiring; FS-only persistence with a future-proof helper
  signature.
