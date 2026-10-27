# Piloto 1 — feedback visual de acciones

Fecha: 2026-10-27. Repositorio exclusivo: Produccion Besten. Branch `master`,
base `a0da26f02ce0aa6cf8d40800fdaf031e8d4d9f07`. Sin commit ni push.

## Alcance y auditoría

Los comandos mutantes principales de la UI pasan por `api/client.request`.
Había feedback desigual: algunos componentes mostraban mensajes locales, otros
cambiaban estado o navegaban sin confirmación visible. El editor usaba además
«Definición guardada» para guardar, validar, congelar y abrir otra revisión.

Se agrega un único sistema de notificaciones en `frontend/src/notifications`,
montado en Root fuera del Outlet. El cliente HTTP publica el resultado después
de recibir y deserializar la respuesta; no publica éxito al pulsar un botón.
Las consultas GET/HEAD no generan toasts ni ruido durante refetch automático.

| Comando auditado | Confirmación |
| --- | --- |
| Guardar borrador | Borrador guardado correctamente. |
| Validar definición válida | Definición validada correctamente. |
| Validar con pendientes | Hay errores que deben corregirse antes de congelar. |
| Congelar | Revisión congelada correctamente. |
| Nueva revisión | Nueva revisión creada correctamente. |
| Liberar | Proyecto liberado a planificación. |
| Retirar liberación | Proyecto retirado de planificación. |
| Simular proyecto/replan/instalación | Simulación generada correctamente. |
| Simulación incompleta | Advertencia para revisar operaciones pendientes y bloqueos. |
| Move/resize del Gantt | Simulación del cambio generada correctamente. |
| Aceptar plan | Nuevo plan confirmado. |
| Descartar propuesta | Propuesta descartada correctamente. |
| Medición/replanteo | Medición/replanteo registrado correctamente. |
| Ubicación de instalación | Ubicación actualizada correctamente. |
| Crear cliente | Cliente creado correctamente. |
| Crear/editar proyecto | Proyecto creado/actualizado correctamente. |
| Archivar/cambiar estado | Registro archivado/estado actualizado correctamente. |
| Estimación restante | Estimación restante guardada correctamente. |
| Iniciar/finalizar operación | Operación iniciada/fase finalizada correctamente. |
| Tramo de ejecución | Tramo de ejecución registrado correctamente. |
| Cerrar proyecto | Proyecto cerrado correctamente. |
| Maestros, skills, calendarios y etapas | Cambios guardados correctamente. |
| Cambio que requiere reconciliación | Cambios guardados. El plan requiere reconciliación. |

Las mutaciones futuras sin una etiqueta específica reciben una confirmación
genérica, sin interpolar URLs, códigos técnicos ni identificadores internos.

## Comportamiento visual y accesibilidad

- SUCCESS/ERROR/WARNING/INFO comparten componente, posición y controles.
- Success/info usan `role=status` y aria-live polite; los errores usan role alert
  y assertive. Las advertencias se anuncian de forma polite. aria-atomic evita
  anunciar fragmentos sueltos del mensaje.
- No se llama a focus ni se usan alertas del navegador. Las confirmaciones
  de negocio ya existentes se conservan.
- Success/info permanecen seis segundos; warning, nueve. Los errores permanecen
  hasta cerrarlos o hasta que un resultado nuevo de la misma acción los reemplace.
- Todos pueden cerrarse con un botón accesible. Se muestran como máximo tres,
  con variantes visuales que incluyen texto, además del color. No hay animaciones.
- Sólo el botón de cierre captura clics; el texto y fondo del toast los dejan
  pasar a la pantalla. Esto evita tapar GUARDAR durante una recuperación de error
  en móvil. No hay overlay modal, bloqueo global ni estado de loading compartido entre
  acciones independientes. Se conservan los bloqueos locales existentes necesarios
  para mantener el contexto de cada intención.
- El store está fuera de las pantallas. El aviso se conserva al cambiar de ruta
  o al remontar un editor después de actualizar su versión. Se prueba expresamente
  simulación → ABRIR PLANIFICACIÓN → Gantt con el mismo aviso visible.

Se agregan textos de espera a guardar/validar/congelar/nueva revisión, creación
de cliente, guardado de proyecto, liberación, simulación, confirmación de plan y
ubicación/plan de instalación. Se mantienen los botones deshabilitados durante
la petición y los controles de intención existentes. No se cambian headers,
Idempotency-Key, payloads, endpoints, reintentos ni reglas de negocio.

## Validación y errores

Validar con HTTP 200 y una lista de errores produce WARNING, conservando la
lista específica del editor y el bloqueo de freeze. Se retira el mensaje local
genérico que decía guardado incluso al validar. Un resultado incompleto de
simulación no se presenta como planificación completa.

Cada fallo mutante publica un resumen contextual de error. El formulario
conserva sus mensajes de dominio útiles, inputs y acciones de actualización/retry.
En los diálogos nativos se mantiene ese detalle inline visible durante el error;
el éxito sigue visible globalmente al cerrar el diálogo.

`ApiError.message` ahora se sanea antes de llegar a cualquier vista. Los errores
5xx no muestran la excepción remota. Los mensajes técnicos con stack traces,
SQL/SQLSTATE, nombres de drivers o rutas se sustituyen por texto comprensible;
los UUID se ocultan en mensajes de error. Los detalles de dominio seguros de
4xx se mantienen. Los logs de diagnóstico conservan método, ruta, estado y código;
el backend conserva su logging previo. No se registran payloads ni claves de
idempotencia en el log añadido.

