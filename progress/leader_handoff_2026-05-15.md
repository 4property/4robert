# Leader handoff — 2026-05-15 (Claude, rol leader)

> Este archivo documenta el estado en el momento de pausar la sesión por
> presupuesto de tokens. Cualquier leader (Claude o humano) que retome:
> lee este archivo + `progress/current.md`, decide qué falta, sigue.

## Resumen ejecutivo del sprint

Sprint de las features **32–37** orquestado por el leader en paralelo
back ↔ front. Estrategia aprobada por el usuario en el primer turno:
"Back+Front de misma feature en paralelo, features secuenciales"
(`AskUserQuestion` registrado).

| Feature | Back | Front | Estado |
|--------:|:----:|:-----:|:------|
| 32 — reels list pagination + filters | ✅ done | ✅ done | Cerrada en `feature_list.json`, reports en `progress/{impl,review}_32.md` |
| 33 — outro upload + render | ✅ done | ✅ done | Cerrada; tabla `agency_intro_outro_assets` creada |
| 34 — intro upload + render | ✅ done | ✅ done | Cerrada; reusa tabla con `kind='intro'`; refactor genérico `concat_segment` |
| 35 — per-reel photos_override | ✅ done | ✅ done | Cerrada; migración `20260515_0003` |
| 36 — per-reel subtitles_override | ✅ done | ✅ done | Cerrada; migración `20260515_0004`; cerró el gap del `ReelORM.subtitles_override` |
| 37 — per-reel slides_override | ⏳ in_progress | ⏳ in_progress | **Implementers corriendo en background al pausar la sesión** |

`alembic current = 20260515_0004 (head)` en el momento de pausar.
Feature 37 añadirá `20260515_0005_reels_manifest_override.py`.

## Estado exacto de feature 37 (lo único in_progress)

Dos `Agent` subagentes (subagent_type=general-purpose con rol implementer
en el prompt) se lanzaron en `run_in_background=true` justo antes de la
pausa. Sus IDs internos (no accesibles fuera de la sesión original):

- Backend implementer: working dir `/opt/projects/4Reels-Backend`,
  reporte esperado en `progress/impl_37.md`.
- Frontend implementer: working dir `/opt/projects/4Reels-Frontend`,
  reporte esperado en `progress/impl_37.md`.

### Cómo retomar feature 37

1. **Comprobar si los implementers acabaron** mientras la sesión estaba
   pausada:
   - `ls -la progress/impl_37.md` en ambos repos. Si existe + tiene
     contenido razonable + closing line en `progress/current.md`, el
     implementer terminó.
   - `cat progress/impl_37.md` para leer su reporte.
   - `python3 -c "import json; data=json.load(open('feature_list.json')); print(next(f for f in (data.get('features',data) if isinstance(data,dict) else data) if f.get('id')==37)['status'])"` → debería decir `in_progress`.
2. **Si los implementers NO acabaron** (no hay `impl_37.md` o quedó a
   medias):
   - Mirar `progress/current.md` para ver si dejaron rastro parcial.
   - Decidir: o esperar (si el reporte está casi listo), o relanzar
     desde cero (los prompts completos están más abajo en este archivo).
3. **Si los implementers acabaron**:
   - Lanzar los **dos reviewers en paralelo** (prompts detallados al
     final de este archivo).
   - Cuando ambos reviewers den verdict APPROVED, ellos mismos marcan
     `done` en `feature_list.json` y cierran su closing line en
     `progress/current.md`.
4. **Cuando feature 37 esté `done` en ambos repos**:
   - Pasar a la **batería de estabilidad** (sección "Post-37" abajo).

## Decisiones del sprint que el próximo leader debe recordar

Tomadas en el turno inicial vía `AskUserQuestion`:

1. **Estrategia paralelización**: back+front de la MISMA feature en
   paralelo; features secuenciales por id. Respeta la regla del repo
   "una feature a la vez por repo".
2. **Search scope (feature 32)**: `q` busca por `reels.title`,
   `reels.slug` Y `properties.list_reference` (tres columnas, JOIN
   real). Implementado.
3. **brand_card (feature 33)**: NO incluido en este sprint. El enum
   `outro_source`/`intro_source` reserva el valor `'brand_card'` pero
   el renderer lo trata como `'none'` + warning log. Documentado como
   feature futura (cualquier feature 38+ podría implementarlo).
4. **HOTFIX classic_template_preview migration**: confirmado YA aplicado
   (alembic head era `20260515_0001` cuando empezó el sprint).

## Patrón establecido durante el sprint (replicar en futuras features
similares)

### Backend — patrón de 6 puntos para añadir un campo de override a `reels`

El feature-35 reviewer lo formalizó tras detectar que la feature 35
había skipped el punto 2 (luego cerrado por feature 36). Cualquier
override JSONB nuevo en `reels` debe tocar:

