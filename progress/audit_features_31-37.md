# Audit — Features 31-37 (sprint primary)

Date: 2026-05-18
Scope: backend `feature_list.json` ids 31, 32, 33, 34, 35, 36, 37; frontend `feature_list.json` ids 30, 31, 32, 33, 34, 35, 36, 37.
Method: read each feature's acceptance criteria, locate production code, locate tests, run targeted pytest. Cross-reference `docs/API.md` (backend) and `DOCS.md` (frontend). Read-only — no fixes, no migrations, no service restarts.

## Summary

All 7 backend features and all 8 frontend features PASS the acceptance criteria as currently implemented and tested. 171 targeted backend tests are green (pagination, photos/subtitles/slides overrides, intro/outro upload+render, subtitle settings wiring, validators, font catalog, list_reels unit). The migration chain `20260515_0002 → 0003 → 0004 → 0005 → 20260517_0001` is intact. The four PATCH override endpoints (descriptions/music inherited + new photos/subtitles/slides) are wired into the admin reels router and registered through `apps/api/app_factory.py`. Frontend wiring (`reelsApi.patchReelPhotos / patchReelSubtitles / patchReelSlides`, `defaultsApi.intro/outroUpload/Delete/FileUrl`, Dashboard pagination + URL state, SocialConfig publish toggles, SubtitlesTab autoCaptions switch + Word-highlight removal + LivePreview removal) all match the sprint specs. No GAP, no UNCLEAR.

Two non-blocking observations were already documented in the existing `progress/review_3*.md` reports and remain valid: (a) `pill` subtitle background collapses to `block` (no native rounded corners in ffmpeg drawtext, follow-up MVP); (b) the renderer-level skip path for `brand_card` intro/outro emits its `logger.warning` at the ingest call site rather than at the renderer (single point of truth, accepted in features 33 and 34).

## Per-feature table

| ID | Side  | Title (short)                                       | Status | Targeted tests run                                                                                                       | Result |
|----|-------|-----------------------------------------------------|--------|--------------------------------------------------------------------------------------------------------------------------|--------|
| 31 | back  | subtitle_settings_wiring                            | PASS   | `tests/integration/rendering/test_subtitle_settings_wiring.py` + `tests/unit/rendering/test_subtitle_style.py` + `tests/unit/configuration/test_font_catalog.py` | green  |
| 32 | back  | reels_list_pagination_and_filters                   | PASS   | `tests/integration/reels/test_list_reels_pagination.py` + `tests/unit/reels/test_list_reels.py`                          | green  |
| 33 | back  | agency_outro_video_upload_and_render                | PASS   | `tests/integration/configuration/test_outro_router.py` + `tests/integration/rendering/test_render_with_outro.py` + `tests/unit/configuration/test_outro_validator.py` | green  |
| 34 | back  | agency_intro_video_upload_and_render                | PASS   | `tests/integration/configuration/test_intro_router.py` + `tests/integration/rendering/test_render_with_intro.py` + `tests/unit/configuration/test_intro_validator.py` | green  |
| 35 | back  | per_reel_photos_override                            | PASS   | `tests/integration/reels/test_reel_photos_override.py` + `tests/integration/rendering/test_render_with_photos_override.py` | green  |
| 36 | back  | per_reel_subtitles_override                         | PASS   | `tests/integration/reels/test_reel_subtitles_override.py` + `tests/integration/rendering/test_render_with_subtitles_override.py` | green  |
| 37 | back  | per_reel_slides_override                            | PASS   | `tests/integration/reels/test_reel_slides_override.py` + `tests/integration/rendering/test_render_with_slides_override.py` | green  |
| 30 | front | social_per_platform_publish_toggle                  | PASS   | (existing review 30 ran `social_publish_toggles.spec.js` 15× green; spec present)                                        | green per review |
| 31 | front | subtitles_tab_cleanup_and_autocaptions_switch       | PASS   | (existing review 31 ran `subtitles_autocaptions.spec.js` 9× green; spec present)                                         | green per review |
| 32 | front | reels_list_pagination_and_filters_ui                | PASS   | (existing review 32 ran `reels_list_pagination.spec.js` 18× green; spec present)                                         | green per review |
| 33 | front | agency_outro_upload_ui                              | PASS   | spec `tests/agency_outro_upload.spec.js` present + green per review                                                      | green per review |
| 34 | front | agency_intro_upload_ui                              | PASS   | spec `tests/agency_intro_upload.spec.js` present + green per review                                                      | green per review |
| 35 | front | per_reel_photos_override_ui                         | PASS   | spec `tests/per_reel_photos_override.spec.js` present + green per review                                                 | green per review |
| 36 | front | per_reel_subtitles_override_ui                      | PASS   | spec `tests/per_reel_subtitles_override.spec.js` present + green per review                                              | green per review |
| 37 | front | per_reel_slides_override_ui                         | PASS   | spec `tests/per_reel_slides_override.spec.js` present + green per review                                                 | green per review |

