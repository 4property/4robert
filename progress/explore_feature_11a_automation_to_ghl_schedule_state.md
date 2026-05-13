# Explore: feature 11 — wire automation publish window to GHL scheduleDate (state)

> Solo lectura. Estado del repo: rama `ghl`, working tree con cambios sin commit
> (ver §6). Todas las referencias archivo:línea son sobre el árbol actual.

---

## 1. `agency_automation_rules` — fuente de la ventana de publicación

### 1.1 Tabla ORM

`modules/configuration/infrastructure/orm.py:80-106` — clase
`AgencyAutomationRulesORM(Base)`, `__tablename__ = "agency_automation_rules"`.

Columnas relevantes (todas server-defaulted, agency-scoped PK):

| Columna (línea) | Tipo SQLAlchemy | Tipo Python (Mapped) | Server default |
|---|---|---|---|
| `agency_id` (83-87) | `String(36)` FK → `agencies.id` (CASCADE) PK | `str` | — |
| `approval_required` (88-90) | `Boolean` NOT NULL | `bool` | `FALSE` |
| `publish_window_start` (91-93) | `Text` NOT NULL | `str` | `""` |
| `publish_window_end` (94-96) | `Text` NOT NULL | `str` | `""` |
| `publish_days` (97-99) | `ARRAY(Text)` NOT NULL | `list[str]` | `ARRAY[]::text[]` |
| `trigger_on_status` (100-104) | `ARRAY(Text)` NOT NULL | `list[str]` | `ARRAY['published']::text[]` |
| `created_at` / `updated_at` (105-106) | `DateTime(timezone=True)` NOT NULL | timestamp tz | — |

NO existen columnas `quiet_hours_*`, `skip_weekends`, `auto_captions`,
`regen_on_update`, `publish_mode`, `review_window_*`, `review_emails`,
`platforms`. La frase del enunciado de feature 11 (“quiet_hours, skip_weekends
en agency_automation_rules”) **no se corresponde con el ORM actual** — el
contrato canónico documentado en `tests/integration/configuration/test_automation_router.py:103-127`
es exactamente: `approval_required`, `publish_window_start`,
`publish_window_end`, `publish_days`, `trigger_on_status` (todo lo demás se
rechaza con `extra='forbid'`).

### 1.2 Value object dominio

`modules/configuration/domain/agency_settings.py:44-54` — dataclass
`@dataclass(frozen=True, slots=True) class AutomationRules`. Campos:

```
agency_id: str
approval_required: bool
publish_window_start: str          # "HH:MM" 24h, timezone agency-local (per payload doc)
publish_window_end: str            # idem
publish_days: tuple[str, ...]      # weekday lowercase 3-letter ("mon","tue",...)
trigger_on_status: tuple[str, ...] # property statuses
created_at: str                    # ISO8601
updated_at: str                    # idem
```

El dataclass NO contiene `quiet_hours`, `skip_weekends` ni ningún campo
adicional.

### 1.3 Use case de lectura

`modules/configuration/application/use_cases/read_automation_rules.py:12-22`
— `class ReadAutomationRulesUseCase` con firma:

```python
def execute(self, *, uow: DatabaseUnitOfWork, agency_id: str) -> AutomationRules | None
```

Devuelve `None` cuando no hay fila (no se materializa default desde aquí). El
repo `uow.configuration.automation.get(...)` se construye en
`modules/configuration/infrastructure/automation_repository.py:13-33`
(repository helper `AutomationRulesRepository.get`).

El use case `UpdateAutomationRulesUseCase` (mismo path, `update_automation_rules.py:30-48`)
materializa defaults por columna en `automation_repository.py:46-77`
(`publish_window_start = "00:00"`, `publish_window_end = "23:59"`,
`publish_days = ["mon","tue","wed","thu","fri"]`,
`trigger_on_status = ["for_sale","to_let"]`). Esto es relevante para el spike
porque `compute_next_publish_slot` puede recibir un `AutomationRules` con
strings vacíos (`""`) si nadie ha hecho un PUT — hay que decidir el fallback.