1. **Migración alembic** chained: `down_revision` = head actual,
   `upgrade()` añade `Column(name, JSONB, nullable=True)`,
   `downgrade()` drop.
2. **ORM** `shared/db/orm.py`: añadir `ReelORM.<campo>: Optional[list]`
   mapeado a JSONB.
3. **Domain `ReelState`**: añadir el field en el dataclass.
4. **Repository SQL**: extender `INSERT … ON CONFLICT DO UPDATE` para
   incluir el campo y NO clobberar el valor existente en re-ingest.
   Bug latente: si el SQL UPDATE no propaga el override, un re-ingest
   posterior al PATCH lo wipea.
5. **`_build_ingested_reel_state`**: propagar el campo desde el
   `existing_state` peek al `ReelState` rebuilt.
6. **`_peeked_existing_state.<campo>`** → forward al `PropertyContext`
   / renderer para que el plan/manifest lo lea.

Sin alguno de los 6, el bug es "el override se aplica una vez y luego
desaparece al siguiente re-ingest". Test obligatorio: "survives
re-ingest" (PATCH → re-trigger ingest real → assertion que el campo
sigue presente).

### Backend — convención de error codes para overrides

- `PHOTOS_OVERRIDE_LOCKED` (feature 35)
- `SUBTITLES_OVERRIDE_LOCKED` (feature 36)
- `SLIDES_OVERRIDE_LOCKED` (feature 37 — pending)

Trigger: `workflow_state == "approved"` OR `publish_status ==
"published"`. Status 409. Body: `{"error": "<CODE>", "detail":
"<copy>"}`.

### Frontend — primitivos compartidos creados durante el sprint

- `src/features/reels/editor/lockedReelHelpers.jsx` (introducido en
  feature 36 como refactor cuando apareció el 2º call-site): exporta
  `LockedReelBanner`, `RerenderBadge`, `isReelClientLocked`,
  `LOCKED_COPY`, `LOCKED_WORKFLOW_STATES`. Consumido por
  `PhotosPanel`, `SubtitlesPanel`. **Feature 37 debe consumirlo también
  para `SlidesPanel`**.
- `src/features/defaults/UploadVideoCard.jsx` (introducido en feature 34
  como refactor): componente shared parametrizado por `kind:
  'intro'|'outro'` + `copy`. `OutroCard` y `IntroCard` son wrappers de
  ~10 líneas.
- **Pendiente para feature 37 del front** (decisión del reviewer
  feature 36): extraer `useReelDebouncedOverride` cuando aparezca el
  3er call-site. Slides ES el 3er call-site, así que el prompt del
  implementer feature 37 front pide la extracción.

## Deviations heredadas pendientes (feature 37 debe cerrarlas)

El reviewer del back-35 detectó tres puntos que el implementer
saltó; el reviewer del back-36 confirmó que se difieren a feature 37
porque ésta ya toca `ReelORM` y `docs/`:

- **A**. Añadir `ReelORM.photos_override` en `shared/db/orm.py`
  (feature 35 hizo el SQL crudo pero no el ORM map).
- **B**. Añadir secciones en `docs/API.md` para los tres PATCH:
  `/photos` (35), `/subtitles` (36), `/slides` (37).
- **C**. Regenerar `docs/http_surface.md` y `docs/openapi.json` si son
  auto-generados; o actualizarlos a mano si son hand-written. Grep
  cómo se actualizaron antes y replicar.

Estas tareas YA están en el prompt del implementer back-37 (sección
"Inherited follow-ups").

## Prompts completos de los reviewers de feature 37

> Si los implementers acabaron y el próximo leader necesita lanzar los
> reviewers, copia este prompt íntegro como `prompt` del `Agent` con
> `subagent_type: "general-purpose"`.

### Reviewer BACKEND feature 37 — prompt completo

```text
You are the **reviewer subagent** for the 4Reels backend.

## Bootstrapping
1. `cd /opt/projects/4Reels-Backend` and stay there.
2. Read `.claude/agents/reviewer.md` — your contract.
3. Read `AGENTS.md`, `ARCHITECTURE.md`, `docs/conventions.md`,
   `docs/verification.md`, `CHECKPOINTS.md`.

## Your task

Review feature **id=37** (`per_reel_slides_override`). Report at
`progress/impl_37.md`. Spec in `feature_list.json` id=37.

### Leader's decisions (verify each, file:line)

- HTTP contract:
  - PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/slides`.
  - Body: `{slides: [{slide_id, position, duration_seconds, kind, ...kind-fields}, ...]}` OR `{slides: null}` OR `{slides: []}`.
  - 200 returns `{manifest_override: [...], render_status: "pending"}`.
