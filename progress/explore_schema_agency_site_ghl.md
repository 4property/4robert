# Mapeo de esquema relacional: Agencies ↔ WordPress Sites ↔ GHL Accounts

**Fecha de análisis:** 2026-05-15  
**Repo:** `/opt/projects/4Reels-Backend`  
**Fuentes:** `shared/db/orm.py`, `modules/configuration/infrastructure/orm.py`, `alembic/versions/`

---

## 1. Diagrama de tablas relevantes

### 1.1 Tenancy y configuración base

#### **agencies** (`shared/db/orm.py:49-59`)
```
┌─────────────────────────────────────────────────────┐
│ agencies (PK: id)                                   │
├─────────────────────────────────────────────────────┤
│ id (VARCHAR(36), PK)                                │
│ name (TEXT, NOT NULL)                               │
│ slug (TEXT, NOT NULL, UNIQUE)                       │
│ timezone (TEXT, NOT NULL)                           │
│ status (TEXT, NOT NULL)                             │
│ created_at, updated_at (TIMESTAMP WITH TZ)          │
└─────────────────────────────────────────────────────┘
```
**Índices:** `UNIQUE(slug)`  
**Cardinalidad de entrada:** 1 por agencia (raíz del árbol de tenancy)

---

#### **ingestion_sources** (`shared/db/orm.py:64-96`)
```
┌─────────────────────────────────────────────────────────────────┐
│ ingestion_sources (PK: id)                                      │
├─────────────────────────────────────────────────────────────────┤
│ id (VARCHAR(36), PK)                                            │
│ agency_id (VARCHAR(36), FK → agencies.id, CASCADE)              │
│ kind (TEXT, NOT NULL) ← Discriminator: 'wordpress', 'other'    │
│ external_id (TEXT, NOT NULL) ← WordPress site URL/ID            │
│ name (TEXT, NOT NULL)                                           │
│ config_json (JSONB, DEFAULT '{}') ← Site metadatos             │
│ secrets_encrypted (BYTEA, NULL)                                 │
│ status (TEXT, DEFAULT 'active')                                 │
│ last_event_at (TIMESTAMP WITH TZ, NULL)                         │
│ created_at, updated_at (TIMESTAMP WITH TZ)                      │
│                                                                 │
│ UNIQUE(kind, external_id)  ← 1 ingestion source per (kind, ID) │
│ UNIQUE(agency_id, kind, external_id)  ← per-agency de-duping  │
│ INDEX(agency_id, kind)                                          │
└─────────────────────────────────────────────────────────────────┘
```
**FK saliente:** `agencies.id`  
**FK entrante:** `properties`, `reels`, `webhook_events`, `jobs`, `outbox_events`, `media_revisions`, `scripted_video_artifacts`

**Nota crítica:** La tabla `ingestion_sources` **es agnóstica del proveedor de publicación**. Almacena solo datos de ingesta (WordPress, futuros orígenes RSS, etc.). Ni GHL ni ningún "sitio de publicación" están representados aquí.

---

#### **provider_connections** (`shared/db/orm.py:101-131`)
```
┌──────────────────────────────────────────────────────────────┐
│ provider_connections (PK: id)                                │
├──────────────────────────────────────────────────────────────┤
│ id (VARCHAR(36), PK)                                         │
│ agency_id (VARCHAR(36), FK → agencies.id, CASCADE)           │
│ provider (TEXT, NOT NULL) ← Discriminator: 'gohighlevel'    │
│ external_id (TEXT, DEFAULT '') ← GHL Location ID            │
│ config_json (JSONB, DEFAULT '{}')                           │
│ secrets_encrypted (BYTEA, NOT NULL) ← GHL API key           │
│ status (TEXT, DEFAULT 'active')                             │
│ created_at, updated_at (TIMESTAMP WITH TZ)                  │
│                                                              │
│ UNIQUE(agency_id, provider) ← 1 connection por proveedor   │
│ INDEX(provider, external_id)                                │
└──────────────────────────────────────────────────────────────┘
```
**FK saliente:** `agencies.id`  
**Cardinalidad:** 1:1 por `(agency_id, provider)` — una sola conexión GHL activa por agencia.

