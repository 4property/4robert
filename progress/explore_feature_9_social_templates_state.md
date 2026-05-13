# Explore — Feature 9 `agency_default_descriptions_ui` — Estado actual

Investigación del estado del backend antes de lanzar el implementer.
Solo lectura.

---

## 1. Estado actual de `social_templates_router`

### Path completo
- Router: `/opt/projects/4Reels-Backend/modules/configuration/transport/http/social_templates_router.py`
- Payload model: `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/social_templates.py`
- Use cases:
  - `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/read_social_templates.py`
  - `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/replace_social_templates.py`

### Verbos expuestos bajo `/v1/admin/agencies/{agency_id}/social-templates`
Prefijo confirmado en `apps/api/app_factory.py:357-361` (incluye el router con `admin_access_policy.base_path`, que por defecto es `/v1/admin` — `settings/app.py:216-218`).

- `GET /v1/admin/agencies/{agency_id}/social-templates` → `social_templates_router.py:50-86`
  - Decorador y summary: líneas `50-58`
  - Handler `read_admin_agency_social_templates`: líneas `60-86`
- `PUT /v1/admin/agencies/{agency_id}/social-templates` → `social_templates_router.py:88-147`
  - Decorador y summary: líneas `88-96`
  - Handler `replace_admin_agency_social_templates`: líneas `97-147`

No hay `POST` ni `DELETE` per-platform expuestos en el router (aunque el repo
sí tiene `delete`/`upsert`/`delete_all_for_agency` — `social_template_repository.py:95-115`).

### Shape EXACTO de request (PUT)
`SocialTemplatesReplacePayload` — `social_templates.py:8-37`:

```python
class SocialTemplatesReplacePayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",                 # línea 18
        str_strip_whitespace=True,      # línea 19
        json_schema_extra={...},        # ejemplo en líneas 20-27
    )
    templates: dict[str, str] = Field(
        default_factory=dict,           # línea 31
        description=(...),              # líneas 32-36; "Unknown keys are accepted"
    )
```

- El cuerpo es `{"templates": {<platform>: <description_template>}}`.
- `extra="forbid"` rechaza claves desconocidas a nivel raíz (no a nivel del
  diccionario `templates`).
- `str_strip_whitespace=True` aplica a strings.
- No hay validador de variables permitidas — el dict admite cualquier string.

### Shape EXACTO de response (GET y PUT)
GET — `social_templates_router.py:78-86`:

```python
return JSONResponse(
    status_code=200,
    content={
        "agency_id": agency_id,
        "templates": _serialize_templates(records),  # dict[platform → description]
        "items": [_serialize_record(record) for record in records],
        "count": len(records),
    },
)
```

PUT (200) — `social_templates_router.py:138-147`:

```python
return JSONResponse(
    status_code=200,
    content={
        "status": "saved",
        "agency_id": agency_id,
        "templates": _serialize_templates(records),
        "items": [_serialize_record(record) for record in records],
        "count": len(records),
    },
)
```

`_serialize_templates` — `social_templates_router.py:152-153`: produce
`{record.platform: record.description_template, ...}` (mapa flat).

`_serialize_record` — `social_templates_router.py:156-165`: cada item es:

```python
{
    "agency_id": str,
    "platform": str,
    "description_template": str,
    "title_template": str,         # actualmente siempre "" desde el PUT
    "hashtags": list[str],         # actualmente siempre [] desde el PUT
    "created_at": str,
    "updated_at": str,
}
```

Nota: el repo `replace_all_for_agency` (`social_template_repository.py:117-138`)
solo toma `description_template` del input; `title_template` y `hashtags` se
quedan con sus defaults (string vacío y array vacío). Los campos están en la
columna pero no son editables por la API actual.

### Errores manejados (PUT)
- `ValidationError` → `400` con `code` propagado del error (`router.py:114-121`).
- `ResourceNotFoundError` → `404` con código (`router.py:122-129`). El use case
  arroja `ADMIN_AGENCY_NOT_FOUND` si la agencia no existe
  (`replace_social_templates.py:35` → `_agency_support.ensure_agency_exists`).
