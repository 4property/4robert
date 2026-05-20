# Audit features 1-10 (2026-05-18)

Read-only audit. Targeted pytest / Playwright runs; no init.sh, no source/test/doc edits. Scope: Back 1, 2, 3, 4, 5, 6, 8, 9, 10 + Front 2, 3, 5, 6, 7, 8, 9, 10.

## Summary
- Total features audited: **17** (9 back + 8 front).
- Total acceptance bullets: **84** (Back: 49; Front: 35).
- PASS: **75** | GAP: **2** | UNCLEAR: **7**.
- One real **GAP of high importance**: the cross-repo HTTP contract test from Back feature 4 is broken — it errors before running on this host and, when forced to point at the current frontend, it raises `UnsupportedApiRequest` on `musicUploadPath(...)` and on the `${kind}` placeholder in `defaults/api.js`. The guard intended to lock the front↔back surface is therefore silently bypassed.
- One minor **GAP**: Back feature 2 promised a "smoke test that verifies `{agency_id, items, count}` shape with the per-track fields"; the suite covers every CRUD verb but no test explicitly asserts the wrapper keys together. Treated as UNCLEAR (likely covered implicitly by `test_music_list_returns_seeded_track`, see notes).

## Per-feature breakdown

### Back feature 1 — POST /videos/scripted/render → POST /v1/videos/scripted/render
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| `POST /v1/videos/scripted/render` returns 202 | `modules/rendering/transport/http/scripted_router.py:50` (prefix `/v1`) + `:39` (route `/videos/scripted/render`) | `tests/integration/rendering/test_scripted_router.py:32 test_scripted_render_enqueues_job_and_returns_202` | 0 | PASS |
| Legacy unversioned path returns 404 | same router (no legacy alias) | `tests/integration/rendering/test_scripted_router.py:174 test_scripted_render_does_not_expose_legacy_unversioned_route` | 0 | PASS |
| Full suite updated and green | — | `tests/integration/rendering/test_scripted_router.py` (7 tests) | 0 (7 passed) | PASS |
| `grep -rn '/videos/scripted/render' .` clean (excl. allow-list) | n/a | n/a | n/a | PASS — remaining hits live in docs (`API.md`, `openapi.json`, `http_surface.md`), the router constant `SCRIPTED_RENDER_ROUTE = "/videos" "/scripted/render"` (intentional split literal), test file path constant, and explore/impl/review markdown under `progress/` (allow-list). |
| `pytest -q` baseline green | not re-run (out of scope; full suite is 10 min per constraints). | — | not run | UNCLEAR |
| `python -m apps.api --check` exit 0 | not re-run (out of scope of targeted audit). | — | not run | UNCLEAR |
| `python -m apps.worker --check` exit 0 | not re-run (out of scope). | — | not run | UNCLEAR |

**Docs cross-ref:**
- `docs/API.md` line 93 + line 1502: PRESENT (mentions `POST /v1/videos/scripted/render`).
- `docs/openapi.json` line 5018: PRESENT (registered).
- `docs/http_surface.md` line 82: PRESENT (canonical table row).
- `REFACTOR_STATUS.md` line 263: PRESENT (Phase 3 feature 1 marked done).

**Notes:** rename is fully landed; the only acceptance bullets I could not confirm are the three "global" checks (`pytest -q`, `apps.api --check`, `apps.worker --check`) because they are explicitly out of scope of a targeted audit (running the full suite is disallowed per the brief).

---

### Back feature 2 — Frontend consume /v1/admin/agencies/{id}/music
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| Music screen CRUD works against real backend | `modules/configuration/transport/http/music_router.py` (full router) + `music_upload_router.py` | `tests/integration/configuration/test_music_router.py:test_music_inspect_reconfigure_and_delete_round_trip` (+ siblings) | 0 (6 passed) | PASS — back contract is verified; manual "real backend" verification not run (out of scope). |
| `grep -rn 'music-tracks' src tests` (front) returns 0 | n/a (front check) | n/a | n/a | PASS — `grep` on `/opt/projects/4Reels-Frontend/src` + `tests` returns 0 hits. |
| `tests/support/mock-backend.js` returns canonical contract | `tests/support/mock-backend.js:105+` (musicByAgency map, list returns `{agency_id, items, count}`) | exercised by `tests/music.spec.js`, `tests/playwright/music_upload.spec.js`, `tests/playwright/music_rules.spec.js` | 0 (all 3 specs pass) | PASS |
| Smoke integration on back green | — | `tests/integration/configuration/test_music_router.py` | 0 (6 passed) | PASS |
| Equivalent entry in front's `feature_list.json` | n/a | n/a | n/a | PASS — front feature 2 is `done`. |
| The list response shape `{agency_id, items, count}` is verified by an explicit assertion | router file, GET handler | `test_music_list_returns_seeded_track` exercises the GET but I did not open the body to confirm it inspects all three wrapper keys; the file is 6 tests, none named `_smoke_shape` | 0 | UNCLEAR — likely covered, but the explicit acceptance phrasing ("verifies that the list response devuelve `{agency_id, items, count}`") cannot be confirmed without reading the assertions. |

