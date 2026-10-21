# Banking Promotions — reglas para Codex

## Objetivo y fuentes de verdad

Capturar promociones y beneficios de bancos y billeteras argentinos: descuentos, reintegros, cuotas, regalos, puntos, servicios gratuitos, bonificaciones de comisiones y otros beneficios documentados. Priorizar fidelidad a la fuente, trazabilidad e integridad de datos antes que cantidad de registros o tests verdes.

**Leer el código actual antes de modificarlo.** El contrato V2 real es `backend/normalization/models.py` (no este documento). Para nuevas fuentes usar la skill `$integrate-promotion-source`. Codex principal desarrolla y coordina; `promotion_qa` realiza una auditoría independiente en contexto nuevo.

## Mapa mínimo

- `backend/scraping/sources/<fuente>/scraper.py`: captura y control del snapshot.
- `backend/scraping/models.py`: `ScrapeResult`; su `complete` es un control estructural, no una garantía total.
- `backend/normalization/sources/<fuente>.py` y `backend/normalization/models.py`: transformación V2 y contrato.
- `backend/synchronization/runner.py`, `sync_<fuente>.py`: validación y ruta con posibles escrituras.
- `backend/persistence/`: Supabase.
- `backend/tests/`: pruebas con mocks y fixtures; `backend/data/`: snapshots/exports persistentes; `backend/.tmp/`: artefactos temporales.
- `.github/workflows/`: sincronización programada, fuera del alcance de una integración normal.

## Reglas obligatorias de datos

- Usar páginas/API y legales oficiales para definir el alcance real; comprobar categorías, filtros, paginación, detalles y cobertura. No asumir que HTTP 200 o un conteo coincidente prueban completitud.
- Preservar datos crudos, identificadores estables, URL, legales y fecha de captura. No inventar porcentajes, topes, fechas, medios de pago, días ni comercios como fallback de parsing.
- Cada registro crudo debe normalizar a una o más variantes V2, con `source_id` estable y único por variante; usar `promotion_group_id` cuando corresponda. No omitir beneficios reales por ser financieros, no comerciales o difíciles de modelar.
- Separar beneficios simultáneos de alternativas condicionadas. Representar topes, mínimos, stock, usos, moneda y período con los tipos V2. Cada `PaymentMethod` es una combinación efectivamente permitida, no un producto cartesiano de tarjetas/billeteras.
- Fechas y canales pueden ser desconocidos (`None`); `days_of_week=[]` no equivale a todos los días. Diferenciar `applies_every_day` explícito de ausencia de información.
- Conservar `terms` íntegros y `specific_conditions` útiles; si debe consultarse un listado externo de comercios adheridos, incluir bandera y URL oficial. No interpretar campos vacíos como prueba de ausencia de restricciones.

## Integridad y escritura: fail closed

1. `scrape()` produce un candidato `ScrapeResult` **sin guardar snapshots**.
2. El `SyncRunner` valida resultado completo, IDs crudos, normalización de cada fila y unicidad de IDs V2 **antes** de llamar al guardado de raw o a Supabase. No crear rutas alternativas que salteen estos controles.
3. `save_raw_promotions()` debe rechazar capturas vacías, truncadas, inconsistentes, detalles obligatorios en blanco y desapariciones/sustituciones de IDs anteriores no justificadas; escritura atómica y conservación de bytes anteriores ante rechazo. Probar con baseline previo *válido*, no con datos malformados.
4. Evaluar por separado: `catalog_complete`, `normalization_complete`, `snapshot_replace_allowed`, `requires_review`, `safe_to_deactivate`. Algunas son metadatos opcionales de fuente, no propiedades garantizadas del modelo. **Flag ausente no equivale a aprobación.**
5. La desactivación debe permanecer deshabilitada por defecto; exige ejecución live completa, opt-in explícito, `coverage.safe_to_deactivate is True` y upsert completo. `--from-file` nunca autoriza desactivaciones. Los jobs de CI son efímeros: ausencia de snapshot local no demuestra que sea la primera ejecución.

El snapshot raw y Supabase no son una transacción única. Informar los riesgos de fallo parcial y de baseline histórico no persistente en vez de declarar seguridad inexistente.

## Límites y permisos

- **Sin autorización expresa**, no ejecutar `sync_<fuente>`, `SyncRunner.run()`, `--from-file` ni siquiera `--validate-only`; este último puede ejecutar scraping real e importar configuración de Supabase. No escribir en Supabase, modificar migraciones/workflows, desplegar, hacer push ni merge.
- Se permiten cambios en código/fixtures/tests de la fuente solicitada y pruebas locales con mocks, sin secretos ni producción. Revisar `git status` y respetar trabajo ajeno. Sin `verify=False`, evasión de bloqueos ni lectura/exposición de `.env`.
- Las revisiones QA son independientes y **sin modificaciones**; las instrucciones del agente no crean por sí solas un sandbox de solo lectura. Declarar si no hubo aislamiento técnico.
- Las correcciones posteriores a QA requieren indicación del usuario: no encadenar automáticamente rondas de Dev/QA.

## Pruebas y entrega

- Usar fixtures pequeñas, `tmp_path`, `httpx.MockTransport`, pruebas de regresión y `python -m pytest -q tests` desde `backend/` cuando el entorno lo permita. Cubrir datos incompletos, IDs faltantes/duplicados, variantes vacías, pérdida de IDs con igual conteo, reemplazo raw rechazado, upsert parcial y bloqueo de desactivación.
- Validar valores normalizados contra evidencia oficial, no contra expectativas copiadas del propio parser. Hasta 30 campañas: revisión completa; más de 30: muestra estratificada y limitaciones explícitas.
- Entregar archivos modificados, comandos/resultados reales, raw/variantes/exclusiones, las cinco decisiones de integridad y riesgos pendientes. QA `PASS` solo habilita **revisión humana**, nunca sincronización automática.
