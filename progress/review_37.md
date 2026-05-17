# Review — feature 37 (`per_reel_slides_override`)

**Verdict:** APPROVED

The implementer landed the full 6-point pattern, closed all three
inherited follow-ups from review 36 (the `ReelORM.photos_override`
ORM deviation flagged on feature 35, the missing `docs/API.md`
sections for features 35/36/37, and the stale `docs/http_surface.md`
+ `docs/openapi.json`), wired a clean Pydantic v2 discriminated union
over the five slide kinds, and respected the leader's
"don't reinvent the renderer" trade-off — the four non-photo kinds are
persisted and round-tripped through PATCH → JSONB → `PropertyContext`,
but the renderer skip is *explicit* (filtered with a comment) and not
silent.

`./init.sh` re-ran in this review session: 1032 passed + 3 known
baseline flakes (`test_http_surface_contract`, two `test_http_transport`
health-shape mismatches) — identical baseline to features 32–36.
Migration round-trip clean (`20260515_0005 → 0004 → 0005`).

---

## 1. 6-point pattern audit

| # | What | File:line | Verified |
|---|------|-----------|---------|
| 1 | Alembic migration `20260515_0005_reels_manifest_override.py` (`down_revision="20260515_0004"`; `JSONB NULL`) | `alembic/versions/20260515_0005_reels_manifest_override.py:30-49` | OK |
| 2 | `ReelORM.manifest_override` declared `JSONB nullable` | `shared/db/orm.py:215-227` | OK |
| 3 | Domain `ReelState.manifest_override: list[dict[str, Any]] \| None = None` | `modules/reels/domain/reel_state.py:77-89` | OK |
| 4 | Repository SQL — `_REEL_COLUMNS`, INSERT `CAST(:manifest_override AS jsonb)`, `ON CONFLICT DO UPDATE SET manifest_override = EXCLUDED.manifest_override`, bind via `_manifest_override_to_jsonb_param`, reader via `_jsonb_to_optional_list` | `modules/reels/infrastructure/reel_state_repository.py:152-166` (helper), `:211-213` (reader), `:224-235` (`_REEL_COLUMNS`), `:277` (INSERT), `:296` (ON CONFLICT), `:336-338` (bind dict) | OK |
| 5 | `_build_ingested_reel_state` forwards `state.manifest_override` (so re-ingest never clobbers) | `modules/reels/application/use_cases/_ingest_property_assets.py:234-238` | OK |
| 6 | `_peeked_existing_state.manifest_override` → `_coerce_manifest_override` → `PropertyContext.manifest_override` → renderer wrap | `modules/reels/application/use_cases/ingest_property_into_reel.py:553-562` (forward), `:1289-1311` (coerce); `modules/rendering/application/frame_composition.py:107-125` (apply call), `:459-540` (helper) | OK |

Helper-method preservation (`update_publish_status`, `update_workflow_state`, `save_local_artifacts`) confirmed at `modules/reels/infrastructure/reel_state_repository.py:410`, `:465`, `:540` — every rebuild forwards `existing.manifest_override`.

---

## 2. Inherited follow-ups (A/B/C) closure audit

| Item | Status | Evidence |
|---|---|---|
| **A.** `ReelORM.photos_override` ORM field (feature 35 deviation flagged in review 36) | **CLOSED** | `shared/db/orm.py:203-214` — declared as `Mapped[list \| None]` JSONB nullable with `server_default=None`. Comment explicitly references the retro-fix scope. |
| **B.** `docs/API.md` — three new PATCH sections (`/photos`, `/subtitles`, `/slides`) | **CLOSED** | `docs/API.md:647-649` (table rows added for all three), `:779-838` (`PATCH .../photos` feature 35), `:839-893` (`PATCH .../subtitles` feature 36), `:894-960+` (`PATCH .../slides` feature 37). Each section carries: example request body, response 200 example, 422 contract, 409 contract, clear semantics. |
| **C.** `docs/http_surface.md` + `docs/openapi.json` include the 3 endpoints | **CLOSED** | `docs/http_surface.md:57-60` lists `/photos`, `/subtitles`, `/slides` with handler names. `docs/openapi.json` paths grep returns `…/photos`, `…/subtitles`, `…/slides` (alongside the previously-existing `…/approve`, `…/descriptions`, `…/images`, `…/manifest`, `…/music`, `…/reject`, `…/video`). |

All three are closed without partial work. No blocker carried forward.

---

## 3. Discriminated Union audit

Pydantic v2 `Annotated[Union[...], Field(discriminator="kind")]` at
`modules/reels/transport/payloads/admin_reels.py:305-314`. All 5
members present, each with its required fields enforced. `extra='forbid'`
applied at base + every member + body level.