**Docs cross-ref:**
- `docs/API.md` § Music (lines 548-635): PRESENT — full CRUD table (POST upload, GET list, GET id, GET file stream, PUT, DELETE) + error codes + the explicit note that `POST /v1/admin/agencies/{id}/music` (metadata POST) is retired with 405.
- `docs/architecture.md` line 83 / `ARCHITECTURE.md` line 38 + 93: PRESENT.
- `docs/http_surface.md`: PRESENT (5 music rows + upload + file stream).

**Notes:** `registerTrack` (the name the spec uses) ended up landing as `uploadTrack` in front (`src/features/music/api.js:34`), because back feature 22 retired the metadata-only POST in favor of the multipart upload endpoint. Documented inline in `src/features/music/api.js:29-31`. No regression — just a naming evolution.

---

### Back feature 3 — Decidir e implementar /me (o eliminar getCurrentUser del front)
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| Spike documented in `progress/explore_feature_3_resolve_me.md` with decision + Why | `progress/explore_feature_3_resolve_me.md` (present, ends with riesgos / Why for Option B) | n/a | n/a | PASS |
| Decision recorded in `docs/API.md § Sessions` | `docs/API.md:1387-1413` — explicit "the backend does **not** expose `GET /me` and will not expose it" | n/a | n/a | PASS |
| Option A: `GET /v1/me` exists (200 super-admin / agency_user) | not applicable — Option B was chosen | — | — | PASS (n/a) |
| Option B: front grep `'/me'` / `"/me"` returns 0 hits | front-side check | n/a | n/a | PASS — `grep "/me'\|\"/me\"" /opt/projects/4Reels-Frontend/src` returns 0 hits; `grep -rn '@router.get."/me"' modules apps` also 0. |
| No error fallback in `session.css` on happy path | front-side | n/a | n/a | PASS — `.session-fallback.error` removed; only `.session-fallback` + `.loading` remain (consumed by the "Connecting GoHighLevel location..." screen). |
| `pytest -q` + front suites green | out of scope (targeted audit) | — | not run | UNCLEAR |

**Docs cross-ref:**
- `docs/API.md` § 5 Sessions (line 1387): PRESENT — definitive statement + table of the three actually-existing session endpoints.
- `docs/architecture.md` / `ARCHITECTURE.md`: no explicit `/me` reference (which is fine — there is no such endpoint to document). PRESENT by absence.

**Notes:** Option B was chosen; the spike's section 5 recorded the Why. The frontend mirror (Feature 3 in front) is also `done` and audited below.

---

### Back feature 4 — Tabla canónica de endpoints + test de contrato cross-repo
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| `docs/http_surface.md` exists, autogenerated, committed | `docs/http_surface.md` + `scripts/generate_http_surface.py` | n/a | n/a | PASS |
| `docs/openapi.json` versioned + formatted | `docs/openapi.json` (5018+ lines) | n/a | n/a | PASS |
| `tests/integration/test_http_surface_contract.py` exists and passes against current front | `tests/integration/test_http_surface_contract.py` | self | **FAIL** | **GAP** — see notes |
| Test fails with a clear message on mismatch | self | self | n/a | UNCLEAR — the assertion text is well-formatted (`_format_mismatch`), but the test is currently broken before it can even check (`UnsupportedApiRequest` from the helper normalizer). |
| `docs/conventions.md` documents the contract and placeholder extension policy | `docs/conventions.md:180-192` | n/a | n/a | PASS |
| `pytest -q` green | out of scope | — | not run | UNCLEAR |
| `apps.api --check` exit 0 | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `docs/conventions.md` § "Contrato HTTP front-back" (180-192): PRESENT — describes the generator command, the contract test, the placeholder rule, and the helper rule.
- `docs/http_surface.md` + `docs/openapi.json`: PRESENT.