- `ApplicationError` → `500` con `code` `SOCIAL_TEMPLATES_SAVE_FAILED`
  (`router.py:130-137`).

Pydantic 422 lo emite FastAPI automáticamente cuando el body no encaja en el
shape (extra keys al root, tipo erróneo, etc.).

### Estado git
- `git log --oneline -- modules/configuration/transport/http/social_templates_router.py modules/configuration/transport/payloads/social_templates.py`
  → un solo commit: `2f106e7 production test`. Ambos ficheros están commiteados.
- `git diff` (working tree) sobre los dos ficheros → cambios SIN commit:
  - `social_templates_router.py` línea 56-58: añadido `pinterest` al texto de
    descripción del GET.
  - `social_templates.py` línea 14: añadido `pinterest` al docstring del payload.
  - **Solo cosmético** (textos de docstring/description). Ni shape ni lógica
    cambian. El implementer puede tocar estos ficheros sin reconciliar nada
    funcional.

---

## 2. Tabla `agency_social_templates` y consumo en el pipeline

### Definición ORM
- Mapeo SQLAlchemy: `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/orm.py:109-127`

```python
class AgencySocialTemplateORM(Base):
    __tablename__ = "agency_social_templates"
    __table_args__ = (
        PrimaryKeyConstraint("agency_id", "platform", name="pk_agency_social_templates"),
    )
    agency_id            : String(36) FK agencies.id ON DELETE CASCADE  # línea 115
    platform             : Text not null                                  # línea 120
    description_template : Text not null                                  # línea 121
    title_template       : Text not null default ""                       # línea 122
    hashtags             : Text[] not null default {}                     # línea 123-125
    created_at           : DateTime tz not null                           # línea 126
    updated_at           : DateTime tz not null                           # línea 127
```

- Re-exportado desde `shared/db/orm.py:35-41` y `:388` (`AgencySocialTemplateORM`).
- También aparece en `apps/api/readiness.py:45` como tabla esperada por la
  prueba de readiness.

### Repositorio
- `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/social_template_repository.py`
  - `list_for_agency` — líneas `13-33`
  - `get` — líneas `35-54`
  - `upsert` — líneas `56-93` (INSERT ... ON CONFLICT DO UPDATE)
  - `delete` — líneas `95-104`
  - `delete_all_for_agency` — líneas `106-115`
  - `replace_all_for_agency` — líneas `117-138` (drop+upsert por platform; solo
    setea `description_template`; otros campos quedan con defaults)
- Aggregator que lo expone bajo `uow.configuration.social_templates`:
  `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/agency_settings_repository.py:13-22`

### Use cases que lo leen
1. **`ReadSocialTemplatesUseCase`** — `read_social_templates.py:12-24`
   (`uow.configuration.social_templates.list_for_agency(...)` — línea `22`).
   Lo invoca el GET del router.
2. **`ReplaceSocialTemplatesUseCase`** — `replace_social_templates.py:25-47`
   (`uow.configuration.social_templates.replace_all_for_agency(...)` — línea `44`).
   Lo invoca el PUT del router.
3. **`ReadAggregatedReelProfileUseCase`** — `read_aggregated_reel_profile.py:142-144`:
   ```python
   social_templates = uow.configuration.social_templates.list_for_agency(
       normalized_agency_id
   )
   ```
   Embebido en la respuesta agregada `extra_settings.social_templates`
   (líneas `76-83`).
4. **`RegenerateReelUseCase`** — `regenerate_reel.py:184-186`:
   ```python
   social_templates_records = (
       uow.configuration.social_templates.list_for_agency(normalized_agency_id)
   )
   ```
   Normalizado a tuplas `(platform_lower, description_template)` y guardado en
   `publish_context["social_templates"]` (líneas `193-208`). Este es el camino
   que llega al worker.

### Camino al `DeterministicPropertyContentGenerator`

Confirmado: el worker lee `publish_context.social_templates_map` y se lo pasa
al generator vía `templates_by_platform`.

