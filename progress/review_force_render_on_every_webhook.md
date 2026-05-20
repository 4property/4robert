# Review — force_render_on_every_webhook

- **Fecha:** 2026-05-19
- **Agente revisor:** Claude (rol reviewer)
- **Veredicto:** APPROVED

## Resumen

Política aplicada como pedida: cada webhook de ingest fuerza
`requires_render = True` incondicionalmente. Sin daños colaterales en
`RegenerateReelUseCase`, `Orchestrator`, ni en las primitivas
`execute_existing` de `PersistLocalArtifactsUseCase` /
`PublishReelUseCase` (siguen vivas para los flujos manual / retry).

## Checks ejecutados

### 1. Cambio en `ingest_property_into_reel.py:422`
- `git diff HEAD -- modules/reels/application/use_cases/ingest_property_into_reel.py`
  muestra exactamente la sustitución descrita en el informe (línea 419
  `requires_render = content_changed or not has_local_artifacts`
  reemplazada por un bloque de comentario que cita la fecha
  `2026-05-19`, el motivo del cambio, y la línea
  `requires_render = True`).
- Verificado en lectura directa
  (`modules/reels/application/use_cases/ingest_property_into_reel.py`,
  líneas 406-431):
  - `existing_snapshot_text` se sigue computando (líneas 413-417).
  - `content_changed` se sigue computando (líneas 418-421).
  - `has_local_artifacts` se sigue computando (líneas 406-412).
  - El log `Property Ingest Decision` (líneas 482-507) sigue
    consumiéndolos.
  - `_should_prepare_assets(..., requires_render=requires_render)` se
    sigue invocando (línea 437), por lo que el cálculo de
    `requires_asset_preparation` ahora siempre asume render.

### 2. No hay daños colaterales fuera del ingest
- `git status --short modules/reels/application/use_cases/regenerate_reel.py modules/reels/application/orchestrator.py modules/reels/application/use_cases/publish_reel.py`
  → vacío: ninguno de los tres está modificado.
- `persist_local_artifacts.py` sí aparece modificado, pero
  `git diff HEAD -- modules/reels/application/use_cases/persist_local_artifacts.py`
  confirma que se trata exclusivamente del cambio de la feature 41
  (`auto_subtitles_snapshot`, comentario `Feature 41` en la línea
  modificada). No tiene relación con la política de render — la API
  `execute_existing` permanece intacta.
- `grep -n "def execute_existing" persist_local_artifacts.py publish_reel.py`
  → ambas primitivas siguen presentes
  (`persist_local_artifacts.py:210`, `publish_reel.py:158`).
- El branch `EXISTING MEDIA PUBLISH` del orquestador sigue presente
  (`orchestrator.py:162`); queda inalcanzable desde ingest, pero el
  implementer documentó la decisión consciente de no borrarlo
  (sigue cubierto por los tests unitarios de las primitivas).

### 3. Tests
- `tests/unit/reels/test_ingest_property_into_reel.py:144` —
  `test_execute_always_requires_render_even_when_state_unchanged`
  con docstring que explica la política. Asserts confirmados
  (líneas 223-228): `context.requires_render is True`,
  `context.is_noop is False`, `len(states.saved) == 1`,
  `states.saved[0].workflow_state == "ingested"`. El test anterior
  (`test_execute_is_noop_when_state_unchanged_and_artifacts_present`)
  ya no aparece — renombrado correctamente.
- `tests/unit/reels/test_ingest_property_into_reel.py:97` —
  `test_execute_persists_state_and_returns_context_for_fresh_property`:
  ya esperaba `requires_render=True` antes del cambio (caso fresh
  ingest); compatible con la nueva política sin modificaciones.
- `tests/integration/reels/test_webhook_ingest_always_renders.py` —
  archivo nuevo (5267 B), 1 test
  `test_webhook_ingest_always_requires_render` que usa
  `temporary_postgres_schema` + `temporary_workspace` + `seed_tenant`.
  Las asserciones cubren ambos requisitos del prompt:
  (a) `second.content_fingerprint == first.content_fingerprint`
  (sanity de que el fingerprint NO se mueve), líneas 138; y
  (b) `requires_render is True` / `is_noop is False` en ambas llamadas
  (líneas 115-116, 139-140).
- `grep -rn "EXISTING MEDIA PUBLISH\|requires_render is False\|is_noop is True" tests/`
  → 3 hits, todos en docstrings de los tests recién añadidos /
  renombrados que explican la antigua política y por qué ahora se
  fuerza render. Ningún hit en tests del path de ingest está obsoleto.
- `grep -rln "requires_render.*False\|is_noop.*True" tests/` → 3
  archivos. Revisado:
  - `test_webhook_ingest_always_renders.py` → contexto en docstrings.
  - `test_ingest_property_into_reel.py` → contexto en docstring.
  - `test_persist_local_artifacts.py:361,378` → casos
    `execute_existing` que pasan `requires_render=False` como **input
    al builder de contexto sintético**, validando la primitiva de
    `PersistLocalArtifactsUseCase` directamente. No es el output del
    ingest — sigue siendo cobertura legítima del primitivo
    `execute_existing`.

### 4. Re-ejecución de la suite focal
```
.venv/bin/python -m pytest \
  tests/unit/reels/test_ingest_property_into_reel.py \
  tests/integration/reels/test_ingest_property_into_reel_flow.py \
  tests/integration/reels/test_webhook_ingest_always_renders.py \
  -q
```
→ `6 passed in 4.09s` ✔ (coincide con el conteo del informe del
implementer).

### 5. Convenciones
- No hay cambios en frontend ni TypeScript (cambio puramente backend).
- No hay nueva migración Alembic — no se toca schema, correcto.
- `grep "from services\.|from application\.|from repositories\.|from core\.|from domain\."` en
  los archivos tocados (`ingest_property_into_reel.py`,
  `test_webhook_ingest_always_renders.py`,
  `test_ingest_property_into_reel.py`) → 0 hits. Imports
  modernos exclusivamente.
- `grep "TODO\|FIXME\|print("` sobre
  `ingest_property_into_reel.py` → 0 hits relevantes al cambio.
- El bloque de comentario antes de `requires_render = True`
  explica política + fecha (`2026-05-19`) + endpoint manual no
  afectado, como pedido.

## Política aplicada como pedida

Ok to ship. El fast-path `EXISTING MEDIA PUBLISH` queda inalcanzable
desde el flujo de ingest sin código muerto literal: las primitivas
siguen siendo invocables desde otros flujos (retry / regenerate manual),
así que la decisión de conservarlas es defensible. Si en el futuro se
quiere limpiar la deuda, basta con auditar quién invoca
`execute_existing` fuera de ingest y decidir si tiene sentido borrar
las primitivas + el branch del orquestador.
