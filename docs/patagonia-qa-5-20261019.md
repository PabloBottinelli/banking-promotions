# Banco Patagonia — cierre independiente QA#5

**VERDICT: PASS. Estado: READY_FOR_HUMAN_REVIEW_QA5_PASS. Producción, reemplazo y desactivación: NO autorizados.**

Auditor: rol existente `promotion_qa`, independiente del desarrollo. Este documento lo publica desarrollo como resumen atribuido del informe comunicado al coordinador. QA fue de sólo lectura por instrucción, sin aislamiento técnico de permisos. No accedió a `.env`, al repositorio real de persistencia ni ejecutó escrituras, sincronización o desactivaciones.

El usuario autorizó hasta dos rondas adicionales tras QA#4 («dale 2 vueltas mas si hace falta»), conservando requisitos y criterios. Se completó una, QA#5, y se detiene el ciclo por PASS. No se necesita QA#6. La reanudación por límite de uso de QA#4 fue la misma auditoría; el intento interrumpido antes del tercer veredicto no cuenta como otra completada. Los cinco veredictos completados fueron FAIL, FAIL, FAIL, FAIL, PASS.

## Alcance y resultados

QA#5 contrastó **16 raws, 25 variantes y 19 fichas oficiales**, más Almundo Paquetes como exploración adicional. No auditó comercialmente los 350 registros completos. Recalculó **350 raws → 583 variantes**, exactamente iguales al export congelado, con cero errores y cero exclusiones. Confirmó Decimales serializados como strings, ausencia de campos planos legacy y conservación de los 350 flags de revisión.

Los casos QA011 y QA012 quedaron cerrados; no se confirmó reapertura de QA001–QA010:

- [Grigorian](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/ciclo-grandes-interpretes-teatro-colon-grigorian.html): `08/12/2026` y `8/12/2026` representan el mismo 8 de diciembre. Ante la tabla del 7, fechas `None` y aviso de vigencias contradictorias. Cuando todas las fuentes coinciden en el 8, se conserva el 8. Sin fechas comerciales hardcodeadas.
- [Patagonia Wine Fest](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/patagonia-wine-fest.html): TuEntrada exclusiva, consumo familiar y máximo de cuatro tickets por persona visibles; `online=True`, tres cuotas sin interés y límite `other`, `quantity=4`, `scope=person`, sin inventar moneda, periodicidad o stock global.

Selección de QA#5: **93 passed, 16 deselected, 0 failed**. Comando base: `python -B -m pytest -q -p no:cacheprovider`, autoload de plugins deshabilitado y persistencia simulada antes de importar. Los 16 tests de filesystem se inspeccionaron sin ejecutarse. Se verificaron además seis escenarios históricos en memoria: desaparición 65→56, sustituciones con totales iguales/mayores y baseline ausente rechazados; adiciones y actualizaciones admitidas; `safe_to_deactivate=False`. Sin escrituras. La suite de desarrollo **109 passed, 0 failed, 1.78 s** es evidencia distinta, con reproducción completa en [el informe principal](patagonia-review.md).

El barrido independiente de **cuatro storefronts, 101 categorías, 822 URLs exactas y 29 categorías vacías** pertenece a QA#3. Se conserva porque el scraper no cambió; no se atribuye a QA#5 ni prueba frescura actual.

## Frescura y límites pendientes

A las **02:36 UTC del 20/10/2026, 23:36 ART del 19/10**, Turismo publicaba [Almundo Paquetes](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/almundo-paquetes.html), ausente del candidato capturado aproximadamente a las 17:55–18:00 UTC. El parser actual de categoría sí la descubre; el detalle normaliza seis cuotas con crédito Visa/Mastercard/Amex y revisión de fechas.

No se conoce cuándo apareció esa campaña. Es un delta de frescura pendiente, no una omisión del parser demostrada. No se insertó en el candidato congelado ni se ejecutó otra captura. Persisten las 29 categorías vacías, 74 URLs históricas ausentes, baseline aceptado con IDs duplicados y contradicciones oficiales. Ninguna baja ni migración de identidad está aprobada.

| Juicio | Resultado |
| --- | --- |
| Completitud de captura | UNKNOWN global; `catalog_complete=False` conservador; frescura pendiente. |
| Normalización | Estructura YES; muestra conforme; fidelidad comercial global UNKNOWN. |
| Reemplazo de snapshot | NO. |
| Revisión humana | YES, 350 flags y asuntos de cobertura/identidades/frescura. |
| Seguridad de desactivación | NO; nunca habilitada. |

PASS permite entregar a revisión humana; no aprueba producción. Los candidatos completos permanecen intactos en `backend/data/patagonia_review_20261019_raw.json` y `backend/data/patagonia_review_20261019_normalized.json`. El snapshot aceptado `patagonia_promotions.json` conserva SHA256 `3c1bc8669d1e0555d55d97647ccfb416b83cdb8d8df3814b5fb9ecdef9b8d83a`.

No se modificaron código, tests o payloads candidatos después del freeze de QA#5. Sólo se actualizó documentación/metadatos. No se repitieron los intentos de limpieza rechazados por revisión automática; los 27 remanentes propios y la razón exacta `automatic review blocked by policy` constan en [el registro de limpieza](patagonia-cleanup-20261019.json).
