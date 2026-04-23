from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI

_POSTMAN_COLLECTION_FILENAME = "test-postman_collection.json"


@dataclass(frozen=True, slots=True)
class OpenApiDocsConfig:
    workspace_dir: Path
    webhook_path: str
    site_id_header: str
    gohighlevel_location_id_header: str
    gohighlevel_access_token_header: str
    timestamp_header: str
    signature_header: str


@dataclass(frozen=True, slots=True)
class _WebhookExample:
    body: dict[str, Any]
    location_id: str
    access_token: str
    site_id: str


def install_openapi_examples(app: FastAPI, *, config: OpenApiDocsConfig) -> None:
    original_openapi = app.openapi

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = original_openapi()
        _enrich_openapi_schema(
            schema,
            config=config,
            webhook_example=_load_postman_webhook_example(config),
        )
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi


def _enrich_openapi_schema(
    schema: dict[str, Any],
    *,
    config: OpenApiDocsConfig,
    webhook_example: _WebhookExample,
) -> None:
    info = schema.setdefault("info", {})
    info.setdefault(
        "description",
        (
            "API para recibir webhooks de propiedades desde WordPress y disparar renders "
            "de video guiados por manifiesto."
        ),
    )

    _merge_tags(
        schema,
        (
            {
                "name": "Health",
                "description": "Sondas mínimas para comprobar si el proceso está vivo y listo.",
            },
            {
                "name": "Webhooks",
                "description": "Recepción de eventos de propiedades provenientes de WordPress/GoHighLevel.",
            },
            {
                "name": "Video Rendering",
                "description": "Render síncrono de videos guionizados a partir de manifiestos JSON.",
            },
            {
                "name": "Admin",
                "description": "Operaciones administrativas protegidas para gestionar el aprovisionamiento de sitios WordPress.",
            },
        ),
    )
    _decorate_health_operations(schema)
    _decorate_webhook_operation(schema, config=config, webhook_example=webhook_example)
    _decorate_scripted_render_operation(schema)


def _merge_tags(schema: dict[str, Any], tags: Iterable[dict[str, str]]) -> None:
    existing_tags = schema.setdefault("tags", [])
    seen = {
        str(tag.get("name"))
        for tag in existing_tags
        if isinstance(tag, Mapping) and tag.get("name")
    }
    for tag in tags:
        tag_name = tag.get("name")
        if not tag_name or tag_name in seen:
            continue
        existing_tags.append(tag)
        seen.add(tag_name)


