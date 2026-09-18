# Etapa 5.1 — Motor de planificación factible V1

Fecha de validación: 2026-09-07  
Versión vigente del algoritmo: `v1-greedy-2`

## 1. Alcance y garantía

El incremento implementa un planificador hacia adelante de capacidad finita,
determinista, explicable y reproducible. Produce exclusivamente:

```text
Scenario -> ScheduleSolution -> resultados -> asignaciones -> segmentos/reservas
```

No crea ni modifica `PlanVersion`, no mueve
`core.plants.current_plan_version_id` y no altera asignaciones publicadas. La
promoción será un caso de uso posterior y explícito. La garantía V1 es factibilidad
respecto del subconjunto documentado, no optimalidad global.

## 2. Arquitectura

- `domain/scheduling/models.py`: comando, input congelable y resultados puros;
- `domain/scheduling/engine.py`: heurística y búsqueda de capacidad sin SQL,
  FastAPI ni estado global;
- `application/scheduling_services.py`: orquestación del caso de uso;
- `persistence/scheduling_uow.py`: lectura tenant-safe, snapshot, transacción y
  materialización en PostgreSQL.

El motor puede invocarse desde tests, servicio, futuro job o futura API. En 5.1 no
se agregó endpoint ni migración.

## 3. Input reproducible

Al iniciar se bloquean la planta y el `PlanningStateHead`. El comando sólo se acepta
si `ProductDefinitionRevision` y `PlanningStateRevision` coinciden con los punteros
vigentes. La solución registra organización, planta, horizonte, proyectos, plan base,
ambas revisiones, definición canónica, operaciones, fases, precedencias, estimaciones,
gates, calendarios, personas, skills, recursos, indisponibilidades, usos reales,
ocupaciones y horas extra.

El insumo técnico completo se serializa canónicamente en
`schedule_solutions.input_snapshot` y recibe SHA-256. La solución histórica conserva
así el estado usado aunque luego avancen los punteros. En V1 se materializa desde el
estado normalizado protegido por locks y se acompaña con el snapshot canónico de la
revisión vigente; no se intenta reconstruir capacidad pasada desde tablas mutables.

## 4. Heurística greedy determinista

1. construir dependencias entre fases y validar el DAG;
2. tomar fases cuyos predecesores ya fueron procesados;
3. ordenarlas por `URGENT`, `HIGH`, `NORMAL`, fecha comprometida y claves semánticas
   estables de proyecto/lote/operación/fase;
4. calcular la primera fecha habilitada por precedencias, `earliest_start` y gates;
5. enumerar equipos humanos y recursos válidos en orden por código;
6. intersectar calendarios de planta, personas y recursos y restar
   indisponibilidades, hechos reales y reservas de la misma solución;
7. cortar ventanas en eventos de inicio/fin de consumos acumulativos y conservar
   sólo los tramos cuya suma de demandas cabe en la capacidad;
8. consumir el primer conjunto de ventanas suficiente, continuando en otra jornada
   cuando la fase sea divisible;
9. elegir la alternativa que termina primero y desempatar establemente;
10. reservar personas, demanda acumulativa, recursos exclusivos y, cuando
    corresponde, ocupación física continua;
11. repetir hasta procesar todas las fases.

No se itera minuto por minuto. El motor opera sobre ventanas/eventos; cada calendario
se expande una vez por horizonte y queda en caché durante la corrida.

## 5. Búsqueda de hueco

`find_earliest_feasible_slot` considera inicio mínimo, horizonte `[inicio, fin)`,
releases y gates, skills, dotación, calendarios, indisponibilidades, hechos reales,
reservas internas, recursos alternativos/exclusivos, divisibilidad y duración.

Una fase no divisible exige una ventana continua. Una divisible conserva los
segmentos factibles aun si no completa: queda `out_of_horizon`, con minutos
planificados y saldo restante separados.

## 6. Personas y proporcionalidad

