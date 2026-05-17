# Review — feature 32 (`reels_list_pagination_and_filters`)

**Veredicto:** APPROVED

Revisor: Claude (subagente `reviewer`, lanzado por leader).
Fecha: 2026-05-15.

---

## 1. Per-decision audit table

| Decisión del leader | Verificada | Evidencia (archivo:línea) |
|---|---|---|
| Búsqueda `q` ILIKE `%q%` sobre **tres columnas** | sí | `modules/reels/infrastructure/reel_query.py:56-60` (`p.title ILIKE :q_pattern OR p.slug ILIKE :q_pattern OR p.list_reference ILIKE :q_pattern`) |
| Columnas son JOIN real, no concat en Python | sí | `modules/reels/infrastructure/reel_query.py:248-251` (`FROM properties AS p LEFT JOIN reels AS r ON r.external_source_id = p.external_source_id AND r.source_property_id = p.source_property_id`). `p.title`, `p.slug`, `p.list_reference` son columnas reales de `properties` (verificado en `modules/catalog/infrastructure/orm.py:53-61` y `alembic/versions/20260501_0001_initial_schema.py:267`). Nota: el docstring del router habla de `reels.title`/`reels.slug`, pero las columnas viven en `properties`; la semántica de "title/slug del reel" se mantiene en el payload aplanado. No es bloqueante. |
| `q` con trim + empty/whitespace → `None` | sí | `modules/reels/application/use_cases/list_reels.py:49-59` (`normalize_q`); test unit `tests/unit/reels/test_list_reels.py:146-152`; test integration `tests/integration/reels/test_list_reels_pagination.py:465-486` (`?q=%20%20%20` → `count_total == _TOTAL_REELS`). |
| `count` legacy = `len(items)` y presente | sí | `modules/reels/transport/http/admin_reels_router.py:274` (`"count": len(serialized)`) y `tests/integration/reels/test_list_reels_pagination.py:122,151` (`payload["count"] == 10`). |
| `?limit=` funciona cuando `page` ausente | sí | `modules/reels/transport/http/admin_reels_router.py:245-251` (rama `raw_page_size is None and raw_page is None and raw_limit is not None`); test `test_legacy_limit_query_param_still_works` (`tests/integration/reels/test_list_reels_pagination.py:385-410`). |
| Precedencia `page_size > limit` cuando ambos llegan | sí | mismo bloque del router (rama `else` toma `raw_page_size`); test `test_page_size_query_wins_over_legacy_limit` (`tests/integration/reels/test_list_reels_pagination.py:489-511`). Documentado en `docs/API.md:525`. |
| Clamping `page>=1` (default 1, 0/negativos → 1) | sí | `modules/reels/application/use_cases/list_reels.py:21-31` (`clamp_page`); tests `test_clamp_page_negatives_and_zero_collapse_to_one` y `test_page_zero_clamps_to_one`. |
| Clamping `1<=page_size<=100` (default 25, 500 → 100) | sí | `modules/reels/application/use_cases/list_reels.py:34-46` (`clamp_page_size`); tests `test_clamp_page_size_clamps_to_max_and_default` y `test_page_size_clamps_to_max_when_too_large`. |
| `count_total` con el **mismo WHERE** que `items` | sí | `modules/reels/infrastructure/reel_query.py:19-62` define `_build_filter_clause`; ambos métodos (`list_recent_for_agency` líneas 219-223 y `count_for_agency` líneas 319-323) lo invocan con los mismos kwargs. El use case (`list_reels.py:111-124`) reenvía los mismos `workflow_state` / `publish_status` / `q` a ambos. Test `test_count_total_reflects_active_filters` confirma `count_total=12` (filtro) vs `_TOTAL_REELS=50` (sin filtro). |
| Filter CSV → 422 ante enum desconocido | sí | `modules/reels/transport/http/admin_reels_router.py:132-136,217-237` (`_parse_csv_filter` lanza `ValueError` → 422 `INVALID_FILTER_VALUE`); test `test_unknown_workflow_state_returns_422`. |
| Sin cambios de schema | sí | `git diff --stat` no muestra ediciones de `shared/db/orm.py` atribuibles a feature 32 (las 13 líneas de diff actuales son `descriptions_override` y `music_id` de features 21/25, con sus migraciones 20260514_0003 y _0006). No hay revisión Alembic nueva para feature 32. La columna `properties.list_reference` ya existía (`alembic/versions/20260501_0001_initial_schema.py:267`). |

