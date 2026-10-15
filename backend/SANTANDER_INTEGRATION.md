# Integración Santander — desarrollo V2

Estado: **READY_FOR_INDEPENDENT_QA**. No representa aprobación de producción.

Captura oficial iniciada el **15/10/2026 18:37:52 ART** (21:37:52 UTC), terminada durante esta sesión. Alcance: catálogo público ALL de https://www.santander.com.ar/personas/beneficios#/results?category-code=ALL, sin provincia, día, segmento ni categoría restrictivos. No se afirma cubrir programas externos que no estén publicados en este catálogo (por ejemplo el catálogo separado de canjes SuperClub+).

## Evidencia y mecanismo

La página Next.js carga `/api/microfrontBeneficios`, que devuelve `/microfront-benefits`. El bundle oficial usa `/bff-benefits/brands` y omite `categories` cuando el filtro es ALL. Usa `/brands/{brandId}` para programas y `/publications/{publicationId}?brandId={brandId}` para condiciones, tarjetas, páginas de compra y establecimientos. Todos son endpoints públicos anónimos; no se utilizaron credenciales ni se leyó `.env`.

Se verificaron **589 marcas** mediante dos particiones completas independientes: límite 100, páginas de tamaños 100/100/100/100/100/89/0; límite 73, tamaños 73/73/73/73/73/73/73/73/5/0. Totales estables y conjuntos de IDs iguales. Cada marca produjo todos los programas de `items` y cada programa su detalle no vacío. `totalItems` de programas no es cantidad de publicaciones: Café Martínez devuelve 1 aunque contiene 2 programas. No se usa ese valor para truncarlos.

Resultado: **1.208 ocurrencias → 1.206 pares únicos marca/publicación → 2.257 filas V2**, IDs normalizados únicos, **182 grupos**, **16 variantes de preventa**. Sin registros excluidos y sin errores de extracción/normalización. Paseo del Jockey repite exactamente las publicaciones 7757 y 7756: se conservan una vez con `program_occurrences=2`; duplicados con contenidos distintos bloquean la captura.

Componentes de beneficios (las filas pueden incluir varios): cashback **2.197**, cuotas **1.082**, descuento directo **10**, otros beneficios documentados **17** (16 preventas y 2x1 Cinépolis). El catálogo observado usa códigos Ahorro/Solo Cuotas/Ahorro y Cuotas; no se encontraron otros tipos explícitos dentro de este alcance. El normalizador no usa `other` como sustituto de fallos de parseo.

## Archivos

- `scraping/sources/santander/scraper.py`: captura candidata, cobertura y aceptación/guardado atómico.
- `normalization/sources/santander.py`: normalización V2 y variantes.
- `synchronization/sync_santander.py`: entrada del runner; **no ejecutada**.
- `normalization/export_json.py`: registro de Santander, sin cambios del contrato común.
- `tests/{scraping,normalization,synchronization}/test_santander_*.py` y 11 extractos oficiales pequeños en `tests/fixtures/santander/`.
- Datos locales persistentes, ignorados por Git: `data/santander_promotions.json` (≈344 MB, detalle completo incluidos establecimientos), `data/normalized/santander_promotions.json` (≈9,7 MB), `data/santander_coverage.json` (metadatos compactos, sin respuestas completas duplicadas).

## Decisiones y límites de fidelidad

Las publicaciones oficiales ya distinguen segmentos y beneficios. IDs estables `marca:publicación`, sufijos semánticos `:credit`, `:non-credit`, `:presale`. Financiación y reintegro compatibles se conservan juntos para crédito; débito no recibe financiación. Preventas tienen sus propios beneficios, tarjetas, fechas explícitas y stock, separados de la financiación general. Los horarios/duraciones permanecen en condiciones porque V2 solo admite fechas de calendario.

Las tarjetas se mapean desde combinaciones `cards[]`, no productos cartesianos. QR App Santander/MODO, NFC Apple Pay/Google Pay/MODO Contactless, App YPF, Cabify y PedidosYa se sustentan en textos positivos. QR transporte usa transferencia PCT, sin inventar tarjetas. Aplicaciones/QR no prueban compras online. Los días provienen de booleanos explícitos; `fullWeek` indica todos los días. Se conservan el detalle legal HTML completo, restricciones, segmentos, códigos, exclusiones y vínculos oficiales de consulta de locales. Establecimientos completos quedan en raw; no se inventan comercios individuales.

**La fuente contiene contradicciones comerciales.** En **191 publicaciones** las fechas legales completas difieren de la ventana de presentación del API (374 filas V2); se prioriza la cláusula legal explícita y se incluye una advertencia visible en `specific_conditions`. Ejemplo: Café Martínez 7558 termina 28/10 en API y 31/10 en legales. arteba 7934 publica subtítulo «Sin tope» pero importe y legales $8.400: se conserva el tope legal y se advierte. La cobertura enumera estos IDs en `semantic_review`. No se afirma que las contradicciones estén resueltas por el banco.

Los importes/porcentajes se toman de datos publicados, sin valores económicos de respaldo. Topes conservan moneda, frecuencia publicada y alcance por cuenta cuando está probado; grupos compartidos vinculan topes cuando el texto reúne titular/adicionales. Beneficios extra/acumulables de Sorpresa y transporte se explican en condiciones; no se suman porcentajes encontrados en párrafos. Valores malformados como stock «105.00 tickets» no se convierten arbitrariamente en cantidades; quedan en condiciones y términos. No se estructuran todos los horarios, precios de membresía, fórmulas de acumulación, exclusiones por producto y restricciones geográficas: permanecen en condiciones/términos y raw.

