# Impl — Feature 10 `reels_use_case_ingest_property_into_reel`

> Extracción del paso 1 del pipeline (ingest) desde
> `application/pipeline/media_services.py` hacia
> `modules/reels/application/use_cases/ingest_property_into_reel.py`
> conforme al informe del explorer.

---

## 1. Archivos creados / modificados / borrados

### Creados

| Archivo | LoC | Tipo |
|---------|-----|------|
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 958 | Use case + helpers privados (mover el contenido del paso ingest del legacy). |
| `tests/unit/reels/test_ingest_property_into_reel.py` | 226 | Unit (camino feliz, noop por estado idéntico, camino de error con payload no Mapping). |
| `tests/integration/reels/test_ingest_property_into_reel_flow.py` | 118 | Integration (`temporary_postgres_schema` + `seed_tenant`, valida `reels`, `properties`, `media_revisions` vacío). |

### Modificados

| Archivo | Cambio |
|---------|--------|
| `application/pipeline/media_services.py` | 1839 → **1034 LoC**. Eliminados los rangos del informe del explorer (helpers privados ingest + free funcs ingest + cuerpo de `ingest_property` + `_build_ingested_pipeline_state`). `DefaultPropertyInfoService` se queda como adapter delgado (~33 LoC con docstring) que delega `ingest_property` al `IngestPropertyIntoReelUseCase`. Imports limpiados (`hashlib`, `json`, `ContentGenerator`+`DeterministicPropertyContentGenerator`, `build_media_delivery_plan`, `get_platform_config`, `normalize_platform_name`, `resolve_site_storage_layout`, `build_property_public_url`, `PlatformPublishTargetPlan`, `SocialPublishContext`). El `unit_of_work_factory` legacy se acepta en el `__init__` (firma estable para `application/bootstrap/runtime.py`) pero no se almacena (`del unit_of_work_factory`). |
| `modules/reels/application/use_cases/__init__.py` | Re-export del nuevo `IngestPropertyIntoReelUseCase`. Conservado `RenderScriptedVideoUseCase`. |
| `tests/support/postgres.py` | En `temporary_postgres_schema` el `finally` ahora dispone el engine cacheado en `shared.db.engine._ENGINE_CACHE` para la URL scoped. Sin esto, la suite acumula 1 engine por test → eventual agotamiento del pool de conexiones de Postgres. La regression apareció al sumar el nuevo test de integración (380 tests vs 376 baseline empujaron al límite). El cambio es defensivo y mejora aislamiento. |

### Borrados

Ninguno. (Las features 11-14 borrarán progresivamente `media_services.py` y `application/persistence.py`.)

---

## 2. Líneas eliminadas de `media_services.py`

Reducción neta: **1839 → 1034 LoC** (805 LoC eliminados, ~44%).

Rangos borrados (relativos al archivo original):

- `73` `_SUCCESSFUL_SOCIAL_STATUSES` (constante).
- `76-101` `_default_pipeline_state`.
- `104-107` `_json_hash`.
- `110-111` `_json_text`.
- `114-121` `_parse_json_object`.
- `124-127` `_resolve_absolute_path`.
- `178-195` `_normalise_platforms`.
- `198-265` `_parse_publish_target_snapshot`.
- `268-282` `_extract_platform_results`.
- `285-291` `_is_successful_platform_result`.
- `294-313` `_extract_successful_platforms`.
- `342-977` Cuerpo completo de `DefaultPropertyInfoService` (excepto el adapter delgado nuevo): `__init__`, `ingest_property`, `_resolve_publish_inputs`, `_build_ingested_pipeline_state`, `_build_content_snapshot`, `_build_publish_target_snapshot`, `_build_publish_targets`, `_determine_pending_publish_platforms`, `_should_prepare_assets`, `_has_local_artifacts`, `_build_existing_published_media`, `_should_reset_publish_history`.

Conservados (los siguen usando los pasos 2-4 que están en este mismo archivo): `_now_iso`, `_relative_path_text`, `_build_workflow_payload`, `LocalPhotoSelectionEngine`, `DefaultMediaPreparationService` (con sus dos staticmethods que el use case nuevo importa puntualmente — bridge documentado en el código), `DefaultPhotoSelectionService`, `DefaultMediaRenderer`, `FileSystemMediaPublisher`, `CompositeMediaPublisher`.

