# Review — hotfix `fix_agent_phone_email_mapping`

**Veredicto:** APPROVED

## Resumen

Hotfix puntual al parser `Property.from_api_payload` en
`modules/catalog/domain/wordpress_property.py`. Añade dos helpers
privados (`_contains_n_digits`, `_resolve_agent_contact`) y reemplaza el
mapeo plano de `agent_email/agent_mobile/agent_number` por la llamada al
resolver. Test nuevo: `tests/unit/catalog/test_wordpress_property_agent_contact.py`
con 8 casos (incluye los 5 obligatorios).

Nota terminológica: el bug-report habla de `WordPressProperty` pero la
clase real exportada del módulo se llama `Property` (queda
`from modules.catalog.domain.wordpress_property import Property`). No es
un defecto del implementer — es la nomenclatura existente del repo y
está documentada en el docstring del módulo.

## Checks (1–5)

### 1. Aislamiento del cambio
- **Resultado:** OK.
- `git diff HEAD -- modules/catalog/domain/wordpress_property.py` muestra:
  - Bloque añadido lineas 34–84 (helpers).
  - Hook insertado en `from_api_payload` (linea ~179): tres líneas
    sustituidas para delegar al resolver.
- `git diff HEAD -- modules/rendering/` produce diff pero corresponde a
  trabajo previo de sprint 17-40 (timestamps:
  `formatting.py = 2026-05-13`, `wordpress_property.py = 2026-05-19`).
  El hotfix NO toca renderer. Verificado leyendo el diff vs `HEAD` de
  `formatting.py` y confirmando que es contenido de feature 41
  (snapshots de subtítulos), no de mapeo de teléfono/email.

### 2. Regla de resolución
- **Resultado:** OK. Cada cláusula del spec está implementada de forma
  literal en `_resolve_agent_contact` (lineas 47–84):
  - `agent_mobile` explícito > `agent_phone` (line 67–69).
  - Email descartado si no contiene `@` (line 72, 82).
  - Promoción defensiva con gating estricto (lineas 74–80): solo cuando
    `email_raw is not None and not email_looks_valid and mobile_candidate
    is None and _contains_n_digits(email_raw, n=6)`.
  - `agent_number` intacto (line 83).
  - Helpers viven en el mismo módulo, ambos prefijados con `_`.

### 3. Tests
- **Resultado:** OK.
- `tests/unit/catalog/test_wordpress_property_agent_contact.py`
  contiene los 8 tests anunciados; los 5 obligatorios están presentes
  (lineas 16, 25, 33, 43, 51).
- `.venv/bin/python -m pytest tests/unit/catalog/ -q` → **13 passed in
  0.05s**.
- `.venv/bin/python -m pytest tests/integration/reels/ -q` → **134 passed
  in 220.64s**.

### 4. Convenciones
- **Resultado:** OK.
- `grep` sin matches para `print(`, `TODO`, `FIXME`, `XXX` en el
  archivo.
- `grep` sin matches para imports legacy (`from services.|application.|
  repositories.|core.|domain.`).
- No introduce dependencias nuevas (`Mapping`, `Any` ya estaban; nada
  de stdlib o terceros nuevo).
- Documentación: docstrings completos en ambos helpers.

### 5. Smoke real (snippet de usuario)
- **Resultado:** OK.
- Ejecutado el snippet (con la corrección de nombre de clase:
  `from ... import Property as WordPressProperty`, ya que el módulo
  exporta `Property`, no `WordPressProperty`):

  ```
  agent_name 'Suzanne Russo'
  agent_mobile '843 300 7077'
  agent_email None
  agent_number None
  ```

- Match exacto con el esperado:
  `agent_mobile == '843 300 7077'`, `agent_email is None`,
  `agent_number is None`.

## Issues

Ninguna.

## Observaciones (no bloquean)

- La descripción del bug y el report del implementer hablan de
  `WordPressProperty.from_api_payload`; la clase real se llama
  `Property` y vive en `modules/catalog/domain/wordpress_property.py`.
  El snippet de smoke del request tal cual está escrito (con
  `from ... import WordPressProperty`) falla con `ImportError`. Es un
  detalle de nomenclatura, no un fallo del fix. Si en el futuro se
  reescribe el snippet conviene usar `Property` directamente o un alias
  explícito.

