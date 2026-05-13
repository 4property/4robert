# Impl: feature 11 — wire_automation_publish_window_to_ghl_schedule

## Resumen

Cableado de la ventana de publicación recurrente (`agency_automation_rules.publish_window_*`, `publish_days`) hasta el `scheduleDate` del POST a GoHighLevel, con un nuevo use case puro `compute_next_publish_slot(rules, now_utc) -> datetime | None`, threading completo por `publish_context` → `SocialPublishContext` → `MultiPlatformPublishRequest` → `social_service.create_social_post`, y echo del slot en el response del `/approve` (campo `scheduled_at` ISO8601 UTC | `null`). Idempotent replay recupera el `scheduled_at` original del `publish_context_json` persistido. Sin cambios de schema, sin alembic, sin nuevas deps.

## Archivos creados

| Archivo | Tipo |
|---|---|
| `modules/configuration/application/use_cases/compute_next_publish_slot.py` | Use case puro |
| `tests/unit/configuration/test_compute_next_publish_slot.py` | Unit tests (26 casos) |
| `tests/unit/publishing/test_social_service_scheduling.py` | Unit tests (5 casos, MagicMock pattern) |

## Archivos modificados

| Archivo | Cambio |
|---|---|
| `modules/configuration/domain/agency_settings.py` | Sin tocar — `AutomationRules` ya existía con los campos necesarios. |
| `modules/reels/domain/types.py` | `SocialPublishContext` ahora lleva `scheduled_at: str \| None = None` con cobertura en `to_dict`/`from_dict`. |
| `modules/reels/application/use_cases/regenerate_reel.py` | Reemplazo de `del automation` por llamada a `compute_next_publish_slot`; `RegenerateReelResult` gana `scheduled_at`; helper `_extract_scheduled_at` para parsear el JSON persistido en el replay path. |
| `modules/reels/transport/http/admin_reels_router.py` | Body del approve incluye `body["scheduled_at"] = result.scheduled_at` cuando `publish_enqueued=True` (siempre, valor `null` para inmediato). |
| `modules/delivery/infrastructure/job_repository.py` | `ActiveJob` gana `publish_context_json: str \| None`; `find_active_job_for_property` lo selecciona y normaliza (str/bytes/dict). |
| `modules/publishing/infrastructure/adapters/gohighlevel/models.py` | `MultiPlatformPublishRequest` gana `scheduled_at: str \| None` con `object.__setattr__` por ser frozen+slots. |
| `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py` | Pasa `scheduled_at=context.publish_context.scheduled_at` al construir `MultiPlatformPublishRequest`. |
| `modules/publishing/infrastructure/adapters/gohighlevel/multi_publish.py` | Forwarda `scheduled_at=request.scheduled_at` a `_publish_platform_with_retry`. |
| `modules/publishing/infrastructure/adapters/gohighlevel/post_creation.py` | `_publish_platform_with_retry` y `_create_post` añaden kwarg `scheduled_at`; log incluye la línea "Scheduled at". |
| `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py` | `create_social_post` y `create_reel_post` aceptan `scheduled_at`. Cuando no es None/empty, `json_body["scheduleDate"] = scheduled_at` y `json_body["status"] = "scheduled"`; resto del tiempo `status="published"` (contrato pre-feature-11 intacto). |
| `tests/unit/reels/test_regenerate_reel.py` | Añadidos 6 tests nuevos para `scheduled_at` (window dentro/fuera, automation None, replay con/sin slot, replay sin atributo). |
| `tests/integration/reels/_client.py` | Nuevo helper `seed_automation_rules`; `insert_legacy_queued_job` acepta `publish_context: dict \| None` para sembrar el JSON correcto. |
| `tests/integration/reels/test_admin_reels_router.py` | 3 tests nuevos: response incluye `scheduled_at`, replay con slot, replay legacy con `null`. |
| `docs/API.md` | Sección `scheduled_at` documenta el contrato del response y la semántica del `scheduleDate` en el body GHL; documenta que `quiet_hours`/`skip_weekends` quedan fuera de scope. |

## Decisiones del leader implementadas (6 puntos clave)

1. **Ruta minimalista**: solo `publish_window_start`/`publish_window_end`/`publish_days`. `quiet_hours_*` y `skip_weekends` quedan como **TODO documentado** (requerirían schema + payload). Sin tocar ORM, payload Pydantic ni dataclass.
2. **Semántica de `scheduled_at`**: implementada exactamente como pidió el leader, con 26 unit tests cubriendo los 5 casos canónicos + edge cases:
   - `rules is None` → `None`.
   - `publish_window_start=""` o `publish_days=()` → `None`.
   - Dentro de la ventana en día válido → `None` (inmediato).
   - Fuera de la ventana, día válido, antes de start → hoy a start.
   - Fuera de la ventana, día válido, después de end → siguiente día válido a start.
   - Día no válido → siguiente día válido a start.
