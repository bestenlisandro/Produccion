# Etapa 4 — Arquitectura backend base V1

## 1. Objetivo y alcance

Construir una base backend testeable sobre el esquema PostgreSQL V1 validado, sin implementar todavía motor APS completo, Gantt, frontend productivo, portal público funcional ni integración real con Compras.

El backend inicial cubre:

- proyectos, lotes y revisiones productivas;
- consulta mínima de capacidad configurable;
- ejecución real y usos de recursos;
- `PlanningStateRevision` concurrency-safe;
- `RemainingEstimateRevision` y sus tres dimensiones;
- detección calculada de escenarios obsoletos;
- API mínima para probar la arquitectura.

## 2. Stack elegido

- Python 3.11.
- FastAPI para contratos HTTP y composición de dependencias.
- Pydantic 2 para configuración, comandos y respuestas.
- SQLAlchemy 2 Core con psycopg 3 para acceso PostgreSQL sin generar 87 modelos ORM.
- pytest y cliente HTTP de FastAPI para pruebas.
- PostgreSQL real para pruebas de integración y concurrencia.

SQLAlchemy Core permite expresar `SELECT ... FOR UPDATE`, consultas tenant-safe y transacciones explícitas sin duplicar en clases ORM todo el diccionario físico. El esquema SQL existente continúa siendo la autoridad; se modela en código únicamente el subconjunto requerido por cada agregado/caso de uso.

## 3. Estructura técnica

```text
src/production_besten/
  domain/          # errores, enums y reglas puras sin FastAPI/SQLAlchemy
  application/     # comandos, DTO, puertos y servicios de casos de uso
  persistence/     # Unit of Work y repositorios PostgreSQL por agregado
  api/             # dependencias, schemas HTTP y routers finos
  infrastructure/  # settings y construcción de engine/app
tests/
  integration/     # PostgreSQL real
  api/             # API mínima sobre PostgreSQL real
```

Dependencias permitidas:

```text
API -> aplicación -> dominio
              |
              v
       puertos/repositorios
              ^
              |
persistencia e infraestructura
```

### Evolución de scheduling 5.2

`domain/scheduling/engine.py` continúa puro y sin SQL. En `v1-greedy-2` mantiene dos
libros de reservas separados: intervalos exclusivos por identidad y consumos
acumulativos `(intervalo, unidades)` por recurso. La factibilidad acumulativa se
calcula con boundaries de inicio/fin y nunca minuto a minuto.

`persistence/scheduling_uow.py` carga capacidad nominal, demanda por fase y usos
reales tenant-safe. Las reservas acumulativas se persisten con
`exclusive_guard=false`; las exclusivas conservan `exclusive_guard=true`. PostgreSQL
sigue protegiendo identidades exclusivas mientras la suma acumulativa es una regla
del snapshot y del algoritmo versionado. No se agregaron tablas ni migraciones.

El dominio no importa FastAPI ni SQLAlchemy. Los endpoints no contienen reglas de negocio.

## 4. Agregados y repositorios iniciales

No se crea un repositorio por tabla. Los repositorios iniciales se alinean a operaciones coherentes:

- `ProjectRepository`: proyecto y lotes.
- `ProductionDefinitionRepository`: operaciones, fases y revisiones productivas.
- `CapacityRepository`: personas, centros, recursos, skills y calendarios necesarios para validar usos.
- `PlanningStateRepository`: head, revisiones, eventos y consulta de obsolescencia.
- `ExecutionRepository`: ejecuciones, segmentos, usos reales y estimaciones restantes.

Todos reciben `organization_id` explícito y lo incluyen en consultas sensibles. No existe `get_by_id(id)` global para entidades tenant-owned.

## 5. Unit of Work y transacciones

Cada comando abre una única sesión y decide su límite transaccional. El Unit of Work confirma sólo al terminar el servicio; toda excepción produce rollback.

### `CREATE_PROJECT`