---

### 1.2 Catálogo de propiedades (WordPress)

#### **properties** (`modules/catalog/infrastructure/orm.py:24-130`)
```
┌───────────────────────────────────────────────────────────────┐
│ properties (PK: record_id, auto-increment)                    │
├───────────────────────────────────────────────────────────────┤
│ record_id (BIGINT, PK, AUTOINCREMENT)                         │
│ agency_id (VARCHAR(36), FK → agencies.id)                     │
│ ingestion_source_id (VARCHAR(36), FK → ingestion_sources.id)  │
│ external_source_id (TEXT, NOT NULL) ← renamed from "site_id" │
│ source_property_id (BIGINT, NOT NULL) ← WP post ID           │
│ slug, title, link, guid, status, ... (36+ columnas más)      │
│ image_folder, image_count, fetched_at                        │
│ social_publish_details_json, raw_json (JSONB)                │
│                                                              │
│ UNIQUE(external_source_id, source_property_id)              │
│ INDEX(external_source_id, slug)                             │
│ INDEX(agency_id, fetched_at DESC)                           │
└───────────────────────────────────────────────────────────────┘
```
**FK:** 
- Saliente: `agencies.id`, `ingestion_sources.id`
- Entrante: `property_images`, `reels`, `media_revisions`

---

#### **property_images** (`modules/catalog/infrastructure/orm.py:132-146`)
```
┌─────────────────────────────────────────────────────────────┐
│ property_images (PK: record_id, position)                   │
├─────────────────────────────────────────────────────────────┤
│ record_id (BIGINT, FK → properties.record_id, CASCADE)       │
│ position (INT, NOT NULL)                                    │
│ image_url (TEXT, NOT NULL)                                  │
│ local_path (TEXT, NULL)                                     │
└─────────────────────────────────────────────────────────────┘
```

---

### 1.3 Reels (renderización y publicación)

#### **reels** (`shared/db/orm.py:142-253`)
```
┌────────────────────────────────────────────────────────────┐
│ reels (PK: external_source_id, source_property_id)         │
├────────────────────────────────────────────────────────────┤
│ external_source_id (TEXT, NOT NULL) ← renamed from "site_id"│
│ source_property_id (BIGINT, NOT NULL)                      │
│ agency_id (VARCHAR(36), FK → agencies.id)                  │
│ ingestion_source_id (VARCHAR(36), FK → ingestion_sources)  │
│                                                            │
│ content_fingerprint, content_snapshot (JSONB)             │
│ publish_target_fingerprint, publish_target_snapshot (JSONB) │
│ descriptions_override, subtitles_override (JSONB, NULL)   │
│ photos_override, manifest_override (JSONB, NULL) ← Overr. │
│                                                            │
│ music_id (VARCHAR(36), FK → agency_music_tracks, SET NULL)│
│ render_template_id (TEXT, FK → render_templates)          │
│                                                            │
│ render_status, publish_status, workflow_state (TEXT)      │
│ publish_details (JSONB) ← {'videos': [...]}               │
│ last_published_provider_external_id (TEXT) ← GHL location │
│                                                            │
│ INDEX(agency_id, publish_status, updated_at DESC)         │
│ INDEX(agency_id, workflow_state, updated_at DESC)         │
└────────────────────────────────────────────────────────────┘
```
**FKs:**
- Saliente: `agencies.id`, `ingestion_sources.id`, `agency_music_tracks.id`, `render_templates.template_id`
- Entrante: ninguna tabla tiene FK hacia reels (PK compuesta, no es referenciada)

---