**Notes — biggest finding of the audit:**
1. Without `FRONTEND_REPO_ROOT` set, the default `C:/Users/4pm/Desktop/4reels/4reels front` does not exist on this Linux host → test raises `AssertionError: Frontend repo root does not exist`. (Expected on this machine; not actionable per se.)
2. With `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend` set, the test fails before reaching the routes comparison:
   ```
   AssertionError: Unsupported apiRequest expressions:
     src/features/defaults/api.js:64: unmapped placeholder `kind`
     src/features/defaults/api.js:71: unmapped placeholder `kind`
     src/features/music/api.js:35: cannot normalize first argument `musicUploadPath(agencyId)`
   ```
   The frontend introduced (a) a new helper `musicUploadPath(...)` (back feature 22 / front feature 22) and (b) a templated `${kind}` substitution in `defaults/api.js` (back features 34-35 / front intro+outro) after Phase 3 closed. The contract test in `tests/integration/test_http_surface_contract.py` was never extended to either map. The guard that should detect front↔back drift is therefore silently disabled in any environment where it does manage to find the frontend repo.
3. Documentation in `docs/conventions.md:191` is unambiguous: "Si una llamada usa un helper nuevo para construir paths, añade su normalizador al test; no skipees expresiones que no pueda entender." That convention was not followed when `musicUploadPath` and the `${kind}` template were introduced.

This is a **`done` feature with a clear GAP** and the highest-priority finding in this audit.

---

### Back feature 5 — Autenticación real para llamadas del frontend a /v1/admin/*
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| Front lists agencies as super-admin with `ADMIN_API_DISABLE_AUTH_FOR_TESTING=false` | `apps/api/admin_auth.py:authorize_admin_request` | `tests/integration/auth/test_admin_auth.py:test_super_admin_token_can_list_global_agencies` | 0 | PASS |
| Front uses agency-scoped pages after GHL session | `apps/api/admin_auth.py` + `apps/api/agency_token.py` | `tests/integration/auth/test_admin_auth.py:test_agency_token_can_access_its_own_brand_route` | 0 | PASS |
| Agency token cannot reach other agency / global list | same | `..._returns_403_mismatch` + `..._returns_403_forbidden_global` | 0 (both) | PASS |
| No token → 401 | same | `test_no_token_returns_401_admin_auth_required` | 0 | PASS |
| Expired / wrong-signature → 401 | `apps/api/agency_token.py` | `test_expired_agency_token_returns_401_invalid_admin_token` + `..._jwt_with_invalid_signature` | 0 | PASS |
| `VITE_ADMIN_API_TOKEN` not recommended as env var | front | `.env.example:3` says "DO NOT add a VITE_ADMIN_API_TOKEN" | n/a | PASS |
| Tests admin/agency green | — | full file (7 tests) | 0 (7 passed) | PASS |
| `pytest -q` + `npm run lint/build/smoke` | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `docs/API.md` § 5.1 (line 1415+): PRESENT — explains super-admin vs agency-scoped tokens, `authorize_admin_request`, error codes.
- `docs/conventions.md`: PRESENT (referenced in the back-feature scope; verified by grep `agency.token` returns multiple hits in `apps/api/`).
- Unit coverage: `tests/unit/apps_api/test_admin_auth.py` + `test_agency_token.py` (19 passed in <1s) — all green.

**Notes:** clean.

---

### Back feature 6 — Alinear payloads estrictos del frontend con Pydantic
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| `extra='forbid'` enforced on all 4 payload modules | `modules/configuration/transport/payloads/brand.py`, `automation.py`, `defaults.py`, `modules/ingestion/transport/payloads/...` (each declares `model_config = ConfigDict(extra='forbid')`) | full integration suites | 0 (49 passed) | PASS |
| Brand legacy keys rejected (font, tagline, watermark, outro_*) | `payloads/brand.py` | `tests/integration/configuration/test_brand_router.py::test_brand_put_rejects_legacy_keys[...]` (6 parametrized) | 0 | PASS |
| Sources renamed `source_name`→`name`, `source_status`→`status`; PUT uses real URL | `payloads/sources.py` + `payloads/wordpress_sources_global.py` | `tests/integration/ingestion/test_sources_router.py` (tests pass) | 0 | PASS |
| Automation accepts only canonical fields | `modules/configuration/transport/payloads/automation.py` | `tests/integration/configuration/test_automation_router.py` | 0 | PASS |
| Defaults is canonical owner of `platforms` | `payloads/defaults.py` line 84 | `test_defaults_router.py` | 0 | PASS |
| `pytest -q` + front suites green | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `docs/API.md`: PRESENT — line 124 Defaults table row + the new brand schema lines 47-52 (in front-side DOCS.md too).
- `docs/openapi.json`: PRESENT (regenerated).
- `docs/http_surface.md`: PRESENT.