- `_ingest_property_planning.py:166-168` (worker):
  ```python
  generated_content = content_generator.generate_property_content(
      property_item=property_item,
      property_url=publish_target_url,
      platforms=desired_platforms,
      templates_by_platform=getattr(
          publish_context, "social_templates_map", {}
      ),
  )
  ```
- `modules/reels/domain/types.py:73-74` define
  `social_templates_map → dict(self.social_templates)`.
- `DeterministicPropertyContentGenerator.generate_property_content` —
  `content_generator.py:114-160`. Por cada platform en `platforms` busca el
  template normalizado (línea `135`); si existe, llama
  `render_template_with_property` y reemplaza el caption deterministic
  (líneas `136-143`).

### Variables permitidas (catálogo único, lo define `content_generator.py`)
Función `_build_property_template_variables` — `content_generator.py:48-85`.
Devuelve este diccionario fijo (claves admitidas — todo lo demás se deja literal):

| Variable             | Origen | Línea |
|----------------------|--------|-------|
| `property_title`     | `property_item.title` | 59 |
| `price`              | `property_item.price` | 60 |
| `bedrooms`           | `property_item.bedrooms` | 61-63 |
| `bathrooms`          | `property_item.bathrooms` | 64-66 |
| `size_m2`            | `property_size` | 67 |
| `property_type`      | `property_type_label` | 68 |
| `city`               | `property_county_label` | 69 |
| `neighborhood`       | `property_area_label` | 70 |
| `neighborhood_tag`   | `property_area_label` lower+sin espacios | 71-73 |
| `eircode`            | `eircode` | 74 |
| `short_description`  | `excerpt_html` (strip) | 75 |
| `agent_name`         | `agent_name` | 76 |
| `agent_phone`        | `agent_mobile` o `agent_number` | 77-81 |
| `agent_email`        | `agent_email` | 82 |
| `booking_link`       | `property_url` | 83 |
| `property_url`       | `property_url` | 84 |

Total: **16 claves**. La regex que las captura es
`_TEMPLATE_VARIABLE_PATTERN = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")` —
`content_generator.py:45`. Las claves se comparan en lowercase (`.strip().lower()`
— línea `107`). Si la variable no está en el dict → fallback `match.group(0)`
(línea `108`), es decir, queda el literal `{{unknown_variable}}` en el caption.

---

## 3. `agency_reel_defaults.caption_template` — dead code o no

### Definición ORM
`modules/configuration/infrastructure/orm.py:68-70`:

```python
caption_template: Mapped[str] = mapped_column(
    Text, nullable=False, server_default=""
)
```

Tabla `agency_reel_defaults` — clave primaria `agency_id`.

### Grep exhaustivo `grep -rn 'caption_template' modules/ apps/ shared/ tests/`

#### Lectura/escritura desde la API de configuración (routers + use cases)
- `modules/configuration/transport/payloads/defaults.py:67-70` — campo del
  `ReelDefaultsUpsertPayload` (PUT `/v1/admin/agencies/{id}/defaults`).
- `modules/configuration/transport/payloads/defaults.py:28` — ejemplo del schema.
- `modules/configuration/transport/payloads/reel_profile.py:34, :55` —
  campo en `ReelProfileUpsertPayload` (PUT
  `/v1/admin/agencies/{id}/reel-profile`).
- `modules/configuration/transport/http/defaults_router.py:121, :173, :184` —
  pasa el campo al use case y lo serializa en la respuesta del GET y PUT.
- `modules/configuration/transport/http/reel_profile_router.py:130` — pasa al
  use case agregado.
- `modules/configuration/application/use_cases/update_reel_defaults.py:27, :58`
  — campo del `UpdateReelDefaultsInput` y reenvío al repo.
- `modules/configuration/application/use_cases/update_aggregated_reel_profile.py:44, :96, :107`
  — idem para el endpoint agregado.
- `modules/configuration/application/use_cases/read_aggregated_reel_profile.py:64-66, :119`
  — incluido en el `to_public_dict()` del agregado.
- `modules/configuration/infrastructure/defaults_repository.py:22, :35, :49, :86-88, :99, :102, :109`
  — SELECT/UPSERT del campo en BBDD.
