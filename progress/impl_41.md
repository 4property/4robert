# Impl — feature 41 (`auto_subtitles_snapshot_for_editor`)

## 1. 6-point pattern checklist

| # | Requirement | File:line | Status |
|---|---|---|---|
| 1 | Alembic migration `20260517_0001_reels_auto_subtitles_snapshot.py` adds `reels.auto_subtitles_snapshot JSONB NULL`; `down_revision="20260515_0005"`; round-trip clean | `alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py:30-52` | done |
| 2 | `ReelORM.auto_subtitles_snapshot` mapped JSONB nullable on the SQLAlchemy model | `shared/db/orm.py:228-241` | done |
| 3 | `ReelState.auto_subtitles_snapshot: list[dict[str, Any]] \| None = None` on the domain dataclass | `modules/reels/domain/reel_state.py:90-100` | done |
| 4 | Repository SQL: `_REEL_COLUMNS` lists the column; INSERT carries `CAST(:auto_subtitles_snapshot AS jsonb)`; `ON CONFLICT DO UPDATE SET auto_subtitles_snapshot = EXCLUDED.auto_subtitles_snapshot`; bind dict uses `_auto_subtitles_snapshot_to_jsonb_param`; reader uses `_jsonb_to_optional_list`. Helper methods (`update_publish_status`, `update_workflow_state`, `save_local_artifacts`) forward `existing.auto_subtitles_snapshot` so they cannot clobber the column. `save_local_artifacts` also accepts an explicit `auto_subtitles_snapshot=...` kwarg (sentinel default `_UNSET` ⇒ keep existing) so the renderer can refresh the column. | Helpers: `modules/reels/infrastructure/reel_state_repository.py:169-184` (param) + `:225-228` (`_UNSET`/`_Unset`). `_REEL_COLUMNS`: `:259-269`. Reader: `:215-222`. INSERT/ON CONFLICT/bind: `:300-302`, `:320-322`, `:351-353`. Helpers preservation: `:434`, `:489`, `:565`. `save_local_artifacts` sentinel: `:511-525`, `:541-548`. | done |
| 5 | `_build_ingested_reel_state` forwards `state.auto_subtitles_snapshot` onto the rebuilt `ReelState` so a re-ingest never wipes it | `modules/reels/application/use_cases/_ingest_property_assets.py:238-248` | done |
| 6 | `RenderedMediaArtifact.auto_subtitles_snapshot` carries the cues the renderer computed (`None` when an override bypassed autoCaptions); `PersistLocalArtifactsUseCase._persist_with_uow` forwards the cues to `save_local_artifacts(..., auto_subtitles_snapshot=...)` only when the artifact carries them; the renderer computes the snapshot inside `_render_reel` via `build_auto_subtitles_snapshot(...)` only when `context.subtitles_override is None`. | Domain: `modules/reels/domain/types.py:303-358` (`RenderedMediaArtifact.auto_subtitles_snapshot`). Renderer call site: `modules/rendering/application/frame_composition.py:215-245`. Snapshot builder: `modules/rendering/infrastructure/layout/subtitles.py:256-330`. Persist forward: `modules/reels/application/use_cases/persist_local_artifacts.py:305-329`. | done |

## 2. Renderer integration point (where the cues are persisted)

The snapshot flows from the renderer to the DB through this chain:

1. `frame_composition.DefaultMediaRenderer._render_reel` (`modules/rendering/application/frame_composition.py:215-245`) — after generating the reel + poster, when `context.subtitles_override is None`, calls `build_auto_subtitles_snapshot(slides=property_render_data.selected_slides, settings=template, property_data=property_render_data, slide_duration=template.seconds_per_slide)`. Defensive try/except around the helper guarantees a snapshot failure never poisons the render — the column simply stays NULL on that path.
2. `RenderedMediaArtifact(..., auto_subtitles_snapshot=...)` (`modules/reels/domain/types.py:336-358`) — frozen dataclass carries the cues to the publish step.
3. `PersistLocalArtifactsUseCase._persist_with_uow` (`modules/reels/application/use_cases/persist_local_artifacts.py:305-329`) — when the artifact has `auto_subtitles_snapshot != None`, forwards the cues to `save_local_artifacts(...)` via the kwarg.
4. `ReelStateRepository.save_local_artifacts` (`modules/reels/infrastructure/reel_state_repository.py:496-572`) — the sentinel `_UNSET` default means "preserve `existing.auto_subtitles_snapshot`"; an explicit `list[dict]` or `None` value updates the column. This keeps the override-set render branch (which sends `auto_subtitles_snapshot=None` on the artifact) from clobbering the previous snapshot.

