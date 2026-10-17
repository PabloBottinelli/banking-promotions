# Santander — integración V2 y recuperación

**Estado final: READY_FOR_HUMAN_REVIEW. QA #8: PASS. Ocho auditorías completadas (siete FAIL históricos y un PASS); QA-001–013 cerrados, sin hallazgos de implementación abiertos. Se detiene el ciclo y no se usa QA #9. Sin aprobación de producción.**

## Fuente y resultados

Alcance: https://www.santander.com.ar/personas/beneficios#/results?category-code=ALL, catálogo público completo sin filtros de provincia/día/segmento. No se afirma incluir otros catálogos externos como canjes SuperClub+. Captura oficial original iniciada el **15/10/2026 18:37:52 ART** (21:37:52 UTC), terminada en esa sesión. La recuperación posterior usa esa captura conservada, sin atribuirle una fecha de descarga nueva.

La página Next.js carga `/api/microfrontBeneficios` → `/microfront-benefits`. El bundle oficial omite `categories` cuando ALL está activo y consulta `/bff-benefits/brands`, `/brands/{brandId}` y `/publications/{publicationId}?brandId={brandId}`. Son endpoints públicos anónimos. El scraper usa el cliente/reintentos compartidos, TLS verificado, dos trabajadores y timestamps UTC.

Cobertura: **589 marcas**, verificación independiente con límite 100: 100/100/100/100/100/89/0; límite 73: 73/73/73/73/73/73/73/73/5/0. Totales estables y conjuntos de IDs iguales; todos los programas y detalles recuperados. `totalItems` de `/brands/{id}` no cuenta publicaciones: Café Martínez devuelve 1 aunque contiene 2; se enumeran todos sus `items`.

**1.208 ocurrencias oficiales → 1.206 pares únicos marca/publicación → 2.255 filas V2 actuales**, todos sus IDs únicos; **182 grupos**, **16 etapas de preventa**. Cero exclusiones y errores de normalización. La reducción desde 2.257 corresponde a las dos variantes no crédito contradichas por legales, documentadas más abajo. Paseo del Jockey repite exactamente 7757 y 7756: una fila por identidad, con `program_occurrences=2`; contenidos duplicados distintos bloquean captura.

Componentes actuales: **2.197 cashback, 1.082 cuotas, 8 descuentos directos y 17 other documentados** (16 preventas y un 2x1). El catálogo observado publica Ahorro/Solo Cuotas/Ahorro y Cuotas; no se encontraron otros tipos explícitos dentro de este alcance. `other` no encubre parsers fallidos.

## Artefactos y contrato

- `scraping/sources/santander/scraper.py`: candidato sin escritura durante scrape, cobertura, guard de snapshot y reemplazo atómico.
- `normalization/sources/santander.py`: V2 fiel a publicaciones, variantes de crédito/no crédito y preventa.
- `synchronization/sync_santander.py`: entrada fina, no ejecutada; desactivación deshabilitada.
- `normalization/export_json.py`: registro Santander.
- `tests/{scraping,normalization,synchronization}/test_santander_*.py`, 38 extractos oficiales pequeños en `tests/fixtures/santander/`.
- Datos persistentes locales ignorados por Git: `data/santander_promotions.json` ≈344 MB (detalle y establecimientos completos); `data/normalized/santander_promotions.json` ≈9,8 MB; cobertura compacta `data/santander_coverage.json` sin duplicar respuestas completas.

IDs `marca:publicación` y sufijos semánticos `:credit`, `:non-credit`, `:presale`; agrupación por campaña oficial. Financiación solo para crédito; beneficios compatibles se conservan juntos. Preventa separada de la financiación general, con sus tarjetas/stock/fechas explícitas; horarios y duración permanecen en condiciones porque V2 representa fechas, no horas. No se inventan valores económicos ni fechas.

Tarjetas desde combinaciones reales `cards[]`, incluido tipo R/Recargable como prepaid. QR transporte PCT no se convierte en tarjetas. QR/NFC son rails, no canales; App YPF/Cabify/MODO no prueban online. Las listas explícitas de billeteras se aplican a las combinaciones de tarjetas a las que el texto las refiere, sin combinar redes/tipos independientes. Contexto de Cabify permanece en `raw_name` y condiciones.

Raw conserva legales completos y listas de establecimientos. Normalizado agrega URL oficial de detalle, flag y nota accionable para consultar adheridos. `terms` retiene HTML legal original; `specific_conditions` conserva restricciones, segmentos, planes, horarios, códigos, exclusiones, productos y etapas. No se modelan establecimientos individuales ni columnas específicas de banco.

## Recuperación y correcciones previas al primer veredicto

Al reanudar, Git estaba limpio y habían desaparecido implementación, tests, fixtures y reporte; sobrevivían raw/cobertura ignorados y bytecode. No se conoce la causa. La limpieza de desarrollo anterior solo apuntó a directorios explícitos bajo `backend/.tmp/`, con validación del padre absoluto; no apuntó a código, tests ni documentos. No hay tarea de limpieza en ejecución.

Se reconstruyeron scraper, normalizador, entrada, registro, tests, fixtures y este reporte usando contexto retenido y captura oficial superviviente; no se hizo reset de cambios de terceros ni nueva captura live. Durante recuperación se reprodujeron y corrigieron observaciones preliminares de QA **antes de que emitiera un veredicto**:

1. Código de tarjeta `R` ahora mapea prepaid; frase «compras mayor o iguales a $15.000» genera mínimo de compra sin fallback.
2. Shopping Days 1782:8009 conserva las opciones legales explícitas **3 y 6** cuotas, no solo máximo 6.
3. Desayunos con MODO 740:7707 conserva horario 06–11, 10 transacciones mensuales y tope mensual publicado. Conflicto API $2.000/legal $1.000 por transacción se expone; el cap transaccional queda con `amount=None`, no un importe cierto.
4. Despegar 146:8000/8001 conserva stock monetario de **ARS 15.400.000** como límite tipo stock, separado del tope del beneficio; un descuento por dispositivo y por reserva produce límites de usos independientes.
5. Fabric Sushi, Nutrican, Amici y Cabify conservan alternativas explícitas MODO/Google Pay/Apple Pay incluso con `paymentType=N/null`; sin inventar NFC para pagos dentro de Cabify.

Estas correcciones son desarrollo, no aprobación independiente. Los candidatos de Carrefour se convirtieron en hallazgos formales QA-001/002; sus correcciones posteriores se documentan por separado más abajo.

## Contradicciones y límites pendientes

