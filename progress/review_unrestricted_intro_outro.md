# Review — Unrestricted intro/outro uploads

**Veredicto:** APPROVED

Fecha: 2026-05-20
Implementer report: `progress/impl_unrestricted_intro_outro.md`

## Checkpoints

- [x] `validate_outro_upload` / `validate_intro_upload` ya no rechazan
      por tamaño. Solo MIME (`*_INVALID_MIME`) y body vacío
      (`*_FILE_EMPTY`) siguen lanzando `ValidationError`. Confirmado en
      `modules/configuration/application/use_cases/upload_outro_video.py:80-117`
      y `modules/configuration/application/use_cases/upload_intro_video.py:79-116`.
- [x] Funciones `validate_outro_duration` / `validate_intro_duration`
      eliminadas por completo (no quedan ni como passthrough). El use
      case ya no las llama: el `try/except ValidationError` que
      envolvía la llamada y limpiaba el blob huérfano también
      desapareció (`upload_outro_video.py:179-188`,
      `upload_intro_video.py:178-187`).
- [x] Constantes `*_MAX_UPLOAD_BYTES`, `*_MIN_DURATION_SECONDS`,
      `*_MAX_DURATION_SECONDS` borradas. El parámetro `max_upload_bytes`
      no aparece ni en el constructor de los use cases ni en la firma
      de `create_*_router`.
- [x] `__all__` de cada use case consistente con lo que queda: solo
      `ALLOWED_*_CONTENT_TYPES`, `*_ValidationResult`,
      `SUFFIX_BY_*_CONTENT_TYPE`, `Upload*VideoInput`,
      `Upload*VideoUseCase`, `validate_*_upload`. No referencia ningún
      símbolo borrado.
- [x] Routers (`outro_router.py`, `intro_router.py`) sin guard 413 ni
      mapeo `FILE_TOO_LARGE → 413`. El handler de `ValidationError`
      siempre devuelve 422. El mapeo MIME → 422 y los 4xx del
      `_extract_file_field` (`UPLOAD_UNSUPPORTED_TYPE`,
      `UPLOAD_MALFORMED`, `UPLOAD_MISSING_FIELD`) se mantienen
      intactos.
- [x] `docs/openapi.json`, `docs/API.md` y `docs/http_surface.md`
      regenerados. Los códigos `OUTRO_FILE_TOO_LARGE`,
      `OUTRO_INVALID_DURATION`, `INTRO_FILE_TOO_LARGE`,
      `INTRO_INVALID_DURATION` y las strings "<=50MB", "1-10s",
      "1..10s" ya no aparecen en doc OpenAPI/HTTP surface. La única
      mención al "50 MB" en `docs/API.md:660,755` es el texto
      explicativo "the 50 MB cap was removed", correcto.
- [x] No quedan referencias a los símbolos borrados en código fuente
      ni tests (`grep -rn -E "OUTRO_MAX_UPLOAD_BYTES|..." --include=*.py`
      vacío). Las únicas residuales (`feature_list.json`,
      `progress/*.md`) son históricas y el protocolo manda no
      reescribirlas.
- [x] Tests añadidos cubren las dos nuevas semánticas:
  - `test_validator_accepts_payload_well_over_50mb` (intro + outro,
    `tests/unit/configuration/test_*_validator.py`) — 60 MB pasa la
    validación.
  - `test_*_upload_accepts_duration_above_10_seconds`
    (`tests/integration/configuration/test_*_router.py`) — usa el
    fixture real `long_outro_15s.mp4` (15 s, ambos tests reusan el
    mismo MP4 ya que es contenido neutro), asserta 200 +
    `*_duration_seconds == 15` + blob persistido en disco.
  - `test_*_upload_accepts_payload_over_50mb` — usa un
    `ffprobe_runner` stub que devuelve 60 s, inyectado vía el
    parámetro `upload_*_video` del router. 50 MB + 16 B pasan; el
    response trae `*_duration_seconds == 60` y `*_object_key`
    presente. Justificado en el docstring del test.
- [x] Suite del módulo verde:
  - `pytest tests/unit/configuration tests/integration/configuration`
    → 273 passed in 208.35 s.
  - `python -m apps.api --check` → RUNTIME READY: Yes.
- [x] Los 3 failures de la suite completa son pre-existentes y ajenos
      a este cambio (ver sección siguiente).

## Verificación de los 3 failures pre-existentes

Ejecutados aisladamente sobre el árbol con los cambios aplicados:

```
pytest tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes \
       tests/integration/test_http_transport.py
→ 3 failed, 19 passed in 34.63 s
```

1. `test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
   — `FRONTEND_REPO_ROOT` no apunta a `/opt/projects/4Reels-Frontend`
   en este host (default Windows). Ningún acoplamiento posible con
   intro/outro.
2. `test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state`
   y `test_health_endpoints_return_minimal_payloads`
   — `/health` ahora devuelve un tercer campo
   `configured_worker_count` (`apps/api/health_router.py:125`) que
   estos tests no esperan. Otro test del repo
   (`tests/integration/apps_api/test_health_router.py:39-72`) sí lo
   incluye, así que la inconsistencia es entre dos baterías del
   propio repo y precede a este cambio.

Comprobado vía `git status` que el implementer no tocó
`tests/integration/test_http_surface_contract.py`,
`tests/integration/test_http_transport.py`, ni
`apps/api/health_router.py` (no aparecen en el listado de
`modified`). Último commit que tocó esos archivos: `f3507e9`
(sprint 17-40), anterior a este cambio.

## Resultado

Cambio aprobado. La eliminación es quirúrgica y consistente entre las
4 capas (use case, router, tests, docs). No hay drift entre el
producción y la documentación generada. Los tests cubren tanto la
nueva semántica permisiva (duración >10 s, tamaño >50 MB) como las
guardias restantes (MIME, body vacío), y los 3 failures que ve la
suite completa son ortogonales a esta tarea.