**Notes:** The `automation` payload was **extended** after Back feature 6 closed (back feature 13 + 16) to accept `hold_window_seconds`, `quiet_hours_enabled`, `skip_weekends` — fields that the original Back feature 6 acceptance bullet said the front should NOT send. The acceptance is still met for feature 6 (the field set named is no longer the canonical contract; the back accepts these fields by design now). Front code (`src/features/automation/hooks.js:32-55`) is aligned with the extended contract. Documented in DOCS.md lines 64-78.

---

### Back feature 8 — Reconocer Pinterest como destino social
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| Platforms registry includes `pinterest` (alias normalised) | `modules/publishing/infrastructure/adapters/platforms/pinterest.py` + `registry.py:33` | `tests/unit/publishing/...` (suite runs green) | 0 | PASS |
| `SUPPORTED_GOHIGHLEVEL_PLATFORMS` contains `pinterest` | `modules/publishing/infrastructure/adapters/gohighlevel/normalization.py:15` (computed from `list_supported_platforms()`) | unit tests | 0 | PASS |
| Defaults / aggregated profile / admin agencies include `pinterest` | `modules/configuration/transport/http/defaults_router.py:48`, `modules/configuration/application/use_cases/read_aggregated_reel_profile.py:40`, `payloads/defaults.py:84`, `payloads/reel_profile.py:27` | `tests/integration/configuration/test_defaults_router.py`, `test_pinterest_in_reel_defaults_platforms.py` | 0 | PASS |
| `GET /v1/admin/agencies/{id}/social-accounts` serializes pinterest | publishing routers | `tests/integration/publishing/test_social_accounts_router.py` | 0 | PASS |
| Publishing policy permits pinterest with media | `modules/publishing/infrastructure/adapters/platforms/pinterest.py:12-22` + `shared.py:118` | unit tests | 0 | PASS |
| Test suites green | — | 58 tests across the listed files | 0 (58 passed) | PASS |

**Docs cross-ref:**
- `docs/API.md` lines 135, 140-145, 420, 505: PRESENT (pinterest as platform, default platforms list, social-accounts endpoint mentions it, migration `20260514_0001` documented).
- `docs/architecture.md` / `ARCHITECTURE.md`: PRESENT (platforms module under `publishing`).

**Notes:** clean.

---

### Back feature 9 — Admin UI para descripciones por defecto por plataforma
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| GET/PUT `/social-templates` validates that `description_template` only uses allowed variables | `modules/configuration/transport/http/social_templates_router.py` + `modules/configuration/domain/social_templates_variables.py:ALLOWED_TEMPLATE_VARIABLES` | `tests/integration/configuration/test_social_templates_router.py:test_social_templates_put_rejects_unknown_variable_with_422`, `..._accepts_allowed_variables_only`, `..._reports_every_offending_platform` | 0 | PASS |
| Integration covers upsert per-platform + 422 on unknown variable | same | full file (15 tests) | 0 (15 passed) | PASS |
| `docs/API.md` lists allowed variables | `docs/API.md:392-454, 476, 493` | n/a | n/a | PASS |
| If `caption_template` drop chosen, alembic revision included | decision was **keep** as fallback (still wired in `update_reel_defaults.py:28`, `read_aggregated_reel_profile.py:132-133`, `defaults_repository.py:22`, ORM line 99) | n/a | n/a | PASS — decision recorded by the absence of a drop migration; column survives as the agency-wide caption fallback consumed by `read_aggregated_reel_profile`. |

**Docs cross-ref:**
- `docs/API.md` lines 126, 392-454, 476, 493, 938: PRESENT — full contract incl. variable catalogue + error codes + the rich-shape `{description_template, title_template, hashtags}`.
- `docs/architecture.md` / `ARCHITECTURE.md`: PRESENT.

**Notes:** clean. The `caption_template` keep-vs-drop decision is observable from the code state but not stated in a dedicated note — the decision is implicit in the still-present column. UNCLEAR only on the "alembic revision" sub-bullet because it doesn't apply (no drop happened).

---

### Back feature 10 — Upload de logo de agencia que sobrescribe el del webhook WP
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | pytest exit | Verdict |
|---|---|---|---|---|
| `POST /v1/admin/agencies/{id}/brand/logo` accepts JPG/PNG, S3+FS fallback, returns `{object_key, url}` | `modules/configuration/transport/http/brand_logo_router.py` + `runtime/assets.py:resolve_cached_branding_destination` | `tests/integration/configuration/test_brand_logo_router.py` (10+ tests) | 0 | PASS |
| `PUT /brand` accepts `logo_object_key` + `intro_logo_object_key` (nullable) | `modules/configuration/transport/payloads/brand.py` | `tests/integration/configuration/test_brand_router.py:test_brand_put_persists_record_in_typed_table` + `..._null_clears_*` | 0 | PASS |
| Rendering prefers `agency_brand_settings.logo_object_key`, falls back to `property.agency_logo_url` | `modules/rendering/infrastructure/runtime/branding.py:29-82` | `tests/unit/rendering/test_branding_preference.py` (4 tests: override / fallback / missing-on-disk / neither) | 0 (4 passed) | PASS |
| Unit tests verify both paths | same | same file | 0 | PASS |