def _decorate_health_operations(schema: dict[str, Any]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return

    live_operation = paths.get("/health/live", {}).get("get")
    if isinstance(live_operation, dict):
        live_operation["tags"] = ["Health"]
        live_operation["summary"] = "Liveness probe"
        live_operation["description"] = "Devuelve `ok` cuando el proceso HTTP está atendiendo peticiones."
        live_operation["responses"] = {
            "200": {
                "description": "El proceso está vivo.",
                "content": {
                    "application/json": {
                        "schema": _health_status_schema(),
                        "example": {"status": "ok"},
                    }
                },
            }
        }

    ready_operation = paths.get("/health/ready", {}).get("get")
    if isinstance(ready_operation, dict):
        ready_operation["tags"] = ["Health"]
        ready_operation["summary"] = "Readiness probe"
        ready_operation["description"] = (
            "Informa si la aplicación completó sus comprobaciones de arranque y si el "
            "dispatcher acepta nuevos trabajos."
        )
        ready_operation["responses"] = {
            "200": {
                "description": "La aplicación está lista para aceptar tráfico.",
                "content": {
                    "application/json": {
                        "schema": _health_status_schema(),
                        "example": {"status": "ready"},
                    }
                },
            },
            "503": {
                "description": "La aplicación aún no está lista.",
                "content": {
                    "application/json": {
                        "schema": _health_status_schema(),
                        "example": {"status": "not_ready"},
                    }
                },
            },
        }


def _decorate_webhook_operation(
    schema: dict[str, Any],
    *,
    config: OpenApiDocsConfig,
    webhook_example: _WebhookExample,
) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return
    operation = paths.get(config.webhook_path, {}).get("post")
    if not isinstance(operation, dict):
        return

    operation["tags"] = ["Webhooks"]
    operation["summary"] = "Receive WordPress property webhook"
    operation["description"] = (
        "Recibe el payload bruto de una propiedad de WordPress, valida las cabeceras "
        "de GoHighLevel y, cuando la seguridad está activa, comprueba timestamp y firma. "
        "Si todo es válido, la API encola el trabajo para procesarlo en segundo plano."
    )
    operation["parameters"] = [
        {
            "name": config.site_id_header,
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": (
                "Opcional. Si falta, la API intentará derivar el `site_id` desde "
                "`site_id`, `link` o `guid.rendered` del cuerpo."
            ),
            "example": webhook_example.site_id,
        },
        {
            "name": config.gohighlevel_location_id_header,
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "Cabecera requerida de GoHighLevel. También se acepta `X-GHL-Location-Id`.",
            "example": webhook_example.location_id,
        },
        {
            "name": config.gohighlevel_access_token_header,
            "in": "header",
            "required": True,
            "schema": {"type": "string"},
            "description": "Cabecera requerida de GoHighLevel. También se acepta `X-GHL-Token`.",
            "example": webhook_example.access_token,
        },
        {
            "name": config.timestamp_header,
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": "Requerida cuando la seguridad del webhook está activa. Debe contener un Unix timestamp.",
            "example": "1771601600",
        },
        {
            "name": config.signature_header,
            "in": "header",
            "required": False,
            "schema": {"type": "string"},
            "description": (
                "Requerida cuando la seguridad del webhook está activa. Debe coincidir con la firma "
                "HMAC calculada sobre el cuerpo JSON bruto y las cabeceras recibidas."
            ),
            "example": "sha256=2a43fbcf4cb7f8c58fbb827f7dca2a4a5b56b6c22abdd887298f715fb8d1d426",
        },
    ]
    operation["requestBody"] = {
        "required": True,
        "content": {
            "application/json": {
                "schema": _webhook_request_schema(),
                "examples": {
                    "postman_collection": {
                        "summary": "Ejemplo real desde Postman",
                        "description": (
                            "Payload extraído automáticamente de `test-postman_collection.json`."
                        ),
                        "value": webhook_example.body,
                    },
                    "single_item_array": {
                        "summary": "Formato alternativo de un solo elemento",
                        "description": (
                            "La API también acepta un array con exactamente un objeto JSON."
                        ),
                        "value": [_fallback_webhook_body()],
                    },
                },
            }
        },
    }
    operation["responses"] = {
        "202": {
            "description": "Webhook aceptado y encolado para procesamiento asíncrono.",
            "content": {
                "application/json": {
                    "schema": _webhook_accepted_schema(),
                    "example": {
                        "status": "accepted",
                        "event_id": "5f4c2af3-4060-4b4d-b9a3-ccbf70dbf3f3",
                        "job_id": "1c4d13eb-7662-4298-92ef-e4842d74904f",
                        "site_id": webhook_example.site_id,
                        "property_id": webhook_example.body.get("id"),
                    },
                }
            },
        },
        "400": {
            "description": "Petición rechazada por cabeceras o JSON inválido.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "examples": {
                        "missing_ghl_headers": {
                            "summary": "Faltan cabeceras de GoHighLevel",
                            "value": {
                                "error": "Missing required GoHighLevel webhook headers.",
                                "code": "MISSING_GHL_HEADERS",
                                "hint": "Send the GoHighLevel location and access token headers on every webhook request.",
                                "details": {
                                    "missing_headers": [
                                        config.gohighlevel_location_id_header,
                                        config.gohighlevel_access_token_header,
                                    ]
                                },
                            },
                        },
                        "invalid_payload": {
                            "summary": "JSON inválido",
                            "value": {
                                "error": "Request body must be valid JSON. Expecting value at line 1, column 1.",
                            },
                        },
                    },
                }
            },
        },
        "401": {
            "description": "La firma o el timestamp no son válidos.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "example": {
                        "error": "Invalid webhook credentials.",
                        "code": "INVALID_WEBHOOK_CREDENTIALS",
                        "hint": "Check the webhook signing secret, timestamp, and required security headers.",
                        "details": {"site_id": webhook_example.site_id},
                    },
                }
            },
        },
        "413": {
            "description": "El cuerpo excede el tamaño máximo permitido.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "example": {
                        "error": "Request body is too large.",
                        "code": "PAYLOAD_TOO_LARGE",
                        "hint": "Reduce the payload size or increase WEBHOOK_MAX_PAYLOAD_BYTES on the API host.",
                        "details": {"max_payload_bytes": 5242880},
                    },
                }
            },
        },
        "404": {
            "description": "El site_id del webhook no estÃ¡ provisionado o activo.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "example": {
                        "error": "The webhook site is not provisioned.",
                        "code": "UNKNOWN_WORDPRESS_SITE",
                        "hint": "Provision an active wordpress_sources row for this site_id before sending webhooks.",
                    },
                }
            },
        },
        "500": {
            "description": "Se produjo un error al aceptar o encolar el webhook.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "example": {
                        "error": "Failed to accept webhook delivery.",
                        "code": "WEBHOOK_ACCEPTANCE_FAILED",
                        "hint": (
                            "Check the dated log folders under logs/MM-YYYY/DD-MM-YYYY for errors.log, "
                            "warnings-errors.log, and audit.jsonl with the request_id and underlying "
                            "acceptance failure."
                        ),
                    },
                }
            },
        },
    }


