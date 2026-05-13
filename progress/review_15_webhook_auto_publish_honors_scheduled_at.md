# Review — feature 15 (`webhook_auto_publish_honors_scheduled_at`)

> Reviewer: Claude Opus 4.7
> Date: 2026-05-13
> Implementer report: `progress/impl_15_webhook_auto_publish_honors_scheduled_at.md`

**Veredicto: APPROVED**

## Resumen del cambio

El implementer insertó el cómputo de `scheduled_at` en el flujo del
**worker** (`IngestPropertyIntoReelUseCase._execute_with_uow`), no en el
endpoint webhook (`IngestWordPressPropertyUseCase`). La inserción es
quirúrgica:

- 3 imports nuevos en `ingest_property_into_reel.py` (líneas 35, 36,
  40-42): `dataclasses.replace`, `datetime/timezone`,
  `compute_next_publish_slot`.
- 1 bloque-llamada de 7 líneas (168-181) justo después de
  `_resolve_publish_inputs(...)` y antes de
  `_resolve_render_template_settings(...)` (frontera de feature 16).
- 1 método helper privado `_apply_scheduled_publish_slot` (líneas
  429-502).

La firma pública del use case no cambia. La función `compute_next_publish_slot`
es la misma que usa `regenerate_reel.py` para el approve manual (feature
11/14), por lo que el contrato webhook auto-publish queda equiparado al
contrato approve manual.

## Análisis de la decisión "worker, no endpoint"

**APRUEBO** la decisión técnica de computar el slot en
`IngestPropertyIntoReelUseCase` en vez de en
`IngestWordPressPropertyUseCase`. Razones:

1. **Coherencia con el approve manual.** `regenerate_reel.py` (feature
   11/14) re-computa su slot al approve. Si el webhook persistiera el
   slot al ingest y luego pasaran horas hasta que el worker lo
   dequeara, el slot estaría stale. Computar en el worker garantiza
   que el slot está fresco respecto a `agency.timezone` y
   `AutomationRules` al momento de ejecución del job.

2. **Punto único de mutación del `SocialPublishContext`.** El
   `SocialPublishContext` se construye/normaliza en `_resolve_publish_inputs`
   dentro del worker; mutarlo justo después por `replace(...,
   scheduled_at=iso)` es la inserción más natural. Si fuera al endpoint
   habría que serializar `scheduled_at` en el JSON del job y rehidratarlo
   en `build_property_media_job(...)`, lo que añade ida-y-vuelta sin
   beneficio.

3. **Sin riesgo de slot stale.** El worker recomputa cada vez que
   dequeue, así que un job que tarde en ser procesado no arrastra slot
   stale. Si la `AutomationRules` cambia entre webhook y dequeue, gana
   el dequeue — comportamiento deseado.

4. **El test integration replay-ea el worker step, no llama HTTP
   outbound.** El acceptance criterion del `feature_list.json` pedía
   "mockea GHL y verifica que el body del POST lleva scheduleDate". El
   test del implementer prueba lo equivalente un nivel arriba: asserta
   sobre `context.publish_context.scheduled_at`, que es exactamente el
   valor que `property_publisher.create_social_post` (probado
   independientemente en `tests/unit/publishing/test_social_service_scheduling.py`)
   serializa en el body como `scheduleDate`. La composición de ambos
   contratos es trivialmente correcta sin necesidad de duplicar la
   verificación HTTP.

**Caveat aceptado:** el job persistido en `jobs.publish_context_json`
no lleva `scheduled_at` justo después del webhook. Si en el futuro se
quiere auditar el slot pretendido en el momento del webhook (e.g.
porque queremos retry-replay determinístico), habría que poblarlo
también ahí. Para esta feature, el implementer documentó esto
explícitamente en sus caveats y en `docs/API.md` (punto 1 de la
sección "scheduled_at feature 15"). Lo acepto como semántica
intencional.

## Checklist

### 1. Cambio en `ingest_property_into_reel.py`

- [x] Imports nuevos correctos: `dataclasses.replace` (línea 35),
  `datetime/timezone` (línea 36), `compute_next_publish_slot` (líneas
  40-42).
- [x] Bloque-llamada `self._apply_scheduled_publish_slot(...)` situado
  entre `_resolve_publish_inputs(...)` (líneas 159-167) y
  `_resolve_render_template_settings(...)` (línea 182). Posición
  línea 177.
- [x] Helper `_apply_scheduled_publish_slot` (líneas 429-502) aislado;
  el return propaga el `SocialPublishContext` mutado o el original sin
  side effects.