## 2. Acceptance checklist (feature 32 en `feature_list.json`)

- ✅ `GET /reels?page=1&page_size=10` devuelve 10 items + `count_total` + `page=1` + `page_size=10` + `has_more` correcto — `test_first_page_returns_page_size_items_and_has_more`.
- ✅ `?page_size=500` → 100; `?page=0` → 1 — `test_page_size_clamps_to_max_when_too_large`, `test_page_zero_clamps_to_one`.
- ✅ `?workflow_state=needs_approval` filtra; CSV acepta `needs_approval,approved` — `test_workflow_state_filter_narrows_results`, `test_workflow_state_filter_accepts_csv`.
- ✅ `?q=cranford` busca por `title`, `slug` o `list_reference` ILIKE `%cranford%` — `test_q_matches_title_slug_or_property_reference` (extiende la acceptance original a 3 columnas, decisión del leader respetada). El spec original menciona "title o slug"; el match adicional sobre `list_reference` es aditivo y consistente con la decisión.
- ✅ `count_total` respeta filtros — `test_count_total_reflects_active_filters` (12 con filtro vs 50 sin filtro).
- ✅ `?limit=N` legacy sigue funcionando — `test_legacy_limit_query_param_still_works` y `test_page_size_query_wins_over_legacy_limit`.
- ✅ `pytest -q` verde — 918 passed (los 3 failed son baseline pre-feature, ver §3).
- ✅ `apps.api --check` exit 0 — capturado en §3.

## 3. Verificación re-run

### `bash ./init.sh`

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
=========================== short test summary info ============================
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 918 passed, 14 warnings in 459.68s (0:07:39)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Exit code 0. Los 3 fallos son baseline (verificados leyendo `test_health_endpoints_return_minimal_payloads`: la diferencia es la presencia de `configured_worker_count` en el payload de `/health`, no tiene nada que ver con feature 32). Idéntica baseline a la reportada por el implementer y por la sesión Codex previa.

### `pytest tests/integration/reels/ -q`

```
69 passed in 118.21s
```

### `pytest tests/integration/reels/test_list_reels_pagination.py -q -v`

14 tests, todos verdes en 37.66s. Los nombres cubren los checks del leader:
- Clamping: `test_page_size_clamps_to_max_when_too_large`, `test_page_zero_clamps_to_one`.
- CSV + 422: `test_workflow_state_filter_accepts_csv`, `test_unknown_workflow_state_returns_422`.
- `q` parcial sobre 3 columnas: `test_q_matches_title_slug_or_property_reference` (1005=title, 1006=slug, 1007=list_reference; el test asserta `property_ids == {1005, 1006, 1007}`).
- `count_total` respeta filtros: `test_count_total_reflects_active_filters`.
- `?limit=` backcompat: `test_legacy_limit_query_param_still_works`, `test_page_size_query_wins_over_legacy_limit`.

### `apps.api --check`

```
API READINESS REPORT
RUNTIME READY: Yes
exit:0
```

## 4. Reglas duras

- ✅ Sin `session.commit()` en `reel_query.py` ni en el resto del path de feature 32 (`grep -n "session.commit"` vacío).
- ✅ Sin imports legacy en los archivos tocados.
- ✅ Sin imports cross-módulo de `<otro>.application` / `<otro>.infrastructure`.
- ✅ Sin schema changes propias de feature 32 (ver §1).
- ✅ Tests no eliminados ni debilitados:
  - Las dos assertions ajustadas (`test_list_reels_returns_empty_for_a_fresh_agency` en `tests/integration/reels/test_admin_reels_router.py:42-49` y `test_admin_reels_listing_is_empty_for_a_fresh_agency` en `tests/integration/test_http_transport.py:652-660`) pasan de `assertEqual(payload, {"items": [], "count": 0})` a 4 asserts explícitos (`items`, `count`, `count_total`, `has_more`). El cambio es justificado (campos aditivos por contrato) y refuerza la verificación: ahora también se prueba `count_total == 0` y `has_more is False`. No es un weakening, es un strengthening.
- ✅ Helpers `tests/support/postgres.py` reutilizados (no mocks de Postgres).
- ✅ `seed_property_with_reel` ahora acepta `slug` / `title` / `list_reference` con defaults preservados — los tests legacy no rompen.

