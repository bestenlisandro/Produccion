# Etapa 5.2 — Capacidad acumulativa V1

Fecha de implementación: 2026-09-18  
Scheduler: `v1-greedy-2`

## Alcance

El scheduler admite recursos físicos con `scheduling_mode='cumulative'` y capacidad
nominal mayor que uno, sin convertir personas ni recursos exclusivos en números
agregados. El flujo continúa siendo exclusivamente:

```text
Scenario -> ScheduleSolution
```

No promueve escenarios, no cambia el plan vigente y no agrega migraciones. El
esquema existente de 87 tablas ya contiene capacidad, demanda y reservas:

- `capacity.physical_resources.capacity_units`: capacidad nominal del recurso;
- `production.operation_physical_requirements.quantity` y `capacity_units`:
  demanda efectiva `quantity * capacity_units` por fase;
- `planning.physical_resource_reservations.capacity_units`: consumo materializado;
- `execution.actual_resource_usages.capacity_units`: consumo real vigente.

Un `work_center_id` selecciona recursos pertenecientes al centro. La reserva sigue
identificando un recurso concreto, lo que conserva el contrato físico existente.

## Algoritmo

Para cada equipo humano y conjunto de recursos candidato:

1. intersecta calendario de planta, persona y recurso;
2. resta indisponibilidades, ocupaciones y reservas exclusivas;
3. para cada recurso acumulativo obtiene eventos de inicio y fin de usos reales y
   reservas ya elegidas por la solución;
4. divide la ventana únicamente en esos boundaries;
5. conserva cada tramo donde `uso comprometido + demanda <= capacidad nominal`;
6. consume los tramos en orden; una fase divisible continúa en otra jornada;
7. compara alternativas por completitud, fin, inicio y códigos estables.

No existe barrido minuto a minuto. Los calendarios permanecen cacheados por corrida.
Los usos reales sin `capacity_units` consumen conservadoramente la capacidad nominal
completa.

## Ejemplo obligatorio

Centro/recurso acumulativo `CENTER-A`, capacidad 3:

```text
08:00-12:00  A, demanda 2
08:00-10:00  B, demanda 1
10:00-11:00  C, demanda 1
```

A y B usan 3 unidades entre 08:00 y 10:00. El evento de fin de B libera una unidad y
C comienza exactamente a las 10:00; no espera al fin de A.

## Interacción de restricciones

La factibilidad exige simultáneamente:

- capacidad acumulativa;
- identidad y disponibilidad de cada persona;
- skills vigentes;
- cantidad mínima/máxima de personas;
- recursos exclusivos concretos;
- calendarios y horas extra autorizadas;
- precedencias, fases y gates.

Una fase puede tener, por ejemplo, demanda 1 de `CENTER-A`, `SAW-1` exclusivo y dos
personas calificadas. Ninguna dimensión sustituye a otra. Cada fase conserva sus
propios requisitos, por lo que prearmado y terminación pueden demandar cantidades
distintas.

## Persistencia, escenarios y multitenancy

Las reservas exclusivas se escriben con `exclusive_guard=true`; las acumulativas con
`exclusive_guard=false`, permitiendo superposición cuando la suma es válida. Cada
consulta de capacidad, usos reales y recursos filtra `organization_id` y planta. Los
libros de reservas en memoria pertenecen a una sola solución, por lo que escenarios
alternativos no se consumen capacidad entre sí. Las constraints de tenant y la carga
del snapshot mantienen el aislamiento PostgreSQL.

## Blockers y explicación

`CUMULATIVE_CAPACITY_UNSUPPORTED` fue eliminado del código. El vocabulario nuevo es:

```text
CUMULATIVE_CAPACITY_EXHAUSTED
CUMULATIVE_CAPACITY_EXHAUSTED:CENTER-A:capacity=3:available_at=2026-09-07T10:00:00+00:00
```

El primer valor permite clasificación estable; el segundo explica recurso, capacidad
y siguiente boundary factible. Permanecen independientes `PERSON_UNAVAILABLE`,
`REQUIRED_SKILL_UNAVAILABLE`, `PHYSICAL_RESOURCE_OCCUPIED` y `OUT_OF_HORIZON`.

## División entre jornadas e instalación simple

Una fase divisible consume sólo ventanas factibles. Si quedan tres horas el lunes y
cinco el martes, persiste dos segmentos de 180 y 300 minutos; la noche no genera
trabajo ni horas-persona. Una instalación simple usa el mismo modelo de operación,
fases, personas y recursos, puede abarcar jornadas y compite por las mismas personas.
No existe scheduler separado de instalación.