def _decorate_scripted_render_operation(schema: dict[str, Any]) -> None:
    paths = schema.get("paths")
    if not isinstance(paths, dict):
        return
    operation = paths.get("/videos/scripted/render", {}).get("post")
    if not isinstance(operation, dict):
        return

    render_request_example = _scripted_render_request_example()
    operation["tags"] = ["Video Rendering"]
    operation["summary"] = "Render scripted property video"
    operation["description"] = (
        "Genera un video desde un manifiesto JSON. Todos los `image_path`, `sources[].path` y "
        "`background_audio_path` deben apuntar a ficheros locales existentes dentro del workspace."
    )
    operation["requestBody"] = {
        "required": True,
        "content": {
            "application/json": {
                "schema": _scripted_render_request_schema(),
                "examples": {
                    "image_path": {
                        "summary": "Slides con `image_path`",
                        "value": render_request_example,
                    },
                    "sources": {
                        "summary": "Slides con `sources`",
                        "value": {
                            **render_request_example,
                            "slides": [
                                {
                                    "sources": [{"path": "uploads/slide-01.jpg"}],
                                    "caption": "Bright living room.",
                                },
                                {
                                    "sources": [{"path": "uploads/slide-02.jpg"}],
                                    "caption": "Sunny rear garden.",
                                },
                            ],
                        },
                    },
                },
            }
        },
    }
    operation["responses"] = {
        "201": {
            "description": "Video renderizado y artefactos persistidos.",
            "content": {
                "application/json": {
                    "schema": _scripted_render_response_schema(),
                    "example": {
                        "status": "rendered",
                        "render_id": "dd6f2ee9c9cf4f48ab6b48d18d17ce7d",
                        "site_id": "site-a",
                        "source_property_id": 170800,
                        "video_path": "generated_media/site-a/scripted_videos/sample-property/dd6f2ee9c9cf4f48ab6b48d18d17ce7d/video.mp4",
                        "manifest_path": "generated_media/site-a/scripted_videos/sample-property/dd6f2ee9c9cf4f48ab6b48d18d17ce7d/resolved-manifest.json",
                        "request_manifest_path": "generated_media/site-a/scripted_videos/sample-property/dd6f2ee9c9cf4f48ab6b48d18d17ce7d/request-manifest.json",
                    },
                }
            },
        },
        "400": {
            "description": "El manifiesto es inválido o referencia ficheros no permitidos.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "examples": {
                        "slides_required": {
                            "summary": "Faltan slides",
                            "value": {
                                "error": "The scripted render payload must include a non-empty slides array.",
                                "code": "SLIDES_REQUIRED",
                                "hint": "Send at least one slide with image_path or a single-entry sources array.",
                                "details": {"context": {"field": "slides"}},
                            },
                        },
                        "invalid_slide_path": {
                            "summary": "Ruta fuera del workspace",
                            "value": {
                                "error": "slides[0].image_path must stay within the workspace.",
                                "code": "INVALID_SLIDE_IMAGE_PATH",
                                "hint": "Use a readable local image path inside the workspace.",
                                "details": {
                                    "context": {
                                        "field": "slides[0].image_path",
                                        "value": "../outside-slide.jpg",
                                    }
                                },
                            },
                        },
                    },
                }
            },
        },
        "404": {
            "description": "La propiedad de referencia no existe todavía.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "example": {
                        "error": "The referenced property does not exist.",
                        "code": "PROPERTY_NOT_FOUND",
                        "hint": "Create or ingest the property first, then retry the scripted render.",
                        "details": {
                            "context": {
                                "site_id": "site-a",
                                "source_property_id": 170800,
                            }
                        },
                    },
                }
            },
        },
        "500": {
            "description": "Fallo interno durante el render.",
            "content": {
                "application/json": {
                    "schema": _error_response_schema(),
                    "example": {
                        "error": "Failed to render the scripted video.",
                        "code": "SCRIPTED_RENDER_ERROR",
                        "hint": "Check the render inputs and the staged output directory, then retry the request.",
                    },
                }
            },
        },
    }


