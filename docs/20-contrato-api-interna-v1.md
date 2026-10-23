# Contrato de API interna V1

Fecha: 2026-09-07.

## 1. Alcance

Interfaz HTTP mínima para proyectos, definición productiva, ejecución real y ajuste
de tiempo restante. Es una capa de transporte sobre servicios existentes. No incluye
scheduler, Gantt, portal público, frontend, Compras ni autenticación productiva.

## 2. Contexto DEV ONLY

En desarrollo/testing cada endpoint protegido requiere:

```http
X-Dev-User-Id: <uuid>
X-Dev-Organization-Id: <uuid>
X-Dev-Plant-Id: <uuid>  # requerido al crear proyecto; opcional en otras lecturas
```

Estos headers se confían sin criptografía y no son autenticación. `organization_id`,
`user_id` y `plant_id` no forman parte de los bodies. En modo productivo el provider
DEV debe estar deshabilitado; será sustituido por un
`SupabaseRequestContextProvider` que validará JWT, memberships y capabilities. RLS
será la barrera adicional en PostgreSQL.

## 3. Idempotencia

Los POST que invocan comandos con `command_id` requieren:

```http
Idempotency-Key: <uuid>
```

Aplica a lotes, rutas, operaciones, fases, revisiones, start, segmentos y finish. Un
retry compatible devuelve el resultado existente, normalmente con HTTP 200 y
`idempotent_replay=true` cuando la respuesta lo expone. Reutilizar la clave con otro
target o payload devuelve 409. `POST /projects` no la usa porque `CREATE_PROJECT` no
posee `command_id`. La estimación restante usa la revisión optimista vigente derivada
por servidor.

## 4. Endpoints

| Método | Ruta | Resultado |
|---|---|---|
| GET | `/health` | Proceso vivo; no consulta DB |
| GET | `/ready` | Conectividad PostgreSQL |
| POST | `/projects` | Crea proyecto en la planta del contexto |
| GET | `/projects/{project_id}` | Obtiene proyecto tenant-safe |
| POST | `/projects/{project_id}/batches` | Crea lote productivo del proyecto |
| GET | `/projects/{project_id}/batches` | Lista lotes por orden |
| POST | `/batches/{batch_id}/route` | Asigna versión publicada de ruta |
| POST | `/batches/{batch_id}/operations` | Crea demanda de operación |
| POST | `/operations/{operation_id}/phases` | Crea fase, requisitos y gates |
| POST | `/projects/{project_id}/product-definition-revisions` | Congela la definición completa de la planta del proyecto |
| POST | `/operations/{operation_id}/start` | Inicia ejecución planificada o no planificada |
| POST | `/executions/{execution_id}/segments` | Registra segmento y usos reales |
| POST | `/operations/{operation_id}/finish` | Finaliza fase/operación |
| POST | `/operations/{operation_id}/remaining-estimate` | Actualiza estimación restante vigente |
| POST | `/scenarios/{scenario_id}/accept` | Promueve atómicamente un replan vigente |
| GET | `/scenarios/{scenario_id}` | Lee bases, stale/rejected/promoted y plan promovido |
| GET | `/planning/current/day?date=YYYY-MM-DD` | Lee el programa vigente del día para operación de planta |
| GET | `/planning/current/gantt` | Lee rango temporal del plan vigente y, opcionalmente, una simulación comparable |
| GET | `/operations/{operation_id}` | Lee el detalle operativo de una operación del plan vigente |
| POST | `/operations/{operation_id}/replan` | Simula `REPLAN_FROM_OPERATION` sobre las bases vigentes |
| POST | `/planning/activities/{operation_id}/move` | Simula un nuevo inicio y, opcionalmente, un recurso físico solicitado |
| POST | `/planning/activities/{operation_id}/resize` | Simula una duración planificada hipotética sin alterar la estimación restante |
| POST | `/scenarios/{scenario_id}/reject` | Descarta una propuesta sin revertir realidad ni estimaciones |

Congelar desde la ruta de un proyecto identifica su planta, pero la revisión
resultante captura la definición productiva vigente completa de esa planta. La
respuesta contiene ID, número, hash, fecha y flags de reutilización; no devuelve el
snapshot canónico.

## 5. Estimación restante simplificada

Ejemplo con un único requisito laboral obligatorio en la fase actual:

```json
{
  "cutoff_at": "2026-09-07T14:00:00Z",
  "reason": "requiere una hora adicional",
  "remaining": [
    {"dimension": "LABOR_WORK", "minutes": 300}
  ]
}
```

La API deriva ejecución, fase, skill, dotación y revisión esperada. Si existen varios
requisitos, el request debe desambiguar `phase_id`, `skill_id`, `min_people` y
`max_people`. Para uso físico puede requerirse `physical_requirement_id`; para
ocupación de un recurso real se exige `physical_resource_id`. El cliente nunca envía
trabajo ejecutado, total actualizado ni `PlanningStateRevision`.