- `modules/configuration/domain/agency_settings.py:38` — campo en el value
  object `ReelDefaults`.

#### Lectura desde el módulo `tenancy`
- `modules/tenancy/transport/http/admin_agencies_router.py:315`:
  ```python
  "caption_template": str(getattr(defaults, "caption_template", "") or ""),
  ```
  Endpoint admin de tenancy lo serializa en la respuesta de detalle de agencia.

#### Tests (sólo CRUD; nadie testea consumo en pipeline)
- `tests/integration/configuration/test_reel_profile_router.py:83, :113`
- `tests/integration/tenancy/test_admin_agencies_router.py:121`
- `tests/unit/configuration/test_read_aggregated_reel_profile.py:50, :85`
- `tests/unit/configuration/test_update_reel_defaults.py:40`
- `tests/unit/configuration/test_read_reel_defaults.py:22`
- `tests/unit/configuration/test_update_aggregated_reel_profile.py:45, :71, :92`
- `tests/unit/reels/test_content_generator_unescape.py:143` — `def
  test_generate_property_content_uses_decoded_title_in_caption_template`
  (¡nombre engañoso! El test no usa `agency_reel_defaults.caption_template`;
  solo usa el helper `render_template_with_property` con un template literal).

#### Pipeline (worker, content_generator, regenerate_reel)
`grep` adicional acotado a `modules/reels/`, `modules/publishing/`,
`apps/worker/`, `apps/api/` → **cero hits**:

```
grep -rn 'caption_template' apps/worker/ apps/api/ modules/reels/ modules/publishing/
→ (sin output)
```

### Conclusión: `caption_template` ES dead code en el pipeline
- Se persiste, se lee y se devuelve en endpoints de lectura, pero
  **ningún consumer del pipeline de publicación lo lee**.
- `regenerate_reel.py` arma `publish_context` con `social_templates` (de
  `agency_social_templates`), no con `caption_template` (de
  `agency_reel_defaults`).
- El worker (`_ingest_property_planning.py`) le pasa al
  `DeterministicPropertyContentGenerator` solo `templates_by_platform`
  (vienen del map de social templates), nunca un caption global.

### Recomendaciones (decisión para la review)

#### Opción A — DROP (recomendada, menor superficie)
- **Pros**: elimina el campo no usado, evita confusión sobre qué template
  manda (¿caption global o per-platform?), reduce el shape público y simplifica
  el contrato del frontend.
- **Coste**: alembic revision con `op.drop_column('agency_reel_defaults',
  'caption_template')`; eliminar el campo del ORM, del value object
  `ReelDefaults`, de los payloads `ReelDefaultsUpsertPayload` y
  `ReelProfileUpsertPayload`, del use case `UpdateReelDefaults*` y de las dos
  proyecciones (aggregated reel profile y admin tenancy router); reescribir 7
  archivos de tests que lo referencian. Mecánico, sin riesgo en runtime.
- **Riesgo del frontend**: si el admin actual ya envía `caption_template` en
  `PUT /defaults` o `PUT /reel-profile`, esos requests pasarían a fallar con
  `extra="forbid"`. Hay que coordinar (o tolerar el campo y descartarlo).

#### Opción B — KEEP como fallback global
- Cablear `caption_template` en `regenerate_reel.py` (o en el worker) como
  template por defecto cuando `social_templates` no tenga entrada para la
  platform actual.
- **Pros**: aprovecha la columna existente y da al admin un "caption por
  defecto" sin tener que rellenar 7 platforms.
- **Coste**: definir orden de precedencia (per-platform > global > deterministic
  builder), añadir el global al `publish_context.social_templates_map` con
  sentinel key (p. ej. `"_default"`), tocar el `DeterministicPropertyContentGenerator`
  para honrar el sentinel.
- **Riesgo**: dos rutas para el mismo dato (per-platform y global) → más
  superficie de bug en el contrato; el frontend tendría que mostrar dos
  pantallas o un toggle "usar global vs override per-platform".