def _load_postman_webhook_example(config: OpenApiDocsConfig) -> _WebhookExample:
    fallback = _WebhookExample(
        body=_fallback_webhook_body(),
        location_id="location-a",
        access_token="token-a",
        site_id="site-a",
    )
    for collection_path in _postman_collection_candidates(config):
        if not collection_path.exists():
            continue
        try:
            collection = json.loads(collection_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        request = _find_postman_request(collection.get("item"), config.webhook_path)
        if request is None:
            continue

        body = _extract_postman_request_body(request)
        if body is None:
            body = fallback.body

        headers = _extract_postman_headers(request)
        location_id = str(
            headers.get(config.gohighlevel_location_id_header)
            or headers.get("X-GHL-Location-Id")
            or fallback.location_id
        )
        access_token = str(
            headers.get(config.gohighlevel_access_token_header)
            or headers.get("X-GHL-Token")
            or fallback.access_token
        )
        site_id = _derive_site_id(body) or fallback.site_id
        return _WebhookExample(
            body=body,
            location_id=location_id,
            access_token=access_token,
            site_id=site_id,
        )
    return fallback


def _postman_collection_candidates(config: OpenApiDocsConfig) -> tuple[Path, ...]:
    repository_root = Path(__file__).resolve().parents[2]
    candidates = (
        config.workspace_dir / _POSTMAN_COLLECTION_FILENAME,
        repository_root / _POSTMAN_COLLECTION_FILENAME,
    )
    unique_candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved_candidate = candidate.resolve()
        if resolved_candidate in seen:
            continue
        seen.add(resolved_candidate)
        unique_candidates.append(resolved_candidate)
    return tuple(unique_candidates)


def _find_postman_request(raw_items: object, webhook_path: str) -> Mapping[str, Any] | None:
    if not isinstance(raw_items, Sequence) or isinstance(raw_items, (str, bytes, bytearray)):
        return None
    normalized_path = webhook_path.rstrip("/")
    for raw_item in raw_items:
        if not isinstance(raw_item, Mapping):
            continue
        request = raw_item.get("request")
        if isinstance(request, Mapping) and _postman_request_matches_path(request, normalized_path):
            return request
        nested_items = raw_item.get("item")
        nested_request = _find_postman_request(nested_items, normalized_path)
        if nested_request is not None:
            return nested_request
    return None


def _postman_request_matches_path(request: Mapping[str, Any], webhook_path: str) -> bool:
    method = str(request.get("method") or "").upper()
    if method != "POST":
        return False
    url = request.get("url")
    if isinstance(url, Mapping):
        raw = url.get("raw")
        if isinstance(raw, str) and raw:
            parsed = urlparse(raw)
            if parsed.path.rstrip("/") == webhook_path:
                return True
        path_parts = url.get("path")
        if isinstance(path_parts, Sequence) and not isinstance(path_parts, (str, bytes, bytearray)):
            joined_path = "/" + "/".join(str(part).strip("/") for part in path_parts if str(part).strip("/"))
            if joined_path.rstrip("/") == webhook_path:
                return True
    return False


def _extract_postman_request_body(request: Mapping[str, Any]) -> dict[str, Any] | None:
    body = request.get("body")
    if not isinstance(body, Mapping):
        return None
    raw = body.get("raw")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
        return parsed[0]
    if isinstance(parsed, dict):
        return parsed
    return None


def _extract_postman_headers(request: Mapping[str, Any]) -> dict[str, str]:
    raw_headers = request.get("header")
    if not isinstance(raw_headers, Sequence) or isinstance(raw_headers, (str, bytes, bytearray)):
        return {}
    headers: dict[str, str] = {}
    for raw_header in raw_headers:
        if not isinstance(raw_header, Mapping):
            continue
        key = raw_header.get("key")
        value = raw_header.get("value")
        if not isinstance(key, str) or not key.strip():
            continue
        headers[key.strip()] = str(value or "").strip()
    return headers


def _derive_site_id(payload: Mapping[str, Any]) -> str | None:
    direct_site_id = payload.get("site_id")
    if isinstance(direct_site_id, str) and direct_site_id.strip():
        return direct_site_id.strip().lower()
    link_candidates: list[str] = []
    link = payload.get("link")
    if isinstance(link, str) and link.strip():
        link_candidates.append(link)
    guid = payload.get("guid")
    if isinstance(guid, Mapping):
        rendered = guid.get("rendered")
        if isinstance(rendered, str) and rendered.strip():
            link_candidates.append(rendered)
    for candidate in link_candidates:
        parsed = urlparse(candidate)
        if parsed.netloc:
            return parsed.netloc.strip().lower()
    return None


def _health_status_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
        "additionalProperties": False,
    }