**192 publicaciones** contienen diferencias entre fechas legales completas y ventanas del API (375 filas V2). Se prioriza la cláusula legal explícita y se advierte en condiciones; ejemplo Café Martínez 7558: API 28/10 frente a legal 31/10. arteba 7934 anuncia subtítulo sin tope pero importe/legal ARS8.400: cap y advertencia conservados. Desayunos exhibe el conflicto de cap descrito arriba. Cobertura enumera IDs en `semantic_review`, con `production_approval=False`. No se afirma haber resuelto contradicciones del banco.

Precios de membresía, geografía, exclusiones por producto, acumulaciones, horarios y stock legal malformado como «105.00 tickets» no se convierten arbitrariamente en valores estructurados: permanecen en textos y raw. No se revisaron manualmente 2.257 filas. Muestra de desarrollo: Café Martínez, Cinépolis, Margarita, Humbe, Transporte, arteba, Paseo del Jockey, Coto, YPF, Shopping Days, Desayunos, Despegar, Fabric, Nutrican, Amici y Cabify. QA debe revisar de forma independiente categorías/segmentos, topes compartidos y contradicciones adicionales.

## Cinco juicios separados

| Juicio | Estado y límite |
|---|---|
| `catalog_complete` | TRUE para captura ALL original: dos particiones, terminales vacíos, IDs iguales y detalles válidos. |
| `normalization_complete` | TRUE estructural: todos los raw producen variantes V2 únicas; fidelidad pendiente de QA, con contradicciones declaradas. |
| `snapshot_replace_allowed` | TRUE para captura original fiel; no certifica hechos comerciales. |
| `requires_review` | FALSE en aceptación de captura local original; revisión comercial pendiente declarada en `semantic_review`, sin producción aprobada. |
| `safe_to_deactivate` | FALSE: sin autorización ni baseline histórico durable externo. |

`ScrapeResult.complete` no prueba por sí solo ninguno de los demás juicios. Primera captura sin baseline local; eso no prueba ausencia de historia en Supabase/CI. Con baseline local válido, el guard bloquea pérdidas/reemplazos de IDs incluso con igual total. Revalida flags, contenido, identidad y digest antes de guardar. Raw y Supabase no forman una transacción: si falla upsert, raw puede adelantarse; tests simulan fallo/reintento y omisión de desactivación.

## Validación ejecutada

Primera sesión: 252 tests pasaron (46 nuevos Santander). Tras reconstrucción y correcciones preliminares: **261 passed in 12.20s**, incluidos **55 tests Santander**. Desde backend, `.venv/Scripts/python`, bootstrap aislado: evita `dotenv.load_dotenv`, fija URL/key ficticias de test y llama `pytest.main(['-q','tests','--basetemp=.tmp/pytest-santander-recovered','-p','no:cacheprovider'])`. Solo durante tests ajusta `os.mkdir` a modo normal 0777 para evitar el problema Windows/Python3.14 con carpetas 0700 inaccesibles al sandbox. No cambia permisos persistentes ni accede a secretos.

Tests cubren extracción completa/parcial, blancos dentro de HTTP200, identidad/duplicados, duplicados idénticos vs conflictivos, desapariciones/reemplazos históricos, adiciones/actualizaciones, tampering, fallo atómico con bytes previos intactos, cero/duplicadas variantes, fuente inválida, flags/rechazo de guardado, validate-only, upserts cortos/fallidos/reintento y todas las compuertas de desactivación. Los tests de runner usan solamente repositorios falsos y temporales.

Export regenerado: `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m normalization.export_json --source santander` → **1.206 raw, 2.257 V2**, éxito. Raw original no modificado. Código fuente inspeccionado como UTF-8. Modelos compartidos sin cambios ni discrepancia de contrato detectada.

No se ejecutó `sync_*` ni `SyncRunner.run()` fuera de pruebas enteramente simuladas; no hubo Supabase, Actions, migraciones, pushes ni despliegues. Aunque la entrada importa runner de forma diferida, runner compartido importa repositorio/configuración de Supabase al cargar: no se afirma que validate-only sea independiente de credenciales.

Primera auditoría completada: FAIL. Correcciones aplicadas; estado congelado para una segunda auditoría nueva, sin aceptación independiente todavía.

## Auditoría independiente #1 y correcciones formales

**QA #1: VERDICT FAIL.** El auditor verificó de forma independiente la unión de **18 categorías y 4 filtros exclusivos = 589 marcas ALL**, y examinó **32 publicaciones de 27 marcas** mediante muestreo de riesgo. No auditó live cada uno de los 1.206 detalles. QA observó **27 tests pasados y 28 errores de entorno** `tmp_path`/WinError5; estos errores no son defectos funcionales ni tests aprobados. Su solo lectura se impuso por instrucciones, **sin sandbox técnico independiente**.

Hallazgos formales y corrección posterior, separados de los ajustes preliminares de recuperación:

- **QA-001 HIGH:** Carrefour 86:8006, 87:8005 y 3721:8003 publican «Tope compartido con las demás promociones en Carrefour», pero la salida vinculaba cada cap a una campaña diferente. Ahora el grupo común **santander:shared-cap:carrefour** se deriva de esa frase explícita; mantiene alcance por cuenta e importe/frecuencia publicados. La identidad no depende de títulos, orden ni IDs de campaña. Sin evidencia explícita no se infiere compartir por similitud de nombres.
- **QA-002 MED:** esas tres publicaciones perdían «No aplica a compras online», presente en `additionalText`. Se conserva en `specific_conditions` aunque no aparezca en el legal; no se infiere canal físico de la exclusión. Permanecen aviso de cap compartido y compra mínima.
- **QA-003 MED:** Coto 131:8075 describe «desde el 26 de febrero de 2026 hasta el 15 de octubre de 2026»; el reconciliador anterior solo reconocía fechas con barras. Ahora reconoce el intervalo completo con meses españoles, usa **26/02/2026–15/10/2026** por prioridad legal y advierte la diferencia con la ventana del API.

Añadidos tres extractos oficiales de Carrefour y **cinco regresiones** específicas. Full suite posterior: **266 passed in 10.69s**, incluidos **60 tests Santander**, cero fallos/errores. Export posterior: **1.206 raw → 2.257 V2**, IDs únicos, sin modificar raw original. Cobertura actualizada con 192 publicaciones/375 variantes con divergencia de fechas, QA #1 y correcciones pendientes de auditoría nueva. Desactivación FALSE; aceptación de captura local y revisión semántica pendiente continúan separadas. Sin sincronizaciones ni escrituras de producción.

### Comando reproducible de tests sin .env ni secretos

Ejecutar en PowerShell desde `backend/`. Es el bootstrap del comando efectivamente ejecutado; `mkdir` se adapta solo dentro del proceso de tests para evitar el modo Windows 0700 inaccesible al sandbox:

