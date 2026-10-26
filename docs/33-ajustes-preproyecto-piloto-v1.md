# Piloto 1 — ajustes mínimos previos al primer proyecto

Fecha: 2026-10-26. Base de código: `master`,
`f62de6498b504c1b51874fa60dae4266d2335f9e`. Sin commit ni push.

## Instalaciones

El editor productivo y la evaluación de instalaciones aceptan requisitos humanos
obligatorios entre 1 y 6 personas. El campo del frontend muestra ese máximo sólo
para instalaciones. El scheduler conserva su mecanismo y las capacidades reales:
no agrega personas ni reduce requisitos para producir una solución.

Las pruebas descartables validan definiciones de 1, 3 y 6 personas y rechazan 7.
Un requisito de 5 con sólo 3 personas elegibles queda bloqueado sin asignaciones
de instalación; tras incorporar otras 2 dentro del test se planifica con 5 por
segmento. El requisito original sigue siendo 5. Ningún empleado de prueba se
crea en `produccion_besten`.

## Prioridades persistentes

`core.projects.priority_id` es obligatorio y referencia
`core.project_priorities`; no basta con las etiquetas de la interfaz.
Se agregaron exclusivamente estas filas para Besten, con auditoría de Maximiliano:

| Código | Etiqueta | Rank | Predeterminada |
| --- | --- | --- | --- |
| URGENT | URGENTE | 1 | No |
| HIGH | ALTA | 2 | No |
| NORMAL | NORMAL | 3 | Sí |

No se alteraron el planning state inicial ni los maestros previamente cargados.

## Rutas y tipos de operación: resultado de la auditoría

`PRODUCT_DEFINITION_CAN_BE_CREATED_WITHOUT_ROUTE_CATALOG`, condicionado a tener
tipos de operación válidos: `EditorLot.route_version_id` admite `null` y
`PostgresProductEditorUnitOfWork.save_lots` crea una ruta versionada propia del
lote mediante `manual_route`, a partir de sus operaciones y precedencias reales.
El test existente `test_manual_lot_route_uses_existing_command_and_published_history`
verifica este flujo. No hace falta inventar una ruta estándar ni suponer que todos
los proyectos usan todos los procesos o un orden común.

**Bloqueo pendiente:** sí existe un catálogo global obligatorio de tipos:
`production.operation_definitions`. `EditorOperation.operation_definition_id`
es UUID obligatorio y `production.required_operations.operation_definition_id`
tiene FK obligatoria. El frontend deshabilita AGREGAR OPERACIÓN si ese catálogo
está vacío. En el piloto sigue con 0 filas.

Por la instrucción expresa de detener esa parte si existe un catálogo obligatorio,
no se cargaron tipos ni rutas. La entidad necesita confirmar los registros de tipo
de operación: nombre y categoría funcional; sus códigos son identificadores técnicos.
Los nombres de los seis procesos conocidos ya están suministrados, pero no se
presume su clasificación ni se crean registros silenciosamente. Los demás campos
obligatorios disponen de defaults del modelo (`minute`, `splittable`, estado activo).

Procesado sin Múltiple conserva únicamente su skill y la habilitación de Mariano;
no se creó centro ni recurso físico para ese proceso.

## Gantt sin CURRENT

El backend conserva HTTP 404 / `RESOURCE_NOT_FOUND`. Sólo la presentación del
Gantt actual, sin escenario seleccionado, reconoce ese contrato y muestra:

> Todavía no existe un plan vigente.
> Cargá y liberá un proyecto y generá una simulación para comenzar.

Incluye enlace a Proyectos. Los otros errores conservan REINTENTAR.
No se crea CURRENT, escenario ni plan ficticio.

## Contexto DEV persistente

Variables guardadas en el entorno de usuario de Windows, sin `.env`:

| Variable | ID real |
| --- | --- |
| VITE_DEV_ORGANIZATION_ID | cc1f3ea8-d31c-4a84-9c2b-0b207ba715f3 |
| VITE_DEV_PLANT_ID | 103863f1-96aa-47f6-9010-274386367150 |
| VITE_DEV_USER_ID | d1d67cad-e54f-4646-985d-9a01a658644b |

Se verificó un proceso Node nuevo y un proceso Vite nuevo que recarga estos valores
del entorno de usuario y los incorpora al módulo del cliente. Las terminales o
aplicaciones ya abiertas pueden conservar el entorno anterior hasta reiniciarse.
Los IDs son públicos de contexto DEV, no credenciales ni autorización productiva.

## Preservación y validación

La comparación SHA-256 de las filas completas de 14 tablas protegidas, antes y
después de los tests, confirmó que organización, planta, actor, calendario,
ventanas, personas, skills, asignaciones, centros, tipos/recursos y planning state
inicial permanecen idénticos. Continúan 3 personas, 6 skills, 14 asignaciones,
4 centros y 5 recursos; clientes y proyectos siguen en 0. Sin datos operativos
nuevos. La única carga adicional son las 3 prioridades y su auditoría.

Backend completo: 511 passed, 2 warnings preexistentes de dependencias.
Vitest completo: 157 passed. Playwright completo: 190 passed, 14 skipped,
0 failed. Son las 13 omisiones preexistentes más la del nuevo caso de Gantt
en smartphone, heredada del alcance desktop/tablet de ese archivo de pruebas.
Los 204 casos finalizaron; el preview propio de la suite requirió detener su
proceso al concluir para liberar el teardown de Windows. El runner cerró con
exit code 0. El servidor DEV del piloto permaneció operativo.
TypeScript y Vite build aprobados; persiste el warning
de bundle grande. OpenAPI y tipos se regeneraron con el tooling existente y no
presentan diferencias semánticas con HEAD: el límite por clase de operación se
valida en el editor/readiness, no en el schema genérico de requisitos humanos.
M0–M11 intactas: 8 schemas y 87 tablas, sin migraciones nuevas. Los tests backend
usaron una base/rol aleatorios descartables, eliminados al finalizar.

Se comprobó en la UI real el Gantt vacío y las tres prioridades, sin 422 por
contexto DEV. Backend reiniciado con el código actualizado y health/ready en 200.

App de Compras y backup: no accedidos, inspeccionados ni modificados.

`git diff --check` aprobado; sin secretos nuevos en el escaneo. El working tree
contiene únicamente los cambios autorizados de código/tests y este informe,
sin staging, commit ni push.

Conclusión: `PILOT_PREPROJECT_REQUIRES_ADJUSTMENTS`, por el catálogo obligatorio
de tipos de operación todavía pendiente de datos según la instrucción del pedido.
