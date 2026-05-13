# Handover — Side Banner refinements (2026-05-13)

> Para el siguiente agente. Contexto, estado actual, decisiones tomadas y
> siguientes pasos. Lee TODO este doc antes de tocar nada.

## 1. Lo que arrancó la sesión

El usuario reportó dos cosas en este orden:

1. **"La feature de elegir entre los dos templates no funciona"** — la página
   `/templates` listaba y persistía la selección, pero al regenerar reels
   salían siempre `classic`.
2. **"El template side_banner es muy distinto al que pedí; debe parecerse a
   `example-new-template.png`"**. La imagen está en
   `/opt/projects/4Reels-Backend/example-new-template.png`.

## 2. Lo que se hizo

### 2.1 Diagnóstico del "no funciona" (resuelto)

**Causa raíz:** API y worker llevaban horas corriendo con código del último
commit (`2f106e7` "production test" 2026-05-11). La feature 16 (DB-backed
render templates + side_banner) estaba en disco como **cambios sin commit**
(169 ficheros `M` + nuevos `??` incluyendo migraciones `0002-0005`). El
`feature_list.json` marcaba feature 16 como `done` pero nadie commiteó.

**Acción:** reinicios ordenados de api y worker con el código de disco. Tras
el primer reinicio:
- `GET /v1/admin/agencies/.../render-templates` devolvió ambos templates con
  `current_template_id=side_banner` para `f86148f7-7862-455a-8161-337b62cb1134`.
- Webhooks WordPress posteriores encolaron jobs con
  `publish_context_json.render_template_id="side_banner"` correctamente.
- El usuario confirmó: **"ya funciona el elegir entre templates"**.

**Bug latente NO arreglado** (queda para futura iteración):
`SocialPublishContext.from_dict` (en `modules/reels/domain/types.py:113-122`)
defaultea `render_template_id` a `"classic"` cuando la key falta del payload.
Eso impide que `IngestPropertyIntoReelUseCase._resolve_render_template_settings`
caiga al fallback de `agency_reel_defaults.render_template_id`, porque la
condición `if not requested_template_id` nunca dispara. Solo importa para
jobs encolados con código previo a feature 16. **No urgente, pero merece
fix futuro:** cambiar `from_dict` para que devuelva `""` cuando la key
falta y dejar que el caller decida el fallback.

### 2.2 Refinamiento visual del side_banner (parcial — solo gaps #1 y #3)

Spec del leader → `progress/spec_16b_side_banner_header_and_ber.md`.
Informe del implementer → `progress/impl_16b_side_banner_header_and_ber.md`.

**Gaps identificados al comparar `example-new-template.png` con
`generated_media/dev76.designbricks.ie/posters/1-friar-street-cork-city-centre-co-cork-poster.jpg`:**

| # | Gap | Decisión usuario | Estado |
|---|---|---|---|
| 1 | Cabecera del top panel: "FOR SALE" → "OFFERS OVER:" | Literal hardcodeado en código | ✅ Hecho |
| 2 | Specs row: solo "57m²" en lugar de "108m² \| 3beds \| 2baths" | El código ya hace bien el formato (`build_property_header_details_line`); la propiedad de Friar Street es comercial sin beds/baths. No requiere cambio | ✅ Confirmado |
| 3 | BER badge centrado vertical en panel → inline con specs row | Hacer | ✅ Hecho |
| 4 | Banner vertical es rectángulo → debería tener notches triangulares (cinta clásica) | Pospuesto (segunda iteración) | ⏸ Pendiente |
| 5 | Foto agente cuadrada → circular | Pospuesto (segunda iteración) | ⏸ Pendiente |
| 6 | Logo agencia sin contenedor → tarjeta blanca redondeada detrás | Pospuesto (segunda iteración) | ⏸ Pendiente |

**Cambios aplicados** (sin commit):
- `modules/rendering/infrastructure/layout/panels.py` — `compose_top_panel`
  gana kwarg `layout_variant="classic"`; texto del bloque `status` se resuelve
  literal `"OFFERS OVER:"` cuando `side_banner`, dinámico cuando `classic`;
  `ber_badge_box.y` alineado con el bloque `address_meta` (la specs row) en
  `side_banner`, centrado contra panel en `classic`.
