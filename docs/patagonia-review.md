# Banco Patagonia: revisión de desarrollo, 19/10/2026

**Estado: READY_FOR_HUMAN_REVIEW_QA5_PASS; producción, reemplazo y desactivación bloqueados.** QA#5 independiente obtuvo PASS; QA011 y QA012 quedaron cerrados en sus casos reproducibles. El usuario autorizó hasta dos rondas adicionales tras QA#4 (máximo seis auditorías); se utilizó una y se detiene el ciclo: no hace falta QA#6. El PASS valida la estructura y la muestra examinada, no acredita fidelidad comercial global ni frescura completa del candidato. No se ejecutaron entry points de sincronización, SyncRunner real, Supabase, desactivaciones, workflows, push ni deploy. No se leyeron secretos. El snapshot aceptado se conserva. Informe independiente resumido, atribuido al auditor: [QA#5](patagonia-qa-5-20261019.md).

## Conexión

`verify=False` estaba activo en Patagonia. Se restauró verificación TLS con el almacén de confianza de httpx/certifi. Se observaron OpenSSL 3.5.7 y certifi 2026.07.22. Home, supermercados y las seis fichas de contraste respondieron HTTP 200 con verificación habilitada; home demoró 1,5 s y supermercados 1,3 s en probes puntuales. No había variables de proxy o de CA personalizada presentes (sólo se verificó presencia, sin leer/exponer valores).

No se dispone del transporte ni de trazas de las fallas históricas: **la causa de aquellos handshake timeouts no puede demostrarse**. Un timeout no demuestra un certificado inválido ni un bloqueo. La observación actual no garantiza disponibilidad futura.

El helper compartido imponía `DEFAULT_TIMEOUT` sobre el timeout del constructor. Patagonia utiliza ahora `_get()` local: connect 30 s, read/write/pool 45 s; hasta tres intentos con espera exponencial para timeouts, errores transitorios de red y 408/429/5xx permitidos. Certificados inválidos, hostnames incorrectos y 403/404 no se reintentan. No se utilizaron proxies, certificados alternativos, `verify=False` ni mecanismos de evasión. `trust_env=False` evita rutas implícitas por proxies del entorno. Se rechazan destinos fuera del host oficial y respuestas que abandonan HTTPS.

## Correcciones

- Se capturan navegación, carrusel de categorías y destacados: el carrusel contiene Farmacias y perfumerías y Transporte, ausentes en la navegación principal. Se recorren **general, Plus, Singular y ON**, con categorías y paginación independientes. Plus y Singular son storefronts reales, no filtros imaginados.
- La misma campaña SKU+slug entre general/Plus/Singular conserva todas sus fichas en `storefront_details`, con URL, categoría, segmento, texto y HTML. ON y diferentes slugs con SKU reutilizado permanecen separados. No se elimina contenido por deduplicación. La normalización compara texto de beneficio, legales, días y fechas por segmento; discrepancias entre storefronts retiran campos estructurados ambiguos y requieren revisión.
- Los SKUs repetidos se desambiguan mediante la ruta oficial estable, nunca el orden. El baseline conserva conocimiento de SKUs históricamente reutilizados para evitar perder el sufijo al desaparecer una URL. La introducción de esta corrección necesita revisión de identidades históricas antes de migrar datos.
- Los iconos no prueban combinaciones de tarjeta/billetera. Las alternativas estructuradas proceden de cláusulas de elegibilidad. Las excepciones de billeteras se aplican sólo al tipo de tarjeta especificado. QR/NFC son rails; una billetera mencionada en información o exclusiones no se agrega sola.
- Los canales requieren cláusulas positivas/negativas de compra; URLs informativas y palabras genéricas como comercio no prueban elegibilidad. La exclusión de portales de pago no equivale a exclusión de compra online. Contradicción/ausencia queda `None`.
- Fechas sin año permanecen desconocidas; ya no se inventa el año de captura. Tras QA011 se canonicalizan fechas antes de deduplicar representaciones textuales, preservando el conflicto resumen/tabla y la revisión obligatoria. QA#5 cerró el caso reproducible; no se afirma fidelidad completa de fechas en todo el catálogo. Los días excluidos no se incorporan como elegibles; ON Bares conserva días desconocidos porque resumen y legales discrepan.
- Porcentajes financieros y ejemplos no se interpretan como beneficio. Montos se parsean con Decimal; topes y compras mínimas siguen límites V2. Se reconocen topes por plazo de vigencia. Condiciones por segmento y exclusiones se muestran además del texto legal completo. No se alteraron modelos compartidos.
- Se bloquean categorías vacías, ciclos, páginas repetidas/duplicadas, totales incompatibles, detalles esenciales vacíos, baseline inválido, pérdida de IDs/categorías y candidatos modificados. `limit` nunca autoriza reemplazo. `scrape()` sólo retorna candidato; `save_raw_promotions()` exige el candidato validado y baseline sin cambios y usa temporal, fsync y os.replace. El CLI del scraper tampoco guarda automáticamente.