Cada requisito humano obligatorio genera equipos entre `min_people` y `max_people`.
Una persona sólo es candidata si su skill está habilitada y vigente durante todo el
horizonte. No puede aparecer dos veces en un equipo ni solaparse dentro de una
solución.

La duración sólo escala si `required_operations.settings.scalable_labor=true` y la
fase tiene exactamente un requisito humano obligatorio:

```text
duración efectiva = ceil(work_minutes / personas asignadas)
```

Sin esa configuración, aumentar la dotación no reduce la duración. V1 no combina
curvas de productividad de varios skills.

## 7. Recursos, centros y ocupación

Se soportan recursos `exclusive` y `cumulative`, seleccionados por tipo, grupo o
centro. El centro sigue siendo un selector de dominio; la reserva apunta a un
recurso físico concreto perteneciente al centro.
Un recurso concreto puede expresarse mediante un grupo cuyo conjunto permitido
contenga sólo ese recurso.

En un recurso `cumulative`, `capacity_units` define la capacidad nominal y la demanda
efectiva de un requisito es `quantity * capacity_units`. La suma de reservas
planificadas y usos reales debe caber durante toda la ventana. `active_use` reserva
segmentos de trabajo. `occupation` crea además un rango continuo entre primer inicio
y último fin, incluyendo noches, sin convertirlo en trabajo ni horas-persona. La
capacidad agregada nunca sustituye personas, skills ni recursos exclusivos.

## 8. Calendarios y horas extraordinarias

El calendario efectivo combina intervalos ordinarios y excepciones `add`, `remove`
o `replace` en la zona configurada, y luego intersecta planta, persona y recurso.
El trabajo fuera de horario sólo se habilita con autorización no revocada compatible
con proyecto, escenario, empleado, recurso o centro. `max_minutes` limita la ventana
desde su inicio. La autorización queda trazada en asignaciones humanas y reservas;
minutos ordinarios y extraordinarios se guardan separados.

## 9. Precedencias, fases y gates

Las fases se enlazan por `sequence_no`. Las precedencias entre operaciones enlazan
última fase predecesora con primera sucesora y respetan el lag. Un ciclo crea
escenario/solución `failed` con `PRECEDENCE_CYCLE` y cero resultados parciales.

Material, planos, herrajes, hitos y fechas explícitas producen una release futura o
un bloqueo específico. Un gate `before_finish` se aplica conservadoramente antes de
iniciar la última fase.

Simplificación expresa: `start_start` y `finish_finish` se serializan en 5.1 como
`finish_start`. Puede demorar de más, pero no anticipa trabajo ni produce una
solución inviable. Su semántica completa queda para una evolución posterior.

## 10. Prioridad, simultaneidad y explicación

La prioridad decide entre trabajo elegible; nunca rompe precedencias, gates o
capacidad. Dos fases pueden comenzar juntas si sus personas y recursos concretos no
se solapan. No existe lock artificial de planta o centro. Un proyecto vencido no
cambia automáticamente de prioridad.

Cada resultado de fase incluye `ready_at` y `why_not_earlier`; las asignaciones
identifican personas y recursos. El vocabulario incluye:

- `PREDECESSOR_NOT_FINISHED`;
- `MATERIAL_NOT_AVAILABLE`;
- `DRAWINGS_NOT_AVAILABLE`;
- `HARDWARE_NOT_AVAILABLE`;
- `MILESTONE_NOT_AVAILABLE`;
- `REQUIRED_SKILL_UNAVAILABLE`;
- `PERSON_UNAVAILABLE`;
- `PHYSICAL_RESOURCE_OCCUPIED`;
- `OUTSIDE_WORKING_CALENDAR`;
- `CUMULATIVE_CAPACITY_EXHAUSTED`, con detalle estable de recurso, capacidad y
  primer instante nuevamente disponible;
- `OUT_OF_HORIZON`.

## 11. Determinismo, persistencia y obsolescencia

