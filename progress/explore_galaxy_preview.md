# Exploración: Single-Frame Render Mechanism para Template Galaxy

## Resumen Ejecutivo

**NO HAY BLOQUEADOR**: El repo ya tiene un mecanismo maduro de single-frame render (poster) con ffmpeg `-frames:v 1`. Este mecanismo es reutilizable directamente para generar previews de frames del template galaxy sin ejecutar el pipeline completo de video.

---

## 1. Hallazgo: Mecanismo Existente de Single-Frame Render

**Ubicación**: `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/poster.py`

**Función pública**:
```python
def generate_property_poster_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
    layout_variant: str = "classic",
) -> Path
```

**Cómo funciona**:
- Recibe `PropertyRenderData` (metadatos de propiedad) + `PropertyReelTemplate` (config de reel)
- Ejecuta `ffmpeg -y -loop 1 -i <foto> ... -filter_complex_script <filtros> -frames:v 1 -q:v 2 <output.jpg>`
- Devuelve la ruta JPG generada
- **CLAVE**: usa `-frames:v 1` (solo 1 frame, SIN video encoding completo)
- Duración típica: <5 segundos para una imagen JPG
- Ya soporta `layout_variant` con valores: `"classic"`, `"side_banner"` (rama lógica en filters.py:136)

---

## 2. Arquitectura de Layout Variants (Cómo Agregar `"galaxy"`)

**Archivo de branching principal**: `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/layout/panels.py`

El patrón es:
```python
is_side_banner = layout_variant == "side_banner"
# ... lógica diferencial ...
if is_side_banner:
    # custom geometry / colors
else:
    # classic defaults
```

**Para agregar `"galaxy"`**:
1. Crear branching `layout_variant == "galaxy"` en `panels.py` (copia el patrón side_banner)
2. Definir geometría de paneles (header/footer/ribbon) específica para galaxy
3. Replicar lógica en `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/ffmpeg/filters.py:136+` (build_overlay_filter)
4. El resto del pipeline (poster.py, frame_composition.py) es agnóstico respecto a layout_variant

---

## 3. Tests Existentes con Snapshots (NO Imágenes Reales)

- **`/opt/projects/4Reels-Backend/tests/unit/rendering/test_overlay_filter_classic_snapshot.py`**: 
  - Snapshot de filter graph (string, no imagen)
  - Compara output byte-for-byte del ffmpeg filter
  - Portable across machines (normaliza rutas de fuentes)
  - **NO genera imagen PNG**, solo valida el filtro ffmpeg

- **Integration tests** (`test_render_with_intro.py`, etc.):
  - Mockean `generate_property_poster_from_data` con `b"jpg-stub"`
  - No producen imágenes reales (tests rápidos)

---

## 4. Assets de Prueba Disponibles

| Ubicación | Contenido |
|-----------|-----------|
| `/opt/projects/4Reels-Backend/assets/render-templates/` | `classic-template.png` (1.1 MB), `side-banner-template.png` (960 KB) - **Referencias visuales** |
| `/opt/projects/4Reels-Backend/example-template-galaxy.png` | 1054×1492 PNG (2.6 MB) - **YA EXISTE**: referencia del template galaxy |
| `/opt/projects/4Reels-Backend/assets/` | Fonts, BER icons, música (listos para usar) |
| `tests/unit/rendering/conftest.py` | Builders: `build_property_data()`, `build_template()` - generan mocks mínimos |

---

## 5. FFmpeg Disponible

```
/usr/bin/ffmpeg version 7.1.4
Compilado con soporte completo para filtros, codecs, y composición
```

✅ Disponible en el host. Listo para usar.

---

## 6. Propuesta: Mecanismo Más Barato para Generar Frames Galaxy

### Opción Ganadora: **(b) Test pytest que escribe frame a `progress/galaxy_iter_N.png`**

