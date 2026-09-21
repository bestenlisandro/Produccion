# Etapa 5.3 — Reprogramación ágil ante desvíos reales V1

Fecha de validación: 2026-09-18

Versión del flujo: `v1-replan-1`
Motor de factibilidad reutilizado: `v1-greedy-2`

## 1. Resultado y alcance

Se implementó el flujo explícito:

```text
realidad confirmada -> revisión restante -> frontera de impacto
-> escenario aislado -> solución -> comparación -> rechazo posible
```

Los comandos de aplicación son `REPLAN_FROM_OPERATION`, `REPLAN_PROJECT` y
`REJECT_REPLAN`. No existe `ACCEPT_REPLAN` en este incremento. Crear o rechazar un
escenario no crea `PlanVersion`, no mueve `core.plants.current_plan_version_id`, no
reescribe ejecución y no revierte una `RemainingEstimateRevision`.

No se agregaron tablas ni migraciones: el modelo físico vigente ya contenía
`scenarios`, `schedule_solutions`, `impact_items`, hashes, comparaciones, revisiones
restantes y fechas comunicadas.

## 2. Contrato transaccional

`ReplanRequest` exige organización, planta, actor, clave idempotente, cutoff,
horizonte, plan base y las revisiones de definición/estado. Debe indicar exactamente
una raíz: operación o proyecto.

La persistencia bloquea primero la planta y el head operativo. Rechaza una base si
plan, definición o estado ya no son vigentes. Bajo ese mismo lock comprueba la clave
idempotente: un retry compatible devuelve escenario/solución existentes y una
reutilización incompatible falla. Dos requests concurrentes iguales materializan
una sola solución; escenarios con claves distintas permanecen independientes.

Toda la corrida —escenario, snapshot, solución, resultados, comparación e impactos—
usa una única transacción. Un error revierte el agregado completo.

## 3. Cutoff, ejecución y saldo

El horizonte nuevo empieza en `cutoff_at`. Ningún segmento propuesto puede quedar
antes de ese instante. Operaciones reales `completed` o `cancelled` se excluyen. En
una ejecución `running` o `paused`, el planificador consume exclusivamente la
`RemainingEstimateRevision` vigente, vincula su UUID en `phase_plan_results` y no
reincorpora el trabajo histórico.

Los usos y ocupaciones reales vigentes continúan entrando como capacidad consumida.
La liberación confirmada por ejecución deja de bloquear según el modelo efectivo;
una mera simulación nunca altera esa realidad. La estimación original permanece
intacta para trazabilidad y comparación.

## 4. Frontera incremental y mínima perturbación

Desde una operación se incluyen sus sucesoras. Desde un proyecto se incluyen sus
operaciones activas. La frontera se expande por personas o recursos físicos
compartidos en el plan base después del cutoff y, al incorporar un competidor, por
sus sucesoras. No se reprograma el universo completo por defecto.

Los inicios del plan base actúan como anclas inferiores: el escenario intenta
conservarlos y sólo desplaza cuando el cutoff, la realidad, precedencias, gates o
capacidad lo exigen. La prioridad industrial vigente sigue ordenando trabajo
elegible (`URGENT`, `HIGH`, `NORMAL`, compromiso y claves semánticas), sin violar
factibilidad.

## 5. Comparación y explicación

La solución referencia `baseline_solution_id` y persiste una comparación semántica
por operación: estado, inicio, fin, saldo, delta, tipo de impacto y causa. Los cambios
se materializan además en `planning.impact_items`. El resumen declara expresamente
`current_plan_modified=false`.

La fecha propuesta final del proyecto se contrasta con la última fecha comunicada
en `portal.communicated_dates`. Un atraso produce
`PROPOSED_DATE_AFTER_COMMUNICATED_DATE`; no modifica automáticamente la fecha
visible al cliente. Los blockers detallados del scheduler se conservan en cada fase.

## 6. Rechazo y obsolescencia

`REJECT_REPLAN` acepta únicamente escenarios `replan` listos u obsoletos, usa
`row_version` para concurrencia optimista y registra razón/timestamp. Repetir el
rechazo es idempotente. La solución histórica se conserva.

Cuando se crea un escenario sobre la base vigente, los replans listos cuyas bases ya
difieren se marcan `stale`. También continúa disponible la detección calculada por
comparación de punteros. Un stale puede inspeccionarse o rechazarse, pero no se
promueve en esta etapa.

## 7. Validación PostgreSQL

Se recreó una base descartable, se aplicaron M0–M10 y pasaron los verificadores de 8
schemas y 87 tablas. Las 172 pruebas previas pasaron antes del incremento. Se
agregaron 35 casos PostgreSQL para aislamiento, cutoff, revisión restante,
comparación, impacto, inmutabilidad del plan, idempotencia, retries concurrentes,
escenarios paralelos, rechazo, conflicto de versión, stale base, multitenancy,
rollback, operación terminada y fecha comunicada.

La corrida final completa obtuvo `208 passed, 2 warnings in 14.72s`. Las dos
advertencias son deprecaciones conocidas de TestClient/httpx y anyio; no son fallos
de dominio ni de persistencia.

El benchmark end-to-end sobre PostgreSQL con plan base, frontera compartida,
snapshot, 10 proyectos y 50 operaciones obtuvo 428,64 ms en esta PC. El núcleo puro
con 10 reservas obtuvo 36,63 ms. Ambos usan un umbral de regresión de 5 s y son
mediciones reproducibles, no una promesa de latencia industrial.

## 8. Límites explícitos

- No hay promoción/aceptación ni publicación automática.
- No hay endpoint HTTP: los servicios y persistencia quedaron validados primero.
- La comparación V1 usa operación y fin de proyecto como proyección; hitos
  especializados podrán ampliar la misma estructura sin migración.
- No hay optimización global; la heurística privilegia factibilidad, prioridad y
  perturbación acotada.
- La capacidad variable absoluta por franja, setups y transportes siguen fuera.

## 9. Conclusión

`REPLAN_SIMULATION_VALIDATED`