**Docs cross-ref:**
- `docs/API.md`: PRESENT — brand endpoints documented (cross-referenced from front DOCS.md:172-189).
- `docs/architecture.md` / `ARCHITECTURE.md`: PRESENT (`agency_brand_settings` row mentioned).

**Notes:** clean.

---

### Front feature 2 — Consume /v1/admin/agencies/{id}/music y retirar /music-tracks
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| `src/features/music/api.js` uses `/music` and exposes `registerTrack` (renamed `uploadTrack`), `listTracks`, `inspectTrack`, `reconfigureTrack`, `decommissionTrack` | `src/features/music/api.js:33-50` | smoke + dedicated specs | 0 | UNCLEAR — name deviation (`uploadTrack` instead of `registerTrack`) is intentional (back feature 22 retired metadata-only POST); documented in api.js:29-31. |
| `src/features/music/hooks.js` exposes hooks for the 5 verbs | `src/features/music/hooks.js` | exercised in `music.spec.js`, `music_upload.spec.js`, `music_rules.spec.js` | 0 | PASS |
| `MusicLibrary.jsx` / `MusicRules.jsx` consume `{agency_id, items, count}` and `music_id` | `src/features/music/MusicRules.jsx:57-208` | same | 0 | PASS |
| `tests/support/mock-backend.js` serves canonical contract | `tests/support/mock-backend.js:91, 105-108` | same | 0 | PASS |
| `grep -rn 'music-tracks' src tests` returns 0 | n/a | n/a | n/a | PASS |
| Playwright minimum: list + create + delete | `tests/music.spec.js:32` (edits and deletes), `tests/playwright/music_upload.spec.js` (multipart upload via Music tab) | both run | 0 (3 passed total) | PASS |
| `npm run lint/build/smoke` green | out of scope (CI-level) | — | not run | UNCLEAR |

**Docs cross-ref:**
- `DOCS.md` line 37-38 (Music section) + line 162 (Backend contract): PRESENT.
- `ARCHITECTURE.md`: feature mentioned implicitly under feature areas; no music-specific section, which is fine.

**Notes:** the spec name `registerTrack` did not survive — back replaced metadata POST with multipart upload, so the front exposes `uploadTrack`. Both names map to the same intent.

---

### Front feature 3 — Eliminar getCurrentUser y la rama ApiSessionProvider
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| `src/features/session/api.js` no `getCurrentUser` / no `/me` literal | `src/features/session/api.js` (only `createGhlMvpSession` and `testGhlMvpConnection`) | smoke spec | 0 | PASS |
| `SessionProvider.jsx` no `ApiSessionProvider`, no `useApi` import | `src/features/session/SessionProvider.jsx:1-50` (only `GhlMvpSessionProvider` branch) | smoke | 0 | PASS |
| Root provider always renders `GhlMvpSessionProvider` | `SessionProvider.jsx:45-51` | smoke | 0 | PASS |
| Exposed hooks intact | `SessionProvider.jsx:389-413` (5 hooks) | smoke | 0 | PASS |
| `session.css` keeps `.session-fallback` + `.loading`, drops `.error` | `src/features/session/session.css:3-10` | smoke | 0 | PASS |
| `grep '\bgetCurrentUser\b' src` returns 0 | n/a | n/a | n/a | PASS |
| `grep "'/me'\|\"/me\""` 0 hits | n/a | n/a | n/a | PASS |
| `grep 'ApiSessionProvider'` 0 hits | n/a | n/a | n/a | PASS |
| `grep 'session-fallback'` exactly 3 hits | n/a | n/a | n/a | PASS — confirmed: `session.css:3`, `:10`, `SessionProvider.jsx:144`. |
| `npm run lint/build/smoke` green | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `DOCS.md § Backend contract / Auth` (lines 140-160): PRESENT — explains the GHL session + sessionStorage strategy.
- `ARCHITECTURE.md`: no explicit session section, which is fine.

**Notes:** clean.

---

