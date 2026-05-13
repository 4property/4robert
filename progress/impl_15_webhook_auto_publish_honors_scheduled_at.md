# Feature 15 — `webhook_auto_publish_honors_scheduled_at`

> Implementer: Claude Opus 4.7
> Started: 2026-05-13
> Status: review pendiente
> Toca schema?: No (sin migración alembic)

## Resumen

Cableado del cómputo de `scheduled_at` para el flujo webhook
auto-publish, equiparando su contrato al del approve manual cerrado en
feature 11/14. La lógica vive en `IngestPropertyIntoReelUseCase` (el
worker), no en el endpoint webhook (`IngestWordPressPropertyUseCase`):
cuando el orquestador llama `IngestPropertyIntoReelUseCase.execute(...)`
sobre el job dequeued, ahora carga
`uow.configuration.automation.get(agency_id)` +
`uow.tenancy.agencies.get_by_id(agency_id).timezone` y delega en el use
case puro `compute_next_publish_slot(...)`. Si el slot no es `None`, se
hace `dataclasses.replace(publish_context, scheduled_at=iso)` para que
el `SocialPublishContext` que viaja hasta el publisher de GHL emita
`scheduleDate` + `status:"scheduled"`. Si el slot es `None` (toggles
off, sin rules, o shifts cancelan), el `publish_context` queda intacto
y el contrato pre-feature-15 ("publish immediately") se preserva.

El cambio es **estrictamente aditivo** sobre `ingest_property_into_reel.py`:
sólo se introducen 3 imports nuevos, 1 bloque-llamada de 7 líneas justo
después de `_resolve_publish_inputs(...)`, y 1 método helper privado
(`_apply_scheduled_publish_slot`). Cero cambios en
`_ingest_property_planning.py`, `_resolve_publish_inputs`, en los
bloques de feature 16 (`_sanitize_property_accent_colors`,
`_resolve_agency_logo_local_path`, `_resolve_render_template_settings`,
`_resolve_brand_primary_color`, merge de
`render_template_reel_settings/poster_settings`, `_build_content_snapshot`
con `render_template_snapshot`), ni en `compute_next_publish_slot.py`.

## Archivos tocados

| Archivo | Tipo | Cambio |
|---|---|---|
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | use case | Nuevos imports (`dataclasses.replace`, `datetime`/`timezone`, `compute_next_publish_slot`). Nueva llamada `self._apply_scheduled_publish_slot(...)` tras `_resolve_publish_inputs(...)`. Nuevo método helper `_apply_scheduled_publish_slot` (puro, sin side effects fuera del UoW que ya recibe). |
| `tests/unit/reels/test_ingest_property_includes_scheduled_at.py` | test (nuevo) | 4 tests unit cubriendo la matriz de la feature card. |
| `tests/integration/ingestion/test_wordpress_webhook_flow.py` | test (extendido) | 1 escenario nuevo end-to-end: webhook → job persistido → worker replay → `publish_context.scheduled_at` poblado. No toca los 5 tests existentes. |
| `docs/API.md` | docs | Nueva sección `#### scheduled_at (feature 15 — webhook auto-publish)` documentando el contrato. |

## Diff conceptual

### `ingest_property_into_reel.py` — imports añadidos

```python
from dataclasses import replace
from datetime import datetime, timezone

from modules.configuration.application.use_cases.compute_next_publish_slot import (
    compute_next_publish_slot,
)
```

### `ingest_property_into_reel.py` — bloque insertado en `_execute_with_uow` (línea ~168)

```python
# Feature 15: compute the scheduled publish slot for the webhook
# auto-publish flow. compute_next_publish_slot returns None for
# "publish immediately"; otherwise the use case forwards the slot down
# the SocialPublishContext so the downstream GHL POST emits
# scheduleDate and status='scheduled'. The approval_required=True case
# still parks the reel pending the manual approve without consulting
# this slot — regenerate_reel.py (feature 11/14) computes its own slot
# at approve time.
publish_context = self._apply_scheduled_publish_slot(
    uow=uow,
    agency_id=job.tenant.agency_id,
    publish_context=publish_context,
)
```

Inserción quirúrgica entre `_resolve_publish_inputs(...)` (deja de
ejecutarse en línea 159..167) y
`self._resolve_render_template_settings(...)` (línea 182).

### `ingest_property_into_reel.py` — método helper nuevo

