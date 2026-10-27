# Piloto 1 — revisión de la primera simulación sin CURRENT

Base: `master`, `286fe01db3da92883294e4279ba5365c7aad8a45`.
Se preservan los cambios pendientes del diagnóstico de permisos de A685.
Clasificación: **FUNCTIONAL_BLOCKER + UX**. Resultado: **SIMULATION_EXISTS**.

## Evidencia real, sólo lectura

Existen **dos**, no una única simulación reciente de A685:

| Hora local, 2026-10-26 | Scenario | ScheduleSolution |
| --- | --- | --- |
| 13:31:41 | f0a46d2f-1eb9-45d1-80d6-5eab94805784 | 88541e34-7ee7-420a-913b-4fe5b8314f04 |
| 13:31:46 | 16b169b0-8512-4b5d-a7ee-7420d60733f8 | dd5d9aea-9bce-4dc8-88a8-a2c24669c3b0 |

Ambas son `initial`, estado `ready` (cálculo terminado), **complete=false**:
0 fases planificadas, 1 bloqueada, 3 fuera de horizonte por precedencias.
Terminaron a 13:31:41.937246 y 13:31:46.186361, respectivamente.
No se creó otra simulación ni se decidió cuál representa la intención del usuario.

Proyecto `7e3f3c2e-d102-41b6-b2b0-ff2780af99a1`, A685 / Alacenas, activo,
row_version 21, liberado para la revisión productiva 2 congelada:
`7a83793f-a8a3-413c-b74e-c50b20593efc`.
Base operativa: `a6a24931-4be6-495e-af0d-8515d18a7862`.
No existe CURRENT. Las dos soluciones conservan exactamente esos mismos insumos.

## Qué calculó el scheduler

En ambas soluciones **no se programó ninguna operación**. Todas tienen inicio y
fin NULL; no hay personas, centros ni recursos asignados, ni fecha final estimada.
Las duraciones son las duraciones definidas pendientes, no tramos ejecutados:

| Operación | Duración | Predecesor | Resultado |
| --- | --- | --- | --- |
| Corte | 20 min | Ninguno | blocked / REQUIRED_SKILL_UNAVAILABLE |
| Multiple | 60 min | Corte | out_of_horizon / PREDECESSOR_NOT_FINISHED |
| Armado | 120 min | Multiple | out_of_horizon / PREDECESSOR_NOT_FINISHED |
| Instalacion | 180 min | Armado | out_of_horizon / PREDECESSOR_NOT_FINISHED |

Evidencia del bloqueo: el horizonte empieza en `2026-10-26T00:00:00Z`, que equivale
a **25/10 21:00** en America/Argentina/Cordoba. Las habilidades de personas tienen
vigencia desde **26/10 local**. El cargador actual exige vigencia durante todo el
horizonte, incluido su comienzo; el snapshot efectivamente contiene los tres
empleados con `skills: []`. Por eso Corte no encuentra personal elegible en esos
insumos, aunque las 14 habilitaciones existen en los maestros.

Además, el snapshot real exige centro **Armado para Corte**, no Escuadradora;
Multiple y Armado no incluyen requerimiento físico. Instalacion requiere skill
**Armado**, no Instalación. Se informa para revisión del usuario: **no se cambió
ningún dato del proyecto, requisito, skill, horizonte ni algoritmo**.

## Causas de la invisibilidad

1. ABRIR PLANIFICACIÓN enlazaba a `/planning/gantt` sin conservar `scenario_id`.
2. La lectura Gantt exigía un JOIN con CURRENT antes de consultar el escenario.
3. La selección y lista de escenarios sólo admitían `replan`, no `initial`.
4. ACCEPT también admitía únicamente `replan` y exigía un plan publicado previo.

## Corrección

Se reutilizan Gantt, ScheduleSolution y ACCEPT existentes:

- El enlace conserva el ID devuelto por la generación; Gantt lee `scenario_id`
  desde la URL y permite abrir propuestas existentes directamente.
- Sin CURRENT, se listan los escenarios iniciales disponibles, distinguidos por
  fecha/hora e ID. Sin selección no se elige uno automáticamente.
- La consulta seleccionada usa la solución inicial como origen de operaciones,
  sin crear un plan ni inventar IDs. El contrato permite plan/versión NULL.
- La tabla inicial muestra todas las operaciones, precedencias, duración, fechas,
  personas, centros, recursos y bloqueos. Las sin fechas siguen siendo visibles.
  El orden de presentación respeta precedencias. El timeline se sitúa al comienzo
  de las fechas propuestas cuando existen; no se habilita ajuste manual sin plan.
- Una propuesta incompleta se identifica explícitamente; ACCEPT está deshabilitado
  y el backend lo rechaza con 409 aunque se intente directamente.
- Una propuesta inicial completa puede aceptarse **sólo con el comando explícito**:
  las validaciones de tenant, revisiones, lock, solución, auditoría, outbox,
  idempotencia y rollback se conservan. `previous_plan_version_id` puede ser NULL.
- Volver desde la vista inicial no debe aceptar ni rechazar la simulación.

No hay migraciones ni un sistema paralelo de planificación. No se modificó el
scheduler ni los datos reales.

## Validación

PostgreSQL descartable: regresión HTTP de proyecto liberado sin CURRENT,
generación, retry sin duplicar, revisión con personas/recursos/fechas, ausencia de
auto-accept, aceptación explícita y primer CURRENT. También escenario incompleto
visible/rechazado, aislamiento y rollback después de escribir el puntero CURRENT.

Backend completo: **533 passed**, incluidos los dos tests pendientes de permisos
y tres nuevos casos del escenario inicial; sólo los dos warnings conocidos.
Vitest completo: **167 passed**, con selección por URL, selección manual y bloqueo
de aceptación incompleta. TypeScript y Vite build aprobados. OpenAPI exportado
desde FastAPI y tipos regenerados con el tooling existente.
Playwright completo: **210 passed, 14 skips preexistentes, 0 failed**. Tras cerrar
la acción VOLVER SIN ACEPTAR se repitieron los 8 casos de simulación inicial en
las cuatro resoluciones, todos aprobados, y los 3 Vitest específicos. No se suman
esos subconjuntos al total como pruebas adicionales.

Verificación de la UI real para ambos escenarios: HTTP 200, cuatro operaciones
visibles en orden, advertencia de solución incompleta y ACCEPT deshabilitado.
Las verificaciones interceptaron y bloquearon cualquier petición que no fuera GET:
ninguna generación ni aceptación se ejecutó en la base del piloto.

## Estado y entrega

Se conservaron las dos simulaciones reales y A685. El usuario puede abrir cada una
con `/planning/gantt?scenario_id=...`; no necesita generarlas de nuevo.
CURRENT continúa NULL. Sin commit ni push. App de Compras y backup no accedidos,
inspeccionados ni modificados.

La comparación de las filas completas de las 87 tablas antes y después confirma
que los datos reales permanecen idénticos. Sin migraciones nuevas; `git diff
--check` aprobado y sin secretos nuevos en el escaneo.

Conclusión: **PILOT_FIRST_SIMULATION_VISIBLE**. Visibilidad corregida; las dos
propuestas reales siguen incompletas y requieren revisar sus insumos antes de
generar otra, mediante una acción posterior explícita del usuario.