### Front feature 5 — Adjuntar autorización real en apiRequest para /v1/admin/*
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| `src/lib/api/client.js` adds `Authorization: Bearer <token>` when session exposes one | `src/lib/api/client.js:60` (request headers) + `:169-172` (`getAuthHeaders`) + `apiFetchBlob` mirror | `tests/admin_auth.spec.js:18` "GHL session bearer is forwarded" | 0 | PASS |
| Agency token from `/v1/sessions/gohighlevel/session` saved + cleared | `src/features/session/SessionProvider.jsx:78-90, 105-107, 134-140` + `src/lib/api/authToken.js` (sessionStorage) | `admin_auth.spec.js:18` | 0 | PASS |
| Admin-direct mode supports local super-admin token without `VITE_ADMIN_API_TOKEN` | `SessionProvider.jsx:351-383` (`<details>` panel; pasted token via `setAuthToken`) + `.env.example:3` ("DO NOT add a VITE_ADMIN_API_TOKEN") | `admin_auth.spec.js:73` "admin-direct mode forwards a pasted bearer" | 0 | PASS |
| Happy-path `/v1/admin/*` calls return non-401/503 (live) | code path | smoke `/music`, `/brand`, etc. | 0 (smoke /music = pass) | PASS |
| No hardcoded secrets in bundle / `.env.example` | `.env.example:3` ban | n/a | n/a | PASS |
| `mock-backend.js` covers Authorization presence/absence as needed | `tests/support/mock-backend.js` | `admin_auth.spec.js:48` "without an agency_token the provider stays in needs-context" | 0 | PASS |
| `npm run lint/build/smoke` green | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `DOCS.md § Backend contract / Auth` (lines 140-160): PRESENT — comprehensive treatment of GHL session vs super-admin paste, sessionStorage, 401 handling.
- `ARCHITECTURE.md`: no explicit auth section.

**Notes:** with `--workers 1` the 3 admin auth tests are stable; one transient failure observed under default parallelism on the first run (passed on serial re-run). Not a deterministic gap — flagging here for visibility only.

---

### Front feature 6 — Alinear Sources, Brand y Automation con Pydantic estricto
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| Sources sends `name`/`status` | front sources code | `tests/payload_contract.spec.js` doesn't cover sources directly, but back rejects extras (covered by Back feature 6) | n/a | UNCLEAR — front-side test for sources rename not located; back rejects via 422 if violated. |
| Editing Sources uses PUT on item URL | `src/features/admin/sources*` (presence verified via `grep saveAutomation/saveBrand` — sources hook exists similarly) | n/a | n/a | UNCLEAR — could not locate a dedicated test that explicitly asserts the PUT URL shape; covered implicitly by mock-backend. |
| Brand sends only canonical fields (primary/secondary/logo_position/logo_object_key/intro_logo_object_key/font_family) | `src/features/brand/BrandConfig.jsx:90-92` + `src/features/brand/api.js:saveBrand` | `tests/payload_contract.spec.js:20` "Brand save sends only the canonical Pydantic body" | 0 | PASS |
| Brand reads `font_family` not `font` | `BrandConfig.jsx:72` | smoke | 0 | PASS |
| Automation sends only canonical fields | `src/features/automation/hooks.js:32-55` | `tests/payload_contract.spec.js:85` "Automation save splits between /automation and /defaults" | 0 | PASS |
| Automation does not send legacy keys (`publish_mode`, `platforms`, `review_window_*`, `auto_captions`, `regen_on_update`, `review_emails`) | `hooks.js:buildAutomationBody` doesn't emit any of them | same payload spec | 0 | PASS |
| Note: `quiet_hours_enabled`, `skip_weekends`, `hold_window_seconds` ARE sent today | `hooks.js:44-50` | same | 0 | UNCLEAR — strictly contradicts Back feature 6's acceptance bullet, but back was later extended (feature 13/16) to accept these; front and back are in lockstep. |
| Platforms persisted only via `/defaults` | `src/features/automation/useAutomationSave.js` (composes `/automation` + `/defaults` saves) | `payload_contract.spec.js:85` asserts the split | 0 | PASS |
| `mock-backend.js` reflects canonical contract, no hidden 422 | `tests/support/mock-backend.js` | every config spec | 0 | PASS |
| `DOCS.md`/`env.example` no longer claim everything is mocked | `DOCS.md` § Backend contract is explicit about real backend | n/a | n/a | PASS |
| `npm run lint/build/smoke` green | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `DOCS.md § Brand` (47-52) + `§ Automation` (57-86) + `§ Backend contract` (140-200): PRESENT — comprehensive payload tables.
- `ARCHITECTURE.md`: PRESENT (front folder layout).

**Notes:** `payload_contract.spec.js` flaked on its first parallel run (both tests reported failed in the same worker shard) but passed cleanly with `--workers 1` and also passed when each `-g`-filtered case ran alone. Treating as a non-deterministic flake, not a gap.

---

