# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

---

# Feature 39 — test_reels_list_ordering_guard (Claude implementer)

- **Inicio:** 2026-05-16
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** No (sólo tests).
- **Modulos afectados:** `tests/integration/reels/test_list_reels_ordering.py` (archivo nuevo).

## Plan
- Crear `tests/integration/reels/test_list_reels_ordering.py` con 2 tests guard.
- Reusar `seed_tenant` + `seed_property_with_reel` + `build_admin_reels_client` del módulo `_client.py` y `tests/support/postgres.py`.
- Controlar `updated_at` vía `UPDATE reels SET updated_at = :ts WHERE source_property_id = :pid` directo en SQL para fijar T0, T0+1h, T0+2h (el seed normal usa now() — todos quedarían iguales).
- Test 1: GET inicial → orden por updated_at DESC [c, b, a].
- Test 2: UPDATE updated_at del reel_a a T0+3h → GET → orden [a, c, b].
- Verificación: `pytest tests/integration/reels/test_list_reels_ordering.py -v`, `pytest tests/integration/reels/ -q`, `bash ./init.sh`.

## Bitacora

---

# HOTFIX side_banner_footer_radius (Codex) — entrada original archivable

- **Feature en curso:** HOTFIX: side_banner_footer_radius
- **Inicio:** 2026-05-14
- **Agente:** Codex
- **Modulos afectados:** `modules/rendering/infrastructure/ffmpeg/`
- **Toca schema?:** No

## Plan
- Añadir un radio discreto al panel footer del template `side_banner`.
- Mantener intacto el render classic y no tocar cambios concurrentes de layout/ribbon.
- Verificar con tests focalizados y `bash ./init.sh` (porque `./init.sh` no tiene bit ejecutable).

## Bitacora
- 2026-05-14: `./init.sh` falla con `Permission denied`; validación previa lanzada con `bash ./init.sh`.
- 2026-05-14: Detectado árbol sucio con cambios concurrentes en Side Banner; el hotfix se limita al filtro ffmpeg del footer.
- 2026-05-14: Implementado footer redondeado en `build_overlay_filter` solo para `layout_variant="side_banner"`; classic conserva `drawbox`.
- 2026-05-14: Tests focalizados verdes y validación mínima de FFmpeg del filtro generado sin errores.
- 2026-05-14: `bash ./init.sh` final exit 0; el log mantiene 3 fallos globales de baseline (`test_http_surface_contract.py` y 2 en `test_http_transport.py`): 3 failed, 665 passed, 14 warnings.

## Proximo paso
- Hotfix listo; pendiente que quien coordine la sesión decida si archiva `progress/current.md` dado que hay otros agentes activos.

---

# Trabajo en paralelo — HOTFIX classic_template_preview (Codex)

- **Inicio:** 2026-05-14
- **Agente:** Codex
- **Modulos afectados:** `assets/render-templates/`, `apps/api/app_factory.py`, `alembic/versions/`, `tests/integration/configuration/`, `tests/integration/apps_api/`
- **Toca schema?:** No cambia schema; data migration sobre `render_templates.preview_images`.

## Bitacora

- 2026-05-14: Movida la imagen subida desde la raiz a `assets/render-templates/classic-template.png`.
- 2026-05-14: Añadido mount estatico `/assets/render-templates` para servir previews versionados.
- 2026-05-14: Añadida migracion `20260514_0002_classic_render_template_preview.py` encadenada tras la feature 19 (`down_revision = "20260514_0001"`) para actualizar la fila `classic` con `preview_images`.
- 2026-05-14: Verificacion focalizada verde con `.venv/bin/python -m pytest tests/integration/configuration/test_render_templates_router.py::test_render_templates_list_returns_seeded_classic tests/integration/apps_api/test_render_template_assets.py -q` (2 passed). `apps.api --check`, `py_compile` y `git diff --check` verdes.
- 2026-05-14: `bash ./init.sh` final exit 0; el log global mantiene los 3 fallos de baseline ya observados (`test_http_surface_contract.py` y 2 en `test_http_transport.py`): 3 failed, 668 passed, 14 warnings.

## Proximo paso

- Hotfix de asset/mount listo.
- **Pendiente cuando termine feature 19:** aplicar/migrar `alembic/versions/20260514_0002_classic_render_template_preview.py` después de que quede cerrada `20260514_0001_include_pinterest_in_reel_defaults.py`, porque `20260514_0002` declara `down_revision = "20260514_0001"`.
- Si feature 19 cambia el revision id antes de cerrar, actualizar el `down_revision` de `20260514_0002_classic_render_template_preview.py` antes de ejecutar `alembic upgrade head`.

---

# Sesión paralela — backlog música (Claude, leader)

- **Inicio:** 2026-05-14
- **Agente:** Claude (rol leader, sin implementación)
- **Estado:** ninguna feature en `in_progress`; sólo se ha abierto backlog.

## Contexto de la petición

El usuario pidió centrar la siguiente tanda en la pestaña `/music` del frontend. Tras
explorar el contrato actual y validar el alcance con el usuario en este turno
(decisiones registradas vía `AskUserQuestion`):

- "Desacoplar el reel del audio" = tres lecturas combinadas: pista intercambiable
  post-render, selección dinámica por agencia, override por reel en /reels.
- Upload = multipart al backend (mismo patrón que `feature 10 brand/logo`).
- Storage = reusar `shared/storage/site_layout` (FS hoy, S3 mañana sin cambiar HTTP).
- Las 4 MP3s actuales de `assets/music/` se seedean por agencia (cada agencia recibe
  copia propia, no pool global).
- Abrir las 4 features en backlog desde ya (`pending`); confirmar arranque después.

## Backlog abierto

| id | nombre | dep | resumen |
|----|--------|-----|---------|
| 22 | `agency_music_upload` | — | POST multipart `/v1/admin/agencies/{id}/music/upload` + GET file/{filename}; retira el POST metadata-only y blinda `object_key` |
| 23 | `wire_render_to_agency_music_tracks` | 22 | `resolve_background_audio_paths` deja de escanear `assets/music/` y lee `agency_music_tracks`; seed por agencia en alembic |
| 24 | `agency_music_selection_rules` | 23 | Persiste `settings.music.selection_rules.fallback_to_full_library` en `agency_reel_defaults`; conecta el Toggle decorativo del front |
| 25 | `per_reel_music_override` | 23 | Columna `reels.music_id` + PATCH `/v1/admin/reels/{id}/music` que re-encola render con esa pista; 409 si reel aprobado/publicado |

Mirror cross-repo: ids 22, 23 (noop front), 24 y 25 abiertos también en
`/opt/projects/4Reels-Frontend/feature_list.json`.

## Próximo paso

- Confirmar con el usuario que se arranque la 22 (back + front en paralelo)
  pese a que hay actividad concurrente de Codex (dos hotfixes cerrados sin
  archivar, feature 19 cerca de cerrar). Si el usuario aprueba, pasar la 22
  a `in_progress` en ambos repos y lanzar implementer en cada uno.
- Antes de tocar `apps.api --check`/migraciones, esperar a que Codex archive
  los hotfixes y feature 19 cierre (revision id `20260514_0001` impacta la
  cadena alembic).

## Pre-trabajo paralelo entregado — explore de feature 23 (sin tocar código)

