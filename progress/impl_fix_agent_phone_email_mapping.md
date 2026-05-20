# Hotfix: agent phone/email mapping en `Property.from_api_payload`

- **Tipo:** hotfix puntual (no es feature del backlog, no toca `feature_list.json`).
- **Agente:** Claude (implementer lanzado por leader).
- **Fecha:** 2026-05-19.
- **Toca schema?:** No. Sólo lógica de parser; columnas `agent_email`,
  `agent_mobile`, `agent_number` ya existen en `properties`.
- **Módulo afectado:** `modules/catalog/domain/wordpress_property.py`.

## Causa raíz

El reel galaxy de Century 21 para `dev76.designbricks.ie / 1234` pintaba el
teléfono en la línea de email (icono `✉️`) y dejaba vacía la línea de teléfono
(icono `📞`). El payload del webhook trae:

```json
{
  "agent_name":  "Suzanne Russo",
  "agent_phone": "843 300 7077",
  "agent_email": "(843) 300 7077"
}
```

Y el mapeo original en `modules/catalog/domain/wordpress_property.py:169-171`
sólo conocía las claves `agent_mobile`, `agent_email`, `agent_number`:

```python
agent_email=to_text(payload.get("agent_email")),
agent_mobile=to_text(payload.get("agent_mobile")),
agent_number=to_text(payload.get("agent_number")),
```

Resultado en `properties`:

- `agent_mobile = NULL`, `agent_number = NULL`.
- `agent_email = "(843) 300 7077"` (un teléfono guardado como email).

`build_agent_lines()` (`modules/rendering/infrastructure/formatting.py:539`)
hacía entonces:

- `phone_number = agent_mobile or agent_number` → `None` → línea `📞` vacía.
- `agent_email = "(843) 300 7077"` → línea `✉️` con un teléfono dentro.

## Regla nueva de resolución

Implementada como helper privado `_resolve_agent_contact(payload)` en
`wordpress_property.py`, invocado desde `from_api_payload`:

1. `agent_mobile` explícito gana. Si está vacío, fallback a `agent_phone`.
   Si ambos vacíos, `None`.
2. `agent_email` se descarta si el string final **no contiene `'@'`**.
   Regla mínima y conservadora; suficiente para el caso real.
3. Promoción defensiva: si tras (1) `agent_mobile` sigue `None` **y** el
   `agent_email` crudo no contenía `@` pero sí ≥ 6 dígitos, se promueve
   ese valor a `agent_mobile`. Sólo aplica cuando ambos slots de teléfono
   están vacíos — nunca pisa un valor del operador.
4. `agent_number` (office line) intacto.

Helper trivial `_contains_n_digits(value, n)` queda como función privada del
mismo módulo (no en `shared/`, según las instrucciones).

## Archivos modificados / creados

| Archivo | Tipo | Cambio |
| --- | --- | --- |
| `modules/catalog/domain/wordpress_property.py` | parser de dominio | Añadidos helpers `_contains_n_digits` y `_resolve_agent_contact`; `from_api_payload` ahora delega la resolución de `agent_mobile/agent_email/agent_number` a este último. |
| `tests/unit/catalog/test_wordpress_property_agent_contact.py` | unit test nuevo | 8 tests cubriendo precedencia, descarte de email malformado, promoción defensiva, caso real `dev76 / 1234`, no-promoción cuando `agent_mobile` ya viene, y aislamiento de `agent_number`. |

## Tests añadidos

`tests/unit/catalog/test_wordpress_property_agent_contact.py`:

1. `test_from_payload_uses_agent_mobile_when_present` — `agent_mobile` explícito gana sobre `agent_phone`.
2. `test_from_payload_falls_back_to_agent_phone_when_mobile_missing` — fallback a `agent_phone`.
3. `test_from_payload_discards_malformed_email_without_at_sign` — sin `@` y con 6+ dígitos: email se descarta + promoción a mobile.
4. `test_from_payload_preserves_valid_email` — un email válido se mantiene; no hay promoción a mobile.
5. `test_from_payload_real_world_dev76_property_1234` — replica el payload Century 21 reportado (Suzanne Russo) y comprueba el resultado correcto.
6. `test_from_payload_explicit_mobile_blocks_email_promotion` — si el operador rellenó `agent_mobile`, el email malformado se descarta pero NO se promueve nada.
7. `test_from_payload_does_not_promote_short_digit_string` — string sin `@` y con < 6 dígitos se descarta sin promover.
8. `test_from_payload_preserves_agent_number_independently` — `agent_number` (office line) sigue su propia ruta.

## Verificaciones

- `.venv/bin/python -m pytest tests/unit/catalog/ -q` → **13 passed in 0.05s** (5 previos + 8 nuevos).
- `.venv/bin/python -m pytest tests/integration/reels/ -q` → **134 passed in 220.85s**.
- `.venv/bin/python -m apps.api --check` → verde.
- `.venv/bin/python -m apps.worker --check` → verde (`Worker --check OK`).
- `bash ./init.sh` → exit 0; **1125 passed, 1 deselected, 14 warnings, 3 failed** (baseline histórico: `test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` y los 2 de `test_http_transport.py`). Pasados subieron de 1117 → 1125 (= +8 tests nuevos, todos verdes).

## Decisiones no obvias

- Helpers (`_contains_n_digits`, `_resolve_agent_contact`) viven en el mismo
  módulo, no en `shared/` o en `_property_conversions.py`. La lógica es
  específica de este dominio y la instrucción pedía mantenerla privada al
  archivo.
- Regla "contiene `@`" para validar email: conservadora a propósito. No
  intenta replicar RFC 5322; cualquier validación más compleja podría
  descartar inputs legítimos. Para el caso reportado (`"(843) 300 7077"`)
  basta y sobra.
- La promoción defensiva queda gateada estrictamente: sólo cuando **ambos**
  slots de teléfono (`agent_mobile` *y* `agent_phone`) están vacíos. Así
  nunca pisamos un dato que el operador haya curado.
- No reescribí el call site en `from_api_payload` con un bloque condicional
  inline para no engordar el método (ya tiene ~70 líneas de mapeo); un
  helper bien nombrado documenta mejor la regla.

## Estado

Implementación cerrada. Revisión pendiente (el leader debe lanzar
`reviewer`). Sin marcar `done` en `feature_list.json` (no procede — es un
hotfix puntual, no una feature del backlog).