```python
def _apply_scheduled_publish_slot(
    self,
    *,
    uow: DatabaseUnitOfWork,
    agency_id: str,
    publish_context: SocialPublishContext | None,
) -> SocialPublishContext | None:
    """Compute scheduled_at and stamp it on publish_context.

    ... (see file for full docstring) ...
    """
    configuration_module = getattr(uow, "configuration", None)
    automation_repository = (
        getattr(configuration_module, "automation", None)
        if configuration_module is not None
        else None
    )
    tenancy_module = getattr(uow, "tenancy", None)
    agency_repository = (
        getattr(tenancy_module, "agencies", None)
        if tenancy_module is not None
        else None
    )
    automation_rules = (
        automation_repository.get(agency_id)
        if automation_repository is not None
        else None
    )
    agency_record = (
        agency_repository.get_by_id(agency_id)
        if agency_repository is not None
        else None
    )
    agency_timezone = (
        agency_record.timezone
        if agency_record is not None and getattr(agency_record, "timezone", "")
        else "UTC"
    )
    scheduled_slot = compute_next_publish_slot(
        automation_rules,
        datetime.now(timezone.utc),
        agency_timezone=agency_timezone,
    )
    scheduled_at_iso: str | None = (
        scheduled_slot.isoformat() if scheduled_slot is not None else None
    )
    if publish_context is not None and scheduled_at_iso is not None:
        return replace(publish_context, scheduled_at=scheduled_at_iso)
    return publish_context
```

El método se coloca **entre** `_resolve_render_template_settings`
(método cerrado por feature 16) y `_sanitize_property_accent_colors`
(método estático de feature 16). No comparte cuerpo con ninguno; sólo
es vecino textual.

## Acreditación: no toqué scope de feature 16

`git diff HEAD modules/reels/application/use_cases/ingest_property_into_reel.py`
muestra una mezcla de:

- Cambios de feature 16 ya presentes en el working tree antes de mi
  sesión (esta es la rama `ghl` con feature 16 en marcha en otra
  sesión).
- Mis 3 grupos de cambios de feature 15 (imports + llamada + helper).

Marcadores buscables que demuestran mi alcance:

```bash
$ git diff HEAD modules/reels/application/use_cases/ingest_property_into_reel.py \
    | grep -E "Feature 15|_apply_scheduled_publish_slot|compute_next_publish_slot|dataclasses import replace"
+from dataclasses import replace
+from datetime import datetime, timezone
+from modules.configuration.application.use_cases.compute_next_publish_slot import (
+    compute_next_publish_slot,
+        # Feature 15: compute the scheduled publish slot for the webhook
+        # auto-publish flow. ``compute_next_publish_slot`` returns ``None``
+        publish_context = self._apply_scheduled_publish_slot(
+    def _apply_scheduled_publish_slot(
+        Feature 15: the webhook auto-publish flow must honour the
+        :func:`compute_next_publish_slot` use case.
+        scheduled_slot = compute_next_publish_slot(
```

Cero hits en mis cambios para los marcadores que identifican el scope
de feature 16: `_sanitize_property_accent_colors`,
`_resolve_agency_logo_local_path`, `brand_fallback_color`,
`fallback_accent_*`, `render_template_reel_settings`,
`render_template_poster_settings`, `render_template_snapshot`. (Esos
strings sí están en el diff, pero pertenecen a hunks que ya estaban en
el working tree cuando arranqué.)

## Tests nuevos

### Unit (`tests/unit/reels/test_ingest_property_includes_scheduled_at.py`)

1. `test_ingest_property_includes_scheduled_at_when_quiet_hours_active` —
   quiet hours 09:00–18:00 Europe/Dublin, now = 23:00 Dublin (Tue
   2026-05-12), espera `scheduled_at` apuntando al próximo 09:00 Dublin
   (Wed 2026-05-13 = 08:00 UTC).
2. `test_ingest_property_no_scheduled_at_when_all_toggles_off` — los 3
   toggles off → `scheduled_at` queda `None` (contrato pre-feature-13).
3. `test_ingest_property_approval_required_true_does_not_block_scheduled_at` —
   `approval_required=True` en `AutomationRules` no
   short-circuit el cómputo: `scheduled_at` se puebla igual; el
   downstream parking es decisión del orquestador/publisher (lee
   `publish_context.approval_required`, que es otro campo).
4. `test_ingest_property_no_publish_context_does_not_crash` —
   `social_publishing_enabled=False` → `publish_context` resuelve a
   `None` y el helper no hace `replace(None, ...)`; el ingest termina
   limpio.

Los 4 usan un patrón `_FrozenDateTime` que monkeypatch-ea
`ingest_property_into_reel.datetime` para fijar el reloj sin tocar el
real (evitando flakiness).

### Integration (`tests/integration/ingestion/test_wordpress_webhook_flow.py`)

