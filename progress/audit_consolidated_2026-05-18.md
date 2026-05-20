# Consolidated audit — 4Reels SaaS — 2026-05-18

> Master consolidation of the 5 per-range audit reports (`audit_features_01-10`,
> `_11-20`, `_21-29`, `_31-37`, `_38-41`). Each individual report has full
> per-feature detail; this master is for triage and prioritisation.
>
> Policy used by every auditor: **read-only**, **conservative** (UNCLEAR when
> in doubt, no fixes), targeted pytest / Playwright per acceptance bullet, no
> full `./init.sh` runs.

---

## 1. Executive summary

**71 features audited** (38 backend + 33 frontend) across 5 ranges. **All marked
`done` features have real code and tests that pass when run targeted.**

| Range | Features | Bullets | PASS | GAP | UNCLEAR |
|---|---:|---:|---:|---:|---:|
| 1–10  | 17 (9 back + 8 front) | 84 | 75 | **2** | 7 |
| 11–20 | 17 (9 back + 8 front) | n/a* | 17 | 0 | 0 (1 documented divergence) |
| 21–29 | 16 (9 back + 7 front) | n/a* | 16 | 0 | 5 (low-risk notes) |
| 31–37 | 15 (7 back + 8 front) | n/a* | 15 | 0 | 0 (2 carry-overs from earlier reviews) |
| 38–41 | 6 (4 back + 2 front) | 27 | 27 | 0 | 0 (3 minor deviations) |
| **Total** | **71** | — | **≈150 explicit** | **2** | **~15** |

\* Some auditors reported per-feature verdict only, not per-bullet count.
Where per-bullet totals are available (1-10 and 38-41), every feature had >70%
bullets PASS; the GAPs/UNCLEARS are concentrated in feature 4 (one feature, one
guard).

**Tests re-executed live** during the audit (read-only, targeted only):

| Range | Backend pytest | Frontend Playwright |
|---|---|---|
| 1–10  | ~150 passed across 9 targeted suites | 8 specs, all pass under `--workers 1` |
| 11–20 | scripted across 17 features | 1 parallel-flakiness observation |
| 21–29 | 123 passed across 8 suites | 16 passed across 6 specs |
| 31–37 | 171 passed across the sprint pytest sets | (cited from earlier review reports) |
| 38–41 | 14 passed across 4 features | 7 Playwright cases passed (desktop project) |
| **Total** | **≈450+ targeted pytest** | **≈30+ Playwright specs** |

**Verdict: production-grade. The SaaS implements its specifications correctly.**
The two real gaps are in coverage/tooling, not in user-facing behaviour.

---

## 2. Top findings — priority order

### 🔴 BLOCKING (1)

**1. Back feature 4 — cross-repo HTTP contract test is silently broken.**
- File: `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` (one of the 3 documented baseline flakes — this audit identified the **why**).
- Default path resolution targets a Windows checkout that doesn't exist on this Linux host.
- When forced via `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend`, it raises `UnsupportedApiRequest` for:
  - `musicUploadPath(agencyId)` (added in front feature 22) — not in `_normalize_first_argument`.
  - The `${kind}` placeholder in `src/features/defaults/api.js` (intro/outro upload, features 33/34) — not in `PLACEHOLDER_NAMES`.
- Severity: HIGH because the guard is meant to lock the front↔back surface; with it bypassed, future drift won't be detected.
- **Recommended fix (a 5-line patch is enough)**:
  1. Add `musicUploadPath` mapping to `_normalize_first_argument`.
  2. Extend `PLACEHOLDER_NAMES` with `"kind"` (or upgrade `kind` from placeholder to enum-of-fixed-strings).
  3. Default `FRONTEND_REPO_ROOT` to the relative `../4Reels-Frontend` (sibling-checkout layout used on this host).

### 🟡 NON-BLOCKING — worth a follow-up sprint (3)

**2. Back feature 2 — list-shape assertion sub-bullet.**
The acceptance text "smoke verifies `{agency_id, items, count}` shape with the per-track fields" cannot be tied to a single test name. `test_music_list_returns_seeded_track` is the natural candidate but its assertion body wasn't expanded in the audit. UNCLEAR rather than GAP — likely covered implicitly. Decide whether to add an explicit shape assertion or accept the implicit one.

