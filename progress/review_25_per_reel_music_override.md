# Reviewer report — feature 25 (BACK) per_reel_music_override

- **Fecha:** 2026-05-14
- **Agente:** reviewer (Claude Opus 4.7, 1M)
- **Veredicto:** **APROBADO** — listo para marcar `done` cuando el leader lo decida (esperando además el front).
- **Plan de origen:** `progress/current.md` §"Trabajo en paralelo — feature 25 BACK (leader Claude, música)"
- **Informe del implementer:** `progress/impl_25_per_reel_music_override.md`

## 1. Resumen ejecutivo

Verificado el ciclo completo del override per-reel: migración alembic con FK
`ON DELETE SET NULL`, PATCH endpoint con validación cross-agency, persistencia
en `reels.music_id`, re-encolado del job de render con `override_music_track_id`
en `publish_context`, swap de la pool en el worker, y fallback defensivo
cuando la pista referenciada desaparece entre el PATCH y el render. Los 9
acceptance criteria del `feature_list.json` (id 25) se cumplen. `bash ./init.sh`
cierra exit 0 con la baseline preexistente de 3 fallos no relacionados
(`test_http_surface_contract` y `test_http_transport`×2) — coincide 1:1 con
lo que vienen reportando los hotfixes Codex de esta sesión. Sin regresiones,
sin violaciones de capa, sin bucles en el flujo approve.

## 2. Acceptance criteria — punto por punto

| # | Criterio | Estado | Evidencia |
|---|----------|--------|-----------|
| 1 | `alembic upgrade head` añade `reels.music_id`; downgrade reversible | OK | Migración `alembic/versions/20260514_0006_reels_music_id_override.py`. Ciclo `upgrade head → downgrade -1 → upgrade head` verde contra Postgres local. `alembic heads` = `20260514_0006 (head)`. |
| 2 | PATCH happy → 200 `{status:'saved', reel_id, music_id}`, re-encola job | OK | `tests/integration/reels/test_admin_reels_music_override.py::test_patch_music_persists_override_and_enqueues_job` (PASS). Cuerpo de respuesta también incluye `publish_enqueued`, `event_id`, `job_id`. |
| 3 | PATCH con `music_id=null` → 200, borra override | OK | `test_patch_music_with_null_clears_override` (PASS). `Payload.music_id: str \| None = None`, `extra='forbid'`. |
| 4 | PATCH cross-agency → 403 o 404 (implementer eligió 404) | OK | `test_patch_music_returns_404_for_cross_agency_music_id` (PASS). Code `ADMIN_MUSIC_TRACK_NOT_FOUND`. Mismo código que cuando el `music_id` no existe — colapso intencional para no leak de existencia (paridad con feature 22). |
| 5 | PATCH a reel aprobado/publicado → 409 `REEL_NOT_EDITABLE` | OK | `test_patch_music_returns_409_when_reel_already_published` (PASS). El use case reutiliza `_EDITABLE_PUBLISH_STATUSES` y `ReelNotEditableError` de feature 21, así que la lista de estados editable es **idéntica** entre PATCH descriptions y PATCH music. |
| 6 | Render con override usa exactamente esa pista | OK | Unit `test_apply_music_track_override_swaps_pool_for_single_track` (PASS): el helper sustituye `background_audio_candidates` por una tupla de 1 elemento usando `resolve_agency_music_local_paths(workspace_dir=..., music_tracks=(track,))`. El renderer no necesita cambios — recibe la tupla filtrada igual que antes. |
| 7 | Tests cubren happy, cross-agency, 409, null override | OK | 9 integration en `test_admin_reels_music_override.py` + 6 unit en `test_ingest_applies_music_override.py` = 15 PASS focalizados. Cobertura: happy, null clear, prereqs missing, unknown id, cross-agency, unknown reel, unknown agency, 409 published, 422 extra keys, swap pool, fallback en track borrada, fallback cross-agency, noop sin override, noop sin publish_context, noop sin music repo. |
| 8 | `docs/API.md` y `docs/http_surface.md` actualizados | OK | `docs/http_surface.md:47` añade la fila PATCH. `docs/API.md:527` la añade en la tabla de endpoints + sección `PATCH .../music (feature 25)` con shape de request/response, matriz de errores (200/404/404/409/422) y nota sobre `ADMIN_MUSIC_TRACK_NOT_FOUND`. |
| 9 | `pytest -q` verde + `apps.api --check` + `apps.worker --check` exit 0 | OK con baseline | `pytest -q` → 778 passed, 3 failed (baseline). `--check` ambos verdes. |