- 2026-05-14 — Explore entregado en `progress/explore_23_render_to_agency_music_tracks.md`. Solo lectura, sin modificar nada del repo. Cubre zonas frías de `git status`: `modules/rendering/infrastructure/runtime/assets.py`, `shared/storage/site_layout.py`, patrón multipart de `brand_logo_router.py`, repositorio de music tracks, inventario de `assets/music/`. Zonas calientes (`modules/reels/application/use_cases/*`, `modules/rendering/infrastructure/preparation.py`) marcadas con ⚠️ y con instrucciones explícitas de revalidar tras cierre de feature 21.
- **Hallazgos relevantes** del explore (afectan al alcance original de la 23 redactada en `feature_list.json`):
  1. `assets/music/` tiene **5 archivos**, no 4 (incluye `New Light.wav` 43MB y `ncs-music.mp3` que **ES el `REEL_BACKGROUND_AUDIO_FILENAME` default** definido en `settings/reels.py:12`). El seed por agencia debe decidir qué hacer con cada uno.
  2. Hay **3 call sites** de `resolve_background_audio_paths`: `preparation.py:186` ⚠️ caliente, `manifest.py:180` y `readiness.py:412` fríos. El refactor de la firma debe preservar el path legacy para readiness/dev sin BBDD (`music_tracks=None` como kwarg opcional).
  3. **8 decisiones pendientes** documentadas en §6 del explore (naming de `display_name` para los 4 NCS; FK en `agency_music_tracks.id`; semántica del `down_revision` cuando 21 cierre; alcance del seed para agencias nuevas).
- El explore deja claro qué comandos correr (`git status`, `git diff HEAD -- <archivo>`) para revalidar antes de implementar feature 23, así no se actúa sobre info caducada cuando la 21 cierre.

---

# Sesión paralela — backlog UX reels + intro/outro upload + needs_approval editable (Claude, leader)

- **Inicio:** 2026-05-15
- **Agente:** Claude (rol leader, sin implementación)
- **Estado:** ninguna feature en `in_progress`; sólo se ha abierto backlog.

## Contexto

El usuario pidió planificar tres tandas de trabajo en `/opt/projects/4Reels-Frontend` y este repo, en paralelo a las features #26/#27 (email) que están activas. Decisiones tomadas en este turno vía `AskUserQuestion`:

1. **/defaults Intro & Outro**: abrir **intro y outro a la vez** (no sólo outro). Mismo patrón multipart que feature 22 (música) y feature 9 (logo).
2. **/reels paginación**: **page + total + filtros básicos** (`workflow_state`, `publish_status`, `q`). No cursor-based.
3. **/reels editor en `needs_approval`**: persistir y re-encolar render para **reorder fotos**, **subtítulos** y **slides**. Voiceover queda fuera del alcance ahora.

## Backlog abierto (ids 32–37 paritarios cross-repo)

| id | name | dep | resumen |
|----|------|-----|---------|
| 32 | `reels_list_pagination_and_filters` | — | `GET /reels` con `page/page_size/count_total/has_more` + filtros `workflow_state,publish_status,q`; `?limit=` legacy preservado |
| 33 | `agency_outro_video_upload_and_render` | — | Upload multipart `/outro/upload`, GET file, DELETE; columna o tabla intro/outro assets; ffmpeg concat al final del reel |
| 34 | `agency_intro_video_upload_and_render` | 33 | Simétrico a 33 pero al inicio; reaprovecha helper concat |
| 35 | `per_reel_photos_override` | — | PATCH `/reels/{id}/photos` con positions+selected; nueva columna `reels.photos_override JSONB`; re-encola render; 409 si approved/published |
| 36 | `per_reel_subtitles_override` | — | PATCH `/reels/{id}/subtitles` con cues (text,in,out); columna `subtitles_override JSONB`; re-encola |
| 37 | `per_reel_slides_override` | — | PATCH `/reels/{id}/slides` con manifest scenes; columna `manifest_override JSONB`; re-encola |

Mirror cross-repo: ids 32–37 abiertos también en `/opt/projects/4Reels-Frontend/feature_list.json` (con `depends_on` apuntando a la counterpart del back desplegada en :8001).

## Próximo paso

- **NO arrancar** ninguna de estas mientras feature 26 (`email_notification_infrastructure`) esté `in_progress` y feature 27 esté `pending`. Las 32–37 esperan a que cierre la tanda de email + el HOTFIX classic_template_preview pendiente de migración `20260514_0002` (encadenado).
- Antes de arrancar 35/36/37 conviene revalidar si entre tanto se ha extendido `reels` con columnas que cambien el rebase de la migración (las tres añaden JSONB nullable).
- Antes de arrancar 33/34, confirmar con el usuario si quiere también el modo `brand_card` (auto-generado) o queda fuera (la entry abierta lo deja explícitamente como pendiente futuro).
- Para 32 conviene comprobar si algún consumer ahora mismo depende de que `count = len(items)` (en tests del back o callers); el plan es preservarlo como alias para no romper.

---

# HOTFIX 2026-05-15 — switch /brand "show agent photo" (Claude)

**Petición del usuario** (palabra `hotfix` invocada explícitamente, `CLAUDE.md §Hotfix`):
> "hotfix, necesito que pongas un switch en brand para quitar la foto del agente inmobiliario y que no aparezca en el reel"

## Decisión arquitectural

Sin migración Alembic. Reúso del JSONB `agency_reel_defaults.settings` (mismo patrón que features 24 música y 31 subtítulos): la clave nueva es `showAgentPhoto` (camelCase, alineado con `INITIAL_DEFAULTS` del front; default `true` para preservar el comportamiento histórico). Esto evita colisionar con la migración `20260514_0007` en flight de feature 26 (`email_notification_infrastructure`).

## Cambio

- `modules/reels/application/use_cases/ingest_property_into_reel.py`:
  - Nuevo helper `_resolve_show_agent_photo(uow, agency_id) -> bool`, simétrico a `_resolve_music_selection_rules` y `_resolve_subtitle_settings_overrides`: lee defensivamente `defaults.settings["showAgentPhoto"]` y devuelve `True` si la clave no está, si el UoW es de unit-test, si no hay agencia o si el valor no es bool-coercible.
  - En `_execute_with_uow`, tras `self._sanitize_property_accent_colors(property_item)` y antes de `build_media_delivery_plan(property_item)`: si el helper devuelve `False`, anula `property_item.agent_photo_url = None`. `Property` es `@dataclass(slots=True)` no-frozen, por lo que la mutación in-place es válida.
  - El resto del pipeline ya tolera `agent_photo_url=None`: `prepare_agent_image` (en `modules/rendering/infrastructure/runtime/branding.py:125`) hace early-return si la URL es falsy; el manifest no necesita guard adicional.

## Verificación

- `.venv/bin/python -m apps.api --check` ✅ (RUNTIME READY: Yes).
- `.venv/bin/python -m pytest tests/integration/reels/ tests/unit/reels/ -q -x` → **156 passed** (no regresiones en el área tocada).
- No se tocó `apps/worker/`, `alembic/`, `shared/email/`, `modules/notifications/` ni `modules/rendering/infrastructure/ffmpeg/`, por lo que no colisiona con el work activo de Codex (HOTFIX side_banner_footer + classic_template_preview) ni con feature 26 (email_notification_infrastructure).

## Scope respetado

- Solo se tocó `modules/reels/application/use_cases/ingest_property_into_reel.py`.
- Sin migración Alembic; sin nueva columna; sin tocar `BrandSettingsUpsertPayload`.
- Reels ya renderizados antes de flipar el switch siguen mostrando la foto hasta que se regenere el render. Comportamiento documentado en la sub-label del Toggle del front.