```powershell
@'
import os, sys
sys.path.insert(0, os.getcwd())
original_mkdir = os.mkdir
def mkdir(path, mode=0o777, *, dir_fd=None):
    return original_mkdir(path, 0o777, dir_fd=dir_fd)
os.mkdir = mkdir
import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ['SUPABASE_URL'] = 'https://tests.invalid'
os.environ['SUPABASE_SECRET_KEY'] = 'test-placeholder'
import pytest
raise SystemExit(pytest.main([
    '-q', 'tests', '--basetemp=.tmp/pytest-santander-recovered',
    '-p', 'no:cacheprovider'
]))
'@ | .venv/Scripts/python -
```

Export local reproducible (sin Supabase):

```powershell
$env:PYTHONIOENCODING='utf-8'
.venv/Scripts/python -m normalization.export_json --source santander
```

Esta versión se remitió a **QA #2 nueva**, cuyo resultado y correcciones posteriores figuran abajo. QA #1 permanece FAIL históricamente; el desarrollador no emite PASS independiente.

## Auditoría independiente #2 y versión para auditoría final #3

**QA #2: VERDICT FAIL.** Nueva auditoría de solo lectura por instrucciones, sin aislamiento técnico independiente. Verificó el catálogo ALL de 589 marcas y muestreó **41 publicaciones de 24 marcas**. Ejecutó la suite con el bootstrap documentado: **266 passed in 10.39s**. Verificó salida estructural **1.206 → 2.257**, sin confundirla con fidelidad semántica ni auditoría live de cada detalle.

Hallazgos formales y correcciones posteriores, preservando QA-001/002/003:

- **QA-004 MED:** Top Gnc 3194:7956 usa «incluidos también los pagos realizados con»; 118 publicaciones tienen esa forma. Otras 14, incluida 47 Street 2:7955, publican App Santander junto con MODO/Google Pay/Apple Pay; dos presentan la variante textual «los pagos los realizados». El parser ahora acepta estas cláusulas positivas y mapea App Santander. Solo aplica la lista a las combinaciones de tarjetas verificadas. Conserva financiación solo con crédito, sin inferir NFC ni compras online.
- **QA-005 HIGH:** Supermercados de Córdoba 3492:7598 publica en legales VISA, pero `cards[]` incluye MASTER/AMEX. La salida ya no afirma esas redes contradictorias: muestra VISA y una advertencia visible con las redes discordantes y la consulta requerida a Santander. El raw API permanece intacto. La conciliación usa cláusulas positivas de elegibilidad de tarjetas, antes de ejemplos y fuera de exclusiones; encontró ocho publicaciones con discrepancias de redes, cuyos IDs quedan en cobertura. No se infiere aceptación de una red por su aparición en ejemplos o negativos.
- **QA-006 MED:** Shopping Days 1782:8009 omitía la exclusión de plataformas de pagos/agregadores; Coto 131:8075 omitía electrodomésticos/neumáticos/rodados y otras categorías. Ahora `specific_conditions` conserva cláusulas «no válido/no incluye». Las listas extensas de marcas añaden una instrucción para consultar el listado completo en los términos oficiales, que permanecen íntegros. Las exclusiones no crean canales positivos.

Añadidos tres extractos oficiales (Top Gnc, 47 Street y supermercados cordobeses) y **ocho casos de regresión**: dos de billeteras, uno de redes, dos de restricciones oficiales y tres negativos de canales. El primer run encontró un error en la expectativa nueva de test: 47 Street publica descuento para crédito y débito sin financiación; se corrigió esa expectativa contra el texto oficial. Resultado final: **274 passed in 10.63s**, incluidos **68 tests Santander**, cero fallos/errores. El comando reproducible es el mismo bootstrap documentado arriba.

Export final local: **1.206 raw → 2.257 V2**, todos los IDs únicos, cero exclusiones; raw original sin cambios. Beneficios siguen siendo 2.197 cashback, 1.082 cuotas, 10 descuentos y 17 otros documentados. No hubo sync, Supabase, `.env`, Actions, migraciones ni commits.

Los cinco juicios independientes de QA #2 deben leerse con precisión: **cobertura live de todos los detalles UNKNOWN** por muestreo; **fidelidad de normalización NO** en la versión auditada, por estos defectos; aceptación de snapshot es el juicio de **captura local** expuesto en metadata, no aprobación semántica; **requires_review semántico YES**, aunque el flag `requires_review` de la captura original sea FALSE; **safe_to_deactivate NO**. Cobertura guarda ambos niveles explícitos, sin convertir recuentos estructurales ni tests verdes en aceptación.

La versión anterior se congeló para **QA #3 nueva y final**. Su resultado definitivo se registra a continuación; QA #1 y #2 permanecen FAIL históricamente.

## Auditoría independiente #3 — resultado final

**VERDICT FAIL; estado NEEDS_HUMAN_REVIEW. Tres auditorías completadas, ocho hallazgos formales en total: seis cerrados y dos abiertos.** QA #3 verificó de forma independiente el cierre de **QA-001 a QA-006**. Encontró los dos defectos siguientes, que **no se corrigieron** después de la tercera auditoría. Se detiene el ciclo automático; no se solicita una cuarta auditoría ni se aprueba producción.

