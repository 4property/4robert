# Impl — Feature 12 `unescape_html_entities_everywhere`

- Status: **in_progress** (awaiting reviewer).
- Date: 2026-05-12.
- Agent: implementer (Opus 4.7 1M).
- Modules touched: `modules/reels/`, `modules/rendering/`, `modules/publishing/`.
- Schema?: No (`schema: "No"` in feature_list.json).

## Resumen

WordPress emite entidades HTML (`&#8217;`, `&amp;`, `&quot;`, `&#x2019;`) en
`title.rendered` y `content.rendered`. `Property.from_api_payload` no las
decodifica (verificado: `extract_rendered_text` solo llama a `to_text`, sin
`html.unescape`), así que hoy llegan crudas al subtítulo del MP4 y al `summary`
del POST `/social-media-posting/{locationId}/posts` de GHL.

La feature aplica `html.unescape()` en los **3 puntos finales** indicados por
el leader, sin tocar el dominio (`Property`) ni la capa de catálogo. Cada
aplicación es **idempotente** (re-decodificar texto ya limpio no rompe nada,
porque `html.unescape` no toca cadenas sin entidades).

## Archivos modificados

- `modules/reels/application/content_generator.py`
  - Añadido `import html`.
  - `render_template_with_property()` ahora envuelve el resultado final en
    `html.unescape(...)` después de la sustitución de variables. Esto cubre
    `{{property_title}}`, `{{neighborhood}}`, `{{short_description}}`, etc. y
    también limpia el texto literal del template si la agencia lo guardó con
    entidades crudas.
  - Docstring actualizado para documentar el contrato.
- `modules/rendering/infrastructure/ai_photo_selection/prompting.py`
  - `normalize_caption()` ahora decodifica con `html.unescape` **antes** del
    `strip("\"'")` y la detección de terminador. `html` ya estaba importado
    (líneas 11 + uso en `html_to_text`); solo se añadió la llamada.
  - Importante: la decodificación va **primero** para que `caption[-1] in ".!?"`
    funcione sobre el texto humano (un caption `Hello&#33;` ya termina en `!`
    y no recibe un punto extra). Ver
    `tests/unit/rendering/test_normalize_caption_unescape.py::test_normalize_caption_strips_html_entities_before_appending_terminator`.
- `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py`
  - Añadido `import html`.
  - `GoHighLevelSocialService.create_social_post()` decodifica `description` y
    `title` justo antes de construir `json_body`. La copia decodificada va al
    campo `summary` del cuerpo JSON y al builder del payload por plataforma
    (que es donde algunas plataformas, p. ej. YouTube, incrustan el title en
    el body). Comentario inline explica que es una defensa-en-profundidad
    además de los dos puntos previos.

## Archivos creados (tests)

- `tests/unit/reels/test_content_generator_unescape.py` — 7 tests:
  decimal numérica (`&#8217;`), hex numérica (`&#x2019;`), named (`&amp;`,
  `&quot;`), anidados (`&amp;amp;` → `&amp;` — pin de comportamiento
  one-level), idempotencia (texto ya limpio sobrevive sin cambios), template
  vacío (devuelve `""`), e integración end-to-end con
  `DeterministicPropertyContentGenerator.generate_property_content`
  verificando que el caption por plataforma sale limpio.
- `tests/unit/rendering/test_normalize_caption_unescape.py` — 7 tests: decimal,
  hex, named (con nota explícita sobre la interacción con `strip("\"'")`
  preexistente — los `&quot;` en los extremos se decodifican y luego se
  limpian, comportamiento legacy de `normalize_caption`), anidados,
  idempotencia, string vacío (devuelve fallback), y edge case del terminador
  (`Hello&#33;` no recibe punto extra).
- `tests/unit/publishing/test_social_service_unescape.py` — 7 tests: decimal,
  hex, named, anidados, idempotencia, description vacío, y un test específico
  para `title` (verifica que el title decodificado llega al body construido
  por la plataforma — usa `youtube` como caso porque su `build_gohighlevel_payload`
  incrusta el title en el body).