## Notas para validación manual contra :8001

- En el frontend `/brand`, flipar el Toggle "Show agent photo in reels" a OFF y guardar → emite `PUT /v1/admin/agencies/{id}/defaults` con `{settings: {showAgentPhoto: false}}` (merge shallow del back preserva las demás keys).
- Ingestar una property nueva vía webhook → el renderer debería producir un reel sin la foto del agente.
- Verificar en logs / inspección del filter graph que `agent_photo_url` llegó como `None` al pipeline.

---

# HOTFIX 2026-05-15 — side_banner render-template preview image (Claude)

**Petición del usuario:**
> "pon la imagen side-banner-template.png como preview del template side banner"

Réplica del patrón ya aprobado para `classic` (`20260514_0002_classic_render_template_preview.py`).

## Cambio

- **Asset:** copiado `side-banner-template.png` (raíz del repo, 959 567 bytes) a `assets/render-templates/side-banner-template.png`. El original en la raíz se conserva.
- **Migración:** `alembic/versions/20260515_0001_side_banner_render_template_preview.py` (`revision = "20260515_0001"`, `down_revision = "20260514_0007"`). Actualiza `render_templates.preview_images` para `template_id = 'side_banner'` con un único item `{kind:"preview", image_url:"/assets/render-templates/side-banner-template.png", alt:"Side banner template preview"}`. `downgrade` idempotente (sólo revierte si el JSONB actual coincide con el aplicado).
- Sin cambios en `apps/`, `modules/`, `shared/` ni `tests/`.

## Verificación

- Implementer: `progress/impl_side_banner_preview.md` (asset OK; `alembic history` muestra `20260515_0001 (head)`).
- Reviewer APPROVED: `progress/review_side_banner_preview.md`.
- `alembic upgrade head` ejecutado: arrastró DB de `20260514_0007` hasta `20260515_0004` (mi `0001` + las `0002`/`0003`/`0004` que features 33/35/36 habían dejado encadenadas pero sin aplicar contra esta base de datos).
- Lectura post-aplicación de `render_templates.preview_images WHERE template_id='side_banner'` confirma el payload esperado.

## Encadenamiento alembic

- Antes del hotfix la cabeza era `20260514_0007` (feature 26 email_notifications).
- Cadena en disco resultante: `…0007 → 20260515_0001 (side_banner preview) → 0002 (outro) → 0003 (photos_override) → 0004 (subtitles_override) → 0005 (manifest_override, feature 37 sin aplicar)`.
- DB actual = `20260515_0004`. `0005` está en disco pero pendiente de aplicar hasta que feature 37 cierre review.

---

# Feature 38 — db_backed_webhook_secrets (Claude leader → implementer → reviewer) — CERRADA

> **Estado (2026-05-16):** `done` en `feature_list.json`. Review APPROVED.
> Originó de la petición "una misma cuenta GHL recibiendo webhooks de múltiples WordPress". Diagnóstico final tras releer ORM: el schema YA soportaba N WP por agencia; el único gap real era que el webhook handler sólo leía secrets de `WEBHOOK_SITE_SECRETS` (env). Feature 38 mueve la resolución a `ingestion_sources.secrets_encrypted` con fallback env legacy.

## Resultado

- `modules/ingestion/transport/http/wordpress_webhook_router.py` resuelve el secret BBDD → env → None.
- 4 tests integration nuevos (`test_wordpress_webhook_flow.py`) + 1 archivo unit nuevo (`test_wordpress_webhook_secret_resolution.py`). Resto sin regresión.
- Sin migración, sin nuevos endpoints, sin cambios en `shared/db/orm.py` ni `modules/reels/` ni `modules/rendering/` (cero solape con feature 37 que estaba in_progress y que cerró también con APPROVED).
- Informes en `progress/impl_38_db_backed_webhook_secrets.md` y `progress/review_38_db_backed_webhook_secrets.md`.

## Diagnóstico inicial corregido (referencia)

Los 2 exploradores iniciales se contradijeron sobre el UNIQUE bloqueante. La verdad verificada en `shared/db/orm.py:64-75`: la UNIQUE real es `(agency_id, kind, external_id)` con 3 columnas, no bloquea N WP por agencia. El admin CRUD (`wordpress_sources_router.py:63-200`) ya persiste el secret en BBDD. El único bloqueo operativo era el handler leyendo env.

## Exploración previa (queda en disco como referencia)

- `progress/explore_ghl_account_shape.md` (fiable).
- `progress/explore_wordpress_webhook_ingestion.md` (fiable; sección 2 acertó la lectura del UNIQUE).
- `progress/explore_schema_agency_site_ghl.md` (⚠️ líneas 339-348 erróneas — confunden `(agency_id, kind, external_id)` con `(agency_id, kind)`. Si se reusa, ignorar esa sección).

## Operación de cierre (2026-05-16)

- `feature_list.json` id=38 → `status: "done"` (marcado tras aprobar el reviewer y por instrucción explícita del usuario).
- Sin trabajo pendiente colgando de esta feature. Sin follow-ups.

## Petición del usuario (verbatim)

> "ahora mismo hay un agente haciendo otras features asi que ten cuidado de no solaparlo. quiero que permitas que una misma cuenta de ghl pueda recibir webhooks de multiples wordpress"

## Constraints

- **Otro agente activo** sobre **feature 37 (`per_reel_slides_override`)** — territorio reservado: `modules/reels/`, `modules/rendering/application/scripted_video/`, `shared/db/orm.py` (`manifest_override` + retro-fix `photos_override`), `alembic/versions/20260515_0005_reels_manifest_override.py` (aplicada — DB head ya en `20260515_0005`), `tests/integration/reels/`, `tests/integration/rendering/`, `docs/API.md`/`http_surface.md`/`openapi.json`. `impl_37.md` existe; falta `review_37.md`.
- **Esta feature vive** en `modules/ingestion/` (transport + use cases + infra) y `settings/`. Cero solape con `modules/reels/`, `modules/rendering/`, `modules/publishing/`.
- **No requiere migración Alembic.** La columna `ingestion_sources.secrets_encrypted` ya existe y el use case `ProvisionWordPressSourceUseCase` ya la persiste. Si finalmente hiciera falta migración (no esperado), encadenar tras `20260515_0005`.

## Semántica confirmada por el usuario

- Opción A: **una agencia con N sitios WordPress propios** (no es N agencias compartiendo un GHL).
- Publish behavior: "no aplica ahora" → el path GHL queda intacto, todos los reels van al mismo `provider_connections.external_id` de la agencia.

## Diagnóstico corregido (verificado leyendo ORM y routers en directo)

**El schema YA soporta multi-WP por agencia.** El UNIQUE real en `ingestion_sources` (`shared/db/orm.py:64-75`) es:
- `UNIQUE(kind, external_id)` — global, impide colisión de `site_id` entre agencias.
- `UNIQUE(agency_id, kind, external_id)` — **3 columnas**, no 2. NO fuerza 1 WP por agencia; sólo deduplica el mismo `external_id` dentro de la agencia.

El schema explorer leyó mal y reportó "UNIQUE(agency_id, kind)" inexistente. El explorer del webhook lo dijo bien (líneas 100-107 de `progress/explore_wordpress_webhook_ingestion.md`).

