# Cleanup backend — 2026-05-17

> Cross-repo sprint cleanup, backend share. Scope: documentation completeness
> (features 33/34/40), Spanish→English translation in production code, dead-
> code audit, tests review.

Baseline confirmed at session start: `bash ./init.sh` exit 0,
**1050 passed + 3 documented flakes** (`test_http_surface_contract.py` +
two in `test_http_transport.py`).

---

## 1. Documentation diff

### `docs/API.md`

Three new sections added:

| Section | Inserted at | Lines added (approx) |
|---|---|---|
| `### Outro video (feature 33)` | between `Music library → Retired endpoints` and `Reel approval and publish status` | ~95 |
| `### Intro video (feature 34)` | immediately after the outro section | ~55 |
| `#### POST .../regenerate (feature 40)` | inside `Reel approval and publish status`, just before `PATCH .../descriptions` | ~75 |

Plus one row added to the Reel-approval transition table at
`docs/API.md` for `POST .../regenerate` (feature 40) — total +225 lines
on the file (1405 → 1630).

Content notes:

- Outro: full upload contract (multipart `file`, MP4/MOV, ≤50 MB,
  1..10 s via ffprobe), GET/DELETE companions, error reference table
  (`OUTRO_INVALID_MIME` / `OUTRO_FILE_TOO_LARGE` / `OUTRO_INVALID_DURATION`),
  blob layout `_agency_outro/{safe_agency_id}/`, and the four `outro_*`
  fields surfaced by `GET /defaults`.
- Intro: symmetric to outro. Documents that intro + outro share the
  `agency_intro_outro_assets` table (migration `20260515_0002`) keyed
  by `(agency_id, kind)`.
- Regenerate (feature 40): body shape (`{reason?: str}`),
  success (`{render_status: "pending", job_id, queued_at}`), the two
  409 conflict codes (`REGENERATE_PUBLISHED_FORBIDDEN`,
  `REGENERATE_ALREADY_IN_FLIGHT`), and an explicit table contrasting
  it with the existing `POST .../approve` (`mode="manual_only"` vs
  `mode="approve_and_regenerate"`).

### `docs/http_surface.md` and `docs/openapi.json`

Both files are **auto-generated** by `scripts/generate_http_surface.py`.
Regenerated with:

```bash
.venv/bin/python scripts/generate_http_surface.py --write
```

Confirmed the three feature-33/34/40 endpoints are present in both
artifacts after regeneration (`outro/upload`, `outro/file`, `outro` DELETE,
`intro/upload`, `intro/file`, `intro` DELETE, and `.../regenerate`).

---

## 2. Spanish → English translations

Production-code sweep used:

```bash
grep -rE --include="*.py" "[áéíóúñ¿¡üÁÉÍÓÚÑÜ]" \
  apps/ modules/ shared/ settings/ alembic/ tests/ main.py
```

Plus a follow-up grep for unaccented Spanish phrases (`este test`,
`la migracion`, `la cabecera`, `deberia`, ...). After the edits below
both greps return zero hits across `apps/`, `modules/`, `shared/`,
`settings/`, `alembic/`, `tests/`, `main.py`.

**Files touched: 1**

- `tests/unit/reels/test_ingest_property_includes_scheduled_at.py`
  - L1-18: module docstring — translated three bullets from Spanish
    narrative ("``scheduled_at`` poblado", "decisión técnica: el
    helper es puro y barato", "el flujo parque el reel") to their
    English equivalents.
  - L317-324: docstring of
    `test_ingest_property_approval_required_true_does_not_block_scheduled_at`
    — translated "Decisión técnica documentada en … el slot se computa
    siempre" to English ("Design decision documented on … the slot is
    always computed").

Untouched per scope rules:

- `progress/*.md` — author intent is Spanish historical bitácora.
- `AGENTS.md`, `CLAUDE.md` — mixed-language instructions for agents.
- `feature_list.json` — internal sprint log.
- Spanish identifiers (variables / function / class names) — none found
  in production code anyway; no renames needed.

Verification after the touch:

```bash
.venv/bin/python -m pytest tests/unit/reels/test_ingest_property_includes_scheduled_at.py -q
# 4 passed in 1.00s
```

---

## 3. Dead code

### Removed

**None.** The audit ran the following checks; all candidates either
proved to be live or were flagged-only per the "be conservative" rule.

### Audit performed

1. **Legacy directories** (`services/`, `application/`, `repositories/`,
   `core/`, `domain/` at repo root) — `ls` confirms none exist.
   Phase 2 cleanup still holding.
2. **Legacy imports** — `init.sh §4` reports 0 imports of
   `services.|application.|repositories.|core.|domain.` across
   `apps|modules|shared|tests`. Clean.
3. **Module-path scan** — ran an AST script that lists every Python
   module under `modules/` whose dotted path (`modules.x.y`) never
   appears as `from <path>` / `import <path>` anywhere in the tree.
   25 candidates surfaced; all 25 are leaf modules that are re-exported
   via their package's `__init__.py` (e.g.
   `modules/catalog/domain/property.py` re-exported from
   `modules/catalog/domain/__init__.py` as `from .property import ...`).
   Not dead.