| Hallazgo abierto | Evidencia y reproducción | Resultado observado y corrección futura necesaria |
|---|---|---|
| **QA-007 MED — tope mensual contradictorio** | PedidosYa `393:7950`, [detalle oficial](https://www.santander.com.ar/bff-benefits/publications/7950?brandId=393). API `topAmount=15000` y descripción mensual $15.000; legal: «Tope: $25.000 por mes»; ejemplo: $15.000. Seleccionar ese raw y ejecutar `SantanderNormalizer().normalize_many(raw)`; inspeccionar `limits` y `specific_conditions`. | La salida afirma ARS15.000 mensuales y concatena referencias discordantes sin advertencia explícita. Requiere conciliar genéricamente topes mensuales o representar el importe como incierto, conservando ambos datos y aviso de revisión. No basta priorizar el ejemplo ni un valor del API silenciosamente. |
| **QA-008 MED — tarjeta de etapa de preventa** | Margarita `1127:7560:presale`, [detalle oficial](https://www.santander.com.ar/bff-benefits/publications/7560?brandId=1127). Cláusula de preventa: tarjetas Santander crédito y débito; `cards[]` general incluye VISA Recargable. Normalizar el raw `1127:7560`, seleccionar la variante `:presale` e inspeccionar `payment_methods`. | La etapa hereda prepaid de la lista general aunque su cláusula solo admite crédito/débito. Requiere filtrar tipos de tarjeta por etapa; preservar raw general sin extenderlo a la preventa. La preventa publicada fue 03–04/08/2026: eso reduce impacto inmediato, pero no elimina el defecto. |

QA #3 examinó **43 publicaciones live de 33 marcas**, con solo lectura por instrucciones y **sin sandbox técnico independiente**. Ejecutó la suite con el bootstrap documentado: **274 passed in 10.36s**; verificó **1.206 raw → 2.257 V2**, IDs únicos. Estos resultados estructurales no anulan los defectos semánticos abiertos. No se volvió a ejecutar código, tests, scraper ni export para este cierre documental.

La consulta live del **16/10/2026 entre 16:25 y 16:32 UTC** encontró **588 marcas**, frente a 589 en el snapshot original del 15/10/2026 21:37 UTC. Las particiones 100 y 73 devolvieron el mismo conjunto y terminales vacíos; faltaba la marca `425` respecto del snapshot histórico. Es un cambio temporal de fuente, **no un defecto probado de la captura anterior ni autorización para remover filas o reemplazar snapshots**. Se conservó el raw original; no hubo nueva captura persistida ni export regenerado.

Juicios finales separados:

- **Catálogo histórico completo a nivel de todos los detalles: UNKNOWN para QA**, porque los detalles se revisaron por muestreo; la cobertura estructural original y el catálogo de marcas verificado no sustituyen esa comprobación.
- **Normalización: YES estructural / NO en fidelidad semántica**, por QA-007 y QA-008 abiertos.
- **Reemplazo de snapshot: TRUE histórico en metadata de captura**, basado en captura local y sin baseline durable externo; no significa aprobación comercial ni de producción.
- **Revisión requerida: YES semántico**. El `requires_review=False` original corresponde exclusivamente a la aceptación de captura; `semantic_review.requires_review=True` y estado NEEDS_HUMAN_REVIEW describen la situación final.
- **Desactivación segura: NO**. Sin autorización, evidencia de baseline durable ni resolución semántica; el cambio live de 589 a 588 no habilita bajas.

La metadata conserva estos niveles, las tres auditorías y los dos hallazgos abiertos. **No se modificaron normalizador, scraper, tests, raw ni export tras el veredicto final**: este cierre solo cambia el informe y la cobertura compacta. No se ejecutaron sincronizaciones, Supabase, Actions, migraciones ni commits. Queda trabajo pendiente que requiere revisión humana antes de cualquier siguiente intervención o uso en producción.

## Ampliación explícita y versión para QA #4

Después del cierre anterior, el usuario indicó **«dale 2 vueltas mas si hace falta»**. Esto autoriza hasta **dos ciclos adicionales de desarrollo → QA nueva**, máximo **cinco auditorías completadas** en esta tarea. No se modifican AGENTS ni skills. El historial de QA #1–#3, incluido su cierre NEEDS_HUMAN_REVIEW en aquel momento, se conserva; esta autorización permite retomar implementación y validación. Si QA #4 pasa, se detiene; si falla, queda como máximo un ciclo adicional para QA #5.

Corregidos en desarrollo y **pendientes de aceptación independiente**:

- **QA-007:** conciliación genérica de topes mensuales explícitos (antes de ejemplos), tanto «Tope mensual…» como «Tope… por mes». Una discrepancia con el API deja `amount=None`, mantiene moneda/período/grupo y describe ambos importes con advertencia de revisión. PedidosYa 393:7950 conserva API15000 y legal25000 sin afirmar ninguno como cierto. No se usan IDs ni importes comerciales hardcodeados. Casos consistentes, como YPF, conservan su importe; cifras de ejemplos no disparan conciliación. En el catálogo retenido se señalan **cinco publicaciones**: `3234:7326`, `3459:7492`, `393:7950`, `429:7960`, `60:7558`. Incluye el caso de cap agregado/base-extra de Sorpresa: se conserva la ambigüedad explícita y todos los textos, sin sumar importes automáticamente.
- **QA-008:** preventa filtra tipos de tarjeta nombrados en su cláusula positiva de etapa. Margarita admite crédito/débito y ya no hereda recargable de la lista general. Red y tipo siguen siendo combinaciones reales publicadas; no se genera producto cartesiano. Una etapa que contradice todas las combinaciones disponibles falla explícitamente, sin pérdida silenciosa. Cinépolis conserva prepaid evidenciado y la financiación general sigue siendo exclusiva de crédito.

Cambios de esta vuelta: `normalization/sources/santander.py`, `tests/normalization/test_santander_normalizer.py`, un fixture oficial adicional `393_7950.json` (26 extractos en total), este informe y cobertura/export locales. Sin cambios del scraper, runner, modelos compartidos ni raw original.

Validación: **283 passed in 15.44s**, incluidos **77 tests Santander**, con el mismo comando/bootstrap reproducible documentado arriba. Se agregaron **nueve regresiones** de conflicto/consistencia mensual, formas legales y exclusión de ejemplos, tipos por etapa, combinación red/tipo y rechazo de etapa imposible; se actualizaron las expectativas del cap agregado de Sorpresa para reflejar incertidumbre explícita. Export local regenerado con `PYTHONIOENCODING=utf-8 .venv/Scripts/python -m normalization.export_json --source santander`: **1.206 raw → 2.257 V2**, IDs únicos y cero exclusiones. Conserva 16 preventas y todos los tipos/componentes de beneficios anteriores. Hay seis límites monetarios sin importe confirmado: cinco por conciliación mensual y el conflicto transaccional ya declarado. Este recuento describe incertidumbre expuesta, no falla del modelo ni aprobación comercial.

Los cinco juicios actuales siguen separados: catálogo y aceptación corresponden al snapshot histórico y sus verificaciones locales; completitud estructural de normalización YES; fidelidad semántica pendiente de **QA #4 nueva**; `requires_review` semántico TRUE frente al FALSE histórico de aceptación de captura; `safe_to_deactivate=False`. Los detalles completos siguen sujetos a la limitación de muestreo independiente, y la variación live de 589 a 588 marcas no autoriza bajas.

**Congelado para QA #4.** No se afirma cierre independiente de QA-007/008, no se ejecutó sincronización/Supabase, no se leyó `.env`, ni se cambiaron Actions, modelos compartidos o commits. El máximo vigente es cinco auditorías por autorización explícita del usuario, con tres completadas hasta aquí.

## Auditoría #4 y última versión para QA #5

**QA #4: VERDICT FAIL.** Verificó independientemente el cierre de **QA-001–QA-008**. Muestreó **42 publicaciones de 39 marcas**, incluidas las **16 preventas**, con solo lectura por instrucciones, sin aislamiento técnico independiente. Suite independiente: **283 passed in 10.65s**; estructura **1.206 raw → 2.257 V2** correcta. La consulta live seguía en 588 marcas frente a 589 del snapshot histórico; no autoriza eliminación ni reemplazo. Encontró dos defectos nuevos:

- **QA-009 MED:** [Grido 3459:7492](https://www.santander.com.ar/bff-benefits/publications/7492?brandId=3459) diferencia cap mensual base $5.000 y cap para clientes Sorpresa $10.000. La publicación es exclusiva de Sorpresa y el API publica $10.000; el parser de QA #4 solo reconocía el base y advertía un conflicto falso. **Corregido en desarrollo:** seleccionar la cláusula calificada por el segmento explícito, preservando el tope mensual $10.000 sin conflicto. No se aplican cuotas de un segmento a otro ni se suman importes. Las cláusulas «extra» se mantienen separadas y no se reinterpretan como un cap total: Café Martínez continúa incierto; también persisten conflictos reales de PedidosYa, Natural Life y Puppis.
- **QA-010 MED:** [BABYMETAL 3040:6908](https://www.santander.com.ar/bff-benefits/publications/6908?brandId=3040) tiene un encabezado PREVENTA seguido de información financiera antes de su cláusula efectiva. El parser anterior elegía el encabezado y dejaba la fecha desconocida. **Corregido en desarrollo:** seleccionar una cláusula positiva de preventa, descartando encabezados y etiquetas de stock; ahora se conserva inicio **22/04/2026**, horario **10hs AM**, duración **48 hs** o hasta agotar stock y **3.500 tickets**. No se inventa fecha de fin a partir de la duración. También se conserva una duración positiva en la oración siguiente cuando la fuente la separa con punto, como Lollapalooza.

Revisión acotada de desarrollo: inspeccionadas las **16 cláusulas de preventa** originales y sus nuevas salidas, más topes análogos Grido/Café Martínez/Natural Life/Puppis/PedidosYa. Se mantienen 16 etapas y sus IDs: 15 tienen inicio explícito, mientras Milo J conserva fechas estructuradas desconocidas por el intervalo contradictorio publicado (10/08 al 04/08), sin fabricar corrección; los textos completos siguen visibles. No se extendió esta revisión a una auditoría completa de 2.257 filas.

Cambios: normalizador, tests de normalización, cuatro fixtures oficiales pequeños adicionales (Grido, BABYMETAL, Natural Life y Puppis), informe y cobertura/export locales. **Nueve regresiones nuevas** cubren el cap del segmento correcto, conflicto sintético en ese mismo segmento, cuatro conflictos reales/base-extra preservados, encabezado versus cláusula efectiva, fechas realmente desconocidas y duración separada. **292 passed in 11.07s**, incluidos **86 tests Santander**, usando el bootstrap reproducible ya documentado. Export local: **1.206 → 2.257**, IDs únicos, cero exclusiones; siguen 2.197 componentes cashback, 1.082 cuotas, 10 descuentos y 17 otros documentados. Raw original sin cambios.

Incertidumbre explícita actual: **cuatro publicaciones con cap mensual sin confirmar** (`60:7558`, `393:7950`, `3234:7326`, `429:7960`) y un cap transaccional (`740:7707`), cinco límites monetarios sin importe confirmado. Grido sale de ese conjunto gracias a su cláusula inequívoca de segmento. Estas incertidumbres de fuente no se convierten en valores de respaldo.

Los cinco juicios mantienen sus ámbitos: catálogo histórico de marcas verificado pero detalles independientes por muestreo; normalización estructural YES y fidelidad pendiente de QA #5; reemplazo TRUE histórico de captura local, no aprobación semántica; revisión semántica TRUE frente a `requires_review=False` histórico de captura; desactivación FALSE. No hubo sync/Supabase, `.env`, Actions, commits ni cambios de modelos compartidos.

**Congelado para QA #5 nueva, última autorizada.** Cuatro auditorías completadas; QA-001–008 cerrados por QA #4. QA-009/010 corregidos por desarrollo y pendientes de aceptación independiente. Se detendrá el ciclo después de QA #5, con PASS o FAIL; no se solicita una sexta auditoría.

## Auditoría #5 — cierre final autorizado

**VERDICT FAIL; NEEDS_HUMAN_REVIEW.** QA #5 verificó independientemente el cierre de **QA-001–QA-010** y detectó **QA-011 MED**, que permanece **abierto y sin corregir**. Se completaron las cinco auditorías autorizadas, todas con FAIL histórico: once hallazgos en total, diez cerrados y uno abierto. Las dos vueltas adicionales autorizadas por el usuario están agotadas; se detiene el ciclo automático, sin sexta auditoría ni nuevas correcciones.

**QA-011 — elegibilidad de tipo de tarjeta en Grido.** [Detalle oficial de Grido 3459:7492](https://www.santander.com.ar/bff-benefits/publications/7492?brandId=3459): el legal admite Santander VISA crédito/débito, mientras el API general incluye VISA Recargable. La salida conserva **dos alternativas prepaid QR** (App Santander y MODO), además de crédito/débito, sin advertir esa contradicción de tipos. El reconciliador actual restringe redes y tipos de preventa, pero no reconcilia tipos en publicaciones generales.

Reproducción: seleccionar `source_id="3459:7492"` en el raw retenido, aplicar `SantanderNormalizer().normalize_many(raw)` e inspeccionar `payment_methods` y `specific_conditions`. Comparar `cards[]` general con la cláusula positiva legal de crédito/débito. Una futura corrección debe conservar únicamente las **cuatro combinaciones VISA crédito/débito × App Santander/MODO QR**, advertir la discrepancia con prepaid y preservar el raw. Debe mantener prepaid en promociones que sí lo evidencian, como Cinépolis. **No se implementó esta corrección después de QA #5.**

QA #5 muestreó **30 publicaciones de 27 marcas**, en modo de solo lectura por instrucciones, **sin sandbox técnico independiente**. Ejecutó el bootstrap documentado: **292 passed in 10.44s**. Verificó los **1.206 raw → 2.257 V2**, IDs únicos y cero exclusiones. El catálogo live permanecía en **588 marcas** frente a 589 del snapshot original: variación temporal que no prueba un defecto histórico ni autoriza bajas. No se reemplazó raw ni se regeneró export para este cierre.

Juicios finales separados:

- Catálogo de todos los detalles: **UNKNOWN en QA**, por muestreo; no se confunde con cobertura estructural de marcas/paginación.
- Normalización: **YES estructural / NO en fidelidad semántica**, por QA-011 abierto.
- Reemplazo de snapshot: **TRUE histórico en metadata de captura local**, sin baseline durable externo ni aprobación de producción.
- Revisión requerida: **YES semántico**; permanece distinto del `requires_review=False` histórico de aceptación de captura.
- Desactivación segura: **NO**; no hay autorización ni evidencia suficiente para retirar filas.

La incertidumbre de topes/fechas/redes de la fuente y las limitaciones del muestreo siguen declaradas. Metadata registra cinco auditorías completadas, diez hallazgos cerrados y QA-011 abierto. Este cierre cambia **solo el informe y la cobertura compacta**: no se modificaron ni ejecutaron normalizador, scraper, tests, raw o export después del veredicto. Sin Supabase, sincronizaciones, `.env`, Actions, migraciones ni commits. Queda pendiente una decisión humana sobre el trabajo adicional; no existe aceptación independiente ni aprobación de producción.

## Segunda ampliación explícita y versión para QA #6

Después del cierre de QA #5, el usuario indicó **«dale2vueltasmas»**: se autorizaron **dos ciclos adicionales**, hasta **siete auditorías completadas** en total. Se conservan los cinco FAIL históricos y sus límites vigentes en cada momento; no se editan AGENTS ni skills. Si QA #6 pasa se detiene; si falla queda como máximo un último ciclo para QA #7.

**QA-011 corregido en desarrollo, pendiente de aceptación independiente:** las cláusulas positivas legales ahora restringen combinaciones reales de red/tipo para publicaciones generales, no solamente etapas de preventa. Grido `3459:7492` conserva exactamente VISA crédito/débito con App Santander/MODO QR (**cuatro combinaciones**) y advierte la discrepancia del API con VISA RECARGABLE. Mantiene tope Sorpresa ARS10.000 sin falso conflicto mensual. Raw original intacto.

Las restricciones se mantienen por alternativa de red/tipo: no se combinan piezas de cláusulas distintas ni se construye producto cartesiano de tarjetas. Se excluyen ejemplos, cláusulas negativas y preventas del análisis de elegibilidad general. Si la relación red/tipo resulta ambigua, los medios quedan sin estructurar y se agrega aviso de consulta, conservando el beneficio y los textos. Cinépolis y otras publicaciones que sí evidencian recargable conservan prepaid. Revisión acotada: **27 raw con recargable en API**, sin ampliar alcance del catálogo ni modificar condiciones comerciales.

Cambios de esta vuelta: normalizador y tests de normalización; seis fixtures oficiales adicionales (Grido base, Open Sports, Bridgestone, Emperador Meiji, Ateneo y Yenny); informe y cobertura/export locales. **13 casos de regresión nuevos** verifican Grido, análogos, prepaid evidenciado, alternativas de red/tipo en una o varias cláusulas, negativos/ejemplos, ambigüedad explícita y conservación de identidad. Un run intermedio tuvo 303 pasados y dos fallos en nuevas expectativas que asumían cashback sin evidencia para Ateneo/Yenny; se corrigió esa expectativa para verificar conservación de componentes sin inventar clasificación. Resultado final: **305 passed in 12.91s**, incluidos **99 tests Santander**, con el bootstrap documentado.

Export local final: **1.206 raw → 2.255 V2**, IDs únicos y cero exclusiones de raw. La diferencia frente a 2.257 se explica enteramente por Ateneo/Yenny: sus legales admiten crédito y contradicen débito del API. Se retiran únicamente `42:7928:non-credit` y `545:7928:non-credit`; se conservan **`42:7928:credit` y `545:7928:credit`**, con su financiación y beneficio porcentual. No se crean IDs nuevos para sustituir esas variantes de crédito. Las dos regresiones oficiales verifican esta identidad. No se ejecuta desactivación: la migración de filas previas requiere revisión humana antes de cualquier sincronización.

Componentes actuales: **2.197 cashback, 1.082 cuotas, 8 descuentos y 17 otros documentados**; los dos descuentos menos corresponden a las variantes no crédito contradichas, no a publicaciones descartadas. Se conservan los 16 beneficios de preventa, las condiciones específicas y la información/consulta de adheridos. Se exponen **14 publicaciones** con discrepancia de tipos de tarjeta en cobertura; ninguna publicación real produjo la advertencia de ambigüedad no estructurada. Se mantienen cuatro conflictos mensuales y uno transaccional con importe incierto.

Juicios separados: catálogo histórico de marcas verificado y detalle independiente por muestreo; normalización estructural YES y fidelidad pendiente de QA #6; reemplazo TRUE histórico de captura local, no aprobación de producción; `requires_review=True` semántico frente al FALSE histórico de captura; `safe_to_deactivate=False`. La variación temporal de 589 a 588 marcas no autoriza bajas. Sin sync/Supabase, `.env`, Actions, modelos compartidos ni commits.

**Congelado para QA #6 nueva.** Cinco auditorías completadas, máximo vigente siete por instrucción explícita del usuario. No se afirma cierre independiente de QA-011 ni PASS de esta versión.

## Auditoría #6 y versión final para QA #7

**QA #6: VERDICT FAIL.** Verificó de forma independiente el cierre de **QA-001–011**. Muestreó **50 publicaciones de 46 marcas**, incluidas las 27 publicaciones con prepaid general en API, contrastadas nuevamente con fuente oficial. Ejecutó el bootstrap documentado: **305 passed in 10.67s**; confirmó **1.206 → 2.255** exactos. Auditoría de solo lectura por instrucciones, sin sandbox técnico independiente. Su catálogo live tenía 589 marcas, pero faltaba `425` respecto del snapshot histórico y aparecía `3865`: **igual total no significa igual identidad ni autoriza reemplazo o bajas**.

**QA-012 MED:** [Kilbel 3472:7933](https://www.santander.com.ar/bff-benefits/publications/7933?brandId=3472) publica API ARS6.000 semanales y legales ARS10.000 mensuales para compras desde ARS50.000. La versión auditada conservaba solo cap semanal y mínimo de compra, omitiendo el cap mensual estructurado.

**Corregido en desarrollo, pendiente de QA #7:** los topes mensuales explícitos legales se extraen independientemente de la frecuencia del API. Kilbel conserva dos límites `monetary_cap` separados: **ARS6.000 weekly** y **ARS10.000 monthly**, este último con alcance agregado por cuenta, además del mínimo de ARS50.000, alternativas QR, texto legal y aviso de adheridos. No se suman importes ni se declaran contradictorios por pertenecer a períodos distintos; se incluye aviso de consultar su aplicación conjunta. Un mismo cap mensual encontrado en más de un texto no se duplica. Se conserva la selección por segmento y el tratamiento incierto de contradicciones del mismo período, como PedidosYa.

Revisión acotada de fuente, sin nuevos filtros ni captura persistida: cuatro raw tienen un cap mensual legal y frecuencia API diferente: **Jumbo `245:7937`** (API vigencia ARS25.000, legal mensual ARS25.000), **Diarco `151:7929`** (sin cap API estructurado, legal mensual ARS15.000), **Joseph Olivera `3349:7498`** (API semanal ARS15.000, legal mensual ARS15.000) y **Kilbel**. Se preservan ambas condiciones cuando hay dos períodos y se remite a la fuente para su relación. El cambio agrega cinco límites mensuales a la salida: uno por Jumbo/Diarco/Kilbel y uno en cada variante de Joseph. No se toma ningún importe de ejemplos ni cláusulas negativas.

Cambios: normalizador, tests de normalización, un fixture oficial de Kilbel (37 totales), informe y cobertura/export locales. **Seis regresiones nuevas**: caso oficial de doble período/mínimo/QR; monto mensual sintético modificado a ARS12.345 para probar extracción sin fallback; tres exclusiones de ejemplos/cláusulas negativas; y preservación de incertidumbre para discrepancias del mismo período. Suite final: **311 passed in 12.71s**, incluidos **105 tests Santander**, con el mismo bootstrap reproducible. Export final: **1.206 raw → 2.255 V2**, IDs únicos, cero exclusiones; beneficios, 16 preventas e identidad de variantes sin cambios respecto de QA #6. Hay 115 límites monetarios estructurados contando los cinco nuevos mensuales; se mantienen las incertidumbres de importe declaradas.

Los cinco juicios mantienen ámbitos distintos: catálogo histórico de marcas verificado, detalle independiente por muestreo UNKNOWN; normalización estructural YES y fidelidad pendiente de QA #7; reemplazo TRUE histórico de captura local sin aprobación comercial; revisión semántica TRUE distinta del `requires_review=False` histórico de captura; desactivación FALSE. No se reemplaza raw ni se autoriza migración/baja de filas por el cambio temporal del catálogo. Sin sync/Supabase, `.env`, Actions, commits ni cambios de modelos compartidos/runner.

**Congelado para QA #7 nueva, última autorizada.** Seis auditorías completadas; QA-001–011 cerrados independientemente. QA-012 corregido por desarrollo, sin afirmar cierre ni PASS todavía. El ciclo se detiene tras QA #7 con PASS o FAIL; no se solicita una octava auditoría.

## Auditoría #7 — cierre definitivo del alcance autorizado

**VERDICT FAIL; NEEDS_HUMAN_REVIEW.** QA #7 verificó independientemente el cierre de **QA-001–012** y encontró **QA-013 MED**, que queda abierto y **sin corregir**. Se completaron siete auditorías, todas con FAIL histórico: trece hallazgos, doce cerrados y uno abierto. Se agotaron las ampliaciones explícitas del usuario; se detiene implementación y auditoría automática, sin octava vuelta.

**QA-013 — afirmación de ausencia de tope contradictoria.** [Diarco 151:7929, detalle oficial](https://www.santander.com.ar/bff-benefits/publications/7929?brandId=151): `texts.description` afirma «Sin tope de reintegro» y `topAmount` es null; el legal publica tope mensual **ARS15.000** y compra mínima **ARS100.000**, agregando las compras de todas las tarjetas de la cuenta. La salida tiene correctamente esos límites, pero `specific_conditions` presenta también la afirmación ilimitada sin atribuirla como dato discordante ni advertir el conflicto. La conciliación actual solo verifica un subtítulo dentro de la rama de cap API positivo, por lo que omite esta forma con API null.

Reproducción: seleccionar raw `151:7929`, normalizarlo con `SantanderNormalizer().normalize_many(raw)` e inspeccionar `limits` y `specific_conditions`; contrastar los límites mensuales con la frase de ausencia de tope en `detail.texts.description`. Una futura corrección debe contrastar las afirmaciones de ausencia de tope en todos los campos de fuente con los límites legales aunque API `topAmount` sea null; atribuir la afirmación ilimitada como discordante y remitir a Santander. Debe preservar el cap mensual ARS15.000, mínimo ARS100.000, agregación por cuenta y regresiones de arteba/PedidosYa/topes de períodos distintos. **No se hizo esta corrección después de QA #7.**

QA #7 muestreó **34 publicaciones de 32 marcas**, con solo lectura por instrucciones y **sin aislamiento técnico independiente**. Suite independiente con el bootstrap documentado: **311 passed in 10.53s**. Verificó los **1.206 raw → 2.255 V2**, IDs únicos y cero errores/exclusiones. Tests y estructura correctos no sustituyen la fidelidad semántica que sigue fallando en QA-013.

La fuente live observada el **16/10/2026 entre 19:25 y 19:30 UTC** tenía 589 marcas; el snapshot original fue capturado el **15/10/2026 21:37 UTC**, también con 589. Los conjuntos difieren: desapareció `425` y apareció `3865`. Es cambio temporal, **no continuidad histórica demostrada ni autorización para reemplazar snapshot o desactivar promociones**. Se conserva raw original y export de desarrollo, sin nueva captura persistida en este cierre.

Juicios finales: **catálogo de marcas YES / todos los detalles UNKNOWN** por muestreo; **normalización YES estructural / NO semántica**; **reemplazo TRUE solo como juicio histórico de captura local**, sin baseline durable externo; **requires_review YES semántico y por continuidad actual de identidades**, distinto del FALSE histórico de aceptación de captura; **safe_to_deactivate NO**. Los flags originales de captura permanecen intactos y se registra el estado final dentro de `semantic_review`.

Las variantes no crédito retiradas (`42:7928:non-credit`, `545:7928:non-credit`) y sus IDs de crédito conservados siguen documentadas: cualquier eventual sincronización requiere manejo explícito de esas filas existentes, no un bypass ni bajas automáticas. Persisten incertidumbres de fuente en topes/fechas/redes y límites del muestreo independiente.

Este cierre modifica **solo este informe y la cobertura compacta**. No se modificaron ni ejecutaron normalizador, scraper, tests, raw o export tras el veredicto; sin sincronizaciones/Supabase, `.env`, Actions, migraciones ni commits. El resultado requiere decisión humana y no tiene aprobación independiente ni de producción.

## Tercera ampliación explícita y versión para QA #8

Después del cierre de QA #7, el usuario indicó nuevamente **«dale2vueltasmas»**, autorizando **dos ciclos adicionales** hasta **nueve auditorías**. Las siete anteriores conservan sus FAIL y sus decisiones históricas. No se editan políticas ni skills. Si QA #8 pasa se detiene; si falla queda como máximo un ciclo para QA #9.

**QA-013 corregido en desarrollo, pendiente de aceptación independiente:** la detección de afirmaciones «sin tope» ya no depende de un importe API positivo ni de un único subtítulo. Contrasta los campos de textos, información adicional y condiciones de `detail`/`program`, descripción del catálogo y texto legal anterior a ejemplos, con límites monetarios evidenciados. Diarco conserva API `topAmount=null` y los límites legales **ARS15.000 monthly/account** y mínimo **ARS100.000**, pero su descripción ilimitada pasa a estar **atribuida como afirmación publicada discordante**, con advertencia explícita y remisión a Santander. Raw, legales completos, QR y adheridos no cambian.

Ante una contradicción, las frases ilimitadas de condiciones/descripciones se atribuyen, y un título que la contenga advierte que el tope requiere confirmación. No se inventan importes. Un beneficio genuinamente ilimitado sin cap contradictorio conserva su texto; ausencia de cap informado sigue siendo desconocimiento y no se convierte en una afirmación ilimitada. Ejemplos, negativos y caps publicados para otro segmento no crean contradicciones monetarias.

Revisión acotada del raw y salida: **dos publicaciones** contienen afirmaciones ilimitadas y límites monetarios discordantes: **arteba `39:7934`** (subtítulo; cap API/legal ARS8.400) y **Diarco `151:7929`** (descripción; cap API null y legal mensual ARS15.000). Ambas quedan explícitas en cobertura. No se amplió el alcance ni se hizo nueva captura live.

Cambios: normalizador, tests de normalización, un fixture oficial de Diarco (38 totales), informe y cobertura/export locales. **11 regresiones nuevas** cubren el caso oficial API-null, cinco campos alternativos, ilimitado genuino, cap desconocido y tres casos sin falsa contradicción por ejemplo/negativo/otro segmento; la regresión de arteba verifica ahora el reconciliador genérico. Suite final: **322 passed in 13.21s**, incluidos **116 tests Santander**, con el bootstrap reproducible documentado. Export final: **1.206 raw → 2.255 V2**, IDs únicos, cero exclusiones y sin cambios de identidad. Se mantienen 2.197 cashback, 1.082 cuotas, 8 descuentos y 17 otros documentados; 16 preventas, 115 caps estructurados y las incertidumbres de importe previas.

Los cinco juicios siguen separados: catálogo histórico de marcas verificado, detalle independiente por muestreo UNKNOWN; normalización estructural YES y fidelidad pendiente de QA #8; reemplazo TRUE histórico de captura local, no aprobación comercial; revisión semántica/continuidad de identidades TRUE distinta del FALSE histórico de captura; desactivación FALSE. El total live de marcas igual al histórico con cambio `425`→`3865` no autoriza reemplazo ni bajas. Tampoco se retiran automáticamente filas de las dos antiguas variantes no crédito documentadas.

**Congelado para QA #8 nueva.** Máximo vigente nueve por autorización explícita; siete completadas hasta aquí. QA-013 no se declara cerrado independientemente ni se afirma PASS. Sin sync/Supabase, `.env`, Actions, commits, modificaciones de modelos compartidos/runner/scraper o raw original.

## Auditoría #8 — PASS y cierre para revisión humana

**VERDICT PASS; READY_FOR_HUMAN_REVIEW.** QA #8 verificó independientemente el cierre de **QA-001–QA-013**. Hay **cero hallazgos de implementación abiertos**. Se completaron **ocho auditorías: siete FAIL históricos y un PASS**. Las autorizaciones llegaron a permitir un máximo de nueve, pero el flujo se detiene con PASS: **no se ejecuta QA #9 ni se solicita otra vuelta automática**.

QA #8 revisó **30 publicaciones de 29 marcas**, con solo lectura por instrucciones y **sin sandbox técnico independiente**. Ejecutó el bootstrap documentado: **322 passed in 10.67s**. Verificó todos los raw y el export: **1.206 → 2.255**, IDs únicos, **182 grupos**, **16 preventas**, cero errores y cero exclusiones. Beneficios: 2.197 cashback, 1.082 cuotas, 8 descuentos y 17 otros documentados. Límites: **115 caps monetarios, 15 mínimos de compra, 43 límites de uso y 16 stocks**. La revisión semántica fue por muestreo, no un examen legal exhaustivo de todas las filas.

Cierre específico de QA-013: [Diarco 151:7929](https://www.santander.com.ar/bff-benefits/publications/7929?brandId=151) conserva cap legal mensual ARS15.000 y mínimo ARS100.000 por cuenta; la frase comercial ilimitada queda atribuida como discordante y requiere confirmación, sin presentarse como una condición ilimitada fiable. [arteba 39:7934](https://www.santander.com.ar/bff-benefits/publications/7934?brandId=39) conserva su cap legal y advertencia equivalente. El cierre significa que la integración expone fielmente esa incertidumbre, **no que el banco haya confirmado ausencia de límites ni resuelto sus contradicciones comerciales**.

La observación oficial del **16/10/2026 entre 20:29 y 20:34 UTC** devolvió **589 marcas**, con particiones 100/73 coincidentes y páginas terminales vacías. El snapshot retenido del **15/10/2026 21:37 UTC** también tenía 589, pero no los mismos IDs: faltaba `425` y apareció `3865`. El PASS no autoriza reemplazar ahora el snapshot, dar por demostrada continuidad de identidades ni remover registros históricos.

Los cinco juicios finales se conservan separados:

| Juicio | Resultado final y alcance |
|---|---|
| Catálogo | **YES para marcas/paginación verificadas; UNKNOWN para auditoría live de todos los detalles**, por muestreo. |
| Normalización | **YES estructural y en semántica muestreada**; no implica revisión legal completa de 2.255 filas. |
| Reemplazo de snapshot | **YES histórico de captura local únicamente; NO aprobación de reemplazo actual ni producción.** |
| Revisión requerida | **YES por contradicciones comerciales de fuente y continuidad de identidades**, sin hallazgos de implementación abiertos. El FALSE original de captura no se cambia ni se confunde con este juicio. |
| Desactivación segura | **NO**, sin autorización ni baseline durable externo suficiente. |

Quedan riesgos operativos para la revisión humana: baseline local sin protección histórica entre runners efímeros; importación temprana de Supabase en el runner común, por lo que validate-only no se considera independiente de credenciales; falta de transacción entre raw y base de datos; y eventual manejo deliberado de `42:7928:non-credit`/`545:7928:non-credit`, retiradas por contradicción legal, manteniendo sus IDs de crédito. Ninguno se habilita ni se elude mediante el PASS.

Este cierre solo actualiza **el informe y la cobertura compacta**. Tras el PASS no se modificaron ni ejecutaron código, tests, scraper, raw o export. Sin sincronizaciones/Supabase, `.env`, Actions, migraciones, commits ni aprobación de producción. La implementación queda lista para revisión humana con las incertidumbres y límites del muestreo declarados.
