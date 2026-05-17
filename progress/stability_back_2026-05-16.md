# Stability Suite — 4Reels Backend — 2026-05-16

Audit run after closing sprint features 32-37. Read-only verification.

## 1. init.sh

- **Exit code**: 0
- **Tail (pytest summary)**:
  ```
  FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
  FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
  FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
  3 failed, 1032 passed, 14 warnings in 589.42s (0:09:49)
  ```
- **Delta vs baseline (1032 passed + 3 documented flakes)**: **match exact**. The 3 failures are the documented intermittents listed in the spec (one in `test_http_surface_contract.py`, two in `test_http_transport.py`). No regression.

## 2. pytest timing

- **Total wall time**: `real 9m15.374s` (`user 7m00.528s`, `sys 0m51.555s`). Pytest internal wall clock: `554.39s`.
- **Slowest 10 tests** (from `--durations=10`):

  | Time   | Test |
  |--------|------|
  | 5.60s  | tests/integration/configuration/test_seed_existing_agencies_music.py::test_seed_migration_downgrade_only_removes_seeded_rows |
  | 4.44s  | tests/integration/configuration/test_seed_existing_agencies_music.py::test_seed_migration_backfills_existing_agency_after_replay |
  | 3.73s  | tests/integration/configuration/test_seed_existing_agencies_music.py::test_seed_migration_skips_agencies_with_existing_tracks |
  | 3.71s  | tests/integration/notifications/test_migration_20260514_0007.py::test_migration_downgrade_drops_table_and_upgrade_recreates_it |
  | 2.68s  | tests/integration/reels/test_list_reels_pagination.py::test_q_matches_title_slug_or_property_reference |
  | 2.67s  | tests/integration/reels/test_list_reels_pagination.py::test_beyond_last_page_returns_no_items_but_count_total_intact |
  | 2.63s  | tests/integration/reels/test_list_reels_pagination.py::test_publish_status_filter_combines_with_workflow_state |
  | 2.63s  | tests/integration/reels/test_list_reels_pagination.py::test_blank_q_is_treated_as_no_filter |
  | 2.62s  | tests/integration/reels/test_list_reels_pagination.py::test_count_total_reflects_active_filters |
  | 2.62s  | tests/integration/reels/test_list_reels_pagination.py::test_page_size_query_wins_over_legacy_limit |

  Top contributors are migration-based seed tests and the new pagination suite from sprint feature 32. Nothing pathological (>10s).

## 3. Alembic chain reversibility

| Step | Exit code | Notes |
|------|-----------|-------|
| `alembic upgrade head` (1st)   | 0 | Clean. |
| `alembic downgrade base`       | **1** | **FAIL** — FK violation mid-chain. |
| `alembic upgrade head` (2nd)   | 0 | DB stayed at head (failed downgrade rolled back its transaction), so this is a no-op confirmation. |
| `alembic current` (final)      | — | `20260515_0005 (head)` ✓ |

**Downgrade failure detail** (captured stderr):

- The downgrade walked back from `20260515_0005` through `20260514_*` and into `20260513_*` successfully until reaching the step:
  ```
  Running downgrade 20260513_0004 -> 20260513_0003, Seed the ``side_banner`` render template row.
  ```
- That step issues `DELETE FROM render_templates WHERE template_id='side_banner' AND layout_variant='side_banner'` and Postgres refuses with:
  ```
  psycopg.errors.ForeignKeyViolation: update or delete on table "render_templates"
    violates foreign key constraint "fk_agency_reel_defaults_render_template_id"
    on table "agency_reel_defaults".
  DETAIL: Key (template_id)=(side_banner) is still referenced from table "agency_reel_defaults".
  ```
- Root cause: a later sprint (32-37 timeframe) seeded `side_banner` into `agency_reel_defaults.template_id` for one or more agencies, but the **downgrade of `20260513_0004` was not updated** to first detach those references (NULL them out, reset to `classic`, or delete the dependent rows). The seed migration is therefore not reversible against a DB that has had the sprint seed/replay sequence applied to it.
- File implicated: `alembic/versions/20260513_0004_seed_side_banner_render_template.py` (line 54 in the downgrade function per traceback).
- Final state is recoverable (DB still at head) because Alembic's per-step transaction rolled back. **But "all clean" was not achieved** — this fails CHECKPOINT C5 ("`alembic downgrade -1` reversible, or commented why not").

## 4. Process checks

| Check                            | Exit code | Tail |
|----------------------------------|-----------|------|
| `python -m apps.api --check`     | 0         | `FFMPEG: /usr/bin/ffmpeg`, banner OK |
| `python -m apps.worker --check`  | 0         | `Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s` |

