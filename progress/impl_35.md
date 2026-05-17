# Feature 35 — per_reel_photos_override (impl report)

- Status in `feature_list.json`: `in_progress` (NOT `done`; reviewer must approve).
- Agent: Claude implementer.
- Alembic head after migration: `20260515_0003 (head)`.

## 1. HTTP contract (as implemented)

| Method | URL | Body | 200 response |
|---|---|---|---|
| `PATCH` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/photos` | `{ "photos": [{ "position": int, "selected": bool }, ...] }` (or `{"photos": null}` / `{"photos": []}` to clear) | `{ "photos_override": [...] \| null, "render_status": "pending", "publish_enqueued": true, "event_id": "...", "job_id": "..." }` |

Error responses:
- **404 `ADMIN_AGENCY_NOT_FOUND`** — agency does not exist (`_admin_support.ensure_agency_exists`).
- **404 `ADMIN_REEL_NOT_FOUND`** — reel does not exist (`_admin_support.reel_not_found_error`).
- **409 `PHOTOS_OVERRIDE_LOCKED`** — `workflow_state == "approved"` OR `publish_status == "published"`. Body: `{"error": "PHOTOS_OVERRIDE_LOCKED", "detail": "Cannot edit photos for a reel that has been approved or published.", "hint": "...", "details": {"context": {"agency_id": "...", "site_id": "...", "source_property_id": int, "workflow_state": "...", "publish_status": "..."}}}`.
- **422** — Pydantic shape errors (extra fields, non-bool `selected`, duplicate positions) AND use-case validation (length mismatch / out-of-range / no photos).

When prerequisites are missing (no GHL connection / no raw payload) the override is still persisted and the response stays 200 with `publish_enqueued=false` plus `reason=PUBLISH_PREREQUISITES_MISSING` and `hint` (same shape as `update_reel_music_override`).

Matches leader's table exactly: 200 body has `photos_override` + `render_status`.

## 2. Files touched

| Path | Type | One-line description |
|---|---|---|
| `alembic/versions/20260515_0003_reels_photos_override.py` | migration | adds `reels.photos_override JSONB NULL`; `down_revision="20260515_0002"`. |
| `modules/reels/domain/reel_state.py` | domain | adds `photos_override: list[dict[str, Any]] \| None = None`. |
| `modules/reels/domain/types.py` | domain | adds `PropertyContext.photos_override: tuple[tuple[int, bool], ...] \| None = None`. |
| `modules/reels/infrastructure/reel_state_repository.py` | infra | reads/writes the new JSONB column (`_jsonb_to_optional_list`, `_photos_override_to_jsonb_param`), threaded through `save / update_publish_status / update_workflow_state / save_local_artifacts`. |
| `modules/reels/application/use_cases/_ingest_property_assets.py` | use case | preserves `music_id` + `photos_override` on the ingested ReelState (pre-existing bug for `music_id` swept up). |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | use case | adds `_coerce_photos_override` helper; forwards `existing_state.photos_override` onto `PropertyContext`. |
| `modules/reels/application/use_cases/update_reel_photos_override.py` | use case (new) | the PATCH-driven use case: agency check → reel check → 409 gate → 422 validation against `len(property_images)` → save → re-enqueue via the same machinery feature 25 uses. |
| `modules/reels/transport/payloads/reel_photos_override.py` | payload (new) | strict Pydantic `ReelPhotosOverridePayload` with `extra="forbid"` on body and each entry. |
| `modules/reels/transport/http/admin_reels_router.py` | transport | new `PATCH .../photos` endpoint with the same auth dependency as the sibling override endpoints. |
| `modules/rendering/application/frame_composition.py` | renderer | applies `context.photos_override` to `prepared_assets.selected_photo_paths` before constructing the manifest. New helper `_apply_photos_override`. |
| `tests/integration/reels/test_reel_photos_override.py` | tests (new) | 13 tests: happy path, clear (null + []), 422 (gap, duplicate, out-of-range, non-bool, extra fields × 2), 409 (approved, published), 404 (reel, agency). |
| `tests/integration/rendering/test_render_with_photos_override.py` | tests (new) | 4 tests: reversed order, drop unselected, default fallback when override is None, defensive fallback when override is all-false. |
| `progress/current.md` | bitácora | appended feature 35 entry. |
| `feature_list.json` | meta | feature 35 flipped to `in_progress`. |

## 3. Migration

`20260515_0003_reels_photos_override.py`:
- `down_revision = "20260515_0002"`.
- `upgrade()` adds `Column("photos_override", postgresql.JSONB, nullable=True)` to `reels`. No server default — `NULL` is the canonical "no override" sentinel.
- `downgrade()` drops the column.
- Round-trip verified: `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` clean (final head = `20260515_0003`).

## 4. Renderer call site

`modules/rendering/application/frame_composition.py::DefaultMediaRenderer._render_reel`. The reorder step happens between `prepared_assets` arriving from `PrepareReelAssetsUseCase` and the slide / manifest construction:

```python
prepared_assets = _apply_photos_override(
    prepared_assets, override=context.photos_override
)
selected_slides = build_local_selected_slides(...)
property_render_data = self._build_render_data(...)
```

`_apply_photos_override` (same file, just below `DefaultMediaRenderer`) returns the input unchanged when `override` is `None` / empty / `selected_photo_paths` is empty. Otherwise it rebuilds the tuple in the override's array order, dropping `selected=false` entries and skipping out-of-range positions with a warning log. If every entry is filtered out it falls back to the original tuple — the override layer must never produce an empty reel.

`context.photos_override` is hydrated in `ingest_property_into_reel.py` from the persisted `reels.photos_override` JSONB via the new `_coerce_photos_override` helper. The job's `publish_context` does **not** carry the override: the renderer reads the row directly through the ingest's `existing_state` peek, which is the canonical "current" override at dispatch time. This avoids stale `publish_context` reads if the override is PATCHed again between enqueue and dispatch.

## 5. Tests added

`tests/integration/reels/test_reel_photos_override.py` (13):
- happy path: PATCH with mix of selected=true/false → 200 with `render_status="pending"`, `publish_enqueued=true`, persisted override matches body.
- clear semantics: `photos=null` → override cleared; `photos=[]` → override cleared.
- 422: gap (`[{0,t},{2,t}]`), duplicate (`[{0,t},{0,t}]`), out-of-range (`[{0,t},{99,t}]` for N=2), wrong type (`[{0,"yes"}]`), extra entry field (`[{0,t,"extra":"x"}, {1,t}]`), extra body key.
- 409 `PHOTOS_OVERRIDE_LOCKED`: `workflow_state='approved'`; `publish_status='published'`.
- 404: unknown reel; unknown agency.

`tests/integration/rendering/test_render_with_photos_override.py` (4):
- Reversed override `(4,3,2,1,0)` → manifest receives reversed photos.
- Mixed selected flags `(0,t),(1,f),(2,t),(3,f),(4,t)` → manifest receives only (0,2,4).
- `photos_override=None` → manifest preserves the default prepared order.
- All-`selected=false` → falls back to default order (no empty reel).

The renderer test stubs out the heavy primitives (`prepare_reel_render_assets`, `generate_property_reel_from_data`, `write_property_reel_manifest_from_data`, `generate_property_poster_from_data`) and asserts on the `property_render_data.selected_image_paths` tuple — the same input that feeds the manifest and the ffmpeg slide builder.

## 6. Verification output (tails)

```
$ .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
Running upgrade 20260515_0002 -> 20260515_0003, Add ``reels.photos_override`` JSONB column (feature 35).
Running downgrade 20260515_0003 -> 20260515_0002, Add ``reels.photos_override`` JSONB column (feature 35).
Running upgrade 20260515_0002 -> 20260515_0003, Add ``reels.photos_override`` JSONB column (feature 35).
$ .venv/bin/alembic current
20260515_0003 (head)

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_photos_override.py tests/integration/rendering/test_render_with_photos_override.py -q
.................                                                        [100%]
17 passed in 21.51s