## 3. Decisiones del implementer — verificadas punto por punto

### 3.1 Cross-agency colapsado a 404 `ADMIN_MUSIC_TRACK_NOT_FOUND`

`modules/reels/application/use_cases/update_reel_music_override.py:165-178`:

1. Carga el track via `uow.configuration.music.get(music_id=...)`. Si devuelve `None` → `_music_track_not_found_error(agency_id, music_id)` (404, code `ADMIN_MUSIC_TRACK_NOT_FOUND`).
2. Si el `track.agency_id` no coincide con `normalized_agency_id` → MISMO helper, MISMO code 404. Comentario inline explícito: *"Cross-agency request: 404 (not 403) so we never leak the existence of a track owned by another tenant."*

El helper `_music_track_not_found_error` (líneas 81-104) construye el `ResourceNotFoundError` con `context={agency_id, music_id}` y un `hint` que apunta al endpoint `GET /v1/admin/agencies/{agency_id}/music` para que el frontend pueda recomendar la acción correcta sin exponer si el id existe en otra tenant. Convención consistente con feature 22 (`agency_music_upload`) y con las features 9/10 (cross-agency = 404).

**Verificación cruzada:** los dos tests `test_patch_music_returns_404_for_unknown_music_id` (con id random `uuid4()`) y `test_patch_music_returns_404_for_cross_agency_music_id` (con id real de otra agencia) ambos asertan `response.json()["code"] == "ADMIN_MUSIC_TRACK_NOT_FOUND"`. El cliente externo no distingue entre los dos casos por respuesta.

### 3.2 Re-enqueue mirror de `RegenerateReelUseCase` con `override_music_track_id`

`update_reel_music_override._maybe_enqueue_publish_job` (líneas 230-407) duplica deliberadamente el patrón de `regenerate_reel.py:150-407`:

- Mismas dependencias (`catalog.properties.get_raw_payload`, `publishing.connections.get_with_secrets`, `configuration.defaults.get`, `automation.get`, `social_templates.list_for_agency`, `tenancy.agencies.get_by_id`).
- Mismo `compute_next_publish_slot` con el `agency_timezone`.
- Mismo `supersede_queued_jobs` antes de encolar para evitar duplicados.
- Mismos campos del `JobEnqueueRequest`.
- Mismo retorno `publish_enqueued=False` cuando faltan prereqs (raw payload o GHL connection) con `reason="PUBLISH_PREREQUISITES_MISSING"` y `hint` documentado.

La única diferencia material es `publish_context["override_music_track_id"] = override_music_track_id` (líneas 339-344). El comentario inline aclara que la clave se persiste **siempre** (None incluido), para que el worker pueda diferenciar "PATCH con null" (clear) de "job pre-feature-25" (no carga la clave) — aunque `from_dict` los trata igual, esto deja traza explícita en el `publish_context_json`.

Patrón validado: no hay re-implementación del flujo de jobs, no se introduce un kind nuevo (`reel_publish` reutilizado), y la idempotencia se mantiene via `supersede_queued_jobs`.

