# Review — feature 14 (`compute_slot_honors_timezone_hold_quiet_skip`)

**Veredicto:** APPROVED

## Resumen

El implementer entrega el refactor de `compute_next_publish_slot` con
firma `(rules, now_utc, *, agency_timezone="UTC")`, algoritmo en orden
estricto (hold → skip_weekends → quiet_hours), fallback defensivo de
timezone con WARNING y preservación del contrato pre-feature-13 (todos
los toggles off → `None`). El threading desde `regenerate_reel.py` carga
`agency` vía `uow.tenancy.agencies.get_by_id(...)` (verificado contra
`modules/tenancy/infrastructure/agency_repository.py:40`) y forwardea
`agency_timezone=agency.timezone or "UTC"`. Cobertura unitaria amplia
(39 tests en `test_compute_next_publish_slot.py`, +2 en
`test_regenerate_reel.py`, +1 integration end-to-end con fake clock en
`test_admin_reels_router.py`). Documentación en `docs/API.md` cubre la
nueva semántica.

Verificación: `pytest -q` 3 failed (los 3 pre-existentes documentados en
`progress/review_13_*.md`) / 640 passed. `apps.api --check` y
`apps.worker --check` exit 0. Subset crítico de 79 tests verde.

El scope queda limitado a los archivos prometidos: ni `modules/catalog/**`,
ni `modules/rendering/**`, ni los routers/repos de render-templates, ni
`ingest_property_into_reel.py` fueron tocados por esta sesión. Los
cambios en esos archivos en `git diff` corresponden a la sesión paralela
de feature 16, verificado por mtime fuera del bloque de escritura del
implementer.

## Checklist mínimo

### 1. Refactor de `compute_next_publish_slot.py`

- [x] Firma final `(rules, now_utc, *, agency_timezone="UTC")` —
  `modules/configuration/application/use_cases/compute_next_publish_slot.py:212-217`.
- [x] `try/except (ZoneInfoNotFoundError, ValueError, TypeError)` con
  fallback a UTC y `logger.warning` —
  `compute_next_publish_slot.py:136-152`.
- [x] `hold_window_seconds` se aplica primero (`target = now + delta`)
  con clamp `[0, 86400]` —
  `compute_next_publish_slot.py:155-165, 227-237`.
- [x] `skip_weekends` desplaza al próximo lunes (o próximo día válido
  en `publish_days`) a `publish_window_start` local —
  `compute_next_publish_slot.py:264-278` + helper
  `_next_allowed_day_at_start` `168-192`.
- [x] `quiet_hours_enabled` defiere al próximo `publish_window_start`
  con soporte wrap-around — `compute_next_publish_slot.py:280-329` +
  helper `_is_inside_quiet_hours_window` `195-209`.
- [x] Si los 3 toggles están off → `None` —
  `compute_next_publish_slot.py:242-246` (early return).
- [x] Si shifts colapsan a `target == now` → `None` —
  `compute_next_publish_slot.py:331-335`.
- [x] Result final en UTC vía `target_local.astimezone(timezone.utc)` —
  `compute_next_publish_slot.py:332`.

### 2. Threading desde `regenerate_reel.py`

- [x] Carga `agency` con
  `uow.tenancy.agencies.get_by_id(normalized_agency_id)` —
  `modules/reels/application/use_cases/regenerate_reel.py:246`.
- [x] Método `get_by_id` existe en
  `modules/tenancy/infrastructure/agency_repository.py:40` con firma
  `(self, agency_id: str) -> Agency | None`. Verificado leyendo el
  archivo.
- [x] Forwardea `agency_timezone=agency.timezone or "UTC"` defensivo —
  `regenerate_reel.py:247-256`.
- [x] No toca otros bloques (defaults, social_templates) — diff acotado
  a las líneas 246-256.

### 3. Tests unitarios de `compute_next_publish_slot`

- [x] Casos pre-existentes recibieron `quiet_hours_enabled=True` para
  preservar cobertura — verificado en
  `tests/unit/configuration/test_compute_next_publish_slot.py:66-254`
  (los 26 tests legacy ahora pasan `quiet_hours_enabled=True` al helper
  `_rules`).
- [x] ≥9 casos nuevos (líneas 261-505), de hecho 13:
  - `test_all_toggles_off_returns_none_immediate_publish` (261)
  - `test_hold_window_only_returns_now_plus_delta_utc` (275)
  - `test_hold_window_capped_at_24h` (283)
  - `test_hold_window_exactly_24h_is_honoured` (291)
  - `test_quiet_hours_dublin_evening_defers_to_next_morning` (299)
  - `test_hold_window_plus_quiet_hours_dublin_BST` (326)
  - `test_skip_weekends_saturday_morning_dublin_advances_to_monday` (353)
  - `test_skip_weekends_friday_evening_plus_hold_lands_on_monday` (375)
  - `test_quiet_hours_enabled_with_empty_publish_days_returns_none` (403)
  - `test_invalid_agency_timezone_falls_back_to_utc_with_warning` (420,
    verifica WARNING vía `caplog`)
  - `test_dst_spring_forward_ambiguous_local_time_is_safe` (444)
  - `test_skip_weekends_with_empty_publish_days_returns_none` (472)
  - `test_quiet_hours_inside_window_at_local_noon_returns_none` (489)

