# HTTP surface

Generated from the real FastAPI app with:

```bash
python scripts/generate_http_surface.py --write
```

Total routes: 51

| Method | Path | Tag | Handler | Module |
|---|---|---|---|---|
| GET | `/health` | Health | `health` | `apps.api.health_router` |
| GET | `/health/live` | Health | `health_live` | `apps.api.health_router` |
| GET | `/health/ready` | Health | `health_ready` | `apps.api.health_router` |
| GET | `/v1/admin/agencies` | Admin · Agencies | `list_admin_agencies` | `modules.tenancy.transport.http.admin_agencies_router` |
| POST | `/v1/admin/agencies` | Admin · Agencies | `create_admin_agency` | `modules.tenancy.transport.http.admin_agencies_router` |
| DELETE | `/v1/admin/agencies/{agency_id}` | Admin · Agencies | `delete_admin_agency` | `modules.tenancy.transport.http.admin_agencies_router` |
| GET | `/v1/admin/agencies/{agency_id}` | Admin · Agencies | `get_admin_agency` | `modules.tenancy.transport.http.admin_agencies_router` |
| PATCH | `/v1/admin/agencies/{agency_id}` | Admin · Agencies | `update_admin_agency` | `modules.tenancy.transport.http.admin_agencies_router` |
| GET | `/v1/admin/agencies/{agency_id}/automation` | Admin · Automation | `read_admin_agency_automation_rules` | `modules.configuration.transport.http.automation_router` |
| PUT | `/v1/admin/agencies/{agency_id}/automation` | Admin · Automation | `update_admin_agency_automation_rules` | `modules.configuration.transport.http.automation_router` |
| GET | `/v1/admin/agencies/{agency_id}/brand` | Admin · Brand | `read_admin_agency_brand_settings` | `modules.configuration.transport.http.brand_router` |
| PUT | `/v1/admin/agencies/{agency_id}/brand` | Admin · Brand | `update_admin_agency_brand_settings` | `modules.configuration.transport.http.brand_router` |
| GET | `/v1/admin/agencies/{agency_id}/defaults` | Admin · Defaults | `read_admin_agency_reel_defaults` | `modules.configuration.transport.http.defaults_router` |
| PUT | `/v1/admin/agencies/{agency_id}/defaults` | Admin · Defaults | `update_admin_agency_reel_defaults` | `modules.configuration.transport.http.defaults_router` |
| DELETE | `/v1/admin/agencies/{agency_id}/ghl-connection` | Admin · GHL connection | `detach_admin_agency_ghl_connection` | `modules.publishing.transport.http.connections_router` |
| GET | `/v1/admin/agencies/{agency_id}/ghl-connection` | Admin · GHL connection | `inspect_admin_agency_ghl_connection` | `modules.publishing.transport.http.connections_router` |
| POST | `/v1/admin/agencies/{agency_id}/ghl-connection` | Admin · GHL connection | `attach_admin_agency_ghl_connection` | `modules.publishing.transport.http.connections_router` |
| PUT | `/v1/admin/agencies/{agency_id}/ghl-connection` | Admin · GHL connection | `rotate_admin_agency_ghl_credentials` | `modules.publishing.transport.http.connections_router` |
| POST | `/v1/admin/agencies/{agency_id}/ghl-connection/test` | Admin · GHL connection | `probe_admin_agency_ghl_connection` | `modules.publishing.transport.http.connections_router` |
| GET | `/v1/admin/agencies/{agency_id}/music` | Admin · Music | `list_admin_agency_music_tracks` | `modules.configuration.transport.http.music_router` |
| POST | `/v1/admin/agencies/{agency_id}/music` | Admin · Music | `register_admin_agency_music_track` | `modules.configuration.transport.http.music_router` |
| DELETE | `/v1/admin/agencies/{agency_id}/music/{music_id}` | Admin · Music | `decommission_admin_agency_music_track` | `modules.configuration.transport.http.music_router` |
| GET | `/v1/admin/agencies/{agency_id}/music/{music_id}` | Admin · Music | `inspect_admin_agency_music_track` | `modules.configuration.transport.http.music_router` |
| PUT | `/v1/admin/agencies/{agency_id}/music/{music_id}` | Admin · Music | `reconfigure_admin_agency_music_track` | `modules.configuration.transport.http.music_router` |
| GET | `/v1/admin/agencies/{agency_id}/reel-profile` | Admin · Reel profile (raw) | `get_admin_agency_reel_profile` | `modules.configuration.transport.http.reel_profile_router` |
| PUT | `/v1/admin/agencies/{agency_id}/reel-profile` | Admin · Reel profile (raw) | `upsert_admin_agency_reel_profile` | `modules.configuration.transport.http.reel_profile_router` |
| GET | `/v1/admin/agencies/{agency_id}/reels` | Admin · Content | `list_admin_agency_reels` | `modules.reels.transport.http.admin_reels_router` |
| GET | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}` | Admin · Content | `get_admin_agency_reel` | `modules.reels.transport.http.admin_reels_router` |
| POST | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve` | Admin · Content | `approve_admin_agency_reel` | `modules.reels.transport.http.admin_reels_router` |
| GET | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images` | Admin · Content | `list_admin_agency_reel_images` | `modules.reels.transport.http.admin_reels_assets` |
| GET | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images/{position}/file` | Admin · Content | `stream_admin_agency_reel_image` | `modules.reels.transport.http.admin_reels_assets` |
| GET | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/manifest` | Admin · Content | `get_admin_agency_reel_manifest` | `modules.reels.transport.http.admin_reels_assets` |
| POST | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/reject` | Admin · Content | `reject_admin_agency_reel` | `modules.reels.transport.http.admin_reels_router` |
| GET | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/video` | Admin · Content | `stream_admin_agency_reel_video` | `modules.reels.transport.http.admin_reels_assets` |
| GET | `/v1/admin/agencies/{agency_id}/social-accounts` | Admin · Content | `list_admin_agency_social_accounts` | `modules.publishing.transport.http.social_accounts_router` |
| GET | `/v1/admin/agencies/{agency_id}/social-templates` | Admin · Social templates | `read_admin_agency_social_templates` | `modules.configuration.transport.http.social_templates_router` |
| PUT | `/v1/admin/agencies/{agency_id}/social-templates` | Admin · Social templates | `replace_admin_agency_social_templates` | `modules.configuration.transport.http.social_templates_router` |
| GET | `/v1/admin/agencies/{agency_id}/sources` | Admin - Sources | `list_ingestion_sources_endpoint` | `modules.ingestion.transport.http.sources_router` |
| POST | `/v1/admin/agencies/{agency_id}/sources` | Admin - Sources | `register_ingestion_source_endpoint` | `modules.ingestion.transport.http.sources_router` |
| DELETE | `/v1/admin/agencies/{agency_id}/sources/{ingestion_source_id}` | Admin - Sources | `decommission_ingestion_source_endpoint` | `modules.ingestion.transport.http.sources_router` |
| GET | `/v1/admin/agencies/{agency_id}/sources/{ingestion_source_id}` | Admin - Sources | `inspect_ingestion_source_endpoint` | `modules.ingestion.transport.http.sources_router` |
| PUT | `/v1/admin/agencies/{agency_id}/sources/{ingestion_source_id}` | Admin - Sources | `reconfigure_ingestion_source_endpoint` | `modules.ingestion.transport.http.sources_router` |
| GET | `/v1/admin/wordpress-sources` | Admin · Sources | `list_admin_wordpress_sources` | `modules.ingestion.transport.http.wordpress_sources_router` |
| GET | `/v1/admin/wordpress-sources/{site_id}` | Admin · Sources | `get_admin_wordpress_source` | `modules.ingestion.transport.http.wordpress_sources_router` |
| PUT | `/v1/admin/wordpress-sources/{site_id}` | Admin · Sources | `upsert_admin_wordpress_source` | `modules.ingestion.transport.http.wordpress_sources_router` |
| POST | `/v1/ingest/wordpress/property` | Webhooks | `ingest_wordpress_property_endpoint` | `modules.ingestion.transport.http.wordpress_webhook_router` |
| POST | `/v1/sessions/gohighlevel/context` | Session - GoHighLevel | `resolve_gohighlevel_session_context` | `modules.publishing.transport.http.sessions_router` |
| POST | `/v1/sessions/gohighlevel/session` | Session - GoHighLevel | `create_gohighlevel_session` | `modules.publishing.transport.http.sessions_router` |
| POST | `/v1/sessions/gohighlevel/test` | Session - GoHighLevel | `test_gohighlevel_session_connection` | `modules.publishing.transport.http.sessions_router` |
| GET | `/v1/sessions/gohighlevel/tokens` | Session - GoHighLevel | `list_gohighlevel_session_connections` | `modules.publishing.transport.http.sessions_router` |
| POST | `/v1/videos/scripted/render` | Video Rendering | `enqueue_scripted_render_endpoint` | `modules.rendering.transport.http.scripted_router` |
