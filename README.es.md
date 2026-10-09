<p align="center">
  <a href="README.md">🇬🇧 English</a> |
  <a href="README.es.md">🇦🇷 Español</a>
</p>

# Promociones Bancarias

![Status](https://img.shields.io/badge/STATUS-EN%20DESARROLLO-4C9A2A)
![Python](https://img.shields.io/badge/Python-3776AB?logo=python\&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?logo=pydantic\&logoColor=white)
![Supabase](https://img.shields.io/badge/Supabase-3FCF8E?logo=supabase\&logoColor=white)
![GitHub Actions](https://img.shields.io/badge/GitHub%20Actions-2088FF?logo=githubactions\&logoColor=white)
![Pytest](https://img.shields.io/badge/Tests-Pytest-0A9EDC?logo=pytest\&logoColor=white)

# Descripción

Sistema para centralizar y consultar promociones bancarias y beneficios de diferentes medios de pago disponibles en Argentina.

El objetivo es facilitar el ahorro permitiendo encontrar descuentos, reintegros y promociones de manera rápida y sencilla, evitando tener que revisar individualmente las páginas o aplicaciones de cada banco, billetera virtual o comercio.

El proyecto recopila información de distintas fuentes, conserva los datos originales, los transforma en un formato común y los almacena en una base de datos que se actualiza periódicamente.

Actualmente cuenta con un backend desarrollado en Python que permite extraer, normalizar y sincronizar promociones de Galicia, BBVA y Patagonia.

Actualmente, la información es utilizada por [Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant), otro proyecto personal que permite consultar las promociones directamente desde Telegram. A futuro, tengo previsto incorporar una interfaz web independiente.

# Decisiones de diseño

## Separación entre scraping y normalización

Cada banco publica sus promociones utilizando estructuras y formatos diferentes. Algunos proporcionan información mediante APIs, mientras que otros requieren extraerla de páginas HTML.

Por este motivo, el proyecto separa la obtención de información de su procesamiento.

Los **scrapers** se encargan de recuperar y conservar los datos originales de cada fuente, mientras que los **normalizadores** transforman esa información en una estructura común.

## Modelo de datos unificado

Las promociones se representan mediante modelos definidos con **Pydantic**, que permiten estructurar y validar la información obtenida de diferentes fuentes.

El modelo contempla datos como:

* Banco de origen e identificador de la promoción.
* Comercio, categoría y descripción.
* Porcentaje de descuento y cuotas sin interés.
* Vigencia y días de aplicación.
* Topes de reintegro y condiciones.
* Medios de pago admitidos.
* Canales de compra y modalidades de pago.
* Requisitos de elegibilidad y términos legales.

Como no todas las fuentes proporcionan la misma información, el modelo admite campos opcionales para aquellos datos que no están disponibles.

## Supabase como persistencia

Las promociones normalizadas se almacenan en **Supabase**, utilizando PostgreSQL como base de datos.

Cada promoción se identifica mediante la combinación de su fuente y su identificador original, lo que permite actualizar registros existentes mediante operaciones de *upsert* sin generar duplicados.

El sistema también registra cuándo fue encontrada por última vez cada promoción.

Cuando una extracción se completa correctamente, las promociones que ya no aparecen en la fuente pueden marcarse como inactivas.

Para evitar desactivar promociones válidas por errores de extracción, el proceso omite esta operación cuando el scraping está incompleto.

## Automatización de sincronizaciones

El proyecto utiliza **GitHub Actions** para ejecutar periódicamente los procesos de extracción, normalización y actualización de la base de datos.

Cada banco se procesa de manera independiente, permitiendo que un error en una fuente no impida intentar sincronizar las restantes.

La lógica de sincronización está centralizada en `SyncRunner`.

Las sincronizaciones también pueden ejecutarse manualmente, tanto desde GitHub Actions como desde el entorno local.

# Testing

El proyecto utiliza **pytest** para probar el comportamiento de los scrapers y normalizadores.

Los tests permiten verificar aspectos como la obtención de datos, el procesamiento de respuestas y la transformación de promociones al modelo común.

En las pruebas de scraping se utilizan respuestas HTTP simuladas para comprobar determinados comportamientos sin depender de las páginas reales de los bancos.

# Integración con otros proyectos

Este proyecto forma parte de un conjunto de herramientas personales que pueden utilizarse de manera independiente o integrarse entre sí.

Actualmente se encuentra integrado con **[Telegram Personal Assistant](https://github.com/PabloBottinelli/telegram-personal-assistant)**, que proporciona una interfaz conversacional para consultar las promociones.

La integración mantiene separadas las responsabilidades:

* **Promociones Bancarias:** recopilación, procesamiento, normalización y almacenamiento de datos.
* **Telegram Personal Assistant:** recepción de consultas, búsqueda de promociones y presentación de resultados.

Ambos proyectos se comunican mediante Supabase, sin que el asistente necesite conocer ni ejecutar los procesos internos de extracción y sincronización.

# Próximas mejoras

* Incorporar nuevas fuentes bancarias y billeteras virtuales.
* Mejorar la normalización y el reconocimiento de condiciones particulares de cada promoción.
* Ampliar las posibilidades de búsqueda y filtrado por comercio, medio de pago, banco y categoría.
* Desarrollar una interfaz web para consultar y comparar promociones.
* Ampliar la cobertura de tests y automatizar su ejecución.
* Mejorar el seguimiento de errores y resultados de las sincronizaciones.
* Incorporar herramientas para detectar promociones equivalentes entre diferentes fuentes.

# Autor

| [<img src="https://github.com/PabloBottinelli.png" width="115"><br><sub>Pablo Bottinelli</sub>](https://github.com/PabloBottinelli) |
| :---------------------------------------------------------------------------------------------------------------------------------: |