def _error_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "error": {"type": "string"},
            "code": {"type": "string"},
            "hint": {"type": "string"},
            "details": {"type": "object", "additionalProperties": True},
        },
        "required": ["error"],
        "additionalProperties": False,
    }


def _webhook_accepted_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["accepted"]},
            "event_id": {"type": "string", "format": "uuid"},
            "job_id": {"type": "string", "format": "uuid"},
            "site_id": {"type": "string"},
            "property_id": {"type": ["integer", "null"]},
        },
        "required": ["status", "event_id", "job_id", "site_id", "property_id"],
        "additionalProperties": False,
    }


def _webhook_request_schema() -> dict[str, Any]:
    return {
        "oneOf": [
            _webhook_payload_object_schema(),
            {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": _webhook_payload_object_schema(),
                "description": "Formato alternativo aceptado: un array con un único objeto.",
            },
        ]
    }


def _webhook_payload_object_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Payload de propiedad enviado por WordPress. El servicio conserva campos adicionales "
            "aunque no se documenten explícitamente aquí."
        ),
        "properties": {
            "id": {
                "oneOf": [{"type": "integer"}, {"type": "string"}],
                "description": "Identificador de la propiedad en WordPress.",
            },
            "site_id": {
                "type": "string",
                "description": "Opcional. Si falta, puede derivarse de `link` o `guid.rendered`.",
            },
            "slug": {"type": "string"},
            "status": {"type": "string"},
            "type": {"type": "string"},
            "link": {"type": "string", "format": "uri"},
            "modified_gmt": {"type": "string", "format": "date-time"},
            "property_status": {"type": "string"},
            "price": {"type": "string"},
            "bedrooms": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            "bathrooms": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            "ber_rating": {"type": "string"},
            "title": {
                "type": "object",
                "properties": {"rendered": {"type": "string"}},
                "additionalProperties": True,
            },
            "guid": {
                "type": "object",
                "properties": {"rendered": {"type": "string", "format": "uri"}},
                "additionalProperties": True,
            },
            "agency_logo": {"type": "string", "format": "uri"},
            "agent_name": {"type": "string"},
            "agent_email": {"type": "string"},
            "agent_number": {"type": "string"},
            "wppd_primary_image": {"type": "string", "format": "uri"},
            "wppd_pics": {
                "type": "array",
                "items": {"type": "string", "format": "uri"},
            },
            "property_features": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "additionalProperties": True,
    }