**Mi recomendación:** **DROP**. La feature 9 introduce explícitamente la UI
per-platform, así que el global no aporta nada que el admin no pueda hacer
duplicando un mismo string en 7 keys (o copiando-pegando). El precio de
mantener dos caminos no compensa el ahorro de UX.

---

## 4. Validación de variables permitidas (estado actual)

### ¿El payload PUT valida `description_template` contra el catálogo?
**No.** El payload `SocialTemplatesReplacePayload` (`social_templates.py:30-37`)
declara `templates: dict[str, str]` con `default_factory=dict` y sin validador
adicional. El use case `ReplaceSocialTemplatesUseCase`
(`replace_social_templates.py:25-47`) solo normaliza la **clave** de la
plataforma (`.strip().lower()`) y hace un `str(value or "")` sobre el valor.
Nadie inspecciona el contenido del template en busca de `{{...}}` desconocidos.

### Flujo de un `{{unknown_variable}}` desde el router al pipeline
1. Router PUT `/social-templates` recibe el body, Pydantic lo valida solo en
   shape (dict de strings). Pasa.
2. Use case `replace_social_templates.py:38-42` lo trata como string opaco.
3. Repo `replace_all_for_agency` persiste tal cual (línea 132-137).
4. En tiempo de publicación (`regenerate_reel.py:184-208`), el string viaja
   al `publish_context`.
5. El worker lo pasa a `DeterministicPropertyContentGenerator`
   (`_ingest_property_planning.py:166-168`).
6. `render_template_with_property` (`content_generator.py:88-111`) intenta
   sustituir; el `_replace` interno (línea `106-108`) hace
   `variables.get(key, match.group(0))`. Si la key no está, devuelve la
   coincidencia textual → en el caption final aparece, literalmente,
   `{{unknown_variable}}`.

Resultado en producción: el caption publicado a la red social contendrá
`{{unknown_variable}}` literal, sin error visible. Fallo silencioso.

### Tests existentes para 422 con variable desconocida
**No hay ninguno.** Los tests del router
(`tests/integration/configuration/test_social_templates_router.py`) cubren:

- `test_social_templates_get_returns_empty_when_none_stored` (líneas 18-32)
- `test_social_templates_put_persists_per_platform_rows` (líneas 35-69)
- `test_social_templates_put_replaces_whole_block` (líneas 72-98)
- `test_social_templates_returns_404_for_unknown_agency` (líneas 101-111)

Los tests del use case
(`tests/unit/configuration/test_replace_social_templates.py`) cubren:

- normalización de plataformas (líneas 15-31)
- mapa vacío permitido (líneas 34-41)
- 404 si la agencia no existe (líneas 44-53)

Ningún test alimenta `{{unknown_variable}}` ni espera 422.

---

## 5. Heads-up del working tree

`git status` reporta cambios sin commit en el árbol. Filtrados al scope de la
feature 9 (router + payload + repo + use case + ORM + pipeline relacionado):

