# Review — feature 10 (`agency_logo_upload`)

**Veredicto:** APPROVED

## Scope verificado contra decisiones del leader

| Decisión leader | Estado | Evidencia |
|---|---|---|
| NO tocar `BrandSettingsUpsertPayload` | OK | `git diff -- modules/configuration/transport/payloads/brand.py` → vacío. |
| NO alembic revision | OK | `git status` no muestra cambios en `alembic/versions/`; sigue habiendo solo `20260501_0001_initial_schema.py`. |
| NO boto3/S3 | OK | `grep -rn 'boto3\|S3_BUCKET\|AWS_'` en módulos nuevos/modificados → 0 hits. La persistencia es FS-only bajo `workspace_dir/generated_media/_agency_branding/`. |
| Deletion via empty string `""`, no `null` | OK | Documentado explícitamente en `docs/API.md` sección "Deletion contract". El payload existente trata `None` como "preserve"; la columna es `Text NOT NULL DEFAULT ''`. |
| Validación content_type + extensión + 5 MB con código de error claro | OK | `modules/configuration/transport/http/brand_logo_router.py:236-296` cruza content-type contra extensión y rechaza con códigos `BRAND_LOGO_UPLOAD_UNSUPPORTED_TYPE` (415), `..._UNSUPPORTED_EXTENSION` (422), `..._TYPE_EXTENSION_MISMATCH` (422), `..._TOO_LARGE` (413), `..._EMPTY` (422), `..._MISSING_FIELD` (422), `..._MALFORMED` (422). |

## Checkpoints

- **C1 — Router nuevo `brand_logo_router.py` con POST multipart + GET stream**: OK.
  `modules/configuration/transport/http/brand_logo_router.py:174-343` (POST) y `345-406` (GET).

- **C2 — Auth vía `authorize_admin_request`**: OK.
  Linea 193-195 del router (POST) y 361-363 (GET): mismo gate que el resto de
  `/v1/admin/*`. Test `test_brand_logo_upload_requires_auth` valida 401/403 sin token.

- **C3 — Validación con códigos de error claros**: OK.
  7 códigos distintos (ver tabla arriba). El payload del error usa el
  shape canónico `{error, code, hint, details}` vía `apps.api.error_handlers.json_error`.

- **C4 — Helper `resolve_agency_branding_destination` en `shared/storage/site_layout.py`**: OK.
  `shared/storage/site_layout.py:31-58` (destino) + `61-89` (resolución inversa).
  Decisión inter-module documentada en el impl report §"Inter-module boundary":
  `modules/reels/application` no puede importar de `modules/rendering/infrastructure`,
  por eso el helper vive en `shared/storage/` (consumido por configuration/transport y
  reels/application). Correcto.

- **C5 — Cableado rendering con preferencia agency logo > webhook**: OK.
  `modules/rendering/infrastructure/runtime/branding.py:53-70`: si
  `property_data.agency_logo_local_path` existe y apunta a un archivo no vacío,
  retorna inmediatamente esa ruta (sin disparar `download_remote_image`).
  Si la ruta es `None` o el archivo no existe, **cae al flujo original** del
  webhook (lineas 72-116). El fallback al webhook URL se preserva.

- **C6 — 4 unit tests rendering + 10 integration tests upload/stream**: OK.
  - `tests/unit/rendering/test_branding_preference.py`: 4 tests (override válido,
    fallback por override unset, fallback por archivo stale, ni override ni URL → `None`).
  - `tests/integration/configuration/test_brand_logo_router.py`: 10 tests
    (PNG OK, JPG OK, content-type no soportado, extension no soportada,
    mismatch type/extension, >5MB, empty, sin auth, agency desconocida, GET 404).

- **C7 — `docs/API.md` con endpoint + contrato deletion via empty string**: OK.
  Sección "Brand logo upload (feature 10)" en `docs/API.md` añade tabla de
  endpoints, request shape, success response, error table (8 códigos) y
  bloque "Deletion contract" que documenta explícitamente que `null` NO es
  delete operator.

- **C8 — Sin `python-multipart` ni nueva dep**: OK.
  `git diff -- requirements.txt` → vacío. `grep python-multipart requirements.txt` → 0 hits.
  El parser multipart custom usa `email.parser` de stdlib (ver §"Notas sobre parser multipart custom").

- **C9 — Test suite focal verde**: OK.
  `.venv/bin/python -m pytest tests/unit/configuration/ tests/integration/configuration/ tests/unit/rendering/ -q` →
  `170 passed in 75.76s`.

- **C10 — `./init.sh` verde con solo 2 fallos preexistentes**: OK.
  `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` →
  `2 failed, 497 passed`. Los 2 fallos son
  `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_*`
  (preexistentes; el código de `/health` devuelve también `configured_worker_count`
  no esperado por los tests). El proceso termina exit 0 (`Entorno listo`).

- **C11 — `apps.api --check` y `apps.worker --check` exit 0**: OK.
  Ambos retornan exit 0 con RUNTIME READY: Yes.

## Notas sobre el parser multipart custom (decisión arriesgada del implementer)

El implementer evitó añadir `python-multipart` como dep y parsea
`multipart/form-data` con stdlib `email.parser`. Análisis de seguridad:

**Path traversal vía `filename` (multipart Content-Disposition):** MITIGADO.
El filename del usuario nunca se escribe a disco. El nombre persistido es
`logo-<sha1-12>.png` (generado a partir del hash SHA-1 de los bytes
subidos en `brand_logo_router.py:310-312`). El filename del usuario solo se
usa para validar el sufijo (`.jpg|.jpeg|.png`) — un valor `"../../etc/passwd"`
tiene `Path(...).suffix == ''` y se rechaza con 422.

