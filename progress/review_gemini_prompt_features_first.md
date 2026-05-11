# Review — Gemini prompt features-first captions/highlights

**Veredicto:** APPROVED

## Verificaciones

### 1. Cumple los tres requisitos del usuario
- [x] Features primero: nuevo bloque "Caption and highlights source-of-truth rules" obliga a generar `caption`/`highlights` PRIMARILY desde "Main features provided by the agent or listing" (`prompting.py:240`).
- [x] Fallback a accommodation/Description/Excerpt solo como SECONDARY source (`prompting.py:241`), con prohibición de inventar (`prompting.py:242`).
- [x] No repetir información entre slides del mismo inmueble (`prompting.py:243`): cada caption/highlight debe aportar un dato distinto y, si una feature ya se usó, elegir otra.

### 2. `property_accommodation` en dominio
- [x] Campo declarado en `modules/catalog/domain/wordpress_property.py:62` (`property_accommodation: str | None = None`) y poblado vía `from_api_payload` (línea 151).
- [x] `build_property_context` lo extrae con `html_to_text(property_item.property_accommodation)` (`prompting.py:137`), lo emite en `context_lines` solo si no está vacío (`prompting.py:174-175`) y lo expone en el dict devuelto (`prompting.py:200`). Uso correcto y simétrico al de `excerpt`/`description`.

### 3. Tests
- [x] `python -m pytest tests/test_gemini_photo_selection.py -q` → `15 passed in 0.59s`. Sin regresiones en las aserciones existentes (cabeceras del prompt, lista de features, ejemplos de caption se conservan literalmente).

### 4. Coherencia con reglas previas del prompt
- Regla previa "Reuse the wording and terminology found in the property context and main features wherever possible" (`prompting.py:288`) NO entra en conflicto: la nueva regla la refuerza dándole prioridad explícita a `main features` sobre el resto del contexto, pero ambas apuntan a reutilizar redacción y no inventar.
- Regla previa "Never invent details" (`prompting.py:12-13` lógicas + `prompting.py:284`) coherente con la nueva "Never invent details that are not present in either the main features block or the property accommodation / description / excerpt".
- Regla previa "Prefer highlights that help distinguish this space from other photos" (`prompting.py:271`) refuerza —no contradice— la nueva exigencia de no repetir información entre slides; la nueva regla es más estricta (prohibición explícita) pero compatible.
- JSON shape, lista de labels, reglas de rechazo de planos/mapas y formato de primer slide quedan intactos.

## Checkpoints
- C-prompt-coverage: [x] tres requisitos cubiertos en texto explícito.
- C-domain-field: [x] `property_accommodation` existe en dominio y se usa.
- C-tests: [x] 15/15 verdes, sin tocar fixtures.
- C-coherencia: [x] sin contradicciones con reglas anteriores.
- C-aislamiento: [x] cambio confinado a `modules/rendering/infrastructure/ai_photo_selection/prompting.py`; sigue importando `Property` desde `modules.catalog.domain` (correcto, dominio cruzado vía dominio, no infra).
- C-schema: [x] N/A (no hay cambios de schema ni migraciones).

## Observaciones menores (no bloquean)
- El nuevo bloque añade ~4 líneas largas al prompt; el coste por llamada subirá marginalmente. Aceptable dado el objetivo.
- Podría considerarse mover el nuevo bloque después del listado completo de "Rules:" para mantener todas las reglas agrupadas, pero la ubicación actual (justo tras el bloque de main features) es defendible porque ata la regla a su fuente de datos.

## Cambios requeridos
Ninguno.
