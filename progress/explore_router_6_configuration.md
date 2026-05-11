# Explore — Feature 6 `configuration_routers`

> Read-only mapping for the implementer who will extract the five
> `/admin/agencies/{id}/{brand,defaults,automation,social-templates,music}`
> sub-resources from `services/transport/http/server.py` to
> `modules/configuration/transport/http/`.
>
> Cited paths use `path:line`. All file paths are absolute.

---

## 1. Rutas y handlers en `services/transport/http/server.py`

Las rutas ya viven en una sola god-file. La base path es
`application.admin_access_policy.base_path` (= `"/v1/admin"` por configuración
de `apps/api/app_factory.py`).

Patrón uniforme de cada handler:

1. `_get_runtime(request)` — recupera `WordPressWebhookApplication` desde
   `request.app.state.runtime`
   (`c:\Users\4pm\Desktop\4reels\4reels back\services\transport\http\server.py:4012`).
2. `_authorize_admin_request(request, runtime)` → delega en
   `apps/api/admin_auth.authorize_admin_request`
   (`c:\Users\4pm\Desktop\4reels\4reels back\services\transport\http\server.py:4197`).
3. `runtime.get_agency(agency_id=...)` para 404 si no existe agencia.
4. (GET) `runtime.get_reel_profile(...)` + serializer; (PUT) merge + delega en
   `runtime.apply_reel_profile_section(...)` cuyo backend es
   `repositories.stores.reel_profile_store.ReelProfileStore.upsert_for_agency`.
5. Devuelve `JSONResponse` con shape `{agency_id, <section>: ...}` en GET, y
   `{status: "saved", agency_id, <section>: ...}` en PUT.

### 1.1 Brand

- **GET** `f"{base_path}/agencies/{{agency_id}}/brand"`
  - Decorator: `c:\Users\4pm\Desktop\4reels\4reels back\services\transport\http\server.py:2464-2473`
  - Handler `get_agency_brand_settings`: `services\transport\http\server.py:2474-2496`
  - Tags: `["Admin · Brand"]`
  - Deps: `runtime.get_agency`, `runtime.get_reel_profile`,
    `_serialize_brand_section`
  - Body: ninguno
- **PUT** `f"{base_path}/agencies/{{agency_id}}/brand"`
  - Decorator: `services\transport\http\server.py:2498-2510`
  - Handler `update_agency_brand_settings`: `services\transport\http\server.py:2511-2568`
  - Body: `BrandSettingsUpsertPayload` (Pydantic)
  - Lógica: lee `extras["brand"]` previo, merge campo a campo
    (`font, tagline, watermark_enabled, outro_enabled, outro_headline,
    outro_sub`), llama
    `runtime.apply_reel_profile_section(extras_key="brand",
    top_level={brand_primary_color, brand_secondary_color, logo_position})`.
  - Excepciones manejadas: `ApplicationError` → 500 (code
    `BRAND_SAVE_FAILED`).

### 1.2 Defaults

- **GET** `f"{base_path}/agencies/{{agency_id}}/defaults"`
  - Decorator: `services\transport\http\server.py:2577-2587`
  - Handler `get_agency_reel_defaults`: `services\transport\http\server.py:2588-2610`
- **PUT** `f"{base_path}/agencies/{{agency_id}}/defaults"`
  - Decorator: `services\transport\http\server.py:2612-2622`
  - Handler `update_agency_reel_defaults`: `services\transport\http\server.py:2623-2674`
  - Body: `ReelDefaultsUpsertPayload`
  - Lógica: si `payload.settings` es un dict, mezcla
    `{**existing_defaults, **payload.settings}` (merge superficial),
    `top_level={intro_enabled, duration_seconds}`. Code de error:
    `REEL_DEFAULTS_SAVE_FAILED`.

### 1.3 Automation

- **GET** `f"{base_path}/agencies/{{agency_id}}/automation"`
  - Decorator: `services\transport\http\server.py:2683-2693`
  - Handler `get_agency_automation_rules`: `services\transport\http\server.py:2694-2716`