### 1.4 Tipos efectivos para el use case

- `publish_window_start` / `publish_window_end`: **`str` en formato "HH:MM"**
  (no `time`, no `datetime`). La validación de formato NO existe en el payload
  Pydantic (`modules/configuration/transport/payloads/automation.py:37-46`,
  son `str | None` sin regex). El nuevo use case `compute_next_publish_slot`
  debe parsear defensivamente.
- `publish_days`: **`tuple[str, ...]`** con strings lowercase tipo `"mon"`,
  `"tue"`, `"wed"`, `"thu"`, `"fri"`, `"sat"`, `"sun"` (3 letras). Existe lista
  `Weekday` en NINGÚN sitio del repo — no hay enum, hay strings sueltos
  (ver §4).
- `trigger_on_status`: `tuple[str, ...]` con strings como `"for_sale"`,
  `"to_let"`, `"published"`. Irrelevante para schedule pero está en la lectura.

---

## 2. Estado actual de `regenerate_reel.py:183` (donde hoy hace `del automation`)

Path completo: `modules/reels/application/use_cases/regenerate_reel.py`.

### 2.1 Carga y descarte

Líneas **182-192** (con sus dos vecinas para contexto):

```python
182        defaults = uow.configuration.defaults.get(normalized_agency_id)
183        automation = uow.configuration.automation.get(normalized_agency_id)
184        social_templates_records = (
185            uow.configuration.social_templates.list_for_agency(normalized_agency_id)
186        )
187        platforms = tuple(
188            defaults.platforms
189            if defaults is not None and defaults.platforms
190            else self.default_platforms
191        )
192        del automation
```

`automation` es un `AutomationRules | None` y se descarta inmediatamente.
Ningún otro punto del use case lo lee. Es exactamente el punto de wire-up que
pide la feature.

### 2.2 Otros datos del agency que se threadean al `publish_context`

`regenerate_reel.py:202-208` construye `publish_context: dict[str, Any]`:

```python
publish_context: dict[str, Any] = {
    "provider": "gohighlevel",
    "location_id": ghl_connection.external_id,
    "platforms": list(platforms),
    "approval_required": False,
    "social_templates": list(social_templates),
}
```

`platforms` viene de `defaults` (`uow.configuration.defaults.get(...)`,
línea 182). `social_templates` viene de
`uow.configuration.social_templates.list_for_agency(...)` (línea 184-186) y se
normaliza a `list[tuple[str, str]]` en `regenerate_reel.py:193-200`.
`approval_required` está hard-coded a `False` (no consulta `automation`).

El `publish_context` se serializa como JSON en
`modules/delivery/infrastructure/job_repository.py:124-125`
(`json.dumps(dict(request.publish_context), separators=(",", ":"))`) y se
persiste en `jobs.publish_context_json::jsonb`.

### 2.3 PropertyContext / publish_context

NO se construye un `PropertyContext` ni un `PublishContext` dataclass dentro de
`regenerate_reel.py` — solo un `dict[str, Any]` plano (línea 202).

El dataclass que sí existe es:

- `modules/reels/domain/types.py:52-110` —
  `@dataclass(frozen=True, slots=True) class SocialPublishContext` con
  `provider`, `location_id`, `access_token`, `platforms`, `approval_required`,
  `social_templates`. Tiene `from_dict(...)` (linea 77-110) y
  `to_dict(...)` (linea 60-70).
- `modules/reels/domain/types.py:250-289` —
  `@dataclass(frozen=True, slots=True) class PropertyContext` con campo
  `publish_context: SocialPublishContext | None = None`. Se construye en el
  worker, NO aquí.

El puente entre el `dict` plano persistido y el `SocialPublishContext`
dataclass ocurre en `modules/reels/application/orchestrator.py:254-274`
(función `build_property_media_job(job)`), línea 272:
`publish_context=SocialPublishContext.from_dict(publish_context_payload)`.