- `modules/rendering/infrastructure/layout/composition.py` — reenvía el
  `layout_variant` ya disponible en su firma hacia `compose_top_panel`.
- `tests/unit/rendering/test_layout_composition_side_banner.py` — extendido
  con 4 tests nuevos (header literal SB, header dinámico classic, BER inline
  SB, BER centrado classic).

**Verificación** (toda en verde tras el cambio):
- `pytest tests/unit/rendering/ tests/unit/reels/ -q` → 170 passed.
- `tests/unit/rendering/test_overlay_filter_classic_snapshot.py` → 2 passed.
  Filter graph de `classic` byte-for-byte idéntico.
- `python -m apps.api --check` y `python -m apps.worker --check` exit 0.
- Smoke in-process con el fixture canónico de los tests:
  - `side_banner`: `status` block text == `"OFFERS OVER:"`,
    `ber_badge.y == address_meta.y == 311`.
  - `classic`: `status` block text == `"FOR SALE"`, `ber_badge` centrado
    contra panel (y=212), como antes.

## 3. Estado del runtime (al cierre)

```
api    PID 1605529  arrancó ~15:42 UTC con código post-implementer
worker PID 1605530  arrancó ~15:42 UTC con código post-implementer
```

Endpoints clave verificados:
- `GET  /health` → `{"status":"ready","dispatcher_accepting_jobs":true,...}`
- `GET  /v1/admin/agencies/f86148f7-7862-455a-8161-337b62cb1134/render-templates`
  → `current_template_id="side_banner"`, ambos templates `selected` flagged
  correctamente.

`agency_reel_defaults` para `f86148…`: `render_template_id='side_banner'`
desde `2026-05-13 13:20:33`.

**No hay jobs queued/processing al cierre.** Los últimos reels `side_banner`
en BBDD son del **período entre el primer reinicio y el refinamiento del
implementer** (14:37–14:40), por tanto siguen llevando el layout PRE-refinamiento
(cabecera "FOR SALE", BER centrado). Cualquier regenerate disparado AHORA
producirá el layout NUEVO ("OFFERS OVER:", BER inline).

## 4. Lo que queda pendiente

### 4.1 Verificación visual del refinamiento

El smoke confirmó la estructura de layout en proceso, pero el usuario no ha
disparado todavía un regenerate real para ver el PNG/MP4 nuevo. El siguiente
agente debería:

1. Pedir al usuario que regenere una propiedad residencial (con beds/baths y
   BER) de la agencia `f86148…`, o
2. Si tiene permiso explícito del usuario, disparar:
   `POST /v1/admin/agencies/f86148f7-7862-455a-8161-337b62cb1134/reels/dev76.designbricks.ie/<property_id>/approve`
   — **OJO**: ese endpoint re-publica en GHL (efecto secundario externo). No
   ejecutar sin confirmación expresa.
3. Comparar el poster resultante con
   `/opt/projects/4Reels-Backend/example-new-template.png`.

### 4.2 Gaps #4, #5, #6 — segunda iteración

Si el usuario aprueba visualmente el refinamiento actual, los gaps
pospuestos son:

- **#4 Notches del banner vertical**: modificar
  `_render_vertical_status_banner` en
  `modules/rendering/infrastructure/preparation.py:254-347` para añadir dos
  triángulos de "muesca" en los extremos del PNG (vía filtro ffmpeg `geq` o
  máscara alfa). Solo cuando `layout_variant=="side_banner"`.
- **#5 Foto agente circular**: añadir paso en `_normalize_agent_image`
  (`preparation.py:512+`) y/o `prepare_agent_image`
  (`modules/rendering/infrastructure/runtime/branding.py:119`) para aplicar
  una máscara circular al PNG del agente. Solo en `side_banner`.
- **#6 Tarjeta blanca redondeada para el logo**: dibujar un `drawbox` blanco
  con esquinas redondeadas detrás del `agency_logo_box` cuando
  `layout_variant=="side_banner"`. `drawbox` de ffmpeg no redondea, así que
  posiblemente PNG pre-renderizado o `geq`. Localización: el dibujo del
  panel inferior está en `modules/rendering/infrastructure/ffmpeg/filters.py`
  y `modules/rendering/infrastructure/poster.py`.