- 422 validation: invalid kind, missing kind-required field, position gap, duplicate, sum durations > 1.5x target, slide_id duplicate, extra field, wrong type.
- 409 `SLIDES_OVERRIDE_LOCKED` when workflow_state='approved' OR publish_status='published'.
- Persistence: NULL when input null/[].
- Renderer: if manifest_override != NULL → render plan from override; else fallback auto-generated.
- Migration `20260515_0005_reels_manifest_override.py`, down_revision="20260515_0004", up/down/up clean.

### 6-point pattern (CRITICAL)

Verify all 6 points for `manifest_override`:
1. Migration at `alembic/versions/20260515_0005_*`.
2. `ReelORM.manifest_override` in `shared/db/orm.py`.
3. `ReelState.manifest_override`.
4. Repository SQL upsert includes manifest_override + doesn't clobber on re-ingest.
5. `_build_ingested_reel_state` propagates manifest_override.
6. `_peeked_existing_state.manifest_override` forwards to PropertyContext.

### Inherited follow-ups (verify all 3 closed)

A. `ReelORM.photos_override` added in `shared/db/orm.py` (feature 35 had skipped it).
B. `docs/API.md` has 3 new sections: /photos, /subtitles, /slides.
C. `docs/http_surface.md` and `docs/openapi.json` updated (regen or hand).

If any of A/B/C is missing AND the implementer didn't document an obstacle, that's a blocking issue.

### Hard rules
- No session.commit() in repositories.
- No legacy imports.
- Inter-module rule respected.
- Composition only in `apps/api/app_factory.py` and `apps/worker/runtime.py`.
- No test deleted/weakened.

### What to do
1. Read `progress/impl_37.md`.
2. Read each touched file (the 6-point checklist + the 3 follow-ups).
3. Re-run:
   - `bash ./init.sh` exit 0 (baseline 1010 + 3 known-flaky → ~+18 new).
   - `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` clean.
   - `pytest tests/integration/reels/test_reel_slides_override.py tests/integration/rendering/test_render_with_slides_override.py -q -v` green.
   - Regression: `pytest tests/integration/reels/test_reel_photos_override.py tests/integration/reels/test_reel_subtitles_override.py tests/integration/reels/test_reel_music_override.py -q` green.
   - `apps.api --check` + `apps.worker --check` exit 0.

### Outcome → `progress/review_37.md`
1. Verdict APPROVED / CHANGES_REQUESTED.
2. 6-point audit (file:line).
3. Inherited follow-ups A/B/C closure status (file:line).
4. Per-decision audit table.
5. Acceptance checklist marked.
6. Verification re-run.
7. Issues + open items (sample curl for :8001).

If APPROVED → mark feature 37 `done` in `feature_list.json` + closing line in `progress/current.md`.
If CHANGES_REQUESTED → leave in_progress + list required changes.

Hard NOs: don't write production code, don't restart services, don't `--no-verify`.

Return 5-line summary.
```

### Reviewer FRONTEND feature 37 — prompt completo

```text
You are the **reviewer subagent** for the 4Reels frontend.

## Bootstrapping
1. `cd /opt/projects/4Reels-Frontend` and stay there.
2. Read `.claude/agents/reviewer.md` — your contract.
3. Read `AGENTS.md`, `ARCHITECTURE.md`, `DOCS.md`, `docs/conventions.md`, `docs/verification.md`, `CHECKPOINTS.md`.

## Your task

Review feature **id=37** (`per_reel_slides_override_ui`). Report at `progress/impl_37.md`.

### Leader's decisions (verify each)

- API: `reelsApi.patchReelSlides(agencyId, siteId, sourcePropertyId, slides)`.
- Hook: `useReelSlidesOverride` (or via shared `useReelDebouncedOverride`).
- Refactor 3rd call-site: `useReelDebouncedOverride` extracted; PhotosPanel + SubtitlesPanel rewired to consume it.
- Debounce 500ms (slides).
- Client validation: yellow warning if sum durations > target, do NOT block; PATCH still fires (back decides — back caps at 1.5x).
- Optimistic + rollback.
- `Re-rendering...` badge + 409 banner: shared lockedReelHelpers.
- Mock backend: PATCH /slides route with per-kind validation, 409 stub, render_status flip ~200ms.
- DOCS.md § Backend contract has slides block.

### Hard rules
- No TypeScript / React Query / MSW / styled-components / Tailwind / CSS-in-JS.
- No new npm deps. `git diff package.json package-lock.json` empty (modulo license).
- hook → api → lib/api/client.js.
- No VITE_* secrets.

### What to do
1. Read `progress/impl_37.md`.
2. `git diff package.json package-lock.json`.
3. Read each touched file.
4. Re-run:
   - `./init.sh` exit 0.
   - `npm run test:smoke` green.
   - `npm run test:e2e tests/per_reel_slides_override.spec.js tests/per_reel_subtitles_override.spec.js tests/per_reel_photos_override.spec.js` — all green.
   - Full `npm run test:e2e` green or only documented pre-existing flake (social_templates).

