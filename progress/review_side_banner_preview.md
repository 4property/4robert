# Review — side_banner render-template preview

**Veredicto:** APPROVED

## Checkpoints

- C1 (cadena alembic): [x] `revision = "20260515_0001"`,
  `down_revision = "20260514_0007"`. La revisión anterior
  `20260514_0007_email_notifications.py` existe en
  `alembic/versions/` y era el head previo. La nueva queda como head.
- C2 (upgrade apunta a side_banner + asset correcto): [x]
  `alembic/versions/20260515_0001_side_banner_render_template_preview.py:32`
  filtra `WHERE template_id = 'side_banner'` y
  `image_url = "/assets/render-templates/side-banner-template.png"`
  (líneas 17-23). El payload replica fielmente el patrón de classic
  (`20260514_0002` líneas 17-23) cambiando sólo template_id, image_url
  y alt.
- C3 (downgrade idempotente): [x] Líneas 37-46: revierte a `'[]'::jsonb`
  sólo si `preview_images = CAST(:preview_images AS jsonb)` coincide
  con el JSONB aplicado en upgrade. Mismo patrón que classic
  (`20260514_0002` líneas 37-46).
- C4 (scope): [x] Sólo se crearon dos archivos nuevos
  (`assets/render-templates/side-banner-template.png` y la migración).
  Nada en `apps/`, `modules/`, `shared/`, `settings/`, `tests/` ni
  `feature_list.json` fue modificado por esta tarea (el resto de
  cambios `M`/`??` visibles en `git status` pertenecen a features
  previas, no a este scope).
- C5 (asset existe y no está vacío): [x]
  `assets/render-templates/side-banner-template.png` = 959 567 bytes,
  PNG válido (721x960 RGBA, non-interlaced). Coincide bit-a-bit con
  el origen `side-banner-template.png` en la raíz (`diff -q` sin
  diferencias, mismo tamaño).

## Notas

- `alembic upgrade` no se ejecutó (por instrucción explícita del
  leader). La validación de la cadena se hizo por inspección estática
  del par `revision` / `down_revision` y de los archivos presentes en
  `alembic/versions/`.
- El archivo origen `side-banner-template.png` en la raíz se conserva.
  No es problema (no se sirve desde ahí), pero puede limpiarse en un
  follow-up si se desea — no bloquea la aprobación.

## Cambios requeridos

Ninguno.