## 3. HTTP response shape

`GET /v1/admin/agencies/{agency_id}/reels` and `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}` now carry the new field:

```json
{
  "publish_subtitles_snapshot": [
    {"index": 0, "text": "Welcome to this stunning property.", "in_seconds": 0.0, "out_seconds": 3.0},
    {"index": 1, "text": "Spacious kitchen and dining area.", "in_seconds": 3.0, "out_seconds": 6.0}
  ]
}
```

The field is `null` when the column is unset. The frontend reads it as `publishSubtitlesSnapshot` via the camelCase mapper (`ReelEditor.jsx:184` already does this); no front changes are required.

Implementation:

- Payload field: `modules/reels/transport/payloads/admin_reels.py:54-60` (`AgencyReelItemPayload.publish_subtitles_snapshot: list[ReelSubtitleCue] | None = None`, reusing `ReelSubtitleCue` from feature 36).
- Serializer: `modules/reels/transport/http/admin_reels_assets.py:69-77` (`_serialize_agency_reel` reads `item.auto_subtitles_snapshot`).
- Read query: `modules/reels/infrastructure/reel_query.py:241-247` (SELECT extended), `:128-135` (`AgencyReelSummary.auto_subtitles_snapshot` field), `:74-103` (`_decode_auto_subtitles_snapshot` helper), `:302-304` (row → summary mapping).

## 4. Tests added

### `tests/integration/reels/test_auto_subtitles_snapshot.py` (7 tests)

- `test_reel_state_round_trips_auto_subtitles_snapshot` — write via raw SQL, read via repo, re-save via repo, reload → snapshot round-trips through `_REEL_COLUMNS`.
- `test_auto_subtitles_snapshot_survives_re_ingest` — PATCH-equivalent (raw SQL seed), peek state, run `_build_ingested_reel_state`, save, reload → snapshot preserved (the regression test family from features 25 / 35 / 36 / 37).
- `test_update_publish_status_preserves_auto_subtitles_snapshot` — repo helper does not clobber the column.
- `test_update_workflow_state_preserves_auto_subtitles_snapshot` — same for the workflow-state helper.
- `test_get_reel_returns_publish_subtitles_snapshot_when_populated` — GET endpoint surfaces the cues.
- `test_get_reel_publish_subtitles_snapshot_is_null_when_unset` — GET endpoint returns `null` for fresh reels.
- `test_list_reels_returns_publish_subtitles_snapshot` — listing endpoint exposes the same field per item.

### `tests/integration/rendering/test_render_persists_auto_subtitles.py` (6 tests)

- `test_renderer_emits_auto_subtitles_snapshot_when_no_override` — no override → artifact carries cues that match the stubbed Gemini captions verbatim (post-`normalize_caption`).
- `test_renderer_emits_no_snapshot_when_override_is_set` — override set → artifact's snapshot is `None` (autoCaptions composer bypassed).
- `test_renderer_snapshot_skips_slides_without_caption` — slides with empty / `None` captions are dropped; remaining cues keep monotonic `index` values.
- `test_renderer_snapshot_includes_intro_when_template_has_intro` — intro segment produces an extra leading cue spanning `[0, intro_duration_seconds)`.
- `test_persist_local_artifacts_writes_snapshot_when_artifact_carries_one` — end-to-end persist round-trip via `PersistLocalArtifactsUseCase`.
- `test_persist_local_artifacts_preserves_existing_snapshot_when_artifact_has_none` — `RenderedMediaArtifact.auto_subtitles_snapshot=None` keeps the previously-persisted column.

## 5. Verification output

### Migration round-trip

```
$ .venv/bin/alembic upgrade head
20260517_0001 (head)
$ .venv/bin/alembic downgrade -1
Running downgrade 20260517_0001 -> 20260515_0005
$ .venv/bin/alembic upgrade head
Running upgrade 20260515_0005 -> 20260517_0001
$ .venv/bin/alembic current
20260517_0001 (head)
```

### Per-file tests

```
$ .venv/bin/python -m pytest \
    tests/integration/reels/test_auto_subtitles_snapshot.py \
    tests/integration/reels/test_reel_subtitles_override.py \
    tests/integration/rendering/test_render_persists_auto_subtitles.py -q -v
... 30 passed in ~25s  (7 new + 17 feature-36 regression + 6 new render persist)
```

### Reels + rendering integration regression

```
$ .venv/bin/python -m pytest tests/integration/reels/ tests/integration/rendering/ -q
189 passed in 234.73s
```

### apps checks

```
$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes
$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s
```

### init.sh

```
$ bash ./init.sh
3 failed, 1063 passed, 14 warnings in 579.47s (0:09:39)
[OK]    pytest verde
[OK]    Entorno listo.
```