#### **media_revisions** (`shared/db/orm.py:255-292`)
```
┌────────────────────────────────────────────────────────────┐
│ media_revisions (PK: revision_id)                          │
├────────────────────────────────────────────────────────────┤
│ revision_id (VARCHAR(36), PK)                              │
│ agency_id, ingestion_source_id (FKs)                       │
│ external_source_id, source_property_id (TEXT, BIGINT)      │
│ artifact_kind, render_profile, media_path, metadata_path  │
│ mime_type, content_fingerprint, publish_target_fingerprint│
│ workflow_state (TEXT), created_at (TIMESTAMP)              │
└────────────────────────────────────────────────────────────┘
```

---

### 1.4 Configuración por agencia

#### **agency_brand_settings** (`modules/configuration/infrastructure/orm.py:50-74`)
```
┌──────────────────────────────────────────────┐
│ agency_brand_settings (PK: agency_id)         │
├──────────────────────────────────────────────┤
│ agency_id (VARCHAR(36), PK, FK cascade)      │
│ primary_color, secondary_color, logo_*       │
│ font_family (TEXT)                           │
│ created_at, updated_at                       │
└──────────────────────────────────────────────┘
```

#### **agency_reel_defaults** (`modules/configuration/infrastructure/orm.py:76-115`)
```
┌──────────────────────────────────────────────┐
│ agency_reel_defaults (PK: agency_id)         │
├──────────────────────────────────────────────┤
│ agency_id (VARCHAR(36), PK, FK cascade)      │
│ platforms (ARRAY[TEXT]) ← Targets: TikTok.. │
│ duration_seconds (INT, default 30)           │
│ music_id (TEXT) ← default track ID           │
│ intro_enabled (BOOL, default TRUE)           │
│ outro_enabled (BOOL, default FALSE) ← New   │
│ caption_template (TEXT)                      │
│ render_template_id (TEXT, FK)                │
│ settings (JSONB, free-form)                  │
│ created_at, updated_at                       │
└──────────────────────────────────────────────┘
```

#### **agency_automation_rules** (`modules/configuration/infrastructure/orm.py:117-153`)
```
┌──────────────────────────────────────────────┐
│ agency_automation_rules (PK: agency_id)      │
├──────────────────────────────────────────────┤
│ agency_id (VARCHAR(36), PK, FK cascade)      │
│ approval_required, quiet_hours_enabled, etc. │
│ publish_window_*, publish_days (ARRAY)       │
│ hold_window_seconds, skip_weekends (INT)     │
│ created_at, updated_at                       │
└──────────────────────────────────────────────┘
```

#### **agency_music_tracks** (`modules/configuration/infrastructure/orm.py:176-193`)
```
┌──────────────────────────────────────────────┐
│ agency_music_tracks (PK: id)                 │
├──────────────────────────────────────────────┤
│ id (VARCHAR(36), PK)                         │
│ agency_id (VARCHAR(36), FK cascade)          │
│ display_name, object_key (TEXT)              │
│ duration_seconds (INT)                       │
│ is_default (BOOL)                            │
│ created_at (TIMESTAMP)                       │
│ INDEX(agency_id)                             │
└──────────────────────────────────────────────┘
```

#### **agency_intro_outro_assets** (`alembic/versions/20260515_0002:41-80`)
```
┌──────────────────────────────────────────────┐
│ agency_intro_outro_assets (PK: id)           │
├──────────────────────────────────────────────┤
│ id (VARCHAR(36), PK)                         │
│ agency_id (VARCHAR(36), FK cascade)          │
│ kind (TEXT) ← 'intro' | 'outro' (CHECK)      │
│ object_key (TEXT, NULL)                      │
│ duration_seconds (INT, NULL)                 │
│ source (TEXT) ← 'uploaded'|'brand_card'|... │
│ created_at, updated_at (TIMESTAMP)           │
│                                              │
│ UNIQUE(agency_id, kind) ← 1 asset por kind │
└──────────────────────────────────────────────┘
```