**Conclusión §2:** para enviar `scheduleDate` al GHL hay tres puntos de
extensión obligatorios:

1. `regenerate_reel.py:182-208` — calcular `scheduled_at` con
   `compute_next_publish_slot(automation, now_utc)` y añadirlo al dict
   `publish_context`.
2. `modules/reels/domain/types.py:52-110` (`SocialPublishContext`) — añadir
   campo opcional `scheduled_at: str | None = None` + cobertura en
   `to_dict` / `from_dict`.
3. `modules/ingestion/application/use_cases/ingest_wordpress_property.py:171`
   — el otro punto que enqueue jobs con `publish_context` (webhook no-approval
   flow) también necesita el mismo wire-up si la feature se aplica al flujo
   webhook auto-publish. Pero las acceptance criteria sólo nombran
   `regenerate_reel`; queda como heads-up para el implementer.

---

## 3. Threading hasta GHL

### 3.1 `MultiPlatformPublishRequest`

`modules/publishing/infrastructure/adapters/gohighlevel/models.py:207-322` —
`@dataclass(frozen=True, slots=True, init=False) class MultiPlatformPublishRequest`.

Campos actuales (atributos declarados, 209-222):
`media_path: Path`, `descriptions_by_platform: dict[str,str]`,
`titles_by_platform: dict[str,str]`,
`publish_targets: tuple[PlatformPublishTarget, ...]`,
`upload_file_name: str | None`, `target_url: str | None`,
`provider: str`, `location_id: str`, `access_token: str`,
`platforms: tuple[str, ...]`, `user_id: str | None`,
`source_site_id: str | None`, `social_post_type: str`, `artifact_kind: str`.

**No tiene `scheduled_at` ni `scheduleDate`.** Hay que añadirlo (y al `__init__`
manual). Es `frozen=True, slots=True` — el implementer debe respetar el patrón
`object.__setattr__` para setearlo.

### 3.2 `social_service.create_social_post`

Path: `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py:87-147`.

Firma actual:

```python
def create_social_post(
    self,
    *,
    location_id: str,
    access_token: str,
    account_id: str,
    user_id: str,
    uploaded_media: UploadedMedia,
    platform: str,
    description: str,
    title: str | None = None,
    social_post_type: str,
    target_url: str | None = None,
) -> CreatedSocialPost:
```

### 3.3 Construcción del `json_body`

**Punto único**: `social_service.py:110-122` ensambla el `json_body`:

```python
json_body: dict[str, object] = {
    "accountIds": [account_id],
    "summary": decoded_description,
    "media": [
        {
            "url": uploaded_media.url,
            "type": uploaded_media.mime_type,
        }
    ],
    "status": "published",
    "type": social_post_type,
    "userId": user_id,
}
json_body.update(
    self._build_platform_payload(...)   # 123-129
)
```

`_build_platform_payload` (línea 280-290) delega en cada plataforma
(`get_platform_config(...).build_gohighlevel_payload(target_url, title)`).
Los builders concretos viven en
`modules/publishing/infrastructure/adapters/platforms/shared.py:91-133`
(`build_empty_gohighlevel_payload`,
`build_google_business_profile_gohighlevel_payload`,
`build_youtube_gohighlevel_payload`,
`build_pinterest_gohighlevel_payload`). Ninguno toca `scheduleDate`.

La cadena de call sites que llega al `json_body`:

1. `regenerate_reel.py` enqueue → job persisted.
2. Worker pipeline → `orchestrator.build_property_media_job` rebuilds
   `SocialPublishContext` (`orchestrator.py:272`).
3. `GoHighLevelPropertyPublisher.publish_property_media` construye
   `MultiPlatformPublishRequest`
   (`property_publisher.py:90-104`).
4. `GoHighLevelMultiPublishMixin.publish_media_to_platforms` itera y llama
   `self._publish_platform_with_retry(...)`
   (`multi_publish.py:242`).
5. `GoHighLevelPostCreationMixin._create_post` llama
   `self.social_service.create_social_post(...)` (`post_creation.py:86-97`).