1063 passed = 1050 baseline + 13 new (7 + 6) tests. The 3 failures are the documented baseline flakes (`test_http_surface_contract`, two `test_http_transport` health-endpoint shape mismatches) — same set the reviewer has confirmed pre-existing across features 32-40.

## 6. Open items for the reviewer

### 6.1 Backfill of existing reels' `auto_subtitles_snapshot`

The migration does **not** backfill the new column. Every reel that already had a `render_status='completed'` row before this feature ships will show `publish_subtitles_snapshot: null` in the GET response until the next render (manual regenerate per feature 40 is the operational path).

This is intentional:

- Backfilling would require running the Gemini caption pipeline against historic property data, which is non-trivial (the captions are tied to the prepared slides, not the property row).
- The editor already handles the empty state gracefully (the front falls back to `subtitlesOverride || publishSubtitlesSnapshot` and renders an empty editor when neither is set; user can type cues from scratch).

A backfill helper is **out of scope** for feature 41. If the product team wants existing reels to show captions in the editor immediately, the cleanest path is a bulk manual regenerate per agency (feature 40's POST `/regenerate` endpoint).

### 6.2 Snapshot text is the normalised caption, not the raw Gemini output

The cues in `auto_subtitles_snapshot` store the **same** text the renderer paints onscreen — after `normalize_caption` strips quotes / "Key features:" prefix / trailing whitespace and appends a sentence terminator. We considered storing the raw Gemini output (so the editor sees the exact LLM response) but rejected it because:

- The editor needs cues that match what the user sees in the video. Showing raw text would create a UX trap where editing a cue back to the "raw" form changes what gets rendered.
- The renderer-side autoCaptions composer also reads the normalised text — keeping the two in sync via a single normalisation point is simpler than threading a "raw vs normalised" flag through the pipeline.

The snapshot text DOES include the trailing period when the caption did not have one. Tests assert this contract (see `_expected_caption` helper in `test_render_persists_auto_subtitles.py`).

### 6.3 Override-set renders preserve the previous snapshot (not refresh from override)

When `subtitles_override` is set, the renderer does NOT recompute or refresh `auto_subtitles_snapshot`. The previous snapshot stays as-is. Rationale (matches the leader's brief):

- The autoCaptions composer is bypassed in this branch, so the renderer has no cues to record.
- Storing the override into `auto_subtitles_snapshot` would mean "if the user clears the override, the editor's starting value is the override they just cleared" — confusing UX. Keeping the snapshot as the historical autoCaptions output gives the user a useful fallback ("reset to the captions Gemini produced last time").

### 6.4 Slide-duration uses `template.seconds_per_slide`, not the variable `compute_segment_timing` durations

The autoCaptions composer in `compose_subtitle_segments` uses a single `slide_duration` (the cells are equal-width). The snapshot mirrors this. When `slide_count >= max_slide_count`, the actual ffmpeg-emitted segment durations vary by ±1 frame to hit the target total duration, so cue boundaries in the snapshot may diverge from the rendered timing by tens of milliseconds in those edge cases. We accept the drift because:

- The drift is bounded (one frame at 30 fps = 33 ms).
- The renderer-side composer drives subtitles from the same `slide_duration` value, so the rendered video and the snapshot agree on cue timing.

### 6.5 `ReelORM.auto_subtitles_snapshot` typed as `Mapped[list | None]`

Same convention as `subtitles_override` / `photos_override` / `manifest_override`. SQLAlchemy 2.0's `Mapped[list[dict] | None]` works in principle but emits noisier `alembic revision --autogenerate` diagnostics on this branch; we stayed with `list | None`.

## 7. Sample curl for :8001

```bash
ADMIN_TOKEN="$(grep ADMIN_API_TOKEN .env | cut -d= -f2)"

# GET one reel — response includes publish_subtitles_snapshot when populated
curl -fsS \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" | jq '.reel.publish_subtitles_snapshot'

# LIST reels — every item carries publish_subtitles_snapshot
curl -fsS \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels?page=1&page_size=10" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  | jq '.items[] | {site_id, source_property_id, publish_subtitles_snapshot}'

# Trigger a fresh render so the snapshot refreshes (feature 40):
curl -fsS -X POST \
  "http://127.0.0.1:8001/v1/admin/agencies/<agency>/reels/<site>/<property>/regenerate" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" -d '{}'
```

The `:8001` process must be reloaded for the new column to be exposed via GET (the routes are wired at boot). The leader / user decides when to restart per `AGENTS.md` §7. Test infra restart is **not** performed by this implementer (instruction: "don't restart services").
