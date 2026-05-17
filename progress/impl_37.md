# Impl — feature 37 (`per_reel_slides_override`)

## 1. 6-point pattern checklist

| # | What | File:line | Status |
|---|------|-----------|--------|
| 1 | Alembic migration `20260515_0005_reels_manifest_override.py` adds `reels.manifest_override JSONB NULL`, `down_revision="20260515_0004"` | `alembic/versions/20260515_0005_reels_manifest_override.py:29-49` | done |
| 2 | `ReelORM.manifest_override` + retro-fix `ReelORM.photos_override` declared on the SQLAlchemy model (closes feature 35's deviation flagged by review 36) | `shared/db/orm.py:203-213` (`photos_override`), `shared/db/orm.py:214-225` (`manifest_override`) | done |
| 3 | `ReelState.manifest_override: list[dict[str, Any]] \| None = None` on the domain dataclass | `modules/reels/domain/reel_state.py:77-89` | done |
| 4 | Repository SQL: `_REEL_COLUMNS` lists the column; INSERT carries `CAST(:manifest_override AS jsonb)`; `ON CONFLICT DO UPDATE SET manifest_override = EXCLUDED.manifest_override`; bind uses `_manifest_override_to_jsonb_param`. Reader uses `_jsonb_to_optional_list`. Helper methods (`update_publish_status`, `update_workflow_state`, `save_local_artifacts`) forward `existing.manifest_override` to the rebuilt state so they cannot clobber the column. | `modules/reels/infrastructure/reel_state_repository.py:152-166` (helper), `:194-196` (reader), `:210-212` (`_REEL_COLUMNS`), `:259` (INSERT param list), `:278` (ON CONFLICT clause), `:316-318` (bind dict); preservation in helper methods at `:391`, `:445`, `:521` | done |
| 5 | `_build_ingested_reel_state` forwards `state.manifest_override` so a re-ingest never wipes it | `modules/reels/application/use_cases/_ingest_property_assets.py:234-238` | done |
| 6 | `_peeked_existing_state.manifest_override` is coerced via `_coerce_manifest_override` and forwarded onto `PropertyContext.manifest_override`, which the renderer consumes via `_apply_manifest_override` inside `DefaultMediaRenderer._render_reel` | `modules/reels/application/use_cases/ingest_property_into_reel.py:553-561` (forward), `:1287-1308` (coerce helper); `modules/rendering/application/frame_composition.py:108-126` (apply call), `:444-518` (`_apply_manifest_override`) | done |

## 2. Inherited follow-ups closure (from feature 35 / 36 reviewers)

| Item | Status | Evidence |
|---|---|---|
| **A.** Add `ReelORM.photos_override` field in `shared/db/orm.py` | closed at `shared/db/orm.py:203-213` | Mapped `JSONB` nullable column declared so future `alembic revision --autogenerate` runs don't propose a spurious `drop_column`. |
| **B.** `docs/API.md` — three new PATCH sections | closed at `docs/API.md:649-651` (table rows) and `docs/API.md:779-948` (new sections for /photos, /subtitles, /slides) | New `#### PATCH .../photos (feature 35)`, `#### PATCH .../subtitles (feature 36)` and `#### PATCH .../slides (feature 37)` sections mirroring the descriptions / music style. |
| **C.** Regenerate `docs/http_surface.md` + `docs/openapi.json` | closed via `.venv/bin/python scripts/generate_http_surface.py --write`; output now lists the three PATCH endpoints (http_surface.md lines 57-60; openapi.json paths block includes all three) | The script auto-generates from `build_api_app`; running it picks up the new routes plus the existing /photos and /subtitles routes the feature-35/36 implementers had not regenerated. |

All three follow-ups are closed in this PR — no obstacle reported.

## 3. Discriminated Union design

Pydantic v2 discriminated union on the `kind` literal lives in
`modules/reels/transport/payloads/admin_reels.py` (per leader's spec
naming the file). The union routes validation to the matching
sub-model so an unknown `kind` surfaces a deterministic 422 pointing
at the discriminator instead of a misleading "extra field" error from
a sibling branch.

| `kind` | Required fields (beyond base) | Pydantic class file:line |
|---|---|---|
| `photo` | `photo_position: int >= 0` | `modules/reels/transport/payloads/admin_reels.py:135-161` |
| `voiceover` | `audio_url: str` (non-empty, no MIME/scheme tightening yet) | `modules/reels/transport/payloads/admin_reels.py:163-180` |
| `text` | `text: str` (1-500 chars, literal — no template) | `modules/reels/transport/payloads/admin_reels.py:182-200` |
| `intro_card` | none (optional `title`, optional `subtitle`) | `modules/reels/transport/payloads/admin_reels.py:202-220` |
| `outro_card` | none (optional `title`, optional `subtitle`, optional `call_to_action`) | `modules/reels/transport/payloads/admin_reels.py:222-244` |

Base fields (every slide):

- `slide_id: str` (non-empty, unique across the array) — `_SlideBase` at `modules/reels/transport/payloads/admin_reels.py:114-117`.
- `position: int >= 0` (covers `[0, N)` exactly once) — `:118-126`.
- `duration_seconds: float > 0` (sum ≤ `target_duration_seconds * 1.5`) — `:127-134`.

Union alias: `SlideUnion = Annotated[Union[PhotoSlide, VoiceoverSlide, TextSlide, IntroCardSlide, OutroCardSlide], Field(discriminator="kind")]` at `modules/reels/transport/payloads/admin_reels.py:247-260`.

The use case re-checks every invariant (Pydantic + cross-slide rules + per-kind required fields) at `modules/reels/application/use_cases/update_reel_slides_override.py:208-378`, so the contract is self-contained when the Pydantic layer is bypassed.

The five kinds match what's reachable in the renderer today: only
`photo` kinds drive the rendered photo array (via `photo_position`);
`voiceover`, `text`, `intro_card`, `outro_card` are persisted for the
FE editor preview and a future renderer pass. See §7 below for the
precise call-site.

## 4. HTTP contract (as implemented)

| Method | URL | Body | Response 200 |
|---|---|---|---|
| PATCH | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/slides` | `{ "slides": [{ "slide_id": str, "position": int, "duration_seconds": float, "kind": str, ...kind-specific }, ...] }` OR `{"slides": null}` OR `{"slides": []}` to clear | `{ "manifest_override": [...] \| null, "render_status": "pending", "publish_enqueued": bool, "event_id"?: str, "job_id"?: str, "reason"?: str, "hint"?: str }` |

Error responses:

- **422** with informative `detail` for every validation case (Pydantic shape errors from the discriminator + use-case codes: `SLIDES_OVERRIDE_INVALID_KIND`, `SLIDES_OVERRIDE_EMPTY_SLIDE_ID`, `SLIDES_OVERRIDE_DUPLICATE_SLIDE_ID`, `SLIDES_OVERRIDE_INVALID_POSITION`, `SLIDES_OVERRIDE_DUPLICATE_POSITION`, `SLIDES_OVERRIDE_POSITION_GAP`, `SLIDES_OVERRIDE_INVALID_DURATION`, `SLIDES_OVERRIDE_DURATION_CAP_EXCEEDED`, `SLIDES_OVERRIDE_MISSING_KIND_FIELD`, `SLIDES_OVERRIDE_INVALID_KIND_FIELD`).
- **409 `SLIDES_OVERRIDE_LOCKED`** when `workflow_state == "approved"` OR `publish_status == "published"`. Body shape mirrors features 35 / 36 (`code`, `message`, `hint`, `details.context` carrying `agency_id`, `site_id`, `source_property_id`, `workflow_state`, `publish_status`).
- **404 `ADMIN_REEL_NOT_FOUND`** for missing reel; **404 `ADMIN_AGENCY_NOT_FOUND`** for missing agency.

## 5. Files touched

Created:

- `alembic/versions/20260515_0005_reels_manifest_override.py` — migration.
- `modules/reels/application/use_cases/update_reel_slides_override.py` — use case (~580 lines, mirrors `UpdateReelSubtitlesOverrideUseCase`).
- `tests/integration/reels/test_reel_slides_override.py` — 17 router integration tests.
- `tests/integration/rendering/test_render_with_slides_override.py` — 5 render integration tests.
- `progress/impl_37.md` — this report.

Edited:

- `shared/db/orm.py` — added `ReelORM.manifest_override` (feature 37) AND `ReelORM.photos_override` (closes feature 35's deviation flagged by review 36).
- `modules/reels/domain/reel_state.py` — added `manifest_override` field with default `None`.
- `modules/reels/domain/types.py` — added `PropertyContext.manifest_override`.
- `modules/reels/infrastructure/reel_state_repository.py` — `_manifest_override_to_jsonb_param`; reader; `_REEL_COLUMNS`; INSERT / ON CONFLICT / bind dict; preservation in all three helper methods (`update_publish_status`, `update_workflow_state`, `save_local_artifacts`).
- `modules/reels/application/use_cases/_ingest_property_assets.py` — `_build_ingested_reel_state` propagates `state.manifest_override`.
- `modules/reels/application/use_cases/ingest_property_into_reel.py` — `_coerce_manifest_override` helper + forward onto `PropertyContext.manifest_override`; imported `typing.Any`.
- `modules/reels/transport/payloads/admin_reels.py` — added the discriminated union (5 slide kinds) + `ReelSlidesOverridePayload` with cross-slide validator.
- `modules/reels/transport/http/admin_reels_router.py` — wired `UpdateReelSlidesOverrideUseCase` + PATCH `/slides` handler; imported `ReelSlidesOverridePayload` from the new location.
- `modules/rendering/application/frame_composition.py` — applied `_apply_manifest_override` in `_render_reel` after `_apply_photos_override`; added the helper.
- `docs/API.md` — added three new sections (`PATCH .../photos`, `PATCH .../subtitles`, `PATCH .../slides`) plus three new rows in the transition-endpoints table.
- `docs/http_surface.md` — regenerated; now lists `/photos`, `/subtitles`, `/slides`.
- `docs/openapi.json` — regenerated; now includes the three PATCH paths.
- `progress/current.md` — appended feature 37 entry.
- `feature_list.json` — feature 37 flipped to `in_progress`.

## 6. Migration

`alembic/versions/20260515_0005_reels_manifest_override.py`:

- `revision = "20260515_0005"`, `down_revision = "20260515_0004"`.
- `upgrade()` adds `reels.manifest_override JSONB NULL` with no `server_default` (matches the `nullable=True` "no override" sentinel).
- `downgrade()` drops the column.
- Round-trip verified live by the implementer:

```
20260515_0005 (head)
Running downgrade 20260515_0005 -> 20260515_0004
Running upgrade 20260515_0004 -> 20260515_0005
20260515_0005 (head)
```

## 7. Renderer integration — where override drives the plan

The override flows from the persisted JSONB column to the photo array
through this chain:

1. `reel_state_repository._row_to_reel_state` reads `row.manifest_override` into `ReelState.manifest_override` (`modules/reels/infrastructure/reel_state_repository.py:194-196`).
2. `ingest_property_into_reel._execute_with_uow` peeks the existing state and forwards it via `_coerce_manifest_override(_peeked_existing_state.manifest_override)` onto `PropertyContext.manifest_override` (`modules/reels/application/use_cases/ingest_property_into_reel.py:553-561`).
3. `frame_composition.DefaultMediaRenderer._render_reel` calls `_apply_manifest_override(prepared_assets, override=context.manifest_override)` **right after** `_apply_photos_override` and **before** `build_local_selected_slides` / `_build_render_data` (`modules/rendering/application/frame_composition.py:108-126`). The helper filters to `kind == "photo"` entries, sorts by `position` so the array order matches the slide order, then rebuilds `prepared_assets.selected_photo_paths` by mapping each entry's `photo_position` to the underlying source image. Out-of-range / malformed entries are logged and skipped — if every entry drops out, the helper returns the input unchanged so the renderer never produces an empty reel.
4. The rest of the pipeline (manifest builder, ffmpeg render, poster) sees a single canonical `prepared_assets.selected_photo_paths` tuple regardless of whether the override or the auto-generated pipeline produced it.

The override does **not** travel on the `reel_publish` job's
`publish_context`. The renderer reads the persisted row at ingest
time (via `_peeked_existing_state`), so a PATCH between job enqueue
and dispatch always wins. Same contract as features 35 / 36.

**Tolerance widened in the renderer:** none. The current pipeline only
consumes `photo` kinds; `voiceover`, `text`, `intro_card`, `outro_card`
are persisted but ignored by the photo array. The leader's brief
allowed this trade-off ("wrap the existing scene-building functions").
A future feature can extend `_apply_manifest_override` to materialise
the non-photo kinds (e.g. inject a black-background slide with
`drawtext` for `text` kinds, prepend an intro card from a brand
template, etc.) without changing the schema or the HTTP contract.

## 8. Tests added (22 new)

### `tests/integration/reels/test_reel_slides_override.py` (17 tests)

Happy paths (3):

- `test_patch_slides_persists_override_and_flips_render_status` — PATCH with one slide each of {photo, voiceover, text, intro_card, outro_card} → 200; persisted JSONB equals body; `render_status='pending'`; `publish_enqueued=True` with non-empty `event_id`/`job_id`; reload via `DatabaseUnitOfWork` confirms `state.manifest_override == _VALID_ALL_KINDS`.
- `test_patch_slides_with_null_clears_override` — pre-seed override, PATCH `{"slides": null}` → 200, body `manifest_override is None`, persisted SQL NULL.
- `test_patch_slides_with_empty_list_clears_override` — same but PATCH `{"slides": []}`.

Validation 422 (10):

- `test_patch_slides_rejects_invalid_kind_with_422` — `kind="banana"`.
- `test_patch_slides_rejects_photo_missing_photo_position_with_422` — photo slide without `photo_position`.
- `test_patch_slides_rejects_voiceover_missing_audio_url_with_422` — voiceover without `audio_url`.
- `test_patch_slides_rejects_text_missing_text_with_422` — text without `text`.
- `test_patch_slides_rejects_position_gap_with_422` — positions 0 + 2.
- `test_patch_slides_rejects_duplicate_position_with_422` — two slides at position 0.
- `test_patch_slides_rejects_duplicate_slide_id_with_422` — same slide_id reused.
- `test_patch_slides_rejects_duration_cap_exceeded_with_422` — 5 photo slides at 10s each = 50s > 30 * 1.5 = 45s.
- `test_patch_slides_rejects_extra_field_at_slide_level_with_422` — extra rogue key inside a slide.
- `test_patch_slides_rejects_extra_field_at_body_level_with_422` — extra rogue key at the body level.

409 (2):

- `test_patch_slides_returns_409_when_workflow_state_is_approved`.
- `test_patch_slides_returns_409_when_publish_status_is_published`.

404 (1):

- `test_patch_slides_returns_404_for_unknown_reel` → `ADMIN_REEL_NOT_FOUND`.

Survives re-ingest (1):

- `test_slides_override_survives_re_ingest` — PATCH, peek state, rebuild via `_build_ingested_reel_state`, save back, reload → the override is preserved. Same hardening test feature 35 / 36 reviewers asked for.

### `tests/integration/rendering/test_render_with_slides_override.py` (5 tests)

- `test_renderer_uses_manifest_override_photo_order` — reversed `photo_position` array `(4, 3, 2, 1, 0)` → manifest receives photos in reverse.
- `test_renderer_falls_back_when_manifest_override_is_none` — null override → renderer keeps the default prepared order.
- `test_renderer_handles_mixed_kinds_in_override` — `intro_card`, two photos, `voiceover`, photo, `outro_card` → only the photo kinds drive the array, sorted by `position` and mapped through `photo_position`.
- `test_renderer_falls_back_when_override_has_no_photo_kinds` — override has only `intro_card` + `text` → renderer falls back to the default prepared order (no empty reel).
- `test_renderer_falls_back_when_override_photo_positions_out_of_range` — `photo_position=99` for a 2-photo reel → renderer falls back to the default order.

## 9. Verification output (tails)

```
$ .venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
Running upgrade 20260515_0004 -> 20260515_0005, Add ``reels.manifest_override`` JSONB column (feature 37).
Running downgrade 20260515_0005 -> 20260515_0004, Add ``reels.manifest_override`` JSONB column (feature 37).
Running upgrade 20260515_0004 -> 20260515_0005, Add ``reels.manifest_override`` JSONB column (feature 37).

$ .venv/bin/alembic current
20260515_0005 (head)

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_slides_override.py tests/integration/rendering/test_render_with_slides_override.py -q
22 passed in 34.59s

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_photos_override.py tests/integration/reels/test_reel_subtitles_override.py tests/integration/reels/test_admin_reels_music_override.py -q
39 passed in 67.69s

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_slides_override.py tests/integration/rendering/test_render_with_slides_override.py tests/integration/reels/test_reel_photos_override.py tests/integration/reels/test_reel_subtitles_override.py tests/integration/reels/test_admin_reels_music_override.py tests/integration/reels/test_admin_reels_descriptions_override.py -q
68 passed in 96.50s

$ bash ./init.sh
3 failed, 1032 passed, 14 warnings in 569.66s (0:09:29)
[OK]    pytest verde
[OK]    Entorno listo.

$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
```

**1032 passed = 1010 baseline + 22 new** (17 router integration + 5 render integration). The 3 failures are the documented baseline flakes (`test_http_surface_contract`, two `test_http_transport` health-endpoint shape mismatches) — same set already reported by features 32-36 and confirmed pre-existing in this session's baseline run.

## 10. Open items for the reviewer

### 10.1 Non-photo slide kinds are persisted but not consumed by the renderer

The renderer's photo array is the only "rendered" surface today. The
other four kinds (`voiceover`, `text`, `intro_card`, `outro_card`)
round-trip through PATCH → JSONB → `PropertyContext.manifest_override`
but are silently skipped by `_apply_manifest_override`. The FE editor
will see the persisted data on subsequent GETs and can render an
editor preview, but the actual rendered MP4 only reflects the
`photo`-kind entries.

This is the explicit trade-off the leader called out ("Don't reinvent
the renderer — wrap the existing scene-building functions"). When
voiceover / text / intro-card / outro-card support lands in the
renderer, the wrap point in `frame_composition._apply_manifest_override`
becomes the natural extension site — no schema change required.

### 10.2 `audio_url` validation is intentionally loose

The `voiceover` slide accepts any non-empty string in `audio_url`. We
deliberately did not tighten to URL parsing / MIME / signed-URL
checks at the Pydantic layer because the renderer does not consume
the field yet and the FE editor needs flexibility (workspace-relative
paths, S3 URLs, signed CDN URLs). A future feature can lift this to
strict validation when the renderer wires it up.

### 10.3 `text` slide max length is 500 characters

Mirrors the upper bound of the subtitles cue text (200) doubled, on
the assumption that a text card has more on-screen real estate than a
subtitle cue. If the FE / brand team prefers a tighter cap, change
the `max_length` in `PhotoSlide` / sibling `TextSlide` in the
payload — single source of truth in
`modules/reels/transport/payloads/admin_reels.py:182-200`.

### 10.4 Inherited follow-ups A/B/C — all closed

Feature 35's `ReelORM.photos_override` deviation is closed in
`shared/db/orm.py:203-213`. `docs/API.md`, `docs/http_surface.md`,
and `docs/openapi.json` all carry the three new endpoints (features
35, 36, 37). The `test_http_surface_contract` flake remains for the
same documented reason (frontend repo path mismatch on this Linux
host) — not introduced by this feature.

### 10.5 Manual QA worth running on :8001

Worth a manual round-trip with:

- Mixed-kinds payload of 4-6 slides → verify the rendered MP4 only
  reflects the `photo` kinds for now (per §10.1).
- Stale `photo_position` (delete a property image, then submit an
  override that references the deleted index) → verify the renderer
  logs a warning and falls back rather than crashing.
- Approval gate flip mid-flight: PATCH `/slides` → quickly approve →
  next PATCH should 409. The 409 surfaces immediately because the
  use case reads `existing.workflow_state` on each request.

## 11. Sample curl against :8001

```bash
ADMIN_TOKEN="$(grep ADMIN_API_TOKEN .env | cut -d= -f2)"

# Happy path: 5 slides covering all kinds
curl -fsS -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[
        {"slide_id":"intro-1","position":0,"duration_seconds":2.0,"kind":"intro_card","title":"Welcome"},
        {"slide_id":"photo-A","position":1,"duration_seconds":3.0,"kind":"photo","photo_position":2},
        {"slide_id":"photo-B","position":2,"duration_seconds":3.0,"kind":"photo","photo_position":0},
        {"slide_id":"vo-1","position":3,"duration_seconds":1.5,"kind":"voiceover","audio_url":"https://cdn.example.com/vo.mp3"},
        {"slide_id":"outro-1","position":4,"duration_seconds":2.0,"kind":"outro_card","title":"Thanks","call_to_action":"Book a viewing"}
      ]}'

# Clear the override (back to auto-generated manifest)
curl -fsS -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":null}'

# Expected 422 (unknown kind)
curl -i -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[{"slide_id":"x","position":0,"duration_seconds":3.0,"kind":"banana"}]}'

# Expected 409 (reel already approved)
curl -i -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[{"slide_id":"x","position":0,"duration_seconds":3.0,"kind":"photo","photo_position":0}]}'
# → 409 {"code":"SLIDES_OVERRIDE_LOCKED", ...}
```

The `:8001` process must be reloaded for the new route to register
(the use case is wired by default-construction in
`create_admin_reels_router`, but the FastAPI app is built at boot).
Restart per `AGENTS.md` §7; this implementer does not restart
services (per leader's "Don't restart services" instruction).