1. valida organización activa;
2. valida planta, cliente y prioridad dentro de la organización;
3. inserta el proyecto;
4. commit único.

### `CREATE_PRODUCTION_BATCH`

El nombre del caso de uso expresa el lenguaje del negocio; su persistencia es
`core.project_lots`. No usa `production.production_batches`, reservado para el
agrupamiento operativo compartido de fases.

1. bloquea planta y proyecto dentro del tenant;
2. valida código y secuencia o asigna la siguiente secuencia bajo lock;
3. inserta el lote independiente con cantidad, unidad, lifecycle y disponibilidad de herrajes;
4. crea un evento y una sola `PlanningStateRevision`;
5. commit único.

### `DEFINE_BATCH_ROUTE`

Asigna a un lote una `route_version` publicada. Al reemplazarla, cierra el rango
`[inicio,fin)` de la asignación anterior y conserva su historia. Las rutas de placa
entera, material cortado o material cortado y canteado son configuración en tablas,
no ramas del servicio.

### `CREATE_REQUIRED_OPERATION` y `CREATE_REQUIRED_OPERATION_PHASE`

Crean demanda productiva, no programación. La operación puede vincularse a un paso
de la ruta activa y declarar precedencias; la fase agrega estimación original,
divisibilidad, requisitos humanos, requisitos físicos y gates en un único agregado
transaccional. `active_use` y `occupation` permanecen dimensiones físicas distintas.
El grafo local completo del proyecto se comprueba antes de insertar aristas nuevas;
un ciclo se rechaza.

### `CREATE_PRODUCT_DEFINITION_REVISION`

1. bloquea la planta, el mismo lock raíz usado por las mutaciones de definición;
2. lee un estado normalizado coherente y obtiene el siguiente `revision_no`;
3. produce el snapshot canónico V1 y SHA-256 sobre sus bytes UTF-8;
4. inserta la revisión inmutable y mueve el puntero vigente en la misma transacción;
5. crea una sola `PlanningStateRevision` y su evento;
6. commit único.

Si el hash coincide con la revisión vigente, devuelve esa revisión con
`semantic_duplicate=true`: no crea revisión, evento ni bump. Si coincide con una
revisión histórica que ya no es vigente, V1 exige una futura reactivación explícita
y rechaza el congelado; no altera silenciosamente la genealogía.

#### Contrato canónico V1

`snapshot_schema_version=1` y `canonicalization_version=1`. Forman parte del contrato:

- proyectos: código, nombre, descripción, cliente y prioridad por código, estado y fechas comprometidas;
- lotes: código, orden, cantidad/unidad, lifecycle y disponibilidad de herrajes;
- requisitos materiales y paquetes de planos del lote;
- ruta activa: código, versión, pasos, plantillas de fase, precedencias y plantillas de requisitos/gates;
- operaciones: identidad semántica por código y scope, tipo, estado, definición/paso por código y settings;
- fases: orden, estimación original, clase de estimación, divisibilidad y estado;
- precedencias, requisitos humanos, requisitos físicos y gates instanciados.

Se excluyen UUID, `created_at`, `updated_at`, `row_version`, autores y orden físico de
filas. Las relaciones se expresan con códigos semánticos, incluyendo el código de
lote cuando un código de operación o material sólo es único dentro de ese scope.
Fechas y horas se normalizan a ISO 8601 UTC, decimales a texto sin ceros no
significativos, listas con orden de dominio explícito y objetos JSON con claves
ordenadas. La serialización usa UTF-8, `ensure_ascii=false` y separadores compactos.

### `START_OPERATION`

1. exige `command_id` y valida tenant, operación, fase y revisión productiva vigente;
2. bloquea `required_operations` para serializar dos inicios concurrentes;
3. valida gates genéricos `before_start` y secuencia de fases;
4. congela `original_estimate_snapshot` desde las fases vigentes;
5. conserva referencias opcionales a plan y resultado programado, sin exigirlas;
6. crea ejecución real independiente, estimación restante inicial, evento efectivo y una revisión operativa;
7. si la operación ya está activa y se inicia una fase posterior válida, conserva la misma ejecución y registra `PHASE_STARTED`;
8. commit único.