- **PUT** `f"{base_path}/agencies/{{agency_id}}/automation"`
  - Decorator: `services\transport\http\server.py:2718-2728`
  - Handler `update_agency_automation_rules`: `services\transport\http\server.py:2729-2792`
  - Body: `AutomationRulesUpsertPayload`
  - Lógica: merge campo a campo (`review_window_enabled, review_window_hours,
    quiet_hours_enabled, skip_weekends, auto_captions, regen_on_update,
    review_emails`); `publish_mode == "review"` → `approval_required = True`;
    `top_level={approval_required, platforms}`. Code: `AUTOMATION_SAVE_FAILED`.

### 1.4 Social templates

- **GET** `f"{base_path}/agencies/{{agency_id}}/social-templates"`
  - Decorator: `services\transport\http\server.py:2800-2809`
  - Handler `get_agency_social_templates`: `services\transport\http\server.py:2810-2832`
- **PUT** `f"{base_path}/agencies/{{agency_id}}/social-templates"`
  - Decorator: `services\transport\http\server.py:2834-2842`
  - Handler `update_agency_social_templates`: `services\transport\http\server.py:2843-2887`
  - Body: `SocialTemplatesUpsertPayload`
  - Lógica: normaliza claves `key.strip().lower()`, REEMPLAZA todo el bloque
    `extras_key="social_templates"` (no merge). Code: `SOCIAL_TEMPLATES_SAVE_FAILED`.

### 1.5 Music

> **Atención:** la ruta actual en `server.py` es `/agencies/{id}/music-tracks`
> (lista únicamente, **stub**, devuelve siempre `{items: [], implemented: false}`).
> No existe `GET/PUT /agencies/{id}/music` ni `update_music`. La feature 6
> pide router `music_router.py` montado en `/admin/agencies/{id}/music` con
> `get_music + update_music`. Ver §11 (riesgos).

- **GET** `f"{base_path}/agencies/{{agency_id}}/music-tracks"`
  - Decorator: `services\transport\http\server.py:3449-3459`
  - Handler `list_admin_agency_music_tracks`: `services\transport\http\server.py:3460-3486`
  - Body: ninguno. Devuelve stub fijo. **No** lee de
    `agency_music_tracks` (¡aunque la tabla y el repo existen!).
- **PUT** /music: **no existe en server.py.**

---

## 2. Aggregates de configuración

Las cinco secciones viven en **cinco tablas separadas**, no en una tabla
`agency_configuration`. No hay aggregate raíz por agencia: cada sección es su
propio aggregate, lo cual está alineado con el guideline en
`modules/configuration/domain/agency_settings.py:1-10` («cada sección es su
propio aggregate para que su admin form pueda guardar sin tocar las otras»).

### Modelos SQLAlchemy (Phase 2, ya migrados)

`c:\Users\4pm\Desktop\4reels\4reels back\modules\configuration\infrastructure\orm.py`

| Sección           | ORM class                        | Tabla                       | Línea (orm.py) |
|-------------------|----------------------------------|-----------------------------|----------------|
| brand             | `AgencyBrandSettingsORM`         | `agency_brand_settings`     | 20             |
| defaults          | `AgencyReelDefaultsORM`          | `agency_reel_defaults`      | 46             |
| automation        | `AgencyAutomationRulesORM`       | `agency_automation_rules`   | 80             |
| social_templates  | `AgencySocialTemplateORM`        | `agency_social_templates`   | 109            |
| music             | `AgencyMusicTrackORM`            | `agency_music_tracks`       | 130            |

### Aggregates de dominio (value objects)

`c:\Users\4pm\Desktop\4reels\4reels back\modules\configuration\domain\agency_settings.py`

| Sección           | Dataclass            | Línea |
|-------------------|----------------------|-------|
| brand             | `BrandSettings`      | 18    |
| defaults          | `ReelDefaults`       | 31    |
| automation        | `AutomationRules`    | 44    |
| social_templates  | `SocialTemplate`     | 56    |
| music             | `MusicTrack`         | 67    |

### Tabla legacy intermedia