El input ordena mapas, sets y colecciones. El resultado semántico usa códigos y
excluye UUID generados. `solution_sha256` cubre proyecto, lote, operación, fase,
estado, blockers, segmentos, personas, recursos y demanda. Dos corridas iguales con
`v1-greedy-2` producen el mismo hash, orden y asignaciones.

Una transacción inserta escenario, solución, resultados, asignaciones, segmentos,
personas, reservas y ocupaciones. Las `EXCLUDE` vuelven a proteger la capacidad
dentro de una solución; soluciones alternativas pueden solaparse. Un fallo revierte
todo. Un escenario se identifica como obsoleto al diferir sus revisiones base de los
punteros vigentes; no se borra ni recalcula automáticamente.

## 12. Validación

Se agregaron 37 pruebas sobre PostgreSQL 18.6 y se conservaron las 101 anteriores.
Cubren el caso principal de muebles, rutas parciales, fases, precedencias, prioridad,
personas, skills, dotación, proporcionalidad opt-in, recursos alternativos/concretos,
simultaneidad, calendarios, feriados, indisponibilidad, overtime, gates, ocupación
nocturna, horizonte parcial, determinismo, obsolescencia, multitenancy, rollback e
inmutabilidad del plan.

```text
138 passed, 2 warnings in 22.48s
```

El fixture de 90 días y 600 minutos quedó bajo el umbral de 5 segundos. Sobre 248
soluciones de las corridas de validación, `metrics.elapsed_ms` registró mínimo 14 ms,
promedio 19,24 ms y máximo 287 ms. Es una comprobación básica con fixtures pequeños,
no un benchmark industrial.

Para 5.2 se agregaron 24 casos de integración PostgreSQL y 10 pruebas unitarias
nuevas (8 funcionales y 2 benchmarks), llevando la colección a 172 pruebas. La base
descartable se recreó desde cero, M0–M10 y sus verificadores pasaron, y la suite final
obtuvo `172 passed, 2 warnings in 12.40s` sobre PostgreSQL 18.6. La cobertura incluye
un uso real acumulativo persistido que desplaza una demanda incompatible.

Benchmarks puros por eventos de 5.2 sobre esta PC:

- pequeño: 3 proyectos, 12 operaciones, 1 recurso, 0 personas, 2 reservas: 6,90 ms;
- moderado: 20 proyectos, 100 operaciones, 1 recurso, 0 personas, 20 reservas: 187,44 ms.

Benchmarks end-to-end con carga y persistencia PostgreSQL:

- pequeño: 3 proyectos, 12 operaciones, 1 recurso, 1 persona, 2 reservas: 112,36 ms;
- moderado: 20 proyectos, 100 operaciones, 1 recurso, 1 persona, 20 reservas: 898,40 ms.

## 13. Límites y riesgos residuales

- no hay optimización global;
- la capacidad variable absoluta por franja no se interpreta todavía: el esquema
  conserva `capacity_factor`, pero 5.2 usa capacidad nominal constante más calendario;
- `start_start`/`finish_finish` tienen semántica conservadora;
- skills y membresías deben cubrir todo el horizonte;
- `max_minutes` limita una ventana, no una bolsa acumulada compartida;
- trabajo ejecutado y `RemainingEstimateRevision` aún no se descuentan de la demanda:
  pertenecen al futuro flujo de reprogramación;
- ocupaciones reales abiertas conservan el límite del modelo físico vigente;
- gates desconocidos quedan bloqueados hasta un nuevo escenario;
- no se calculan camino crítico, setups, transporte ni tardanza óptima;
- no hay promoción, API del scheduler, Gantt, frontend, portal o integración Compras.

Estas limitaciones son explícitas y no se representan como soporte entregado.

## 14. Conclusión

Checkpoint histórico 5.1: `BASIC_FINITE_CAPACITY_SCHEDULER_VALIDATED`.

Estado 5.2:
`CUMULATIVE_CAPACITY_SCHEDULER_VALIDATED`.