El `request` (MultiPlatformPublishRequest) tiene `location_id`,
`access_token`, etc., pero `scheduled_at` no se forwardea a
`_publish_platform_with_retry` ni a `social_service.create_social_post`
(`post_creation.py:26-56` y `58-105` — kwargs cerrados). El implementer debe
extender ambas firmas o pasar la fecha como atributo del `target` (más
invasivo).

### 3.4 ¿El `json_body` actual acepta `scheduleDate`?

`grep -rn "scheduleDate" modules/ apps/ shared/ tests/` → **0 matches**.
Nunca se envía. Hay que añadirlo condicionalmente:

```python
if scheduled_at:
    json_body["scheduleDate"] = scheduled_at
    json_body["status"] = "scheduled"   # decisión del implementer
```

(la línea 119 hoy hardcodea `"status": "published"` — el implementer debe
decidir si `status` queda `"published"` cuando hay `scheduleDate` o cambia a
`"scheduled"`. El contrato GHL acepta `status="scheduled"` con `scheduleDate`
ISO8601; sin `scheduleDate` y `status="published"` publica inmediatamente.
Ver `social_service.py:240-267` `_infer_status` donde el código YA reconoce
`"scheduled"` como estado válido).

### 3.5 Shape esperado por GHL para `scheduleDate`

GHL API `POST /social-media-posting/{locationId}/posts` espera
`scheduleDate` como string ISO8601 UTC (e.g. `"2026-05-13T15:30:00.000Z"`
o `"2026-05-13T15:30:00+00:00"`). El campo viaja sólo cuando `status` es
`"scheduled"` (o cuando GHL lo deriva por presencia del campo, según la
versión del endpoint). Documentación interna NO existe en este repo —
referencia: docs públicos HighLevel v2 social-media-posting POST. El
implementer debería verificar el shape exacto en un POST real antes de
codear el formato (basta `T`-separado con sufijo `Z` o `+00:00`).

---

## 4. `compute_next_publish_slot` — ¿existe ya algo parecido?

### 4.1 Grep

```
grep -rn "next_publish_slot\|next_slot\|publish_window\|quiet_hours\|skip_weekends" modules/
```

Resultados (subset, sólo modules/):

- `modules/configuration/domain/agency_settings.py:48-49` — campos
  `publish_window_start` / `publish_window_end` del dataclass.
- `modules/configuration/infrastructure/orm.py:91-99` — columnas.
- `modules/configuration/application/use_cases/update_automation_rules.py:24-26,44-47`
  — campos del input DTO.
- `modules/configuration/transport/payloads/automation.py:22-50` — payload PUT.
- `modules/configuration/infrastructure/automation_repository.py:53-66`
  — upsert con defaults.

**No existe un use case ni helper que calcule el slot.** Tampoco hay módulo
`shared/datetime/`, `shared/scheduling/` ni equivalente. `shared/` tiene
`crypto`, `db`, `errors`, `http`, `locking`, `media_cleanup`, `observability`,
`storage` — ninguno con utilidades de date math.

### 4.2 Únicos usos de `datetime.combine` / weekday math

`grep -rn "weekday\|Weekday\|datetime.combine" shared/` → 1 hit:
`shared/observability/persistent_log.py:53` (`datetime.combine(active_date, record_time)`)
— no reutilizable, es para parsear timestamps de logs.

### 4.3 Manejo de `quiet_hours` / `skip_weekends`

`grep -rn "quiet_hours\|skip_weekends" --include="*.py"` → 0 hits en
`modules/`. Aparecen sólo en:
- `tests/integration/configuration/test_automation_router.py:108-110, 124-125`
  — documentando que esas keys legacy se RECHAZAN.
- `tests/integration/configuration/test_defaults_router.py:100` — comentario
  documental sobre la reubicación de los 7 toggles huérfanos a
  `defaults.settings`.