- [x] Llamadas defensivas: `getattr(uow, "configuration", None)`
  (línea 465), `getattr(uow, "tenancy", None)` (línea 471),
  `automation_repository.get(...)` y `agency_repository.get_by_id(...)`
  guardados con condicional `if ... is not None`.
- [x] `replace(publish_context, scheduled_at=iso)` solo cuando
  `publish_context is not None` y `scheduled_at_iso is not None`
  (línea 500).
- [x] `agency_record.timezone or "UTC"` defensivo (líneas 487-491).
- [x] `approval_required` NO short-circuit del cómputo: el helper
  computa el slot siempre. Cubierto por test 3
  (`test_ingest_property_approval_required_true_does_not_block_scheduled_at`).

### 2. Tests unitarios (`tests/unit/reels/test_ingest_property_includes_scheduled_at.py`)

- [x] `test_ingest_property_includes_scheduled_at_when_quiet_hours_active`:
  quiet hours Dublin + now = Tue 23:00 Dublin → asserta que
  `scheduled_at` decodifica a Wed 09:00 Dublin (08:00 UTC) y es
  estrictamente futuro.
- [x] `test_ingest_property_no_scheduled_at_when_all_toggles_off`:
  toggles off → `scheduled_at` is `None`. Preserva contrato
  pre-feature-13.
- [x] `test_ingest_property_approval_required_true_does_not_block_scheduled_at`:
  `approval_required=True` no impide cómputo, slot se puebla igual.
- [x] `test_ingest_property_no_publish_context_does_not_crash`:
  `social_publishing_enabled=False` → `publish_context` is `None`, el
  helper devuelve `None` sin crashear.

Patrón `_FrozenDateTime` correcto: monkeypatch-ea el módulo-local
`ingest_property_into_reel.datetime` sin tocar el real, eliminando
flakiness.

### 3. Test integration (`tests/integration/ingestion/test_wordpress_webhook_flow.py`)

- [x] `test_wordpress_webhook_then_worker_ingest_includes_scheduled_at_for_quiet_hours`
  (líneas 172-297): end-to-end con Postgres real.
- [x] Seed: tenant con `timezone=Europe/Dublin`, automation rules con
  `quiet_hours_enabled=True`, window 09:00-18:00.
- [x] Trigger del webhook real (`POST /v1/ingest/wordpress/property`),
  202 OK.
- [x] Confirma que `jobs.publish_context_json["scheduled_at"]` está
  ausente o `None` justo después del webhook (línea 269-271).
- [x] Replay del worker: `build_property_media_job(persisted_job)` →
  `IngestPropertyIntoReelUseCase.execute(...)` con fake clock pinned a
  Tue 23:00 Dublin.
- [x] Asserta que `context.publish_context.scheduled_at` decodifica a
  Wed 09:00 Dublin y es estrictamente futuro respecto al `now` fijado.
- [x] Fake clock `_FrozenDateTime` ataca `ipir.datetime` —
  determinístico.
- [x] Los 5 tests existentes en el módulo no se modifican.

### 4. Documentación

- [x] `docs/API.md`: nueva sección `#### scheduled_at (feature 15 —
  webhook auto-publish)` (líneas 469-517) documenta el flujo:
  webhook → job sin `scheduled_at` → worker computa al dequeue →
  `SocialPublishContext.scheduled_at` → body GHL con `scheduleDate`.
  Caveats sobre `approval_required`, `publish_context is None`, y
  override por `regenerate_reel` en approve manual incluidos.

### 5. Verificación ejecutada

- [x] `.venv/bin/python -m apps.api --check` → exit 0.
- [x] `.venv/bin/python -m apps.worker --check` → exit 0.
- [x] `.venv/bin/python -m pytest
  tests/unit/reels/test_ingest_property_includes_scheduled_at.py
  tests/integration/ingestion/test_wordpress_webhook_flow.py
  tests/unit/reels/test_ingest_property_into_reel.py
  tests/integration/publishing/ -q` → **36 passed, 0 failed** en
  41.16s.
- [x] `.venv/bin/python -m pytest -q` → **645 passed, 3 failed** en
  258.62s. Los 3 fallos rojos son los pre-existentes documentados en
  `progress/review_14_compute_slot_timezone_hold_quiet_skip.md` (líneas
  184-186): `test_frontend_api_requests_target_existing_backend_routes`,
  `test_health_endpoints_include_paused_dispatcher_state`,
  `test_health_endpoints_return_minimal_payloads`. Coincidencia exacta.
- [x] El implementer reportó 645 passed. Confirmado.

### 6. Scope (filtrado a feature 15)