Puede existir ejecución no planificada. Un segundo inicio de la misma operación/fase se rechaza, salvo replay con el mismo `command_id`.

### `REGISTER_EXECUTION_SEGMENT`

1. bloquea la ejecución;
2. valida estado, fase, predecesoras, primer gate de fase y rango `[inicio,fin)`;
3. valida personas reales activas, habilidades/cantidad mínima, recursos reales activos y solapamientos estructurales;
4. inserta un segmento append-only y usos reales de persona/recurso físico;
5. conserva `origin_assignment_segment_id` sólo como referencia inmutable de comparación;
6. registra ocupaciones físicas reales independientes del trabajo en `physical_occupations(source_kind='actual')`;
7. crea evento y revisión operativa exactamente una vez;
8. commit único.

Los intervalos separados nunca se fusionan. La ocupación puede atravesar noches o fines de semana sin crear horas-persona.

### `FINISH_OPERATION`

1. bloquea la ejecución activa;
2. valida timestamp, secuencia y que la fase no esté terminada;
3. evalúa gates genéricos `before_finish` para la fase y, al terminar la última, para la operación;
4. registra `PHASE_COMPLETED` de forma append-only;
5. sólo la última fase obligatoria cambia la ejecución a `completed` y registra `OPERATION_COMPLETED`;
6. deriva trabajo humano real desde usos persistidos y registra desviación contra el snapshot original;
7. crea una revisión operativa y commit único.

En V1 todas las fases instanciadas no archivadas y todos los `operation_gates` instanciados son obligatorios: las tablas físicas no tienen un flag opcional. Los gates se evalúan por target genérico: disponibilidad temporal, herrajes del lote, material asignado, plano liberado o hito ocurrido.

### `UPDATE_REMAINING_ESTIMATE`

1. bloquea `operation_executions` con `FOR UPDATE`;
2. exige y valida `expected_revision_no`;
3. deriva trabajo ejecutado desde usos humanos reales vigentes;
4. bloquea `planning_state_heads` con `FOR UPDATE`;
5. crea la siguiente `PlanningStateRevision` y su `EffectiveEvent`;
6. prepara el UUID de la nueva revisión restante;
7. marca la anterior como superseded apuntando a ese UUID;
8. inserta la nueva revisión y sus dimensiones explícitas;
9. fuerza constraints diferidas antes del commit;
10. devuelve la revisión vigente y el nuevo state head.

No crea ni modifica `PlanVersion`. No extiende implícitamente trabajo humano, uso activo ni ocupación física.

## 6. Concurrencia

`PlanningStateRevision` se incrementa bajo lock de fila:

```sql
SELECT ...
FROM planning.planning_state_heads
WHERE organization_id = :organization_id AND plant_id = :plant_id
FOR UPDATE;
```

Dos comandos concurrentes se serializan sobre el head y generan números distintos sin contador perdido.

`UPDATE_REMAINING_ESTIMATE` bloquea primero la ejecución y luego el state head. Dos requests con el mismo `expected_revision_no` no producen overwrite: la primera confirma y la segunda, al adquirir el lock, recibe conflicto de versión. El orden de locks se mantiene estable para evitar deadlocks.

Los comandos de ejecución usan un orden estable:

- start: operación requerida, ejecución activa cuando existe, state head;
- segmento y finish: ejecución, state head;
- finish y remaining estimate se serializan sobre la misma ejecución.

Finish contra remaining puede producir dos confirmaciones ordenadas si remaining obtiene primero el lock, o finish confirmado y remaining rechazado por estado final si finish llega primero. Nunca hay revisión perdida.

### Idempotencia práctica V1