**Conclusión §4:** la feature 11 debe crear el use case desde cero. Sugerencia
de path canónico siguiendo la convención del módulo:
`modules/configuration/application/use_cases/compute_next_publish_slot.py`,
sin tocar I/O (use case puro). Como no hay enum `Weekday`, conviene mapear
los strings 3-letter (`"mon"..."sun"`) a `int 0..6` (Python `datetime.weekday()`
devuelve 0=lunes) dentro del propio use case. No hay enum, NO inventes uno
nuevo — basta una tupla módulo-local.

**Sobre `quiet_hours` y `skip_weekends`:** el ORM/dataclass actual NO los
soporta. El enunciado de feature 11 los menciona, pero la decisión de
producto (test_automation_router.py:103-127) los DESCARTÓ como columnas y
los empujó a `defaults.settings`. **El implementer debe escoger una de dos
rutas**:

1. **Ruta minimalista (recomendada)**: ignorar `quiet_hours` y `skip_weekends`
   en este sub-feature. Sólo aplicar `publish_window_start`,
   `publish_window_end`, `publish_days`. Dejar las otras dos como TODO/feature
   futura. Esto es lo que el contrato actual del ORM permite sin tocar schema.
2. **Ruta extendida**: leer `defaults.settings` (`agency_reel_defaults.settings::jsonb`,
   keys namespaced según test_defaults_router) y combinar con
   `AutomationRules` en el input del use case. Más invasiva; toca otro módulo.

La acceptance criteria de feature 11 dice "Schema: No" → ruta minimalista
encaja con la restricción.

---

## 5. Tests del flujo de approve / publish

### 5.1 Integration tests con cliente GHL mockeado

- **`tests/unit/publishing/test_social_service_unescape.py`** (todo el
  fichero, 1-280) — patrón de mock canónico para `GoHighLevelSocialService`:
  inyecta `MagicMock()` como `client` con `request_json.return_value = {...}`,
  y luego inspecciona `request_json.call_args` para validar el `json_body`
  enviado. Este es el patrón a copiar para el test "json_body contiene
  scheduleDate" (líneas 29-44 muestran el helper `_build_service`).
- **`tests/unit/publishing/test_inspect_agency_social_accounts.py:63-85`** —
  monkeypatchea `GoHighLevelSocialService` completo. Útil cuando el test
  cruza el use case, no para validar el body.

NO hay un test de integración real (FastAPI client + DB) que mockee el HTTP
de GHL para inspeccionar el body. El nivel correcto para el test
`scheduleDate` es **unit** en `tests/unit/publishing/`.

### 5.2 Fixtures que cubren `agency_automation_rules`

- `tests/support/postgres.py` — `seed_tenant`, `temporary_postgres_schema`,
  `temporary_workspace`. NO siembra automation_rules por defecto.
- `tests/integration/configuration/_client.py` — `build_configuration_client`
  helper.
- `tests/integration/configuration/test_automation_router.py` (todo el fichero,
  pero sobre todo 50-65 y 103-127) — patrón de seed manual: hacer un PUT vía
  HTTP client para crear la fila.
- `tests/unit/configuration/test_read_automation_rules.py` y
  `test_update_automation_rules.py` — usan stubs in-memory de
  `automation_repository`. Útiles si el implementer quiere reusar el patrón
  para test unitario del nuevo use case `compute_next_publish_slot`.
- `tests/unit/reels/_uow_stubs.py:87-93` — `class StubAutomation` con
  `existing: Any = None`, expone `.get(agency_id) -> existing`. Cableado en
  `build_uow(automation=...)` (línea 173, 193). Esto es lo que el test unit
  de `RegenerateReelUseCase` actualizado va a necesitar para inyectar un
  `AutomationRules` con `publish_window_*` y verificar que aparece
  `scheduled_at` en el `enqueue_calls[0].publish_context`.

### 5.3 Cómo se mockea el POST a GHL hoy

Hay dos niveles:

1. **Unit, granularidad cliente HTTP**:
   `tests/unit/publishing/test_social_service_unescape.py:32-44` — patch del
   `client.request_json` con `MagicMock`. Permite inspeccionar el `json_body`
   exacto que el `social_service` envía. **Este es el mock canónico para
   feature 11.**
