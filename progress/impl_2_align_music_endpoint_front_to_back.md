# Implementacion - feature 2 (align_music_endpoint_front_to_back)

## Alcance

Feature cross-repo para alinear el dashboard Music con el CRUD real del
backend en `/v1/admin/agencies/{id}/music` y retirar el stub
`/music-tracks` del front y del mock Playwright.

## Cambios backend

- `docs/API.md`: documentado el contrato definitivo de musica con los 5
  verbos, response wrappers, shape de `music_track` y codigos de error.
- `tests/integration/configuration/test_music_router.py`: reforzado el test
  de list para fijar `{agency_id, items, count}` y el shape canonico por
  track.
- `REFACTOR_STATUS.md`: marcado el cierre de feature 2 y eliminado el item
  pendiente de `/music-tracks` en la auditoria front-back.

## Cambios frontend

- `src/features/music/api.js`: reemplazo de `/music-tracks` por `/music` y
  exposicion de `registerTrack`, `listTracks`, `inspectTrack`,
  `reconfigureTrack`, `decommissionTrack`.
- `src/features/music/hooks.js`: hooks de lectura y mutacion para los 5
  verbos, usando `useApi`/`useMutation`.
- `src/features/music/MusicConfig.jsx`, `MusicLibrary.jsx`, `MusicRules.jsx`
  y `music.css`: UI adaptada a `music_id`, `display_name`, `object_key`,
  `duration_seconds`, `is_default`, `created_at`; CRUD basico completo.
- `tests/support/mock-backend.js`: mock CRUD in-memory para
  `/v1/admin/agencies/{id}/music` con el shape del backend.
- `tests/music.spec.js`: Playwright minimo que lista, crea, edita y borra
  tracks en desktop/tablet/mobile.
- `DOCS.md`: contrato de Music actualizado en la documentacion del front.

## Verificacion

- Backend: `apps.api --check` verde.
- Backend: `apps.worker --check` verde.
- Backend: `pytest tests\integration\configuration\test_music_router.py -q`:
  `4 passed`.
- Backend: `pytest -q --no-header`: `395 passed`.
- Front: `npm run lint --silent` verde.
- Front: `npm run build --silent` verde.
- Front: `npm run test:smoke`: `40 passed`, `2 skipped`.
- Front: `npx playwright test music.spec.js`: `3 passed`.
- Front: `npm run test:e2e`: `43 passed`, `2 skipped`.
- `rg -n "music-tracks" src tests` en `4reels front`: 0 hits.

## Notas

`bash ./init.sh` no puede ejecutarse literalmente en este Windows porque falta
`/bin/bash`; se uso el flujo equivalente documentado por ambos harnesses.