**Caveat (no bloqueante)**: duplicar todo `_maybe_enqueue_publish_job` en lugar de extraer un helper compartido con `regenerate_reel` introduce ~150 líneas duplicadas. El implementer lo escogió porque las firmas divergen en sutilezas (regenerate empuja `pending_publish` antes de encolar; update_music no toca el estado) y para mantener el blast radius acotado. No bloquea: si el contrato del job cambia, ambos archivos necesitarán cambio coordinado — anótese para futuras refactorizaciones.

### 3.3 `regenerate_reel.py` propaga `existing_state.music_id` al approve

`modules/reels/application/use_cases/regenerate_reel.py:277-283`:

```python
"override_music_track_id": (
    getattr(existing_state, "music_id", None) or None
),
```

`getattr(..., None)` es defensivo por si un test stub no lleva el campo, pero `ReelState.music_id` ya tiene `field(default=None)`, así que el `getattr` siempre resuelve. El `or None` colapsa el caso "string vacío persistido" (legacy) al canónico `None`.

**Análisis de bucles / efectos secundarios:**

1. El use case approve **NO** llama a `update_reel_music_override`, sólo lee `existing_state.music_id` y lo forwardea en el contexto.
2. `update_reel_music_override` **NO** llama a `regenerate_reel` — tiene su propio `_maybe_enqueue_publish_job`.
3. El worker (`ingest_property_into_reel._apply_music_track_override`) **lee** el override del `publish_context` y termina ahí — no crea un nuevo job.
4. El `supersede_queued_jobs` en ambos use cases es idempotente: marca cualquier job previo como `superseded` y emite uno nuevo. Llamar al approve sobre un reel que ya tenía override sólo produce un job nuevo (no recursivo).

Cadena: **PATCH music → save state → enqueue job-A → worker drena job-A → render con override**. Luego **POST approve → reusa state.music_id → enqueue job-B → worker drena job-B → render con override (preservado)**. Sin bucles. Sin double-enqueue (cada use case tiene su propio `supersede_queued_jobs`).

### 3.4 Worker fallback si track borrada en race

`modules/reels/application/use_cases/ingest_property_into_reel.py:603-665`:

El helper `_apply_music_track_override` está bien blindado:

1. **Pre-feature-25 / publish_context ausente** (línea 630-631): `if publish_context is None: return background_audio_candidates`. Backward-compat.
2. **Override vacío / clave no en el dict** (líneas 632-638): lee `publish_context.override_music_track_id`, normaliza, si está vacío → pass-through.
3. **UoW sin configuration** (líneas 639-641): defensivo para unit-tests que omiten el namespace.
4. **UoW sin music repo** (líneas 642-644): idem.
5. **Track no existe O cross-agency** (líneas 645-654): este es el caso de la race condition. El track se borró entre el PATCH y el render. `ON DELETE SET NULL` ya puso `reels.music_id` a NULL en disco, pero el job en vuelo todavía carga el id antiguo en `publish_context_json`. Resolución:

```python
track = music_repo.get(music_id=override_id)
normalized_agency_id = str(agency_id or "").strip()
if track is None or str(track.agency_id).strip() != normalized_agency_id:
    logger.warning(
        "Music override %s no longer resolves for agency %s; "
        "falling back to the resolved pool.",
        override_id,
        normalized_agency_id,
    )
    return background_audio_candidates
```

- ✅ `logger.warning` PRESENTE (línea 648).
- ✅ Fallback es a `background_audio_candidates`, que es **la pool default ya resuelta por `resolve_agency_background_audio_candidates`** en líneas 174-181 — es decir, las pistas de la propia agencia (con respeto al flag `fallback_to_full_library` de feature 24). **NO** cae a tracks de otra agencia, **NO** cae a un error que aborta el render.
- ✅ La rama `track.agency_id != agency_id` es el caso paranoico (hipotético: alguien manualmente PATCHeó un job en flight con un id ajeno) — también cae al warning y al pool default. Defensa-en-profundidad sobre la validación que ya hace `update_reel_music_override` al recibir el PATCH.