Total: **21 tests nuevos**, cubriendo los 6 casos mínimos (decimal, hex,
named, anidados, idempotencia, empty) por cada uno de los 3 puntos de
integración, más 3 tests específicos de borde por punto.

## Verificación

### Focal (verification[] de la feature)

```
$ FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend .venv/bin/python -m pytest tests/unit/rendering/ tests/unit/publishing/ -q
.........................................................................................................[100%]
97 passed in 0.88s
```

Baseline previo era 83 passed (sin los 14 tests de unescape en rendering+publishing). Ahora 97 = 83 + 14 nuevos en esos dos directorios. Los 7 tests adicionales viven en `tests/unit/reels/` y pasan también:

```
$ .venv/bin/python -m pytest tests/unit/reels/test_content_generator_unescape.py -q
.......                                                                  [100%]
7 passed in 0.47s
```

### Suite completa

```
$ FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
...
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
2 failed, 471 passed, 14 warnings in 200.96s (0:03:20)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
exit 0
```

Los **2 fallos restantes son preexistentes** (documentados por el leader en el
heads-up): `test_http_transport.py` espera que `/health` no incluya
`configured_worker_count`, y **están fuera del scope de esta feature**.
El tercer fallo histórico (`test_http_surface_contract.py` por
`FRONTEND_REPO_ROOT` apuntando a una ruta Windows) **desaparece** al exportar
`FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend`.

`gemini_photo_selection.py` (15 tests que usan `normalize_caption`) y el resto
de `tests/unit/reels/` (55 tests, incluyendo los que ejercitan
`content_generator` a través de `regenerate_reel` y `ingest_property_into_reel`)
**pasan sin cambios** — la decodificación es retro-compatible.

## Decisiones no obvias

- **Decodificar al final del template, no al inicio de los valores.** Probé
  decodificar `property_item.title` antes de construir el dict de variables;
  esto funcionaba pero perdía la oportunidad de limpiar también texto literal
  que la agencia haya pegado con entidades en su template guardado. Decodificar
  el resultado final cubre ambos vectores con una sola llamada. Es seguro
  porque el template no contiene placeholders sintácticos con `&` (el patrón
  es `{{variable}}`, no `&variable;`).
- **`html.unescape` decodifica un solo nivel.** El test
  `test_render_template_decodes_nested_entities_one_level` pinéa esto
  explícitamente (`&amp;amp;` → `&amp;`, NO `&`). Es el comportamiento
  documentado de la stdlib y es lo que queremos: el doble-encode de WP solo
  aparece cuando un plugin upstream ya escapó, y colapsarlo a `&` perdería
  información. Si en el futuro se descubre un caso donde WP envía
  triple-encoded, se añadirá un loop bounded; por ahora no es necesario.
- **Defensa-en-profundidad en `create_social_post`.** Los dos puntos previos
  (content_generator + normalize_caption) ya cubren el camino feliz del
  pipeline interno. La tercera decodificación en el adapter de GHL protege
  contra callers externos al pipeline (p. ej. tests manuales, integradores)
  que pasen description/title con entidades crudas — el contrato con GHL queda
  garantizado independientemente de la cadena de origen.
- **Interacción con `strip("\"'")` en `normalize_caption`.** El test de named
  entities cambió ligeramente respecto a la primera redacción: si el caption
  decodificado termina en `"` (porque venía de `...&quot;` al final), el
  `strip("\"'")` legacy lo elimina antes de añadir el `.`. Es comportamiento
  intencional de la función (limpia captions envueltos en comillas) y no es
  regresión de esta feature. El test ahora ejercita el caso con `&quot;` en
  el medio del string para evitar la interacción con `strip` y se documenta
  el caveat en el docstring del test.

## Próximo paso

Reviewer valida y, si aprueba, cambia `feature_list.json[id=12].status` →
`done` en una sesión posterior (paso 10 del protocolo, **no** lo hago yo).

## Mirror cross-repo

La feature equivalente en `/opt/projects/4Reels-Frontend/feature_list.json`
es id **11** (mismo `name`). Per instrucciones del leader, no se tocó el
front desde esta sesión — su implementación corre en paralelo y es
independiente.
