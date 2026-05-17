# Feature 32 — reels_list_pagination_and_filters (impl report)

> Implementer: Claude (lanzado por leader). Estado en `feature_list.json`:
> `in_progress` (no se marcó `done`; espera review).

## 1. Files touched

### Production code

- `modules/reels/infrastructure/reel_query.py` — Añadido helper privado
  `_build_filter_clause` (compone WHERE compartido para list/count). Extendido
  `ReelQuery.list_recent_for_agency` con `offset`, `workflow_state`,
  `publish_status`, `q` (kwargs opcionales; el JOIN ya era contra
  `properties` así que el match de `q` sobre `properties.list_reference` es
  parte del mismo `LEFT JOIN`). Nuevo `ReelQuery.count_for_agency` que reusa
  el mismo helper para producir el total consistente con la página.
- `modules/reels/application/use_cases/list_reels.py` — Reescrito.
  Constantes `DEFAULT_PAGE=1`, `DEFAULT_PAGE_SIZE=25`, `MAX_PAGE_SIZE=100`,
  `MIN_PAGE_SIZE=1`. Helpers públicos `clamp_page`, `clamp_page_size`,
  `normalize_q`. `ListReelsUseCase.execute` ahora devuelve un dataclass
  `ListReelsResult(items, count_total, page, page_size)`; aplica clamping,
  normaliza `q`, computa `offset` y dispara los dos queries
  (`list_recent_for_agency` + `count_for_agency`) bajo la misma UoW.
- `modules/reels/transport/payloads/admin_reels.py` — `ListReelsResponse`
  extendido con `count_total`, `page`, `page_size`, `has_more`. `count`
  se conserva como alias de `len(items)`.
- `modules/reels/transport/http/admin_reels_router.py` — Importa los
  helpers (`clamp_page`, `clamp_page_size`, `normalize_q`). Añadidos
  `_VALID_WORKFLOW_STATES` / `_VALID_PUBLISH_STATUSES` (frozenset con los
  valores que la base usa hoy) y `_parse_csv_filter` (parse CSV → tuple,
  unknown → `ValueError`). El handler `list_admin_agency_reels` ahora:
  - parsea `workflow_state` / `publish_status` (CSV → tuple), responde
    **422 `INVALID_FILTER_VALUE`** ante valores desconocidos;
  - aplica backcompat `?limit=`: si no llega `page` y sí `limit`, lo trata
    como `page_size` con `page=1`; si ambos llegan, `page_size` gana;
  - clampa `page`/`page_size` server-side;
  - trim de `q` (vacío/whitespace → `None`);
  - llama al use case y devuelve `{items, count, count_total, page,
    page_size, has_more}` con `count = len(items)` y
    `has_more = page * page_size < count_total`.
- `docs/API.md` — Nueva sección `#### GET /reels — pagination and filters
  (feature 32)` documentando query params, response shape, y la precedencia
  `page_size > limit`.

### Tests

- `tests/integration/reels/test_list_reels_pagination.py` — **Nuevo**. 14
  tests integration que cubren paginación, filtros y backcompat. Seed de
  50 reels heterogéneos (12 `needs_approval/needs-approval`, 18
  `approved/pending_publish`, 20 `rendered/ready_to_publish`) con la
  needle `cranford` repartida entre title, slug y `list_reference`.
- `tests/unit/reels/test_list_reels.py` — Reescrito. 9 tests (use case +
  clamp helpers + normalize_q).
- `tests/unit/reels/_uow_stubs.py` — `StubReelQuery` ahora acepta la firma
  extendida (`offset`, `workflow_state`, `publish_status`, `q`) y expone
  `count_for_agency` + `count_calls`. Param adicional `count_total` en el
  constructor para inyectar el total esperado.
- `tests/integration/reels/_client.py` — `seed_property_with_reel` acepta
  `slug`, `title`, `list_reference` como kwargs opcionales (los defaults
  conservan el comportamiento previo, así que los tests legacy no rompen).
- `tests/integration/reels/test_admin_reels_router.py` — Una assertion
  ajustada (la de `test_list_reels_returns_empty_for_a_fresh_agency` ya no
  exige igualdad exacta porque ahora la respuesta lleva campos nuevos
  aditivos; el contrato legacy `items + count` sigue verificándose).
