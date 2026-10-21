---
name: integrate-promotion-source
description: Integrar una fuente de promociones bancarias V2 con Codex principal como desarrollador y una sola auditoría independiente del agente promotion_qa; detenerse para decisión humana ante hallazgos.
---

# Integrar fuente de promociones V2

Usar esta skill cuando el usuario solicite integrar una fuente de banco/billetera o invocar `$integrate-promotion-source`. Leer `AGENTS.md`. **Codex principal desarrolla y coordina**; no hay un subagente de desarrollo obligatorio. La auditoría corresponde a `promotion_qa` en contexto nuevo.

## 1. Alcance y plan breve

- Inspeccionar `git status`, `backend/normalization/models.py`, `backend/scraping/models.py`, `backend/synchronization/runner.py`, integración comparable y tests.
- Identificar URLs oficiales y el alcance: campañas, categorías, filtros, paginación, detalles, versiones por medio de pago/segmento. Informar brevemente qué se capturará y qué archivos se prevé modificar.
- Una petición de integrar una fuente autoriza implementar y probar esa fuente, **no** sincronizar base de datos, editar Actions/migraciones, push ni merge.

## 2. Implementación del Codex principal

- Crear scraper, normalizador V2 y entrypoint `sync_<fuente>.py` (sin ejecutarlo); agregar fixtures pequeñas y tests ordinarios. No modificar el contrato común salvo que el usuario pida ese trabajo explícitamente.
- `scrape()` devuelve candidato en memoria sin escribir snapshots; extraer evidencia raw completa, IDs/URLs/legales, detección de errores, paginación y cobertura real.
- Normalizar todos los tipos de beneficios y sus variantes, topes/mínimos/stock/usos, pagos, fechas desconocidas, días, canales, comercios/condiciones según `backend/normalization/models.py`. Ningún fallback comercial inventado ni eliminación silenciosa de registros.
- Reutilizar el runner y bloquear pérdida de datos antes de guardar o upsertear. El guardado específico debe ser atómico, rechazar detalles obligatorios vacíos e IDs previos desaparecidos/sustituidos sin revisión. Baseline ausente en CI = riesgo no resuelto.
- Agregar regresiones con mocks: captura parcial, campos esenciales vacíos bajo 200, 65→56 IDs, reemplazo de IDs con igual total, altas/actualizaciones legítimas, raw/variantes con IDs malos, guardado rechazado, upsert parcial y desactivación sin todos los permisos.
- Ejecutar tests específicos y `python -m pytest -q tests` desde `backend/` si es posible. Comparar valores normalizados con la fuente oficial (hasta 30 campañas: todas; catálogo mayor: muestra diversa). No correr `SyncRunner.run()`, tampoco `--validate-only`, sin autorización expresa.

## 3. Una auditoría independiente

- Al completar desarrollo, delegar a **una sesión nueva** del agente `promotion_qa`, indicando nombre y URLs oficiales de la fuente y dónde está la implementación, **sin pasar los resultados del desarrollador como verdad esperada**. Debe investigar los hechos oficiales primero.
- Verificar que existió una delegación real al rol personalizado; `promotion_qa` es un nombre de agente, **no un modelo**. Si el cliente no permite delegar de forma independiente, devolver BLOCKED; nunca inventar una auditoría.
- QA no modifica archivos. Sus instrucciones no imponen sandbox de solo lectura: reportar si la restricción fue solo por instrucciones. Evitar ediciones concurrentes.
- QA inspecciona fidelidad comercial y las cinco decisiones distintas: `catalog_complete`, `normalization_complete`, `snapshot_replace_allowed`, `requires_review`, `safe_to_deactivate`. Nada habilita desactivación por inferencia.

## 4. Parada para control humano

- QA `PASS` → `READY_FOR_HUMAN_REVIEW`; **no** sincronizar, publicar ni incorporar automáticamente.
- QA `FAIL` → `NEEDS_CHANGES`: entregar hallazgos QA-### y **detenerse**; no corregir ni repetir QA hasta una nueva indicación del usuario.
- QA `BLOCKED` → `BLOCKED`: identificar evidencia/acceso faltante, no inventar defectos ni realizar otro intento automático.
- Ante una solicitud posterior de corrección: arreglar hallazgos con tests de regresión y convocar un **QA nuevo**, no reutilizar conclusiones previas; máximo tres auditorías por integración si el usuario pide iterar.

## Informe final breve

Entregar: fuente y fecha de observación, archivos cambiados, pruebas y resultados reales, campañas raw / variantes V2 / exclusiones justificadas, cinco decisiones de integridad (YES/NO/UNKNOWN/NOT EXPOSED según origen), hallazgos pendientes, estado final, evidencia de delegación y confirmación de que **no hubo sincronización, despliegue ni modificaciones de workflows**. Priorizar hechos verificables y riesgos, no una checklist extensa.
