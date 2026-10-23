# Escenarios recuperados de QA-011 y QA-012

`qa011_qa012_matrix.json` conserva las entradas y expectativas de los 38 escenarios ejecutados por stdin en la auditoría `/root/bbva_qa005_audit`. El generador exacto se recuperó de esa sesión como una consulta documental, sin inspeccionar código, ejecutar pruebas ni emitir una auditoría nueva. No son textos publicados por BBVA: son casos sintéticos del auditor anterior.

| Grupo | Casos | Resultado original |
| --- | --- | --- |
| Seis etiquetas inline, cierre antes del tope ilustrativo | 6 | Falso positivo |
| Seis etiquetas inline, cierre antes del porcentaje ilustrativo | 6 | Falso positivo |
| Ocho formas delimitadas, contrato 16000 frente a API 20000 | 8 | Bloqueo correcto |
| Ocho formas delimitadas, contrato y API 20000 | 8 | Aceptación correcta |
| Punto, punto y coma o salto; contrato 16000 | 3 | Bloqueo correcto |
| Punto, punto y coma o salto; contrato 20000 | 3 | Aceptación correcta |
| Exclamación o interrogación; contrato 16000 | 2 | Falso negativo |
| Exclamación o interrogación; contrato 20000 | 2 | Aceptación correcta |

Resultado original: 24 satisfechos y 14 fallidos. Se conservan los espacios finales de los IDs inline del generador. Los IDs de puntuación se serializan con comillas JSON; sus entradas y expectativas son las originales. No se conservaron los mensajes individuales de excepción de los 24 controles satisfechos.

Antes de corregir la implementación, `test_original_38_independent_expectations` reprodujo los 14 fallos. Cuatro regresiones adicionales de guardado reprodujeron la aprobación incorrecta de los dos falsos negativos, con revisión inicial normal o diferida. Las pruebas de snapshot usan baseline temporal previo válido.

## Diseño del procesamiento

`bbva_evidence.py` mantiene cuatro responsabilidades separadas:

1. `project_html` recorre el árbol con BeautifulSoup. Los bloques, saltos, separadores, filas y celdas conservan límites; las etiquetas inline no crean cortes.
2. `clause_ranges` recorre caracteres y reconoce límites de oración y cláusula, números y delimitadores balanceados. Los dos puntos ligan etiquetas a valores; no se tratan como finales universales de ejemplo.
3. `parse_legal_evidence` conserva texto, posiciones y clasificación contractual, ilustrativa o ambigua. Los ejemplos entre paréntesis o comillas tienen un alcance explícito. Una declaración sin cuerpo, delimitación abierta, topes múltiples sin separación o ciertos usos ambiguos de dos puntos bloquean el análisis.
4. El normalizador extrae importes de la evidencia contractual con una gramática monetaria acotada. Verifica que menciones e importes contractuales queden explicados; los formatos o atribuciones sin resolver requieren revisión.

Las expresiones regulares permanecen como reconocedores léxicos de palabras, cantidades y formas monetarias soportadas. No deciden el final de ejemplos mediante cierres inline ni cortes globales desde la primera aparición de “Ejemplo”. La segmentación y clasificación se comparten entre normalización, comparación de topes y revisión comercial. Mínimos, moneda y otras condiciones normalizadas usan la evidencia contractual; `terms` conserva todo el texto legal proyectado y el raw mantiene el HTML original.

## Cambio explícito de expectativa previa

Las dos entradas antiguas con `<span>Ejemplo: ...tope 12000</span> Tope ...`, sin puntuación ni separación estructural entre ambos topes, permanecen en `test_bbva_html_clauses.py` como casos ambiguos. Un cierre inline por sí solo no aporta una separación contractual fiable. Se comprueba bloqueo con contrato 16000 o 20000, con o sin importe API, y rechazo del reemplazo del snapshot. No se usan para afirmar un conflicto explícito ni una aprobación comercial.

Los casos con delimitación real siguen exigiendo conflicto explícito 20000/16000 o aceptación 20000/20000, según corresponda. Las pruebas ampliadas también cubren moneda y mínimos ilustrativos, sintaxis monetaria no explicada, importes arbitrarios, anidamiento, continuidad inline y conservación de cláusulas posteriores.

La gramática no pretende resolver cualquier ambigüedad de lenguaje natural. Ante evidencia insuficiente se requiere revisión. Los resultados de desarrollo y la auditoría posterior deben informarse por separado.