`tests/unit/reels/test_ingest_applies_music_override.py` cubre estas 3 ramas (fallback-on-missing, fallback-on-cross-agency, noop sin music repo) con asserciones explícitas de que la pool devuelta es la original sin tocar.

### 3.5 `SocialPublishContext` extendido — backward-compat verificada

`modules/reels/domain/types.py:108-115`:

```python
# Feature 25: per-reel music override ...
# Jobs enqueued before feature 25 never carry the field, which
# round-trips to ``None`` and preserves the legacy behaviour.
override_music_track_id: str | None = None
```

`to_dict` (línea 130): emite siempre la clave (consistencia para nuevos jobs).
`from_dict` (líneas 188-196):

```python
raw_override_music_track_id = payload.get("override_music_track_id")
if raw_override_music_track_id is None:
    override_music_track_id: str | None = None
else:
    normalized_override = str(raw_override_music_track_id).strip()
    override_music_track_id = normalized_override or None
```

`payload.get(...)` con default implícito `None`: si el dict no tiene la clave (job viejo persistido pre-feature-25), `raw_override` es `None` y el `from_dict` reconstruye un `SocialPublishContext` con `override_music_track_id=None`. Backward-compat OK. Test `test_apply_music_track_override_noop_without_override` cubre el caso del `publish_context.override_music_track_id=None`.

Greps verificados:
- `grep -rn 'override_music_track_id' modules/reels/domain/` → 8 hits en `types.py`, ningún hit en `reel_state.py`. La domain layer trata el field como parte del contrato del job (`SocialPublishContext`), no como parte del estado persistido del reel (que lleva `music_id`, no `override_music_track_id`). Separación correcta.

### 3.6 Migración `20260514_0006` — FK `ON DELETE SET NULL` y roundtrip

`alembic/versions/20260514_0006_reels_music_id_override.py`:

- `revision = "20260514_0006"`, `down_revision = "20260514_0005"` — cadena ordenada tras el seed migration de feature 23.
- `upgrade()`: `add_column reels.music_id String(36) nullable` + `create_foreign_key("fk_reels_music_id_agency_music_tracks", "reels", "agency_music_tracks", ["music_id"], ["id"], ondelete="SET NULL")`.
- `downgrade()`: `drop_constraint("fk_reels_music_id_agency_music_tracks", ..., type_="foreignkey")` + `drop_column("reels", "music_id")`. Sin data preservation — el override es puramente editorial.

Ciclo ejecutado manualmente en este review:

```
alembic upgrade head        # → verde, head 20260514_0006
alembic downgrade -1        # → verde, head 20260514_0005
alembic upgrade head        # → verde, head 20260514_0006 (idempotente)
```

Documentación del FK en el ORM (`shared/db/orm.py:181-190`) coincide línea a línea con la migración: mismo `String(36)`, mismo `ondelete="SET NULL"`, mismo target `agency_music_tracks.id`. Sin drift.

### 3.7 Tests de feature 23 ajustados a `downgrade "20260514_0004"` — necesario y mínimo

`tests/integration/configuration/test_seed_existing_agencies_music.py` ahora usa
`_run_alembic(workspace_dir, database.url, "downgrade", "20260514_0004")`
en lugar de `downgrade -1` en las 3 funciones de test.

**Justificación auditada:**

- Cuando feature 23 se mergeó, el `head` era `20260514_0005` (la propia seed migration de feature 23). `downgrade -1` desde `_0005` aterriza en `_0004`, que es la revisión inmediatamente anterior al seed.
- Con feature 25, el `head` pasa a `20260514_0006`. `downgrade -1` ahora aterriza en `_0005` — **NO bajaría el seed migration**, así que el data-path del seed no se replay-aría y los tests fallarían (no encontrarían las filas a re-insertar).

**¿Por qué no `downgrade -2` en lugar de la revisión explícita?**

