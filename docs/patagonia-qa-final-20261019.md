# Banco Patagonia — historial QA#3/QA#4 (archivo histórico)

**Resultado vigente: READY_FOR_HUMAN_REVIEW_QA5_PASS.** El informe de cierre es [QA#5](patagonia-qa-5-20261019.md). Este archivo conserva observaciones históricas de QA#3/QA#4 anteriores a los fixes; QA011/QA012 están cerrados por QA#5 y sus observados de abajo no describen el export actual. Producción/reemplazo/desactivación siguen bloqueados. Se usó una de las dos rondas adicionales autorizadas y se detuvo el ciclo al obtener PASS.

Auditor: rol existente `promotion_qa`, independiente del desarrollo. Resumen del informe comunicado al coordinador el 19/10/2026. La restricción de sólo lectura fue instruccional; no existió sandbox técnicamente aislado de sólo lectura. No se realizaron escrituras de producción, sincronizaciones, desactivaciones ni cambios de código durante esta auditoría.

Se completaron cuatro auditorías, todas con FAIL. Un intento de la tercera se interrumpió antes del veredicto para descartar una regresión de desarrollo en encabezados Plan Sueldo; no cuenta como auditoría completada. El usuario pidió explícitamente «dale una vuelta mas», autorizando una cuarta auditoría fresca por encima del límite original de tres. QA#4 se reanudó tras un límite de uso, manteniendo la misma auditoría, cerró QA009/QA010 y encontró QA011/QA012. La nueva autorización explícita de hasta dos rondas adicionales permitió corregir esos hallazgos en desarrollo; QA#5 fresca los evaluó y cerró, con PASS de estructura y muestra.

Desarrollo tras QA#4: 109 tests passed, incluidas las 103 regresiones anteriores. Fechas se canonicalizan antes de deduplicar; Wine Fest tiene máximo de tickets por persona, consumo familiar y canal online positivo. Estos son resultados de desarrollo, no cierres independientes. Las observaciones siguientes describen el estado auditado por QA#4, anterior a esos fixes.

## QA#4: alcance y hallazgos abiertos

Muestreo independiente de 18 raws, 28 variantes y 22 URLs oficiales; no pretende auditar comercialmente los 350 registros completos. Recalculó 350→583, exactamente igual al export, sin errores estructurales. Selección de sólo lectura: **87 passed, 16 deselected, 1.52 s**; `python -B`, `pytest -q -s -p no:cacheprovider -p no:logging`, autoload deshabilitado, stub de persistencia y audit hook que rechaza escrituras. Los 16 tests de filesystem no se ejecutaron en QA. Los 103 passed de desarrollo son un resultado diferente.

### QA011 — ALTA: fecha incorrecta y revisión faltante en Grigorian

Fuente: [Grandes Intérpretes — Grigorian](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/ciclo-grandes-interpretes-teatro-colon-grigorian.html).

Resumen: `08/12/2026` y `8/12/2026`, la misma fecha del 8 de diciembre. Tabla: 7 de diciembre. `_extract_validity_value` deduplica representaciones textuales, encuentra dos strings, pierde la fecha del resumen y deja prevalecer la tabla. Tanto el export como el recálculo devuelven `valid_from=valid_to=2026-12-07`; `review_issues(raw)=[]`.

Esperado: deduplicar fechas canonicalizadas. Para 8 versus 7, ambas fechas `None` y revisión «Vigencias contradictorias»; si las distintas representaciones corresponden al mismo 8 sin conflicto, conservar el 8. Éste era el observado de QA#4; el candidato actual deja fechas desconocidas y revisión, cerrado por QA#5.

### QA012 — MEDIA: restricciones y máximo de tickets Wine Fest omitidos

Fuente: [Patagonia Wine Fest](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/patagonia-wine-fest.html).

Los términos completos conservan compra exclusiva por TuEntrada, consumo familiar y máximo de cuatro tickets por persona. `specific_conditions` omite esas restricciones, `limits=[]` y `online=None`.

Esperado: restricciones visibles, `online=True` y un límite `other` con quantity 4, scope person y descripción fiel; sin inventar moneda, período ni stock. Fue corregido en la ronda autorizada posterior y cerrado por QA#5.

Los casos QA001–QA010 y Carrefour Plan Sueldo quedaron cerrados en sus reproducciones concretas. El inventario de cobertura de QA#3 se conserva como evidencia anterior y no se atribuye al muestreo de QA#4.

## Evidencia conservada de QA#3

El auditor reconstruyó de forma independiente los cuatro storefronts y sus categorías, paginación y destacados: **101 categorías, 822 URLs exactamente coincidentes, sin URLs faltantes ni extra; 29 categorías vacías confirmadas**. Esto valida el recorrido del catálogo visible; la completitud global sigue desconocida por vacíos y antecedentes no resueltos.

Recalculó **350 registros raw → 583 variantes V2**, coincidentes con el export, sin errores estructurales. Contrastó **20 raws/32 variantes y 24 fichas oficiales** mediante muestreo. No auditó comercialmente los 350 registros completos.

Ejecutó una selección de sólo lectura: **83 passed, 16 deselected, 1.74 s**, sin temporales. Es distinta de la suite de desarrollo, que obtuvo **99 passed**. No se interpreta una suite verde como aceptación comercial.

QA001–QA008 y los casos concretos de Carrefour Plan Sueldo quedaron cerrados entonces. Los siguientes dos hallazgos históricos fueron posteriormente cerrados por QA#4:

## QA009 — ALTA: Mastercard omitida en La Agrícola Regional

Fuente: [La Agrícola Regional](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/la-agricola-regional-supermercados-regionales.html).

Los legales admiten crédito «VISA, AMEX Y MÁSTER». El normalizador reconoce `mastercard` pero no el alias oficial `MÁSTER`, por lo que conserva Visa y American Express y omite Mastercard tanto directa como con las billeteras aplicables, en las tres variantes.

Resultado esperado: las tres redes de crédito evidenciadas; porcentajes Clásica/Plus/Singular 15%/20%/30%, topes $10.000/$10.000/$15.000 mensuales por cuenta. La contradicción de fechas debe seguir marcada para revisión. No se autorizan otros tipos de tarjeta ni combinaciones no evidenciadas.

Éste es el hallazgo histórico de QA#3. La ronda posterior autorizada agregó el alias oficial Máster→Mastercard, probado con fixture real y tres segmentos; **QA#4 lo cerró en sus reproducciones concretas**.

## QA010 — MEDIA: restricciones importantes de Teatro Colón omitidas

Fuentes: [Filarmónica de Berlín](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/filarmonica-de-berlin-teatro-colon.html) y [Grandes Intérpretes — Grigorian](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/ciclo-grandes-interpretes-teatro-colon-grigorian.html).

El beneficio `other` conserva el 2x1 y los términos completos son fieles. Sin embargo, `specific_conditions` omite restricciones materiales: categorías Black/World Legend, países, asientos y distinción entre traslado/entradas; para Filarmónica, reserva con al menos dos semanas de anticipación. `payment_methods` queda vacío aunque Mastercard está evidenciada.

Resultado esperado: restricciones concisas visibles, con el plazo de reserva sólo donde esté publicado y con los alcances de cada servicio separados. Estructurar Mastercard sin inventar tipo de tarjeta ni stock global. El selector actual de restricciones es insuficiente.

Éste es el hallazgo histórico de QA#3. La ronda posterior autorizada conserva las restricciones visibles y Mastercard sin inventar issuer/card_type/rail ni stock global. Los plazos y asignaciones se restringen al alcance publicado en cada ficha; **QA#4 lo cerró en sus reproducciones concretas**.

## Cinco decisiones al finalizar QA#4, antes de los fixes para QA#5

| Decisión | Resultado |
| --- | --- |
| Completitud de captura | UNKNOWN global; `catalog_complete=False` conservador. Recorrido visible de 822 URLs confirmado. |
| Normalización | Estructura YES, fidelidad NO: QA011/QA012 abiertos y muestreo comercial limitado. |
| Reemplazo de snapshot | NO. Baseline inválido y revisión pendiente. |
| Revisión humana | YES; 349 registros señalados por el código, más el caso QA011 con revisión faltante y QA012. |
| Seguridad de desactivación | NO; nunca habilitada. |

Los archivos `backend/data/patagonia_review_20261019_raw.json` y `backend/data/patagonia_review_20261019_normalized.json` son **candidatos de revisión NO aprobados**, no reemplazos del snapshot aceptado ni entradas autorizadas para una sincronización. El detalle de conteos, discrepancias y paginación queda en `docs/patagonia-coverage-20261019.json`.
