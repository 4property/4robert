# Review — feature 36 (`per_reel_subtitles_override`)

**Veredicto:** APPROVED

---

## 1. 6-point pattern audit

The reviewer's nightmare from feature 35 was point 2 (ORM column not declared
on the SQLAlchemy model). Feature 36 closes the new column on the ORM and
matches the rest of the pattern end-to-end.

| # | Requirement | File:line | Status |
|---|---|---|---|
| 1 | Alembic migration `20260515_0004_reels_subtitles_override.py`, `down_revision="20260515_0003"`, JSONB nullable column | `alembic/versions/20260515_0004_reels_subtitles_override.py:29-48` | OK |
| 2 | `ReelORM.subtitles_override` mapped to JSONB (the field feature 35 skipped for its own column) | `shared/db/orm.py:191-202` | OK |
| 3 | `ReelState.subtitles_override` domain field, default `None` | `modules/reels/domain/reel_state.py:64-76` | OK |
| 4 | Repository SQL: bind in INSERT, `ON CONFLICT DO UPDATE`, all three helper methods forward `existing.subtitles_override`, reader decodes JSONB→list | `modules/reels/infrastructure/reel_state_repository.py:135-149` (param helper), `:188-194` (reader), `:204-215` (`_REEL_COLUMNS`), `:254-256` + `:273-274` + `:311-313` (INSERT / ON CONFLICT / bind), `:384` (`update_publish_status`), `:438` (`update_workflow_state`), `:513` (`save_local_artifacts`) | OK |
| 5 | `_build_ingested_reel_state` propagates `state.subtitles_override` so re-ingest never wipes it | `modules/reels/application/use_cases/_ingest_property_assets.py:228-233` | OK |
| 6 | `_peeked_existing_state.subtitles_override` coerced and forwarded onto `PropertyContext.subtitles_override`, then onto `PropertyRenderData`, then read by `compose_subtitle_segments` + `build_overlay_filter` | `modules/reels/application/use_cases/ingest_property_into_reel.py:547-551` (forward), `:1245-1275` (coerce helper); `modules/rendering/application/frame_composition.py:314-319`; `modules/rendering/infrastructure/models.py:200-209`; `modules/rendering/infrastructure/layout/subtitles.py:91-124` (autoCaptions bypass); `modules/rendering/infrastructure/ffmpeg/filters.py:191-205` (gate) | OK |

The "music_id / photos_override drive-by" clobber bug is **not** re-introduced:
`update_publish_status`, `update_workflow_state` and `save_local_artifacts`
all forward `existing.subtitles_override` (lines 384, 438, 513 of
`reel_state_repository.py`).

---

## 2. Per-decision audit (leader's contract)

| Decision | Implementation | File:line | Status |
|---|---|---|---|
| URL `PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/subtitles` | Router decorator | `modules/reels/transport/http/admin_reels_router.py:646-648` | OK |
| Body `{"cues":[{index,text,in_seconds,out_seconds},...]}` OR `{"cues":null}` OR `{"cues":[]}` | Pydantic payload; `cues: list[ReelSubtitleCue] \| None`; default `None`; `extra='forbid'` on both layers | `modules/reels/transport/payloads/reel_subtitles_override.py:45-110` | OK |
| 200 returns `{"subtitles_override":[...],"render_status":"pending",...}` | Response body builder | `modules/reels/transport/http/admin_reels_router.py:716-727`; use case stamps `render_status="pending"` on `next_state` (`update_reel_subtitles_override.py:362`) | OK |
| 422 `in >= out` | Pydantic `out_seconds: gt=0` + cue model_validator | `payloads/reel_subtitles_override.py:75-92`; use case `_validate_cues` `SUBTITLES_OVERRIDE_INVALID_WINDOW` `:230-243` | OK |
| 422 negative time | Pydantic `ge=0` on `in_seconds`; `SUBTITLES_OVERRIDE_NEGATIVE_TIME` in use case | `payloads/...:67-74`; `update_reel_subtitles_override.py:218-229` | OK |
| 422 overlap (consecutive cues) | `_validate_cues_array` cross-cue check; use case `SUBTITLES_OVERRIDE_OVERLAP` | `payloads/...:112-133`; `update_reel_subtitles_override.py:257-268` | OK |
| 422 duplicate index | Cross-cue validator (`cue.index <= previous_index`); use case `SUBTITLES_OVERRIDE_NON_MONOTONIC_INDEX` | `payloads/...:118-124`; `update_reel_subtitles_override.py:244-256` | OK |
| 422 non-monotonic index | Same cross-cue validator | `payloads/...:118-124`; use case `:244-256` | OK |
| 422 empty text | Pydantic `min_length=1` | `payloads/...:58-66`; use case `SUBTITLES_OVERRIDE_EMPTY_TEXT` `:194-204` | OK |
| 422 text >200 chars | Pydantic `max_length=200` | `payloads/...:58-66`; use case `SUBTITLES_OVERRIDE_TEXT_TOO_LONG` `:205-217` | OK |
| 422 extra field (cue) | `model_config = ConfigDict(extra="forbid")` on cue | `payloads/...:48` | OK |
| 422 extra field (body) | Same on body model | `payloads/...:98` | OK |
| 422 wrong type | Pydantic type coercion fails (e.g. `text=42` raises) | `payloads/...:58` (`text: str`) | OK |
| 409 `SUBTITLES_OVERRIDE_LOCKED` when `workflow_state=='approved'` OR `publish_status=='published'` | `_LOCKED_WORKFLOW_STATES={"approved"}`, `_LOCKED_PUBLISH_STATUSES={"published"}`; raises `ReelSubtitlesOverrideLockedError` | `update_reel_subtitles_override.py:66-67`, `:321-331` | OK |
| Persistence: NULL for `null` or `[]`, JSONB array otherwise | `_subtitles_override_to_jsonb_param` returns `None` when value is falsy (covers `None` and `[]`) | `reel_state_repository.py:135-149` | OK |
| Renderer integration: autoCaptions BYPASSED when override is set; new `compose_subtitle_segments` + `build_overlay_filter` gate used | Override branch returns early in `compose_subtitle_segments`; filter gate force-enables drawtext | `layout/subtitles.py:91-124`; `ffmpeg/filters.py:202-205` | OK |
| Migration `20260515_0004`, `down_revision="20260515_0003"`, round-trip clean | Migration file; round-trip verified in §6 | `alembic/versions/20260515_0004_reels_subtitles_override.py:29-48` | OK |