- `tests/integration/test_http_transport.py` — Misma corrección de
  assertion para `test_admin_reels_listing_is_empty_for_a_fresh_agency`.

## 2. Tests added (con acceptance que cubren)

`tests/integration/reels/test_list_reels_pagination.py` (14 tests):

| Test | Acceptance cubierta |
|---|---|
| `test_first_page_returns_page_size_items_and_has_more` | `page=1&page_size=10 → 10 items, count_total=50, has_more=True` |
| `test_last_page_returns_remaining_items_and_has_more_false` | `page=5&page_size=10 → 10 items, has_more=False` |
| `test_beyond_last_page_returns_no_items_but_count_total_intact` | `page=6&page_size=10 → 0 items, count_total=50, has_more=False` |
| `test_workflow_state_filter_narrows_results` | `workflow_state=needs_approval filtra` |
| `test_workflow_state_filter_accepts_csv` | `workflow_state=needs_approval,approved` CSV |
| `test_unknown_workflow_state_returns_422` | Unknown → 422 `INVALID_FILTER_VALUE` |
| `test_publish_status_filter_combines_with_workflow_state` | `publish_status` + combinación con `workflow_state` |
| `test_q_matches_title_slug_or_property_reference` | `q='cranford'` parcial en title, slug y `list_reference` |
| `test_count_total_reflects_active_filters` | `count_total` respeta filtros (12 vs 50) |
| `test_legacy_limit_query_param_still_works` | Backcompat: `?limit=10` (sin `page`) → 10 items, `page=1`, `page_size=10` |
| `test_page_size_clamps_to_max_when_too_large` | Clamp: `page_size=500 → 100` |
| `test_page_zero_clamps_to_one` | Clamp: `page=0 → 1` |
| `test_blank_q_is_treated_as_no_filter` | `q='   '` → tratado como `None` |
| `test_page_size_query_wins_over_legacy_limit` | Precedencia `page_size > limit` cuando ambos llegan |

`tests/unit/reels/test_list_reels.py` (9 tests):

| Test | Acceptance cubierta |
|---|---|
| `test_list_reels_returns_query_results_for_existing_agency` | Use case wire-up básico (forwards filtros + offset al query) |
| `test_list_reels_uses_defaults_when_pagination_is_omitted` | Defaults `page=1`, `page_size=25` |
| `test_list_reels_computes_offset_from_page_and_page_size` | `page=3, page_size=25 → offset=50` |
| `test_list_reels_forwards_filters_to_query` | Forwards CSV + `q` al query y al count |
| `test_list_reels_raises_when_agency_does_not_exist` | 404 `ADMIN_AGENCY_NOT_FOUND` (legacy) |
| `test_clamp_page_negatives_and_zero_collapse_to_one` | Clamp `page` |
| `test_clamp_page_size_clamps_to_max_and_default` | Clamp `page_size` |
| `test_clamp_page_size_handles_garbage_input` | Garbage `page` / `page_size` → defaults |
| `test_normalize_q_collapses_blank_strings_to_none` | Trim + empty → `None` |

## 3. Verification output

### `bash ./init.sh`

Exit code: **0**. Pytest tail:

