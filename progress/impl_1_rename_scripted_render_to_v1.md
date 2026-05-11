# Implementacion - feature 1 (rename_scripted_render_to_v1)

## Alcance

Phase 3 feature 1 mueve el endpoint publico de scripted render desde la ruta
sin version a `POST /v1/videos/scripted/render`, sin alias legacy.

## Cambios

- `modules/rendering/transport/http/scripted_router.py`: el router usa
  `APIRouter(prefix="/v1", tags=["Video Rendering"])`; el path interno se
  mantiene como constante de recurso (`/videos/scripted/render`).
- `tests/integration/rendering/test_scripted_router.py`: los 6 tests
  existentes invocan la URL versionada y se anadio cobertura de regresion
  para confirmar que `POST /videos/scripted/render` devuelve 404.
- `docs/API.md`: documentado el contrato externo versionado, el body de
  respuesta `202 Accepted`, y la ausencia de alias legacy.
- `REFACTOR_STATUS.md`: actualizado el estado de Phase 3 para marcar A1 como
  hecho.

## Verificacion

- `bash ./init.sh`: no ejecutable en este Windows porque falta `/bin/bash`.
  Se uso el flujo equivalente con `.venv\Scripts\python.exe`.
- `.venv\Scripts\python.exe -m apps.api --check`: verde.
- `.venv\Scripts\python.exe -m apps.worker --check`: verde.
- `.venv\Scripts\python.exe -m pytest tests\integration\rendering\test_scripted_router.py -q`:
  `7 passed`.
- `.venv\Scripts\python.exe -m pytest -q --no-header`: `395 passed`.
- `rg --pcre2 -n '(?<!v1)/videos/scripted/render' .`: solo quedan menciones
  en documentos de plan/historial (`feature_list.json`,
  `docs/phase_3_operating_rules.md`, `progress/*`), no en codigo ni docs
  publicas activas.
- `rg -n "scripted/render" "..\4reels front\src" "..\4reels front\tests"`:
  0 hits.

## Notas

No toca schema. No cambia el use case ni el worker; el worker consume jobs
`scripted_render` desde Postgres y no depende de la URL HTTP.