Un error de transporte o una respuesta ilegible se representa como resultado
incierto (503/502), de modo que las convenciones existentes retienen la misma
clave y payload al reintentar. No se convierte en un fallo conocido que pudiera
permitir repetir la acción con otra intención. Un éxito del retry reemplaza el
toast de error anterior de esa acción.

## Pruebas y límites de la intervención

Vitest completo: **194 aprobadas**. Incluye confirmaciones por acción,
validación con pendientes, error sin success, sanitización, ausencia de éxito
prematuro, doble click con una sola request, botón pendiente, cierre/expiración,
aria-live, foco conservado, sustitución del error y navegación con feedback.

Regresión backend relevante: **154 aprobadas**, en base PostgreSQL descartable:
editor, liberación, clientes, primer escenario e instalaciones. No hay cambios
backend, de contrato ni migraciones, por lo que no se repitió el backend completo.
Los dos warnings de dependencias conocidos continúan.

Playwright relevante: 88 casos de definición, cliente, liberación y primer plan
aprobaron en las cuatro resoluciones. Se ejecuta también la suite completa.
TypeScript y Vite build aprobados; subsiste el warning conocido de bundle grande.
Los tests distinguen el resumen global del error y su detalle inline, y reconocen
las etiquetas de espera. No se alteraron aserciones sobre claves ni cantidad de
requests.

La tarea no corrige datos de REV 3 ni el resumen duplicado de personas auditado
anteriormente: son asuntos separados del feedback de comandos. No se guardó,
validó, congeló, liberó, simuló ni aceptó nada sobre A685 real.

## Base real y aislamiento

La huella SHA-256 de las filas completas de las 87 tablas, ordenadas por su JSON,
se registra antes de los cambios y se compara al cierre:
`b650ead377abb6fa247b7d51c5d677af1b22ad669c9c659e63505eee96619afe`.

Estado inicial: A685 activo, row_version 25, REV 3 congelada, CURRENT NULL y
siete simulaciones. No se creó REV 4. Las consultas de auditoría se realizan con
transaction_read_only=on; todos los comandos de las pruebas se aíslan mediante
fixtures HTTP o una base descartable.

No se accedió ni modificó App de Compras ni el backup. No se crearon archivos
de entorno, credenciales, migraciones ni cambios de autenticación productiva.

## Cierre de validación

Playwright completo final: **238 aprobadas**, 14 omisiones preexistentes y cero
fallas. Incluye recuperación desde error en móvil con los avisos visibles, cierre
manual por puntero y navegación al Gantt con feedback. Las capturas de escritorio
y móvil fueron inspeccionadas.

La huella de las 87 tablas al cierre coincide con la inicial; A685 conserva
row_version 25, REV 3 y siete simulaciones, CURRENT vacío. No se modificaron datos
reales ni se creó REV 4.

Escaneo de 242 archivos: cero candidatos nuevos a secretos, dos coincidencias de
ejemplo preexistentes sin cambios. Diff-check y whitespace de archivos nuevos
aprobados. Backend, migraciones y OpenAPI sin cambios; nada staged.

`git status --short`:

```text
 M frontend/src/api/client.ts
 M frontend/src/features/gantt/GanttPage.tsx
 M frontend/src/features/projects/CustomerDialog.tsx
 M frontend/src/features/projects/Installations.tsx
 M frontend/src/features/projects/ProductEditor.test.tsx
 M frontend/src/features/projects/ProductEditor.tsx
 M frontend/src/features/projects/ProductionReadiness.tsx
 M frontend/src/features/projects/ProductionReadinessTime.test.tsx
 M frontend/src/features/projects/Projects.tsx
 M frontend/src/routes/Root.tsx
 M frontend/src/test/setup.ts
 M frontend/tests/customer-create.spec.ts
 M frontend/tests/initial-simulation.spec.ts
 M frontend/tests/master-data.spec.ts
 M frontend/tests/product-editor.spec.ts
 M frontend/tests/production-release.spec.ts
 M frontend/tests/projects.spec.ts
?? docs/40-feedback-acciones-v1.md
?? frontend/src/notifications/
```

`git diff --stat` (tracked; los seis nuevos se detallan en el catálogo anterior):

```text
 frontend/src/api/client.ts                         | 38 +++++++++++++---
 frontend/src/features/gantt/GanttPage.tsx          |  4 +-
 frontend/src/features/projects/CustomerDialog.tsx  |  2 +-
 frontend/src/features/projects/Installations.tsx   |  4 +-
 .../src/features/projects/ProductEditor.test.tsx   | 38 ++++++++++++++++
 frontend/src/features/projects/ProductEditor.tsx   |  9 ++--
 .../src/features/projects/ProductionReadiness.tsx  |  4 +-
 .../projects/ProductionReadinessTime.test.tsx      |  2 +-
 frontend/src/features/projects/Projects.tsx        |  2 +-
 frontend/src/routes/Root.tsx                       |  3 +-
 frontend/src/test/setup.ts                         |  4 +-
 frontend/tests/customer-create.spec.ts             |  1 +
 frontend/tests/initial-simulation.spec.ts          |  1 +
 frontend/tests/master-data.spec.ts                 |  4 +-
 frontend/tests/product-editor.spec.ts              | 51 +++++++++++++++++++++-
 frontend/tests/production-release.spec.ts          |  6 ++-
 frontend/tests/projects.spec.ts                    |  2 +-
 17 files changed, 148 insertions(+), 27 deletions(-)
```

Conclusión: **PILOT_ACTION_FEEDBACK_IMPLEMENTED**.