## 5. Issues found

Ninguno bloqueante. Observaciones no bloqueantes (informativas, mismas que ya documentó el implementer en §4 de `impl_32.md`):

- **non-blocking / nit**: El docstring de la ruta en `admin_reels_router.py:196-197` habla de `reels.title`, `reels.slug`, mientras que la SQL apunta a columnas de `properties`. El comportamiento es el correcto (la admin "Reels" view expone los campos aplanados de la JOIN como "title/slug del reel"), pero alinear el docstring a `properties.title` / `properties.slug` o aclarar "the reel's title / slug as displayed in the admin view (sourced from `properties`)" ayudaría a futuros lectores. Sugerencia para un follow-up cosmético, no para este review.
- **non-blocking / nit**: `_parse_csv_filter` descarta segmentos vacíos (trailing comma → silenciosa). Documentado por el implementer; el comportamiento es razonable y el frontend a veces emite comas colgantes. Acceptable.
- **non-blocking / observación**: El `ORDER BY r.updated_at DESC NULLS LAST, p.fetched_at DESC NULLS LAST` no incluye tie-breaker estable. Con timestamps idénticos al milisegundo (poco probable en producción pero posible en seed loops) un paginado podría duplicar / saltar items. Hoy no se reproduce en los tests. Si en el futuro se ve flake, añadir `, p.source_property_id DESC`.
- **non-blocking / observación**: Las whitelist `_VALID_WORKFLOW_STATES` y `_VALID_PUBLISH_STATUSES` aceptan tanto `needs_approval` como `needs-approval` (spellings históricos divergentes). Bien decidido para no romper lecturas existentes; consolidar a una única spelling es trabajo aparte.

## 6. Open items para el leader

### Smoke manual sugerido contra :8001

Suponiendo `AGENCY_ID` y `ADMIN_TOKEN` exportados:

```bash
AGENCY_ID="<uuid-agencia>"
ADMIN_TOKEN="<bearer-admin-test>"
BASE="http://127.0.0.1:8001/v1/admin/agencies/$AGENCY_ID/reels"

# (1) Shape básico
curl -fsS "$BASE?page=1&page_size=25" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '{count, count_total, page, page_size, has_more, items_len: (.items|length)}'

# (2) Clamping observable
curl -fsS "$BASE?page_size=500" -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.page_size'
# expected: 100

# (3) CSV filter + count_total
curl -fsS "$BASE?workflow_state=needs_approval,approved" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.count_total'

# (4) q parcial sobre las tres columnas (sustituye 'cranford' por un valor real)
curl -fsS "$BASE?q=cranford" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '.items[] | {title, slug, source_property_id}'

# (5) Backcompat: ?limit= sin page
curl -fsS "$BASE?limit=10" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '{count, count_total, page, page_size, has_more}'

# (6) Precedencia: page_size gana a limit cuando ambos llegan
curl -fsS "$BASE?limit=99&page_size=5" -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '.page_size'
# expected: 5

# (7) Validación: 422 ante enum desconocido
curl -i "$BASE?workflow_state=bogus_state" -H "Authorization: Bearer $ADMIN_TOKEN"
# expected: HTTP/1.1 422  body.code == INVALID_FILTER_VALUE
```

### Tareas restantes para cerrar la feature

1. Marcar `feature 32` como `done` en `feature_list.json` (ya aplicado por este reviewer).
2. (Cross-repo) Coordinar con la feature 32 del front (`/opt/projects/4Reels-Frontend/feature_list.json`) que consume `{count_total, page, page_size, has_more}`.

---

## Checkpoints (CHECKPOINTS.md)

- C1: [x] Arnés completo, `./init.sh` exit 0.
- C2: [x] Feature 32 en `in_progress` antes del review; reviewer la pasa a `done`.
- C3: [x] Sin imports cross-módulo `application`/`infrastructure`; sin `session.commit()` en repos; sin código nuevo en `services/` `application/` `repositories/` `core/` `domain/`.
- C4: [x] 14 integration + 9 unit tests nuevos, todos verdes; reuso de `tests/support/postgres.py`.
- C5: [x] Sin cambios de schema atribuibles a feature 32; sin migración nueva (la columna `properties.list_reference` ya existía en la migración initial).
- C6: [x] Sin archivos temporales relevantes en el árbol de la feature; `progress/impl_32.md` y `progress/review_32.md` quedan como trazas.