#### **agency_social_templates** (`modules/configuration/infrastructure/orm.py:155-174`)
```
┌──────────────────────────────────────────────┐
│ agency_social_templates (PK: agency_id, plat)│
├──────────────────────────────────────────────┤
│ agency_id, platform (PK composite, CASCADE)  │
│ description_template, title_template (TEXT)  │
│ hashtags (ARRAY[TEXT])                       │
│ created_at, updated_at                       │
└──────────────────────────────────────────────┘
```

---

### 1.5 Eventos, jobs y audit

#### **webhook_events** (`shared/db/orm.py:297-323`)
```
┌───────────────────────────────────────────────┐
│ webhook_events (PK: event_id)                 │
├───────────────────────────────────────────────┤
│ event_id (VARCHAR(36), PK)                    │
│ agency_id, ingestion_source_id (FKs)          │
│ external_source_id (TEXT)                     │
│ source_kind (TEXT) ← discriminator            │
│ property_id (BIGINT, NULL)                    │
│ received_at, updated_at (TIMESTAMP)           │
│ status, raw_payload_hash, error_message       │
│                                               │
│ INDEX(external_source_id, received_at DESC)  │
│ INDEX(status, updated_at)                    │
└───────────────────────────────────────────────┘
```

#### **jobs** (`shared/db/orm.py:325-370`)
```
┌───────────────────────────────────────────────┐
│ jobs (PK: job_id)                             │
├───────────────────────────────────────────────┤
│ job_id (VARCHAR(36), PK)                      │
│ agency_id, ingestion_source_id, event_id (FK) │
│ kind (TEXT, default 'reel_publish')           │
│ external_source_id, property_id               │
│ provider_secrets_encrypted (BYTEA, NULL)      │
│ status, payload_json, publish_context_json    │
│ attempt_count, max_attempts, available_at     │
│ lease_expires_at, worker_id (TEXT)            │
│ last_error, created_at, updated_at, finished_ │
│ superseded_by_job_id (VARCHAR(36), NULL)      │
│                                               │
│ INDEX(status, available_at, created_at)      │
│ INDEX(external_source_id, property_id, ...)  │
│ INDEX(status, lease_expires_at)               │
└───────────────────────────────────────────────┘
```

#### **email_notifications** (`alembic/versions/20260514_0007:27-65`)
```
┌──────────────────────────────────────────────┐
│ email_notifications (PK: id)                 │
├──────────────────────────────────────────────┤
│ id (VARCHAR(36), PK)                         │
│ agency_id (VARCHAR(36), FK cascade)          │
│ event_kind (TEXT)                            │
│ site_id (TEXT) ← external_source_id value    │
│ source_property_id (INT)                     │
│ recipient_email (TEXT)                       │
│ status, provider_message_id, error_message   │
│ sent_at, created_at, updated_at              │
│                                              │
│ UNIQUE(agency_id, site_id, source_property.. │
│ INDEX(status)                                │
│ INDEX(agency_id, created_at DESC)            │
└──────────────────────────────────────────────┘
```
**Nota:** La columna `site_id` aquí es un TEXT aliasing de `external_source_id` (de `ingestion_sources`), **no** una FK. Desnormalización a propósito.

---

## 2. Multiplicidad real

### 2.1 Agency ↔ IngestionSource (WordPress)
```
RELACIÓN ACTUAL:
┌─────────────┬──────────────────────────┬─────────────┐
│   agency    │    ingestion_sources      │   (otros)   │
│ (1 tenancy) │   (kind='wordpress')      │             │
├─────────────┼──────────────────────────┼─────────────┤
│  1 id       │  N rows per agency       │             │
│             │  UNIQUE(agency_id, kind) │             │
│             │  → 1 WordPress source    │             │
│             │    per agency (típico)   │             │
└─────────────┴──────────────────────────┴─────────────┘

MULTIPLICIDAD: 1:N
- **1 agencia** puede tener **N fuentes de ingesta**
  (e.g., múltiples sitios WordPress, futuros feeds RSS)
- **PERO** hoy: UNIQUE(agency_id, kind='wordpress')
  fuerza **exactamente 1 WordPress site por agencia**
- Futuro: pueden existir múltiples fuentes no-WordPress
```