## Contraste oficial y fixtures

Capturados por HTTP con TLS verificado el 19/10/2026. Fixture `backend/tests/fixtures/patagonia/official_details_20261019.json`, con cuatro campañas y fichas adicionales Plus/Singular de Temple. Tras QA#1 se agregaron fixtures individuales `havanna_20261019.json` y `almundo-hoteles_20261019.json`: seis campañas, ocho fichas oficiales de contraste.

Tras QA#2 se descargaron seis fichas oficiales adicionales con TLS verificado y se guardaron como fixtures: Decathlon general y ON, Educación IT ON, CUI Idiomas ON, Changomas general y Plus. Los fixtures de contraste contienen así 14 fichas; no representan un muestreo completo del catálogo grande.

El cierre de la regresión de encabezados agregó el fixture Carrefour Plan Sueldo de general/Plus/Singular, extraído de la captura oficial verificada del día: **17 fichas de contraste en los fixtures finales**.

La ronda adicional autorizada agregó La Agrícola Regional y las dos experiencias del Teatro Colón, con todas sus fichas de storefront preservadas en el candidato: **24 fichas en el conjunto actual de fixtures**.

| Campaña y URL oficial | Hechos contrastados | Discrepancias preservadas |
| --- | --- | --- |
| [Carrefour](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/carrefour3.html) | Clásica 15%/$10.000; Plus 20%/$15.000; Singular 30%/$20.000. Mensual por cuenta, miércoles, compra física y online con entrega miércoles; débito Patagonia24 y crédito Visa/Mastercard/Amex; excepciones de billeteras y exclusiones de productos. Reintegros acreditados posteriormente. | Tabla de vigencia un día anterior al resumen/legal. |
| [Temple Bar](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/temple-bar.html), [Plus](https://ahorrosybeneficios.bancopatagonia.com.ar/plus/temple-bar.html), [Singular](https://ahorrosybeneficios.bancopatagonia.com.ar/singular/temple-bar.html) | Clásica/Plus 20%/$15.000, Singular 30%/$20.000; mensual por cuenta, todos los días, presencial/adheridos. Débito y crédito Visa; excepción MODO/Google/Apple sólo para crédito según cláusula. Fichas de cada storefront equivalentes para sus respectivos segmentos. | Tabla de vigencia un día anterior. Icono Visa débito no convierte en Visa cualquier débito permitido genéricamente por legales. |
| [Adidas](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/adidas2.html) | Plan sueldo; Clásica/Plus 20%/$12.500, Singular 30%/$20.000; tres cuotas sin interés, jueves y presencial. Tope por plazo de vigencia; débito y crédito Visa. | Tabla de vigencia un día anterior. El texto conjunto de débito y cuotas requiere lectura de condiciones; no se garantiza que débito financie cuotas. |
| [Bares ON](https://ahorrosybeneficios.bancopatagonia.com.ar/on/bares-on.html) | 30%; $10.000 por mes/cuenta; crédito Mastercard Patagonia, rubros bares/fast food. | Resumen viernes y sábados; legales exclusivamente viernes. Tabla de vigencia un día anterior. Se conserva `days=[]`, fechas `None` y revisión humana; no se elige uno arbitrariamente. |
| [Havanna](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/havanna.html) | 30%, tope $20.000 por mes. Exclusivamente Visa crédito mediante Google Pay o Apple Pay, con NFC indicado en resumen. | La excepción genérica de billeteras y cláusula de acreditación no amplían la elegibilidad a MODO ni tarjeta directa. |
| [Almundo Hoteles](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/almundo-hoteles.html) | Dos ofertas numeradas independientes: descuento 10%, tope $200.000 y stock 30 unidades para hoteles/actividades Bariloche con códigos HTLPATAGONIABRC/ACTPATAGONIABRC; financiación hasta 12 cuotas sin interés con crédito Visa/Amex/Mastercard Patagonia. | Dos variantes estables `:discount` y `:installments`, agrupadas. Cap/stock/códigos/Bariloche corresponden sólo al descuento; financiación no hereda esas restricciones. No se afirma acumulación entre ofertas independientes. |
| [Decathlon general](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/decathlon-octubre.html) y [ON](https://ahorrosybeneficios.bancopatagonia.com.ar/on/decathlon-octubre.html) | Seis cuotas sin interés con crédito Visa/Amex/Mastercard, viernes y sábados. | Fragmento residual «PARA COMPRAS CON TARJETAS DE DÉBITO.» permanece en términos, pero no prueba elegibilidad de débito para financiar. |
| [Educación IT ON](https://ahorrosybeneficios.bancopatagonia.com.ar/on/educacion-it.html) y [CUI ON](https://ahorrosybeneficios.bancopatagonia.com.ar/on/cui-idiomas.html) | Descuentos en carrito de 50% y 15%, respectivamente; CUI sobre precio Corporate. Cuenta abierta/activa, cupón antes del pago BENEFICIO_ON/PATAGONIA, válido una única vez durante la promoción. | «Sin tope de reintegro» es redacción de límites, no prueba de cashback; `Benefit.type=discount` y límite tipado de uso 1 por promoción. |
| [Changomas general](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/changomas3.html) y [Plus](https://ahorrosybeneficios.bancopatagonia.com.ar/plus/changomas3.html) | Clásica/Plus 15% y tope mensual $10.000 por cuenta; Singular 30%/$20.000, sábados y crédito. | Encabezados «Patagonia Clásica Y Plus»/«Patagonia Plus» son presentación equivalente, no contradicción económica. La discrepancia real de fechas sigue en revisión. |

El contraste detallado es muestra de riesgo, no auditoría manual de cada promoción del catálogo grande.

## Captura y cinco decisiones

La primera captura de **general+ON solamente** produjo 350 URLs/detalles y 350 IDs raw únicos; normalización local: 582 variantes/IDs únicos, cero fallos/exclusiones. **No representa el alcance final de cuatro storefronts.** Se detectaron 15 categorías vacías: cuatro general y once ON. Sus artefactos exploratorios temporales se retiran al cerrar la entrega; no se confunden con el candidato final.

Baseline aceptado: 398 registros, 374 IDs únicos; 74 URLs anteriores ausentes y 26 nuevas respecto de aquella candidata parcial. No se infiere baja legítima ni se reemplaza. Un baseline duplicado es inválido y bloquea aprobación, no se trata como inexistente.

**La captura final de los cuatro storefronts terminó:** 822 URLs y 822 detalles exitosos, cero errores HTTP/TLS/detalle. Distribución: general 243, Plus 230, Singular 242, ON 107. La agrupación preserva **350 campañas raw/350 IDs únicos y 472 fichas adicionales en `storefront_details`**. Que el total de campañas coincida con la captura parcial no implica que las 472 fichas adicionales fueran prescindibles: la comparación final señala **31 campañas con diferencias potenciales de texto, requisitos, beneficio o vigencia**, pendientes de interpretación humana; no equivale a 31 contradicciones económicas confirmadas.

Se recorrieron 101 categorías y se encontraron 29 vacías (general 5, Plus 6, Singular 6, ON 12), por lo que no se acredita completitud del catálogo aunque `ScrapeResult.complete=True` estructural. Se observaron cambios de navegación/categorías entre las dos capturas del día; no se inventa una explicación ni se consideran bajas justificadas.

Export actual con fixes de desarrollo hasta QA011/QA012: **350/350 raws válidos, 583 variantes/583 IDs únicos, cero errores de normalización y cero exclusiones**. Esto acredita validez estructural, no fidelidad completa. Hay **350 campañas en revisión por fechas** tras recuperar el conflicto de Grigorian, 31 con diferencias potenciales entre storefronts, nueve con días contradictorios, once con cuotas, siete con porcentajes y cuatro con topes contradictorios (categorías superpuestas). Los campos ambiguos quedan desconocidos/descriptivos y los textos completos se preservan.

Se inspeccionaron todos los encabezados de las 822 fichas: 24 formatos distintos/1.022 apariciones reconocidas y ninguno no reconocido de los prefijos oficiales inspeccionados. Una exportación intermedia de desarrollo produjo 50 alertas por omitir «Exclusivo» en encabezados de Plan Sueldo; se descartó antes de finalizar la tercera auditoría y **no es evidencia de nuevos conflictos oficiales**. El fix recuperó agrupaciones reales (fixture Carrefour Plan Sueldo, tres storefronts, 20/25/35% y topes 15.000/20.000/25.000), elimina 19 falsas alertas de esa exportación y conserva requisitos Plan Sueldo/Jubilados en la comparación. No confunde esos requisitos comerciales con los nombres de segmento.

El diagnóstico final compara todas las signatures y documenta muestras en los metadatos: 17 diferencias de cuerpo legal, once de texto de beneficio, nueve de candidatos de fecha y nueve de requisitos de encabezado, sobre alternativas por segmento y con solapamientos. Ejemplos de diferencias sólo de requisitos: Atalaya, Dandy, Kansas, Rapanui y Freddo muestran Plan Sueldo/Jubilados en el encabezado general y no en otro storefront. Se conserva esa incertidumbre para revisión, sin resolverla arbitrariamente.

Artefactos finales persistentes, explícitamente **candidatos NO aprobados**: `backend/data/patagonia_review_20261019_raw.json` y `backend/data/patagonia_review_20261019_normalized.json`. Se movieron desde `.tmp` después de finalizar QA, conservando sus hashes y sin sobrescribir destinos existentes. La captura reutilizó 350 detalles de hoy ya descargados con TLS verificado, conservando timestamp; descargó 472 detalles nuevos con cliente verificado. La evidencia compacta persistente es `docs/patagonia-coverage-20261019.json`: conteos, IDs, categorías/páginas, discrepancias y URLs históricas ausentes, sin duplicar catálogos completos.

SHA256 del snapshot aceptado, sin cambios: `3C1BC8669D1E0555D55D97647CCFB416B83CDB8D8DF3814B5FB9ECDEF9B8D83A`. Los nuevos candidatos no autorizan sincronización ni uso productivo.

Respecto al snapshot aceptado siguen faltando 74 URLs anteriores. Los diagnósticos por IDs son 101 IDs anteriores ausentes y 77 nuevos, afectados por la desambiguación de SKUs; no constituyen migración aprobada. El baseline con 398 registros/374 IDs únicos continúa inválido. No se sustituyó.

| Decisión | Estado en el handoff | Motivo |
| --- | --- | --- |
| Completitud de captura | UNKNOWN global, False conservador | QA#3 confirmó cuatro storefronts, 101 categorías y 822 URLs exactas; 29 categorías vacías y un delta posterior de frescura siguen pendientes. ScrapeResult.complete es sólo estructural. |
| Fidelidad/completitud de normalización | Estructura YES; muestra conforme QA#5 PASS; fidelidad global UNKNOWN | 350/350 raws producen 583 variantes válidas, exactamente iguales al recálculo independiente. QA011/QA012 cerrados; QA#5 muestreó 16 raws/25 variantes/19 fichas, no los 350 registros comerciales completos. |
| Autorización de reemplazo | False | Baseline inválido, cobertura no acreditada y contradicciones. No se reemplazó snapshot aceptado. |
| Necesidad de revisión | True | 350 registros marcados tras canonicalizar fechas; contradicciones, identidades previas y cobertura aún requieren revisión humana. |
| Seguridad de desactivación | False | Nunca habilitada; baseline no confiable y cobertura no aprobada. |

## Pruebas y reproducción

Desde `backend/`, con Python `.venv/Scripts/python`:

- **Última ejecución**, tras QA011/QA012 y la autorización de hasta seis auditorías: Patagonia + runner compartido, **109 passed, 0 failed, 1.78 s**. Incluye las 103 regresiones previas, fechas canonicalizadas y sus conflictos, Wine Fest y separación de tickets/stock/usos/montos.
- Ejecución anterior, antes de QA#4: Patagonia + runner compartido, **103 passed, 0 failed, 3.04 s**. Incluye las 99 regresiones previas y cuatro casos nuevos para Máster/Mastercard, ausencia de inferencias desde marketing/iconos y restricciones de las dos experiencias del Colón.
- Patagonia + runner compartido (`test_runner_validation.py`, `test_runner_deactivation.py`): **99 passed, 0 failed, 1.74 s** después de corregir QA#2 y la regresión detectada antes de finalizar QA#3. Incluye el fixture real Plan Sueldo con sus tres storefronts y una regresión que impide borrar un requisito comercial del encabezado como si fuera presentación. Los tests anteriores cubren crédito exclusivo de financiación, cupones/cuenta/uso único/Corporate, mecanismo de descuento en carrito, encabezados equivalentes/header-only, transitorios/TLS permanente, timeouts efectivos, medios combinados/exclusiones/exclusividad, canales nullable, porcentajes financieros, fechas desconocidas/contradicciones, segmentos, comparación de storefronts, stock y ofertas independientes, vacíos/ciclos/totales, IDs perdidos con igual conteo, baseline duplicado/ausente/modificado, `limit`, alteración de candidato y fallo de reemplazo atómico.
- Suite completa `tests`: **327 passed, 26 failed, 9.90 s** en una corrida anterior a los últimos tests Patagonia y a los fixes de QA. **No es una ejecución del estado final.** Los 26 fallos observados son `tests/scraping/test_banco_del_sol_scraper.py`, con carga acumulativa no verificable `[3,4]`/`[2,3]` y efectos relacionados. No se modificó Banco del Sol ni sus tests. Se repitió únicamente el conjunto afectado más runner compartido tras fixes locales, con el resultado 109/0 indicado arriba.
- El comando estándar `python -m pytest -q ... --basetemp=.tmp/<nuevo> -p no:cacheprovider` encontró **WinError 5** al crear/iterar carpetas temporales con `mkdir(mode=0700)`, incluso nombres nuevos. Se verificó sin modificar ACL existentes ni archivos compartidos: wrapper sólo en el proceso de test transforma ese modo a `0777` (comportamiento normal de mkdir de Windows antes del cambio de Python). No es código de aplicación ni cambio de permisos general del repositorio.

Wrapper reproducible, ajustando `args` al conjunto deseado:

```python
from pathlib import Path
import pytest
original = Path.mkdir
def mkdir(self, mode=0o777, parents=False, exist_ok=False):
    return original(self, mode=0o777 if mode == 0o700 else mode,
                    parents=parents, exist_ok=exist_ok)
Path.mkdir = mkdir
args = ['-q', 'tests/normalization/test_patagonia_normalizer.py',
        'tests/normalization/test_patagonia_official.py',
        'tests/scraping/test_patagonia_scraper.py',
        'tests/scraping/test_patagonia_safety.py',
        'tests/synchronization/test_runner_validation.py',
        'tests/synchronization/test_runner_deactivation.py',
        '--basetemp=.tmp/patagonia-check-<nuevo>', '-p', 'no:cacheprovider']
raise SystemExit(pytest.main(args))
```

## Archivos y riesgos

Modificados: scraper y normalizador Patagonia; helper exclusivamente Patagonia `scraping/sources/patagonia/text.py`; dos tests Patagonia existentes; nuevos `test_patagonia_official.py`, `test_patagonia_safety.py`, fixtures y este informe/metadatos. `synchronization/sync_patagonia.py` ya usa normalize_many y `allow_deactivation=False`; se inspeccionó y no necesitó cambios.

No hay garantía histórica entre runners efímeros de CI sin baseline durable. Se bloquea baseline ausente, por lo que el primer alta exige aceptación humana concreta. Raw y upserts no son una transacción conjunta; un fallo posterior de Supabase dejaría raw más nuevo que base y requiere retry/reconciliación. El import compartido de Supabase sigue siendo eager; no se afirma independencia de credenciales de entry points `--validate-only`.

## Ciclo independiente de QA

**QA#1: VERDICT FAIL**, con cuatro hallazgos reproducibles. El auditor informó 14 campañas/~23 variantes contrastadas y 69 tests passed/11 deselected en su selección. Sus resultados no son aprobación de producción.

| Hallazgo | Corrección de desarrollo y regresión |
| --- | --- |
| QA001 alta: Havanna añadía tarjeta directa/MODO y perdía NFC | Exclusividad de billeteras se conserva junto con tarjeta y rail, por encima de cláusulas genéricas de acreditación/excepción. Fixture oficial y regresión adversarial con Mastercard ajena: exactamente dos alternativas Visa crédito Google/Apple NFC. |
| QA002 alta: descripción legal sólo encabezado era aceptada | Se exige cuerpo sustancial tras encabezado, también en storefronts. Regresión de HTTP 200 con header-only: result incompleto, guard bloqueado y NamedTemporaryFile nunca alcanzado; baseline bytes preservados. |
| QA003 alta: Almundo omitía stock/códigos/Bariloche y mezclaba alcances | Split de ofertas numeradas con IDs estables por tipo; stock tipado 30 y cap sólo descuento, códigos/Bariloche visibles en condiciones/descripción, financiación independiente, legales completos en ambas variantes. |
| QA004 media: Adidas ADHERIDIOS no requería consulta de locales | Tolerancia explícita al error tipográfico oficial dentro del normalizador Patagonia. Ambas variantes requieren URL y nota accionable; sin editar helper compartido. |

**Fixes de desarrollo tras QA#1: 86 tests passed. QA#2 fresca: VERDICT FAIL.** QA#2 cerró QA001/QA003/QA004 y encontró QA002 incompleto y cuatro defectos adicionales; informó 74 tests passed/12 deselected en su selección de sólo lectura.

| Hallazgo de QA#2 | Última corrección de desarrollo y regresión |
| --- | --- |
| QA002 alta, parcial: headings sin «Legales» aún aceptados sin cuerpo | Helper source-local reconoce encabezados Patagonia con/sin prefijo y calificadores de segmento/plan. Se comparte sólo dentro de Patagonia para quitar presentación de validación y comparación. Headers reales Changomas y combinaciones de plan sin cuerpo bloquean primary y storefront sin alcanzar writer; bytes anteriores preservados. No elimina cláusulas comerciales que comienzan por Patagonia. |
| QA005 alta: Decathlon añadía débito a financiación | Se exige cláusula positiva de elegibilidad de beneficio. La acreditación sólo puede precisar una familia de tarjeta ya admitida, sin crear nuevos tipos/alternativas directas. Decathlon general/ON conserva seis cuotas exclusivamente crédito; fragmento residual íntegro en terms. |
| QA006 alta: cupones/cuenta/uso único ON omitidos | Se muestran cupón exacto, cuenta abierta/activa, aplicación antes del pago, precio Corporate y exclusiones; «única vez durante vigencia» produce usage_count quantity 1 period promotion. |
| QA007 media: descuento en carrito salía cashback por frase de tope | El mecanismo positivo de aplicación del descuento determina el tipo; una mención de «sin tope de reintegro» no transforma descuento en cashback. Helpers compartidos no modificados. |
| QA008 media: falso conflicto Changomas por distintos headings | Encabezados reconocidos se eliminan sólo de la comparación, preservándose en términos. General/Plus ahora coinciden por segmento; porcentajes/topes/pagos/sábados se mantienen. La contradicción de fechas continúa marcada. |

**Fixes anteriores: 99 tests passed. QA#3: VERDICT FAIL**, tercera auditoría completada y límite original de la skill. Un intento se interrumpió antes del veredicto para corregir la regresión de encabezados y descartar su exportación intermedia; no se cuenta como auditoría completada. La selección del auditor obtuvo **83 passed/16 deselected, 1.74 s**, distinta de la suite de desarrollo. No se atribuye PASS independiente a las pruebas de desarrollo.

QA final cerró los casos concretos QA001–QA008 y Carrefour Plan Sueldo. Confirmó de forma independiente las 822 URLs y las 29 categorías vacías, pero dejó dos defectos abiertos:

- **QA009 ALTA:** La Agrícola Regional publica crédito Visa/Amex/Máster; el alias «Máster» no se reconoce y se pierde Mastercard en las tres variantes, tanto directa como con billeteras admitidas. No se modifica el export para ocultar esta omisión.
- **QA010 MEDIA:** En Filarmónica de Berlín y Grandes Intérpretes — Grigorian, el 2x1 y los términos completos se conservan, pero faltan condiciones visibles de Black/World Legend, países, asientos y distinción traslado/entradas; sólo Filarmónica requiere reserva con al menos dos semanas. Mastercard queda sin estructurar. No se inventan tipo de tarjeta ni stock global.

El resultado independiente de QA#3, alcance, URLs, esperados/observados y limitaciones están en `docs/patagonia-qa-final-20261019.md`. Auditor: rol `promotion_qa`; sólo lectura instruccional, sin aislamiento técnico de permisos. El cierre original por tres auditorías fue posteriormente ampliado por instrucción explícita del usuario; el nuevo máximo autorizado es **cuatro auditorías completas en ese momento**, posteriormente ampliado hasta seis por el usuario.

### Ronda adicional autorizada por el usuario

Sin cambiar scraper, modelos compartidos ni otras fuentes, se agregó el alias oficial Máster→Mastercard sólo en listas de elegibilidad de tarjetas. El fixture de La Agrícola Regional conserva las tres variantes, sólo crédito, 15/20/30%, topes 10.000/10.000/15.000 mensuales por cuenta, medios directos y billeteras expresamente admitidas; las fechas contradictorias continúan bajo revisión.

Las dos experiencias del Teatro Colón conservan su 2x1 `other` y términos íntegros. Se muestran Black/World Legend, registro Priceless, países, asignaciones de asientos/palcos, entradas digitales, traslado y distinción de visitas correspondientes a otros recitales. La reserva de al menos dos semanas se conserva **sólo en Filarmónica**. Mastercard se estructura como requisito de red, con issuer/card_type/rail desconocidos cuando no están publicados. No se convierten las asignaciones de asientos o lugares por visita en stock global.

Los tres fixtures nuevos provienen de la captura oficial verificada del día. Suite afectada más runner compartido: **103 passed, 0 failed, 3.04 s**, incluyendo las 99 regresiones anteriores. Export completo recalculado y verificado: **350 raws válidos → 583 variantes/583 IDs únicos, cero errores**; 349 registros con revisión y 31 diferencias potenciales entre storefronts, sin cambios en esos conteos. Los candidatos continúan explícitamente NO aprobados y el snapshot aceptado permanece intacto.

### QA#4: resultado histórico y siguientes correcciones

**VERDICT: FAIL.** Auditor `promotion_qa`, sólo lectura instruccional sin aislamiento técnico de permisos. La sesión se reanudó tras un límite de uso; fue la misma cuarta auditoría, no otra adicional. QA009 y QA010 quedaron cerrados en sus reproducciones concretas. La cuarta auditoría muestreó 18 raws/28 variantes/22 URLs oficiales y confirmó recalculando 350→583, idéntico al export entonces disponible, sin errores estructurales. No atribuye a QA#4 el barrido de cobertura de QA#3 ni pretende auditar comercialmente los 350 registros.

La selección de QA#4 obtuvo **87 passed, 16 deselected, 1.52 s**, con `python -B`, `pytest -q -s -p no:cacheprovider -p no:logging`, autoload deshabilitado, persistencia simulada y audit hook que rechaza escrituras; no ejecutó los 16 tests de filesystem. Es un resultado distinto de los 103 passed de desarrollo.

- **QA011 ALTA — Grigorian, observado por QA#4:** el resumen publica `08/12/2026` y `8/12/2026`, ambas el 8 de diciembre. El parser deduplicaba strings sin canonicalizar fechas, descartaba ese resumen y elegía la tabla del 7 de diciembre, con revisión vacía. La corrección posterior canonicaliza por fecha real; ante 8 versus 7 deja ambas fechas `None` y revisión de vigencias contradictorias. Si todas las fuentes coinciden en el 8, conserva el 8. Cerrado por QA#5 en el caso reproducible.
- **QA012 MEDIA — Patagonia Wine Fest, observado por QA#4:** se omitían condiciones visibles de consumo familiar y máximo de cuatro tickets por persona, límite estructurado y canal online. La corrección posterior preserva TuEntrada/consumo familiar/máximo, detecta la compra online positiva y emite límite `other`, quantity 4, scope person, con descripción y sin moneda, periodicidad ni stock global. Cerrado por QA#5 en el caso reproducible.

### Ronda QA#5 autorizada por el usuario

Se implementaron y ejecutaron regresiones de fechas con/sin cero inicial y distintos separadores, coincidencia sin conflicto y revisión obligatoria ante resumen/tabla contradictorios. Un scan de los 350 raws y 822 resúmenes identificó exactamente las dos fichas general/Singular de Grigorian con representaciones equivalentes afectadas; no se hardcodearon fechas de la campaña.

Wine Fest tiene fixture oficial nuevo obtenido con TLS verificado. El máximo de tickets se obtiene del número publicado y se distingue de stock, cantidad de usos y topes monetarios. El canal requiere una cláusula positiva de adquisición, conservando `None` ante una URL informativa y respetando exclusiones negativas. Suite afectada más runner compartido: **109 passed, 0 failed, 1.78 s**, incluyendo las 103 regresiones anteriores. Export completo recalculado: **350 raws→583 variantes**, sin errores; 350 revisiones y 31 diferencias potenciales. Se comprobaron fechas nulas/revisión de Grigorian, canal y límite Wine Fest, Decimales JSON como strings y ausencia de campos planos legacy. QA#5 fresca obtuvo PASS en estructura y muestra; los candidatos siguen NO aprobados para reemplazo o producción.

Estos cambios **no están preparados para producción** mientras persistan contradicciones oficiales, cobertura/identidades pendientes y el delta de frescura. Los candidatos completos y la evidencia compacta se preservan para revisión humana; el snapshot aceptado se mantiene sin cambios.

### Limpieza y archivos entregables

Se preservan los candidatos completos no aprobados en `backend/data/patagonia_review_20261019_raw.json` y `backend/data/patagonia_review_20261019_normalized.json`; informes en este archivo, `docs/patagonia-qa-final-20261019.md` y `docs/patagonia-coverage-20261019.json`. Los hashes están en los metadatos. Los fixes y exports posteriores a QA#4 fueron expresamente autorizados por el usuario y quedaron congelados antes de QA#5. Tras su PASS sólo se actualiza documentación/metadatos.

La eliminación de artefactos temporales propios fue rechazada **antes de ejecutarse** por la revisión automática, tanto con rutas verificadas y recursión acotada como con una alternativa de archivos absolutos explícitos sin recursión. Razón devuelta: `automatic review blocked by policy`; no se atribuye esta denegación a ACL ni se cambiaron permisos. Se detuvieron los intentos y no se repitieron en la ronda adicional. Quedan 27 rutas propias en `backend/.tmp`, incluidas las nuevas carpetas necesarias para regresiones, enumeradas exactamente en `docs/patagonia-cleanup-20261019.json`; no se tocaron artefactos ajenos. Esta limitación de limpieza es distinta de los WinError 5 observados antes al ejecutar pytest.

## Cierre independiente QA#5: PASS con revisión humana pendiente

Auditor `promotion_qa`, independiente del desarrollo; sólo lectura instruccional, sin aislamiento técnico. Desarrollo publica este resumen del resultado comunicado al coordinador; no se atribuye la auditoría. QA#5 examinó **16 raws, 25 variantes y 19 fichas oficiales**, más Almundo Paquetes como exploración adicional. Recalculó **350→583 exactamente iguales al export, cero errores/exclusiones**, Decimales como strings y sin campos planos legacy. Los 350 flags de revisión se conservan. QA011/QA012 cerrados; sin reapertura confirmada de QA001–QA010.

QA#5 ejecutó **93 passed, 16 deselected, 0 failed**, con `python -B`, `pytest -q -p no:cacheprovider`, autoload deshabilitado y persistencia simulada antes de importar. Inspeccionó los 16 tests de filesystem sin ejecutarlos y verificó seis escenarios históricos en memoria, incluidos desaparición 65→56, sustitución con total igual/mayor y baseline ausente rechazados; adiciones/actualizaciones admitidas; desactivación siempre bloqueada. Es distinto del resultado de desarrollo **109 passed**.

**Frescura pendiente, no defecto demostrado:** a las 02:36 UTC del 20/10 (23:36 ART del 19/10), Turismo publicaba [Almundo Paquetes](https://ahorrosybeneficios.bancopatagonia.com.ar/ahorrosybeneficios/almundo-paquetes.html), ausente de la captura de aproximadamente 17:55–18:00 UTC. El parser actual de categoría sí la descubre y el detalle normaliza seis cuotas con crédito Visa/Mastercard/Amex, con revisión de fechas. No hay evidencia de cuándo apareció: no se atribuye a una omisión del parser. No se insertó retroactivamente en el candidato ni se hizo una nueva captura. El barrido 101/822/29 vacías corresponde a QA#3, no QA#5.

Trazabilidad raw: CC9C0B4068DD5C41AB9C1E153EF4AF51B43D32C5FCC59FDC7F0CFD333162C00D→D7A49A114EDF237A214C4F4DC71CE3253E61F632FCEAEB508A71B6233ACEB998 cambia exclusivamente por añadir `review_reasons` al raw Grigorian (+124 bytes), recuperable exactamente al retirar esa clave en memoria y conservar UTF-8/indentación/CRLF. No cambiaron payloads fuente ni timestamps. El fixture nuevo Wine Fest, descargado con TLS a 2026-10-20T02:24:04.649839+00:00 (19/10 ART), no sustituyó el raw candidato, que mantiene 2026-10-19T17:57:58.893872+00:00.

Los candidatos se entregan para revisión humana. No hay autorización de reemplazo, sincronización ni desactivación. No se repitieron los intentos de limpieza bloqueados por la revisión automática.