**El CRUD admin YA soporta multi-WP por agencia:**
- `GET/PUT /v1/admin/wordpress-sources/{site_id}` (`modules/ingestion/transport/http/wordpress_sources_router.py:63-200`) crea/actualiza sites y persiste el `webhook_secret` en BBDD vía `ProvisionWordPressSourceUseCase`.
- `GET /v1/admin/agencies/{agency_id}/sources` (`modules/ingestion/transport/http/sources_router.py`) lista las fuentes de una agencia (ya N).

**Gap real (único bloqueante en producción):** el webhook handler **sólo lee secrets de env** (`modules/ingestion/transport/http/wordpress_webhook_router.py:179`: `settings.site_secrets.get(site_id)`). Para añadir un site nuevo hoy hay que añadirlo a `WEBHOOK_SITE_SECRETS` y **reiniciar el servicio** (mensaje literal: "Add the site to WEBHOOK_SITE_SECRETS on the deployed service and restart it", línea 186). Eso convierte el modelo en operativamente 1:1 aunque el schema permita N:1.

## Plan de feature 38 — `db_backed_webhook_secrets`

Único cambio funcional: resolver el secret desde `ingestion_sources.secrets_encrypted` en lugar de (o como primera prioridad antes de) `WEBHOOK_SITE_SECRETS`. Sin migración, sin nuevas tablas, sin nuevos endpoints.

### Scope

1. **Webhook handler** (`modules/ingestion/transport/http/wordpress_webhook_router.py`):
   - Reemplazar `settings.site_secrets.get(site_id)` por un lookup en BBDD vía `IngestionSourceRepository.get_by_kind_external_id(kind='wordpress', external_id=site_id)` → descifrar `secrets_encrypted` con `shared/db/security.decrypt_text(...)`.
   - **Fallback a env** sólo si el row no tiene `secrets_encrypted` (cubre legacy de sites provisionados sin secret en BBDD). El fallback se registra como warning para forzar la migración operativa.
   - Si ni BBDD ni env tienen secret → 401 `INVALID_WEBHOOK_CREDENTIALS` (comportamiento actual).
2. **No tocar** `ProvisionWordPressSourceUseCase` ni `wordpress_sources_router.py` — ya persisten correctamente el secret.
3. **Tests integration** (`tests/integration/ingestion/test_wordpress_webhook_flow.py`):
   - Nuevo test: webhook con secret persistido en BBDD (sin env) → 202.
   - Nuevo test: webhook con secret en BBDD que no matchea → 401.
   - Nuevo test: site sin secret en BBDD pero con env (fallback legacy) → 202 + warning log.
   - Nuevo test: dos sites WP distintos para la misma agencia, ambos ingestan correctamente (cubre el caso multi-WP end-to-end aunque ya pase con el flow actual — vale como regression guard).
4. **Tests unit** (`tests/unit/ingestion/test_wordpress_webhook_router_secret_resolution.py` nuevo): mock del repo + assert orden de resolución BBDD → env.
5. **Sin cambios en** schema, migrations, frontend, GHL adapter, publishing path.

### Verificación

- `bash ./init.sh` (baseline + tests nuevos).
- `.venv/bin/python -m apps.api --check`.
- Manual contra `:8001`: provisionar 2 sites WP para una misma agencia (PUT `/v1/admin/wordpress-sources/site-a`, PUT `/v1/admin/wordpress-sources/site-b`), enviar webhook a cada uno con su secret persistido (sin tocar `WEBHOOK_SITE_SECRETS`), verificar 202 y jobs encolados con la agencia correcta.

### Acciones inmediatas tras aprobación del usuario

1. Añadir feature `id: 38, name: "db_backed_webhook_secrets"` a `feature_list.json` con status `pending`.
2. Marcar `in_progress`.
3. Lanzar `implementer` con scope estricto al webhook router + tests.
4. Tras `impl_38.md`, lanzar `reviewer`.
5. **No solaparse con feature 37**: no tocar `modules/reels/`, `modules/rendering/`, `shared/db/orm.py`, `docs/openapi.json`. Si se necesita regenerar `docs/http_surface.md`/`docs/openapi.json` por esta feature, **diferir** hasta que feature 37 cierre (sólo añadiríamos tests, el contrato HTTP del webhook no cambia).

## Exploración previa (3 informes en disco — útiles pero el de schema tiene un error)

1. `progress/explore_ghl_account_shape.md` — fiable.
2. `progress/explore_wordpress_webhook_ingestion.md` — fiable; sección 2 (líneas 100-107) tenía la lectura correcta del UNIQUE.
3. `progress/explore_schema_agency_site_ghl.md` — **contiene un error**: las líneas 339-348 dicen "UNIQUE(agency_id, kind)" que NO existe en el ORM. La UNIQUE real es `(agency_id, kind, external_id)` (3 cols) → no bloquea multi-WP. Si releemos, ignorar esa sección y confiar en el ORM (`shared/db/orm.py:64-75`).

## Lo que NO se ha tocado todavía

- Cero ediciones en `apps/`, `modules/`, `shared/`, `settings/`, `alembic/`, `tests/`.
- Cero entradas en `feature_list.json`.
- Sólo se escribieron 3 informes en `progress/` y este bloque WIP.

---

# Feature 32 — reels_list_pagination_and_filters (Claude implementer)

- **Inicio:** 2026-05-15
- **Agente:** Claude (rol implementer, lanzado por leader)
- **Modulos afectados:** `modules/reels/application/use_cases/list_reels.py`, `modules/reels/transport/http/admin_reels_router.py`, `modules/reels/transport/payloads/admin_reels.py`, `modules/reels/infrastructure/reel_query.py`, `tests/integration/reels/test_list_reels_pagination.py`, `tests/unit/reels/test_list_reels.py`, `docs/API.md`.
- **Toca schema?:** No.

## Plan

- Extender `ReelQuery` con `list_recent_for_agency(filters/offset)` + `count_for_agency(filters)` que reusan un helper interno para el WHERE compuesto (incluye JOIN a `properties.list_reference` para el match de `q`).
- Extender `ListReelsUseCase.execute` para aceptar `page`, `page_size`, `workflow_state: tuple|None`, `publish_status: tuple|None`, `q: str|None`, devolver `(items, count_total, page, page_size)`.
- Router: parsear query params (CSV → tuple, clamp page>=1, 1<=page_size<=100, q trim → None si vacío, backcompat `?limit=` cuando no llega `page`), validar valores enum (422 con código), serializar response con `count_total`, `page`, `page_size`, `has_more`, y `count` (legacy = len(items)).
- Tests integration nuevos (50 reels seedeados, paginación, filtros, CSV, `q` parcial sobre title/slug/list_reference, clamping, backcompat `?limit=`); preservar tests existentes.
- Documentar params nuevos en `docs/API.md`.

## Cierre