### 2.2 Agency ↔ ProviderConnection (GHL)
```
RELACIÓN ACTUAL:
┌─────────────┬──────────────────────────┐
│   agency    │  provider_connections    │
│ (1 tenancy) │  (provider='gohighlevel')│
├─────────────┼──────────────────────────┤
│  1 id       │  1 row per agency       │
│             │  UNIQUE(agency_id,       │
│             │         provider)        │
│             │  → 1 GHL account        │
└─────────────┴──────────────────────────┘

MULTIPLICIDAD: **1:1**
- Una **sola conexión GHL** por agencia, garantizada por UNIQUE.
- Si existe una segunda, `INSERT ... ON CONFLICT` la sustituye.
```

### 2.3 IngestionSource (WordPress) ↔ ProviderConnection (GHL)
```
RELACIÓN ACTUAL:
┌──────────────────────┬─────────────────────┐
│  ingestion_sources   │ provider_connections│
│  (WordPress site)    │ (GHL location)      │
├──────────────────────┼─────────────────────┤
│  N por agency        │  1 por agency       │
│  external_id =       │  external_id = GHL  │
│  WP URL/site ID      │  location ID        │
└──────────────────────┴─────────────────────┘

MULTIPLICIDAD: **N:1 (derivado via agency)**
- No hay FK directo entre ellas.
- Ambas cuelgan de la misma `agency_id`.
- En `publish_context_json` de los jobs se unen en memoria.
- Constraint implícito: 1 conexión GHL recibe videos de N propiedades
  WordPress (combinación de N WordPress + 1 GHL = 1 flujo de publicación).
```

---

## 3. Site/multi-tenant interno: Origen del `site_id`

### 3.1 Renombramientos recientes
De `shared/db/orm.py:1-14`:
```
Refactor plan (schema renames):
  `site_id`                 → `external_source_id`
  `wordpress_source_id`     → `ingestion_source_id`
  `last_published_location_id` → `last_published_provider_external_id`
```

### 3.2 Dónde vive `site_id` hoy
1. **En URLs admin** (contrato HTTP)
   - `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}`
   - De: `test_http_surface_contract.py` → `_normalize_reel_path()`
   - Mapeo: `site_id` URL param = `external_source_id` de `ingestion_sources`

2. **En reels.PK**
   - Clave primaria compuesta: `(external_source_id, source_property_id)`
   - De: `test_admin_reels_router.py:74`: `payload["items"][0]["site_id"] == seeded.external_source_id`
   - `site_id` es un alias de respuesta para `external_source_id`

3. **En email_notifications** (tabla reciente, 2026-05-14)
   - Columna `site_id` (TEXT, NOT NULL) desnormalizada
   - No es FK, solo valor copiado de `ingestion_sources.external_source_id`
   - Razonamiento: "auditoría + deduplicación por (agency, site, property, email, event)"

### 3.3 Atributos de ingestion_sources.external_id
- Valor: URL o ID del sitio WordPress (e.g., `"ckp.ie"`)
- Rol: Identificador global único dentro de `(kind='wordpress')`
- Constraint: `UNIQUE(kind, external_id)`
- No está "relacionado con el origen" además que es **el** origen WordPress

---

## 4. Constraints que bloquearían "una misma GHL recibiendo de múltiples WordPress"

### 4.1 A nivel de schema

| Tabla | Constraint | Efecto |
|-------|-----------|--------|
| `provider_connections` | `UNIQUE(agency_id, provider)` | ✓ Garantiza 1 GHL/agencia |
| `ingestion_sources` | `UNIQUE(agency_id, kind, external_id)` | 1 WordPress/agencia (soft) |
| `reels` | PK `(external_source_id, source_property_id)` | Rastreo per-property |
| `jobs` | `(agency_id, ingestion_source_id, ...)` | Vincular a origen WordPress |