**Por qué esta opción**:
1. **Velocidad**: Reutiliza el código existente de `generate_property_poster_from_data`, ajustado a `layout_variant="galaxy"`. Una línea de Python → ffmpeg `-frames:v 1` → 3-5 seg. Más rápido que un script manual.
2. **Fidelidad**: Usa el mismo pipeline ffmpeg que el reel final (same filter graph builder, mismo orden de overlays, mismos fonts). No hay sorpresas en la iteración final.
3. **Iterabilidad**: El test está bajo control de versión; el leader puede hacer diff de cambios en conftest/fixtures sin escribir scripts.
4. **Facilidad de integración**: Ya hay fixtures (`build_property_data`, `build_template`) → agregar `build_template(..., layout_variant="galaxy")` y pasar a `generate_property_poster_from_data`.

**Rechazo de alternativas**:
- **(a) Script ffmpeg manual**: Menos fidelidad (reinventar drawtext/overlay manual). Más líneas de bash para mantener.
- **(c) Pillow en Python puro**: No soporta los filtros avanzados de ffmpeg (blur, rounded panels, drawtext con fonts dinámicas); tendría que reimplementarlos → riesgo de divergencia vs. render final.

---

## 7. Pasos para Implementar Iteración Galaxy

1. **Rama de feature**: Crear `layout_variant="galaxy"` con branching en `panels.py` + `filters.py`
2. **Fixture de test**: Agregar `test_render_galaxy_preview()` en `tests/unit/rendering/test_galaxy.py`
   ```python
   from modules.rendering.infrastructure.poster import generate_property_poster_from_data
   
   def test_render_galaxy_preview(tmp_path):
       prop_data = build_property_data(...)
       template = build_template(layout_variant="galaxy", width=1054, height=1492)
       output = tmp_path / "galaxy_iter_1.png"
       generate_property_poster_from_data(
           base_dir=...,
           property_data=prop_data,
           output_path=output,
           template=template,
           layout_variant="galaxy",
       )
       assert output.exists()
       # Leader manually compares output vs. example-template-galaxy.png
   ```
3. **Iteración**:
   - Implementer: ajusta geometría/colores en `panels.py`
   - CI: genera `progress/galaxy_iter_N.png` (o test escribe a fs)
   - Leader: abre `example-template-galaxy.png` + `galaxy_iter_N.png` lado a lado → feedback
   - Loop: ~5 min/iteración (render + review)

---

## 8. Archivos Clave a Modificar

| Archivo | Cambio |
|---------|--------|
| `modules/rendering/infrastructure/layout/panels.py` | Agregar branching `layout_variant == "galaxy"` (geometría header/footer/ribbon) |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | Agregar branching en `build_overlay_filter` (colores panels, opacity) |
| `modules/rendering/infrastructure/models.py` | Opcional: agregar campos galaxy-específicos a `PropertyReelTemplate` |
| `tests/unit/rendering/test_galaxy.py` | Nueva: test con `generate_property_poster_from_data(..., layout_variant="galaxy")` |

---

## 9. Evidencia de Caminos No Bloqueados

✅ **Mecanismo de single-frame**: Posters ya generan JPG con `-frames:v 1` sin video  
✅ **Layout variant extensible**: `layout_variant` es string aceptado en filters.py + panels.py  
✅ **Assets de referencia**: `example-template-galaxy.png` (1054×1492) ya existe  
✅ **FFmpeg disponible**: v7.1.4 con todos los filtros compilados  
✅ **Fixtures reutilizables**: `build_property_data`, `build_template` cubren mocks  

**Ningún cambio de arquitectura requerido. Es puro branching en lógica existente.**

---

## Conclusión

La iteración visual del template galaxy está habilitada. Usar la opción **(b)**: test pytest + `generate_property_poster_from_data` con `layout_variant="galaxy"`. El leader obtiene una imagen PNG nueva cada vez en ~5 segundos, lista para comparar con `example-template-galaxy.png`.