---

## 3. Acceptance checklist (feature 36)

- [x] `PATCH /reels/{id}/subtitles` con cues válidos → 200; `reels.subtitles_override` persistido. (`test_patch_subtitles_persists_override_and_flips_render_status`)
- [x] Body inválido (overlap, in>=out, text vacío / >200) → 422. (10 dedicated tests cover all enumerated cases)
- [x] PATCH a reel approved → 409. (`test_patch_subtitles_returns_409_when_workflow_state_is_approved`, `test_patch_subtitles_returns_409_when_publish_status_is_published`)
- [x] Render usa los cues persistidos en el filter graph. (`test_renderer_uses_override_cues_when_present`)
- [x] PATCH con `cues=[]` o `null` → clear override; render vuelve a autoCaptions. (`test_patch_subtitles_with_null_clears_override`, `test_patch_subtitles_with_empty_list_clears_override`, `test_renderer_falls_back_to_autocaptions_when_override_is_none`)
- [x] Migración up/down/up funcional. (verified live, §6)
- [x] `pytest -q` verde — 1010 passed + 3 documented pre-existing flakes (same as features 32-35).
- [x] `apps.api --check` and `apps.worker --check` exit 0.

---

## 4. Survives-re-ingest test evaluation

`tests/integration/reels/test_reel_subtitles_override.py::test_subtitles_override_survives_re_ingest`
exercises the **realistic** call path that feature 25's `music_id` clobber
and feature 35's `photos_override` survivability needed:

1. PATCH the override via the real router (HTTP TestClient).
2. Peek state from the repository — confirm persisted.
3. Build a `_build_ingested_reel_state(...)` from the peek (the exact helper
   that would be called inside `_ingest_property_assets` on a re-ingest).
4. Save back via `uow.reels.states.save(...)`.
5. Reload and assert the override is still present.

This is **not** a SQL noop test — it invokes the actual builder that
historically dropped the column. It does, however, skip the full
`IngestPropertyIntoReelUseCase.execute()` pipeline (it does not enqueue a
real WordPress webhook). For feature 36 this is acceptable because:

- The builder (`_build_ingested_reel_state`) is the **only** place inside
  the ingest pipeline where the new state is constructed, and the test
  invokes it directly.
- The repository helpers (`update_publish_status`, `update_workflow_state`,
  `save_local_artifacts`) all forward `existing.subtitles_override`, and
  the broader integration suites (`test_ingest_property_into_reel_flow.py`
  etc.) exercise the full pipeline on every run.

**Recommendation (not blocking):** When feature 37 lands its
`slides_override`, consider lifting this into a shared "override survives
the full ingest pipeline" helper that drives a real webhook ingestion. For
feature 36 the current test is sufficient.

---

## 5. Renderer-side coverage (caveat acknowledged)

`tests/integration/rendering/test_render_with_subtitles_override.py`
asserts the **ffmpeg filter graph string** produced by
`build_overlay_filter`, not a real ffmpeg invocation or extracted SRT
track. This matches the existing feature 31 (`test_subtitle_settings_wiring.py`)
convention and keeps the suite fast. The implementer flagged this as §8.3
and listed a manual curl path against `:8001` for end-to-end visual
verification. **Acceptable.**

---

## 6. Independent verification re-run