| Archivo | Cambio sin commit | Impacto en feature 9 |
|---------|-------------------|---------------------|
| `modules/configuration/transport/http/social_templates_router.py` | Cosmético: añade `pinterest` al texto de descripción del GET (líneas 56-58 del diff). | Trivial. El implementer puede sobrescribir; sin riesgo. |
| `modules/configuration/transport/payloads/social_templates.py` | Cosmético: añade `pinterest` al docstring (línea 14 del diff). | Trivial. |
| `modules/configuration/infrastructure/social_template_repository.py` | Sin cambios. | — |
| `modules/configuration/application/use_cases/read_social_templates.py` | Sin cambios. | — |
| `modules/configuration/application/use_cases/replace_social_templates.py` | Sin cambios. | — |
| `modules/configuration/infrastructure/orm.py` | Sin cambios (no aparece en `git status`). | — |
| `modules/configuration/infrastructure/defaults_repository.py` | Añade `pinterest` al default platforms list (líneas 60-68 del diff). | Si la decisión es DROP `caption_template`, este archivo igual será tocado por la migración → reconciliar es suficiente con `git add -p`. |
| `modules/configuration/transport/payloads/defaults.py` | Añade `pinterest` a ejemplos. | Idem. |
| `modules/configuration/transport/payloads/reel_profile.py` | Añade `pinterest` a ejemplos. | Idem. |
| `modules/configuration/application/use_cases/read_aggregated_reel_profile.py` | Añade `pinterest` a `_DEFAULT_PLATFORMS`. | Si DROP, el `to_public_dict` deja de exponer `caption_template` → cambio independiente. |
| `modules/reels/application/content_generator.py` | Añade `import html` y un `html.unescape(rendered)` al final de `render_template_with_property` (de feature 12). | **Relevante**: si el implementer de feature 9 añade validación contra el catálogo de variables, debe partir de ESTE estado (con el unescape ya integrado). |
| `modules/reels/application/use_cases/regenerate_reel.py` | Añade idempotencia (`active_job` check) + `idempotent_replay` flag. Sin tocar la rama de `social_templates`. | Sin conflicto con feature 9. |
| `modules/reels/application/orchestrator.py` | Modificado (no inspeccionado, fuera del scope directo). | Cuidado por si toca el camino que pasa `templates_by_platform`. |
| `modules/configuration/transport/http/defaults_router.py` | Modificado (cambios menores asociados a pinterest según el patrón). | Si DROP, este archivo recibe el cambio que elimina `caption_template` del serializer. |
| `tests/unit/configuration/test_*` | No aparecen modificados en este momento. | — |
| `tests/integration/configuration/test_defaults_router.py` | Modificado. | Reconciliar antes/durante la edición. |
| `tests/unit/reels/test_regenerate_reel.py` | Modificado (probable feature 12/idempotencia). | Sin conflicto directo. |

Archivos NO en scope que tienen cambios sin commit (informativo): `apps/api/*`,
`apps/worker/main.py`, varios `modules/publishing/*`, varios `modules/delivery/*`,
varios `tests/*`. El implementer no debería tocarlos.

### Resumen de reconciliación
- Cambios no commiteados son uniformemente "añadir pinterest a defaults/ejemplos"
  + el unescape de feature 12 + idempotencia de regenerate_reel. Ninguno
  modifica el contrato de `social_templates`.
- El implementer de feature 9 puede trabajar sobre el árbol actual sin
  rebasar nada. La única atención es cuando edite
  `modules/reels/application/content_generator.py` para añadir validación de
  variables: debe respetar el `html.unescape` ya presente.
- Si la decisión es DROP `caption_template`, el implementer tocará varios
  archivos que ya tienen cambios (defaults_repository, defaults payload,
  defaults router, read_aggregated_reel_profile). No hay conflicto pero conviene
  hacer un commit limpio del trabajo "pinterest" antes de empezar, o asumir que
  el commit de la feature 9 mezclará ambos.

---

## Ficheros clave (paths absolutos)

- `/opt/projects/4Reels-Backend/modules/configuration/transport/http/social_templates_router.py`
- `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/social_templates.py`
- `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/read_social_templates.py`
- `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/replace_social_templates.py`
- `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/social_template_repository.py`
- `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/orm.py`
- `/opt/projects/4Reels-Backend/modules/configuration/domain/agency_settings.py`
- `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/read_aggregated_reel_profile.py`
- `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/defaults_repository.py`
- `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/defaults.py`
- `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/reel_profile.py`
- `/opt/projects/4Reels-Backend/modules/configuration/transport/http/defaults_router.py`
- `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/update_reel_defaults.py`
- `/opt/projects/4Reels-Backend/modules/reels/application/content_generator.py`
- `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/regenerate_reel.py`
- `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/_ingest_property_planning.py`
- `/opt/projects/4Reels-Backend/modules/reels/domain/types.py`
- `/opt/projects/4Reels-Backend/modules/tenancy/transport/http/admin_agencies_router.py`
- `/opt/projects/4Reels-Backend/apps/api/app_factory.py`
- `/opt/projects/4Reels-Backend/tests/integration/configuration/test_social_templates_router.py`
- `/opt/projects/4Reels-Backend/tests/unit/configuration/test_replace_social_templates.py`
- `/opt/projects/4Reels-Backend/tests/unit/reels/test_content_generator_unescape.py`