### 4.2 A nivel de aplicación (observado)

1. **Worker de publicación** (`jobs` table):
   - Lee `provider_connection` (1:1 con agency)
   - Lee `ingestion_source_id` (qué WordPress generó la propiedad)
   - Construye `publish_context_json` con ambos
   - **Envía a GHL** con el `external_id` (location ID) de la conexión

2. **Pattern actual:** 1 agencia = 1 WordPress + 1 GHL:
   ```
   agency A
     ├─ ingestion_source (WordPress) ← 1 por UNIQUE(agency, kind)
     │   └─ properties (N desde WP)
     │       └─ reels (N reel per property)
     │           └─ publish a provider_connections (GHL) ← 1 por UNIQUE(agency, provider)
     └─ provider_connections (GHL)
   ```

3. **Si quisieras 1 GHL ← N WordPress:**
   - Necesitarías eliminar `UNIQUE(agency_id, kind, external_id)` en `ingestion_sources`
   - Permitir N filas `(agency_id, kind='wordpress', external_id=..., ...)`
   - Cambiar lógica de jobs para elegir **dinámicamente** a qué provider enviar
   - Hoy: el destino GHL es **estático** (1 location fijo por agencia)

---

## 5. Migraciones recientes (últimos 30 días)

### 5.1 Migraciones tocando tablas clave

| Fecha | Revisión | Tabla | Cambio |
|-------|----------|-------|--------|
| 2026-05-15 22:06 | `20260515_0005` | `reels` | ADD `manifest_override` (JSONB) |
| 2026-05-15 21:17 | `20260515_0004` | `reels` | ADD `subtitles_override` (JSONB) |
| 2026-05-15 20:11 | `20260515_0003` | `reels` | ADD `photos_override` (JSONB) |
| 2026-05-15 18:28 | `20260515_0002` | `agency_reel_defaults`, NEW | ADD `outro_enabled` (BOOL); CREATE `agency_intro_outro_assets` |
| 2026-05-15 16:59 | `20260515_0001` | `render_templates` | UPDATE preview_images para "side_banner" |
| 2026-05-14 20:00 | `20260514_0007` | NEW `email_notifications` | Tabla audit para notificaciones (nuevo) |
| 2026-05-14 18:02 | `20260514_0006` | `reels` | ADD `music_id` FK → `agency_music_tracks` (music override) |
| 2026-05-14 15:52 | `20260514_0005` | `agency_music_tracks` | SEED música NCS para agencias existentes |
| 2026-05-14 14:33 | `20260514_0004` | `agency_social_templates` | SEED templates sociales default |
| 2026-05-14 12:40 | `20260514_0003` | `reels` | ADD `descriptions_override` (JSONB) |
| 2026-05-14 12:36 | `20260514_0002` | `render_templates` | UPDATE preview "classic" |
| 2026-05-14 12:36 | `20260514_0001` | `agency_reel_defaults` | ADD `pinterest` a `platforms` ARRAY |
| 2026-05-13 13:21 | `20260513_0005` | `agency_automation_rules` | ADD `hold_window_seconds`, `quiet_hours_enabled`, `skip_weekends` |
| 2026-05-13 13:18 | `20260513_0004` | `render_templates` | SEED "side_banner" template |
| 2026-05-13 13:16 | `20260513_0003` | `properties` | ADD `wppd_accent_text_color`, `wppd_accent_background_color` |
| 2026-05-13 11:10 | `20260513_0002` | NEW `render_templates` | CREATE tabla templates, seed "classic" |
| 2026-05-01 09:59 | `20260501_0001` | ALL | Migración de refactor inicial: renombres, restructura |

### 5.2 Patrones de cambio

**Tendencia:** Columnas JSONB (`*_override`, `*_json`) para features de editor (fotos, subtítulos, música, manifiestos).  
**Impacto en schema:** Cero FKs nuevos entre agencia ↔ WordPress ↔ GHL. La estructura de tenancy es estable.