Both green.

## 5. Hard rule scans

### 5a. Legacy imports (`from {services|application|repositories|core|domain}.`)
- `apps/`, `modules/`, `shared/`, `tests/`: **0 hits**. Clean.

### 5b. `session.commit(` inside `modules/*/infrastructure/`
- **0 hits**. Clean.

### 5c. Inter-module crossings (`from modules.X.application|infrastructure` from a different module Y)

True cross-module hits (32 lines, importer module ≠ imported module):

**Accepted patterns from earlier phases (still present, expected):**

- `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py:35-41` → `modules.rendering.infrastructure.{models, photos.filesystem, poster, runtime}` — accepted publishing→rendering adapter pattern (Phase 3).
- `modules/reels/application/orchestrator.py:50` → `modules.rendering.application.frame_composition.DefaultMediaRenderer` — orchestrator composition (feature 21).
- `modules/reels/application/orchestrator.py:247` (deferred import) → `modules.publishing.infrastructure.adapters.gohighlevel.factory` — feature 13/25 pattern.
- `modules/reels/application/use_cases/render_scripted_video.py:23` (deferred) → `modules.rendering.application.scripted_video.render_service` — feature 25.
- `modules/reels/application/use_cases/prepare_reel_assets.py:42-48` → `modules.rendering.infrastructure.photos.*` — feature 11/14.
- `modules/reels/application/content_generator.py:20-24` → `modules.publishing.infrastructure.social_copy.*` — feature 13.
- `modules/reels/application/use_cases/_ingest_property_diffs.py:20` & `_ingest_property_planning.py:24-28` & `_ingest_property_assets.py:88` → `modules.publishing.infrastructure.adapters.gohighlevel.*` and social_copy — feature 10/16.
- `modules/reels/application/use_cases/ingest_property_into_reel.py:41,44,82,778` → `modules.configuration.application.use_cases.{compute_next_publish_slot, read_aggregated_reel_profile}` + `modules.rendering.infrastructure.{render_template_settings, runtime.assets}` — feature 10/16.
- `modules/reels/application/use_cases/regenerate_reel.py:26` → `modules.configuration.application.use_cases.compute_next_publish_slot` — feature 16.
- `modules/reels/application/use_cases/_resolve_agency_music_pool.py:38` → `modules.rendering.infrastructure.runtime.assets` — feature 23.
- `modules/reels/domain/media_planning.py:15` → `modules.rendering.infrastructure.formatting.format_price` — feature 16.
- `modules/tenancy/application/use_cases/register_agency.py:12` → `modules.configuration.application.use_cases.seed_default_music_tracks` — feature 23.
- `modules/notifications/infrastructure/email_notification_repository.py:16` → `modules.configuration.infrastructure.repository_helpers.isoformat` — feature 31 (email notifications).
- `modules/publishing/infrastructure/social_copy/description.py:22` → `modules.rendering.infrastructure.data.PropertyReelRecord` — feature 13/16.

**Likely sprint 32-37 additions (new this sprint, all share the same pattern of reaching `compute_next_publish_slot` from the new override use cases):**

- `modules/reels/application/use_cases/update_reel_photos_override.py:45` → `modules.configuration.application.use_cases.compute_next_publish_slot.*`
- `modules/reels/application/use_cases/update_reel_subtitles_override.py:47` → same target
- `modules/reels/application/use_cases/update_reel_slides_override.py:61` → same target
- `modules/reels/application/use_cases/update_reel_music_override.py:43` → same target

These match the already-accepted pattern used by `regenerate_reel.py` (which also calls `compute_next_publish_slot`). They are arguably the same cross-module dependency repeated four times for the override use cases. **No new architectural violation** — but if you want to centralise this, the four sites are good refactor candidates (extract a shared `application` helper at the orchestrator/composition layer).

**Net assessment**: no `modules/X` → `modules/Y.{application,infrastructure}` for **new** Y/X pairs introduced by this sprint. Only the existing reels→configuration and reels→rendering channels grew by 4 more callsites.

## 6. Sprint coverage

Spec listed `tests/integration/reels/test_reel_music_override.py` — **that file does not exist**. The matching test file in the repo is `tests/integration/reels/test_admin_reels_music_override.py`. Ran with that substitution; full set went green.

Result: `117 passed in 162.51s` (exit 0). Per-file breakdown:

| Tests | File |
|-------|------|
| 17    | tests/integration/reels/test_reel_subtitles_override.py |
| 17    | tests/integration/reels/test_reel_slides_override.py |
| 14    | tests/integration/reels/test_list_reels_pagination.py |
| 13    | tests/integration/reels/test_reel_photos_override.py |
| 11    | tests/integration/configuration/test_intro_router.py |
| 10    | tests/integration/configuration/test_outro_router.py |
| 9     | tests/integration/reels/test_admin_reels_music_override.py *(spec said `test_reel_music_override.py` — does not exist)* |
| 7     | tests/integration/rendering/test_render_with_intro.py |
| 5     | tests/integration/rendering/test_render_with_subtitles_override.py |
| 5     | tests/integration/rendering/test_render_with_slides_override.py |
| 5     | tests/integration/rendering/test_render_with_outro.py |
| 4     | tests/integration/rendering/test_render_with_photos_override.py |
| **117** | **TOTAL** |

No unexpected failures.

## 7. Git status

- **Branch**: `ghl`, ahead of `origin/ghl` by 1 commit (`1749e02 x`).
- **Tracked-only `git status -uno`**: 101 files modified, 0 deleted, 0 staged. No new tracked files.
- **`git diff --stat HEAD` totals**: **101 files changed, 10254 insertions(+), 755 deletions(-)**.
- **Heaviest touched areas** (from the diff stat):
  - `apps/api/app_factory.py`, `apps/worker/main.py`, `apps/worker/runtime.py`
  - `modules/configuration/` — brand/defaults/music/social_templates (routers + payloads + repositories + ORM)
  - `modules/reels/` — admin_reels_router, list_reels, ingest_property_into_reel, regenerate_reel, domain/types, domain/reel_state, infrastructure/reel_query, reel_state_repository
  - `modules/rendering/` — ffmpeg/filters, ffmpeg/render_reel, layout/{models,panels,subtitles}, manifest, models, poster, preparation, render_template_settings, runtime/{__init__,assets}
  - `shared/db/orm.py`, `shared/db/uow.py`
  - Tests: 30+ files modified across integration and unit suites.
- **Untracked sprint output (FYI, did NOT run `-uall`)** — separate count via `git ls-files --others --exclude-standard modules/ tests/ alembic/` found **104 untracked `.py` files**, including:
  - 12 new Alembic migrations (`20260514_0001` through `20260515_0005`).
  - New `modules/notifications/` bounded context (domain/application/infrastructure, sprint feature 31).
  - New `modules/configuration/transport/http/{intro_router,outro_router,fonts_router,music_upload_router}.py`.
  - New override use cases under `modules/reels/application/use_cases/update_reel_{descriptions,music,photos,slides,subtitles}_override.py`.
  - Corresponding test files in `tests/integration/{configuration,reels,rendering,notifications}/`.
- **None of the sprint code is committed yet.** The single recent commit `1749e02 x` is opaque and the working tree carries the entire sprint footprint.

## 8. Verdict

**CLEANUP SUGGESTED** (functionally stable, two governance issues).

The runtime is healthy: `init.sh` matches the 1032+3-flake baseline exactly, `apps.api`/`apps.worker` `--check` are green, the 117-test sprint coverage subset is fully green, all hard-rule scans for legacy imports / `session.commit` in repos / new cross-module pairs return zero new violations. However two non-runtime issues need follow-up before this can be called "stable" in the C1–C6 sense:

1. **Alembic full chain is not reversible** (fails CHECKPOINT C5): `alembic downgrade base` aborts at `20260513_0004 -> 20260513_0003` because the `side_banner` render-template row is still referenced from `agency_reel_defaults` (seeded later in the sprint chain). Either the seed migration's `downgrade()` needs to NULL/reset dependent `agency_reel_defaults.template_id` rows first, or a later migration that introduces the `side_banner` references should drop them on its own downgrade before the chain reaches `20260513_0004`. Per the user memory note about preferring drop+recreate over surgical ALTERs in test DBs, day-to-day testing isn't affected — but the chain claim in the task spec ("should all be clean") is not met.
2. **Sprint footprint is uncommitted** (fails CHECKPOINT C6 spirit): 101 modified tracked files (+10254/-755) plus ~104 untracked `.py` files (new `notifications` BC, 12 new Alembic migrations, new override use cases, new routers, new tests) are sitting in the working tree without commits. The only recent commit (`1749e02 x`) has no descriptive message. Closing sprint features 32-37 normally means each lands as its own commit; that hasn't happened. The repo is functionally correct but the audit trail required by the harness lifecycle (§5 of AGENTS.md) is missing.

Recommend: (a) patch the side_banner downgrade chain so the Alembic round-trip is clean, (b) split the working tree into per-feature commits with proper messages before declaring the sprint closed.
