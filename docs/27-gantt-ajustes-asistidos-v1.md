# Gantt con ajustes asistidos V1

Fecha de cierre: 2026-10-14

Scheduler: `v1-greedy-3`

## Modelo y alcance

Etapa 6.3 implementa:

```text
drag/formulario -> intención -> SIMULAR -> SimulationHypothesis
-> Scenario -> ScheduleSolution -> comparación -> ACCEPT_REPLAN/REJECT_REPLAN
```

El Gantt nunca escribe el programa vigente. La tabla existente
`planning.simulation_hypotheses` ya ofrecía tipo, target y parámetros JSON
vinculados al Scenario; no hubo migraciones y se mantienen 87 tablas. CURRENT sólo
cambia mediante el `ACCEPT_REPLAN` transaccional existente.

## MOVE y requested vs proposed

`requested_start` es un ancla preferida, no una orden. El motor intenta ese
instante y valida calendarios, precedencias, gates, personas, skills, recursos,
ocupaciones, capacidad acumulativa e horizonte. Si no es factible, propone el
primer slot posterior posible. Las demás actividades conservan sus anclas mientras
sigan siendo factibles; se reutilizan frontera de impacto y mínima perturbación.

La respuesta distingue `requested_start`, `proposed_start` y
`exact_request_satisfied`, con impacto y explicaciones. La simulación no modifica
el plan base.

`requested_resource_id` también es hipótesis. El backend valida tenant, estado,
compatibilidad con el requerimiento, calendario, disponibilidad, ocupación y
capacidad. Un movimiento vertical nunca reasigna directamente.

## RESIZE

Para una operación futura no iniciada, resize significa exclusivamente
`PLANNED_DURATION_HYPOTHESIS`: cambia la duración sólo en el input del Scenario,
sin tocar `original_estimate_minutes`, ejecución ni realidad.

Una operación en curso no admite MOVE/RESIZE en V1. La UI dirige a
`UPDATE_REMAINING_ESTIMATE -> REPLAN`, con confirmación explícita. Una operación
finalizada/cancelada tampoco es editable.

La reasignación manual de personas queda diferida: el scheduler elige equipos por
skills, disponibilidad y capacidad, y no existe un contrato inequívoco y seguro de
`requested_person`.

## Scheduler v1-greedy-3

La versión sube porque la intención manual agrega prioridad semántica a la fase
elegida y puede cambiar la selección de slots. No es sólo una capa HTTP. Se
conservan todas las restricciones duras y el orden determinista para fases sin
intención.

## UX

La pantalla inicia en MODO CONSULTA. MODO AJUSTE es funcionalidad DEV/interna, no
autenticación. Al soltar una barra, el callback de vis-timeline devuelve `null`:
CURRENT vuelve a la posición del servidor. Un panel muestra actual, solicitado,
recurso y semántica; sólo `SIMULAR CAMBIO` llama al backend. No hay optimistic
update.

El overlay separa CURRENT, solicitado y propuesto. ACCEPT invalida y relee el
Gantt; REJECT conserva CURRENT. Un Scenario stale no puede aceptarse.
`PROPONER HORARIO` y `PROPONER DURACIÓN` son alternativas etiquetadas y
operables con teclado. En smartphone el timeline permanece read-only y se usa el
formulario. El modo ajuste no se persiste entre sesiones.

## Consistencia y seguridad

Los endpoints exigen `Idempotency-Key`: misma clave/payload reproduce el Scenario;
otra intención genera conflicto. PlanVersion, PlanningStateRevision y
ProductDefinitionRevision protegen carreras con otro ajuste,
`UPDATE_REMAINING_ESTIMATE` o ACCEPT concurrente; una base reemplazada queda
stale. Organización y planta acotan actividades, recursos y escenarios.

Endpoints:

- `POST /planning/activities/{operation_id}/move`;
- `POST /planning/activities/{operation_id}/resize`;
- `GET /planning/current/gantt?scenario_id=...`;
- `POST /scenarios/{scenario_id}/accept`;
- `POST /scenarios/{scenario_id}/reject`.

OpenAPI y `frontend/src/api/schema.d.ts` se generan desde FastAPI.

## Validación y rendimiento

- PostgreSQL 18.6; M0-M10, 8 schemas y 87 tablas;
- backend completo: 276/276 sobre base descartable;
- Vitest: 46/46; cubre modos, captura, cancelación, simulación, alternativa y
  formularios;
- Playwright cubre cancel, reject, accept/refetch, requested vs proposed, resize
  futuro, operación en curso y smartphone: 51 passed y 13 skips intencionales;
- TypeScript/Vite build aprobado.

Benchmark MOVE 10 proyectos/50 operaciones: 2.084,36 ms end-to-end, 43 operaciones
desplazadas, 10 proyectos afectados y payload de respuesta de 507 bytes. El
benchmark visual 50 proyectos/250 operaciones obtuvo 1.019-1.403 ms para CURRENT y
654-4.322 ms para el overlay Scenario en Chromium según viewport, ambos bajo el
umbral explícito de 5 s. El payload backend histórico para 50/250 fue 172,7 KiB.

## Limitaciones

- no hay requested person;
- no se edita ejecución pasada ni se hace resize de una operación en curso;
- no hay optimización global, realtime, PWA, autenticación productiva ni
  comunicación automática;
- snap de 15 minutos es sólo UX;
- persiste el warning de chunk grande de vis-timeline;
- MODO AJUSTE DEV no sustituye un permiso futuro `planning.simulate`.
