# MODO — desarrollo V2 y evidencia de captura

Estado: **READY_FOR_HUMAN_REVIEW; QA #3 PASS técnico; candidato requiere revisión y no está habilitado para sincronización**.
No se ejecutaron entry points de sincronización, Supabase, migraciones ni GitHub Actions.

## Alcance oficial y adquisición

Fuente: [catálogo público](https://www.modo.com.ar/promos). Captura oficial HTTP del
15/10/2026, **00:40:15–00:40:26 ART (03:40:15–03:40:26 UTC)** para la nueva
enumeración de campañas activas y seis detalles reconsultados.
La página usa Next.js; el bundle oficial `3jhppua_oewiw.js` declara rutas
`/v2/filter` y `/v2/benefit/{id}` bajo `/promos/api/rewards`, y
`2j4vc93yswmev.js` declara que el cliente web incluye los estados running,
finished_for_product y next_for_product cuando no hay un filtro seleccionado.
El usuario restringió explícitamente el alcance a **sólo activas**: esta integración
ahora solicita `fcalcstatus=RUNNING` y rechaza cualquier card con otro estado.
No se necesita autenticación, ubicación, .env ni Supabase para leerlos.

Endpoints públicos observados:

- [Filtro del catálogo activo](https://www.modo.com.ar/promos/api/rewards/v2/filter?limit=100&page=1&origin=WEB_MODO&fcalcstatus=RUNNING).
- [Categorías y subcategorías](https://www.modo.com.ar/promos/api/rewards/categories?subcategories=true).
- [Bancos](https://www.modo.com.ar/promos/api/rewards/v2/banks).
- [Contenedor web activo](https://www.modo.com.ar/promos/api/rewards/slots-container/active?source=web_modo).
- [Seis slots de portada](https://www.modo.com.ar/promos/api/rewards/slots-container/web-modo-container-hub-promos-1?source=web_modo).

Se recapturaron **las 35 páginas de RUNNING**, 100 por página y 60 en la última:
**3.460 cards, 3.460 benefit IDs únicos, 3.460 detalles y 3.460 ofertas nativas**.
Todos los bancos, categorías, días y canales, sin filtros de esos ejes. El estado
RUNNING identifica la campaña activa en la fuente; no significa elegibilidad
todos los días o para toda persona.

La página 36 devuelve cards vacías y su convención particular es
`total_results=0,total_pages=0`. Se verifican los contadores de cada página,
IDs de cards, fin explícito, detalle por ID/oferta y relectura de primera página
antes y después de descargar detalles. La primera página se mantuvo idéntica.
La lista completa se reconsultó por HTTP oficial con cuatro workers, pausas,
TLS verificado, cachebuster `_t` y `Cache-Control: no-cache`. Todas las listings
activas coinciden exactamente con la captura anterior. Se reconsultaron seis
detalles, incluidos los cuatro IDs de QA y Café Martínez. Los otros **3.454
detalles se reutilizaron** después de comparar cada listing fresca completa
(condiciones, fechas, ofertas, límites, importes y estado) con su listing anterior.
El raw identifica cada caso en `detail_acquisition`, conserva la ventana original
03:18:47–03:30:28 UTC para el cuerpo reutilizado y `listing_observed_at` para
su comprobación nueva. Los seis refetch tienen hora de consulta individual.
No se presenta un cuerpo reutilizado como descarga nueva. La validación final
usó esos cuerpos mediante cliente inyectado y revalidó primera página en vivo.
Esto documenta estabilidad observada; no proporciona un token transaccional
del servidor ni prueba que una página intermedia no cambiara sin cambiar el total.

Estado entregado: **3.460 RUNNING, cero próximas y cero finalizadas**.
La primera captura de desarrollo tenía 4.826 campañas en 49 páginas, con 18
próximas y 1.348 finalizadas; el cambio explícito de alcance reemplaza ese
candidato anterior, sin otros filtros inventados. Las fechas normalizadas vienen de
`conditions.schedule`, no de `display_*`, que indica publicación en el catálogo.
Si una cláusula explícita de vigencia legal contradice una fecha del calendario,
ese extremo normalizado queda `null`, ambas fechas se muestran en condiciones
y la campaña continúa RUNNING en el candidato bloqueado hasta aclaración oficial.

## Artefactos de revisión

- Raw completo: `backend/data/candidates/modo_promotions.json` (53.499.503 bytes).
- V2: `backend/data/normalized/candidates/modo_promotions.json` (19.607.631 bytes).
- Cobertura compacta: `backend/data/modo_coverage.json`.

**No hay un snapshot MODO aceptado en `backend/data/modo_promotions.json`.**
Los candidatos no autorizan escrituras ni desactivaciones. El raw conserva
cada card, detalle JSON, términos HTML originales, FAQ, enlaces, botones,
restricciones técnicas, IDs y UTC. No hay exclusiones de registros.

Reexportación local, sin runner ni Supabase, desde `backend/`:

```powershell
.venv/Scripts/python.exe -m normalization.export_json --source modo --input-dir data/candidates --output-dir data/normalized/candidates
```

Resultado: **3.461 variantes únicas / 3.460 grupos**. Café Martínez agrega una
segunda variante explícitamente publicada en FAQ. Beneficios, contados por
componente: 2.512 cashback, 1.267 financing/installments, 3 descuentos directos,
4 participaciones Raspá y Ganá (`other` descrito como premio aleatorio).
Los máximos publicitados no se presentan como un premio garantizado.
Límites: 2.422 monetarios, 114 mínimos de compra, 43 cantidades de uso/premios
y 2 stocks de premios publicados explícitamente.

Los pagos mantienen las parejas nativas tipo de tarjeta/red. Se resuelve
`issuer` cuando una oferta exige un único banco identificado; si hay varios,
la restricción queda en condiciones sin inventar cruces de bancos y redes.
Las alternativas QR/NFC se conservan para cada pareja válida cuando los flujos
nativos las publican. Los flujos de app no implican online;
QR/NFC no se convierten en canales de compra. Todos los registros conservan
enlace oficial y nota accionable de comercios/sucursales adheridas.

## Discrepancias y límites de evidencia

1. [Café Martínez](https://www.modo.com.ar/promos/cafemartinez-santander-agos26-oct26):
   ID `38825c80-1999-4b6a-b5f6-46a7557bfbc4`. Card «hasta 20%», motor 10%; FAQ
   publica 10% / $10.000 mensuales para todos los clientes Santander y 20% /
   $20.000 para Sorpresa Santander. Se generan dos variantes, sin sumar tasas.
   IDs con huella del nombre del segmento, independientes del porcentaje,
   tope, fechas, orden y marketing. El raw conserva el slug oficial real;
   consultar `promotion_url` del JSON si cambia la URL de esta documentación.
2. **Pendiente de fuente:** [Get The Look Galicia](https://www.modo.com.ar/promos/6csi-galicia-getthelook-oct26),
   `45301a91-6671-42f0-bd31-b4795dfa845a`: el legal publica 25% + hasta 6
   cuotas para Éminent, sábados/domingo, tope 50.000 por marca; el motor sólo
   cuotas, siete días, sin tope. Se explicitan las tres contradicciones y se
   bloquea cualquier snapshot, incluso aislando esta sola campaña. No se suma
   el 25% automáticamente; días/everyday quedan desconocidos ante conflicto.
   El chequeo conservador de cláusulas positivas documentadas encuentra **64
   campañas activas con contradicciones legales/técnicas**, detalladas por ID
   y motivo en `legal_engine_conflicts` de cobertura. No pretende ser un parser
   legal universal ni interpretar todos los porcentajes de un texto (p.ej TNA).
3. Test GDN y CAZZU Nivel 2, inconsistentes en la primera captura, **no forman
   parte del candidato actual porque no están RUNNING**. No se excluyeron por
   su nombre ni para ocultar inconsistencias.

Hay **182 detalles con términos null o string vacío originales**; el API los
publica así, especialmente financiaciones y beneficios laborales. También hay
textos legales poco informativos, por ejemplo «.» en TelePASE. Se conserva la
ausencia sin inventar términos ni condiciones. Un nodo legal HTML presente
pero en blanco se rechaza; la pérdida de un texto legal/FAQ previo bloquea
reemplazos aunque el campo ahora sea null o vacío.

El catálogo bancario público resuelve 32 nombres, pero aparecen más IDs de
emisores en requisitos técnicos (incluye códigos no visibles en el filtro).
Se conservan todos los IDs raw y una advertencia accionable para los nombres
no resueltos. No se inventan nombres. **353 límites monetarios no tienen una
moneda demostrable** en el texto disponible y quedan `currency=null`, no ARS
por defecto. Stock/exclusiones/códigos no estructurados permanecen en las
frases restrictivas de `specific_conditions` y en términos completos; algunas
condiciones son extensas porque el origen agrupa muchas restricciones.

Revisión de desarrollo: chequeos estructurales de cada registro, comparación
de todas las tasas publicitadas con tasas técnicas y muestreo por riesgos de
cashback + cuotas (CARDON), segmento FAQ (Café Martínez), descuento en PDV
(Diarco), premio aleatorio (Santa Fe), importe fijo y cantidad de usos
(`1a6ca76c-eff8-469f-a8d8-051bba459153`), cuotas con interés preferencial
(`ad41b629-abcc-4f41-b7c5-5f6a870eb0a0`) y TelePASE
(`5cc79a5e-45bd-420c-992c-f4439eafda6c`). No es revisión legal exhaustiva de
las 3.460 campañas, ni auditoría independiente. Los links externos bancarios
se preservan; no se promete haber revisado todos los destinos externos.

## Cinco gates y persistencia

| Juicio | Estado final | Motivo |
|---|---|---|
| catalog_complete | true | Alcance web completo observado, páginas y detalles capturados |
| normalization_complete | null / pendiente | 3.461 filas V2 estructuralmente válidas; 64 campañas con contradicciones legales/técnicas sin resolver |
| snapshot_replace_allowed | false | Conflicto pendiente de fuente |
| requires_review | true | Contradicciones de fuente y revisión humana de fidelidad/muestreo |
| safe_to_deactivate | false | Sin baseline durable independiente ni autorización de retiro |

`scrape()` no guarda; `save_raw_promotions()` exige candidato aprobado y
sin cambios, revalida normalización, IDs y baseline inmediatamente antes del
reemplazo atómico con fsync. Bloquea desapariciones/sustituciones de IDs,
pérdida de ofertas y de términos/FAQ previos. Una primera captura local no
demuestra ausencia de historia en producción/CI; no hay protección entre
runs efímeros sin estado persistente. No se presume seguridad por conteos.
El reemplazo raw y el upsert no forman una transacción: un fallo de red
posterior puede dejar raw nuevo y base antigua; los mocks prueban ese estado
y que no se desactiva tras un upsert parcial o fallido.

El entry point `synchronization/sync_modo.py` queda con `allow_deactivation=False`.
No se ejecutó. El runner común conserva import eager de Supabase, que puede
leer .env incluso con validate-only; esta integración no lo modifica.

## Pruebas

**67 casos MODO; suite completa final: 273 passed en 8,91s.** Incluye extracción
parcial, paginación, duplicados, nodo HTML legal vacío con HTTP 200, identidad,
baseline válido con desaparición/sustitución de IDs, adiciones y actualizaciones,
pérdida de detalles, manipulación del candidato, fallo de os.replace, cero/
duplicadas/fuente incorrecta en variantes, bloqueos de coverage y del guard,
validate-only, upsert parcial/fallido y cada gate de desactivación.

El comando estándar enfocado con `--basetemp=.tmp/pytest-modo` sufrió
PermissionError/WinError 5 al crear tmp_path con permisos privados en este
sandbox Windows. El primer intento también detectó colisión de nombres de
módulos de test, corregida renombrando el de normalización. Se usó un harness
temporal con fixture equivalente que crea directorios con Path.mkdir por
defecto, y un stub del módulo `persistence.supabase_client` antes de importar
la suite, para impedir lectura de .env o credenciales. No modifica el runner.
Reproducción desde `backend/` (guardar temporalmente en `.tmp/run_modo_tests.py`):

```python
import pathlib, uuid, pytest, sys, types
sys.path.insert(0, str(pathlib.Path.cwd()))
stub = types.ModuleType('persistence.supabase_client')
stub.SUPABASE_URL = 'https://unit-test.invalid'
stub.get_headers = lambda: {'apikey': 'unit-test-only'}
sys.modules['persistence.supabase_client'] = stub
class TempPlugin:
    @pytest.fixture
    def tmp_path(self):
        p = pathlib.Path('.tmp') / ('modo-test-' + uuid.uuid4().hex)
        p.mkdir()
        return p
raise SystemExit(pytest.main(['-q', 'tests', '-p', 'no:tmpdir',
    '-p', 'no:cacheprovider'], plugins=[TempPlugin()]))
```

```powershell
.venv/Scripts/python.exe .tmp/run_modo_tests.py
```

## Auditoría #1 y correcciones

La auditoría independiente #1 cerró **FAIL**, con 14 detalles muestreados y
verificación completa de las 49 páginas del alcance anterior. Sus 11 pruebas de
normalización y 21 de runner pasaban, pero la revisión encontró defectos
semánticos que los tests anteriores no detectaban. No se equiparó pytest a QA.

- **QA-001:** contradicciones no detectadas en Get The Look. Corregido con
  advertencias explícitas de beneficio, días y tope; gate de revisión bloqueado
  y weekdays desconocidos ante contradicción. El contenido comercial de fuente
  queda pendiente de aclaración, no artificialmente reconciliado.
- **QA-002:** Santa Fe Raspá y Ganá omitía compra en últimos 60 días, ausencia
  de mora, participación diaria y stock 7.396. Se conservan las restricciones
  y se agregan límites independientes daily usage y stock; `winning_cap` sigue
  siendo máximo de premios ganadores, distinto de participaciones. Las cifras
  salen del legal mediante cláusulas completas; no son fallback hardcodeado.
- **QA-003:** issuer sin resolver y rail ambiguo. CARDON ahora conserva Macro
  con Visa/Mastercard/Amex crédito y alternativas QR/NFC; Paruolo conserva Comafi
  con Visa/Mastercard crédito y QR. Una regresión con dos ofertas y bancos
  distintos prueba que se resuelve por oferta sin mezclar emisores.

En paralelo, el usuario pidió sólo activas. Se reemplazaron los candidatos
anteriores por RUNNING y se añadieron tests que rechazan próximas/finalizadas
en la respuesta de ese endpoint. Listo para auditoría independiente #2.

Los temporales de investigación y los del harness se eliminan al entregar.
La carpeta del primer intento `backend/.tmp/pytest-modo` quedó inaccesible
(PermissionError/WinError 5) y no pudo eliminarse con los permisos actuales;
no contiene datos persistentes del pipeline. El intento inicial de limpieza
PowerShell fue rechazado por revisión automática; una limpieza Python con
rutas verificadas eliminó el resto. Los fixtures
pequeños reproducibles son siete respuestas oficiales: CARDON, Café Martínez,
Get The Look, Santa Fe, Paruolo, Tienda BNA+ motos y Todos los pagos Macro.
Los tests sintéticos modifican copias, nunca snapshots reales ni Supabase.


## Auditoría #2 y correcciones para auditoría #3

La auditoría independiente #2 cerró **FAIL** luego de verificar las 35 páginas,
3.460 IDs activos exactos, 17 detalles y la igualdad de la exportación con la
normalización en memoria. Sus 51 tests de lectura pasaron; confirmó las
correcciones QA-001/002/003 y halló tres defectos adicionales. Esta sección
registra correcciones de desarrollo; no constituye un PASS independiente.

- **QA-004 (alta):** [Tienda BNA+ motos](https://www.modo.com.ar/promos/24cf-tiendabna-motos-bna-abr26),
  `ad41b629-abcc-4f41-b7c5-5f6a870eb0a0`. El endpoint oficial fue reconsultado:
  el legal publica fin 30/09/2026 y TNA 41,20%; el motor publica fin
  31/12/2026 y TNA 35,00%. Las nuevas cláusulas de detección comparan vigencia
  explícita y TNA de financiación sin inventar tasas ni elegir fecha. El fin
  normalizado queda `null`; el inicio coincidente 01/04/2026 se conserva,
  igual que las 24 cuotas con interés preferencial. Ambas evidencias aparecen
  en condiciones y cobertura; se bloquea aceptación incluso con esta única
  campaña y sin baseline local. No se retira una campaña RUNNING por conjetura.
- **QA-005 (media):** [Todos los pagos Macro](https://www.modo.com.ar/promos/2000-todostuspagos-macro-oct26),
  `1a6ca76c-eff8-469f-a8d8-051bba459153`. La reconsulta oficial confirma
  «El reintegro es por cuenta por mes» frente a `aggregate_by=user/reset_by=promo`.
  Se preserva esa restricción legal en condiciones y se declara el conflicto
  bloqueante de ámbito/período, sin sustituir silenciosamente el cap técnico.
  Permanecen cashback fijo ARS 2.000, compra mínima ARS 8.000, cinco usos,
  cap por transacción ARS 2.000 y cap técnico ARS 10.000 por persona/promoción.
- **QA-006 (baja):** Santa Fe `154f2a18-c248-4ebd-8195-49bbd4837e12` tiene
  ahora un resumen de 2.090 caracteres, frente a 7.032 antes. Selecciona por
  secciones semánticas completas: edad/provincia, cuenta y app bancaria,
  compra en últimos 60 días, sin mora, QR mínimo ARS 25.000, una participación
  diaria, exclusiones de pagos, azar/probabilidad y ruta sin obligación de
  compra con email y punto 7 del legal. Mantiene la consulta de adheridos.
  Domicilio/CUIT del organizador, responsabilidad, seguridad, impuestos,
  autorización publicitaria y preguntas FAQ huérfanas quedan fuera del resumen;
  el legal completo sigue en `terms`. No se aplica truncado por longitud.
  Los límites de una participación diaria, stock 7.396 y un premio ganador
  por promoción siguen separados y probados.

Las dos nuevas respuestas oficiales son idénticas a los cuerpos ya preservados
en el raw candidato. El raw y su provenance no se reescribieron ni se presentaron
como una captura de todo el catálogo nueva. La igualdad de listings previamente
observada no prueba que el legal de los 3.454 detalles reutilizados sea idéntico
al legal actual; se conserva esta limitación de evidencia para QA.

El detector general encuentra **52 campañas con contradicción de fechas**
(53 extremos: una campaña contradice ambos), además de las 11 campañas previas
y Macro: **64 campañas distintas requieren aclaración**. Se inspeccionaron
además las cláusulas de Cecchini, Super ANSES, Pasión y Puppis para confirmar
que las nuevas detecciones se refieren a vigencia de campaña y no a plazos de
crédito/publicación. La lista completa de IDs y motivos está en cobertura.
No hay exclusiones nuevas ni cambios de identidad: **3.460 raw / 3.461 V2**,
3.460 grupos, un grupo con dos segmentos. Todos siguen activos RUNNING según
la captura oficial conservada; no se fabrican beneficios para resolver conflictos.

Los cinco gates siguen separados: `catalog_complete=true` para la captura
conservada; `normalization_structurally_complete=true` y
`normalization_complete=null` por conflictos pendientes; aceptación de snapshot
`false`; revisión `true`; desactivación `false`. El guard reconsulta los
conflictos antes de un reemplazo, además de los gates y digest existentes.
La exportación revisable se regeneró con `normalization.export_json.export_source`
desde el raw candidato guardado, sin ejecutar guard de guardado ni sync.
Cobertura conserva fechas de captura originales y registra la recomputación
local con hashes SHA-256 de raw y V2. Esto no autoriza persistencia ni desactivación.

Pruebas: `.venv/Scripts/python.exe .tmp/run_modo_fix2_tests.py`, usando el
mismo harness Windows credential-free documentado arriba (plugin `tmp_path`
con `Path.mkdir`, stub de Supabase anterior a imports, sin tmpdir/cacheprovider).
Primero **65 MODO passed en 1,47s**, después **271 passed en 8,78s** en toda
la suite. Tras dos regresiones adicionales de cláusulas negativas/plazos de
crédito, resultado final **273 passed en 8,91s**, incluidos **67 casos MODO**.
No hubo fallos de tests en estas ejecuciones. Se agregaron regresiones
source-based para fechas/TNA, cap cuenta/mes, resumen sin boilerplate y guard
bloqueado con un único registro oficial; se preservaron todos los tests previos.
El harness y su export script son temporales y se eliminan al entregar.
La carpeta inaccesible `backend/.tmp/pytest-modo` del intento anterior no se tocó.

No se ejecutó ningún entry point sync ni `SyncRunner.run()` fuera de mocks,
no se accedió a `.env`/secretos, no hubo escrituras Supabase, cambios de Actions,
migraciones, commit, push o despliegue. Modelo V2 runtime revisado y compatible;
no se alteró el contrato compartido. En esta etapa quedó pendiente la auditoría
independiente #3, cuyo resultado se registra a continuación; el candidato
permanece bloqueado por las contradicciones oficiales.

## Cierre de coordinación — auditoría #3

Resultado independiente final: **VERDICT: PASS**, listo para revisión humana.
Se completaron tres auditorías: **#1 FAIL → correcciones → #2 FAIL →
correcciones → #3 PASS**. Las sesiones de QA interrumpidas se retomaron sin
un veredicto adicional; no hubo una cuarta auditoría completada. Se delegó
implementación al rol `promotion_dev` y auditoría a sesiones nuevas del rol
`promotion_qa`. QA fue de solo lectura por instrucciones, con sistema de
archivos compartido y sin aislamiento técnico separado.

La última auditoría reconsultó seis respuestas oficiales, iguales a sus cuerpos
raw, y confirmó las correcciones **QA-001 a QA-006**: conflictos de beneficio,
días, topes, fechas y TNA señalados y bloqueantes; restricciones y stock de
Raspá y Ganá; emisores y alternativas de pago por oferta; condiciones accionables
separadas del legal íntegro. No encontró nuevos defectos confirmados en esa
muestra. La normalización completa en memoria reprodujo exactamente las
**3.461 variantes / 3.460 grupos** del export. Ejecutó **22 pruebas de
normalización y 21 del runner con mocks: 43 passed**, sin escrituras, bytecode
ni cachés. No ejecutó las pruebas que escriben archivos ni atribuye a QA los
273 tests de desarrollo.

**Cambio temporal del catálogo:** el 15/10/2026 a las **10:39:48 ART
(13:39:48 UTC)** el endpoint oficial informó **3.482 RUNNING**, frente a las
3.460 de la captura conservada. El export entregado es histórico y no contiene
una captura actualizada de esas 3.482 campañas. QA no repitió en su cierre
todas las páginas ya enumeradas en el tramo anterior. No se interpreta la
variación temporal como un defecto de truncamiento.

| Juicio final | Resultado |
|---|---|
| catalog_complete | Sí para la captura conservada; desconocido frente al catálogo actual de 3.482 |
| normalization_complete | Estructuralmente sí; fidelidad global pendiente por 64 campañas con conflictos de fuente |
| snapshot_replace_allowed | false |
| requires_review | true |
| safe_to_deactivate | false |

El PASS técnico no resuelve contradicciones comerciales ni autoriza producción.
Siguen pendientes la aclaración de conflictos oficiales, una captura actualizada,
la revisión semántica más allá de la muestra, detalles reutilizados sin reconsulta
exhaustiva y un baseline histórico durable. El detector legal tiene alcance
limitado; raw y Supabase no son una transacción conjunta. No hubo sincronización
real, escrituras Supabase, cambios de Actions, migraciones, commits ni push.