$ bash ./init.sh
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 988 passed, 14 warnings in 496.09s (0:08:16)
[OK]    pytest verde
[OK]    Entorno listo.

$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
```

Baseline preserved: **988 passed = 971 (pre-feature-35) + 17 new** + 3 known-flaky. The 3 known-flaky failures are identical to the pre-feature baseline (`http_surface_contract` checks against a Windows path that does not resolve on this Linux host; `http_transport health_endpoints*` are pre-existing flakes — same hash as the messages logged in earlier features 32-34).

## 7. Open items for the reviewer

- **Feature 36 / 37 chaining.** My migration uses `down_revision = "20260515_0002"` and outputs `20260515_0003`. Feature 36 (`subtitles_override`) should chain `down_revision = "20260515_0003"` and pick a `20260515_0004_*` slug. Feature 37 (`slides_override`) chains after that. Both add a single nullable JSONB column to `reels` so they don't conflict with this one — but they DO need to propagate the new column through every `ReelState` constructor in `reel_state_repository.py` and the ingest's `_build_ingested_reel_state` the same way I did. I left a sweep-up fix in `_build_ingested_reel_state` to preserve `music_id` (pre-existing bug — feature 25 forgot to add it there), so 36/37 should double-check the pattern still holds.
- **`render_status` flip.** The leader's table says `render_status: pending` in the 200 response. I implemented that as a direct field assignment on the saved `ReelState` (the existing music/descriptions overrides don't touch `render_status` — they piggyback on the worker's render cycle). If the reviewer wants the music override to flip the status too for symmetry, that's a separate ticket.
- **`publish_context` shape.** I do NOT add a `photos_override` key to the `reel_publish` job's `publish_context`. The renderer pulls the persisted column straight via the ingest's `existing_state` peek (same row the use case just wrote). If feature 36/37 decide they need their overrides to travel on the job payload (e.g. for audit), they can add a `subtitles_override` / `slides_override` key without touching mine.
- **Override semantics under re-ingest.** A re-ingest from a fresh WordPress payload preserves the previous override because `_build_ingested_reel_state` now forwards `state.photos_override`. The reviewer may want to add an explicit test for "re-ingest preserves override" — out of scope for feature 35 but worth flagging.
- **Photo count source.** The use case validates against `len(uow.catalog.images.list_for_property(...))` (the canonical "N" the admin photos endpoint also returns). If the renderer's prepared photo set ends up smaller (Gemini curates to a subset), the override positions beyond the curated count are skipped at render time with a warning — this is the documented fallback. The reviewer should sanity-check whether feature 35 should validate against the curated set instead — current behaviour matches the frontend's UX (positions come from the photos list shown in the admin UI).
- **Workflow gate set.** Per the leader's brief, `_LOCKED_WORKFLOW_STATES = {"approved"}` and `_LOCKED_PUBLISH_STATUSES = {"published"}` — stricter than feature 25's `_EDITABLE_PUBLISH_STATUSES` (which also locks `failed` / `pending_publish` / etc.). This is deliberate: photos can still be edited after a render failure, only the post-approval / post-publish path is locked. If the product team wants this aligned with the music gate, change `_LOCKED_*` in `update_reel_photos_override.py`.

## 8. Sample curl (against :8001)

```bash
# Set the override (3 photos, drop position 1):
curl -fsS -X PATCH \
  http://127.0.0.1:8001/v1/admin/agencies/ag-123/reels/ckp.ie/42/photos \
  -H "Authorization: Bearer ${ADMIN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "photos": [
      {"position": 0, "selected": true},
      {"position": 1, "selected": false},
      {"position": 2, "selected": true}
    ]
  }'

# Clear the override:
curl -fsS -X PATCH \
  http://127.0.0.1:8001/v1/admin/agencies/ag-123/reels/ckp.ie/42/photos \
  -H "Authorization: Bearer ${ADMIN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"photos": null}'

# Expected 409 when re-trying after the reel was approved:
curl -fsS -X PATCH \
  http://127.0.0.1:8001/v1/admin/agencies/ag-123/reels/ckp.ie/42/photos \
  -H "Authorization: Bearer ${ADMIN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"photos": [{"position":0,"selected":true},{"position":1,"selected":true},{"position":2,"selected":true}]}'
# → 409 {"error":"PHOTOS_OVERRIDE_LOCKED", ...}
```
