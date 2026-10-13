# Gantt operativo V1

Fecha: 2026-09-29

## Alcance

Etapa 6.2 incorpora un Gantt operativo de sólo lectura en `/planning/gantt`. Muestra
el plan vigente, segmentos ejecutados reales, saldo/futuro, ocupaciones físicas,
ventanas de calendario y una simulación opcional sin mezclarla con el programa
publicado. Permite vistas día, semana y dos semanas, navegación temporal y agrupación
por centro, recurso físico, persona o proyecto.

No existe drag-and-drop ni edición directa. Aceptar o rechazar reutiliza los comandos
transaccionales de Etapa 5.4 y vuelve a leer el plan desde el servidor.

## Gate de zona horaria

No fue necesaria una migración. El esquema ya declara `default_timezone` en
organización y `timezone` no nulo tanto en planta como calendario. Los intervalos
semanales conservan hora local y vigencia civil; excepciones, ejecución, reservas y
resultados de planificación usan `timestamptz`/`tstzrange`. El scheduler y el nuevo
adaptador resuelven nombres IANA con `ZoneInfo`.

El backend expande turnos locales en la zona del calendario y devuelve instantes con
offset. El frontend calcula medianoches, semanas, etiquetas y eje en la zona IANA de
la planta mediante `moment-timezone`; no depende de la zona del navegador.

## Biblioteca de timeline

Se eligió `vis-timeline` 8.5.4 con `moment-timezone` 0.6.4. `vis-timeline` ofrece
grupos, backgrounds, subgrupos, zoom, scroll, línea de hora actual, templates y eje
temporal configurable. Se usa directamente desde React y se destruye al desmontar;
la integración permanece localizada en `GanttTimeline.tsx`.

Licencia declarada: Apache-2.0 o MIT para `vis-timeline`, y MIT para
`moment-timezone`. Fuentes auditadas:

- https://www.npmjs.com/package/vis-timeline
- https://github.com/visjs/vis-timeline
- https://visjs.github.io/vis-timeline/docs/timeline/
- https://visjs.github.io/vis-timeline/examples/timeline/other/timezone.html

Se descartó `react-calendar-timeline` por su división entre versión estable antigua y
beta para React reciente, y Frappe Gantt porque su modelo centrado en tareas no
resuelve tan directamente grupos de recursos, backgrounds y overlays industriales.

## Contrato y persistencia

`GET /planning/current/gantt` recibe `from`, `to`, `group_by` y `scenario_id`
opcional. El límite es 31 días. Devuelve IDs técnicos para interacción y nombres
humanos para presentación, además de:

- plan y `PlanningStateRevision` vigentes;
- zona IANA y rango efectivo;
- centros con modo/capacidad acumulativa;
- personas y recursos exclusivos;
- segmentos reales y minutos ejecutados/restantes;
- saldo vigente obtenido de RemainingEstimateRevision sin reescribir la estimación original;
- ocupaciones físicas reales o del `schedule_solution` vigente;
- ventanas regulares/excepcionales de calendario;
- escenarios ready/stale y overlay semántico.

vis-timeline es sólo la capa visual localizada: la fuente de verdad continúa en
PostgreSQL y en los contratos del backend. Las diferencias son `UNCHANGED`, `SHIFTED`, `ADVANCED`, `DELAYED`,
`OUT_OF_HORIZON` y `NEWLY_PLANNED`. Un escenario stale se visualiza, pero no ofrece
confirmación. Sin escenario la lectura mantiene seis consultas SQL fijas; con
escenario suma una consulta, evitando N+1.

## UX y accesibilidad

La línea AHORA, leyenda y estilos distinguen realidad, plan vigente, restante,
ocupación y simulación. Los estados DEMORADO y BLOQUEADO incluyen texto. Cada barra
operativa es seleccionable por mouse, Enter o espacio y abre un detalle con proyecto,
lote, fase, prioridad, fechas, personas, recurso, ejecutado, restante y blocker. En
móvil se presenta una lista simplificada; el Gantt completo fue validado en
1440×900, 1366×768 y 1024×768.

## Rendimiento y validación

Medición PostgreSQL 18.6 sobre base descartable con M0–M10:

| Fixture | Operaciones | Latencia backend | Payload JSON |
|---|---:|---:|---:|
| 10 proyectos | 50 | 54,05 ms | 34,6 KiB |
| 50 proyectos | 250 | 63,92 ms | 172,7 KiB |

El render inicial Chromium con 50 proyectos/250 operaciones midió 899 ms en la
corrida aislada de 1440×900. La suite final confirmó 846 ms en 1440×900, 785 ms
en 1366×768 y 856 ms en 1024×768. `vis-timeline` virtualiza los
ítems visibles. Los límites automatizados son deliberadamente holgados: 2/3 s para
backend, 512 KiB/2 MiB de payload y 5 s de render.

Validación final:

- PostgreSQL/FastAPI: 268 passed;
- Vitest: 43 passed;
- Playwright: 34 passed y 6 skipped intencionales del Gantt en smartphone;
- build TypeScript/Vite aprobado;
- OpenAPI y tipos TypeScript regenerados;
- sin migraciones nuevas; 8 schemas y 87 tablas conservados.

## Límites

- No hay edición visual ni promoción implícita.
- No hay polling/realtime ni persistencia de preferencias de vista.
- El bundle advierte un chunk inicial grande por la biblioteca de timeline; queda como
  optimización futura mediante carga diferida, sin afectar la validación funcional.