## 6. Errores

Los errores de dominio usan:

```json
{"error": {"code": "GATE_BLOCKED", "message": "..."}}
```

- 400: request estructuralmente válido pero semánticamente inválido;
- 404: recurso inexistente o inaccesible para el tenant, con el mismo cuerpo genérico;
- 409: estado, concurrencia, gate, disponibilidad o idempotencia;
- 422: validación de path/header/body por FastAPI/Pydantic;
- 500: error inesperado genérico, sin SQL ni stack;
- 503: provider productivo de identidad no configurado.

## 7. OpenAPI y seguridad futura

`/openapi.json` es generado por FastAPI con títulos, schemas y códigos declarados.
La transición futura reemplaza únicamente el provider de contexto y agrega políticas
RLS/privilegios mínimos; los DTO, comandos y servicios no deben recibir identidad del
body ni cambiar sus reglas productivas.

## 8. Promoción de escenario

`POST /scenarios/{scenario_id}/accept` exige contexto de planta e
`Idempotency-Key`. El body contiene `expected_promotion_lock_version` positivo y una
razón opcional. Devuelve plan anterior/nuevo, número, solución, lock resultante,
timestamp, recomendación de comunicación y flag de replay.

- 201: nueva promoción;
- 200: replay compatible;
- 404: scenario no accesible en el tenant/planta;
- 409: stale, rejected, base/lock/revisión incompatible o clave reutilizada;
- 422: UUID/header/body inválido.

Aceptar nunca recibe organización/actor desde el body ni cambia la fecha comunicada.

## 9. Superficie operativa Etapa 6.1

Las lecturas de tablero y detalle filtran siempre organización y planta y consultan
exclusivamente `current_plan_version_id`. Los UUID se conservan como identificadores
de navegación, pero las respuestas incluyen nombres/códigos de proyecto, lote,
operación, personas y recursos para que no sean etiquetas visibles.

`POST /operations/{operation_id}/replan` deriva plan, definición y revisión de estado
vigentes en el servidor; el cliente sólo entrega cutoff, horizonte y razón. Tanto
replan como reject requieren `Idempotency-Key`. Reject conserva ejecución y
`RemainingEstimateRevision`. La lectura de escenario incluye `row_version`, lock de
promoción, resumen e impactos necesarios para confirmar o descartar desde la UI.

## 10. Gantt operativo Etapa 6.2

`GET /planning/current/gantt` requiere `from`, `to` con offset y `group_by` igual a
`center`, `resource`, `person` o `project`; admite `scenario_id`. El rango debe ser
positivo y no superar 31 días. La respuesta declara la zona IANA de la planta, plan
y revisión vigentes, grupos, operaciones, segmentos reales, ocupaciones físicas,
ventanas laborables, escenarios disponibles y comparación semántica seleccionada.

La consulta es tenant-safe y usa siempre `current_plan_version_id`. Sin escenario
ejecuta seis sentencias de lectura independientemente del número de operaciones; la
selección de escenario agrega una séptima. El endpoint no publica ni modifica datos.

## 11. Ajustes asistidos Etapa 6.3

`POST /planning/activities/{operation_id}/move` y `POST
/planning/activities/{operation_id}/resize` requieren `Idempotency-Key`, el plan
base, cutoff, horizonte y fase objetivo. MOVE admite inicio y recurso solicitado;
RESIZE sólo acepta `PLANNED_DURATION_HYPOTHESIS`. Ambos persisten una hipótesis,
crean un escenario y devuelven solicitado versus propuesto. Nunca alteran CURRENT.

Las actividades finalizadas no se editan. Para una actividad en curso, la API deriva
al flujo `UPDATE_REMAINING_ESTIMATE`. La selección del tenant se aplica antes de leer
la actividad o el plan; un identificador de otra organización se informa como no
encontrado. Véase `docs/27-gantt-ajustes-asistidos-v1.md`.

## 12. Maestros operativos — Etapa 7.1

`/master-data` expone snapshot y comandos de personas, skills, centros, recursos,
calendarios/excepciones y planta. Son 22 operaciones HTTP; las mutaciones requieren
Idempotency-Key UUID y contexto DEV. Ediciones principales exigen
expected_row_version. Asignar calendario usa base_calendar_id de la entidad.

PATCH de excepción admite cambiar calendar_id dentro de la organización y persiste
el destino interpretando el horario local en su timezone IANA. Calendarios admiten
POST ID/status. PUT ID/windows requiere effective_from explícito y conserva las
vigencias históricas y programaciones posteriores. La fecha por defecto de una
habilitación persona–skill es local de planta; su historia se conserva por tramos.

El digest incorpora organización, planta, actor y comando. Replay sólo corresponde
a la misma intención y contexto; una clave reutilizada con otro contexto produce
409. Frontend conserva clave y payload para reintentar una respuesta incierta.