- 2026-05-15: feature 32 lista para review; reporte en `progress/impl_32.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; 918 passed). `apps.api --check` verde. Estado en `feature_list.json`: `in_progress`. No se marcó `done`; espera reviewer.
- 2026-05-15: Review feature 32 (back) approved; ver `progress/review_32.md`.

---

# Feature 33 — agency_outro_video_upload_and_render (Claude implementer)

- **Inicio:** 2026-05-15 (hora UTC alrededor de las 18:25)
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** Sí (nueva tabla `agency_intro_outro_assets`)
- **Modulos afectados:** `modules/configuration/{domain,application,infrastructure,transport}/`, `alembic/versions/20260515_0002_agency_outro_assets.py`, `shared/storage/site_layout.py`, `modules/rendering/application/scripted_video/` (helper concat), `modules/rendering/infrastructure/ffmpeg/render_reel.py`, `apps/api/app_factory.py`, `tests/integration/configuration/test_outro_router.py`, `tests/integration/rendering/test_render_with_outro.py`, `tests/unit/configuration/test_outro_validator.py`.

## Plan

- Decisión schema: NUEVA tabla `agency_intro_outro_assets(agency_id, kind 'intro'|'outro', object_key, duration_seconds, source 'uploaded'|'brand_card'|'none', created_at, updated_at)` con UNIQUE(agency_id, kind) — feature 34 reusará la misma tabla con `kind='intro'`. `outro_enabled` se añade como columna nueva en `agency_reel_defaults` (paralelo a `intro_enabled` existente).
- HTTP: `POST /v1/admin/agencies/{id}/outro/upload` (multipart `file`), `GET /v1/admin/agencies/{id}/outro/file`, `DELETE /v1/admin/agencies/{id}/outro`. GET `/defaults` agrega `outro_object_key`, `outro_duration_seconds`, `outro_source`, `outro_enabled`.
- Validación: 422 INVALID_MIME (no video/mp4|video/quicktime), 413 FILE_TOO_LARGE (>50MB), 422 INVALID_DURATION (no 1≤s≤10) — via ffprobe.
- Storage FS: `{workspace}/generated_media/_agency_outro/{safe_agency}/<sha1>.<ext>` (mirror del patrón music).
- Renderer: nuevo helper `concat_outro_to_reel` que normaliza outro (scale/SAR/DAR/fps/audio sample rate match) antes del concat demuxer; se enchufa en `generate_property_reel_from_data` cuando `outro_source='uploaded' && outro_enabled=true`. `brand_card` → loguea warning + no-op (documentado como pendiente).
- Migración 20260515_0002 encadenada tras 20260515_0001; up + down + up clean.

## Bitacora


- 2026-05-15: feature 33 lista para review; reporte en `progress/impl_33.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; 943 passed). `apps.api --check` + `apps.worker --check` verdes. Migración `20260515_0002_agency_outro_assets` round-trip clean (up/down/up). 25 tests nuevos (10 router integration + 10 unit validator + 5 render concat). Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.
- Review feature 33 (back) approved; ver `progress/review_33.md`

---

# Feature 34 — agency_intro_video_upload_and_render (Claude implementer)

- **Inicio:** 2026-05-15
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** No (reusa tabla `agency_intro_outro_assets` y migración `20260515_0002` de feature 33). `intro_enabled` ya existe en `agency_reel_defaults` desde la migración inicial.
- **Modulos afectados:** `modules/configuration/{application,transport}/`, `modules/rendering/infrastructure/ffmpeg/` (refactor a helper genérico), `modules/rendering/application/frame_composition.py`, `modules/reels/{domain,application}/`, `apps/api/app_factory.py`, `tests/integration/configuration/test_intro_router.py`, `tests/integration/rendering/test_render_with_intro.py`, `tests/unit/configuration/test_intro_validator.py`.

## Plan

- Refactor `outro_concat.py` → `video_segment_concat.py` genérico con `concat_segment(reel_path, segment_path, output_path, position: 'start'|'end', ...)`. Mantener `outro_concat.py` como wrapper delgado para no romper imports de feature 33 mientras se completa la transición; alternativamente, retirar y actualizar el call site (decisión: extender renderer y eliminar wrapper para evitar duda; preservar misma normalización).
- Nuevos use cases en `modules/configuration/application/use_cases/`: `upload_intro_video.py`, `delete_intro_video.py`, `read_intro_asset.py` simétricos a los de outro.
- Nuevo router `modules/configuration/transport/http/intro_router.py` simétrico a `outro_router.py`.
- Extender `GET /defaults` (`defaults_router.py`) y la lectura simétrica para `read_intro_asset` para exponer `intro_object_key`, `intro_duration_seconds`, `intro_source`. (`intro_enabled` ya está expuesto.)
- En `ingest_property_into_reel.py`, añadir simétrico `_resolve_agency_intro_asset` y forward de `intro_local_path/source/duration` al `PropertyContext`.
- `PropertyContext` extendido con `intro_local_path / intro_source / intro_duration_seconds`.
- En `frame_composition.py`, añadir gate paralelo a outro: cuando `intro_source=='uploaded' && intro_local_path is not None` antes de la generación del poster, prepend del intro al reel. Orden cuando ambos: `intro + base_reel + outro` (concat intro primero, luego outro, sobre el mismo `media_path`).
- `apps/api/app_factory.py`: enchufar `create_intro_router`. Igual en `tests/integration/configuration/_client.py`.
- Tests: integration router (mismo matrix que outro), integration render (renderer routea intro, combinado con outro), unit validator. Reusar fixtures de feature 33.

## Bitacora

- 2026-05-15: baseline `bash ./init.sh` exit 0 con 943 passed + 3 known-flaky; arrancando implementación.
- 2026-05-15: feature 34 lista para review; reporte en `progress/impl_34.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; **971 passed = 943 + 28 nuevos**). `apps.api --check` + `apps.worker --check` verdes. Sin migración nueva (`alembic current` = `20260515_0002 (head)`, reusa la de feature 33). 28 tests nuevos (11 router integration + 7 render integration + 10 unit validator). Refactor: extraído `concat_outro_to_reel` a helper genérico `video_segment_concat.concat_segment(position='start'|'end', ...)`; outro/intro son wrappers delgados; los 25 tests de feature 33 siguen verdes. Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.
- Review feature 34 (back) approved; ver `progress/review_34.md`

---

# Feature 35 — per_reel_photos_override (Claude implementer)

- **Inicio:** 2026-05-15
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** Sí — nueva columna `reels.photos_override JSONB NULL` + migración encadenada `20260515_0003_reels_photos_override.py` (`down_revision="20260515_0002"`).
- **Modulos afectados:** `alembic/versions/20260515_0003_reels_photos_override.py`, `modules/reels/{domain,application,infrastructure,transport}/`, `modules/rendering/application/frame_composition.py`, `modules/reels/domain/types.py` (`PropertyContext.photos_override`), `tests/integration/reels/test_reel_photos_override.py`, `tests/integration/rendering/test_render_with_photos_override.py`.

## Plan

- Migración 0003: añade `reels.photos_override JSONB NULL`. Up/down/up clean.
- `ReelState` gana campo `photos_override: list[dict[str, Any]] | None = None`; repo lee/escribe JSONB y normaliza `[]` → `None`.
- Nuevo use case `UpdateReelPhotosOverrideUseCase`: valida positions cubren `[0, N)` (N = count `property_images`), reusa la 409-gate de features 21/25 (`workflow_state=approved` o `publish_status=published` → 409 `PHOTOS_OVERRIDE_LOCKED`), persiste, re-encola job vía la misma maquinaria que feature 25.
- Pydantic `ReelPhotosOverridePayload` con `extra="forbid"`; entries con `extra="forbid"` también.
- PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/photos` en `admin_reels_router.py` con auth + error mapping uniforme.
- Render call site: `frame_composition._render_reel` aplica `context.photos_override` para reordenar/filtrar `selected_photo_paths` antes de construir el manifest. La fuente del override en el `PropertyContext` es `reel_state.photos_override` (cargado por el ingest como las otras overrides).
- Tests integration: happy path + clear (null & []) + 422 (gap/dup/out-of-range/wrong-type/extra) + 409 (approved/published). Render integration: reversed order + null fallback + selected=false filtra.

