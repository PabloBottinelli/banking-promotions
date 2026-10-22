<p align="center">
  <a href="README.md">🇬🇧 English</a> |
  <a href="README.es.md">🇦🇷 Español</a>
</p>

# Promociones Bancarias

![Estado](https://img.shields.io/badge/Estado-En%20desarrollo-4C9A2A)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)
![Pytest](https://img.shields.io/badge/Tests-Pytest-0A9EDC?logo=pytest&logoColor=white)

Sistema para centralizar y consultar promociones bancarias y beneficios de diferentes medios de pago disponibles en Argentina.

El objetivo es facilitar el ahorro permitiendo encontrar descuentos, reintegros y promociones de manera rápida y sencilla, evitando tener que revisar individualmente las páginas o aplicaciones de cada banco, billetera virtual o comercio.

El proyecto recopila información de distintas fuentes, conserva los datos originales, los transforma en un formato común y los almacena en una base de datos que se actualiza periódicamente.

Actualmente cuenta con un backend desarrollado en Python que permite extraer, normalizar y sincronizar promociones de **BBVA, Buepp, Banco del Sol y Patagonia**.

La información es utilizada por [Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant), otro proyecto personal que permite consultar las promociones directamente desde Telegram. A futuro, tengo previsto incorporar una interfaz web independiente.

## Decisiones de diseño

### Separación entre captura, normalización y persistencia

Cada fuente publica sus promociones utilizando estructuras y formatos diferentes. Por este motivo, el proyecto separa la obtención de información de su procesamiento y almacenamiento:

1. Los **scrapers** recuperan los datos originales e informan si la extracción se completó.
2. Los **normalizadores** transforman cada registro en una o más variantes validadas con **Pydantic**.
3. **SyncRunner** valida los datos antes de solicitar el guardado del snapshot y sincronizarlos con **Supabase**.

Esta separación permite adaptar la captura de cada fuente sin modificar el contrato común utilizado por el resto del sistema.

### Modelo de datos unificado

El modelo representa beneficios, topes monetarios, mínimos de compra, stock, límites de uso, medios de pago, vigencias, días de aplicación, canales de compra, condiciones y términos legales.

También conserva la URL oficial y permite indicar cuándo es necesario consultar un listado externo de comercios adheridos.

Una campaña puede generar varias variantes cuando sus beneficios dependen de condiciones diferentes. Cada variante tiene un `source_id` estable y único dentro de su fuente; `promotion_group_id` permite relacionar las variantes de una misma campaña.

Como no todas las fuentes proporcionan la misma información, el modelo admite datos desconocidos. 

### Supabase como persistencia

Las promociones normalizadas se almacenan en **Supabase**, utilizando PostgreSQL como base de datos.

Cada variante se identifica mediante la combinación `(source, source_id)`, lo que permite actualizar registros existentes mediante operaciones de *upsert* sin generar duplicados.

El sistema registra si cada promoción está activa mediante `active` y cuándo fue encontrada por última vez mediante `last_seen_at`.

La desactivación de promociones ausentes está implementada, pero permanece deshabilitada actualmente porque requiere mejoras de seguridad para no desactivar erróneamente.

### Validación antes de escribir

El runner comprueba que la captura esté completa y que los registros tengan identificadores válidos y únicos. También verifica que cada registro crudo produzca variantes normalizadas válidas antes de solicitar el guardado o acceder a Supabase.

Si una fuente informa que su snapshot no puede reemplazarse o que requiere revisión, el proceso bloquea la sincronización.

### Automatización de sincronizaciones

El proyecto utiliza **GitHub Actions** para ejecutar los procesos de extracción, normalización y actualización de la base de datos.

La sincronización programada se ejecuta **una vez por semana**. 

Cada fuente se procesa en un job independiente, permitiendo que un error en una no impida intentar sincronizar las restantes.

La lógica de sincronización está centralizada en `SyncRunner`. Las fuentes incluidas en el workflow también pueden ejecutarse manualmente desde GitHub Actions.

## Pruebas

El proyecto utiliza **pytest** para verificar el comportamiento de los scrapers, normalizadores, el exportador JSON, la estructura del modelo y los controles del runner.

Las pruebas utilizan mocks y fixtures para evaluar la obtención y transformación de datos sin depender de consultas a los sitios reales.

También se comprueban escenarios de error, como capturas incompletas, identificadores duplicados, fallos de normalización y restricciones de desactivación.

## Desarrollo asistido

El desarrollo se realiza con asistencia de Codex, siguiendo las reglas definidas en `AGENTS.md` y la skill de integración de fuentes.

Codex principal implementa y coordina el trabajo, mientras que `promotion_qa` realiza una auditoría en un contexto independiente.

Un resultado QA `PASS` significa que la implementación esta lista para revisar; no autoriza por sí mismo una sincronización automática.

## Integración con otros proyectos

Este proyecto forma parte de un conjunto de herramientas personales que pueden utilizarse de manera independiente o integrarse entre sí.

Actualmente se encuentra integrado con **[Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant)**, que proporciona una interfaz conversacional para consultar las promociones.

La integración mantiene separadas las responsabilidades:

- **Promociones Bancarias:** recopilación, procesamiento, normalización y almacenamiento de datos.
- **Telegram Personal Assistant:** recepción de consultas, búsqueda de promociones y presentación de resultados.

Ambos proyectos se comunican mediante Supabase, sin que el asistente necesite ejecutar los procesos internos de extracción y sincronización.

## Próximas mejoras

- Incorporar una referencia histórica persistente por fuente para detectar pérdidas entre ejecuciones.
- Mejorar el seguimiento de errores y la recuperación frente a escrituras parciales.
- Ampliar la cobertura de pruebas y automatizar su ejecución en CI.
- Mejorar la extracción de condiciones y sumar bancos y billeteras.
- Detectar promociones equivalentes entre fuentes.
- Desarrollar una interfaz web de consulta y comparación.

## Autor

[Pablo Bottinelli](https://github.com/PabloBottinelli)