### 4. Tests de `regenerate_reel`

- [x] `StubAgencies` expone `get_by_id(agency_id) -> SimpleNamespace`
  con `timezone` configurable — `tests/unit/reels/_uow_stubs.py:9-32`.
- [x] `test_regenerate_reel_forwards_agency_timezone_to_compute_slot`
  (`tests/unit/reels/test_regenerate_reel.py:409-450`) — patcha la
  función pura y asserta `kwargs == {"agency_timezone": "Europe/Dublin"}`
  + verifica que `agencies.calls[-1] == "agency-1"`.
- [x] `test_regenerate_reel_falls_back_to_utc_when_agency_timezone_missing`
  (`test_regenerate_reel.py:453-486`) — `agency.timezone=""` colapsa a
  `"UTC"`.
- [x] Fixture `_automation_rules` actualizada con los 3 campos de
  feature 13 (`test_regenerate_reel.py:30-51`).

### 5. Test integration nuevo

- [x] `test_approve_skip_weekends_quiet_hours_dublin_lands_on_monday_utc`
  (`tests/integration/reels/test_admin_reels_router.py:871-952`) configura
  agency Dublin (vía `seed_tenant` que defaultea `timezone="Europe/Dublin"`
  en `tests/support/postgres.py:184`), automation con `skip_weekends=True`
  + `quiet_hours_enabled=True` + ventana 09:00-18:00 Mon-Fri, mockea
  `datetime.now` para Sat 09:00 UTC, aprueba reel y verifica que
  `payload["scheduled_at"]` y `jobs.publish_context_json["scheduled_at"]`
  coinciden con Mon 09:00 Dublin → UTC.

### 6. Documentación

- [x] `docs/API.md:440-467` documenta la nueva semántica de `scheduled_at`
  bajo "feature 14 — timezone + hold/quiet/skip": orden de los shifts
  (hold → tz → skip_weekends → quiet_hours), fallback UTC con WARNING,
  y descripción de cómo `regenerate_reel` carga `get_by_id` y forwardea
  `agency_timezone`.
- [x] `docs/API.md:148-200` actualiza la sección de Automation con la
  documentación de los 3 campos de feature 13 y la transición de
  semántica.

### 7. Verificación ejecutada por el reviewer

- [x] `.venv/bin/python -m apps.api --check` exit 0:
  ```
  API READINESS REPORT
  RUNTIME READY: Yes
  PRODUCTION READY: No
  WORKSPACE: /opt/projects/4Reels-Backend
  DATABASE: postgresql+psycopg://postgres:***@127.0.0.1:5433/miapp_test
  DATABASE SCHEMA: public
  PYTHON: /opt/projects/4Reels-Backend/.venv/bin/python
  PYTHON VERSION: 3.12.12
  FFMPEG: /usr/bin/ffmpeg
  EXIT=0
  ```
- [x] `.venv/bin/python -m apps.worker --check` exit 0:
  ```
  Worker --check: database_url=postgresql+psycopg://postgres:***@127.0.0.1:5433/miapp_test schema=public
  Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
  EXIT=0
  ```
- [x] Subset crítico:
  `.venv/bin/python -m pytest tests/unit/configuration/test_compute_next_publish_slot.py tests/unit/reels/test_regenerate_reel.py tests/integration/reels/test_admin_reels_router.py -q`
  → `79 passed in 37.63s`.
- [x] Full suite (últimas 30 líneas):
  ```
  tests/unit/apps_api/test_agency_token.py::test_issue_and_decode_round_trip
  tests/unit/apps_api/test_agency_token.py::test_decode_raises_expired_when_token_past_exp
  tests/unit/apps_api/test_agency_token.py::test_decode_raises_invalid_when_signature_does_not_match
  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_missing_required_claims
  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_with_non_agency_scope
  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_with_wrong_issuer
  tests/unit/apps_api/test_agency_token.py::test_decode_requires_non_empty_token_and_secret
    /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:147: InsecureKeyLengthWarning: The HMAC key is 11 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
      return self._jws.encode(

  tests/unit/apps_api/test_agency_token.py::test_issue_and_decode_round_trip
  tests/unit/apps_api/test_agency_token.py::test_decode_raises_expired_when_token_past_exp
  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_missing_required_claims
  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_with_non_agency_scope
  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_token_with_wrong_issuer
    /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:365: InsecureKeyLengthWarning: The HMAC key is 11 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
      decoded = self.decode_complete(

  tests/unit/apps_api/test_agency_token.py::test_decode_raises_invalid_when_signature_does_not_match
    /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:365: InsecureKeyLengthWarning: The HMAC key is 12 bytes long, which is below the minimum recommended length of 32 bytes for SHA256. See RFC 7518 Section 3.2.
      decoded = self.decode_complete(

  tests/unit/apps_api/test_agency_token.py::test_decode_rejects_tokens_signed_with_different_algorithm
    /opt/projects/4Reels-Backend/.venv/lib64/python3.12/site-packages/jwt/api_jwt.py:147: InsecureKeyLengthWarning: The HMAC key is 11 bytes long, which is below the minimum recommended length of 64 bytes for SHA512. See RFC 7518 Section 3.2.
      return self._jws.encode(

  -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
  =========================== short test summary info ============================
  FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
  FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
  FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
  3 failed, 640 passed, 14 warnings in 248.42s (0:04:08)
  ```