2. **Integration, granularidad publisher**:
   `tests/integration/reels/test_publish_reel_flow.py:95-139` — fake
   `_FakePropertyPublisher` que devuelve un `MultiPlatformPublishResult`
   sintético (`SimpleNamespace`). No llega al HTTP layer. No sirve para
   verificar `scheduleDate` salvo que el test inspeccione el request que
   recibió el fake.

### 5.4 Existing tests para `regenerate_reel`

`tests/unit/reels/test_regenerate_reel.py` cubre `RegenerateReelUseCase`
end-to-end con stubs. `test_regenerate_reel_enqueues_job_with_full_prereqs`
(líneas 39-76) ya verifica:

```python
assert enqueue_request.publish_context["approval_required"] is False
assert enqueue_request.publish_context["location_id"] == "loc-1"
```

→ El test de feature 11 puede extender este patrón a:
```python
assert enqueue_request.publish_context.get("scheduled_at") is not None
assert enqueue_request.publish_context["scheduled_at"].endswith("+00:00")
```

`tests/integration/reels/test_admin_reels_router.py:400-518` cubre el HTTP
`/approve` flow. Útil para añadir asserts sobre la jsonb almacenada en
`jobs.publish_context_json` (acceso vía `engine.execute("SELECT
publish_context_json FROM jobs WHERE job_id=...")`).

---

## 6. Heads-up working tree

Cambios SIN COMMIT relevantes al scope de feature 11 (rama `ghl`,
output de `git status` filtrado al scope):

| Archivo | Estado | Relevancia para feature 11 |
|---|---|---|
| `modules/reels/application/use_cases/regenerate_reel.py` | modified | **ALTA** — el use case central. Diff actual añade idempotency check (líneas 165-180 nuevas, `find_active_job_for_property` + early-return con `idempotent_replay=True`). El bloque `del automation` sigue en línea 192 del archivo modificado. El implementer debe partir de este árbol, NO del HEAD. |
| `modules/publishing/infrastructure/adapters/gohighlevel/models.py` | modified | **MEDIA** — `MultiPlatformPublishResult.aggregate_status` retocado (skipped_missing_account ya no penaliza). NO toca `MultiPlatformPublishRequest`. El implementer puede añadir el campo `scheduled_at` sin colisión. |
| `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py` | modified | **MEDIA** — feature 12 ya aplicado: `html.unescape` en `decoded_description` / `decoded_title` (líneas 101-109, 112, 127). El bloque `json_body = {...}` (línea 110-122) sigue siendo el punto único donde añadir `scheduleDate`. No hay conflicto. |
| `modules/reels/domain/types.py` | modified | **MEDIA** — `PropertyContext` ganó `agency_logo_local_path: Path | None = None` (línea 281, feature 10). `SocialPublishContext` (52-110) NO está modificado en este diff. El implementer puede añadir `scheduled_at: str | None = None` a `SocialPublishContext` sin colisión. |
| `modules/publishing/infrastructure/adapters/platforms/registry.py` | modified | BAJA — no scope. |
| `modules/publishing/infrastructure/adapters/platforms/shared.py` | modified | BAJA — sólo si el implementer decide pasar `scheduleDate` vía `build_gohighlevel_payload` (no recomendado). |
| `modules/configuration/domain/__init__.py` | modified | BAJA — exports. Hay que verificar que `AutomationRules` siga exportado al añadir el nuevo use case. |
| `modules/configuration/application/use_cases/read_aggregated_reel_profile.py` | modified | BAJA — diff de feature 9. No bloquea. |
| `modules/configuration/infrastructure/defaults_repository.py` | modified | BAJA — fuera de scope. |
| `modules/reels/application/orchestrator.py` | modified | **MEDIA** — `build_property_media_job` (línea 254-274) reconstruye `SocialPublishContext` con `from_dict`. Si el implementer añade `scheduled_at` al dict del job, `SocialPublishContext.from_dict` debe sacarlo y `PropertyContext` debe forwardearlo. No hay diff en estas líneas concretas pero el archivo tiene cambios. |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | modified | BAJA — feature 10 (logo). Para feature 11, es el otro punto donde se construye `publish_context`; si la decisión es aplicar `scheduleDate` también al flujo webhook, hay que tocarlo. Las acceptance no lo piden explícitamente. |
| `modules/reels/application/content_generator.py` | modified | BAJA — feature 12. |
| `modules/rendering/infrastructure/ai_photo_selection/prompting.py` | modified | BAJA — feature 12. |
| `tests/integration/test_http_transport.py` | modified | MEDIA — contiene tests del `/automation` HTTP endpoint (líneas 548-602). Si el implementer modifica el contrato del PUT (no debería), aquí explota. |
| `tests/integration/configuration/test_defaults_router.py` | modified | BAJA. |

