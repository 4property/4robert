# Review feature 21 — `per_reel_description_override_endpoint` (backend)

- **Fecha:** 2026-05-14
- **Agente:** reviewer (backend), invocado por leader Claude
- **Veredicto:** **APPROVED**
- **Informe del implementer:** `progress/impl_21_per_reel_description_override_endpoint.md`

## Resumen

La feature 21 cierra el bucle de descripciones por reel añadiendo:

- Columna `reels.descriptions_override` (JSONB nullable, default NULL) via
  Alembic `20260514_0003`, encadenada limpiamente tras el hotfix Codex
  `20260514_0002_classic_render_template_preview`. Up / down / up validados.
- Endpoint `PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/descriptions`
  con payload Pydantic (`extra='forbid'`) y mapeo de errores 404/409/422.
- Use case `UpdateReelDescriptionsOverrideUseCase` con validación contra
  `agency_reel_defaults.platforms` y enforcement del gate editorial
  (`publish_status in {needs-approval, pending_review, pending, ''}`).
- Merge per-platform aplicado en `IngestPropertyIntoReelUseCase` justo
  después de la generación de captions y antes del `publish_target_snapshot`.
  Esa ubicación es **correcta**: el worker (`ReelPipeline.handle`) ejecuta
  ingest → publish en cada `reel_publish` job, así que tanto la ingestión
  inicial como la re-aprobación vía `regenerate_reel.py` pasan por aquí.
- Repositorio respeta la regla "no `session.commit()` en repositorio": la
  UoW commitea en el `__exit__` del context manager abierto por el router.

## Validación contra los acceptance criteria

| # | Criterio | Estado |
|---|---|---|
| 1 | Migración Alembic add column `reels.descriptions_override` JSONB nullable; downgrade reversible | OK (verificado up→down→up; head única `20260514_0003`) |
| 2 | PATCH con admin auth persiste el override por plataforma | OK (test `test_patch_descriptions_persists_override_and_returns_200` valida la persistencia en `reels.descriptions_override`) |
| 3 | PATCH a reel ya aprobado/publicado devuelve 409 (RESOURCE_LOCKED o equivalente) | OK (devuelve **409 `REEL_NOT_EDITABLE`**; ver decisión abajo) |
| 4 | Worker publish_reel usa override por plataforma; fallback al snapshot | OK (verificado: el merge se aplica en ingest sobre `publish_descriptions_by_platform`, que es lo que consume `property_publisher.py` y persiste en `publish_target_snapshot.descriptions_by_platform`) |
| 5 | Edits posteriores a la template global no fuerzan re-render de reels con override | OK (`content_fingerprint` se calcula sólo a partir de propiedad+delivery_plan+render_template — NO incluye las descripciones; `requires_render = content_changed or not has_local_artifacts`, así que cambiar la template global o el override no dispara re-render mientras los local artifacts existan) |
| 6 | Tests integración cubren happy path, 404, 409, 422 | OK (7 tests integración + 5 unitarios; 12 nuevos, todos verdes) |
| 7 | `pytest -q` verde excepto baseline 3 | OK (711 passed, 3 fallos baseline conocidos: `test_http_surface_contract.py` por ausencia del repo frontend en este host + 2 en `test_http_transport.py` por health endpoints) |
| 8 | `python -m apps.api --check` y `python -m apps.worker --check` exit 0 | OK |

## Decisiones del implementer — validación crítica

### 1. Path real del endpoint

El plan literal decía `/v1/admin/reels/{reel_id}/descriptions` pero el resto
de `admin_reels_router.py` identifica reels por la tupla
`(agency_id, site_id, source_property_id)` — **no** existe ningún
endpoint admin de reels que use un `reel_id` UUID. El path elegido por el
implementer (`/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/descriptions`)
es **coherente** con `GET .../reels/{site_id}/{source_property_id}`,
`POST .../approve`, `POST .../reject` y los asset endpoints. Aprobado.

### 2. Códigos de error

- **409 `REEL_NOT_EDITABLE`** (en vez de `RESOURCE_LOCKED`). El repo no usa
  `RESOURCE_LOCKED` en ningún sitio — el patrón consolidado es códigos
  semánticos en `UPPER_SNAKE_CASE` (`ADMIN_AGENCY_NOT_FOUND`,
  `ADMIN_REEL_NOT_FOUND`, `EXISTING_MEDIA_REQUIRED`,
  `CURATED_ASSET_PREPARATION_FAILED`, etc.). `REEL_NOT_EDITABLE` encaja en
  esa convención y es más accionable para el frontend.
