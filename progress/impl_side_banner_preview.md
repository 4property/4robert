# impl: side_banner render-template preview image

## Scope

Out-of-tracker task (no `feature_list.json` entry). Replica del patrón
aplicado a `classic` (migración `20260514_0002`) pero para el template
`side_banner`.

## Archivos creados / modificados

- **Created** `assets/render-templates/side-banner-template.png`
  (copia 1:1 de `side-banner-template.png` en la raíz; 959 567 bytes).
- **Created** `alembic/versions/20260515_0001_side_banner_render_template_preview.py`
  (migración: `revision = "20260515_0001"`, `down_revision = "20260514_0007"`).

No se modificó nada más. El archivo origen en la raíz se conserva.

## Verificaciones

1. Asset copiado:

   ```
   $ ls -la assets/render-templates/side-banner-template.png
   -rw-r--r--. 1 support support 959567 May 15 16:59 .../side-banner-template.png
   ```

2. Metadata de la nueva revision:

   ```
   $ python -c "import importlib.util; spec=importlib.util.spec_from_file_location('m','alembic/versions/20260515_0001_side_banner_render_template_preview.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.revision, m.down_revision)"
   20260515_0001 20260514_0007
   ```

3. Cadena alembic (sólo lectura, sin aplicar):

   ```
   $ alembic history | head
   20260514_0007 -> 20260515_0001 (head), Attach the side_banner render-template preview image.
   20260514_0006 -> 20260514_0007, Create ``email_notifications`` table (feature 26).
   ...
   ```

   La nueva revisión queda correctamente como `head`, encadenada
   después de `20260514_0007`.

## Decisiones / desviaciones

- Ninguna desviación del patrón de `20260514_0002`: mismo estilo de
  `op.execute` con `sa.text(...).bindparams`, mismo payload de un sólo
  item `kind=preview`, mismo `downgrade` idempotente que sólo revierte
  si el JSONB actual coincide con el aplicado en `upgrade`.
- `alembic upgrade` **no** se ejecutó (decisión del leader tras review).
- `feature_list.json` no se tocó (la tarea no está listada).