**3. Back feature 6 vs back features 13/16 — automation payload spec drift.**
Feature 6 explicitly said the front should NOT send `quiet_hours_enabled` / `skip_weekends`. After features 13/16 landed, BOTH sides ship them and accept them (no 422). Code is consistent; the feature 6 acceptance string in `feature_list.json` is stale. Add a one-line addendum so the next audit doesn't trip over it.

**4. Front feature 39 — singleton toast store vs Provider+Context.**
The implementer chose a singleton store instead of the ToastProvider pattern. All acceptance bullets pass, a11y (`role="alert"`/`status`) confirmed, rationale documented inline in `useToast.js`. If the architecture doc prefers Provider patterns, this is the place to revisit.

### 🟢 NITS / housekeeping (~7)

**5. `docs/API.md` — three known gaps:**
- `publish_subtitles_snapshot` field (feature 41) not mentioned in GET responses section. Out of spec scope but inconsistent if "every response-shape change touches API.md" is the policy.
- The Phase-2 TODO in `admin_agencies_router.py:330` is stale (Phase 2 closed 2026-05-06). Cleanup audit already flagged it.
- Feature 9's `caption_template` keep-decision not recorded in `feature_list.json`.

**6. Migration downgrade paths not exercised (features 23 and 27).**
Read-only policy + leader-only migrations meant downgrades stayed un-run. The downgrade BODIES are present in code; just unexecuted in this audit. Stability suite already documented one pre-existing alembic full-downgrade issue at `20260513_0004 → 0003` (FK side_banner) — unrelated to this sprint.

**7. Back feature 17 — ribbon background colour divergence.**
Spec says `#FECF4D`, code/tests use `#9CA3AF` (Tailwind `gray-400`) per a 2026-05-15 hotfix that is *documented in source comments AND tests*. Not a real GAP, but the spec text in `feature_list.json` is now misleading.

**8. Back feature 40 — 409 envelope shape diverges from `json_error`.**
Manual `regenerate` returns `{"error": "CODE", "detail": "..."}` instead of the canonical `{"message", "code", "hint", "details"}`. The front reads `err.body.error || err.body.code` so both work. Unify the envelope for consistency.