- **422 `PLATFORM_NOT_ENABLED`** (en vez de `UNKNOWN_PLATFORM`). Justifica
  bien la semántica: la plataforma puede existir en el catálogo pero no
  estar habilitada para esta agencia. 422 es el código correcto para una
  validación de regla de negocio (no de tipo). Aprobado.

### 3. Override aplicado en ingest, no en publish

Decisión validada con lectura de `apps/worker/runtime.py` y
`modules/reels/application/orchestrator.py`. El worker:

1. `self._ingest.execute(media_job)` → `IngestPropertyIntoReelUseCase` arma
   `PropertyContext` (con el merge per-platform aplicado).
2. `self._publish.execute(context, rendered_media)` → consume
   `context.publish_descriptions_by_platform` que ya trae el override.

Y para el flujo **approve → publish**: `regenerate_reel.py` encola un job
`reel_publish` con el payload de WordPress original — al desencolarse pasa
por el mismo `ReelPipeline.handle`, por tanto por el ingest, por tanto el
override se aplica. **No hay regresión: editar override sobre un reel ya
ingestado SÍ surte efecto al re-publicar.**

### 4. Semántica replace + `{}` limpia

Cubierto por `test_patch_descriptions_with_empty_mapping_clears_override`:
PATCH con `{"descriptions_by_platform": {}}` → 200 → `descriptions_override`
queda en `NULL`. La función `_override_to_jsonb_param` mapea `None` y `{}`
al mismo sentinel SQL NULL, así que el `WHERE descriptions_override IS NULL`
sigue funcionando como "no override" sin ambigüedad.

### 5. Estados editables (`pending`, `''`, `needs-approval`, `pending_review`)

El plan original mencionaba solo `needs-approval` y `pending_review`. El
implementer añade `pending` y `''`. Verificado contra el resto del repo:

- `_ingest_property_assets.py:192` setea `publish_status='pending'` para
  reels recién ingestados.
- `reel_state.py:68` (`build_empty_reel_state`) inicia con `publish_status=''`.

Ambos son estados de pre-aprobación legítimos donde el editor tiene
sentido. Aprobado — la ampliación es coherente con el ciclo de vida del
reel y mejora la UX sin debilitar el gate editorial (los estados terminales
`published`, `approved`, `pending_publish`, `rejected`, `failed`, `skipped`
siguen rechazándose con 409).

## Verificaciones ejecutadas en esta review

```text
.venv/bin/python -m alembic heads                  → 20260514_0003 (head)  ✅
.venv/bin/python -m alembic upgrade head           → OK                    ✅
.venv/bin/python -m alembic downgrade -1           → drop_column OK        ✅
.venv/bin/python -m alembic upgrade head           → OK (idempotente)      ✅
pytest tests/integration/reels/test_admin_reels_descriptions_override.py
    + tests/unit/reels/test_ingest_applies_descriptions_override.py
                                                    → 12 passed in 11.51s  ✅
pytest tests/integration/reels/ tests/unit/reels/  → 123 passed in 53.73s  ✅
bash ./init.sh (que incluye pytest -q global)      → 711 passed, 3 baseline
                                                       failures, exit 0    ✅
python -m apps.api --check                          → exit 0                ✅
python -m apps.worker --check                       → exit 0                ✅
```

Los 3 fallos baseline en `pytest -q` están documentados en informes
anteriores (`test_http_surface_contract.py` por ausencia del repo frontend;
2 en `test_http_transport.py::HttpTransportIntegrationTests` por health
endpoints sin dispatcher pausado). No introducidos por feature 21.

## Concurrencia — interferencias detectadas

- Migración `20260514_0003` se encadena correctamente tras
  `20260514_0002_classic_render_template_preview` (hotfix Codex). No hay
  conflicto ni cadena rota.
- No detecté migraciones nuevas de feature 22 (música) que puedan haber
  aparecido durante la review.
- `feature_list.json` id 21 sigue `in_progress` (correcto — no me toca
  cerrar a `done` según el protocolo, eso queda para el leader una vez
  cierre también el frontend).

## Notas para el leader

- La review es **APPROVED** sin cambios solicitados. Sin embargo, el cierre
  de la feature requiere también el lado frontend (tasks #16 y #17). El
  backend está listo para ser consumido por la UI.
- Sugerencia opcional (no bloqueante): la UI podría querer un endpoint
  `GET .../descriptions` que devuelva el override actual junto con las
  captions auto-generadas para que el editor abra precargado. Hoy el
  inspect endpoint (`GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}`)
  no expone `descriptions_override` — sería un nice-to-have, no necesario
  para el MVP de la feature.
- El test integración `test_patch_descriptions_rejects_extra_keys_with_422`
  documenta correctamente que Pydantic devuelve 422 para campos extra (no
  hace falta tocar nada).