def _scripted_render_request_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["site_id", "source_property_id", "title", "property_status", "slides"],
        "properties": {
            "site_id": {"type": "string"},
            "source_property_id": {"type": "integer"},
            "title": {"type": "string"},
            "property_status": {"type": "string"},
            "render_profile": {
                "type": "string",
                "description": "Opcional. Si no se envía, se resuelve desde la planificación de medios.",
            },
            "listing_lifecycle": {"type": "string"},
            "banner_text": {"type": "string"},
            "price_display_text": {"type": "string"},
            "price": {"type": "string"},
            "price_term": {"type": "string"},
            "link": {"type": "string", "format": "uri"},
            "featured_image_url": {"type": "string", "format": "uri"},
            "bedrooms": {"type": "integer"},
            "bathrooms": {"type": "integer"},
            "ber_rating": {"type": "string"},
            "agent_name": {"type": "string"},
            "agent_photo_url": {"type": "string", "format": "uri"},
            "agent_email": {"type": "string"},
            "agent_mobile": {"type": "string"},
            "agent_number": {"type": "string"},
            "property_type_label": {"type": "string"},
            "property_area_label": {"type": "string"},
            "property_county_label": {"type": "string"},
            "eircode": {"type": "string"},
            "property_size": {"type": "string"},
            "agency_psra": {"type": "string"},
            "agency_logo_url": {"type": "string", "format": "uri"},
            "background_audio_path": {
                "type": "string",
                "description": "Ruta local opcional dentro del workspace.",
            },
            "render_settings": _scripted_render_settings_schema(),
            "slides": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "oneOf": [
                        _scripted_render_slide_image_path_schema(),
                        _scripted_render_slide_sources_schema(),
                    ]
                },
            },
        },
        "additionalProperties": True,
    }


def _scripted_render_settings_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "Overrides opcionales de la plantilla de render. El manifiesto resuelto persiste la "
            "configuración efectiva final después de aplicar el `render_profile`."
        ),
        "properties": {
            "width": {"type": "integer", "minimum": 2},
            "height": {"type": "integer", "minimum": 2},
            "fps": {"type": "integer", "minimum": 1},
            "total_duration_seconds": {"type": "number", "exclusiveMinimum": 0},
            "seconds_per_slide": {"type": "number", "exclusiveMinimum": 0},
            "max_slide_count": {"type": "integer", "minimum": 1},
            "intro_duration_seconds": {"type": "number", "minimum": 0},
            "assets_dirname": {"type": "string"},
            "ber_icons_dirname": {"type": "string"},
            "cover_logo_filename": {"type": "string"},
            "background_audio_filename": {"type": "string"},
            "audio_volume": {"type": "number", "minimum": 0},
            "ffmpeg_filter_threads": {"type": "integer", "minimum": 0},
            "ffmpeg_encoder_threads": {"type": "integer", "minimum": 0},
            "font_path": {
                "type": "string",
                "description": "Ruta de fuente base para drawtext.",
            },
            "bold_font_path": {
                "type": "string",
                "description": "Ruta de fuente bold para drawtext.",
            },
            "subtitle_font_path": {
                "type": "string",
                "description": "Ruta de fuente usada en subtítulos.",
            },
            "subtitle_font_size": {"type": "integer", "minimum": 1},
            "ber_icon_scale": {"type": "number", "exclusiveMinimum": 0},
            "agency_logo_scale": {"type": "number", "exclusiveMinimum": 0},
            "include_intro": {"type": "boolean"},
            "footer_bottom_offset_px": {
                "type": "integer",
                "minimum": 0,
                "description": "Desplaza el footer hacia arriba respecto al borde inferior.",
            },
        },
        "additionalProperties": False,
    }


