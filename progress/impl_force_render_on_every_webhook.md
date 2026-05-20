# Implementación — force_render_on_every_webhook

- **Fecha:** 2026-05-19
- **Agente:** Claude (rol implementer)
- **Tipo:** Cambio de política deliberado (no es bug "accidental", es contrato nuevo).
- **Toca schema:** No.
- **Migración Alembic:** No.

## 1. Política nueva

Cada webhook de ingest dispara render incondicionalmente. El use case
`IngestPropertyIntoReelUseCase.execute` ya no consulta el
`content_fingerprint` ni `_has_local_artifacts` para decidir si rendea —
siempre rendea. El fast-path `EXISTING MEDIA PUBLISH` del orquestador
(`modules/reels/application/orchestrator.py:160-180`) queda **muerto
para el flujo de ingest**, porque el branch `if not context.requires_render`
nunca se cumple desde un ingest.

### Por qué

El `content_snapshot` (y por tanto el `content_fingerprint`) no incluye
los brand/subtitle overrides (`font_family`, accent colors,
subtítulos). Cuando una agencia cambiaba su fuente brand pero la
property era idéntica, el fingerprint no se movía → `requires_render`
quedaba en `False` → el orquestador reutilizaba el MP4 viejo via
`EXISTING MEDIA PUBLISH` → se publicaba con la fuente antigua. El
usuario prefiere pagar el coste de un render por webhook a tener
artefactos stale.

### Qué NO se ve afectado

- **`RegenerateReelUseCase`** (feature 40 / `regenerate_reel.py`): es
  otro use case con otro endpoint manual. Sigue funcionando como
  estaba — no consume `IngestPropertyIntoReelUseCase`.
- **`PersistLocalArtifactsUseCase.execute_existing`** y
  **`PublishReelUseCase.execute_existing`**: siguen existiendo como
  primitivas, no las usa el orquestador desde ingest (sólo via la rama
  `if not context.requires_render` que es ahora inalcanzable desde
  ingest). El leader puede decidir más adelante si valen la pena.
- **`is_noop`** sigue calculándose. Con `requires_render=True`
  permanente, `is_noop` solo será `True` cuando además
  `requires_external_publish=False` y `has_local_artifacts=True` — pero
  como `is_noop = not requires_render and ...` y `requires_render=True`
  siempre, `is_noop` queda permanentemente `False` desde ingest. Es el
  comportamiento deseado.
- **Logs**: el cálculo de `content_changed` se mantiene vivo para que
  el bloque de log `Content changed: yes/no` (línea 478) siga teniendo
  sentido. `has_local_artifacts` también se mantiene porque alimenta
  otros cómputos del bloque y `_should_prepare_assets` (vía
  `requires_asset_preparation`).

## 2. Cambios de código

### `modules/reels/application/use_cases/ingest_property_into_reel.py`

Sustituida la línea 422 (`requires_render = content_changed or not
has_local_artifacts`) por `requires_render = True` con un bloque de
comentario explicando la política y la fecha. El cálculo previo de
`existing_snapshot_text` + `content_changed` se conserva intacto
porque sigue alimentando el log.

## 3. Tests modificados

### `tests/unit/reels/test_ingest_property_into_reel.py`

- **Renombrado**: `test_execute_is_noop_when_state_unchanged_and_artifacts_present`
  → `test_execute_always_requires_render_even_when_state_unchanged`.
- **Asserciones invertidas**: ahora exige `requires_render is True`,
  `is_noop is False`, y que `states.saved` tenga 1 elemento (porque la
  rama `if not is_noop` siempre se ejecuta). Añadido docstring con el
  motivo del cambio.

El otro test del archivo (`test_execute_persists_state_and_returns_context_for_fresh_property`,
línea 138/140) ya esperaba `requires_render is True` / `is_noop is False`
para una ingestión fresh — no requiere cambios.

### Tests no tocados (revisados manualmente)

- `tests/integration/reels/test_ingest_property_into_reel_flow.py:73-74`:
  ejecuta `execute` una sola vez (fresh ingest) y ya esperaba
  `requires_render is True`. Sigue válido.
- `tests/unit/reels/test_persist_local_artifacts.py::test_execute_existing_*`:
  esos tests cubren la API `execute_existing` de
  `PersistLocalArtifactsUseCase` con `requires_render=False` como
  parámetro de **input** al `_build_context` helper, no como output del
  ingest. No tocan el flujo modificado. Siguen válidos.
