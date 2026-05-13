# Feature 11b · Approve response shape para `scheduled_at`

> Spike read-only para soportar el mirror del front: "Publicará el dd/mm/yyyy a las HH:MM"
> después de un approve cuando el back devuelva `scheduled_at`.
> Fecha del spike: 2026-05-13.

## TL;DR

1. **Endpoint**: `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve`
   (no `{slug}`).
2. **Response 200 actual**: `JSONResponse` directo (no Pydantic model).
   Tres formas según el caso (enqueue OK / replay idempotente / sin prerequisitos).
3. **Cálculo de `scheduled_at` viable en el approve**: sí, todos los datos están
   en mano (rules cargadas en `regenerate_reel.py:183`, `now_utc` trivial). Solo
   hay que dejar de hacer `del automation` y threadearlo por el `publish_context`
   y al `RegenerateReelResult` para que el handler lo devuelva.
4. **Idempotent replay**: cuando hay un `active_job` (queued/processing) se devuelve
   el `event_id`/`job_id` del job original y `idempotent_replay=True`. Hoy **no se
   guarda `scheduled_at` en jobs**, así que en replay no hay forma de devolver el
   slot original sin un cambio de schema (o re-calcularlo con la misma fórmula y
   `created_at` del job, que es lo más limpio).
5. **Heads-up working tree**: ya hay cambios sin commit que añaden idempotencia
   (`active_job` + `idempotent_replay`) en el use case y el handler. Feature 11b
   debe encadenarse encima de ese diff.

---

## 1) Endpoint del approve

- Path exacto: `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve`
  - El prefijo `/v1/admin` viene del `AdminAccessPolicy.base_path`. Default en
    `settings/app.py:217-218` (`ADMIN_API_BASE_PATH=/v1/admin`).
  - **No** existe `{slug}` en el path. La identidad del reel es
    `(site_id, source_property_id)` (PK compuesta de `reels`).
- Archivo del router + número de línea del handler:
  - Decorador `@router.post`: `modules/reels/transport/http/admin_reels_router.py:163-178`.
  - Función `approve_admin_agency_reel`: `modules/reels/transport/http/admin_reels_router.py:179-221`.
- Auth / middleware:
  - `apps/api/admin_auth.py:50-88` `AdminAccessPolicy`/`build_admin_access_policy`.
  - Validación: `apps.api.admin_auth.authorize_admin_request(request, admin_access_policy)`
    invocada en la línea 185 del handler (mismo patrón que el resto de
    `/v1/admin/*`: bearer admin global o JWT agency-scoped, ver `admin_auth.py:134`).
- Mount: `apps/api/app_factory.py:385` (`create_admin_reels_router(...)`); base
  path inyectado vía `admin_access_policy.base_path`.

## 2) Shape del response actual

Tipo: `JSONResponse` con `status_code=200` y un `dict[str, object]` construido
inline en el handler (`admin_reels_router.py:208-221`). **No hay Pydantic model**
para el response — el front lo consume como dict opaco.

### 2a) Caso "publish_enqueued=True" (camino feliz, primer click)

```json
{
  "status": "approved",
  "publish_enqueued": true,
  "reel": { /* AgencyReelSummary serializado, ver §2d */ },
  "event_id": "<uuid4>",
  "job_id": "<uuid4>"
}
```

Construcción exacta:

- `admin_reels_router.py:208-215` arma `body` con
  `status="approved"`, `publish_enqueued=result.publish_enqueued`,
  `reel=_serialize_agency_reel(result.reel)`.
- `admin_reels_router.py:213-215` añade `event_id` y `job_id` (no `idempotent_replay`).

### 2b) Caso "idempotent_replay" (working tree, ver §5)

Igual que 2a pero con un campo extra:

```json
{
  "status": "approved",
  "publish_enqueued": true,
  "reel": { ... },
  "event_id": "<uuid4 del job original>",
  "job_id": "<uuid4 del job original>",
  "idempotent_replay": true
}
```

- `admin_reels_router.py:216-217` solo añade `idempotent_replay` cuando vale `True`
  (omitido si `False`; el front debe tratar la ausencia como `false`).
- Test que pinea esta forma: `tests/integration/reels/test_admin_reels_router.py:432-505`
  (`test_approve_replays_existing_queued_job_for_same_property` y
  `test_approve_is_idempotent_when_active_job_already_exists` en :520-611).

### 2c) Caso "publish_enqueued=False" (prerequisitos faltantes)

```json
{
  "status": "approved",
  "publish_enqueued": false,
  "reel": { ... },
  "reason": "PUBLISH_PREREQUISITES_MISSING",
  "hint": "The reel was marked as approved, but no publish job was queued because either the original WordPress payload or the agency's GHL connection is missing."
}
```