3. **Cálculo en el approve**: el slot se computa en `regenerate_reel.py` justo después de cargar `automation`, antes del enqueue. Se persiste en `publish_context_json` y se devuelve en `RegenerateReelResult` → handler.
4. **Replay idempotente**: `ActiveJob` ampliado con `publish_context_json: str | None`. `find_active_job_for_property` lo selecciona. El handler de replay parsea el JSON con `_extract_scheduled_at(...)` — devuelve `None` defensivamente cuando el JSON es vacío, malformado, no-dict o el atributo no existe (compatibilidad con jobs pre-feature-11).
5. **Threading hasta GHL**: cadena completa cableada (`regenerate_reel` → `SocialPublishContext` → `PropertyContext.publish_context` se reconstruye desde el JSON en el worker → `property_publisher` → `multi_publish` → `post_creation` → `social_service.create_social_post`). En `social_service` se setea `json_body["scheduleDate"]` y `json_body["status"] = "scheduled"` solo cuando `scheduled_at` es un string no vacío; whitespace-only se trata como inmediato.
6. **NO aplicado al webhook auto-publish**: `modules/reels/application/use_cases/ingest_property_into_reel.py` queda fuera de scope. Su `publish_context` no incluye `scheduled_at` — el flujo del webhook sigue publicando inmediato. Documentado aquí.

## Edge cases del use case puro

Cubiertos por `tests/unit/configuration/test_compute_next_publish_slot.py` (26 tests, todos verdes):

- `rules=None` → `None`.
- `publish_window_start=""` → `None`.
- `publish_days=()` → `None`.
- `publish_window_start="9am"` (HH:MM malformado) → `None`.
- `publish_window_start="25:00"` (hora fuera de rango) → `None`.
- `publish_window_start="09:60"` (minuto fuera de rango) → `None`.
- Strings de día desconocidos en `publish_days` se ignoran sin error.
- `now_utc` naive (sin tzinfo) se trata como UTC.
- `now_utc` en otro huso horario se convierte a UTC antes del cálculo.
- Ventana wrap-around (`22:00` → `06:00`): la hora actual `23:00` o `03:00` cae dentro → `None`.
- Mapeo `mon..sun` → `0..6` validado para cada uno de los 7 días.
- Friday 22:00 con Mon–Fri salta a Monday next.
- Sábado con Mon–Fri salta a Monday next.

## Decisión sobre el shape del response

Optamos por **incluir siempre** `scheduled_at` en el body cuando `publish_enqueued=True`, con valor `null` para inmediato (no omitir la clave). Esto:

- Permite al front branch directo sobre `payload.scheduled_at` sin distinguir entre presencia/ausencia.
- Es coherente con el contrato cross-repo pactado (feature 10 del front).
- No rompe ningún cliente existente (el front nuevo lo lee opcionalmente; clientes legacy lo ignoran).

Documentado en `docs/API.md` y en el comentario inline del router.

## Output focal pytest

### Test unitario del use case puro

```
$ .venv/bin/python -m pytest tests/unit/configuration/test_compute_next_publish_slot.py -q
..........................                                               [100%]
26 passed in 0.09s
```

### Test unitario del regenerate_reel (con scheduled_at)

```
$ .venv/bin/python -m pytest tests/unit/reels/test_regenerate_reel.py -q
.............                                                            [100%]
13 passed in 0.93s
```

### Test unitario de social_service (scheduling + unescape)

```
$ .venv/bin/python -m pytest tests/unit/publishing/test_social_service_scheduling.py tests/unit/publishing/test_social_service_unescape.py -q
............                                                             [100%]
12 passed in 0.53s
```

### Test integration del approve (scheduled_at en body y replay)

```
$ .venv/bin/python -m pytest tests/integration/reels/test_admin_reels_router.py -q
........................                                                 [100%]
24 passed in 33.75s
```

### Buckets del scope completo

```
$ .venv/bin/python -m pytest tests/unit/configuration/ tests/unit/publishing/ tests/unit/reels/ tests/integration/reels/ tests/integration/publishing/ -q
... (236 passed)
```

### init.sh

```
$ FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh
[OK] Entorno listo.
Pytest: 2 failed, 537 passed
Los 2 fallos son los preexistentes de tests/integration/test_http_transport.py:
  - test_health_endpoints_include_paused_dispatcher_state
  - test_health_endpoints_return_minimal_payloads
(esperan un shape de /health que no incluye configured_worker_count;
 son anteriores a feature 11 — leader ya los documentó).
Exit code: 0
```

### Readiness checks

```
$ .venv/bin/python -m apps.api --check  → exit 0
$ .venv/bin/python -m apps.worker --check  → exit 0
```

## Contrato con el front (feature 10 del repo `4Reels-Frontend`)

- Response del `/approve` ahora incluye siempre `"scheduled_at": string | null` cuando `publish_enqueued=true`.
- Si `null`: mensaje genérico "Reel approved" (comportamiento actual del front).
- Si string: ISO8601 UTC parseable a fecha local → mensaje "Publicará el dd/mm/yyyy a las HH:MM".
- Garantías del back:
  - El campo siempre se llama `scheduled_at` (no `scheduleDate`, no `scheduled_for`).
  - El valor siempre es un string ISO8601 UTC (`isoformat()` con sufijo `+00:00`) o `null`.
  - En replay idempotente, el valor coincide con el del primer enqueue (no se recalcula).

## NO TOCAR — confirmación

- ❌ Schema/ORM: sin tocar.
- ❌ Alembic: sin migración.
- ❌ `quiet_hours_*` y `skip_weekends`: documentados como TODO, no implementados.
- ❌ Flujo webhook auto-publish (`ingest_property_into_reel.py`): fuera de scope, documentado.
- ❌ Sin commits, sin marcar `done`, sin tocar Pinterest/decodeHtmlEntities/social-templates/brand-logo/idempotencia previa.
- ✅ Use case puro sin UoW.
- ✅ Frozen dataclasses respetan `object.__setattr__`.

## Revisión pendiente

Lanzar `reviewer` sobre este informe y los archivos listados.