- [x] Los 3 fallos coinciden con los pre-existentes documentados en
  `progress/review_13_automation_hold_quiet_skip.md` (Windows path en
  `FRONTEND_REPO_ROOT` y `test_health_endpoints` con
  `configured_worker_count` no resueltos). Sin nuevos fallos.
- [x] El delta de tests pasados (640 vs 632 reportados por el
  implementer) corresponde a los +8 tests añadidos por la sesión
  paralela de feature 16 entre la corrida del implementer y la del
  reviewer. El delta atribuible a feature 14 (632 - 583 = +49) es
  consistente: 13 nuevos casos en `test_compute_next_publish_slot.py`
  (de 26 a 39 collected), 2 en `test_regenerate_reel.py`, 1 integration,
  y los tests legacy migrados que ahora cuentan con `quiet_hours_enabled=True`
  no cambian su número pero sí su shape.

### 8. Scope

- [x] `git diff --name-only HEAD` filtrado a archivos atribuibles a
  feature 14 (timestamps en bloque 14:24-14:30 y la rama 14:37:33 que
  matchea la lista del implementer):
  ```
  M modules/configuration/application/use_cases/compute_next_publish_slot.py  (untracked, 14:24:29)
  M modules/reels/application/use_cases/regenerate_reel.py        (14:37:33)
  M tests/unit/configuration/test_compute_next_publish_slot.py    (untracked, 14:26:28)
  M tests/unit/reels/_uow_stubs.py                                (14:37:33)
  M tests/unit/reels/test_regenerate_reel.py                      (14:37:33)
  M tests/integration/reels/_client.py                            (14:37:33)
  M tests/integration/reels/test_admin_reels_router.py            (14:37:33)
  M docs/API.md                                                   (14:37:33)
  ```
  Los demás archivos del `git status` (catalog/**, rendering/**, render
  template router/repo/payload, ingest_property_into_reel.py) son de la
  sesión paralela de feature 16, NO modificados por feature 14:
  verificado por mtime fuera de la ventana del implementer y por
  contenido del diff (esos archivos no añaden imports/llamadas de
  `compute_next_publish_slot` ni de `agency_timezone`).
- [x] Status de feature 14 sigue `in_progress` en `feature_list.json:403`.
  NO marcado `done`.
- [x] `progress/current.md` no tocado en contenido por feature 14
  (sigue describiendo feature 16 — la sesión paralela lo escribe).
  Aunque su mtime sea 14:37:33, el diff vs HEAD muestra el bloque de
  feature 16 ya escrito antes de la sesión 14.
- [x] No hay migraciones nuevas en
  `alembic/versions/` con mtime en la ventana de feature 14 (verificado
  con `find -newermt "2026-05-13 14:24:00" -path '*/alembic/*'` → 0
  resultados nuevos). Schema="No" se respeta.

## Notas opcionales (no bloqueantes)

1. **`logger.warning` sin `traceId`.** El use case puro no tiene acceso
   al correlation ID. El implementer lo documenta como decisión
   deliberada en `progress/impl_14_*.md` §Caveats. Si en el futuro se
   quiere el `traceId`, debería emitirlo el caller (`regenerate_reel`)
   en vez del use case puro.
2. **DST gap no pinea valor exacto.** El test
   `test_dst_spring_forward_ambiguous_local_time_is_safe` solo asegura
   "no crashea + result UTC válido". Acoplar al comportamiento exacto
   de `ZoneInfo` en CPython sería frágil. Aceptable.
3. **Tests legacy migrados a `quiet_hours_enabled=True`.** Esta es la
   única forma de preservar la cobertura semántica de feature 11
   ahora que el window dejó de ser "horas permitidas por defecto".
   Documentado en `docs/API.md:180-189`.
4. **Migración de `_uow_stubs.py` (StubAgencies).** La clase nueva
   reemplaza al stub pre-feature-14 (que no exponía `timezone` ni
   `get_by_id`). Los tests previos siguen verdes porque
   `build_uow(agency_present=..., agency_timezone=...)` mantiene los
   kwargs antiguos como wrappers.