- `admin_reels_router.py:218-220` rama `else`.
- `RegenerateReelResult.reason="PUBLISH_PREREQUISITES_MISSING"` viene de
  `regenerate_reel.py:48-52,158-163`.
- Aquí el state del reel se ha movido igual a `workflow_state='approved'` /
  `publish_status='pending_publish'` (regenerate_reel.py:103-116) — el front
  debe mostrar la columna "approved" pese a no haber slot.

### 2d) Shape del subobjeto `reel`

`_serialize_agency_reel` está en `modules/reels/transport/http/admin_reels_assets.py:42-70`.
Claves (tipos del `AgencyReelSummary`):

| clave                          | tipo            | notas                                  |
|--------------------------------|-----------------|----------------------------------------|
| site_id                        | str             | mismo que `external_source_id`         |
| source_property_id             | int             |                                        |
| slug                           | str             |                                        |
| title                          | str             |                                        |
| link                           | str             | URL pública                            |
| price                          | str             | etiqueta legible                       |
| property_status                | str             | for_sale / to_let / sold / …           |
| property_type_label            | str             |                                        |
| property_area_label            | str             |                                        |
| property_county_label          | str             |                                        |
| bedrooms                       | int             |                                        |
| bathrooms                      | int             |                                        |
| featured_image_url             | str \| null     |                                        |
| agent_name                     | str             |                                        |
| workflow_state                 | str             | "approved" tras el POST                |
| publish_status                 | str             | "pending_publish" tras el POST         |
| render_status                  | str             |                                        |
| last_published_location_id     | str             |                                        |
| current_revision_id            | str \| null     |                                        |
| pipeline_updated_at            | str (ISO)       |                                        |
| pipeline_created_at            | str (ISO)       |                                        |
| fetched_at                     | str (ISO)       |                                        |
| revision_media_path            | str             |                                        |
| revision_metadata_path         | str             |                                        |
| revision_artifact_kind         | str             |                                        |
| revision_created_at            | str (ISO)       |                                        |

Definición del dataclass: `modules/reels/infrastructure/reel_query.py:53` (clase
`AgencyReelSummary`, leída entre :53-160).

### 2e) Errores

| Código | Excepción                | Quién la lanza |
|--------|--------------------------|----------------|
| 404    | `ResourceNotFoundError`  | `ensure_agency_exists` (regenerate_reel.py:84) o el `_load_reel_summary` (regenerate_reel.py:271-294) |
| 400    | `ValidationError`        | `regenerate_reel.py` no lo lanza directamente pero el handler lo captura (admin_reels_router.py:198-205) — defensivo |
| 500    | `ApplicationError`       | catch-all (admin_reels_router.py:206-207) |

Para los 4xx hay un `code` y `hint` opcionales (formato uniforme de `apps/api/error_handlers.json_error`).

## 3) Use case que orquesta el approve

- Archivo: `modules/reels/application/use_cases/regenerate_reel.py`.
- Clase: `RegenerateReelUseCase` (regenerate_reel.py:55-294).
- Firma: `execute(*, uow, agency_id, site_id, source_property_id) -> RegenerateReelResult`
  (regenerate_reel.py:67-74).
- DTO devuelto: `RegenerateReelResult` (regenerate_reel.py:37-45).

  ```python
  @dataclass(frozen=True, slots=True)
  class RegenerateReelResult:
      publish_enqueued: bool
      reel: AgencyReelSummary
      event_id: str | None = None
      job_id: str | None = None
      reason: str | None = None
      hint: str | None = None
      idempotent_replay: bool = False  # añadido por el working tree
  ```

- Persistencia del job: `regenerate_reel.py:244-262` llama a
  `uow.delivery.jobs.enqueue_job(JobEnqueueRequest(...))`. El `publish_context`
  se construye en `regenerate_reel.py:202-208` y se serializa a JSONB en la
  fila `jobs.publish_context_json` (ver `modules/delivery/infrastructure/job_repository.py:108-125`).
- **Aquí NO se crea aún el `PropertyContext`**. Eso ocurre tarde en el worker
  (`build_property_media_job` → `IngestPropertyIntoReelUseCase`), no en el approve.
  El `publish_context` (snake_case, JSONB del job) es distinto del `PropertyContext.publish_context`
  (objeto `SocialPublishContext` que vive en memoria durante el pipeline).

## 4) Datos disponibles en el approve handler

Cuando el handler responde 200, el use case ya tiene en mano (justo antes de
los `uuid4()` de event/job en :217-218):