### Outcome → `progress/review_37.md`
Same structure as feature 36 review.
- Evaluate the `useReelDebouncedOverride` extraction (clean / partial / over-extracted).
- Confirm features 35/36 tests still pass.

If APPROVED → mark `done` + closing line.
If CHANGES_REQUESTED → list changes.

Return 5-line summary.
```

## Post-37: batería de estabilidad (próximo paso después de 37 done)

El usuario pidió, una vez cerrada feature 37: **"lances todo tipo de
pruebas para asegurarte de que todo está bien en general en la app y
que es estable"**.

Plan:

### Backend (lanzar como agent general-purpose en background)

```text
You are running a STABILITY SUITE on /opt/projects/4Reels-Backend.

1. cd /opt/projects/4Reels-Backend
2. bash ./init.sh — capture exit code + tail of pytest summary. Expected
   baseline: 1010 + ~18 (feature 37) ≈ 1028 passed + 3 documented
   flakes in test_http_surface_contract.py and test_http_transport.py.
3. Time the full pytest: `time .venv/bin/python -m pytest -q` and
   report duration.
4. Alembic full chain reversibility:
     .venv/bin/python -m alembic upgrade head
     .venv/bin/python -m alembic downgrade base
     .venv/bin/python -m alembic upgrade head
   Should be clean. If anything errors, capture stderr.
5. `apps.api --check` + `apps.worker --check` exit codes.
6. Hard rule scan (grep -rn):
   - Legacy imports: `^\s*(from|import)\s+(services|application|repositories|core|domain)\.` in apps/, modules/, shared/, tests/ → must be zero.
   - `session.commit(` inside `modules/*/infrastructure/*_repository.py` → must be zero.
   - Cross-module crossings: from `modules/<bc>/<layer>` to `modules/<other>/application` or `modules/<other>/infrastructure` → flag for review (some are accepted patterns from features 21/25/35).
7. Write report to `progress/stability_back_2026-05-15.md` with sections:
   - init.sh result.
   - pytest timing.
   - alembic chain reversibility.
   - apps checks.
   - Hard rule findings.
   - Recommendation (stable / regression detected / cleanup suggested).
```

### Frontend (paralelo al backend)

```text
You are running a STABILITY SUITE on /opt/projects/4Reels-Frontend.

1. cd /opt/projects/4Reels-Frontend
2. ./init.sh — capture exit code (lint + build).
3. `npm run test:smoke` — green expected (46 passed / 2 skipped baseline).
4. `npm run test:e2e` full — capture passed/skipped/flake counts.
   Expected: ~300+ passed / 2 skipped / 0-2 flakes in
   social_templates.spec.js (documented pre-existing).
5. Bundle analysis: tail of vite build output (CSS + JS sizes,
   warnings, chunks > 500kB).
6. Quick git diff stats: `git diff --stat` to spot any uncommitted
   changes from this sprint.
7. Write report to `progress/stability_front_2026-05-15.md` with:
   - init.sh result.
   - test:smoke result.
   - test:e2e result (timing + flake list).
   - Bundle analysis (sizes vs baseline).
   - Uncommitted-changes inventory.
   - Recommendation.
```

### Cross-repo HTTP contract verification (manual o agent)

Para los 6 endpoints nuevos del sprint (32-37 — específicamente las
shapes nuevas/PATCH), abrir `DOCS.md` § Backend contract del front y
contrastar contra `docs/API.md` del back (o el mock-backend.js vs el
router real). Mismas keys, mismos error codes, mismas validaciones.

## Lo que NO se hizo durante el sprint (intencional)

- **Restart de `reels-test.service` en :8001**: requiere `sudo`,
  el rol leader no lo hace sin permiso del usuario en el mismo turno.
  El back de las 6 features está corriendo "in repo" pero el proceso
  vivo en :8001 sigue siendo el código viejo. Cuando el usuario quiera
  smoke real contra :8001, hay que reiniciar (sus AGENTS.md §7
  documenta los comandos). Eso es ops, fuera de scope leader.
- **HOTFIX cleanup**: el `IntroOutroCard.jsx` legacy quedó huérfano en
  el front (flaggeado por reviewer feature 34 como nit non-blocking).
  No se borró para mantener la PR pequeña.
- **Smoke manual end-to-end** contra :8001: cada review lo deja como
  open item con curl commands listos.

## Contacto cross-repo

- Repo hermano (back): `/opt/projects/4Reels-Backend`
- Repo hermano (front): `/opt/projects/4Reels-Frontend`
- Producción legacy en :8000: `/opt/reels` (no tocar — código fuente
  distinto, `4property/4robert` branch `ghl`).