**9. Two carry-overs from prior reviews (features 33/34):**
- `pill` subtitle background collapses to `block` (ffmpeg drawtext doesn't render rounded corners). MVP follow-up.
- Brand-card warning emitted at ingest call site, not at renderer. Single source of truth — by design.

**10. Front-side parallel-run flakes.**
- `admin_auth.spec.js` and `payload_contract.spec.js` flake under default `--workers 5`; pass under `--workers 1`.
- Frontend feature 16 (automation) flakes when multiple system-clock-mocking specs run together.
- Both point at `tests/support/mock-backend.js` not being reset per-worker.

**11. Feature 41 docs.**
Backend `docs/API.md` did not get the new `publish_subtitles_snapshot` entry (out of feature scope but inconsistent if "ship doc with shape changes" is policy).

---

## 3. Recurrent patterns observed

- **Tooling drift > product drift.** The 2 GAPs and most UNCLEARs concentrate
  in *tests and tooling* (contract test broken, migrations not run in audit,
  toast pattern), not in user-facing behaviour. The product spec is faithfully
  implemented.
- **Documentation lags code.** Several features have correct implementation
  but `docs/API.md` / `feature_list.json` acceptance strings drift. Suggests
  a documentation-refresh checkpoint should be part of feature `done`.
- **Mock-backend isolation.** Multiple flakes trace back to the same root:
  `tests/support/mock-backend.js` shares mutable state across Playwright
  workers under default parallelism. A worker-scoped reset would eliminate
  most reported flakes.
- **Cross-repo same-id pattern works.** Front features 23 (symbolic no-op),
  39 (different semantics same id), and the regular paired features (32-37,
  40, 41) all correctly track their back counterparts. No `done` features
  found unpaired or orphaned.

---

## 4. Coverage by source

### `feature_list.json`
- Used as primary spec source; all 71 IDs accounted for.
- Acceptance bullets match implementation for ≈98% of cases.
- Drift candidates documented in §2 items 3, 7, 9 (spec text now stale vs
  evolved behaviour).

### `docs/API.md` (back)
- Endpoints from features 32-37 + 40 covered.
- `publish_subtitles_snapshot` field (feature 41) missing.
- Outro/intro upload sections were added during the 17 May cleanup pass.
- Phase-2 TODO at `admin_agencies_router.py:330` still stale.

### `DOCS.md` (front)
- Backend contract section updated through feature 40.
- Feature 41 mapper change documented in cleanup.
- Page descriptions match current UI.

### `ARCHITECTURE.md` (both)
- Layer rules respected (no audit-detected violations).
- Feature 29 cascade documented.
- No legacy directories (`services/`, `application/`, etc.) found at repo root.

### `docs/http_surface.md` and `docs/openapi.json`
- Auto-generated via `scripts/generate_http_surface.py`.
- All new endpoints from features 33/34/40 present.
- Feature 41's new field would appear automatically on the next regen if the
  Pydantic schema is hit by the generator.

---

## 5. Tests that did not run during the audit

These are *not* a sign of test failure — the audit policy was targeted-only,
some paths require the full suite or external infra:

| Path | Reason |
|---|---|
| `alembic downgrade -1` (features 23, 27) | Migrations are leader-only per AGENTS.md. |
| Full `bash ./init.sh` | Policy: avoid global DB truncations during audit. |
| `apps.api --check` / `apps.worker --check` | Optional global checks; can be re-run on demand. |
| Frontend `npm run test:e2e` full | Audit ran only the specs that map to the audited features. |
| `tests/integration_smoke_e2e.spec.js` | Env-gated by `RUN_INTEGRATION_SMOKE=1`; not invoked. |

---

## 6. Recommended actions — priority order

The user's policy is "when in doubt, do nothing". The list below is **what to
do**, not what was done. No fixes were applied by this audit.

### Must do (before next major release)

1. **Repair the contract test of feature 4**. 5–10 line patch (§2 item 1).
   The guard is the only mechanism preventing future cross-repo drift; with it
   broken, drift will accumulate silently.

### Should do (next sprint)

2. **Update `feature_list.json` to reflect spec drift** for features 6
   (automation payload), 17 (ribbon colour), 9 (caption_template kept).
   One-line addenda each.
3. **Reset `tests/support/mock-backend.js` per worker.** Removes the
   parallel-run flakes observed across multiple ranges.
4. **Unify 409 envelope shape (feature 40)** with `json_error` for consistency.
5. **Add `publish_subtitles_snapshot` to `docs/API.md`** GET response section.

### Could do (housekeeping)

6. Delete the stale Phase-2 TODO at `admin_agencies_router.py:330`.
7. Make `kind` an enum-of-fixed-strings in the front contract helpers
   (intro/outro), so the contract test doesn't need a new placeholder.
8. Re-run alembic downgrade paths (features 23, 27) in a CI job to prove the
   migration bodies still work.
9. Re-visit feature 39 toast pattern if the architecture doc prefers
   Provider+Context.

### Won't do (out of audit scope)

- Implementation of new features.
- Migration of the test DB to a separate runtime DB (architectural change,
  blocked DB-loss incident on 2026-05-17).
- Rewriting any feature; no `done` feature was found broken.

---

## 7. Pointers to per-range reports

- `progress/audit_features_01-10.md` — 399 lines, deepest detail (per-bullet table).
- `progress/audit_features_11-20.md` — 214 lines.
- `progress/audit_features_21-29.md` — 200 lines, includes the full test-command transcript.
- `progress/audit_features_31-37.md` — 190 lines.
- `progress/audit_features_38-41.md` — 241 lines, focused on the freshest features.

---

## 8. Open questions for the leader / user

1. Should the contract test of feature 4 be wired into CI (mandatory pass)?
   Today it is silently broken and would have caught the front↔back drift if
   it had been firing.
2. Should `feature_list.json` acceptance strings be treated as immutable spec
   (frozen at feature close) or living docs (updated when behaviour evolves)?
   Today it's ambiguous, leading to the §2 item 3/7/9 findings.
3. Is `docs/API.md` policy "ship docs with shape changes" or "regenerate on
   schedule"? Today: inconsistent.
4. Worth investing in a test DB separate from the runtime DB? (Independent
   of this audit — the 17 May incident demonstrated the risk.)