- `tests/unit/reels/test_publish_reel.py::test_execute_existing_*` y
  línea 151 ("existing media required"): análogo, validan la primitiva
  `PublishReelUseCase.execute_existing` directamente sin pasar por
  ingest. Siguen válidos.
- `tests/integration/reels/test_*` que pasan `requires_render=True` a
  helpers de construcción de contexto (`test_reel_slides_override.py`,
  `test_auto_subtitles_snapshot.py`, `test_reel_subtitles_override.py`,
  `test_prepare_reel_assets.py`, `test_publish_reel.py`,
  `test_persist_local_artifacts.py:100-132`): siguen siendo válidos —
  son inputs para construir contextos sintéticos en tests de otros use
  cases, no asserciones sobre el output del ingest.

## 4. Test focal nuevo

`tests/integration/reels/test_webhook_ingest_always_renders.py` —
1 archivo, 1 test:

- **`test_webhook_ingest_always_requires_render`**: con `temporary_postgres_schema`
  real, ejecuta `IngestPropertyIntoReelUseCase.execute` dos veces con
  el mismo `_PAYLOAD`. Verifica:
  - Primera llamada (cold): `requires_render is True`, `is_noop is False`.
  - Segunda llamada (con `reels` row ya persistido + fingerprint
    idéntico): `content_fingerprint == first.content_fingerprint`
    (sanity check de que la política antigua habría caído al fast-path)
    **y** `requires_render is True`, `is_noop is False` (la nueva
    política sigue forzando render).

Docstring exhaustivo explica el contrato anterior, el motivo del
cambio y por qué este test es el guard de la nueva política.

## 5. Resultados de verificación

### Focales

```
.venv/bin/python -m pytest \
  tests/unit/reels/test_ingest_property_into_reel.py \
  tests/integration/reels/test_ingest_property_into_reel_flow.py \
  tests/integration/reels/test_webhook_ingest_always_renders.py \
  -q
```

→ `6 passed in 4.08s`.

### Reels completos (unit + integration)

```
.venv/bin/python -m pytest tests/unit/reels/ tests/integration/reels/ -q
```

→ `242 passed in 220.41s`.

### Readiness checks

- `.venv/bin/python -m apps.api --check` → exit 0, banner con
  `DATABASE`, `FFMPEG`, etc.
- `.venv/bin/python -m apps.worker --check` → exit 0, banner con
  `Worker --check OK: kinds=email_send, reel_publish, scripted_render
  outbox_events=review_requested worker_count=1 lease=900s poll=0.50s`.

### `bash ./init.sh`

→ exit 0. Cola:

```
FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
3 failed, 1117 passed, 1 deselected, 14 warnings in 589.83s (0:09:49)
```

3 fallos = baseline histórico documentado (`test_http_surface_contract.py`
+ 2× `test_http_transport.py`). El conteo `1117 passed` ≥ baseline
previo (1116) — neto: +1 test focal nuevo
(`test_webhook_ingest_always_requires_render`); el test renombrado se
cuenta igual en ambos lados.

## 6. Decisiones no obvias

- **No introduje flag/env var** para parametrizar el comportamiento
  (regla explícita del prompt: "cambio duro"). Si en el futuro hace
  falta volver atrás, basta con revertir el commit.
- **No eliminé** las primitivas `execute_existing` ni el branch
  `EXISTING MEDIA PUBLISH` del orquestador. Argumentos: (a) son código
  legítimo para flujos no-ingest (retry tras crash, regenerate
  manual); (b) borrarlas era out-of-scope del prompt; (c) si quedan
  inalcanzables desde ingest, la cobertura la dan los tests focales de
  `PersistLocalArtifactsUseCase.execute_existing` / 
  `PublishReelUseCase.execute_existing` que siguen verdes.
- **Mantuve `content_changed` y `has_local_artifacts` vivos** porque
  el log `Property Ingest Decision` (línea 473-498) los muestra como
  detalle informativo — el operador sigue viendo en logs si la
  re-ingesta venía con cambios reales en el snapshot o no, aunque la
  decisión de render ya no dependa de ello.

## 7. Estado del feature_list

No marcado como `done` (regla explícita: "NO marques features como
`done`"). Tampoco hay entry en `feature_list.json` para este cambio —
es una política bajo control directo del usuario, no una feature
catalogada. El reviewer decide el siguiente paso.