## Cierre

- 2026-05-15: feature 35 lista para review; reporte en `progress/impl_35.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; **988 passed = 971 + 17 nuevos**). `apps.api --check` + `apps.worker --check` verdes. Migración `20260515_0003_reels_photos_override` round-trip clean (up/down/up; head = `20260515_0003`). 17 tests nuevos (13 integration router + 4 render integration). Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.
- 2026-05-15: Review feature 35 (back) APPROVED — ver `progress/review_35.md`. Drive-by `music_id` en `_build_ingested_reel_state` aceptado como bug-fix real (sin regresión: 190 tests de `reels` pasan). Tres follow-ups no bloqueantes flaggeados (`ReelORM.photos_override` no añadido al modelo SQLAlchemy, `docs/API.md` sin sección nueva, `docs/http_surface.md`+`docs/openapi.json` sin regenerar). Estado en `feature_list.json` → `done`.

---

# Feature 36 — per_reel_subtitles_override (Claude implementer)

- **Inicio:** 2026-05-15 (UTC)
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** Sí (reels.subtitles_override JSONB NULL) — migración `20260515_0004_reels_subtitles_override.py` encadenada tras `20260515_0003`.
- **Modulos afectados:** `alembic/versions/20260515_0004_reels_subtitles_override.py`, `shared/db/orm.py`, `modules/reels/{domain,application,infrastructure,transport}/`, `modules/rendering/`, `tests/integration/reels/test_reel_subtitles_override.py`, `tests/integration/rendering/test_render_with_subtitles_override.py`.

## Plan

- Replicar el 6-point pattern de feature 35 (con `subtitles_override`):
  1. Migración 0004 añade `reels.subtitles_override JSONB NULL`.
  2. `ReelORM.subtitles_override` en `shared/db/orm.py` (NO saltarse este paso — feature 35 lo olvidó).
  3. `ReelState.subtitles_override: list[dict] | None = None`.
  4. `reel_state_repository.py`: SQL INSERT/UPDATE + `_subtitles_override_to_jsonb_param` + reader; ON CONFLICT DO UPDATE preserva valor existente sin clobbering.
  5. `_build_ingested_reel_state` propaga `state.subtitles_override` para que re-ingest no lo borre.
  6. `_peeked_existing_state.subtitles_override` forward al `PropertyContext.subtitles_override` en el ingest.
- Nuevo use case `UpdateReelSubtitlesOverrideUseCase`: valida cues (in/out>=0, out>in, no overlap, index único y monotónico, text 1-200, extra='forbid'); 409 cuando `workflow_state=approved` OR `publish_status=published` (`SUBTITLES_OVERRIDE_LOCKED`); persiste y re-encola con misma maquinaria que features 25/35.
- Pydantic `ReelSubtitlesOverridePayload` con cues estrictos.
- PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/subtitles` en `admin_reels_router.py`.
- Render call site: bypass `compose_subtitle_segments` (autoCaptions) cuando `context.subtitles_override` está presente; en su lugar generar `subtitle_segments` directamente desde los cues (reutilizar `measure_text_block` y el geometry del subtitle_style).
- Tests: 12+ integration en `test_reel_subtitles_override.py` (happy, clear null/[], 9 validation cases 422, 2 cases 409, 404, survives re-ingest); render integration: override → cues custom usados; null + autoCaptions on → fallback; null + autoCaptions off → no subs.

## Bitacora

- 2026-05-15: baseline `bash ./init.sh` exit 0 (988 passed + 3 known-flaky). Arrancando implementación.
- 2026-05-15: feature 36 lista para review; reporte en `progress/impl_36.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; **1010 passed = 988 + 22 nuevos**). `apps.api --check` + `apps.worker --check` verdes. Migración `20260515_0004_reels_subtitles_override` round-trip clean (up/down/up; head = `20260515_0004`). 22 tests nuevos (17 router integration + 5 render integration). 6-point pattern aplicado en su totalidad (incluyendo point 2 `ReelORM.subtitles_override` que feature 35 había saltado). Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.
- 2026-05-15: Review feature 36 (back) APPROVED — ver `progress/review_36.md`. 6-point pattern auditado punto por punto (file:line); todos los criterios de aceptación del leader verificados. Migración round-trip clean re-ejecutada por el reviewer. `init.sh` confirma 1010 passed + mismos 3 known-flaky. Regresión features 25/35 verde (22 passed en `test_reel_photos_override.py` + `test_admin_reels_music_override.py`). Tres follow-ups no bloqueantes documentados (ORM `photos_override` aún pendiente — deferred a feature 37; `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` sin regenerar — deferred a feature 37). Estado en `feature_list.json` → `done`.

---

# Feature 38 — db_backed_webhook_secrets (Claude implementer)

- **Inicio:** 2026-05-16
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** No (la columna `ingestion_sources.secrets_encrypted` ya existe; cero DDL nuevo).
- **Modulos afectados:** `modules/ingestion/transport/http/wordpress_webhook_router.py`, `modules/ingestion/domain/ingestion_source.py`, `modules/ingestion/infrastructure/ingestion_source_repository.py`, `tests/integration/ingestion/test_wordpress_webhook_flow.py`, `tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py`.

## Plan

- Extender `IngestionSource` domain con `secrets_encrypted: bytes | None = None` (default-friendly, no rompe callers).
- Actualizar `_row_to_source` para poblar el nuevo campo (sigue calculando `has_secret` igual).
- Añadir helper `_resolve_expected_secret(uow, site_id, env_site_secrets, logger)` en `wordpress_webhook_router.py` con la prioridad BBDD → env (warning) → None.
- Abrir un UoW corto para el lookup ANTES de la rama 401; cerrarlo antes de emitir 401 (no mantener sesión abierta cubriendo la rama de error).
- Sustituir línea 179 (`expected_secret = settings.site_secrets.get(site_id)`) por la llamada al helper.
- Mantener intacta la rama 401 (mismo body, code, hint, details) y la rama `settings.security_disabled`.
- Tests integration: 4 nuevos en `test_wordpress_webhook_flow.py` con `security_disabled=False` y firma real.
- Tests unit: archivo nuevo `tests/unit/ingestion/test_wordpress_webhook_secret_resolution.py` con 4 casos (BBDD secret, BBDD null + env, ambos null, BBDD None + env).

## Bitacora

- 2026-05-16: arrancando implementación.
- 2026-05-16: feature 38 lista para review; reporte en `progress/impl_38_db_backed_webhook_secrets.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; **1040 passed = 1032 + 8 nuevos** [4 integration + 4 unit]). `apps.api --check` + `apps.worker --check` verdes. Sin migración (la columna `ingestion_sources.secrets_encrypted` ya existía). Helper `_resolve_expected_secret` con prioridad BBDD → env (warning) → None enchufado en el handler vía un UoW corto cerrado antes del 401. Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.

- **Inicio:** 2026-05-15 (UTC)
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** Sí (reels.manifest_override JSONB NULL) — migración `20260515_0005_reels_manifest_override.py` encadenada tras `20260515_0004`.

## Plan

- Replicar el 6-point pattern de features 35/36 (con `manifest_override`):
  1. Migración 0005 añade `reels.manifest_override JSONB NULL`.
  2. `ReelORM.manifest_override` + retro-fix `ReelORM.photos_override` (cierre del follow-up de feature 35).
  3. `ReelState.manifest_override: list[dict] | None = None`.
  4. `reel_state_repository.py`: SQL INSERT/UPDATE + `_manifest_override_to_jsonb_param` + reader; ON CONFLICT preserva sin clobber.
  5. `_build_ingested_reel_state` propaga `state.manifest_override`.
  6. `_peeked_existing_state.manifest_override` forward al `PropertyContext.manifest_override`.