| Disponible                                      | Origen / línea                                        |
|-------------------------------------------------|-------------------------------------------------------|
| `defaults: ReelDefaults`                        | regenerate_reel.py:182                                |
| `automation: AutomationRules` ← **clave**       | regenerate_reel.py:183 (pero hace `del automation`:192) |
| `social_templates_records`                      | regenerate_reel.py:184-186                            |
| `platforms`                                     | regenerate_reel.py:187-191                            |
| `payload_dict` (raw WordPress JSON)             | regenerate_reel.py:138-148                            |
| `ghl_connection` + `access_token`               | regenerate_reel.py:122-130                            |
| `existing_state` (workflow + publish status)    | regenerate_reel.py:90-93                              |
| `reel_summary: AgencyReelSummary`               | regenerate_reel.py:150-155                            |
| `now = datetime.now(timezone.utc).isoformat()`  | regenerate_reel.py:216 (ya se calcula)                |
| `event_id`, `job_id`                            | regenerate_reel.py:217-218                            |

Forma del `AutomationRules` accesible (`modules/configuration/domain/agency_settings.py:44-53`):

```python
agency_id: str
approval_required: bool
publish_window_start: str        # ej. "09:00"
publish_window_end: str          # ej. "17:30"
publish_days: tuple[str, ...]    # ej. ("mon","tue","wed","thu","fri")
trigger_on_status: tuple[str, ...]
created_at: str
updated_at: str
```

Nota: `quiet_hours_*` y `skip_weekends` están descritos en el `feature_list.json:338`
pero **todavía no existen como atributos del dataclass** ni columnas en
`agency_automation_rules` (verificado en `automation_repository.py:13-33` y
`tests/integration/configuration/test_automation_router.py:109-125` los
referencia como toggles aún no persistidos). Si el spike pinta `scheduled_at`
hoy, solo puede usar `publish_window_start/end` + `publish_days`.

### ¿Es viable calcular `scheduled_at` en el approve y devolverlo?

Sí. Todos los datos están en mano antes del `enqueue_job`. El plan canónico
(feature 11 en `feature_list.json:336-355`) coincide:

1. Crear `modules/configuration/application/compute_next_publish_slot.py`
   con la pure function `compute_next_publish_slot(rules: AutomationRules, now_utc: datetime) -> datetime | None`.
2. En `regenerate_reel.py:192` reemplazar `del automation` por
   `scheduled_at = compute_next_publish_slot(automation, datetime.now(timezone.utc)) if automation else None`.
3. Añadir `"scheduled_at": scheduled_at.isoformat() if scheduled_at else None` al
   `publish_context` (línea :202-208) — feature 11 lo lleva al GHL como `scheduleDate`.
4. Añadir `scheduled_at: str | None = None` al `RegenerateReelResult` y propagarlo
   al `JSONResponse` del handler (admin_reels_router.py:208-217).

### Alternativa: cálculo en el worker

El cálculo **también podría** ocurrir en `regenerate_reel.py:183` worker-side
(es decir, en `IngestPropertyIntoReelUseCase` / `PrepareReelAssetsUseCase`), pero
requeriría que el approve no respondiera `scheduled_at` hasta que el worker
hubiera persistido un campo `jobs.scheduled_at` y el front hiciera un segundo
GET. Es estrictamente peor para el UX descrito y duplica reglas de negocio
entre módulos. **Recomendación: cálculo en el approve.**

## 5) Idempotencia / replay

El working tree añadió (sin commit) en `regenerate_reel.py:165-180`:

```python
active_job = uow.delivery.jobs.find_active_job_for_property(
    external_source_id=normalized_site_id,
    property_id=normalized_property_id,
    kind="reel_publish",
)
if active_job is not None:
    return RegenerateReelResult(
        publish_enqueued=True,
        reel=reel_summary,
        event_id=active_job.event_id or None,
        job_id=active_job.job_id,
        idempotent_replay=True,
    )
```

Y en `job_repository.py:23-31, 179-217` el nuevo dataclass `ActiveJob` y el
método `find_active_job_for_property` (status IN ('queued','processing'), order
by `created_at DESC, job_id DESC LIMIT 1`).

Implicaciones para el response de feature 11b:

- **En replay no hay `scheduled_at` cacheado.** El dataclass `ActiveJob` solo
  trae `job_id, event_id, status, created_at` (job_repository.py:23-31). El
  `publish_context_json` de la fila `jobs` sí lo tendría (si se persiste en
  feature 11), pero `find_active_job_for_property` solo selecciona 4 columnas
  (job_repository.py:194-201).