| `kind` | Class file:line | Discriminator literal | Required fields (beyond base) |
|---|---|---|---|
| `photo` | `modules/reels/transport/payloads/admin_reels.py:174-199` | `Literal["photo"]` | `photo_position: int >= 0` |
| `voiceover` | `:202-225` | `Literal["voiceover"]` | `audio_url: str` (min_length=1) |
| `text` | `:228-246` | `Literal["text"]` | `text: str` (1-500 chars) |
| `intro_card` | `:249-270` | `Literal["intro_card"]` | none (optional `title`, `subtitle`) |
| `outro_card` | `:273-297` | `Literal["outro_card"]` | none (optional `title`, `subtitle`, `call_to_action`) |

Base fields (`_SlideBase` at `:130-171`):
- `slide_id: str` (`min_length=1`)
- `position: int` (`ge=0`)
- `duration_seconds: float` (`gt=0`)

Cross-slide invariants in `ReelSlidesOverridePayload._validate_slides_array` at `:353-...` (unique slide_ids, contiguous positions covering `[0, N)`); the use case re-checks the same invariants + the duration cap at `modules/reels/application/use_cases/update_reel_slides_override.py:208-449` for self-contained contract enforcement.

---

## 4. Renderer skip-for-non-photo audit (explicit vs silent)

**Skip is EXPLICIT.** The non-photo filtering in
`modules/rendering/application/frame_composition.py:_apply_manifest_override`:

- **Code-level filter** at `:494-497`:
  ```python
  photo_entries = [
      entry for entry in override
      if isinstance(entry, dict) and entry.get("kind") == "photo"
  ]
  ```
- **Docstring at the function itself** (`:459-488`) calls out the trade-off explicitly: *"filters the override down to `kind == 'photo'` entries (only those map to actual image slides today; the other kinds are persisted for the FE editor preview)"*.
- **Comment at the call site** in `_render_reel` (`:110-122`) explains: *"non-photo kinds (voiceover, text, intro_card, outro_card) are persisted for the editor and the FE preview, but do not contribute to the photo array consumed by the ffmpeg pipeline today."*
- Out-of-range `photo_position`s emit `logger.warning(...)` at `:506-510` and `:513-518`; an empty `photo_entries` list short-circuits at `:498-499` (falls back to the input unchanged); a completely-empty `reordered` falls back with a `logger.warning` at `:521-525`.

No silent skips. The leader's trade-off is documented at three layers (call-site comment, helper docstring, and code comment).

---

## 5. Per-decision audit table

| Decision | Verified | File:line |
|---|---|---|
| HTTP path: `PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/slides` | OK | `modules/reels/transport/http/admin_reels_router.py:744-746` |
| Body shape `{slides: [...] \| null \| []}` | OK | `modules/reels/transport/payloads/admin_reels.py:317-351` (default `None`, accepts list + null + empty) |
| 200 returns `{manifest_override, render_status, publish_enqueued, event_id?, job_id?, reason?, hint?}` | OK | `modules/reels/transport/http/admin_reels_router.py:815-826` |
| 5 discriminated union members | OK | see §3 |
| `extra='forbid'` at body + every slide | OK | `modules/reels/transport/payloads/admin_reels.py:141` (`_SlideBase`), `:338` (`ReelSlidesOverridePayload`) |
| 422 — invalid kind | OK | use case raises `SLIDES_OVERRIDE_INVALID_KIND` at `update_reel_slides_override.py:237-239`; Pydantic also rejects at the discriminator |
| 422 — missing kind-required field | OK | use case raises `SLIDES_OVERRIDE_MISSING_KIND_FIELD` at `:350-353`; Pydantic also rejects |
| 422 — position gap | OK | `:414-417` (`SLIDES_OVERRIDE_POSITION_GAP`) |
| 422 — duplicate position | OK | `:306-308` (`SLIDES_OVERRIDE_DUPLICATE_POSITION`) |
| 422 — duplicate slide_id | OK | `:265-267` (`SLIDES_OVERRIDE_DUPLICATE_SLIDE_ID`) |
| 422 — sum durations > `target * 1.5` | OK | `:430-449` (`SLIDES_OVERRIDE_DURATION_CAP_EXCEEDED`) |
| 422 — extra field at slide / body level | OK | Pydantic `extra='forbid'` on both `_SlideBase` and `ReelSlidesOverridePayload`; tests at `test_reel_slides_override.py:447`, `:464` |
| 422 — wrong type | OK | Pydantic typing on every field |
| 409 — `SLIDES_OVERRIDE_LOCKED` when `workflow_state == 'approved'` OR `publish_status == 'published'` | OK | `update_reel_slides_override.py:104-137` (error class), `:500-510` (lock guard); transport mapping `admin_reels_router.py:797-804` |
| Persistence: NULL when `null` / `[]`, JSONB array otherwise | OK | `_manifest_override_to_jsonb_param` at `reel_state_repository.py:152-166` (`if not value: return None`) |
| Renderer wrap point — inside `frame_composition._render_reel`, after `_apply_photos_override` and before `build_local_selected_slides` | OK | `modules/rendering/application/frame_composition.py:107-126` |
| Migration `20260515_0005_*` with `down_revision="20260515_0004"`, JSONB nullable, no server_default | OK | `alembic/versions/20260515_0005_reels_manifest_override.py:30-49` |