`reel_profiles` (legacy, all-in-one) sigue existiendo en
`c:\Users\4pm\Desktop\4reels\4reels back\repositories\postgres\models\__init__.py:322`.
El store legacy `ReelProfileStore`
(`c:\Users\4pm\Desktop\4reels\4reels back\repositories\stores\reel_profile_store.py:88-345`,
347 LoC) **YA NO escribe** en `reel_profiles` directamente — compone vía las
tablas tipadas (brand/defaults/automation). Pero los handlers actuales lo
siguen llamando vía `runtime.apply_reel_profile_section` que internamente usa
`unit_of_work.reel_profile_store.upsert_for_agency`
(`services\transport\http\server.py:1019-1034`).

**Implicación clave**: el store legacy mete TODO el JSON de `extra_settings`
(brand/defaults/automation/social_templates) dentro de la columna
`agency_reel_defaults.settings` (jsonb). Esto significa que las pruebas
actuales de los handlers leen las secciones desde `extra_settings_json`,
no desde las tablas tipadas. Los nuevos use cases deben elegir entre:

- **Opción A — clean migration**: cada use case llama el repo correspondiente
  (`uow.configuration.brand`, `uow.configuration.defaults`, etc.). Los datos
  se persisten en sus tablas tipadas. Esto rompe `to_public_dict()` y los
  serializadores que leen `extras["brand"]`, `extras["defaults"]`, etc.
- **Opción B — bridge**: los use cases siguen llamando `ReelProfileStore`
  (vía un repo en `modules/configuration/infrastructure/`) por compatibilidad.
  Mismo comportamiento, solo se mueve el transport.

> Recomendación: **Opción B** para esta feature. La feature 6 está acotada a
> «extraer el transport». La migración del store legacy debería ser una
> feature aparte (no aparece todavía en `feature_list.json`). Si se intenta
> Opción A en una sola sesión, el blast radius incluye los serializers
> `_serialize_*_section` y todas las tests de
> `tests/integration/test_http_transport.py` que comprueban el contenido de
> `extra_settings`.

---

## 3. Repositorio existente para configuration

Hay **dos capas** vivas en paralelo:

### 3.1 Capa Phase 2 — `modules/configuration/infrastructure/`

Cada sección tiene su `Repository` que extiende `ModuleRepository` y trabaja
con SQLAlchemy `Session` (no llama `commit`).

| Repo                                    | Path:line                                                                  | Métodos                                       |
|-----------------------------------------|----------------------------------------------------------------------------|-----------------------------------------------|
| `BrandSettingsRepository`               | `modules\configuration\infrastructure\brand_repository.py:10`              | `get(agency_id)`, `upsert(...)`              |
| `ReelDefaultsRepository`                | `modules\configuration\infrastructure\defaults_repository.py:17`           | `get(agency_id)`, `upsert(...)`              |
| `AutomationRulesRepository`             | `modules\configuration\infrastructure\automation_repository.py:12`         | `get(agency_id)`, `upsert(...)`              |
| `SocialTemplatesRepository`             | `modules\configuration\infrastructure\social_template_repository.py:12`    | `list_for_agency`, `get(agency_id, platform)`, `upsert(...)`, `delete(...)` |
| `MusicTracksRepository`                 | `modules\configuration\infrastructure\music_track_repository.py:10`        | `list_for_agency`, `add_track(...)`, `delete(music_id)` |

Compatibility export:
`modules\configuration\infrastructure\agency_settings_repository.py:1-23`.

Helpers compartidos en
`modules\configuration\infrastructure\repository_helpers.py:1-50`
(`isoformat`, `list_param`, `jsonb_to_mapping`, `mapping_to_jsonb`,
`normalize_text_tuple`).

### 3.2 Namespace en el UoW

`shared\db\uow.py:91-98` y `:153-159`:
```python
@dataclass(slots=True)
class ConfigurationNamespace:
    brand: BrandSettingsRepository
    defaults: ReelDefaultsRepository
    automation: AutomationRulesRepository
    social_templates: SocialTemplatesRepository
    music: MusicTracksRepository
```
Listo para usar como `uow.configuration.brand.upsert(...)` etc.

