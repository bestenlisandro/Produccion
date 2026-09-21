# Etapa 5.4 — Promoción atómica del programa V1

Fecha de validación: 2026-09-21

Comando: `ACCEPT_REPLAN`

Scheduler conservado: `v1-greedy-2`

## 1. Resultado

`ACCEPT_REPLAN` convierte una `ScheduleSolution` de reprogramación lista en la
siguiente `PlanVersion` publicada. La promoción no vuelve a ejecutar el scheduler,
no modifica realidad y no reescribe la versión anterior.

```text
V5 published + Scenario ready + ScheduleSolution ready
  -> V5 superseded + V6 published + Scenario confirmed
  -> audit + outbox, en un único COMMIT
```

El estado físico `confirmed` es el equivalente V1 de PROMOTED. La navegación
escenario → plan queda en `scenario.parameters.promoted_plan_version_id`; la
relación autoritativa plan → escenario es `plan_versions.source_scenario_id`.

## 2. Sin migraciones

Las 87 tablas ya soportaban la operación:

- `core.plants.current_plan_version_id` es el puntero vigente;
- `promotion_lock_version` implementa concurrencia optimista;
- `plan_versions.valid_during` y su EXCLUDE conservan una vigencia única;
- `previous_version_id` forma la genealogía;
- `source_scenario_id` y `schedule_solution_id` congelan el origen;
- `audit.audit_entries` responde quién, cuándo y por qué;
- `integration.outbox_messages` registra el evento transaccional.

No se añadió tabla 88 ni se modificaron M0–M10.

## 3. Precondiciones

La misma transacción exige:

- organización, planta, actor y escenario tenant-safe;
- scenario `replan` en estado `ready`;
- última solución `ready`, con hash terminal;
- plan base todavía vigente;
- `PlanningStateRevision` igual al head actual;
- `ProductDefinitionRevision` igual a la revisión vigente;
- revisiones de solución iguales a las bases del escenario;
- `promotion_lock_version` esperado;
- plan actual publicado y rango temporal válido.

`rejected`, `stale`, solución fallida, base reemplazada o revisión diferente se
rechazan con conflicto explicable. No se recalcula automáticamente.

## 4. Locking y atomicidad

El orden es estable:

1. organización `FOR UPDATE`, para serializar `command_id` en todo el tenant;
2. planta `FOR UPDATE`;
3. `planning_state_heads` `FOR UPDATE`;
4. escenario y versión actual `FOR UPDATE`.

Dos escenarios basados en V5 pueden aceptarse concurrentemente, pero sólo el primero
crea V6. El segundo observa el nuevo lock/puntero y falla; no existe last-write-wins.

Se probaron rollbacks después de cerrar V5, crear V6, validar materialización, mover
el puntero, insertar auditoría e insertar outbox. En todos los casos V5 siguió
vigente y no quedaron filas huérfanas.

## 5. Materialización por referencia inmutable

V6 referencia directamente la `ScheduleSolution` aceptada. No copia resultados,
segmentos, asignaciones, reservas u ocupaciones porque esas filas ya forman un
snapshot identificado por `schedule_solution_id`, hashes y revisiones base, y sus FK
compuestas impiden mezclar soluciones/tenants.

Así V6 representa exactamente la solución aceptada y conserva también operaciones
fuera de horizonte. V5 continúa apuntando a su solución original: ninguna asignación
histórica se actualiza.

## 6. Realidad y reconciliación

La promoción no escribe `operation_executions`, `execution_segments`,
`actual_resource_usages`, `remaining_estimate_revisions` ni `effective_events`. Una
operación en curso conserva pasado y revisión restante; la solución promovida ya
contiene únicamente su saldo posterior al cutoff.

La reconciliación queda representada porque V6 almacena la
`planning_state_revision_id` que sigue siendo el head vigente al aceptar. No se
elimina el historial que produjo el desvío.

## 7. Idempotencia

`command_id`, proveniente de `Idempotency-Key`, se registra como `request_id` y
`transaction_key` de auditoría. Un replay con escenario y payload idénticos devuelve
V6. Cambiar target, planta, versión esperada o razón produce
`IdempotencyConflict`. Un doble click nunca crea V7.

## 8. Estados y escenarios hermanos

- escenario aceptado: `confirmed`;
- escenario rechazado: continúa `rejected` y no es promocionable;
- escenarios hermanos basados en V5: pasan a `stale`;
- escenario ya confirmado con otra clave: conflicto;
- replay de su clave original: devuelve la promoción existente.

Los escenarios y soluciones nunca se eliminan.

## 9. Comunicación

La simulación persiste `COMMUNICATION_RECOMMENDED` como `impact_item` cuando la
estimación supera la fecha comunicada. La promoción propaga el flag en auditoría y
outbox, pero no modifica `portal.communicated_dates`, no actualiza automáticamente
la proyección pública y no envía mensajes.

## 10. Auditoría y outbox

La auditoría `SCENARIO_PROMOTED` contiene actor, scenario, plan anterior/nuevo,
solución, revisiones de estado/definición, `command_id`, motivo, timestamp y lock
resultante.

El outbox pendiente `PLAN_VERSION_PROMOTED` se inserta en la misma transacción con
schema version 1 y clave lógica derivada del comando. No se publica ni consume en
este incremento y no existe integración con sistemas externos.

## 11. API

```http
POST /scenarios/{scenario_id}/accept
Idempotency-Key: <uuid>
X-Dev-Organization-Id: <uuid>
X-Dev-Plant-Id: <uuid>
X-Dev-User-Id: <uuid>

{"expected_promotion_lock_version": 1, "reason": "aprobado"}
```

Una creación devuelve 201; replay, 200; stale/concurrencia/idempotencia, 409;
tenant inaccesible, 404; estructura inválida, 422. `GET /scenarios/{scenario_id}`
expone estado, bases, stale/rejected/promoted y el plan promovido.

## 12. Validación y benchmark

La base descartable se recreó con M0–M10: 8 schemas y 87 tablas. Se agregaron 52
pruebas PostgreSQL/API para precondiciones, historia, unicidad, realidad,
idempotencia, concurrencia, multitenancy, seis failpoints, auditoría, outbox, API y
OpenAPI. La suite completa obtuvo `260 passed, 0 failed, 0 skipped` en 24,45 s.
Persisten dos warnings externos conocidos de TestClient/httpx y anyio.

Benchmark end-to-end representativo:

| Proyectos | Operaciones | Segmentos | Humanos | Reservas | Auditoría | Outbox | Promoción |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 10 | 50 | 51 | 51 | 51 | 1 | 1 | 18,43 ms |

La promoción referencia el snapshot; su costo no crece copiando cada asignación.

### Incidencias corregidas durante la validación

1. La primera compilación detectó un `if` multilínea sin paréntesis; se corrigió
   antes de ejecutar integración.
2. La recomendación de comunicación comparaba fechas pero no aplicaba el umbral de
   días hábiles. Ahora usa el calendario de comunicación (o el base), respeta
   excepciones `add/remove/replace` y sólo genera impacto al superar el umbral.

## 13. Límites

- No hay drag-and-drop, Gantt, optimización global ni comunicaciones automáticas.
- No hay consumidor de outbox.
- `confirmed` conserva el nombre físico histórico aunque el lenguaje de negocio sea
  PROMOTED.
- La inmutabilidad de soluciones se protege por ausencia de comandos de edición,
  hashes y FK; el rol dueño aún podría ejecutar SQL directo.

## 14. Conclusión

`REPLAN_PROMOTION_VALIDATED`