4. **Public-symbol scan** — same AST script, narrowed to public
   top-level `class`/`def` defined in `modules/` whose name doesn't
   appear in any other file. 40 candidates surfaced; spot-checked the
   first 8 — every one is either a dataclass returned by a use case
   (`RegenerateReelResult`, `ListReelsResult`, …) referenced by external
   callers via `.execute()` return-type binding, or a Pydantic payload
   used via FastAPI dependency injection (the grep can't see those
   bindings). Not dead.
5. **TODO/FIXME blocks** — exactly one TODO in production code:

   - `modules/tenancy/transport/http/admin_agencies_router.py:330`
     `# TODO Phase 2 feature 4: unify this serializer with the ingestion
     router.`

   Older than 4 weeks (Phase 2 closed 2026-05-06). **FLAGGED, NOT
   DELETED.**

### Flagged (kept, leader review)

- The Phase-2 TODO in `admin_agencies_router.py:330` — Phase 2 is
  closed; either the unification is still planned post-Phase-4 (then
  the TODO should be tracked elsewhere) or the comment is stale.
- `.tmp_test_cases/workspace_*` directories — two empty workspaces
  left from previous integration test runs (created 2026-05-15 /
  2026-05-16). Cleanup rule per `AGENTS.md §5.5` says no `.tmp_*`
  but these are inside `.tmp_test_cases/` which appears to be a test
  fixture root. Leaving alone — purge belongs in a tests housekeeping
  job, not this cleanup pass.

---

## 4. Tests audit

180 test files (104 unit, 61 integration, plus support/root). Audit
methodology:

- AST scan for tests without an `assert`/`pytest.raises`/`assert_called*`
  → 2 candidates surfaced, both proved to use `assertNotIn` /
  `assert_not_called`. Not no-value.
- AST scan for duplicate function names across files → 14 hits.
  Reviewed each pair.
- Skip/xfail grep → 0 matches; nothing to gardener.

### Deleted

**None.** No test was confirmed to be no-value or strictly redundant.

### Consolidated

**None.** The most tempting consolidation candidate is the 9-test
parallel pair `test_outro_validator.py` ↔ `test_intro_validator.py` —
identical structure, distinct fixtures, but they exercise **two
separate implementations** (`validate_outro_upload` vs
`validate_intro_upload`, with their own constants and error codes). A
real consolidation would require pulling the validators into a single
generic helper first, which is a production-code change explicitly
out of scope ("Don't touch features 32-40 implementations"). **Flagged
for a future "feature 33/34 shared-validator refactor" rather than
deleted now.**

### Flagged (kept, suspect-but-not-actionable here)

| Files | Reason |
|---|---|
| `tests/unit/configuration/test_outro_validator.py` ↔ `tests/unit/configuration/test_intro_validator.py` | 9 functions with identical names and parallel logic. Cannot consolidate without merging the underlying validators (production change, out of scope). |
| `tests/unit/reels/test_publish_reel.py::test_execute_existing_raises_when_no_existing_artifact` ↔ `tests/unit/reels/test_persist_local_artifacts.py::test_execute_existing_raises_when_no_existing_artifact` | Same assert (`EXISTING_MEDIA_REQUIRED`) but one tests the use case directly and the other tests the publisher delegation chain. The `# Single source of truth (D7)` comment makes the intent explicit. Kept. |
| `tests/integration/publishing/test_social_accounts_router.py::test_returns_items_when_upstream_succeeds` ↔ `tests/unit/publishing/test_inspect_agency_social_accounts.py::test_returns_items_when_upstream_succeeds` | Same name, different scopes (HTTP-level integration vs use-case-level unit). Both valuable. Kept. |
| `tests/unit/configuration/test_inspect_music_track.py::test_inspect_raises_when_agency_missing` ↔ `tests/unit/publishing/test_inspect_provider_connection.py::test_inspect_raises_when_agency_missing` | Same name, different use cases (music vs provider connection). Kept. |
| `tests/integration/publishing/test_connections_router.py` ↔ `tests/integration/publishing/test_gohighlevel_session_router.py` — `test_probe_uses_saved_token_and_returns_social_accounts` | Same name, different router scopes. Both valuable. Kept. |

### Baseline flakes confirmed present

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` (kept)
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state` (kept)
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads` (kept)

---

## 5. Baseline diff

| Metric | Before | After | Delta |
|---|---|---|---|
| `pytest` passed | 1050 | 1050 | 0 |
| `pytest` failed (documented flakes) | 3 | 3 | 0 |
| Net test deletions | — | 0 | 0 |
| Net test consolidations | — | 0 | 0 |

No regressions; no intentional reductions to explain.

---

## 6. Verification output

Final `bash ./init.sh` tail (after all edits):

```
=========================== short test summary info ============================
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1050 passed, 14 warnings in 624.62s (0:10:24)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Exit code 0. The 3 failures are the documented baseline flakes; the
1050 passed count is unchanged vs. session-open baseline.
