# impl - Feature 4 (Phase 3): http_surface_audit_and_contract_test

> Estado: **done**. Cierre de Phase 3; no arranca Phase 4.

## Resultado

`done`. Generada la superficie HTTP canonica desde `build_api_app(...)`,
versionados `docs/http_surface.md` y `docs/openapi.json`, y anadido un test
de contrato cross-repo que valida las llamadas `apiRequest(...)` del front
contra rutas vivas del back.

## Archivos principales

| Archivo | Cambio |
|---|---|
| `scripts/generate_http_surface.py` | Generador de `docs/http_surface.md` y `docs/openapi.json` desde la app real. |
| `scripts/__init__.py` | Paquete para importar el generador desde tests. |
| `docs/http_surface.md` | Tabla canonica generada: 51 rutas HTTP. |
| `docs/openapi.json` | OpenAPI versionado y formateado desde la app real. |
| `tests/integration/test_http_surface_contract.py` | Extrae 37 llamadas `apiRequest(...)` de `4reels front/src` y compara metodo+path contra FastAPI. |
| `docs/conventions.md` | Documenta el flujo para regenerar artefactos y extender placeholder mappings. |

## Comportamiento del test

- Lee `FRONTEND_REPO_ROOT` o usa `C:/Users/4pm/Desktop/4reels/4reels front`.
- Falla si el root no existe o no contiene `src/`.
- Normaliza template literals con `encodeURIComponent(...)` y helpers actuales
  `musicPath(...)` / `reelPath(...)`.
- Falla en expresiones que no sabe normalizar; no las skipea.
- Mensaje de mismatch incluye metodo, path normalizado, archivo+linea del front
  y ruta backend cercana con el mismo metodo cuando existe.

## Verificaciones

- `python scripts/generate_http_surface.py --write`: verde.
- `pytest tests/integration/test_http_surface_contract.py -q`: `1 passed`.
- Prueba de regresion en copia temporal rota del front: fallo esperado con
  mensaje accionable (`corregir src\features\admin\api.js:9`, ruta cercana).
- `python -m apps.api --check`: verde.
- `python -m apps.worker --check`: verde.
- `pytest -q --no-header`: `396 passed`.
- Front `npm run lint`: verde.
- Front `npm run build`: verde.
- Front `npm run test:smoke`: `40 passed, 2 skipped`.

## Cierre administrativo

- Feature 3 marcada `done` en back/front antes de arrancar feature 4.
- Feature 4 marcada `done` en back tras review APPROVED.
- `REFACTOR_STATUS.md` actualizado: Phase 3 cerrada; Phase 4 no aprobada.