- **Dos caminos posibles**:
  1. **Recalcular** el slot con `compute_next_publish_slot(rules, now_utc=active_job.created_at)`
     en el replay para devolver el mismo `scheduled_at` que se calculó la primera
     vez (determinista si las rules no cambiaron entre clicks).
  2. **Ampliar `ActiveJob`** para incluir `publish_context_json` y leer
     `scheduled_at` de ahí. Requiere tocar `find_active_job_for_property` (un
     campo más en SELECT) + parseo JSON.

  La opción 1 es la más barata, pero rompe si el admin edita las rules entre
  clicks (raro pero posible). La 2 es más sólida pero arrastra trabajo extra.
  **Recomendación**: opción 2 — `ActiveJob` ya es interno al módulo `delivery`,
  añadir una columna más es trivial y elimina la rama "rules editadas".
- En cualquier caso, el front recibirá `scheduled_at` también en el response
  de replay. Cuando el job original era pre-feature-11 (no tiene
  `scheduled_at` en su `publish_context_json`), devolver `null` y no romper.

## 6) Heads-up working tree

`git status` muestra modificaciones (sin commit) en:

| Archivo                                                          | Relevancia para 11b                                       |
|------------------------------------------------------------------|-----------------------------------------------------------|
| `modules/reels/transport/http/admin_reels_router.py`             | Cambio único: añade `body["idempotent_replay"] = True` cuando aplica (líneas 216-217). Feature 11b debe encadenarse aquí (añadir `body["scheduled_at"] = result.scheduled_at`). |
| `modules/reels/application/use_cases/regenerate_reel.py`         | Añade `idempotent_replay: bool` al dataclass y el bloque `active_job` (líneas 165-180). Feature 11b cambia `del automation` por `compute_next_publish_slot(automation, now)` y propaga al DTO y al `publish_context`. |
| `modules/delivery/infrastructure/job_repository.py`              | Añade `ActiveJob` dataclass + `find_active_job_for_property`. Feature 11b probablemente necesite añadir `publish_context_json` al SELECT para soportar `scheduled_at` en replay (ver §5). |
| `tests/integration/reels/test_admin_reels_router.py`             | Tests nuevos del replay (líneas 432-611). Feature 11b debe añadir asserts de `scheduled_at` aquí. |
| `modules/reels/domain/types.py`                                  | Cambio ortogonal: añade `agency_logo_local_path: Path | None` a `PropertyContext`. Sin relación con 11b. |
| `modules/reels/application/orchestrator.py`                      | Cambios de feature 10 (logo). Sin relación con 11b. |
| `modules/configuration/transport/payloads/automation.py`         | Hay cambios; revisar si tocan el shape del PUT `/automation` que el front 11b usa para configurar la ventana (posible interacción). |
| `modules/configuration/transport/http/social_templates_router.py`| Ortogonal (social templates). |
| `modules/publishing/infrastructure/adapters/gohighlevel/*.py`    | Cambios en `models.py`/`social_service.py`/`post_creation.py`. Feature 11 los tocará para enviar `scheduleDate`; revisar para que no choquen. |

Diffs clave verificados con `git diff`:

- `regenerate_reel.py` diff: solo `idempotent_replay` (campo + bloque `active_job`).
- `admin_reels_router.py` diff: solo línea `body["idempotent_replay"] = True`.
- `job_repository.py` diff: `ActiveJob` dataclass + `find_active_job_for_property`.

## Referencias adicionales

- Constante `ADMIN_API_BASE_PATH`: `settings/app.py:217-218`, normalización en
  `settings/app.py:535-541, 588-596`.
- `JobEnqueueRequest` (campos que persisten al job): `modules/delivery/domain/job.py:15-31`.
  Hoy `publish_context` es `Mapping[str, Any]` → flexible para añadir
  `"scheduled_at"` sin migración de schema (es JSONB en la BBDD).
- `SocialPublishContext` (lo que se reconstruye en el worker desde el JSON):
  `modules/reels/domain/types.py:51-105`. Si feature 11b quiere que el worker
  consuma `scheduled_at`, hay que añadir el campo aquí también (con
  `from_dict`/`to_dict`) y propagarlo a `PublishReelUseCase`.
- Plan canónico de feature 11: `feature_list.json:328-355` (status `pending`).

---

**Plan recomendado para feature 11b (no implementar, solo documentar el shape
para que el front pueda mockear):**

Response 200 propuesto (todas las claves opcionales se omiten si `null`):

```json
{
  "status": "approved",
  "publish_enqueued": true,
  "reel": { /* sin cambios */ },
  "event_id": "<uuid4>",
  "job_id": "<uuid4>",
  "idempotent_replay": true,
  "scheduled_at": "2026-05-14T09:00:00+00:00"
}
```

`scheduled_at` es ISO8601 UTC (mismo formato que `pipeline_created_at`). El
front formatea a `dd/mm/yyyy a las HH:MM` en local del usuario. Cuando
`scheduled_at` es `null` (rules vacías o ventana no aplica), el front cae al
copy genérico "Se publicará en cuanto sea posible".