> **Nota sobre el LoC objetivo**: el explorer estimó ~960 LoC. El resultado real es 1034 porque mantuve los blocks de código que dependen del adapter delgado (sus imports siguen vivos para los pasos 2-4). El delta no afecta la corrección y queda dentro del orden de magnitud previsto.

---

## 3. Decisiones del leader respetadas

- **D1 (`media_revisions` no escribe en ingest)**: el use case nuevo NO toca `uow.reels.revisions`. El test de integración asserta que `media_revisions` está vacía tras `execute(...)`. Documentado.
- **R1 (`_should_prepare_assets` cruza al step 2)**: el método en el use case importa `DefaultMediaPreparationService.resolve_selected_dir` y `.resolve_primary_image_from_dir` de `application.pipeline.media_services` con un comentario que menciona "feature 11 lo absorbe". Como el método estático legacy lee `state.selected_image_folder` de un `PropertyPipelineState`, el use case construye un `SimpleNamespace` con ese único campo desde el `ReelState` moderno (helper `_state_for_legacy_helpers`).
- **R2 (`PropertyContext` con strings JSON)**: contrato preservado. El use case escribe `dict` a `uow.reels.states` y serializa a `str` (`_json_text`) para construir el `PropertyContext` de salida.
- **R3 (doble UoW durante el bridge)**: el use case acepta opcionalmente un `uow` en `execute(...)`. Si no se pasa, abre su propio `DatabaseUnitOfWork(self.database_locator, base_dir=self.workspace_dir)`. Esto es lo que hace el adapter `DefaultPropertyInfoService` invocado desde el bridge legacy. El `unit_of_work_factory` legacy del adapter se ignora con `del unit_of_work_factory` (aceptado para no romper bootstrap).
- **R5 (logs verbatim)**: los `logger.info(format_console_block(...))` se trasladan sin reformatear (mismos titles "Property Ingest Decision", "Property Content Generation Started", "Property Content Generation Completed").
- **D3 (`application/bootstrap/{runtime.py,__init__.py}`)**: NO se tocaron. La firma de `DefaultPropertyInfoService.__init__` se mantiene exacta, así que ambos archivos siguen funcionando byte-a-byte iguales.

---

## 4. Resultado de los checks de cierre

### Tests

```
$ pytest -q tests/unit/reels/test_ingest_property_into_reel.py
3 passed in 1.09s

$ pytest -q tests/integration/reels/test_ingest_property_into_reel_flow.py
1 passed in 3.00s

$ ./init.sh
...
380 passed in 228.40s (0:03:48)
[OK]    pytest verde
```

Baseline pre-feature: **376 tests**. Tras feature 10: **380 tests** (376 + 3 unit + 1 integration = 380). Todos verdes en `./init.sh`.

### Readiness

```
$ python -m apps.api --check
... apps.api --check verde

$ python -m apps.worker --check
... apps.worker --check verde
```

Ambos exit 0.

### Repo limpio

- Sin `xfail`, sin `print()` de debug, sin TODOs sin contexto.
- Sin `__pycache__` o `.tmp_*` adicionales fuera de los habituales.

---

## 5. Desviaciones frente al plan del explorer

1. **LoC final 1034 vs ~960 estimado**: explicado arriba (el delta es ruido, no funcional).
2. **Constructor del use case sin `unit_of_work_factory` legacy**: el explorer dejó la opción abierta entre "aceptar el factory legacy" o "limpiar el constructor". Elegí la opción limpia: el use case nuevo NO acepta `unit_of_work_factory` legacy. El adapter `DefaultPropertyInfoService` recibe el factory legacy en su `__init__` (no lo guarda, `del unit_of_work_factory`) y construye el use case sin ese parámetro. Esto reduce el ruido en el use case sin romper la firma del bootstrap.
3. **Fix colateral en `tests/support/postgres.py`**: añadir el use case + integración empujó la suite al límite del pool de conexiones de Postgres, haciendo fallar `tests/unit/test_tenancy.py::TenantResolverTests::test_resolve_returns_tenant_context_for_active_site` por "no schema has been selected to create in" durante alembic upgrade. La causa: `shared.db.engine._ENGINE_CACHE` acumula un engine por URL scoped, y la disposición no ocurría al destruir el schema. Solución: en `temporary_postgres_schema._finally_` se hace `_ENGINE_CACHE.pop(scoped_url).dispose()`. Cambio defensivo, no toca lógica de feature.

---

**Fin del informe.**