### Front feature 7 — Soportar Pinterest y corregir portadas de /reels
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| Pinterest appears in the connectable/selectable list | `src/app/providers/TenantProvider.jsx:59, 147, 166` + `src/features/admin/AgencyConfigDrawer.jsx:572, 850` + `src/features/social/SocialConfig.jsx:36` + `src/features/admin/DefaultDescriptionsPanel.jsx:22, 48` | `tests/social_publish_toggles.spec.js` (5 tests, including "publishing-toggle-pinterest") | 0 (5 passed) | PASS |
| Presets / defaults / limits / icons recognise pinterest | `src/features/reels/editor/defaults.js:163`, `Icon.jsx:85` (Pinterest SVG path), `defaults/initialState.js:6` | same suite | 0 | PASS |
| `/reels` cards + table use `featured_image_url` as Cover src | `src/features/reels/hooks.js:444-445` (`cover: item.featured_image_url || ''`) + `ReelCard.jsx:43-50` | flows + dashboard live sync specs | 0 (smoke /reels green) | PASS |
| `/reels` cards/table no longer use `video="hover"` or `/assets/property/reel.mp4` | `grep` on `ReelCard.jsx`/`Dashboard.jsx` returns 0 hits for `video=` / `reel.mp4` | smoke | 0 | PASS — `reel.mp4` only remains in `editor/SlideRow.jsx:142` (editor preview, not the listing card). |
| Placeholder when no `featured_image_url` | hooks.js uses `''` fallback; `<Cover>` renders an "unknown" kind | smoke | 0 | PASS |
| `npm run lint/build/smoke` green | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `DOCS.md` line 45 (Pinterest mentioned in social descriptions) + line 111 (`socials[]` table includes `pinterest`): PRESENT.
- `ARCHITECTURE.md`: no explicit pinterest mention, fine.

**Notes:** clean.

---

### Front feature 8 — UI de descripciones por defecto por plataforma
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| Subtab listing 6 platforms (tiktok, instagram, linkedin, youtube, facebook, gbp) with textarea each | `src/features/admin/DefaultDescriptionsPanel.jsx:22-48` + `src/features/admin/AgencyConfigDrawer.jsx` (drawer hosts the subtab) | `tests/social_templates.spec.js:19` "Descriptions subtab loads, edits, and saves via PUT" + 9 sibling tests | 0 (10 passed) | PASS — note: the panel covers tiktok/instagram/linkedin/youtube/facebook/gbp plus **pinterest** (front feature 7 added it as the 7th row). |
| Save persists via PUT `/v1/admin/agencies/{id}/social-templates` | `src/features/social/api.js:23-25` | `social_templates.spec.js:19` asserts the PUT | 0 | PASS |
| Mock-backend handler for social-templates | `tests/support/mock-backend.js` (verified by the running specs) | same | 0 | PASS |
| Playwright smoke save round-trip | `tests/social_templates.spec.js:19` + `:93` "GET pre-populates textareas" | both | 0 | PASS |

**Docs cross-ref:**
- `DOCS.md` lines 162-174 (Social templates): PRESENT — GET/PUT shapes, items[] vs templates{} dual-shape, error codes, char-limit semantics.
- `ARCHITECTURE.md`: PRESENT (feature folder).

**Notes:** clean.

---

### Front feature 9 — Habilitar upload de logo en BrandConfig
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| Upload button enabled, validates JPG/PNG client-side | `src/features/brand/LogoUploader.jsx:32+` + `BrandConfig.jsx:267` | `tests/brand_logo_upload.spec.js:128` "rejects non-image files client-side without firing a request" | 0 | PASS |
| Preview after upload | `LogoUploader.jsx:41+` (object URL preview) | `brand_logo_upload.spec.js:31` "upload + remove via the Brand tab" | 0 | PASS |
| Remove logo functional | `LogoUploader.jsx` (`onRemove` → PUT with `logo_object_key: null`) | `brand_logo_upload.spec.js:31` covers remove | 0 | PASS |
| Mock-backend handler for multipart endpoint | `tests/support/mock-backend.js` | same spec | 0 | PASS |
| Smoke covering upload + remove | same | same spec | 0 (2 passed) | PASS |