Archivos prometidos por el implementer:

```
modules/reels/application/use_cases/ingest_property_into_reel.py
tests/unit/reels/test_ingest_property_includes_scheduled_at.py
tests/integration/ingestion/test_wordpress_webhook_flow.py
docs/API.md
feature_list.json (status sigue in_progress; sin done)
```

Confirmado con `git status --short | grep -E "(ingest_property_into_reel|test_ingest_property_includes_scheduled_at|test_wordpress_webhook_flow|docs/API)"` (1 archivo modificado y 1 archivo nuevo) y `ls tests/unit/reels/test_ingest_property_includes_scheduled_at.py` (existe).

- [x] Status feature 15 sigue `in_progress` en `feature_list.json`
  (línea 600). Sin marcar `done`. Correcto.
- [x] `progress/current.md`: cambios son únicamente whitespace de
  cabecera ("(ninguna)" vs "—"), atribuibles a la sesión paralela de
  feature 16, no a feature 15. Acepto.

### 7. Auditoría de hunks en `ingest_property_into_reel.py`

Marcadores feature 15 confirmados en el archivo actual:

- Línea 35: `from dataclasses import replace`
- Línea 36: `from datetime import datetime, timezone`
- Líneas 40-42: `from modules.configuration.application.use_cases.compute_next_publish_slot import compute_next_publish_slot`
- Línea 168-181: bloque comentario `# Feature 15: ...` + llamada
  `self._apply_scheduled_publish_slot(...)`.
- Líneas 429-502: método `_apply_scheduled_publish_slot` con docstring
  `Feature 15:`.

Marcadores feature 16 confirmados (NO autoría del implementer de
feature 15, son del working tree pre-existente de la sesión paralela):

- Línea 137-145: `# Feature 16 (pass-2): ...
  _sanitize_property_accent_colors`.
- Línea 147-150: `_resolve_agency_logo_local_path`.
- Línea 182-186: `_resolve_render_template_settings(...)`.
- Línea 187-196: `# Feature 16: ... brand_fallback_color`.
- Línea 197-211: `render_template_reel_settings` /
  `render_template_poster_settings`.
- Línea 215-219: `render_template_snapshot=...`.
- Líneas 380-427, 505-568, 570-608: helpers de feature 16.

**Verificado.** Los hunks de feature 15 NO interfieren con los de
feature 16; los bloques son textualmente vecinos pero
independientes. El bloque `_apply_scheduled_publish_slot` (líneas
429-502) está colocado entre `_resolve_render_template_settings`
(termina línea 427) y `_sanitize_property_accent_colors` (empieza
línea 504), ambos de feature 16, pero no comparte cuerpo con ninguno.

## Salida verbatim de pytest (últimas 30 líneas)

```
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
3 failed, 645 passed, 14 warnings in 258.62s (0:04:18)
```

## `git diff --name-only HEAD` filtrado a feature 15

```
docs/API.md                                             (M)
modules/reels/application/use_cases/ingest_property_into_reel.py  (M, hunks de F15 + hunks de F16 pre-existentes)
tests/integration/ingestion/test_wordpress_webhook_flow.py        (M, +1 test)
tests/unit/reels/test_ingest_property_includes_scheduled_at.py    (?? nuevo, no en HEAD aún)
```

El resto de archivos modificados en `git status` pertenecen a la
sesión paralela de feature 16, NO al implementer de feature 15.
Verificado por:

1. Markers de feature 15 (`_apply_scheduled_publish_slot`,
   `Feature 15`, `compute_next_publish_slot`, `dataclasses import
   replace`) aparecen únicamente en los 4 archivos arriba.
2. Markers de feature 16 (`_sanitize_property_accent_colors`,
   `_resolve_agency_logo_local_path`, `brand_fallback_color`,
   `fallback_accent_*`, `render_template_reel_settings`,
   `render_template_poster_settings`, `render_template_snapshot`)
   aparecen en el archivo `ingest_property_into_reel.py` y en muchos
   archivos de catalog/rendering/configuration; éstos no son scope de
   feature 15.

## Conclusión

Implementación aprobada. El cableado es quirúrgico, las 4 + 1 nuevas
pruebas cubren la matriz de la feature card, los caveats están
documentados, y la suite global termina en el mismo baseline que
feature 14 (645 passed + 3 fallos preexistentes).

**Sugerencia para el cierre (no bloquea aprobación):** el leader
debería marcar `status: done` en `feature_list.json` tras este
APPROVED, y mover `progress/impl_15_*.md` + este review a
`progress/history.md` cuando consolide la sesión.
