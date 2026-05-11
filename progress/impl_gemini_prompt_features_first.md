# Impl — Gemini photo-selection prompt: features-first captions/highlights

Tarea fuera de `feature_list.json` (cambio puntual de prompt solicitado por
el usuario). No se ha tocado `feature_list.json`.

## Archivos modificados

- `modules/rendering/infrastructure/ai_photo_selection/prompting.py`
  - `build_property_context`:
    - Nuevo: `property_accommodation = html_to_text(property_item.property_accommodation)`
      (el campo ya existe en el dominio `Property`).
    - Nueva línea de contexto: `Property accommodation: {property_accommodation}`
      (cuando esté disponible).
    - Nueva clave en el dict devuelto: `"property_accommodation"`.
  - `build_prompt`:
    - Nuevo bloque "Caption and highlights source-of-truth rules" insertado
      tras "Main features provided by the agent or listing" y antes de
      "Classify the image...". Reglas añadidas:
      1. Generar `caption` y `highlights` principalmente desde el bloque
         de main features (reutilizando su redacción).
      2. Recurrir a property accommodation / Description / Excerpt solo
         como fuente secundaria cuando los main features no basten.
      3. No repetir información entre captions / highlights de distintas
         fotos del mismo inmueble; cada slide aporta un dato distinto.
    - Resto de reglas y JSON shape intactos.

## Tests

`pytest tests/test_gemini_photo_selection.py -q`

```
...............                                                          [100%]
15 passed in 0.91s
```

Las aserciones existentes sobre el texto del prompt (presencia de
`Main features provided by the agent or listing:`, lista de features,
ejemplos de caption, etc.) siguen verdes; el nuevo bloque se añade sin
alterar las cadenas exactas que comprueban los tests.

## Notas

- `property_accommodation` ya estaba expuesto en
  `modules/catalog/domain/wordpress_property.py` (campo `Property.property_accommodation`),
  por lo que no fue necesario tocar el dominio.
- Cambio quirúrgico: solo se añade contenido al prompt y un campo nuevo
  al contexto; ningún flujo, JSON shape ni regla previa fue eliminado.
- Pendiente revisión por `reviewer`. No se marca nada como `done`.