### 4.3 Otros pendientes "no urgentes"

- **Commit del WIP**: hay 169+ ficheros sin commit, incluyendo toda la feature
  16. `progress/current.md` se actualizó por el implementer; al final habrá
  que limpiar y commitear. **NO** he commiteado nada en esta sesión.
- **Posible refinamiento del centrado BER**: cuando `address_meta.box_height
  < ber_icon_height` la fórmula `max(0, ...)` clamps a 0, dejando el badge
  alineado por arriba con el texto en lugar de centrado contra la fila. Es
  un misalignment de ~10–15 px. Si el usuario pide perfeccionismo, quitar
  el `max(0, ...)` en `panels.py` (gap #3 lo introduce). No urgente.
- **Bug latente de `SocialPublishContext.from_dict`** (ver §2.1).
- **`feature_list.json`**: feature 16 está marcada `done` desde antes de
  esta sesión. No tocar.

## 5. Decisiones del usuario tomadas

1. **Reiniciar worker + api** para cargar el código de hoy (autorizado, hecho).
2. **"OFFERS OVER:"** es texto HARDCODEADO en plantilla, no un campo del
   feed. Sin nueva migración ni nuevo campo en WordPress payload.
3. **Iteración 1 solo gaps #1 + #3.** Los demás (#4, #5, #6) en una posible
   iteración 2.

## 6. Comandos útiles

```bash
# Working dir
cd /opt/projects/4Reels-Backend

# Activar venv (Python 3.12)
source .venv/bin/activate

# Health
curl -s http://127.0.0.1:8001/health | python -m json.tool

# Lista de templates de la agencia de prueba
curl -s http://127.0.0.1:8001/v1/admin/agencies/f86148f7-7862-455a-8161-337b62cb1134/render-templates | python -m json.tool

# Tests
.venv/bin/python -m pytest tests/unit/rendering/ tests/unit/reels/ -q
.venv/bin/python -m pytest tests/unit/rendering/test_overlay_filter_classic_snapshot.py -q

# Estado de jobs en cola para la agencia
.venv/bin/python -c "
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
load_dotenv()
e = create_engine(os.environ['DATABASE_URL'])
ag = 'f86148f7-7862-455a-8161-337b62cb1134'
with e.connect() as c:
    print(c.execute(text(\"SELECT job_id,status,created_at,property_id FROM jobs WHERE agency_id=:a AND status IN ('queued','processing') ORDER BY created_at DESC\"), {'a': ag}).fetchall())
"

# Reinicio limpio de api+worker (memoria de runtime: reference_4reels_backend_runtime.md)
kill -TERM $(cat logs/test-api-8001.pid) $(cat logs/test-worker.pid)
nohup .venv/bin/python -m apps.api    > logs/test-api-8001.log 2>&1 & echo $! > logs/test-api-8001.pid
nohup .venv/bin/python -m apps.worker > logs/test-worker.log   2>&1 & echo $! > logs/test-worker.pid
```

## 7. Referencias clave en el repo

- `progress/spec_16b_side_banner_header_and_ber.md` — spec del leader
- `progress/impl_16b_side_banner_header_and_ber.md` — informe del implementer
- `progress/impl_16_side_banner.md` — informe original de feature 16 (clave para
  entender la arquitectura del side_banner)
- `progress/explore_feature_16_layout_side_banner.md` — diseño original
- `example-new-template.png` (root del repo) — la referencia visual del usuario
- `generated_media/dev76.designbricks.ie/posters/1-friar-street-cork-city-centre-co-cork-poster.jpg`
  — poster generado PRE-refinamiento (sirve de baseline)

## 8. Tareas Claude Code abiertas

Todas completadas en esta sesión:

```
#1 [completed] Mapear código actual del side_banner
#2 [completed] Identificar gaps visuales vs referencia
#3 [completed] Validar plan con el usuario
#4 [completed] Delegar cambios al implementer
#5 [completed] Reviewer + smoke poster  (smoke in-process verde; visual real pendiente)
```

El siguiente agente puede arrancar limpio con tareas nuevas.

---

Fin del handover. Si tienes dudas, lee `progress/impl_16b_*` para los detalles
exactos de los cambios y `progress/spec_16b_*` para entender por qué cada
decisión se tomó como se tomó.
