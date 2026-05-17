# Impl — feature 36 (`per_reel_subtitles_override`)

## 1. 6-point pattern checklist

| # | What | File:line | Status |
|---|------|-----------|--------|
| 1 | Alembic migration `20260515_0004_reels_subtitles_override.py` adds `reels.subtitles_override JSONB NULL`, `down_revision="20260515_0003"` | `alembic/versions/20260515_0004_reels_subtitles_override.py:27-46` | done |
| 2 | `ReelORM.subtitles_override` declared on the SQLAlchemy model | `shared/db/orm.py:191-201` | done (feature 35's reviewer flagged this as point-2 was skipped — closed here) |
| 3 | `ReelState.subtitles_override: list[dict[str, Any]] \| None = None` on the domain dataclass | `modules/reels/domain/reel_state.py:64-76` | done |
| 4 | Repository SQL: `_REEL_COLUMNS` lists the column; INSERT carries `CAST(:subtitles_override AS jsonb)`; `ON CONFLICT DO UPDATE SET subtitles_override = EXCLUDED.subtitles_override`; bind uses `_subtitles_override_to_jsonb_param`. Reader uses `_jsonb_to_optional_list`. Helper methods (`update_publish_status`, `update_workflow_state`, `save_local_artifacts`) forward `existing.subtitles_override` to the rebuilt state so they cannot clobber the column. | `modules/reels/infrastructure/reel_state_repository.py:118-150` (helper), `:189-208` (`_REEL_COLUMNS` + reader), `:252-258` (INSERT param list), `:269-275` (ON CONFLICT clause), `:307-314` (bind dict); preservation in helper methods at `:362, :413, :490` | done |
| 5 | `_build_ingested_reel_state` forwards `state.subtitles_override` onto the rebuilt `ReelState` so a re-ingest never wipes it | `modules/reels/application/use_cases/_ingest_property_assets.py:228-234` | done |
| 6 | `_peeked_existing_state.subtitles_override` is coerced via `_coerce_subtitles_override` and forwarded onto `PropertyContext.subtitles_override`, which the renderer reads through `_build_render_data → PropertyRenderData.subtitles_override → compose_subtitle_segments` | `modules/reels/application/use_cases/ingest_property_into_reel.py:543-551` (forward), `:1241-1271` (helper). Renderer wire-up in `modules/reels/application/frame_composition.py:316-322` and `modules/rendering/infrastructure/layout/subtitles.py:91-124` | done |

## 2. HTTP contract (as implemented)

| Method | URL | Body | Response 200 |
|---|---|---|---|
| PATCH | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/subtitles` | `{ "cues": [{ "index": int, "text": str, "in_seconds": float, "out_seconds": float }, ...] }` OR `{"cues": null}` OR `{"cues": []}` | `{ "subtitles_override": [...] \| null, "render_status": "pending", "publish_enqueued": bool, "event_id"?: str, "job_id"?: str, "reason"?: str, "hint"?: str }` |

Error responses:

- **422** with informative detail for every validation case (see §6). Codes
  emitted by the use case: `SUBTITLES_OVERRIDE_INVALID_INDEX`,
  `SUBTITLES_OVERRIDE_EMPTY_TEXT`, `SUBTITLES_OVERRIDE_TEXT_TOO_LONG`,
  `SUBTITLES_OVERRIDE_NEGATIVE_TIME`, `SUBTITLES_OVERRIDE_INVALID_WINDOW`,
  `SUBTITLES_OVERRIDE_NON_MONOTONIC_INDEX`, `SUBTITLES_OVERRIDE_OVERLAP`.
  The Pydantic layer also surfaces the same shape failures with FastAPI's
  default 422 body.
- **409 `SUBTITLES_OVERRIDE_LOCKED`** when `workflow_state == "approved"` OR
  `publish_status == "published"`. Body mirrors feature 35's
  `PHOTOS_OVERRIDE_LOCKED`: `code`, `message`, `hint`, `details.context`
  carrying `agency_id`, `site_id`, `source_property_id`, `workflow_state`,
  `publish_status`.
- **404 `ADMIN_REEL_NOT_FOUND`** when no reel matches
  `(external_source_id, source_property_id)`. **404 `ADMIN_AGENCY_NOT_FOUND`**
  for an unknown agency.

## 3. Files touched

Created:
- `alembic/versions/20260515_0004_reels_subtitles_override.py` — migration.
- `modules/reels/application/use_cases/update_reel_subtitles_override.py` —
  use case (~470 lines, mirrors `UpdateReelPhotosOverrideUseCase`).
- `modules/reels/transport/payloads/reel_subtitles_override.py` — Pydantic
  payload with `extra='forbid'` at both levels + cross-cue monotonicity /
  overlap validator.
- `tests/integration/reels/test_reel_subtitles_override.py` — 17 tests.
- `tests/integration/rendering/test_render_with_subtitles_override.py` —
  5 tests (filter-graph assertions).

Edited:
- `shared/db/orm.py` — added `ReelORM.subtitles_override` (point 2 of the
  6-point pattern). Closes the feature-35 leftover for the new column;
  did not retro-fix `photos_override` (out of scope for feature 36 per
  leader: "don't touch the orm for photos_override unless you're
  literally touching the file in your normal scope"). Since we are
  editing the same `ReelORM`, I added a brief note in the comment but
  did not add `photos_override` to avoid stepping outside the contract.
- `modules/reels/domain/reel_state.py` — added field.
- `modules/reels/domain/types.py` — added `PropertyContext.subtitles_override`.
- `modules/reels/infrastructure/reel_state_repository.py` — bind /
  read / `_REEL_COLUMNS` / 3 helper methods forward the new column.
- `modules/reels/application/use_cases/_ingest_property_assets.py` —
  `_build_ingested_reel_state` propagates `state.subtitles_override`.
- `modules/reels/application/use_cases/ingest_property_into_reel.py` —
  forward override + `_coerce_subtitles_override` helper.
- `modules/reels/transport/http/admin_reels_router.py` — wire the use case
  + PATCH handler.
- `modules/rendering/application/frame_composition.py` — forward override
  onto `PropertyRenderData`.
- `modules/rendering/infrastructure/models.py` —
  `PropertyRenderData.subtitles_override` field (default `None`).
- `modules/rendering/infrastructure/layout/subtitles.py` — bypass the
  autoCaptions loop when override is set; extracted shared helper
  `_build_subtitle_segments_from_raw` so geometry / measurement stays
  identical between the two paths.
- `modules/rendering/infrastructure/ffmpeg/filters.py` — gate the
  subtitle drawtext block on `subtitle_enabled OR subtitles_override`
  so the override always renders even when the agency disabled
  `auto_captions_enabled`.

## 4. Migration

`alembic/versions/20260515_0004_reels_subtitles_override.py`:
- `revision = "20260515_0004"`, `down_revision = "20260515_0003"`.
- `upgrade()` adds `reels.subtitles_override JSONB NULL` with no
  server_default (matches the `nullable=True` "no override" sentinel).
- `downgrade()` drops the column.
- Round-trip verified (reviewer can re-run):
  ```
  20260515_0004 (head)
  Running downgrade 20260515_0004 -> 20260515_0003
  Running upgrade 20260515_0003 -> 20260515_0004
  20260515_0004 (head)
  ```

## 5. Renderer call site (where the override is read and autoCaptions
   is bypassed)

The override flows from the persisted JSONB column to ffmpeg through
this chain:

1. `reel_state_repository._row_to_reel_state` reads
   `row.subtitles_override` into `ReelState.subtitles_override`.
2. `ingest_property_into_reel._execute_with_uow` peeks the existing
   state and forwards it via
   `_coerce_subtitles_override(_peeked_existing_state.subtitles_override)`
   onto `PropertyContext.subtitles_override`
   (`ingest_property_into_reel.py:543-551`).
3. `frame_composition.DefaultMediaRenderer._build_render_data` copies
   `context.subtitles_override` onto
   `PropertyRenderData.subtitles_override`
   (`frame_composition.py:316-322`).
4. `layout.subtitles.compose_subtitle_segments` checks
   `getattr(property_data, "subtitles_override", None)` first. If set
   and `slide_duration is not None`, it builds the
   `(start, end, text)` triples from the cues and routes them through
   the shared `_build_subtitle_segments_from_raw` helper — the
   autoCaptions slide-derived loop is skipped entirely
   (`subtitles.py:91-124`).
5. `ffmpeg.filters.build_overlay_filter` reads the same dataclass
   field and force-enables the subtitle drawtext block even when the
   agency-level `subtitle_style.enabled` is `False`
   (`filters.py:191-205`). Geometry / colour / outline cascade are
   inherited from `SubtitleStyle` — only the cue source changes.

The override does **not** travel on the `reel_publish` job's
`publish_context`. The renderer reads the persisted row at ingest time
(via `_peeked_existing_state`), so a PATCH between job enqueue and
dispatch always wins.

## 6. Tests added (22 new)

### `tests/integration/reels/test_reel_subtitles_override.py` (17 tests)

Happy paths (3):
- `test_patch_subtitles_persists_override_and_flips_render_status` —
  PATCH `[{"index":0,"text":"…","in_seconds":0.0,"out_seconds":3.0}, …]`
  → 200; persisted JSON equals payload; `render_status='pending'`;
  `publish_enqueued=True` with non-empty `event_id`/`job_id`; reload
  via `DatabaseUnitOfWork` confirms `state.subtitles_override == cues`.
- `test_patch_subtitles_with_null_clears_override` — pre-seed override,
  PATCH `{"cues": null}` → 200, body `subtitles_override is None`,
  persisted SQL NULL.
- `test_patch_subtitles_with_empty_list_clears_override` — same but
  PATCH `{"cues": []}`.

Validation (10):
- in==out, negative in, overlap, duplicate index, non-monotonic index,
  empty text, 201-char text, extra field per cue, wrong type for
  `text`, extra field at body level.

409 (2):
- `workflow_state='approved'` and `publish_status='published'` both
  trigger `SUBTITLES_OVERRIDE_LOCKED`.

404 (1):
- Unknown reel id → `ADMIN_REEL_NOT_FOUND`.

Survives re-ingest (1):
- `test_subtitles_override_survives_re_ingest` — PATCH, peek state,
  rebuild via `_build_ingested_reel_state`, save back, reload → the
  override is preserved. This is the same hardening test feature 35's
  reviewer flagged as a follow-up and that the feature-25 `music_id`
  drive-by fixed retroactively.

### `tests/integration/rendering/test_render_with_subtitles_override.py` (5 tests)

- `test_renderer_uses_override_cues_when_present` — override of 2 cues
  → exactly 2 subtitle drawtext blocks in the filter graph; cue text
  appears verbatim; auto-generated slide caption does not; timing
  expressions `between(t\,0.000\,2.000)` and
  `between(t\,2.000\,5.500)` present.
- `test_renderer_override_wins_when_auto_captions_disabled` — override
  set, `SubtitleStyle(enabled=False)` → drawtext still emitted with
  the override text.
- `test_renderer_falls_back_to_autocaptions_when_override_is_none` —
  override None, autoCaptions enabled → slide caption appears in
  filter graph.
- `test_renderer_skips_subtitles_when_override_none_and_autocaptions_off`
  — no override, autoCaptions disabled → zero subtitle drawtext.
- `test_renderer_override_handles_single_cue` — single-cue smoke test.

## 7. Verification output (tail)

```
$ .venv/bin/alembic current
20260515_0004 (head)

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_subtitles_override.py tests/integration/rendering/test_render_with_subtitles_override.py -q
22 passed in 27.08s

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_photos_override.py tests/integration/reels/test_admin_reels_music_override.py tests/integration/rendering/ -q
67 passed in 49.21s

$ .venv/bin/python -m pytest tests/integration/reels tests/unit/reels tests/unit/rendering -q
344 passed in 165.08s

$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s

$ bash ./init.sh
3 failed, 1010 passed, 14 warnings in 521.03s (0:08:41)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

1010 passed = 988 baseline + 22 new (17 router integration + 5 render
integration). The 3 failures are the documented baseline flakes
(`test_http_surface_contract`, two `test_http_transport` health-endpoint
shape mismatches) — same set already reported by features 32, 33, 34,
35 and confirmed pre-existing in this session's baseline run.

## 8. Open items for the reviewer

### 8.1 Feature 37 (`per_reel_slides_override`) — same pattern next

Feature 37 will add another JSONB column to `reels`
(`manifest_override` or `slides_override`). Migration head after this
feature is `20260515_0004`, so feature 37's migration should use
`down_revision = "20260515_0004"` and slug
`20260515_0005_reels_slides_override.py`. Same 6-point pattern applies:

1. Migration with `down_revision = "20260515_0004"`.
2. `ReelORM.slides_override` on `shared/db/orm.py` (do NOT skip this
   one — feature 35 skipped it for `photos_override`).
3. `ReelState.slides_override` on the dataclass.
4. Repo SQL: extend `_REEL_COLUMNS`, INSERT, ON CONFLICT, all three
   helper methods (`update_publish_status`, `update_workflow_state`,
   `save_local_artifacts`) so the override survives unrelated saves.
5. `_build_ingested_reel_state` forwards `state.slides_override`.
6. `_peeked_existing_state.slides_override` forwarded to
   `PropertyContext.slides_override` via a coerce helper.

### 8.2 Feature-35 deviations NOT closed here

The leader's directive is explicit: "Don't fix feature-35's deviations
(ORM, docs/API.md, openapi) unless you're literally touching the file
in your normal scope".

- `ReelORM.photos_override` (the gap feature 35's reviewer logged): I
  did **not** close this — even though I edited `shared/db/orm.py` to
  add `subtitles_override`, retro-adding `photos_override` would
  expand the scope beyond feature 36's contract. Recommended: feature
  37's implementer closes it together with the new `slides_override`
  column.
- `docs/API.md` was not updated. Same rationale: out of scope per
  leader's directive ("Don't fix feature-35's deviations … unless
  you're literally touching the file in your normal scope") — I did
  not touch `docs/API.md`.
- `docs/http_surface.md` / `docs/openapi.json` were not regenerated.
  Same rationale.

### 8.3 Renderer-side coverage caveat

The `test_render_with_subtitles_override.py` suite asserts the
**filter graph** (ffmpeg command) produced by `build_overlay_filter`.
It does not exercise a real ffmpeg invocation or extract an SRT track,
because the existing reel-render integration tests (feature 31's
`test_subtitle_settings_wiring.py`) also test at this layer and that
keeps the suite fast. End-to-end manual verification on `:8001` is
listed below as §9.

### 8.4 `ReelORM.subtitles_override` is `Mapped[list | None]`

I typed it as `list` (not `dict`) to mirror the actual on-wire shape
(a JSONB array). Sister overrides use `Mapped[dict | None]` /
`Mapped[str | None]` — pick a consistent convention if reviewer
prefers `Mapped[list[dict] | None]` (Python's generic alias support is
ok with SQLAlchemy 2.0 `Mapped[...]`, but `list[dict] | None` triggers
a noisier annotation in autogenerate). Defensive choice: stayed with
`list | None`.

## 9. Sample curl against :8001

The proxy / process restart is decided by the user (see `AGENTS.md`
§7). For a freshly-restarted `:8001` carrying this feature:

```bash
ADMIN_TOKEN="$(grep ADMIN_API_TOKEN .env | cut -d= -f2)"

# Happy path
curl -fsS -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/subtitles" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"cues":[
        {"index":0,"text":"Welcome to this property","in_seconds":0.0,"out_seconds":3.0},
        {"index":1,"text":"Beautiful kitchen","in_seconds":3.0,"out_seconds":6.0}
      ]}'

# Clear (back to autoCaptions fallback)
curl -fsS -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/subtitles" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"cues":null}'

# Expected 422 (overlap)
curl -i -X PATCH \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/subtitles" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"cues":[
        {"index":0,"text":"x","in_seconds":0.0,"out_seconds":5.0},
        {"index":1,"text":"y","in_seconds":4.0,"out_seconds":8.0}
      ]}'
```

The `:8001` process must be reloaded for the new route to register
(the use case is wired by default-construction in
`create_admin_reels_router`, but the FastAPI app is built at boot).
The leader / user decides when to restart per `AGENTS.md` §7. Test
infra restart is **not** performed by this implementer (instruction:
"don't restart services").