5. `test_wordpress_webhook_then_worker_ingest_includes_scheduled_at_for_quiet_hours` —
   End-to-end con Postgres real:
   - Seed tenant con `timezone="Europe/Dublin"` (default de
     `seed_tenant`) + `seed_automation_rules(quiet_hours_enabled=True,
     publish_window_start="09:00", publish_window_end="18:00")`.
   - Trigger `POST /v1/ingest/wordpress/property`.
   - Confirma que `jobs.publish_context_json["scheduled_at"]` **no**
     existe / es `None` en el row persistido (semántica deliberada:
     feature 15 difiere el cálculo al worker, no al endpoint).
   - Replay del worker: `build_property_media_job(persisted_job)` →
     `IngestPropertyIntoReelUseCase.execute(...)` con el reloj
     monkeypatch-eado al Tue 23:00 Dublin.
   - Asserta que el `context.publish_context.scheduled_at` resultante
     decodifica al Wed 09:00 Dublin y es estrictamente futuro respecto
     al `now` fijado.

## Verificación

### `python -m apps.api --check`

```
PYTHON VERSION: 3.12.12
FFMPEG: /usr/bin/ffmpeg
```

Exit 0.

### `python -m apps.worker --check`

```
INFO     Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
```

Exit 0.

### `pytest -q` subset crítico

```
.venv/bin/python -m pytest \
  tests/unit/reels/test_ingest_property_includes_scheduled_at.py \
  tests/integration/ingestion/test_wordpress_webhook_flow.py \
  tests/unit/reels/test_ingest_property_into_reel.py \
  tests/integration/publishing/ -q
```

Resultado: **36 passed**, 0 failed, ~40 s.

### `pytest -q` suite completa

Últimas líneas:

```
=========================== short test summary info ============================
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 645 passed, 14 warnings in 251.41s (0:04:11)
```

Baseline feature 14 = 640 passed. Ahora 645 passed → **+5 tests
nuevos** (4 unit + 1 integration). Los 3 fallos rojos son
preexistentes y documentados en `progress/review_14_*.md` (no
relacionados con esta feature; involucran
`configured_worker_count` en `/health`).

## Caveats / decisiones documentadas

- **Dónde se computa el slot.** La feature card original
  (`feature_list.json` id 15) pide "Test integration del webhook ...
  mockea GHL y verifica que el body del POST lleva scheduleDate". La
  forma natural de cumplirlo era extender
  `IngestWordPressPropertyUseCase` (HTTP endpoint, persiste el job).
  Pero el prompt del leader es explícito: sólo tocar
  `ingest_property_into_reel.py` (worker). Resolví la tensión así: el
  webhook persiste el job **sin** `scheduled_at`; el worker lo computa
  cuando ejecuta `IngestPropertyIntoReelUseCase` y muta el runtime
  `SocialPublishContext` vía `dataclasses.replace`. El downstream
  `property_publisher.create_social_post` lee
  `context.publish_context.scheduled_at` → llega correctamente al body
  de GHL. El test integration **replay-ea el worker step** sobre el
  job persistido (no mockea GHL, no llama HTTP outbound) y asserta
  sobre el `PropertyContext` resultante.

- **`approval_required=True` + slot computado.** Decisión consciente:
  cuando `AutomationRules.approval_required=True`, el slot se computa
  igual y se sella en el `publish_context`. Razones:
  1. El cómputo es puro y barato (sin I/O extra: la consulta a
     `agencies` y `automation` ya se hace).
  2. El campo `approval_required` que decide si el reel se parka NO es
     este (es `publish_context.approval_required`, set por el job/webhook
     upstream, no por las rules).
  3. Cuando el approve manual fire, `regenerate_reel.py` (feature
     11/14) re-computa su propio slot, así que la stamp de feature 15
     se sobreescribe — no hay riesgo de "stale slot".

- **`publish_context is None`.** Es un caso legítimo
  (`social_publishing_enabled=False`). El helper devuelve `None` sin
  tocarlo; el `dataclasses.replace(None, ...)` que crashearía nunca se
  ejecuta. Cubierto por test 4.

- **Conflicto futuro con feature 16.** El método helper
  `_apply_scheduled_publish_slot` vive **entre**
  `_resolve_render_template_settings` y
  `_sanitize_property_accent_colors`. Si feature 16 reordena/refactoriza
  estos helpers, hará falta un rebase trivial (mover mi método al
  lugar nuevo). El bloque-llamada en `_execute_with_uow` (línea ~168)
  está fijado relativamente al final de `_resolve_publish_inputs(...)`
  — feature 16 no toca esa zona del flujo principal.

- **No hay tests sobre `jobs.publish_context_json["scheduled_at"]`
  poblado a tiempo de webhook.** El test integration explícitamente
  verifica lo contrario: el row persistido en `jobs` **no** lleva
  `scheduled_at` justo después del webhook (es el worker quien
  computa). Esto es la semántica intencional de la feature según el
  prompt del leader.

- **No tocado:** `_ingest_property_planning.py`, `_resolve_publish_inputs`,
  `_uow_stubs.py`, `compute_next_publish_slot.py`, ninguna migración
  alembic, ningún router transport, ningún use case fuera de
  `ingest_property_into_reel.py`. La firma pública de
  `IngestPropertyIntoReelUseCase` y todos sus contratos pre-existentes
  se mantienen.