**Path traversal vía `agency_id` (path param):** MITIGADO.
`agency_id` se sanea con `safe_site_dirname` (regex `[^A-Za-z0-9._-]+` →
`_` + `.strip("._-")`) antes de construir la ruta. Cualquier `..` o `/`
en `agency_id` se transforma en `_`. En el GET stream
(`brand_logo_router.py:366-389`), el `{filename}` URL segment se rechaza
explícitamente si contiene `/`, `.`, `..` antes de tocar el workspace,
y `resolve_agency_branding_local_path` rechaza shapes con `..`, `.` o
`://`.

**Header injection vía boundary del Content-Type:** RIESGO MENOR ACEPTABLE.
El regex `_MULTIPART_BOUNDARY_RE = re.compile(r'boundary\s*=\s*"?([^";]+)"?', re.IGNORECASE)`
acepta `\r\n` dentro del boundary, lo que permite que un atacante inyecte
headers adicionales en el **wrapper RFC-822 sintetizado** que se pasa al
`email.parser`. Sin embargo:

1. El wrapper sintetizado no se propaga a ninguna respuesta HTTP — solo
   se usa internamente para alimentar al parser.
2. El "header inyectado" se aplica al EmailMessage sintético, no al
   request real. El parser no escribe esos headers a disco ni los refleja
   en la respuesta.
3. El cuerpo está acotado a 5 MB por la guard previa (linea 210), así que
   no hay vector de DoS por memoria.
4. El impacto máximo es que el boundary efectivo se trunque al primer
   `\r\n`, lo que confunde al parser y retorna `BRAND_LOGO_UPLOAD_MALFORMED`
   (422) — un downgrade de funcionalidad, no una vulnerabilidad.

**Recomendación opcional para futura iteración** (no bloqueante): estrechar
el regex a `r'boundary\s*=\s*"?([A-Za-z0-9\'()+_,\-./:=?]+)"?'` (alfabeto
RFC 2046 §5.1.1 para parámetros de boundary). No es necesario aprobar
esta feature.

**Memoria:** El cuerpo entero se buffea con `await request.body()`. El
guard `len(body) > max_upload_bytes` (5 MB) se ejecuta antes de invocar al
parser, así que el peor caso es ~5 MB en memoria — aceptable para un
endpoint admin de baja frecuencia.

**Cobertura del parser:** Los 10 tests de integración cubren los happy
paths (PNG + JPG via `httpx`/Starlette TestClient, que genera multipart
RFC-compliant) y los casos de rechazo. No hay test que cubra multipart
exótico (parts vacíos, transfer-encoding non-identity, charset binary
sin Content-Transfer-Encoding), pero el contrato del endpoint solo
declara `file` field con JPG/PNG binario — escenarios fuera de spec.

## Out of scope detectado en el árbol de trabajo

`git diff -- apps/api/app_factory.py` revela un cambio NO documentado en
el impl report:

```
+        allow_private_network=True,
```

en el `CORSMiddleware` (linea 254). Este flag NO es necesario para la
feature 10 y no se menciona en `progress/impl_10_agency_logo_upload.md`,
`progress/current.md`, ni en ningún `progress/explore_*.md`.

**Análisis**: el `progress/explore_feature_10_agency_logo_upload_state.md`
§6 documenta que `apps/api/app_factory.py` ya estaba modificado **antes**
de que el implementer de feature 10 empezase a trabajar (la regla
"sin commits intermedios" de Phase 2 dejó deriva acumulada de features 8,
9, 12). El implementer fue advertido en el spike de
"reconciliar [su] línea sin pisar las existentes".

Hipótesis más probable: el `allow_private_network=True` es deriva
**pre-existente** (de otra feature o experimento de runtime), no
introducido por el implementer de feature 10. Las 2 líneas de cambio que
sí corresponden inequívocamente a feature 10 son el import de
`create_brand_logo_router` (linea 49-51) y el `app.include_router(...)`
de 7 líneas (linea 347-353).

**No bloqueante para esta review** porque:
1. El impl_10 declara apps/api/app_factory.py como modificado solo para
   "Register `create_brand_logo_router`".
2. El cambio CORS NO toca módulos prohibidos (`apps/api` no está en la
   lista frozen de la regla).
3. No introduce regresión funcional ni de tests (las 497 suites pasan).

El **leader debería decidir** si limpiar la deriva CORS en una feature
posterior dedicada a "limpiar el árbol Phase 4". No es responsabilidad
del implementer de feature 10 revertir cambios que estaban en el árbol
cuando llegó.

## Cambios requeridos

Ninguno. La implementación satisface todos los checkpoints, las decisiones
del leader, las reglas duras de la review, y la suite de tests focal pasa
con 170 verdes. Los 2 fallos del init.sh son preexistentes y orthogonales.

## Resumen ejecutivo

- 1 router nuevo (`brand_logo_router.py`) con POST multipart + GET stream.
- 1 helper FS-agnostic en `shared/storage/site_layout.py`
  (`resolve_agency_branding_destination` + `resolve_agency_branding_local_path`).
- Rendering wired con preferencia agency-upload > webhook URL, fallback
  preservado.
- 14 tests nuevos (4 unit + 10 integration).
- 0 deps nuevas, 0 alembic, 0 cambios al payload Pydantic, 0 boto3/S3.
- Decisión de seguridad sobre parser multipart custom: aceptable, sin
  vulnerabilidades explotables. Sugerencia opcional de hardening del
  regex de boundary documentada arriba pero no bloqueante.