Los cambios operativos adelantan PlanningStateRevision e invalidan escenarios
anteriores. Si afectan operaciones de CURRENT, el detalle operativo representa
persistentemente plan_requires_reconciliation. CURRENT no se reescribe. Los
conteos expresan operaciones distintas de CURRENT e incluyen el calendario base
de planta. OpenAPI y tipos fueron regenerados desde FastAPI real y validados.
Alcance, semántica histórica y límites en `docs/28-administracion-maestros-v1.md`.

## 13. Proyectos / pedidos — Etapa 7.2

El agregado sigue siendo Project. POST /projects ahora exige Idempotency-Key,
comienza en draft y reutiliza CREATE_PROJECT. GET /projects permite búsqueda y
filtros; GET /projects/{id} agrega cliente, fechas separadas, hitos, revisión,
readiness administrativa, admisión productiva y reconciliation. Se mantienen los
campos previos de proyecto. GET /project-intake/options devuelve catálogos existentes
y contexto de planta; no acepta organization_id ni plant_id desde el body.

PATCH /projects/{id}, POST /projects/{id}/status y los POST de measurement/replanteo
requieren clave y expected_row_version. Conflicto de versión: 409 con código
PROJECT_INTAKE_VERSION_CONFLICT. Un replay exige el mismo payload/contexto.
Archivo es baja lógica terminal y se rechaza con ejecución en curso.

measurement/replanteo registran hechos realizados con fecha timezone-aware y
observación; las correcciones usan supersedes_id. No admiten citas futuras.
La fecha prevista de medición y ubicación de obra quedaron fuera del alcance
acordado sin migraciones. No se reinterpretan notas o datos de privacidad como
campos estructurales inexistentes.

Prioridad/committed date afectan la siguiente simulación y su revisión operativa;
CURRENT, ejecución, fechas comunicadas y snapshots industriales siguen intactos.
Un alta administrativa no libera demanda sin definición congelada. No se agregan
rutas de edición industrial. Detalle en `docs/29-proyectos-pedidos-v1.md`.

## Etapa 7.3 — Editor de definición productiva

GET `/product-definition/options` y GET `/projects/{id}/product-definition`
exponen maestros activos, borrador e historia congelada. PUT sobre la segunda ruta
guarda el agregado editable; POST con sufijos `/validate`, `/freeze` y
`/new-revision` coordina su lifecycle. Todas las mutaciones requieren
Idempotency-Key y expected_row_version. Un conflicto de versión devuelve 409
PRODUCT_EDITOR_VERSION_CONFLICT. Congelar no ejecuta scheduler ni modifica CURRENT.

Se reutilizan los cinco comandos productivos existentes; no se agregan endpoints
individuales redundantes. Contratos completos generados desde FastAPI y decisiones
en [definición productiva](30-definicion-productiva-v1.md).

## Etapa 7.4 — Preparación y liberación

GET `/projects/{id}/production-readiness` deriva checklist e historia; GET
`/projects/production-readiness` opera en lote. Los Project incluyen el indicador
para evitar N+1 de la UI. POST `/projects/{id}/release` y `/unrelease` requieren
Idempotency-Key, expected_row_version, evaluation_token y reason. Un conflicto
de evaluación devuelve 409 PRODUCTION_RELEASE_VERSION_CONFLICT.

POST `/projects/{id}/simulations` es una acción separada con horizonte timezone-aware
y la misma protección de intención/concurrencia. Reutiliza GenerateSchedule, sin
aceptar un escenario ni cambiar CURRENT. Freeze por sí solo no autoriza scheduler.
Modelo, evidencia y límites en [preparación y liberación](31-preparacion-liberacion-produccion-v1.md).

## Etapa 7.5 — Instalaciones

- GET `/installations`: agenda derivada de operaciones installation congeladas,
  CURRENT y hechos reales, filtrada por organización/planta; sin agenda paralela.
- GET `/projects/{id}/installations`: preparación, ubicación, asignación, avance y
  posibilidad de cierre; incluye proyectos sin instalación.
- PATCH `/projects/{id}/installation-location`: seis datos estructurados; reutiliza
  Idempotency-Key, expected_row_version y conflicto de proyectos existente.
- POST `/projects/{id}/installation-plan`: REPLAN_PROJECT explícito con horizonte;
  reutiliza scheduler y ACCEPT_REPLAN, no publica automáticamente CURRENT.
- POST `/installations/{operation_id}/remaining-estimate`: wrapper del caso de uso
  existente con Idempotency-Key y expected_revision_no; replay no duplica revisiones.
- POST `/projects/{id}/complete`: cierre explícito, versionado e idempotente; exige
  definición congelada con todas sus operaciones finalizadas, incluida instalación.

START_OPERATION, REGISTER_EXECUTION_SEGMENT y FINISH_OPERATION conservan sus rutas.
El inicio de instalación exige ubicación, liberación y precedencias realmente
finalizadas, respetando sus timestamps. Registro real verifica personas y recursos.
Véase [instalaciones](32-instalaciones-v1.md). Autenticación productiva diferida.