---

## 6. Hard rules audit

| Rule | Status | Notes |
|---|---|---|
| No `session.commit()` inside repositories | OK | `grep -n "session.commit" modules/reels/infrastructure/reel_state_repository.py modules/reels/application/use_cases/update_reel_slides_override.py` → 0 hits |
| No legacy imports | OK | `./init.sh` step 4: *"0 imports legacy en apps\|modules\|shared\|tests"* |
| No new code in `services/`, `application/`, `repositories/`, `core/`, `domain/` legacy dirs | OK | `./init.sh` step 4 confirms no legacy dirs reborn |
| Inter-module isolation (no `from modules.<other>.application\|infrastructure`) | OK | grep on the touched files returns 0 cross-module imports |
| Composition only in `apps/api/app_factory.py` and `apps/worker/runtime.py` | OK | `UpdateReelSlidesOverrideUseCase` injected via constructor at `admin_reels_router.py:185, :219-221` (no module-level singletons) |
| No test deleted/weakened | OK | 1010 baseline → 1032 (= 1010 + 22 new) — net positive |

---

## 7. Acceptance checklist (from `feature_list.json` id=37)

- [x] **`PATCH /reels/{id}/slides` con slides válidos → 200; manifest_override persistido.** — `test_patch_slides_persists_override_and_flips_render_status` covers this, plus `_VALID_ALL_KINDS` exercises all 5 kinds in one go.
- [x] **Body inválido → 422 con detalles por slide.** — 10 dedicated 422 tests in `test_reel_slides_override.py` (`test_patch_slides_rejects_*`).
- [x] **PATCH a reel approved → 409.** — `test_patch_slides_returns_409_when_workflow_state_is_approved` and `test_patch_slides_returns_409_when_publish_status_is_published`.
- [x] **Render construye plan desde `manifest_override`.** — `tests/integration/rendering/test_render_with_slides_override.py` has 5 rendering integration tests including `test_renderer_uses_manifest_override_photo_order` (reversed order applied).
- [x] **PATCH con `slides=[]` o `null` → clear override.** — `test_patch_slides_with_null_clears_override` and `test_patch_slides_with_empty_list_clears_override`.
- [x] **Migración up/down/up funcional.** — Re-run in this session: `20260515_0005 → 0004 → 0005` clean.
- [x] **pytest -q verde.** — `./init.sh` step 6 closes with `[OK] pytest verde` (1032 passed + 3 known flakes).
- [x] **`apps.api --check` y `apps.worker --check` exit 0.** — Both verified live in this review.

---

## 8. Verification re-run output (tails)

```text
$ .venv/bin/alembic current
20260515_0005 (head)

$ .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
Running downgrade 20260515_0005 -> 20260515_0004, Add ``reels.manifest_override`` JSONB column (feature 37).
Running upgrade 20260515_0004 -> 20260515_0005, Add ``reels.manifest_override`` JSONB column (feature 37).

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_slides_override.py tests/integration/rendering/test_render_with_slides_override.py -q
22 passed in 26.70s

$ .venv/bin/python -m pytest tests/integration/reels/test_reel_photos_override.py tests/integration/reels/test_reel_subtitles_override.py tests/integration/reels/test_admin_reels_music_override.py -q
39 passed in 66.97s

$ .venv/bin/python -m apps.api --check
RUNTIME READY: Yes

$ .venv/bin/python -m apps.worker --check
Worker --check OK: kinds=email_send, reel_publish, scripted_render outbox_events=review_requested worker_count=1 lease=900s poll=0.50s

$ bash ./init.sh
3 failed, 1032 passed, 14 warnings in 586.49s (0:09:46)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

The 3 failures are the documented baseline flakes (`test_http_surface_contract` — frontend repo path mismatch on this Linux host — and two `test_http_transport` health-payload shape mismatches), identical to the baselines reported in features 32-36. Not introduced by this feature.

---

## 9. Issues found

### Blocking
*None.*

### Non-blocking
*None.*

### Nits
1. `audio_url` (voiceover) is intentionally a loose `str` with no URL/MIME validation. The implementer flagged this as a deliberate trade-off (§10.2 of `impl_37.md`) because the renderer does not consume the field yet and the FE editor needs flexibility (workspace-relative, S3, signed CDN). Worth tightening when the renderer wires it up — track as a future feature, not a feature 37 blocker.
2. `text` slide max length is 500 chars (`modules/reels/transport/payloads/admin_reels.py:241`). Mirrors 2× the subtitle cue cap. If the FE/brand team prefers tighter, the change is single-source at `:238-246`. Non-blocking.
3. The implementer's report claims migration round-trip output line "20260515_0005 (head)" — matches the live re-run in this review.

---

## 10. Open items for the leader

### Manual QA on `:8001`

Restart `:8001` (per `AGENTS.md §7`) so the new PATCH route registers, then exercise:

```bash
ADMIN_TOKEN="$(grep ADMIN_API_TOKEN .env | cut -d= -f2)"
BASE="http://127.0.0.1:8001/v1/admin/agencies"