def _scripted_render_slide_image_path_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["image_path"],
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Ruta local de la imagen. Puede ser relativa al workspace o absoluta dentro de él.",
            },
            "caption": {"type": "string"},
        },
        "additionalProperties": False,
    }


def _scripted_render_slide_sources_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["sources"],
        "properties": {
            "sources": {
                "type": "array",
                "minItems": 1,
                "maxItems": 1,
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "required": ["path"],
                            "properties": {"path": {"type": "string"}},
                            "additionalProperties": False,
                        },
                    ]
                },
                "description": "En v1 solo se admite una única fuente por slide.",
            },
            "caption": {"type": "string"},
        },
        "additionalProperties": False,
    }


def _scripted_render_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["rendered"]},
            "render_id": {"type": "string"},
            "site_id": {"type": "string"},
            "source_property_id": {"type": "integer"},
            "video_path": {"type": "string"},
            "manifest_path": {"type": "string"},
            "request_manifest_path": {"type": "string"},
        },
        "required": [
            "status",
            "render_id",
            "site_id",
            "source_property_id",
            "video_path",
            "manifest_path",
            "request_manifest_path",
        ],
        "additionalProperties": False,
    }


def _fallback_webhook_body() -> dict[str, Any]:
    return {
        "id": 170800,
        "slug": "sample-property",
        "title": {"rendered": "46 Example Street, Dublin 4"},
        "modified_gmt": "2026-03-24T10:43:19",
        "property_status": "For Sale",
        "price": "650000",
        "bedrooms": 3,
        "bathrooms": 2,
        "ber_rating": "B2",
        "link": "https://ckp.ie/property/sample-property",
        "agent_name": "Jane Doe",
        "agent_email": "jane@example.com",
        "agent_number": "+353 1 234 5678",
        "agency_logo": "https://example.com/agency-logo.png",
        "wppd_primary_image": "https://example.com/property-primary.jpg",
        "wppd_pics": [
            "https://example.com/property-primary.jpg",
            "https://example.com/property-secondary.jpg",
        ],
        "property_features": ["Private patio", "Open-plan kitchen"],
    }


def _scripted_render_request_example() -> dict[str, Any]:
    return {
        "site_id": "site-a",
        "source_property_id": 170800,
        "title": "46 Example Street, Dublin 4",
        "property_status": "For Sale",
        "render_profile": "for_sale_reel",
        "render_settings": _scripted_render_settings_example(),
        "price": "650000",
        "bedrooms": 3,
        "bathrooms": 2,
        "ber_rating": "B2",
        "agent_name": "Jane Doe",
        "agent_number": "+353 1 234 5678",
        "agency_logo_url": "https://example.com/agency-logo.png",
        "slides": [
            {
                "image_path": "uploads/slide-01.jpg",
                "caption": "Bright living room.",
            },
            {
                "image_path": "uploads/slide-02.jpg",
                "caption": "Sunny rear garden.",
            },
        ],
    }


def _scripted_render_settings_example() -> dict[str, Any]:
    return {
        "width": 1080,
        "height": 1440,
        "fps": 24,
        "total_duration_seconds": 35,
        "seconds_per_slide": 5,
        "max_slide_count": 7,
        "intro_duration_seconds": 3,
        "assets_dirname": "assets",
        "ber_icons_dirname": "ber-icons",
        "cover_logo_filename": "ckp-logo.png",
        "background_audio_filename": "music/ncs-music.mp3",
        "audio_volume": 0.45,
        "ffmpeg_filter_threads": 1,
        "ffmpeg_encoder_threads": 2,
        "font_path": "assets/fonts/Inter/static/Inter_28pt-Regular.ttf",
        "bold_font_path": "assets/fonts/Inter/static/Inter_28pt-Bold.ttf",
        "subtitle_font_path": "assets/fonts/Inter/static/Inter_28pt-Bold.ttf",
        "subtitle_font_size": 54,
        "ber_icon_scale": 0.5,
        "agency_logo_scale": 1.5,
        "include_intro": False,
        "footer_bottom_offset_px": 72,
    }


__all__ = [
    "OpenApiDocsConfig",
    "install_openapi_examples",
]