- Funcionalmente equivalente HOY (con head=`_0006`, `-2` aterriza en `_0004`). Pero **frágil**: si en el futuro se añade `_0007`, `_0008`, etc., el `-N` necesitará crecer manualmente cada vez. El target explícito `"20260514_0004"` es invariante respecto a futuras migraciones — el test sólo necesita saber "bájame justo debajo del seed migration", no contar saltos.
- El implementer eligió la opción robusta. Acertado.

Tests ejecutados: `pytest tests/integration/configuration/test_seed_existing_agencies_music.py -v` → 3 passed. Sin regresión.

## 4. Verificación de capa / convención

- `grep -rn 'from modules.configuration' modules/rendering/` → 2 hits, ambos a `modules.configuration.domain` (tipos `RenderTemplate`, `MusicTrack`). **Cero** hits a `.application` o `.infrastructure`. La frontera rendering ↛ configuration sigue intacta, esta feature no la rompió.
- `_apply_music_track_override` consume `uow.configuration.music` (repositorio en namespace configuration), pero lo hace desde `modules/reels/application` — capa application puede cruzar a otras namespaces application/infrastructure, conforme a las convenciones del repo.
- `from modules.rendering.infrastructure.runtime.assets import resolve_agency_music_local_paths` es **import local dentro del método** (línea 658-660), evitando contaminar el módulo con un acoplamiento eager. Mismo patrón que el resto de helpers de música (descrito en docstring).
- `session.commit()` no se llama desde repositorios — el UoW del router maneja la transacción.

## 5. Comandos ejecutados (todos verdes / acordes a baseline)

```bash
cd /opt/projects/4Reels-Backend
bash ./init.sh
# → exit 0, 3 failed (baseline preexistente), 778 passed, 14 warnings

.venv/bin/python -m alembic heads
# → 20260514_0006 (head)

.venv/bin/python -m alembic upgrade head    # verde
.venv/bin/python -m alembic downgrade -1    # verde (vuelve a 20260514_0005)
.venv/bin/python -m alembic upgrade head    # verde (idempotente)

.venv/bin/python -m pytest \
  tests/integration/reels/test_admin_reels_music_override.py \
  tests/unit/reels/test_ingest_applies_music_override.py -v
# → 15 passed in 14.83s

.venv/bin/python -m pytest tests/integration/reels/ tests/unit/reels/ -q
# → 149 passed in 72.04s

.venv/bin/python -m pytest tests/integration/configuration/test_seed_existing_agencies_music.py -v
# → 3 passed in 14.19s

.venv/bin/python -m apps.api --check        # → verde
.venv/bin/python -m apps.worker --check     # → verde
```

Greps clave:
- `grep -rn 'override_music_track_id\|music_id' modules/reels/` → 54 hits, todas alineadas con el contrato (domain `ReelState`, domain `SocialPublishContext`, use case music override, use case ingest, use case regenerate, router admin, payload Pydantic). Sin orfandades.
- `grep -rn 'ADMIN_MUSIC_TRACK_NOT_FOUND\|MUSIC_TRACK_FORBIDDEN' modules/ tests/ docs/` → `MUSIC_TRACK_FORBIDDEN` **0 hits** (no se usa el 403); `ADMIN_MUSIC_TRACK_NOT_FOUND` 9 hits (use case, router, tests integration ×2, docs API.md). Coherente con la decisión 3.1.
- `grep -rn 'from modules.configuration' modules/rendering/` → 2 hits, ambos a `.domain`. Frontera intacta.
- `grep -rn 'override_music_track_id' modules/reels/domain/` → 8 hits en `types.py`, separación domain/state correcta.

## 6. Caveats no bloqueantes