### 3.3 Capa legacy — `repositories/stores/reel_profile_store.py`

`ReelProfileStore` (`repositories\stores\reel_profile_store.py:88-345`,
347 LoC).
- `get_by_agency_id(agency_id) -> ReelProfileRecord | None` (línea 97)
- `upsert_for_agency(...) -> ReelProfileRecord` (línea 103) — escribe a
  `agency_brand_settings`, `agency_reel_defaults`, `agency_automation_rules`
  (NO escribe `agency_social_templates` ni `agency_music_tracks`).
- `delete_by_agency_id(agency_id) -> bool` (línea 262) — limpia las 4 tablas.

Nota: este store guarda `social_templates` indirectamente bajo
`agency_reel_defaults.settings.social_templates` (jsonb), no en la tabla
`agency_social_templates`. Es un compromiso temporal.

---

## 4. Use cases sugeridos

10 use cases, en `modules/configuration/application/use_cases/`. Nomenclatura
verbo-recurso, un archivo por uso:

| Archivo (sugerido)                             | Clase                              | Responsabilidad                                                |
|------------------------------------------------|------------------------------------|----------------------------------------------------------------|
| `get_brand.py`                                 | `GetBrandUseCase`                  | `uow.configuration.brand.get(agency_id)` + 404 si agencia no existe |
| `update_brand.py`                              | `UpdateBrandUseCase`               | merge + `uow.configuration.brand.upsert(...)` (Opción A) o `apply_reel_profile_section(extras_key="brand", ...)` (Opción B) |
| `get_defaults.py`                              | `GetDefaultsUseCase`               | idem `defaults`                                                |
| `update_defaults.py`                           | `UpdateDefaultsUseCase`            | idem `defaults`                                                |
| `get_automation.py`                            | `GetAutomationUseCase`             | idem `automation`                                              |
| `update_automation.py`                         | `UpdateAutomationUseCase`          | idem; mapear `publish_mode` → `approval_required`              |
| `get_social_templates.py`                      | `GetSocialTemplatesUseCase`        | usa `social_templates.list_for_agency` (Opción A) o serializa `extras["social_templates"]` (Opción B) |
| `update_social_templates.py`                   | `UpdateSocialTemplatesUseCase`     | reemplaza el bloque completo                                   |
| `get_music.py`                                 | `GetMusicUseCase`                  | `music.list_for_agency` (devolver `items[]`)                   |
| `update_music.py`                              | `UpdateMusicUseCase`               | **A definir** — ver §11. La PUT no existe hoy. Posible: bulk replace de la lista, o create/delete por `music_id`. |

### Validación cross-section / defaults compartidos

- **`platforms`** se usa en defaults (`agency_reel_defaults.platforms`) Y en
  automation (`top_level["platforms"]` del legacy store apunta también a
  `agency_reel_defaults.platforms`). Hoy hay desacople porque
  `apply_reel_profile_section` para `automation` mete `platforms` en
  `top_level` (que el legacy store re-redirige a `agency_reel_defaults`). Si
  se hace Opción A, hay que decidir quién es dueño de `platforms` (idealmente
  `defaults`). Riesgo de doble escritura si dos use cases lo tocan.
- **`music_id`** vive en `agency_reel_defaults.music_id`. La sección defaults
  ya lo expone implícitamente. Si el `update_music` añade tracks a
  `agency_music_tracks` y luego el frontend selecciona uno como `music_id`
  por defecto, hay un acoplamiento defaults ⇄ music.
- **No hay validación cruzada** explícita en los handlers actuales más allá
  de la 404 sobre `agencies`.

---

## 5. Payloads Pydantic existentes

Todos viven en `services\transport\http\server.py`. Hay que moverlos a
`modules/configuration/transport/payloads/<section>.py` (o uno por archivo;
la convención del repo es `transport/payloads/`).

