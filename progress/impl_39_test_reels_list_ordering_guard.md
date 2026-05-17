# Feature 39 — test_reels_list_ordering_guard (implementer report)

## Resumen

Guard test integration añadido para fijar el contrato de orden del endpoint
`GET /v1/admin/agencies/{agency_id}/reels` (ORDER BY `r.updated_at DESC
NULLS LAST`, ver `modules/reels/infrastructure/reel_query.py:259`). El
backend ya cumple este contrato; los 2 tests garantizan que nadie lo rompa
a futuro. Cero cambios en código de producción.

## Archivos creados

| Tipo | Path |
|------|------|
| Test integration (nuevo) | `tests/integration/reels/test_list_reels_ordering.py` |

## Archivos modificados

| Tipo | Path |
|------|------|
| Estado de sesión | `progress/current.md` (entrada feature 39 añadida) |
| Estado de feature | `feature_list.json` (id 39 ya estaba `in_progress` antes de empezar) |

Ningún archivo bajo `apps/`, `modules/`, `shared/`, `alembic/`, `settings/`
o `docs/` fue tocado. Confirmado contra el scope del leader.

## Decisiones tomadas

- **Control de `updated_at` vía SQL directo** (helper local
  `_force_updated_at`). El seed normal `seed_property_with_reel` usa
  `now()` en `created_at`/`updated_at`, lo que dejaría los tres reels con
  timestamps efectivamente iguales y la aserción de orden sería un
  coin-flip. Un `UPDATE reels SET updated_at = :ts` por fila tras el seed
  fija T0, T0+1h, T0+2h de forma determinista. Esto es exactamente lo
  permitido por el leader_notes ("vía SQL directo en la fixture es más
  simple y suficiente para guardar el contrato de la query").
- **No se ejercita un PATCH real** (ej. `UpdateReelMusicOverrideUseCase`)
  para el test 2: el objetivo es probar el orden de la query, no el use
  case. Un `UPDATE` directo al `updated_at` reproduce exactamente lo que
  el use case haría (`ReelStateRepository.save()` siempre setea
  `updated_at = utcnow()`, ver `modules/reels/infrastructure/reel_state_repository.py:261`)
  sin acoplar el test a la API de un use case que podría cambiar.
- **Patrón seed reusado**: `seed_tenant` + `seed_property_with_reel` +
  `build_admin_reels_client`, idéntico a `test_list_reels_pagination.py`.
  Sin fixtures nuevas en `tests/support/`.
- **Property IDs altos (2001/2002/2003)** para evitar cualquier choque
  futuro con el rango 1000-1049 que usa `test_list_reels_pagination.py`
  por si alguien decide compartir schema entre tests (hoy no se comparte
  porque cada test crea su propio `temporary_postgres_schema`, pero es
  cheap defensive).

## Verificación

### 1. `pytest tests/integration/reels/test_list_reels_ordering.py -v`

```
tests/integration/reels/test_list_reels_ordering.py::test_list_reels_orders_by_updated_at_desc PASSED [ 50%]
tests/integration/reels/test_list_reels_ordering.py::test_list_reels_promotes_touched_reel_to_top PASSED [100%]

============================== 2 passed in 4.73s ===============================
```

### 2. `pytest tests/integration/reels/ -q` (regression)

```
........................................................................ [ 61%]
..............................................                           [100%]
118 passed in 195.84s (0:03:15)
```

### 3. `bash ./init.sh`

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
...
=========================== short test summary info ============================
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1042 passed, 14 warnings in 563.28s (0:09:23)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Exit code 0. Los 3 fallos son los mismos baseline-failures conocidos
(`test_http_surface_contract.py` + 2 en `test_http_transport.py`) — no
introducidos por esta feature. Total: **1042 passed = 1040 baseline + 2
tests nuevos**, alineado con el delta esperado.

## Acceptance criteria — checklist

- [x] Test 1: tres reels seeded en T1<T2<T3 → GET devuelve orden T3, T2, T1.
- [x] Test 2: tras mutar el reel T1 (touch `updated_at`) → siguiente GET
      devuelve T1 primero.
- [x] Los tests existentes en `tests/integration/reels/` siguen pasando
      sin regresión (118 passed; era 116 antes del delta de 2).
- [x] `bash ./init.sh` exit 0 (módulo los 3 baseline failures conocidos).

## Notas para el reviewer

- Sin migración Alembic.
- Sin cambios en `feature_list.json` salvo el `in_progress` ya existente.
- Sin cambios en docs (`docs/API.md`, `docs/http_surface.md`,
  `docs/openapi.json`) — el contrato HTTP no cambia, sólo se añade un
  guard test.
- Estado en `feature_list.json` queda en `in_progress`; el leader (no el
  implementer) marcará `done` tras la review.