Start, segmento y finish exigen un UUID `command_id`, persistido como referencia externa namespaced por comando y `source_system`. Un retry idéntico devuelve el resultado original. Reutilizar la clave para otra operación, ejecución o fase se rechaza.

Los comandos de definición que producen estado usan la misma estrategia. La planta
es el lock raíz, seguida —cuando corresponde— por proyecto/lote/operación. Por eso:

- dos lotes simultáneos obtienen secuencias distintas;
- dos congelados simultáneos crean una revisión semántica y el segundo reutiliza la vigente;
- editar y congelar se ordenan: el snapshot contiene todo el agregado confirmado antes del lock o nada de ese agregado, nunca una definición parcial.

## 7. Multitenancy

- `organization_id` forma parte del contexto de aplicación, no del identificador de recurso.
- Toda consulta tenant-owned filtra organización además del UUID.
- Las FK compuestas continúan siendo la segunda barrera.
- La API temporal obtiene organización/actor desde headers de desarrollo, nunca desde el body del comando.
- Cuando exista autenticación, esos headers serán reemplazados por claims verificados y memberships; el servicio de aplicación no cambiará su firma tenant-safe.

## 8. Detección de escenarios obsoletos

`scenario.is_stale` se calcula comparando:

- `scenario.base_state_revision_id` contra `planning_state_heads.current_revision_id`;
- `scenario.base_product_definition_revision_id` contra `plants.current_product_definition_revision_id`;
- `scenario.base_plan_version_id` contra `plants.current_plan_version_id` cuando corresponda.

La consulta no actualiza ni elimina el escenario.

## 9. API mínima

Implementada en Etapa 4.4 como adaptador fino sobre los servicios validados:

- `POST /projects`;
- `GET /projects/{project_id}`;
- `POST/GET /projects/{project_id}/batches`;
- `POST /batches/{batch_id}/route`;
- `POST /batches/{batch_id}/operations`;
- `POST /operations/{operation_id}/phases`;
- `POST /projects/{project_id}/product-definition-revisions`;
- `POST /operations/{operation_id}/start`;
- `POST /executions/{execution_id}/segments`;
- `POST /operations/{operation_id}/finish`;
- `POST /operations/{operation_id}/remaining-estimate`;
- `GET /health` y `GET /ready`.

Cada endpoint realiza HTTP → Pydantic → `RequestContext` → comando/servicio →
respuesta. Los routers no abren transacciones ni escriben SQL. Las lecturas auxiliares
tenant-safe viven en `PostgresApiQueries`.

El contexto temporal es `DevRequestContextProvider` y está rotulado `DEV ONLY`.
Construye `RequestContext(user_id, organization_id, plant_id, capabilities)` desde
`X-Dev-User-Id`, `X-Dev-Organization-Id` y `X-Dev-Plant-Id`. Los bodies rechazan
campos extra y nunca aceptan al tenant como autoridad. En producción el provider se
deshabilita y responde 503 hasta reemplazarlo por Supabase Auth.

Los POST cuyos comandos poseen `command_id` usan exclusivamente
`Idempotency-Key: <UUID>`. Replay compatible devuelve el resultado persistido; una
reutilización incompatible devuelve 409. `UPDATE_REMAINING_ESTIMATE` conserva su
control optimista propio: la API deriva la revisión vigente y el servicio serializa
la actualización.

Errores centralizados: 400 para semántica inválida, 404 genérico para inexistente o
inaccesible, 409 para estado/concurrencia/idempotencia, 422 para estructura HTTP y
500 genérico sin stack ni SQL para fallos inesperados.

## 10. Pruebas

Las pruebas usan PostgreSQL real con M0–M10 aplicadas. Se cubrirán como mínimo:

- proyecto, lote y revisión productiva;
- cross-organization;
- inicio, segmentos/usos y finalización;
- evento/revisión operativa;
- caso 10 h original, 7 h ejecutadas, 5 h restantes, total 12 h;
- dos revisiones consecutivas;
- rollback completo;
- escenario stale calculado;
- concurrencia con locks y versión esperada;
- endpoints mínimos.