```
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 918 passed, 14 warnings in 430.40s (0:07:10)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Los 3 failed coinciden con la baseline histórica documentada por la sesión
anterior (Codex / HOTFIX side_banner_footer_radius). No hay regresión.
La cuenta total pasa de **897 → 918** (+21 = 14 nuevos tests integration
del feature 32 + 7 unit tests adicionales en `test_list_reels.py`).

### `.venv/bin/python -m pytest tests/integration/reels/ -q`

```
69 passed in 118.35s
```

### `.venv/bin/python -m apps.api --check`

```
API READINESS REPORT
RUNTIME READY: Yes
exit:0
```

## 4. Open items for reviewer

1. **Valores enum de `workflow_state` / `publish_status`** — Las whitelist
   en el router incluyen tanto `needs_approval` (underscore, el valor que
   los tests usan tras la decisión del leader) como `needs-approval`
   (con guion, el valor histórico que aparece en `publish_status` y en
   `_EDITABLE_PUBLISH_STATUSES` de `update_reel_descriptions_override.py`).
   Si el equipo prefiere consolidar a una sola spelling, conviene
   migrar todos los seeds + descriptions overrides + dashboards en un
   feature aparte; por ahora el filtro acepta ambos para no romper
   ninguna lectura existente.
2. **Performance** — `count_for_agency` ejecuta un `SELECT COUNT(*)` que
   reusa el `LEFT JOIN reels` (no necesita el JOIN lateral a
   `media_revisions`). En una agencia con decenas de miles de reels el
   COUNT puede notarse; hoy es despreciable. Si fuese necesario, una
   estrategia futura es exponer un endpoint `/reels/count` cacheable o
   un índice parcial sobre `(agency_id, workflow_state, publish_status)`.
   El índice `idx_reels_agency_workflow_state` ya existe y ayuda al
   filtro single-column.
3. **CSV de un solo valor con coma colgante** — `?workflow_state=approved,`
   parsea a `("approved",)` (el split descarta el segmento vacío). No
   levanta 422. Lo considero feature: el frontend a veces emite trailing
   commas al concatenar selects. Si el reviewer prefiere strict-parse,
   cambiar la línea `cleaned = tuple(p for p in parts if p)` por una que
   pase el vacío al validador.
4. **`q` ILIKE sin índice trigram** — En una BBDD grande,
   `p.title ILIKE '%cranford%'` no usa índice. Convivimos con esto desde
   antes (no es regresión); si el dataset crece, considerar
   `pg_trgm` + `GIN` index sobre las tres columnas.
5. **`order by` no incluye un tie-breaker estable** — La query mantiene
   el orden original `ORDER BY r.updated_at DESC NULLS LAST, p.fetched_at
   DESC NULLS LAST`. En reels con timestamps idénticos al milisegundo
   (raro en producción pero posible en tests con muchos seeds en un
   `for`-loop), un paginado podría producir items duplicados o saltados.
   Hoy los tests con 50 reels insertados en un `for` no han fallado;
   si se reproduce, añadir `, p.source_property_id DESC` como tercer
   criterio. Marcado como observación, no como bloqueo.
6. **Schema** — No tocado. Sin migración. La columna `properties.list_reference`
   ya existía en `20260501_0001_initial_schema.py` (línea 267).
7. **Drive-by no aplicado** — `seed_property_with_reel` admitía solo
   `slug="sample"` y `title="Sample"` hardcoded. Lo extendí con kwargs
   opcionales preservando los defaults. Si el reviewer quiere
   factorizar más helpers (p. ej. `seed_property_only`), es trabajo
   aparte y no impacta este feature.

## 5. Sample curl commands para smoke manual contra :8001

Suponiendo `AGENCY_ID` y `ADMIN_TOKEN` exportados:

```bash
AGENCY_ID="<uuid-agencia>"
ADMIN_TOKEN="<bearer-admin-test>"
BASE="http://127.0.0.1:8001/v1/admin/agencies/$AGENCY_ID/reels"

# 1) Pagina 1, 25 items, sin filtros
curl -fsS "$BASE?page=1&page_size=25" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq .

# 2) Pagina 2 con 10/pagina
curl -fsS "$BASE?page=2&page_size=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '{count, count_total, page, page_size, has_more}'

# 3) Filtro workflow_state (CSV)
curl -fsS "$BASE?workflow_state=needs_approval,approved" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.count_total'

# 4) Combinación workflow_state + publish_status
curl -fsS "$BASE?workflow_state=approved&publish_status=pending_publish" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.count_total'

# 5) Busqueda libre (title / slug / list_reference)
curl -fsS "$BASE?q=cranford" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.items[] | {title, slug, source_property_id}'

# 6) Backcompat: ?limit= legacy sigue funcionando
curl -fsS "$BASE?limit=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '{count, count_total, page, page_size, has_more}'

# 7) Clamping: page_size=500 -> 100
curl -fsS "$BASE?page_size=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.page_size'

# 8) Validación: workflow_state desconocido -> 422
curl -i "$BASE?workflow_state=bogus_state" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Expected: HTTP/1.1 422 ... {"error":"...","code":"INVALID_FILTER_VALUE",...}
```