1. **Duplicación de `_maybe_enqueue_publish_job` entre `update_reel_music_override.py` y `regenerate_reel.py`** — ~150 líneas casi idénticas. Riesgo: cualquier cambio futuro al contrato del `reel_publish` job (e.g. nuevo campo en `publish_context`, cambio de `supersede_queued_jobs`) hay que aplicarlo en los 2 archivos. Recomendación post-feature-25: extraer un `_PublishJobEnqueuer` helper compartido, con un kwarg opcional para el override. NO BLOQUEA: el plan original explicitaba "el use case re-encola un job de render con el override" sin pedir refactor.

2. **`update_reel_music_override.execute` no fuerza una transición de `workflow_state` ni `publish_status`** — a diferencia de `regenerate_reel` que empuja `workflow_state='approved'` + `publish_status='pending_publish'`. Coherente con la semántica del PATCH (sólo persiste el override, no aprueba el reel), pero implica que un reel en `workflow_state='needs-approval'` permanece en ese estado tras el PATCH aunque el job esté encolado. El editor tendrá que aprobar manualmente para que se renderice — pero **realmente sí se renderiza con el job encolado**, porque el job es de kind `reel_publish` y el worker no consulta el `workflow_state` para empezar a renderizar. **NO es un bug funcional**, pero sí una sutileza UX que el front debe presentar bien (badge "music updated, pending re-render" mientras el job está en cola).

3. **`update_reel_music_override` valida con `_EDITABLE_PUBLISH_STATUSES` de feature 21 importado directamente** (`from modules.reels.application.use_cases.update_reel_descriptions_override import (ReelNotEditableError, _EDITABLE_PUBLISH_STATUSES,)`). Acoplamiento intencional para garantizar paridad — si feature 21 cambia el set, feature 25 lo hereda automáticamente. Caveat: el nombre con `_` lo marca como privado; un futuro refactor de feature 21 podría romper el import sin avisar. Recomendación: en el futuro, mover ambos a `_admin_support.py` (donde ya viven `ensure_agency_exists`/`reel_not_found_error`). NO BLOQUEA.

## 7. Verificación cruzada contra :8001

No ejecutada (el runtime de :8001 no tiene aún el código de feature 25 hasta que el leader lo despliegue; los tests integration cubren el contrato HTTP). El plan tampoco pedía verificación manual contra :8001 desde el reviewer — sólo lista una verificación manual cuando el front esté integrado.

## 8. Recomendaciones para el leader

1. **Marcar feature 25 BACK** como criterio cumplido. NO marcar `done` en `feature_list.json` hasta que el front (tarea #30) cierre y reviewer #31 valide cross-repo (per el bitácora del current.md).
2. Anotar los 2 caveats §6.1 y §6.3 (duplicación de helper + import de `_EDITABLE_PUBLISH_STATUSES`) en el backlog para una refactorización conjunta cuando se acumule deuda — no son bloqueantes para esta feature.
3. Lanzar implementer front (feature 25 mirror) — el contrato HTTP es estable: PATCH con `{music_id: str | null}`, 200 `{status:'saved', reel_id, music_id, publish_enqueued, event_id?, job_id?}`, 404 `ADMIN_MUSIC_TRACK_NOT_FOUND` para unknown/cross-agency, 409 `REEL_NOT_EDITABLE` para reels aprobados/publicados, 422 para extra keys.
4. Cuando se cierre la feature 25 cross-repo, archivar la sesión `progress/current.md` y agregar a `progress/history.md`.

## 9. Conclusión

Implementación **aprobada**. Cumple los 9 acceptance criteria, mantiene la frontera arquitectónica rendering ↛ configuration, introduce 1 migración limpia con roundtrip verde, propaga el override correctamente por los 3 callsites del job lifecycle (update_music → ingest worker, approve → ingest worker), y el fallback del worker es defensivo sin enmascarar errores reales. 15 tests focalizados nuevos (9 integration + 6 unit) pasan en verde y cubren tanto los happy paths como los failure paths declarados. Los 3 fallos de `pytest -q` son baseline preexistente y están documentados en `progress/current.md`.