| Payload                              | Path:start-end (server.py)                                                  |
|--------------------------------------|-----------------------------------------------------------------------------|
| `BrandSettingsUpsertPayload`         | `services\transport\http\server.py:348-417`                                 |
| `ReelDefaultsUpsertPayload`          | `services\transport\http\server.py:420-475`                                 |
| `AutomationRulesUpsertPayload`       | `services\transport\http\server.py:478-552`                                 |
| `SocialTemplatesUpsertPayload`       | `services\transport\http\server.py:555-584`                                 |

`MusicUpsertPayload`: **no existe**. Implementer debe diseñarlo. Sugerencia
mínima:
```python
class MusicTrackUpsertItem(BaseModel):
    music_id: str | None = None  # generated if absent
    display_name: str
    object_key: str
    duration_seconds: int
    is_default: bool = False

class MusicUpsertPayload(BaseModel):
    tracks: list[MusicTrackUpsertItem]
```

### Atención a shapes complejos

- **`SocialTemplatesUpsertPayload.templates`**
  (`services\transport\http\server.py:577`): es `dict[str, str]`, las claves
  son plataformas. El handler normaliza `key.strip().lower()`. La tabla
  `agency_social_templates` tiene PK compuesta `(agency_id, platform)` y
  campos extra `description_template`, `title_template`, `hashtags`. Si se
  hace Opción A, hay que decidir cómo mapear `templates: {ig: "..."}`
  (one-line) a `(description_template, title_template, hashtags)`. Hoy el
  legacy guarda solo el string crudo en `extras["social_templates"]`. Probable
  decisión: Opción B en feature 6, redesign en feature aparte.
- **`ReelDefaultsUpsertPayload.settings`**
  (`services\transport\http\server.py:467`): `dict | None` libre. El
  frontend manda objeto INITIAL_DEFAULTS con `currency, language, aspect,
  resolution, fps, subFont, subSize, subBgStyle, musicVolume, kenBurns,
  introCard, outroCard`. Se almacena verbatim.

---

## 6. Helpers transversales que invocan

| Helper                              | Definición                                                                                                  | Uso                                                  |
|-------------------------------------|--------------------------------------------------------------------------------------------------------------|------------------------------------------------------|
| `_get_runtime`                      | `services\transport\http\server.py:4012`                                                                     | Acceso a `WordPressWebhookApplication`               |
| `_authorize_admin_request`          | `services\transport\http\server.py:4197` (wrapper sobre `apps.api.admin_auth.authorize_admin_request:59`)    | Auth bearer token admin                              |
| `_json_error`                       | re-export de `apps.api.error_handlers.json_error` (`services\transport\http\server.py:93`)                   | Respuestas error consistentes                        |
| `_serialize_brand_section`          | `services\transport\http\server.py:4041`                                                                     | GET brand                                            |
| `_serialize_defaults_section`       | `services\transport\http\server.py:4060`                                                                     | GET defaults                                         |
| `_serialize_automation_section`     | `services\transport\http\server.py:4074`                                                                     | GET automation                                       |
| `_serialize_social_templates`       | `services\transport\http\server.py:4093`                                                                     | GET social-templates                                 |
| `runtime.get_agency`                | `services\transport\http\server.py:1040`                                                                     | 404 check                                            |
| `runtime.get_reel_profile`          | `services\transport\http\server.py:984`                                                                      | Lectura legacy                                       |
| `runtime.apply_reel_profile_section`| `services\transport\http\server.py:998`                                                                      | Escritura legacy                                     |

`apps.api.admin_auth.AdminAccessPolicy`
(`apps\api\admin_auth.py:24`) ya está disponible para que el router lo
inyecte como dependencia. El base path se obtiene del settings
`ADMIN_API_BASE_PATH` (importado en `apps\api\app_factory.py:11`).

`ApplicationError` y `ValidationError` están en
`shared\errors\__init__.py` (re-export desde `core.errors`).

---

## 7. Imports cruzados peligrosos