---

## 6. Resumen ejecutivo

### 6.1 Cardinalidades confirmadas

```
┌──────────────┐
│   Agency     │
└──────┬───────┘
       │
       ├─────1:N─────────────────────────── ingestion_sources (WordPress)
       │                                           │
       │                                           └──────────────┐
       │                                                          │
       ├─────1:1─────────────────────────── provider_connections (GHL)
       │
       ├─────1:N─────────────────────────── properties (WordPress posts)
       ├─────1:N─────────────────────────── reels (reel states)
       ├─────1:N─────────────────────────── agency_brand_settings
       ├─────1:N─────────────────────────── agency_reel_defaults
       ├─────1:N─────────────────────────── agency_automation_rules
       ├─────1:N─────────────────────────── agency_music_tracks
       ├─────1:N─────────────────────────── agency_intro_outro_assets
       ├─────1:N─────────────────────────── webhook_events
       └─────1:N─────────────────────────── jobs

agency : wordpress_site = 1 : 1 (hoy, UNIQUE(agency, kind))
agency : ghl_location = 1 : 1 (UNIQUE(agency, provider))
wordpress_site : ghl_location = N : 1 (derivado: múltiples propiedades WordPress → 1 destino GHL)
```

### 6.2 Concepto de `site_id`

- **Valor:** Identificador de la fuente de ingesta (WordPress URL/ID)
- **Vive en:** `ingestion_sources.external_id` (PK conceptual junto con `kind`)
- **Alias en URLs:** `/reels/{site_id}/{source_property_id}` → `external_source_id`
- **Alias en respuestas API:** Campo `site_id` en payloads JSON
- **Uso:** Rastrear qué WordPress generó qué propiedad → qué reel

### 6.3 Bloques para "1 GHL de N WordPress"

1. **`UNIQUE(agency_id, kind)` en `ingestion_sources`**  
   Requeriría: DROP e implementar lógica de selección dinámica de fuente en jobs

2. **`UNIQUE(agency_id, provider)` en `provider_connections`**  
   Ya está en su lugar — una sola GHL por agencia (no es un problema hoy)

3. **Lógica stateless de jobs**  
   Worker asume 1:1 agency-to-GHL; sería necesario pasar `ingestion_source_id` → lógica de enrutamiento

### 6.4 Salud del schema

✓ Normalización correcta (3NF, 4NF)  
✓ Constraints UNIQUE e índices presentes  
✓ FKs con `ON DELETE CASCADE` apropiados  
✓ Estructura de tenancy aislada (todos los agregados bajo `agency_id`)  
✓ Agnóstico a futuros proveedores (discriminadores `kind` / `provider`)

---

## Referencias de fuentes

| Archivo | Líneas | Concepto |
|---------|--------|----------|
| `shared/db/orm.py` | 1-14 | Refactor plan, renombres |
| `shared/db/orm.py` | 49-59 | AgencyORM |
| `shared/db/orm.py` | 64-96 | IngestionSourceORM |
| `shared/db/orm.py` | 101-131 | ProviderConnectionORM |
| `shared/db/orm.py` | 142-253 | ReelORM |
| `modules/catalog/infrastructure/orm.py` | 24-130 | PropertyORM |
| `modules/configuration/infrastructure/orm.py` | 50-115 | Agency config tables |
| `alembic/versions/20260501_0001_initial_schema.py` | 36-645 | Schema inicial (todas las tablas) |
| `alembic/versions/20260514_0007_email_notifications.py` | 26-65 | email_notifications table |
| `alembic/versions/20260515_0002_agency_outro_assets.py` | 41-80 | agency_intro_outro_assets |
| `tests/integration/reels/test_admin_reels_router.py` | 52-75 | Uso de `site_id` en respuestas |
| `tests/integration/test_http_surface_contract.py` | N/A | Contrato de URL `/reels/{site_id}/{source_property_id}` |