```
$ .venv/bin/alembic upgrade head
20260515_0004 (head)
$ .venv/bin/alembic downgrade -1
Running downgrade 20260515_0004 -> 20260515_0003
$ .venv/bin/alembic upgrade head
Running upgrade 20260515_0003 -> 20260515_0004
20260515_0004 (head)
```

```
$ .venv/bin/python -m pytest \
    tests/integration/reels/test_reel_subtitles_override.py \
    tests/integration/rendering/test_render_with_subtitles_override.py -q
22 passed in 29.69s
```

```
$ .venv/bin/python -m pytest \
    tests/integration/reels/test_reel_photos_override.py \
    tests/integration/reels/test_admin_reels_music_override.py -q
22 passed in 39.93s     ← features 25 / 35 regression: clean
```

Note: the leader asked for `test_reel_music_override.py`, but the file is
named `test_admin_reels_music_override.py` in this repo — substituted.

```
$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes        rc=0
$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render     rc=0
$ bash ./init.sh
3 failed, 1010 passed, 14 warnings in 536.77s
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

The 3 failures are the same pre-existing flakes recorded since feature 32
(documented in features 32-35 review threads):

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state`
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads`

No new failures introduced by feature 36.

---

## 7. Hard rules

| Rule | Verdict |
|---|---|
| No `session.commit()` inside repositories | OK (`grep` in `modules/reels/infrastructure/` returns nothing) |
| No legacy imports (`services|application|repositories|core|domain`) | OK |
| Inter-module rule respected | OK — only `modules.delivery.domain.JobEnqueueRequest`, `modules.configuration.application.use_cases.compute_next_publish_slot` (pre-existing pattern across features 25 / 35), `modules.tenancy.domain`, `modules.catalog.domain`. No `.infrastructure` or sibling `.application` imports beyond the established shared helper. |
| Composition only in `apps/api/app_factory.py` / `apps/worker/runtime.py` | OK — `UpdateReelSubtitlesOverrideUseCase` default-constructed inside `create_admin_reels_router` (same pattern as features 25 / 35). |
| No test deleted/weakened by feature 36 | OK — the feature only adds two new test files (`test_reel_subtitles_override.py`, `test_render_with_subtitles_override.py`). The deleted tests visible in `git diff` predate this session and are unrelated. |
| Reel ORM gained one nullable column — existing tests still pass | OK (1010 / 1010 non-flake green). |
| No new module / repo created | OK — work confined to existing modules. |
| `--no-verify` / hook skipping | OK — none used. |

---

## 8. Issues found

**None blocking.**

Minor observations (not blocking, no action required for feature 36):

1. **Pydantic payload filename diverges from the spec.** Feature 36 spec
   lists `modules/reels/transport/payloads/admin_reels.py` (one file for
   all admin reel payloads). The implementer used a dedicated file:
   `modules/reels/transport/payloads/reel_subtitles_override.py`. Matches
   the convention used by `reel_photos_override.py` (feature 35) so the
   precedent is consistent, but the spec text is now stale. Worth a
   docs follow-up in feature 37 if a wider reconciliation is wanted.
2. **`ReelORM.subtitles_override` annotated as `Mapped[list | None]`**
   instead of `Mapped[list[dict] | None]` — implementer's §8.4 flags this
   intentionally. The historical sibling columns (`descriptions_override
   = Mapped[dict | None]`, `photos_override` missing from the ORM) use
   coarse generics, so `list | None` is consistent. No change needed.
3. **Survives-re-ingest test does not drive the full
   `IngestPropertyIntoReelUseCase`** — it exercises
   `_build_ingested_reel_state` directly. See §4 above for why this is
   acceptable for feature 36.

---

## 9. Open items (for feature 37 leader)

- [x] **Feature 36 closes ORM point 2 for its OWN column** (`subtitles_override`
      is declared in `ReelORM`). Confirmed `shared/db/orm.py:191-202`.
- [ ] **Feature 35's `ReelORM.photos_override` deviation remains open.**
      Implementer flagged it correctly in `progress/impl_36.md:240-249`
      and chose not to retro-fix in feature 36 to honour the leader's
      explicit directive ("Don't fix feature-35's deviations … unless
      you're literally touching the file in your normal scope"). I
      confirm the deviation is still present (`grep photos_override
      shared/db/orm.py` returns nothing) and concur with deferring it
      to feature 37, which will already touch `ReelORM` to add
      `slides_override`. **Approved deferral.**
- [ ] **`docs/API.md`, `docs/http_surface.md`, `docs/openapi.json`**
      not regenerated for the new PATCH route. Same scope rationale.
      Recommend feature 37 closes all three at once.

---

## 10. Summary

All six points of the feature-35-reviewer's clobber-bug checklist are
present and verified file:line. All leader-mandated HTTP / validation /
409 / persistence / renderer / migration decisions match exactly. The
survives-re-ingest test exercises the realistic builder. Migration
round-trip clean. `init.sh` reports the same 1010 / 3-flake baseline as
features 32-35. **APPROVED.**