1. **`runtime.apply_reel_profile_section` apunta a
   `unit_of_work.reel_profile_store`** que es el store legacy en
   `repositories/stores/reel_profile_store.py`. El nuevo módulo
   `modules/configuration/transport/http/` **no debe importar** de
   `repositories/`. Si se opta por Opción B (bridge), hay que crear un
   adapter wrapper en `modules/configuration/infrastructure/` que use el UoW
   nuevo (`shared.db.uow.DatabaseUnitOfWork`) y replique el comportamiento
   de merge. Si se opta por Opción A, el bridge se evita pero hay que
   actualizar serializers.
2. **`apps.api.admin_auth`** ya es legítimo (es shared infra).
3. **`services.transport.http.openapi_docs`** y `services.transport.http.security`
   solo se usan en el server legacy, no relevantes para el router nuevo.
4. **`from core.errors import ApplicationError, ValidationError`**: usar
   `from shared.errors import ApplicationError, ValidationError` en el código
   nuevo.
5. **No debe haber import desde
   `modules/configuration/transport/` hacia
   `services/transport/http/server.py`**. Las 5 funciones de serialización
   (`_serialize_*_section`) deben copiarse a
   `modules/configuration/transport/http/_serializers.py` (o equivalente),
   **no importarse** desde `server.py`.

---

## 8. Tests existentes

Solo un fichero toca estas rutas hoy:

`c:\Users\4pm\Desktop\4reels\4reels back\tests\integration\test_http_transport.py`

| Test                                                              | Línea | Ruta probada                              |
|-------------------------------------------------------------------|-------|-------------------------------------------|
| `test_brand_endpoint_only_touches_its_section`                    | 451   | PUT `/v1/admin/agencies/{id}/brand`       |
| `test_automation_endpoint_drives_approval_required`               | 487   | PUT `/v1/admin/agencies/{id}/automation`  |
| `test_social_templates_endpoint_persists_per_network_templates`   | 512   | PUT `/v1/admin/agencies/{id}/social-templates` |
| `test_admin_music_tracks_endpoint_advertises_unimplemented_state` | 553   | GET `/v1/admin/agencies/{id}/music-tracks` |

No hay tests directos para defaults, ni para el GET de brand/automation/social-templates.

Los tests usan `ReelProfileStore` directamente para verificar la persistencia
(`tests\integration\test_http_transport.py:459, 478, 506, 530`). Si la
implementación migra a Opción A, estos tests se vuelven inválidos: hay que
sustituir las verificaciones por queries a la tabla tipada o a través de
`uow.configuration.<section>`.

No existen tests bajo `tests/unit/configuration/` ni `tests/integration/configuration/`
(la feature debe crearlos según acceptance criteria).

---

## 9. Acoplamiento cross-feature con feature 7 (reels admin)

Sí — los reels heredan configuración por agencia, pero **no necesariamente**
por las mismas rutas:

- `services\transport\http\server.py:1158-1175` y `:3642-3675`: cuando el
  pipeline construye un `SocialPublishContext`, llama
  `runtime.get_reel_profile(agency_id=...)` para extraer:
  - `reel_profile.platforms` (defaults)
  - `reel_profile.approval_required` (automation)
  - `reel_profile.extra_settings["social_templates"]`
- `_serialize_agency_summary` (`services\transport\http\server.py:4146`) lo
  usa el endpoint de **agencias** (feature 3), no el de reels (feature 7).
  Lee `reel_profile.to_public_dict()`.
- Feature 7 (reels admin: `/admin/agencies/{id}/reels`) no escribe
  configuración; solo lee. La interferencia es mínima: comparten el
  `ReelProfileStore` legacy para lectura.

**Riesgo concreto**: si feature 6 elimina `runtime.get_reel_profile` /
`runtime.apply_reel_profile_section`, los handlers de reels y el endpoint
`GET /admin/agencies/{id}` (resumen) se rompen. Recomendación: feature 6 NO
elimina esos métodos en `WordPressWebhookApplication`, solo deja de
exponer las cinco rutas. Esos métodos del runtime los retira la feature 9
(`retire_wordpress_webhook_server`).

---

## 10. LoC estimado a mover

### Desde `services/transport/http/server.py` (origen)