Muestra de revisión de desarrollo (no QA independiente): Café Martínez base/Sorpresa (7557/7558), Cinépolis (7150), Margarita (7560, financiación/preventa/stock), Humbe (6373), Transporte (7899/7900), arteba (7934), Paseo del Jockey (7757), Coto NFC (8075), YPF App (7909). Incluye categorías gastronomía, espectáculos, transporte, shopping, supermercado y combustible; segmentos masivo/Sorpresa; los tests agregan escenarios sintéticos de fechas desconocidas, negativas y ausencia de beneficio. Catálogo grande: no se revisaron manualmente las 2.257 filas; QA debe ampliar muestra a Select, sueldo/jubilados, Dining, códigos especiales y campañas compartidas.

## Cinco juicios separados

| Juicio | Resultado y fundamento |
|---|---|
| `catalog_complete` | TRUE: dos particiones, terminales vacíos, IDs iguales y todos los detalles válidos para ALL. |
| `normalization_complete` | TRUE estructural: 1.206 registros producen 2.257 V2 válidos únicos; fidelidad semántica pendiente de QA y contradicciones de fuente declaradas. |
| `snapshot_replace_allowed` | TRUE para esta captura fiel: datos completos y sin pérdidas contra baseline local; no certifica hechos comerciales. |
| `requires_review` | FALSE en aceptación de captura local; `semantic_review.production_approval=False` registra revisión comercial pendiente. No confundir ambos niveles. |
| `safe_to_deactivate` | FALSE incondicional en esta integración; no hay baseline histórico durable externo. |

La primera captura carecía de baseline local. Eso no prueba ausencia de historia en Supabase/CI. El guard compara IDs contra snapshots locales válidos cuando existen y bloquea desapariciones/reemplazos con iguales totales. `scrape()` no guarda. El runner valida raw/variantes antes de guardar y persiste solo después. El guard revalida contenidos, flags, identidad y digest antes del `os.replace` atómico. Raw y Supabase no son una transacción: un error de upsert puede dejar raw adelantado; los tests verifican conservación y reintento, sin desactivar tras fallos.

## Verificación ejecutada

Desde `backend/`, Python de `.venv`:

- Primera ejecución desde raíz: 2 errores de colección por cwd; corregido a backend.
- Primera ejecución normal desde backend: 16 pasaron; 11 errores al crear temporales con permisos Windows Python 3.14 `mkdir(0700)` y error final de limpieza. No era fallo de datos; no se cambiaron permisos del árbol.
- Bootstrap aislado de pytest: reemplaza `os.mkdir` solo en proceso de tests para usar modo normal `0777`, deshabilita `dotenv.load_dotenv`, asigna valores ficticios de test y ejecuta `pytest.main(['-q','tests','--basetemp=.tmp/pytest-santander-full','-p','no:cacheprovider'])`. Resultado final **252 passed in 10.83s**, **46 tests nuevos Santander**. No red ni repositorios reales en tests de sincronización.
- `.venv/Scripts/python -m normalization.export_json --source santander`, con `PYTHONIOENCODING=utf-8`: **1.206 → 2.257**, éxito. Primer intento sin UTF-8 completó el archivo pero falló al imprimir la flecha Unicode en consola CP1252; el rerun UTF-8 terminó correctamente. Se verificaron bytes UTF-8 del código, sin U+FFFD.
- Scrape local candidato + normalización de todos los registros + `save_raw_promotions()` solo después de validarlos: completo, 0 errores. No se invocó `SyncRunner.run()` fuera de pruebas completamente simuladas, ni ninguna entrada `sync_*`.

Tests cubren captura completa/incompleta, esenciales vacíos dentro de HTTP 200, IDs inválidos/duplicados, programas duplicados idénticos/conflictivos, cambios de identidad con igual total, desapariciones, adiciones legítimas, actualizaciones, tampering, fallo de reemplazo atómico y bytes previos intactos. Mocks del runner cubren cero/duplicadas variantes, fuente incorrecta, rechazo de guardado/flags, validate-only, upserts cortos/fallidos/reintento y todas las compuertas de desactivación.

Contrato V2 real compatible; no se editaron modelos compartidos. `sync_santander` importa el runner de forma diferida, pero el runner compartido todavía importa Supabase al cargar y puede leer `.env`; **no se afirma que la entrada validate-only sea independiente de credenciales**. No se ejecutó ninguna sincronización, escritura en Supabase, migración, cambio de Actions, push ni despliegue.

Pendientes para revisión humana/QA: contradicciones publicadas en fechas/topes, semántica de acumulaciones y topes compartidos en más campañas, horarios/stock malformados y muestreo ampliado de segmentos. No se autoriza producción ni desactivación.

Limpieza: retirados los archivos de investigación descargados y temporales de las pruebas exitosas. Quedó únicamente el directorio vacío/inaccesible backend/.tmp/pytest-santander creado por el primer intento de pytest; Windows rechaza listar/eliminar ese directorio. No se tocaron temporales ajenos.