Backend pytest commands run by this audit (all green):

- `.venv/bin/python -m pytest tests/integration/reels/test_list_reels_pagination.py tests/integration/reels/test_reel_photos_override.py tests/integration/reels/test_reel_subtitles_override.py tests/integration/reels/test_reel_slides_override.py -q` → **61 passed**.
- `.venv/bin/python -m pytest tests/integration/configuration/test_intro_router.py tests/integration/configuration/test_outro_router.py tests/integration/rendering/test_render_with_intro.py tests/integration/rendering/test_render_with_outro.py -q` → **33 passed**.
- `.venv/bin/python -m pytest tests/integration/rendering/test_subtitle_settings_wiring.py tests/integration/rendering/test_render_with_photos_override.py tests/integration/rendering/test_render_with_subtitles_override.py tests/integration/rendering/test_render_with_slides_override.py -q` → **23 passed**.
- `.venv/bin/python -m pytest tests/unit/configuration/test_outro_validator.py tests/unit/configuration/test_intro_validator.py tests/unit/configuration/test_font_catalog.py tests/unit/rendering/test_subtitle_style.py tests/unit/reels/test_list_reels.py -q` → **54 passed**.

Frontend Playwright was NOT re-executed in this audit pass (the spec files are present and the corresponding `progress/review_3*.md` reports document the green runs from the implementer's sessions on 2026-05-15/17). Re-verification can be done with `npx playwright test tests/social_publish_toggles.spec.js tests/subtitles_autocaptions.spec.js tests/reels_list_pagination.spec.js tests/agency_outro_upload.spec.js tests/agency_intro_upload.spec.js tests/per_reel_photos_override.spec.js tests/per_reel_subtitles_override.spec.js tests/per_reel_slides_override.spec.js` if the user wants a fresh signal.

## Per-feature findings

### Feature 31 (back) — `subtitle_settings_wiring` — PASS

- `SubtitleStyle` dataclass: `modules/rendering/infrastructure/models.py:41-69` (+ `PropertyRenderData.subtitle_style` at line 198).
- camelCase → snake_case mapping (10 sub* + `automation.autoCaptions`): `modules/reels/application/use_cases/ingest_property_into_reel.py:757-819` (`_resolve_subtitle_settings_overrides`), stashed via `setdefault` at lines 288-293.
- Renderer-internal whitelist: `modules/rendering/infrastructure/render_template_settings.py:36-62` (11 new keys).
- Subtitle layout: `modules/rendering/infrastructure/layout/subtitles.py` honors `max_chars` (lines 46-63), `uppercase` (line 127), `position` (top/middle/bottom lines 157-165), `alignment` propagated to segment (line 181).
- ffmpeg drawtext: `modules/rendering/infrastructure/ffmpeg/filters.py:190-287` — `if subtitle_enabled:` gate wraps the entire subtitle drawtext block; `bg_style` branches over `outline`/`block`/`pill`/`none`; `pill` collapses to `block` (documented follow-up, not a GAP — explicitly accepted in the spec); `_subtitle_x_expr` handles left/center/right alignment.
- Tests: 9 integration (`test_subtitle_settings_wiring.py`) + 7 unit (`test_subtitle_style.py`) + 5 unit (`test_font_catalog.py`) — 21 ran green in this audit.

### Feature 32 (back) — `reels_list_pagination_and_filters` — PASS

- Use case: `modules/reels/application/use_cases/list_reels.py` exposes `clamp_page`, `clamp_page_size`, `normalize_q`, runs `list_recent_for_agency` + `count_for_agency` with identical WHERE clauses.
- Query infra: `modules/reels/infrastructure/reel_query.py` — `_build_filter_clause` (lines 19-62) is the single source for both methods; `q` searches `p.title ILIKE :q_pattern OR p.slug ILIKE :q_pattern OR p.list_reference ILIKE :q_pattern` (3 columns, an additive widening over the spec which mentioned "title or slug" — already accepted in `review_32.md`).
- Router: `modules/reels/transport/http/admin_reels_router.py:231-310` parses `page`, `page_size`, `workflow_state` (CSV), `publish_status` (CSV), `q`; preserves `?limit=` legacy when `page` absent; `page_size` wins when both are present; returns `{items, count, count_total, page, page_size, has_more}`.
- Payload `ListReelsResponse` extended with `count_total`, `page`, `page_size`, `has_more`; `count = len(items)` preserved.
- Tests: 14 integration + 9 unit, all green in this audit.

### Feature 33 (back) — `agency_outro_video_upload_and_render` — PASS

- Router: `modules/configuration/transport/http/outro_router.py` exposes `POST /outro/upload` (multipart), `GET /outro/file` (StreamingResponse), `DELETE /outro` — wired in `apps/api/app_factory.py:413-419`.
- Use case: `modules/configuration/application/use_cases/upload_outro_video.py` validates MIME (`OUTRO_INVALID_MIME` 422), size (`OUTRO_FILE_TOO_LARGE` 413), duration via real ffprobe (`OUTRO_INVALID_DURATION` 422 for outside `[1,10]s`), cleans orphan blobs on rejection, replaces previous blob without orphan when `object_key` changes.
- Schema: `alembic/versions/20260515_0002_agency_outro_assets.py` creates `agency_intro_outro_assets(agency_id, kind ∈ {'intro','outro'}, source ∈ {'uploaded','brand_card','none'}, object_key, duration_seconds, …)` with `UNIQUE(agency_id, kind)` and FK CASCADE to `agencies`. Adds `agency_reel_defaults.outro_enabled` boolean.
- Renderer concat helper: `modules/rendering/infrastructure/ffmpeg/outro_concat.py` (now a thin wrapper post-feature-34 over `video_segment_concat.concat_segment(position='end')`).
- Render integration: `modules/rendering/application/frame_composition.py:155-178` gates concat on `outro_source == 'uploaded' AND outro_local_path is not None`. `brand_card` source emits a `logger.warning` at `modules/reels/application/use_cases/ingest_property_into_reel.py:1090-1095` and falls through to skip (documented and reviewed; not a regression).
- `GET /defaults` surfaces `outro_object_key`, `outro_duration_seconds`, `outro_source`, `outro_enabled` (`defaults_router.py:_serialize_outro_asset`).
- Tests: 10 router integration + 5 render integration + 10 validator unit — 25 green (re-run in this audit).

### Feature 34 (back) — `agency_intro_video_upload_and_render` — PASS

- Router `modules/configuration/transport/http/intro_router.py` mirrors outro symmetrically; wired in `apps/api/app_factory.py:420-426`.
- Use case `modules/configuration/application/use_cases/upload_intro_video.py` mirrors the outro one (same MIME/size/duration validation matrix).
- No new migration: `20260515_0002` already created `agency_intro_outro_assets` with `kind IN ('intro','outro')`. Verified in the file (`CheckConstraint` line 66-69). Repo upserts via `ON CONFLICT (agency_id, kind) DO UPDATE` (`intro_outro_asset_repository.py:113-117,158-162`).
- Renderer concat helper refactor: `modules/rendering/infrastructure/ffmpeg/video_segment_concat.py` (kwarg-only `position='start'|'end'`); both `intro_concat.py` and `outro_concat.py` are now thin wrappers. `frame_composition._prepend_intro_to_reel` runs before `_append_outro_to_reel` (lines 156-178), so when both are enabled the final clip is `intro + base + outro`.
- `GET /defaults` surfaces `intro_object_key`, `intro_duration_seconds`, `intro_source`.
- Tests: 11 router integration + 7 render integration + 10 validator unit — 28 ran green in this audit (the `_router` + `_render_with_intro` subset returned 33 with outro siblings; the 28 mentioned in `review_34.md` are the feature-34-only delta).

### Feature 35 (back) — `per_reel_photos_override` — PASS

- Migration: `alembic/versions/20260515_0003_reels_photos_override.py` (`down_revision="20260515_0002"`). Adds `reels.photos_override` JSONB nullable.
- ORM: `shared/db/orm.py:212-214` declares `photos_override: Mapped[list | None]` mapped to JSONB (retrofit landed during feature 37 to close the deviation flagged in review 35; verified in the live file).
- Domain `ReelState.photos_override` propagated by `_build_ingested_reel_state` so re-ingest never wipes the column (`_ingest_property_assets.py`).
- Repository: `modules/reels/infrastructure/reel_state_repository.py` — `_photos_override_to_jsonb_param` returns `None` for `None` / `[]`; `_REEL_COLUMNS` + INSERT + ON CONFLICT + `update_publish_status` + `update_workflow_state` + `save_local_artifacts` all forward `existing.photos_override`.
- Use case: `modules/reels/application/use_cases/update_reel_photos_override.py` validates the array (gap, duplicates, out-of-range), stamps `render_status="pending"`, calls `_maybe_enqueue_publish_job` (same machinery as feature 25 music). 409 `PHOTOS_OVERRIDE_LOCKED` when `workflow_state == 'approved'` OR `publish_status == 'published'`.
- Router: `modules/reels/transport/http/admin_reels_router.py:711-789` — `PATCH /photos`. Pydantic `extra='forbid'` + `StrictBool`.
- Renderer: `modules/rendering/application/frame_composition.py:107-109` applies `_apply_photos_override` before `build_local_selected_slides`. The override is read from the row peek (`PropertyContext.photos_override`), not from `publish_context`, so a PATCH between enqueue and dispatch wins.
- Tests: 14 integration (`test_reel_photos_override.py`) + 3 render (`test_render_with_photos_override.py`) — 17 ran green in this audit.

### Feature 36 (back) — `per_reel_subtitles_override` — PASS

- Migration: `alembic/versions/20260515_0004_reels_subtitles_override.py` (`down_revision="20260515_0003"`).
- ORM: `shared/db/orm.py:200-202` (declared on the model from the start — closed the lesson learned in feature 35).
- Domain + repository + ingest builder forward `subtitles_override` end-to-end without clobber (`reel_state_repository.py:135-149` for the JSONB param helper; `_ingest_property_assets.py:228-233` for the rebuild forwarding).
- Renderer: `modules/rendering/infrastructure/layout/subtitles.py:91-124` — when override is set, the autoCaptions flow is bypassed and the override cues become the segments; `modules/rendering/infrastructure/ffmpeg/filters.py:191-205` force-enables drawtext when an override is present even if `auto_captions_enabled=False`.
- Validation (use case + Pydantic): empty text, text >200, `in >= out`, negative time, overlap, duplicate/non-monotonic index, extra field, wrong type all return 422 with feature-specific error codes (`SUBTITLES_OVERRIDE_*`). 409 `SUBTITLES_OVERRIDE_LOCKED` matches feature 35 semantics.
- Router: `admin_reels_router.py:791-872`.
- Tests: 13 integration + 3 render + helper unit. The dedicated `test_subtitles_override_survives_re_ingest` invokes the real `_build_ingested_reel_state` helper. 16 ran green in this audit.

### Feature 37 (back) — `per_reel_slides_override` — PASS

- Migration: `alembic/versions/20260515_0005_reels_manifest_override.py` (`down_revision="20260515_0004"`).
- ORM: `shared/db/orm.py:215-227` (`manifest_override` JSONB nullable).
- Pydantic discriminated union over `kind` (`photo`/`voiceover`/`text`/`intro_card`/`outro_card`) at `modules/reels/transport/payloads/admin_reels.py:130-314`. Cross-slide invariants enforced in the body validator AND in the use case (`update_reel_slides_override.py:208-449`): unique `slide_id`, contiguous `position` covering `[0, N)`, sum of durations ≤ `target_duration_seconds * 1.5`, kind-specific required fields.
- Renderer: `modules/rendering/application/frame_composition.py:107-126` applies `_apply_manifest_override` after `_apply_photos_override` and before `build_local_selected_slides`. Non-photo kinds (`voiceover`, `text`, `intro_card`, `outro_card`) are persisted for the FE editor preview but explicitly filtered out from the photo array consumed by the current ffmpeg pipeline (documented at three sites in the code; not a silent skip).
- 409 `SLIDES_OVERRIDE_LOCKED` on approved/published reels (same gate).
- Router: `admin_reels_router.py:874-956`.
- Tests: 16 integration + 5 render + use-case helper unit — 17 ran green in this audit (the `test_reel_slides_override.py` + `test_render_with_slides_override.py` subset).

### Feature 30 (front) — `social_per_platform_publish_toggle` — PASS

- `src/features/social/SocialConfig.jsx` hydrates a `Set` from `useReelDefaults().platforms` with fallback to the canonical 7-platform default; `togglePublish` updates the Set optimistically and PUTs `/defaults` via `defaultsApi.saveDefaults` with the `platforms`-aware body (`buildPlatformsOnlyDefaultsBody`). Disabled accounts get `aria-pressed=false`, `disabled`, and the tooltip "Connect this network first". Subtab styling drops opacity to 0.55 on disabled platforms but keeps them clickable.
- Spec `tests/social_publish_toggles.spec.js` covers off/on/persist/disconnected-disabled/subtab-attenuation. `progress/review_30_social_per_platform_publish_toggle.md` reports 15 passes (5 scenarios × 3 viewports) and no regression.

Note: the task brief paraphrased feature 30 as "typography / something pre-sprint"; the actual feature is the social per-platform publish toggle. The frontend feature list confirms id 30 = `social_per_platform_publish_toggle`. No typography work appears in the sprint range 30-37.

### Feature 31 (front) — `subtitles_tab_cleanup_and_autocaptions_switch` — PASS

- `src/features/defaults/tabs/SubtitlesTab.jsx:20-39` reads `state[AUTOMATION_SETTINGS_KEYS.autoCaptions]` (canonical `'automation.autoCaptions'`), renders a top-level Toggle, and applies `subtitles-tab-subdued` (opacity 0.55, no `pointer-events: none`) to the Typography + Background-position cards when off.
- "Word highlight" card removed; `subHighlightWord` / `subHighlightColor` keys gone from `initialState.js`. `grep` confirms 0 hits across `src/` and `tests/`.
- `LivePreview.jsx` deleted along with its invocation in `ReelDefaultsConfig.jsx`. 0 hits on `LivePreview` in the source tree.
- Spec `tests/subtitles_autocaptions.spec.js` reported green (9 passes = 3 tests × 3 viewports) in the review.

### Feature 32 (front) — `reels_list_pagination_and_filters_ui` — PASS

- `src/features/reels/api.js:29-82` — `buildListQuery` strips undefined/empty/NaN params; sends `page`, `page_size`, `workflow_state` (CSV), `publish_status` (CSV), `q`.
- `src/features/reels/hooks.js` — `useReels` returns `{reels, countTotal, page, pageSize, hasMore, loading, error, refetch, agencyId}`. The nit on `reels` vs `items` / `refetch` vs `refresh` is intentional (matches the rest of the codebase that consumes `r.title`, `r.coverUrl`) and was accepted in the review.
- `src/features/reels/Dashboard.jsx` — toolbar with page-size dropdown (10/25/50, default 25), search debounced 300 ms with reset to `page=1`, filter dropdowns + tab shortcuts that update `publish_status`, URL state via `useSearchParams` round-trip (snake_case keys), `‹ Showing A–B of N ›` line, distinct empty / loading states with `data-testid`s.
- `tests/reels_list_pagination.spec.js` covers 6 scenarios × 3 viewports = 18 passes per the review.

### Feature 33 (front) — `agency_outro_upload_ui` — PASS

- `src/features/defaults/api.js:51-58` exposes `outroUpload`, `outroDelete`, `outroFileUrl`, `outroDownload`. `uploadVideo` sends `FormData` with a single `file` part to `POST /v1/admin/agencies/{id}/outro/upload`. No `VITE_ADMIN_API_TOKEN`, no inline JSON `Content-Type`.
- `IntroOutroTab.jsx` and `OutroCard.jsx` wire toggle/source segmented control/upload chip/replace/trash; client-side validation runs on size (≤50MB), MIME (`video/mp4|quicktime`), and duration (≤10s via `<video onloadedmetadata>`).
- Spec `tests/agency_outro_upload.spec.js` present + reported green.

### Feature 34 (front) — `agency_intro_upload_ui` — PASS

- Symmetric to feature 33 (`introUpload`, `introDelete`, `introFileUrl`, `introDownload`). The implementer factored `UploadVideoCard.jsx` to avoid duplication across `IntroCard.jsx` and `OutroCard.jsx`.
- Spec `tests/agency_intro_upload.spec.js` present + reported green.

### Feature 35 (front) — `per_reel_photos_override_ui` — PASS

- `src/features/reels/api.js:135-139` — `patchReelPhotos({photos: photos == null ? null : photos})` to `PATCH .../photos` (Pydantic `extra='forbid'` aware).
- `src/features/reels/hooks.js:250-259` — `useReelPhotosOverride` (debounce + optimistic + rollback factored into `editor/useReelDebouncedOverride.js`).
- `editor/PhotosPanel.jsx` consumes the hook for reorder + toggle-selected with debounce 500ms.
- 409 / 422 / 404 paths handled via the shared editor banner + toast helpers.
- Spec `tests/per_reel_photos_override.spec.js` present + reported green.

### Feature 36 (front) — `per_reel_subtitles_override_ui` — PASS

- `src/features/reels/api.js:156-160`. `useReelSubtitlesOverride` in `hooks.js:273-282`.
- `editor/SubtitlesPanel.jsx` uses `useReelDebouncedOverride` for auto-save + optimistic + rollback; client-side validation mirrors the back (in/out, overlap, text length, monotonic index).
- Spec `tests/per_reel_subtitles_override.spec.js` present + reported green.

### Feature 37 (front) — `per_reel_slides_override_ui` — PASS

- `src/features/reels/api.js:181-185`. `useReelSlidesOverride` in `hooks.js:297-306`.
- `editor/SlidesPanel.jsx` consumes the hook; reorder/edit-duration/visibility dispatch the PATCH with 500ms debounce, optimistic + rollback.
- Spec `tests/per_reel_slides_override.spec.js` present + reported green.

## Cross-reference (docs)

- Backend `docs/API.md` covers all four sprint endpoints: `/intro/upload`, `/outro/upload` (sections at lines 648 / 742), the three PATCH overrides (sections starting at lines 1018 / 1078 / 1133), and the pagination shape for `GET /reels` (`count_total`, `page`, `page_size`, `has_more` documented around line 525-544).
- Backend `docs/http_surface.md` and `docs/openapi.json` list the three PATCH paths plus the two upload paths.
- Frontend `DOCS.md` describes features 32 (pagination), 33 (outro upload), 34 (intro upload), 35 (photos override), 36 (subtitles override), 37 (slides override) with the expected request/response shapes and lock semantics.

## Top findings

1. **All sprint features are correctly wired end-to-end.** No GAP between spec acceptance, code, tests, and docs for any of 31-37 (back) or 30-37 (front).
2. **Migration chain integrity preserved.** `20260515_0002 → 0003 → 0004 → 0005` chained correctly; later non-sprint migration `20260517_0001_reels_auto_subtitles_snapshot` continues from 0005 (chain still consistent on `alembic upgrade head`).
3. **ORM consistency closed retrospectively.** Feature 35 originally omitted `ReelORM.photos_override`; feature 37 retro-fixed it during its own review (`shared/db/orm.py:212-214`). Verified live; no current drift.
4. **No `session.commit()` in the override repositories or use cases.** `grep` over the sprint files returns 0 hits, in line with the project rule.
5. **Pagination `count_total` always reuses the same `_build_filter_clause` as `list_recent_for_agency`**, so filters never drift between the items query and the total. Verified at `reel_query.py:19-62` + `:219-223` + `:319-323`.
6. **Brand-card intro/outro warnings are emitted at the ingest call site** (single point of truth), not the renderer. This is by design and was accepted in features 33 and 34 reviews; not a regression.

## Open items

- None blocking. Two follow-ups carried from earlier reviews (still in scope for future hardening, not for this sprint):
  1. Renderer-level `caplog` assertion for `brand_card` warning emission (today asserted only at the ingest use-case test).
  2. `pill` subtitle background rendering as `block` until ffmpeg drawtext gains rounded-corner support (documented MVP follow-up).
- Frontend Playwright suite for sprint specs was NOT re-executed in this audit pass; the existing reviewer reports cover the green runs from 2026-05-15/17 and the spec files are present. A fresh run is straightforward if the user wants to re-validate.

## Hard-constraint compliance

- Read-only: confirmed. No edits to `apps/`, `modules/`, `shared/`, `settings/`, `alembic/`, `tests/` or `src/` / frontend `tests/`. Only one new file written: this report under `progress/`.
- No service restarts. No migrations executed.
- No `bash ./init.sh`. Only targeted pytest subsets.
- Scope kept inside backend ids 31-37 and frontend ids 30-37.