Archivos del scope SIN modificar (HEAD limpio):
- `modules/configuration/application/use_cases/read_automation_rules.py`
- `modules/configuration/application/use_cases/update_automation_rules.py`
- `modules/configuration/infrastructure/automation_repository.py`
- `modules/configuration/infrastructure/orm.py`
- `modules/configuration/domain/agency_settings.py`
- `modules/configuration/transport/payloads/automation.py`
- `modules/configuration/transport/http/automation_router.py`
- `modules/publishing/infrastructure/adapters/gohighlevel/multi_publish.py`
- `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py`
- `modules/publishing/infrastructure/adapters/gohighlevel/post_creation.py`
- `tests/unit/reels/_uow_stubs.py`
- `tests/unit/reels/test_regenerate_reel.py`
- `tests/unit/publishing/test_social_service_unescape.py`

**Recomendación al leader**: lanza el implementer sobre el árbol actual
(`ghl` branch + uncommitted changes). NO hay rebases pendientes ni
conflictos lógicos previsibles en el scope.

---

## Apéndice — checklist mínima de wire-up que el implementer hará

1. Crear `modules/configuration/application/use_cases/compute_next_publish_slot.py`
   con `compute_next_publish_slot(rules: AutomationRules, now_utc: datetime) -> datetime | None`.
   Use case puro (sin UoW). Tests en `tests/unit/configuration/test_compute_next_publish_slot.py`.
2. Añadir `scheduled_at: str | None = None` a `SocialPublishContext`
   (`modules/reels/domain/types.py:52-110`) + `to_dict`/`from_dict`.
3. En `regenerate_reel.py:182-208`: dejar de hacer `del automation`, llamar al
   use case nuevo, añadir `"scheduled_at": <iso8601>` al dict `publish_context`
   cuando aplique.
4. Añadir `scheduled_at: str | None` a `MultiPlatformPublishRequest`
   (`models.py:207-322`, init manual con `object.__setattr__`) y propagarlo en
   `property_publisher.py:90-104`.
5. Forwardear `scheduled_at` por `_publish_platform_with_retry`
   (`post_creation.py:26-56`) → `_create_post` (58-105) → `social_service.create_social_post`.
6. En `social_service.create_social_post` (`social_service.py:87-147`):
   añadir kwarg `scheduled_at: str | None = None`. Si no es None, setear
   `json_body["scheduleDate"] = scheduled_at` y cambiar
   `json_body["status"] = "scheduled"`.
7. Test integration con `MagicMock()` para `client.request_json` que verifica
   el `json_body` en ambos casos (con y sin scheduleDate). Patrón en
   `tests/unit/publishing/test_social_service_unescape.py:29-65`.
8. Actualizar `tests/unit/reels/test_regenerate_reel.py` para inyectar un
   `StubAutomation(existing=AutomationRules(...))` no vacío y assertar
   `enqueue_request.publish_context["scheduled_at"]`.

Schema: NO (acceptance lo confirma — feature 11 explícitamente "Schema: No").
No hay migración Alembic en este sub-feature.