- Nuevo use case `UpdateReelSlidesOverrideUseCase`: valida slides (5 kinds discriminated union, positions cubren [0,N), durations sum ≤ target * 1.5, slide_id único no vacío); 409 cuando approved/published (`SLIDES_OVERRIDE_LOCKED`); persiste y re-encola.
- Pydantic `ReelSlidesOverridePayload` con discriminated union Pydantic v2 (`Field(discriminator='kind')`) en `modules/reels/transport/payloads/admin_reels.py`.
- PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/slides` en `admin_reels_router.py`.
- Render call site: cuando `context.manifest_override` está presente, el render plan se construye desde el override (positions ordenadas; cada slide kind drives scene creation). Wrap de la función existente para aceptar override en lugar del manifest auto-generado, sin reinventar el renderer.
- Tests: integration router (happy per kind + clear + 422 + 409 + survives re-ingest); render integration (override → manifest comparison; null → fallback; mixed kinds).
- Cerrar inherited follow-ups de features 35/36: ORM `photos_override` + docs/API.md sections (35/36/37) + regenerate http_surface.md + openapi.json.

## Cierre

- 2026-05-15: feature 37 lista para review; reporte en `progress/impl_37.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; **1032 passed = 1010 + 22 nuevos**). `apps.api --check` + `apps.worker --check` verdes. Migración `20260515_0005_reels_manifest_override` round-trip clean (up/down/up; head = `20260515_0005`). 22 tests nuevos (17 router integration + 5 render integration). 6-point pattern aplicado en su totalidad. Inherited follow-ups A/B/C cerrados: `ReelORM.photos_override` añadido al ORM, `docs/API.md` recibe tres secciones nuevas (PATCH /photos, /subtitles, /slides), `docs/http_surface.md` + `docs/openapi.json` regenerados con `scripts/generate_http_surface.py --write`. Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.
- Review feature 37 (back) approved; ver `progress/review_37.md`

---

# Docs review + deployment docs (Claude, leader) — 2026-05-16

> **Estado:** completado. Tareas de documentación, no toca código.

## Petición

Usuario pidió: "lances reviews para comprobar que todo este bien y que mejores la documentacion de los dos proyectos y que detalles como desplegarlos".

## Auditorías lanzadas (4 en paralelo, Explore agents)

1. **Backend state** — inline (Explore no escribe). Top hallazgos: tests baseline ~1032 passed + 3 known-flaky; migration chain limpia head `20260515_0005`; 1 TODO residual. Feature 37 ya estaba `done` (otro agente cerró entre tanto) — la auditoría se confundió pero fue corregido.
2. **Frontend state** — inline. Top: build verde 2.4s, lint verde, 321/324 tests passing (1 fallo en tablet `social_templates.spec.js:19` por timing race en mock, no bloqueante), 2 skipped. Bundle 25 MB dist.
3. **Backend deployment** — `progress/audit_backend_deployment_2026_05_16.md` (1041 líneas). Top gaps: `docker/Dockerfile` faltaba aunque `compose.yml` lo referenciaba; sin `docs/DEPLOYMENT.md` paso-a-paso; nombres de servicio inconsistentes entre `AGENTS.md` (`reels.service` en repo `4property/4robert`) y `deploy/rocky-linux/` (`cpihed.service`, `reels-test.service`).
4. **Frontend deployment** — `/opt/projects/4Reels-Frontend/progress/audit_frontend_deployment_2026_05_16.md` (560 líneas). Top gaps: sin inyección documentada de `VITE_MVP_API_URL` en producción; CI/CD sin lint/test gate previo al deploy; versión stuck en `0.0.0`.

## Decisiones del usuario (vía AskUserQuestion)

- Dockerfile: **crear mínimo**.
- Nombres de servicio: **documentar ambos mundos** (prod corre desde repo hermano `4property/4robert` con `reels.service`; este repo en :8001 con `reels-test.service`).
- Feature 38: **marcar `done` y archivar WIP**.

## Cambios entregados

### Backend (`/opt/projects/4Reels-Backend`)

- ✨ `docker/Dockerfile` **nuevo** — Python 3.12-slim + ffmpeg + `requirements.txt`, parametriza CMD vía `compose.yml`. `docker compose build` ya no falla.
- ✨ `docs/DEPLOYMENT.md` **nuevo** — guía completa: 3 modos (local docker, test/staging systemd `:8001`, producción systemd `:8000` desde repo hermano), variables de entorno con tabla de criticidad, recipes de migración, troubleshooting, ejemplo de `PUT /v1/admin/wordpress-sources/{site_id}` post-feature-38.
- 🔧 `README.md` — Layout actualizado a la realidad Phase 4 (`apps/`, `modules/`, `shared/`, `settings/`, `alembic/`, `tests/`); Setup limpio con `python3.12 -m venv` + `alembic upgrade head`; añadida mención de feature 38 y enlaces a `docs/DEPLOYMENT.md` + `deploy/rocky-linux/README.md`.
- 🔧 `feature_list.json` — id 38 marcado `done`.
- 🔧 `progress/current.md` — bloque WIP de feature 38 transformado en bloque de cierre (este archivo); añadido este bloque resumen de docs.

### Frontend (`/opt/projects/4Reels-Frontend`)

- ✨ `README.md` **nuevo** (no existía) — stack, quickstart, tabla de scripts, layout, env vars básicos, deploy summary, backend pairing.
- ✨ `docs/DEPLOYMENT.md` **nuevo** — 3 entornos (local dev, preview/Playwright, producción nginx), workflow de `.github/workflows/deploy.yml`, secrets requeridos, hardening recomendado (lint/test gate, `.env` injection, versionado), inventario de `VITE_*`, troubleshooting.

### Zonas NO tocadas (por respeto a feature 37 / por convención)

- `apps/`, `modules/`, `shared/`, `settings/`, `alembic/`, `tests/`, `main.py` raíz.
- `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` (regenerados por feature 37 hace pocas horas).
- `AGENTS.md`, `CLAUDE.md`, `ARCHITECTURE.md` (mencionan `reels.service` — la decisión fue documentar la dualidad en el nuevo `DEPLOYMENT.md`, no reescribir las instrucciones existentes).
- Frontend `src/`, `tests/`, `feature_list.json`.

## Follow-ups visibles que NO se atacaron

- Backend: `agency_intro_outro_assets` (features 33/34) no documentada en `docs/API.md` — corresponde al patrón de los implementers; doc-debt menor.
- Frontend: 1 test tablet (`social_templates.spec.js:19`) en rojo intermitente; voiceover (`VoiceoverPanel.jsx:83`) sigue stub.
- Frontend deploy: las recomendaciones de hardening del CI (lint+test gate, `.env` injection, version stamp) quedan documentadas en `docs/DEPLOYMENT.md` pero **no implementadas** — requieren tocar `.github/workflows/deploy.yml`, fuera del scope de "mejorar docs".


---

# Feature 39 cross-repo — live state sync reels dashboard + ordering guard — CERRADA

> **Estado (2026-05-16):** ambas mitades `done`. Reviewers APPROVED en los dos repos.

## Petición

