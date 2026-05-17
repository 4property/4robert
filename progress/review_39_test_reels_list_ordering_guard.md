# Review — feature 39 (test_reels_list_ordering_guard)

**Veredicto:** APPROVED

## Resumen

Guard test integration que fija el contrato de orden del endpoint
`GET /v1/admin/agencies/{agency_id}/reels` (`ORDER BY r.updated_at DESC
NULLS LAST`, definido en
`modules/reels/infrastructure/reel_query.py:259`). Cero cambios en
código de producción; sólo se añade
`tests/integration/reels/test_list_reels_ordering.py` con 2 tests.

## Verificación ejecutada

| Comando | Resultado |
|---------|-----------|
| `.venv/bin/python -m pytest tests/integration/reels/test_list_reels_ordering.py -v` | 2 passed in 4.71s |
| `.venv/bin/python -m pytest tests/integration/reels/ -q` (regresión) | 118 passed in 219.23s (= 116 baseline + 2 nuevos) |
| `bash ./init.sh` | exit 0 — 1042 passed, 3 baseline failures conocidos |

Los 3 fallos baseline son `test_http_surface_contract.py` +
`test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state`
+ `test_http_transport.py::test_health_endpoints_return_minimal_payloads`,
documentados como conocidos (no introducidos por feature 39). El delta
+2 sobre 1040 coincide exactamente con los 2 tests nuevos.

## Checkpoints

- **C1 — Arnés completo:** [x] init.sh exit 0; archivos base presentes.
- **C2 — Estado coherente:** [x] feature 39 sigue en `in_progress` (el
  leader la cerrará); no se añadieron entradas espurias a
  `feature_list.json` (revisado `feature_list.json:1296-1322`).
- **C3 — Arquitectura respetada:** [x] el cambio es 100 % en
  `tests/integration/reels/`. Production tree (`apps/`, `modules/`,
  `shared/`, `alembic/`, `settings/`) intacto frente al baseline previo a
  la feature 39 (confirmado por timestamps de archivos y por inspección
  del scope declarado).
- **C4 — Verificación real:** [x] los tests usan
  `tests/support/postgres.py::temporary_postgres_schema` +
  `seed_tenant` + helper `seed_property_with_reel` de
  `tests/integration/reels/_client.py`, no mockean Postgres.
- **C5 — Schema y migraciones:** [x] no aplica (sin cambios de schema,
  sin nueva migración Alembic).
- **C6 — Cierre de sesión:** [x] sólo se añade un fichero `.py`
  productivo; no hay `print()` de debug, ni TODOs sin contexto, ni
  archivos `.tmp_*` introducidos por la feature.

## Revisión punto por punto

### 1. Existencia y forma del fichero

`tests/integration/reels/test_list_reels_ordering.py:1-9` abre con un
docstring que explicita: "Guards the ordering contract of the reels
list endpoint" y enlaza a `reel_query.py:259`. Cumple el requerimiento
de comentario de propósito.

Hay 2 tests:
- `test_list_reels_orders_by_updated_at_desc`
  (`test_list_reels_ordering.py:62-115`).
- `test_list_reels_promotes_touched_reel_to_top`
  (`test_list_reels_ordering.py:118-191`).

### 2. Calidad de asserts

- Los asserts comparan `source_property_id` (id estable elegido por el
  test al seedear) — no objetos completos
  (`test_list_reels_ordering.py:112-115`, `:167-171`, `:187-191`).
- Los tres timestamps son `t0`, `t0+1h`, `t0+2h` y el touch del test 2
  es `t0+3h` (`test_list_reels_ordering.py:67-100`, `:175-180`). Hay
  separación horaria, no microsegundal; no es flaky por relojes.

### 3. Control de `updated_at`

El test usa SQL directo vía `_force_updated_at`
(`test_list_reels_ordering.py:30-59`):

```sql
UPDATE reels SET updated_at = :when
WHERE external_source_id = :external_source_id
  AND source_property_id = :source_property_id
```

- Es seguro: `WHERE` estricto sobre las dos claves de seed; no afecta a
  otros reels.
- Cada test corre en su propio `temporary_postgres_schema`
  (`test_list_reels_ordering.py:64`, `:120`), por lo que no hay
  cross-contamination entre tests.
- La justificación del implementer es correcta: el seed
  `seed_property_with_reel` setea `created_at = updated_at = now()`
  (`tests/integration/reels/_client.py:128-129`), así que sin este
  helper los tres reels tendrían el mismo `updated_at` y la aserción de
  orden sería un coin-flip. La vía SQL directa estaba explícitamente
  permitida en `leader_notes`.
- Aceptable que no se ejercite un PATCH real: el use case de mutación
  (`ReelStateRepository.save()`,
  `modules/reels/infrastructure/reel_state_repository.py:261-264`)
  siempre setea `updated_at = utcnow()`, así que un `UPDATE` directo
  reproduce exactamente lo que cualquier PATCH haría sin acoplar el
  guard test a la API de un use case que podría cambiar.

### 4. Reuso de fixtures

`test_list_reels_ordering.py:18-27` importa:

- `ADMIN_BEARER`, `build_admin_reels_client`, `seed_property_with_reel`
  de `tests/integration/reels/_client.py` (helpers ya usados por
  `test_list_reels_pagination.py`).
- `seed_tenant`, `temporary_postgres_schema`, `temporary_workspace`
  de `tests/support/postgres.py`.

Sin fixtures nuevas y sin duplicación de lógica de seed.

### 5. Conteo de tests

Confirmado: `bash ./init.sh` reporta `1042 passed` = 1040 baseline + 2
tests nuevos. Coincide con lo declarado por el implementer.

### 6. Scope y reglas duras

- Solo cambios en `tests/integration/reels/test_list_reels_ordering.py`
  (archivo nuevo).
- `feature 39` sigue en `in_progress` en `feature_list.json:1320` —
  el implementer no la marcó `done`.
- No hay migraciones Alembic asociadas a la feature 39 (no aplica).
- No se tocó `docs/openapi.json` / `docs/http_surface.md` / `docs/API.md`
  (el contrato HTTP no cambia).

## Cambios requeridos

Ninguno.

## Follow-ups no bloqueantes (opcionales, fuera del scope de esta feature)

1. Considerar exponer `_force_updated_at` (o un equivalente
   `touch_reel_updated_at`) como helper público en
   `tests/integration/reels/_client.py` o `tests/support/postgres.py`
   si alguna feature futura necesita controlar timestamps de reels
   determinísticamente. Hoy es función privada local a este test y eso
   está bien para un único uso.
2. El test cubre el ordering primario (`r.updated_at DESC NULLS LAST`)
   pero no ejercita el tie-breaker secundario
   `p.fetched_at DESC NULLS LAST` (`reel_query.py:259`). Si se quiere
   un guard más completo, una feature futura podría añadir un test que
   seedee dos reels con `updated_at = NULL` y `fetched_at` distintos.
3. No bloquea, pero si en el futuro se prefiere ejercitar también el
   path real de mutación (no solo el query), añadir un test paralelo
   que use un PATCH público (p. ej.
   `PATCH /v1/admin/agencies/{id}/reels/{rid}/music`) para forzar el
   `ReelStateRepository.save()` y verificar que ese path real también
   promueve el reel al top. El guard actual ya protege el contrato
   crítico; este sería un test adicional, no un reemplazo.