# 1. Mixed-kinds happy path (200) — confirm body echoes manifest_override
#    and the rendered MP4 (after the worker picks the job) only reflects
#    the photo kinds for now.
curl -fsS -X PATCH \
  "${BASE}/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[
        {"slide_id":"intro-1","position":0,"duration_seconds":2.0,"kind":"intro_card","title":"Welcome"},
        {"slide_id":"photo-A","position":1,"duration_seconds":3.0,"kind":"photo","photo_position":2},
        {"slide_id":"photo-B","position":2,"duration_seconds":3.0,"kind":"photo","photo_position":0},
        {"slide_id":"vo-1","position":3,"duration_seconds":1.5,"kind":"voiceover","audio_url":"https://cdn.example.com/vo.mp3"},
        {"slide_id":"outro-1","position":4,"duration_seconds":2.0,"kind":"outro_card","title":"Thanks","call_to_action":"Book a viewing"}
      ]}'

# 2. Clear (200) — body's manifest_override should be null
curl -fsS -X PATCH \
  "${BASE}/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":null}'

# 3. 422 — unknown kind
curl -i -X PATCH \
  "${BASE}/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[{"slide_id":"x","position":0,"duration_seconds":3.0,"kind":"banana"}]}'

# 4. 422 — sum durations exceeds target * 1.5
curl -i -X PATCH \
  "${BASE}/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[
        {"slide_id":"a","position":0,"duration_seconds":10.0,"kind":"photo","photo_position":0},
        {"slide_id":"b","position":1,"duration_seconds":10.0,"kind":"photo","photo_position":1},
        {"slide_id":"c","position":2,"duration_seconds":10.0,"kind":"photo","photo_position":2},
        {"slide_id":"d","position":3,"duration_seconds":10.0,"kind":"photo","photo_position":3},
        {"slide_id":"e","position":4,"duration_seconds":10.0,"kind":"photo","photo_position":4}
      ]}'

# 5. 409 — approved reel
curl -i -X PATCH \
  "${BASE}/<agency>/reels/<site>/<property>/slides" \
  -H "Authorization: Bearer ${ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"slides":[{"slide_id":"x","position":0,"duration_seconds":3.0,"kind":"photo","photo_position":0}]}'
# → 409 {"code":"SLIDES_OVERRIDE_LOCKED", ...}
```

### Future renderer extension (non-photo kinds)

The skip in `_apply_manifest_override` is the natural extension point
for a future feature that materialises the four non-photo kinds at
render time:

- **`voiceover`**: download `audio_url` to a workspace-staging path and
  weave it into the ffmpeg mixer (probably as an additional input
  stream concatenated with the music ducking pipeline). Will likely
  need a new domain port (`VoiceoverAssetStorePort`) and validation
  tightening on `audio_url` (MIME / size / signed-URL).
- **`text`**: emit a synthetic image (e.g. a black background with
  `drawtext`) and inject it into `selected_photo_paths` at the right
  `position`. Brand colors / fonts should reuse the agency's existing
  brand customisation (features around brand_colors_and_fonts).
- **`intro_card`** / **`outro_card`**: similar to `text` but pulling
  from the agency's intro/outro template assets (features 19/20). The
  template can already render a card from a title/subtitle — just need
  to splice the rendered card into the photo array.

None of those require a schema change or a new HTTP contract — the
extension point is purely inside `frame_composition.py`. Suggest
landing them as separate features (one per kind) so the renderer
changes stay small and reviewable.

### Frontend integration

The frontend repo (`/opt/projects/4Reels-Frontend`) has feature 37 on
its side of the plan ("SlidesPanel del front permite editar la lista/orden
de escenas del reel"). The backend contract is now stable; the FE can
wire `SlidesPanel → PATCH /slides` with confidence that the body shape
will not change in this feature.