### Estado del primer incremento

El 2026-09-04 se implementó y validó solamente `UPDATE_REMAINING_ESTIMATE`, tal como se solicitó antes de ampliar el backend. La cobertura real y sus resultados están en `docs/18-validacion-backend-base-v1.md`. Los demás comandos, consultas y endpoints enumerados en este documento continúan como arquitectura prevista, no como funcionalidad entregada.

### Estado de Etapa 4.2

El 2026-09-04 se implementaron y validaron `START_OPERATION`, `REGISTER_EXECUTION_SEGMENT` y `FINISH_OPERATION` contra PostgreSQL 18.6. Los endpoints y los demás comandos previstos continúan pendientes.

### Estado de Etapa 4.3

El 2026-09-07 se implementaron y validaron contra PostgreSQL 18.6
`CREATE_PROJECT`, `CREATE_PRODUCTION_BATCH`, `DEFINE_BATCH_ROUTE`,
`CREATE_REQUIRED_OPERATION`, `CREATE_REQUIRED_OPERATION_PHASE` y
`CREATE_PRODUCT_DEFINITION_REVISION`. El draft normalizado queda separado de las
revisiones congeladas; crear el proyecto vacío no produce bump, mientras que cada
mutación programable produce exactamente uno. No se crearon endpoints.

### Estado de Etapa 4.4

El 2026-09-07 se implementó la API mínima, OpenAPI, health/readiness, contexto DEV,
errores e idempotencia HTTP. Se validó con 26 pruebas HTTP sobre PostgreSQL 18.6;
las 101 pruebas totales quedaron aprobadas. El contrato completo está en
`docs/20-contrato-api-interna-v1.md`.

## 11. Riesgos y límites

- La canonicalización V1 está cerrada para las entidades del incremento; cualquier campo nuevo deberá evolucionar explícitamente `canonicalization_version` o declarar su carácter no semántico.
- No se cambian automáticamente estados derivados de operaciones/proyectos.
- Faltan comandos de edición/archivo para modificar campos existentes del draft; este incremento cubre creación y reemplazo de ruta.
- La inmutabilidad se garantiza por ausencia de comandos de actualización y referencias históricas; el rol dueño de la base aún podría ejecutar SQL directo. Los privilegios mínimos/RLS siguen siendo requisito de despliegue.
- Actualizar tiempo restante no ejecuta scheduling ni genera escenario automáticamente;
  deja evento y state revision listos para el futuro flujo explícito de reprogramación.
- RLS permanece desactivada hasta contar con identidad real y pruebas de políticas.
- La cuenta de aplicación deberá recibir privilegios mínimos antes de un despliegue productivo.
- Los headers DEV no verifican identidad ni memberships; la aplicación debe arrancar con ese provider deshabilitado fuera de desarrollo/testing.
- `TestClient` emite advertencias de deprecación por la combinación actual Starlette/httpx/anyio; no afecta V1, pero conviene alinear versiones antes de ampliar la suite.

## 12. Extensión Etapa 5.1: scheduling de capacidad finita

Se incorporó `domain/scheduling` con modelos inmutables y el motor puro
`GreedyFiniteCapacityScheduler`. Aplicación orquesta; persistencia materializa un
input completo bajo locks y guarda `Scenario -> ScheduleSolution` en una única
transacción. El motor no depende de FastAPI ni SQLAlchemy.

```text
futura API/job -> GenerateScheduleService -> UnitOfWork
                                          -> motor puro
UnitOfWork -> PostgreSQL y tablas planning existentes
```

No se agregaron migraciones ni ORM masivo. `v1-greedy-1`, hashes de entrada/salida y
revisiones base integran el contrato reproducible. El plan publicado es un agregado
distinto y este servicio no puede promoverlo ni modificarlo. Heurística, capacidad,
explicaciones y límites se detallan en `docs/21-motor-planificacion-v1.md`.