| Bloque                                   | Líneas              | LoC |
|------------------------------------------|---------------------|-----|
| `BrandSettingsUpsertPayload`             | 348-417             | 70  |
| `ReelDefaultsUpsertPayload`              | 420-475             | 56  |
| `AutomationRulesUpsertPayload`           | 478-552             | 75  |
| `SocialTemplatesUpsertPayload`           | 555-584             | 30  |
| Handlers brand (GET+PUT)                 | 2457-2568           | 112 |
| Handlers defaults (GET+PUT)              | 2570-2674           | 105 |
| Handlers automation (GET+PUT)            | 2676-2792           | 117 |
| Handlers social-templates (GET+PUT)      | 2794-2887           | 94  |
| Handler music-tracks (GET stub)          | 3449-3486           | 38  |
| Serializadores brand/defaults/auto/social| 4036-4099           | 64  |
| **Subtotal mover**                       |                     | **~761 LoC** |

### Adicional (nuevo código)

| Pieza                                      | LoC estimado |
|--------------------------------------------|--------------|
| `brand_router.py`                          | ~120         |
| `defaults_router.py`                       | ~110         |
| `automation_router.py`                     | ~120         |
| `social_templates_router.py`               | ~100         |
| `music_router.py`                          | ~120 (incluye PUT nueva) |
| `payloads/{brand,defaults,automation,social_templates,music}.py` | ~280 |
| 10 use cases (`modules/configuration/application/use_cases/`) | ~500 |
| Serializers reubicados                     | ~80          |
| Tests unit (10 use cases × ~40)            | ~400         |
| Tests integration (5 routers × ~80)        | ~400         |
| **Subtotal nuevo**                         | **~2230 LoC**|

### Total impactado

`~761` LoC removidos + `~2230` LoC nuevos = **~3000 LoC** de superficie de
cambio. Esta es la feature MÁS pesada de las 7 (2-8) por amplia diferencia.

---

## 11. Riesgos y blockers

### Riesgos técnicos

1. **GAP funcional `/music`**. La feature 6 pide
   `GET/PUT /admin/agencies/{id}/music` con use cases `get_music` +
   `update_music`. Hoy:
   - Solo existe `GET /admin/agencies/{id}/music-tracks` (stub vacío).
   - El path nuevo es `/music` (singular), distinto del actual `/music-tracks`.
   - No hay shape Pydantic ni endpoint PUT.
   - El frontend usa el stub para mostrar «Music library is not yet wired»
     (`services\transport\http\server.py:3454-3458`).
   - **Decisión necesaria del leader**: ¿se renombra
     `/music-tracks` → `/music` (rompe el frontend) o el router nuevo expone
     ambas rutas en transición? ¿`update_music` reemplaza la lista o añade
     items? Esto debería resolverse antes de arrancar.
2. **GAP `/defaults` GET no tiene test**. Implementer debe añadirlos sin
   referencia previa.
3. **Acoplamiento al store legacy `ReelProfileStore`**. Los handlers actuales
   pasan por `runtime.apply_reel_profile_section` que llama
   `unit_of_work.reel_profile_store` (= `repositories/stores/`). El módulo
   nuevo no puede importar de `repositories/`. Hay dos rutas:
   - **Opción B (bridge)**: el use case acepta un colaborador que es la
     instancia de `WordPressWebhookApplication` (vía `request.app.state.runtime`).
     Mantenemos la lógica de merge actual hasta que feature 9 retire el
     runtime. El módulo configuration **NO** importa el store legacy; lo hace
     el router con un dep `Depends(get_runtime)`. Aceptable como bridge
     temporal, pero hace que la app de configuración importe el runtime
     legacy.
   - **Opción A (cleanup)**: use cases reciben `DatabaseUnitOfWork` y llaman
     `uow.configuration.<section>.upsert(...)`. Se rompe el contrato actual
     porque los serializers leen `extras["brand"]`, `extras["defaults"]`,
     etc. — hay que rediseñar `_serialize_*` para leer de los aggregates
     tipados, y los tests actuales (que verifican vía `ReelProfileStore`) hay
     que reemplazarlos por verificación de las tablas tipadas. **Esto excede
     el scope de "extraer router"**.