Equipo variable por día no está modelado como reasignación dinámica dentro de una
misma fase: la alternativa humana elegida se mantiene para sus segmentos.

## Determinismo

La versión sube de `v1-greedy-1` a `v1-greedy-2`. Recursos, personas, proyectos,
fases y eventos se ordenan por claves semánticas estables. El hash semántico incluye
la demanda reservada por recurso. Mismo snapshot y misma versión producen los mismos
segmentos, asignaciones y hash.

## Pruebas

Se agregaron 24 casos de integración PostgreSQL que cubren capacidad 3, cuarta
operación desplazada, 2+1, 2+2, personal, skills, recurso exclusivo concurrente,
liberación interna, división entre jornadas, prioridad, desempate, fases, escenarios,
plan vigente, tenant, rollback, horizonte, blocker, instalación, repetibilidad y
persistencia de demanda. La cobertura adicional valida uso real acumulativo cargado
desde PostgreSQL y dos benchmarks end-to-end. También se agregaron 8 pruebas puras y
2 benchmarks puros.

Colección total: 172 pruebas. Se configuró `TEST_DATABASE_URL` únicamente en el
proceso de pytest, sin guardar la contraseña en el repositorio. La primera corrida
completa obtuvo 169 passed en 36,68 s. Tras agregar cobertura PostgreSQL para uso real
acumulativo se obtuvieron 170 passed en 11,42 s. Finalmente se eliminó la base
descartable, se creó nuevamente, se aplicaron M0–M10 y la suite completa obtuvo:

```text
172 passed, 2 warnings in 12.40s
```

### Incidencias y correcciones de validación

1. El binario PostgreSQL 18.6 estaba instalado, pero el clúster local no estaba
   iniciado. Se arrancó el clúster existente; no se instaló infraestructura.
2. La cuenta administrativa local no tenía una credencial utilizable. Con
   autorización explícita se habilitó `trust` sólo para localhost, se restableció la
   contraseña, se guardó únicamente en `pgpass.conf` protegido y se restauró de
   inmediato `scram-sha-256` para IPv4 e IPv6.
3. La colección original no atravesaba persistencia para un uso real acumulativo.
   Se agregó una integración que persiste uso 2 sobre capacidad 3 y comprueba que
   una demanda nueva de 2 espera su liberación.
4. No se encontraron fallos de implementación, concurrencia, cálculo, determinismo,
   aislamiento tenant, rollback ni inmutabilidad del plan vigente.

La base y el rol descartables se eliminaron al terminar. `TEST_DATABASE_URL` no se
persistió y PostgreSQL quedó operativo con autenticación SCRAM.

## Benchmark

Mediciones puras del algoritmo por eventos:

| Fixture | Proyectos | Operaciones | Recursos | Personas | Reservas | Tiempo |
|---|---:|---:|---:|---:|---:|---:|
| pequeño | 3 | 12 | 1 | 0 | 2 | 6,90 ms |
| moderado | 20 | 100 | 1 | 0 | 20 | 187,44 ms |

Son guardas básicas, no un benchmark industrial. Ambos permanecen bajo el umbral de
5 segundos y no muestran crecimiento minuto por minuto.

Benchmarks end-to-end sobre PostgreSQL 18.6:

| Fixture | Proyectos | Operaciones | Recursos | Personas | Reservas | Tiempo |
|---|---:|---:|---:|---:|---:|---:|
| pequeño | 3 | 12 | 1 | 1 | 2 | 112,36 ms |
| moderado | 20 | 100 | 1 | 1 | 20 | 898,40 ms |

## Limitaciones y riesgos residuales

- no hay optimización global, MILP, CP-SAT ni metaheurísticas;
- `start_start` y `finish_finish` conservan la semántica segura de 5.1 y se cubren
  mediante regresión, sin rediseño;
- `capacity_factor` existe en calendarios, pero 5.2 no lo interpreta como capacidad
  absoluta variable; usa capacidad nominal constante durante ventanas abiertas;
- no hay setup, cambio, demora, promoción, Gantt ni frontend;
- el guard de suma acumulativa vive en el algoritmo/snapshot, no en una constraint SQL
  de suma; la generación de una solución es transaccional y serial bajo el lock de
  planta, pero escrituras externas directas deben respetar el contrato;
- los dos warnings provienen de deprecaciones externas de Starlette/TestClient:
  migración futura de `httpx` a `httpx2` y alias `anyio.abc.BlockingPortal`;
  no afectan la lógica ni pertenecen a código propio.

## Conclusión formal

`CUMULATIVE_CAPACITY_SCHEDULER_VALIDATED`