Usuario: "analiza y mejora el manejo del estado entre front y backend, muchas veces hay que rrcargar la pagini para que se vean los cambios y muchas veces no se recibe feedback de las acciones que hace el usuario … el dashboard de reels debe ordenarse segun el ultimo reel modificado".

## Diagnóstico

Explorers identificaron que **el backend YA ordena por `r.updated_at DESC NULLS LAST`** (`modules/reels/infrastructure/reel_query.py:259`), todas las mutaciones tocan `updated_at` vía `ReelStateRepository.save()` (`reel_state_repository.py:261`), e índices existen. **El problema percibido como "orden mal" era en realidad "Dashboard no se invalida tras mutaciones en el editor overlay"**. Mismo problema para el feedback: faltaba toaster global, refetch silent en Approve/Reject.

Decisiones del usuario (vía `AskUserQuestion`):
- Toaster global compartido.
- Refetch on editor close (no en cada mutación).
- Alcance: Reels (Dashboard + editor) + test backend del orden. Brand/Music/Templates fuera.

## Resultados

### Backend `/opt/projects/4Reels-Backend` (feature 39 `test_reels_list_ordering_guard`)

- `tests/integration/reels/test_list_reels_ordering.py` nuevo — 2 tests guard del contrato `ORDER BY updated_at DESC`.
- Sin código de producción tocado.
- `bash ./init.sh` → 1042 passed = 1040 baseline + 2 nuevos; mismos 3 baseline failures conocidos.
- Informes: `progress/impl_39_test_reels_list_ordering_guard.md` + `progress/review_39_test_reels_list_ordering_guard.md`.

### Frontend `/opt/projects/4Reels-Frontend` (feature 39 `live_state_sync_reels_dashboard_and_editor`)

- `src/lib/hooks/useToast.js` nuevo — singleton + hook (vanilla React 18, sin libs externas).
- `src/shared/Toaster.jsx` nuevo — `role="status"`/`role="alert"`, auto-dismiss 4s/6s.
- `<Toaster />` montado en `src/app/Shell.jsx`.
- `DashboardRefetchContext` provee `refetch()` del `useReels()` al editor.
- `ReelEditor.jsx` trackea `hasMutated`; cada panel (Photos, MusicOverride, Subtitles, Slides, Descriptions) lo propaga vía `onMutate` prop; al cerrar el editor con `hasMutated=true`, dispara `dashboardRefetch()`.
- `Dashboard.jsx`: Approve/Reject envueltos en try/catch con toast success/error + disable durante in-flight.
- 9 specs E2E nuevos (3 escenarios × 3 viewports) en `tests/reels_dashboard_live_sync.spec.js`.
- `npm run build` + `npm run lint` + `npm run test:smoke` verdes; 330 e2e passed con sólo el flake pre-existente conocido (`social_templates.spec.js:19` tablet — documentado como pre-existing y no se ataca aquí).
- Sin nuevas dependencias en `package.json`.
- Informes: `progress/impl_39_live_state_sync_reels_dashboard.md` + `progress/review_39_live_state_sync_reels_dashboard.md`.

## Pendiente operativo (no incluido en la feature)

- Para que los cambios del frontend sean visibles en el server, hace falta `cd /opt/projects/4Reels-Frontend && npm run build` (CI workflow lo hace en push a `main`). El backend test stack `:8001` no necesita reinicio para esto.
- Follow-ups conocidos pre-existentes (no atacados): tabla `agency_intro_outro_assets` sin entrada en `docs/API.md`; flaky tablet en `social_templates.spec.js:19`; voiceover stub en `VoiceoverPanel.jsx`.

---

# Feature 40 — manual_reel_regenerate_endpoint (Claude implementer)

- **Inicio:** 2026-05-16
- **Agente:** Claude (rol implementer lanzado por leader)
- **Toca schema?:** No.
- **Modulos afectados:** `modules/reels/application/use_cases/regenerate_reel.py` (extender), `modules/reels/transport/http/admin_reels_router.py` (nuevo endpoint), `modules/reels/transport/payloads/admin_reels.py` (nuevo payload `ReelManualRegeneratePayload`), `tests/integration/reels/test_regenerate_reel_manual.py` (nuevo).

## Plan
- Extender `RegenerateReelUseCase.execute` con kwarg `mode: Literal['approve_and_regenerate','manual_only'] = 'approve_and_regenerate'`. Default preserva los callers existentes (approve handler).
- Pre-check inside use case:
  - `existing_state.publish_status == 'published'` → `RegeneratePublishedForbidden` (ApplicationError, code `REGENERATE_PUBLISHED_FORBIDDEN`).
  - `uow.delivery.jobs.find_active_job_for_property(... kind='reel_publish')` no-None → `RegenerateAlreadyInFlight` (code `REGENERATE_ALREADY_IN_FLIGHT`). Diferencia con el approve flow: approve hace idempotent-replay; el manual hard-fails con 409.
  - El approve handler sigue idempotent-replay sin tocar el 409 (orden de pre-checks decide quién se aplica).
- En `mode='manual_only'`: skipear `update_workflow_state` y `update_publish_status`; enqueue normal del render job. El payload del nuevo job persiste `reason` en `publish_context.manual_reason` para auditoría.
- Nuevo payload `ReelManualRegeneratePayload(reason: str | None, extra='forbid')` en `admin_reels.py`.
- Router: nuevo POST `/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate`. Body opcional/`{}`. Response 200: `{"render_status": "pending", "job_id": ..., "queued_at": ...iso}`. 409 con body literal `{"error": "<CODE>", "detail": "..."}` (shape del leader, no la canónica del project).
- Tests integration: happy + 404 + 409 published + 409 in-flight + override-survives + approve regression.
- Verificación: `bash ./init.sh`, los 4 pytest específicos del leader, `apps.api --check`, `apps.worker --check`.

## Bitacora

- 2026-05-16: feature 40 lista para review; reporte en `progress/impl_40.md`. `bash ./init.sh` exit 0 (mismos 3 fallos de baseline; **1050 passed = 1042 + 8 nuevos**). `apps.api --check` + `apps.worker --check` verdes. Use case `RegenerateReelUseCase.execute` extendido con `mode: Literal['approve_and_regenerate','manual_only'] = 'approve_and_regenerate'` (default preserva approve handler) + `manual_reason: str | None`. Dos excepciones nuevas: `RegeneratePublishedForbidden` (code `REGENERATE_PUBLISHED_FORBIDDEN`) y `RegenerateAlreadyInFlight` (code `REGENERATE_ALREADY_IN_FLIGHT`). Endpoint nuevo `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate`. 8 tests integration nuevos (`tests/integration/reels/test_regenerate_reel_manual.py`). Estado en `feature_list.json`: `in_progress`. No marcado `done`; espera reviewer.
- 2026-05-16: Review feature 40 (back) APPROVED — ver `progress/review_40.md`. Auditoría per-decision OK (HTTP contract literal verificado; `mode='manual_only'` no muta workflow/publish state; 2 excepciones → 409; conflict pre-check via `find_active_job_for_property` reusado; sin schema). Divergencia 409 body-shape vs feature 35 confirmada pero front-compatible (`RegenerateReelButton.jsx:58-67` lee `body.error` como discriminator, mismo shape que el back emite). Re-run de `./init.sh` reproducido en 1050 passed + 3 known-flaky de baseline. Estado en `feature_list.json` → `done`. Doc-debt (`docs/API.md` + `docs/http_surface.md` + `docs/openapi.json`) diferido a follow-up dedicado (no bloqueante).
