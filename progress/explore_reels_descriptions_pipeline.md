# Explore: pipeline de descripciones de reels (2026-05-14)

## TL;DR
Las descripciones de reels se generan por plataforma en tiempo de ingestión de la property (webhook de WordPress). El flujo es: se carga la plantilla de la agencia desde `agency_social_templates` → se renderiza con variables de la property (`{{property_title}}`, `{{price}}`, etc.) → se almacena en `publish_target_snapshot.descriptions_by_platform` y se manda a GHL en `PublishMediaRequest.description`. Si falta template para una plataforma, se usa la descripción "fallback" genérica por plataforma (p.ej. TikTok tiene su propia estrategia).

## Cadena de llamadas
1. **Webhook → Ingest**: `modules/ingestion/application/use_cases/ingest_wordpress_property.py:100-121`
   - Lee plantillas de `uow.configuration.social_templates.list_for_agency(agency_id)`
   - Las serializa en `publish_context = {"social_templates": [(platform, template), ...]}`
   - Encola un `reel_publish` job con ese contexto

2. **Job Worker → Ingest Property Planning**: `modules/reels/application/use_cases/_ingest_property_planning.py:162-170`
   - Extrae `templates_by_platform = getattr(publish_context, "social_templates_map", {})`
   - Llama `content_generator.generate_property_content(..., templates_by_platform=...)`

3. **Content Generator**: `modules/reels/application/content_generator.py:118-163`
   - Construye `_build_property_template_variables()` con valores de property (línea:50-88)
   - Renderiza: `render_template_with_property(template, property, property_url)` (línea:91-114)
   - Si template existe y es válido → sobrescribe la descripción por defecto en `captions_by_platform[platform] = rendered`
   - Si no hay template → mantiene descripción genérica por plataforma de `build_platform_descriptions_for_property_with_url()`

4. **Snapshot → Publish Target**: `modules/reels/application/use_cases/_ingest_property_planning.py:223-255`
   - Guarda `publish_target_snapshot = {"descriptions_by_platform": dict(generated_content.captions_by_platform), ...}`
   - Persiste en tabla `reels` columna `publish_target_snapshot` (JSONB)

5. **Publish → GHL**: `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py`
   - Lee `context.publish_descriptions_by_platform.get(platform)` 
   - Construye `PublishMediaRequest(description=..., platform=...)`
   - Llama `self.social_publisher.publish_media(request)` → `GoHighLevelSinglePublishMixin._publish_media_once()` (línea:52)
   - Manda `description` en `_create_post(description=request.description, ...)`

## Variables soportadas
- **Fuente canónica**: `modules/configuration/domain/social_templates_variables.py:21-40`
  - `property_title`, `price`, `bedrooms`, `bathrooms`, `size_m2`, `property_type`, `city`, `neighborhood`, `neighborhood_tag`, `eircode`, `short_description`, `agent_name`, `agent_phone`, `agent_email`, `booking_link`, `property_url`

- **Mapeo en runtime**: `modules/reels/application/content_generator.py:50-88`
  - Construye dict con valores de `Property` object; si atributo no existe → string vacío `""`
  - **Nunca devuelve error**: placeholder no resuelto → se reemplaza por `match.group(0)` (el placeholder original entre `{{}}`) o string vacío si la clave no está en `variables`

## Comportamiento si falta template
1. **Si no hay template para plataforma**: 
   - Se usa descripción "fallback" genérica de la plataforma: `build_platform_descriptions_for_property_with_url()` (línea:156-172 en `description.py`)
   - Cada plataforma tiene su propia estrategia (TikTok, Instagram, etc. tienen formatos distintos)

2. **Si no hay publish_context (sin GoHighLevel)**: 
   - `_resolve_publish_inputs()` devuelve contexto vacío
   - `publish_descriptions_by_platform = {}` (dict vacío)
   - `publish_target_snapshot = {}` (dict vacío)
   - **No se omite la publicación**: se sigue procesando pero sin plantillas

3. **Si template renderiza a string vacío** (p.ej. solo contiene `{{nonexistent_var}}`):
   - El resultado es `""` (string vacío)
   - Se acepta como válido: `if rendered:` (línea:145) → si falsy, NO sobrescribe
   - Se mantiene descripción genérica por plataforma

## Override per-reel (editor)
**Gaps actuales**: El pipeline NO tiene endpoint de edición de descripción antes de publicar.
- La descripción renderizada de la template se almacena en `publish_target_snapshot.descriptions_by_platform` (inmutable en BD)
- El workflow es: generar → snapshot → aprob → publicar
- **No hay campo editable `reel.description` en la tabla ni endpoint PATCH**: la descripción es "read-only" desde el editor
- Si usuario necesita override: tendría que cambiar la template global, lo que afecta **todos** los reels futuro de esa plataforma

**Nota**: `regenerate_reel.py` ("Approve") re-encola el job pero no modifica la descripción: simplemente marca el reel como `approved` y espera el worker.

## Adaptador GHL
- **Archivo**: `modules/publishing/infrastructure/adapters/gohighlevel/single_publish.py:52-112`
- Se envía `description` como campo simple de `PublishMediaRequest` (línea:108)
- Se pasa a `_create_post(description=request.description, ...)` (línea:108)
- **Separación caption + hashtags**: 
  - No explícita en `PublishMediaRequest`; la `description` es un string único
  - Hashtags se pueden estar en el template como parte del texto (p.ej. `{{description}} #IrelandHomes`)
  - No hay campo `hashtags` separado en el request actual

- **Por plataforma**: Sí, se envía por plataforma (loop de `publish_targets` en `property_publisher.py`)

## Tests relevantes
- `tests/integration/configuration/test_social_templates_router.py` — GET/PUT endpoints
- `tests/unit/configuration/test_social_templates_variables.py` — validación de variables
- `tests/unit/reels/test_content_generator_unescape.py` — renderizado de variables
- `tests/integration/reels/test_publish_reel_flow.py` — flujo end-to-end
- `tests/unit/publishing/test_social_service_scheduling.py` — planificación + descripciones

## Gaps identificados
1. **No hay override de descripción per-reel en el editor**: la plantilla rendida es inmutable desde el UI
2. **Hashtags**: no hay campo separado en el modelo de publish; deben estar concatenados en la template o description
3. **Validación de largo por plataforma**: TikTok tiene un máximo (1000 caracteres aprox.) pero no se valida en la renderización
4. **Fallback global**: no hay descripción "por defecto" si falta template Y plataforma desconocida (se devuelve string vacío)
5. **Testing de template variables faltantes**: hay test unitario pero no hay test de integración que verifique el comportamiento end-to-end con una property real