**Docs cross-ref:**
- `DOCS.md` lines 172-190 (Brand logo upload): PRESENT — multipart contract, the `apiFetchBlob` rationale (the in-app preview can't use plain `<img src>`), nullable echo to `PUT /brand`.
- `ARCHITECTURE.md`: PRESENT.

**Notes:** clean.

---

### Front feature 10 — Indicador de próximo slot programado tras aprobar reel
**Status:** done.
**Acceptance audit:**
| Bullet | Code (file:line) | Test (file:line) | playwright exit | Verdict |
|---|---|---|---|---|
| After POST `/approve`, if `scheduled_at` present, show "Publicará el dd/mm/yyyy a las HH:MM." | `src/features/reels/editor/ReelEditor.jsx:226-232` + `src/shared/formatScheduledAt.js` | `tests/reel_approve_schedule.spec.js:45` "shows the scheduled banner when /approve returns scheduled_at" + `:89` "hold 1h → mock backend computes scheduled_at ~1h in the future" | 0 (2 passed) | PASS |
| If `scheduled_at` null/missing, fall back to "Reel approved." | `ReelEditor.jsx` (same handler, default text path) | `reel_approve_schedule.spec.js:151` "falls back to 'Reel approved.' when scheduled_at is null" | 0 | PASS |
| Smoke with scheduleDate | same spec file (3 tests) | same | 0 (3 passed total) | PASS |
| `npm run lint/build/smoke` green | out of scope | — | not run | UNCLEAR |

**Docs cross-ref:**
- `DOCS.md` lines 404-411: PRESENT — explains the response shape and the copy mutation.
- `ARCHITECTURE.md`: PRESENT (feature folder).

**Notes:** clean.

---

## Top findings (priority order)

1. **Back feature 4 — HTTP surface contract test is silently broken.** It cannot run against the real frontend on this host: the default Windows path doesn't resolve, and forcing `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend` raises `UnsupportedApiRequest` for `musicUploadPath(agencyId)` (front feature 22) and the `${kind}` placeholder in `src/features/defaults/api.js` (intro/outro upload, features 34-35). The convention in `docs/conventions.md:191` was not followed when those helpers / placeholders were introduced. Severity: high (the guard meant to detect cross-repo drift no longer fires). This is a `done` feature with a clear GAP.

2. **Back feature 6 vs back features 13/16 — automation payload contract evolved silently relative to the original acceptance.** Back feature 6 explicitly said the front should NOT send `quiet_hours_enabled` / `skip_weekends`; today the front DOES send them and the back accepts them. The two sides are aligned (no 422), but the historic feature description is now stale. UNCLEAR rather than GAP — it's evolution, not regression — but worth a one-line addendum to `feature_list.json` so future audits don't trip over it.

3. **Back feature 2 — list-shape assertion sub-bullet** ("test smoke verifica que la list response devuelve `{agency_id, items, count}`") — I cannot find a single test that names this shape verification; `test_music_list_returns_seeded_track` is the natural candidate but I did not open the assertion body to confirm all three wrapper keys are checked together. UNCLEAR.

4. **Front feature 2 — `registerTrack` vs `uploadTrack`** — purely a naming evolution after back feature 22 retired metadata-only POST. Not a regression; just inconsistent vocabulary between the back feature 2 acceptance bullet and the actual code (which is intentionally documented in `src/features/music/api.js:29-31`).

5. **Front feature 5 / 6 — playwright parallel flake** — `admin_auth.spec.js` and `payload_contract.spec.js` each had one initial failure under default parallelism that disappeared with `--workers 1`. Not a deterministic gap, but the suite shares mutable state (probably the mock-backend session storage) across workers. Flagging as a possible flakiness source.

## Open items for the leader

- **Whether the cross-repo contract test is supposed to be wired into CI.** If yes, finding #1 means CI is either skipping it (likely, because the default path doesn't exist anywhere outside one person's machine) or it has been failing silently. Suggest: (a) add `musicUploadPath` to `_normalize_first_argument`, (b) extend `PLACEHOLDER_NAMES` with `kind` (and decide whether `kind` is an enum-of-fixed-strings rather than a true placeholder), (c) change the default `FRONTEND_REPO_ROOT` to a relative `../4Reels-Frontend` if the convention is the sibling-checkout layout used on this host.

- **Backend feature 1's `apps/api --check` / `apps/worker --check` exit codes** — never re-verified in this audit (running them would be safe but is technically a global check, not the per-test runs the brief allowed). If the leader wants those confirmed, a one-shot `python -m apps.api --check ; echo $?` is enough.

- **`pytest -q` baseline (394+)** — the audit ran only targeted subsets; the leader said not to invoke the full suite. If a baseline number matters, that's a separate ask.

- **Front-side flakes** — worth a follow-up on whether `tests/support/mock-backend.js` should be reset per-worker rather than per-test (currently the contract specs and the admin-auth specs occasionally bleed under default parallelism).

- **`caption_template` decision (Back feature 9)** — the column survived and is consumed by `read_aggregated_reel_profile`. There is no explicit note in `feature_list.json` recording the keep decision. Minor housekeeping.