4. **`platforms` y `approval_required` están "en dos sitios"**. El handler
   automation actual escribe `platforms` y `approval_required` como
   `top_level` (que el legacy redirige a `agency_reel_defaults` y
   `agency_automation_rules`). Si se va Opción A puro, `update_automation`
   tendría que escribir tanto en `automation` (approval) como en `defaults`
   (platforms). Esto rompe la regla "un use case = un aggregate". Hay que
   decidir si `platforms` se mueve a un endpoint distinto.
5. **`SocialTemplatesUpsertPayload.templates` es plano (string)** mientras
   que la tabla `agency_social_templates` tiene shape rico
   (`description_template`, `title_template`, `hashtags`). Migrar de Opción B
   a Opción A requiere ampliar el contrato HTTP y coordinar con frontend.

### Riesgos de scoping / volumen

- LoC total impactado: **~3000**. Es 4-5x más que feature 2
  (sessions_router) o feature 5 (connections_router).
- 10 use cases nuevos. Las features 2-5 introducen 1-5 use cases cada una.
- Si la sesión de implementer se cae a la mitad, se queda con el server.py
  legacy + 2 routers extraídos pero los otros 3 handlers todavía vivos —
  estado intermedio publicable, pero no cierra la feature.

### Recomendación al leader

**Partir feature 6 en sub-tareas independientes para tres
implementer-passes**, no en una sola sesión:

1. **6a — clean read-side (Opción B-bridge)**: extraer los 5 routers solo
   con los GET, deps al runtime legacy, payloads en
   `modules/configuration/transport/payloads/`, use cases `get_*` (5 use
   cases). Tests unit de los 5 GET + smoke integration. ~600 LoC.
2. **6b — write-side**: añadir los 5 PUT (4 existentes + 1 nuevo `update_music`),
   use cases `update_*` (5 use cases). Decidir y documentar Opción A vs B
   (ver §11.3 — recomiendo B para 6b). ~700 LoC.
3. **6c — opcional, no requerido para Phase 2**: migrar Opción B → Opción A
   eliminando el bridge al `ReelProfileStore`. Esto solo tiene sentido tras
   feature 9 (retire `WordPressWebhookServer`). Marcarlo como feature aparte
   en `feature_list.json` o esperar a Phase 3.

Sub-tarea adicional **bloqueante antes de 6**: el leader debe responder en
un comentario/issue:

- Q1: ¿Qué shape tiene `MusicUpsertPayload` (bulk replace vs append/delete)?
  ¿Cambia el path a `/music` o se mantiene `/music-tracks`?
- Q2: ¿Opción A o Opción B para 6b? Mi recomendación es B (bridge).
- Q3: ¿Quién es dueño de `platforms` y `approval_required` en
  Opción A si la feature 6c llega? (recomendación: `defaults` y `automation`
  respectivamente; ya están bien repartidos en las tablas tipadas).

Si las tres respuestas son claras, **6 puede ejecutarse en una sola sesión
si el implementer dispone de >= 4-6h de tiempo y tolera ~3000 LoC de
diff**. Pero el riesgo de regresión es alto y el reviewer va a sufrir. Mi
recomendación firme es **partirla en 6a + 6b**.

---

### Apéndice — referencias rápidas para el implementer

- Pattern de ruta admin existente para mirar:
  `services\transport\http\server.py:2464-2568` (brand GET+PUT) — copia
  fiel del esqueleto a usar.
- UoW namespace listo:
  `shared\db\uow.py:91-98, 153-159` (`uow.configuration.{brand,defaults,
  automation,social_templates,music}`).
- Auth helper para el router: `apps\api\admin_auth.py:59`.
- Error handler: `apps\api\error_handlers.json_error`.
- App factory donde registrar los routers nuevos: `apps\api\app_factory.py:60`.
- Settings base path: `ADMIN_API_BASE_PATH` (= `/v1/admin`).
- Acceptance: ver `feature_list.json:106-122`.
