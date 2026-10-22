# Proyectos / pedidos V1 — Etapa 7.2

Estado: **PROJECT_INTAKE_VALIDATED** para el alcance acordado sin migraciones.
Alcance DEV, con autenticación productiva diferida.
Directorio: `C:\Users\BESTEN-01\Documents\ChatGPT\Produccion Besten`.
Branch `master`; checkpoint de partida `74974ca424eebbe49bea5f7cb52e6cc4df5002b5`.
El working tree estaba limpio al iniciar. No se realizó commit ni push.

## Auditoría y compuerta del modelo

Se revisaron README, modelo lógico, cierre lógico, esquema físico, diccionario,
arquitectura backend, contrato API y documentación de maestros. La referencia del
pedido `docs/07-modelo-fisico-postgresql-v1.md` no existe: su equivalente vigente es
`docs/07-esquema-fisico-postgresql-v1.md`, identificado desde README.
Se comprobaron las migraciones y las implementaciones reales antes de modificar.

| Necesidad | Estructura reutilizada / decisión |
|---|---|
| Proyecto o pedido | `core.projects`; no existe ni se agrega un agregado Order |
| Cliente | `core.customers`: nombre, email, teléfono y notas |
| Código, referencia y notas | `projects.code`, `name`, `description` |
| Prioridad | `core.project_priorities`; URGENT, HIGH, NORMAL configuradas |
| Compromiso | `projects.committed_date` |
| Inicio deseado existente | `projects.desired_start_at`, conservado; no equivale a fecha estimada |
| Fecha estimada | Resultados del plan CURRENT; no se copia sobre committed_date |
| Fecha comunicada | `portal.communicated_dates`, independiente y sin envío |
| Medición y replanteo realizados | `milestone_definitions` y `project_milestones` |
| Estados y archivo | `core.record_status`: draft, active, inactive, archived; `closed_at` |
| Historia e idempotencia | `audit.audit_entries` y referencias de superseding de hitos |
| Reconciliation | `planning_state_revisions`, `planning_state_heads` y estados stale |
| Definición industrial | ProductDefinitionRevision y estructuras existentes, reservadas para 7.3 |

El esquema no tiene una ubicación de obra por proyecto ni un campo de fecha
prevista de medición. `project_milestones.occurred_at` representa un hecho realizado,
no una cita futura; `customers.privacy_metadata` no es una dirección de obra.
Tampoco corresponde convertir notas o auditoría en un modelo oculto de agenda.
El usuario confirmó expresamente continuar **sin migraciones con los datos
soportados**, documentando ambas limitaciones. No se implementaron esos campos ni
un estado PROGRAMADA que aparentara persistirlos. No es necesaria una migración
para el alcance acordado. M0–M10 permanecen intactas: 8 schemas y 87 tablas.

## Alta, identificación y cliente

`POST /projects` reutiliza la implementación existente de CREATE_PROJECT dentro
del mismo Unit of Work; no duplica inserciones ni demanda productiva.
El proyecto nuevo comienza como borrador. Se ingresan código comercial, referencia,
cliente existente, prioridad, fecha comprometida opcional y notas.
Planta y organización provienen del RequestContext DEV, nunca del body.

La auditoría no encontró numerador comercial existente. Se conserva el código
manual, único por organización y validado en backend; no se inventa un numerador
ni se genera un código comercial en frontend. UUID se usa para rutas y contratos,
pero no se presenta como identificación comercial al usuario.

El selector reutiliza clientes activos. Cambiar cliente cambia customer_id, sin
copiar un snapshot editable ni alterar al cliente compartido. Email y teléfono se
muestran en detalle. No se agregó CRM ni edición global de contactos. Una
organización necesita clientes y prioridades configurados; si faltan, el formulario
lo informa y no ofrece un guardado ficticio.

## Prioridades, fechas y listado

Se persisten los IDs de las prioridades existentes. URGENT/HIGH/NORMAL se muestran
como URGENTE/ALTA/NORMAL. Un atraso no cambia automáticamente la prioridad.

La fecha comprometida es un compromiso administrativo editable. La estimada deriva
del final planificado de operaciones en CURRENT, convertido a la zona IANA de
planta; se omite si los resultados del proyecto no son todos planned. La comunicada
se obtiene del último hecho vigente, excluyendo hechos superseded. Ninguna edición
de proyecto modifica esa historia ni envía comunicaciones.

La recomendación de comunicación muestra impactos COMMUNICATION_RECOMMENDED ya
producidos por el mecanismo existente de planificación, que conserva el umbral y
calendario de días hábiles de planta. Esta etapa no introduce otro cálculo ni un
envío automático.

El orden del backend es active → draft → inactive → archived, prioridad por rank,
compromiso más próximo y desempate por código/ID. Hay búsqueda por código, nombre
y cliente y filtros por estado, prioridad, cliente y rango comprometido.
La UI aplica filtros locales sobre el listado; la API también permite filtrarlos.
La vista inicial muestra activos y borradores; los históricos siguen accesibles
mediante Estado/Todos y por su detalle. Los atrasados se advierten sin ocultarlos.

## Medición, replanteo y readiness

Se muestran dos hechos separados: Medición PENDIENTE/REALIZADA y Replanteo
PENDIENTE/COMPLETADO. Cada registro recibe fecha realizada y observación.
Frontend interpreta el horario en la zona IANA de la planta y envía un instante
con offset; no utiliza UTC como sustituto de una fecha operativa local.
Los formularios esperan la configuración de zona; no permiten guardar usando un
fallback UTC mientras ésta falta.

Registrar un hito crea, si falta, su definición de catálogo MEASUREMENT o REPLANTEO
dentro de la mutación explícita, bajo lock de organización. No hay seeding en GET,
personas hardcodeadas ni scheduler de mediciones. Un timestamp futuro o sin zona
se rechaza porque no representa un hecho realizado válido.
Una corrección inserta otra fila con supersedes_id, conservando la anterior.

LISTO PARA DEFINIR PRODUCCIÓN significa que nombre, cliente, prioridad y compromiso
administrativos están completos en un proyecto abierto. No impone que todos los
proyectos necesiten los mismos hitos. La obligatoriedad de medición/replanteo para
trabajo posterior deberá expresarse mediante los gates productivos configurables
de 7.3. Readiness administrativa no libera trabajo ni equivale a listo para planificar.

## Lifecycle, archivo e historia

La presentación usa Borrador, Activo, Suspendido y Archivado, sin inventar estados
físicos de producción/instalación/finalización. Transiciones admitidas:

- draft → active o archived;
- active → inactive o archived;
- inactive → active o archived;
- archived conserva detalle y es terminal en esta etapa.

No existe cancelado en el enum actual: se ofrece **ARCHIVAR**, no un falso estado
cancelado. No hay hard delete. Si existe ejecución running/paused se rechaza
suspender o archivar; la realidad no se cancela por una edición administrativa.
Planes, segmentos, ejecuciones, escenarios, revisiones y auditoría se conservan.

## Definición productiva y scheduler

No se crean lotes, rutas, operaciones, fases ni estimaciones industriales desde
estas pantallas. Los lotes existentes se cuentan; su edición se reserva para 7.3.
La tarjeta de definición muestra revisión y cantidad de lotes, y la acción futura
DEFINIR PRODUCCIÓN queda deshabilitada con explicación.

El alta no cambia CURRENT ni crea una revisión operativa por sí sola. La admisión
del scheduler exige proyecto activo y demanda existente. Para las definiciones
canónicas con projects se exige inclusión del proyecto con operaciones/fases en el
snapshot congelado. Un proyecto nuevo de intake queda fuera incluso si después se
lo activa o se le agregan operaciones sin congelar su definición.

Se conserva compatibilidad para los snapshots antiguos vacíos utilizados por los
fixtures previos: el bypass legado no admite proyectos con procedencia
PROJECT_INTAKE_CREATE en auditoría. Esa comprobación utiliza la trazabilidad
existente, no una nueva columna de release. Se prueba el rechazo del nuevo proyecto
tanto con definición canónica normal como con snapshot legado vacío.

Las ediciones administrativas no reescriben snapshots. Prioridad y compromiso
actuales se capturan explícitamente en SchedulingInput.projects de la simulación
futura, junto a su revisión operativa; la definición industrial histórica queda
conservada por separado. Se verificó con dos proyectos competidores que pasar de
NORMAL a HIGH cambia realmente el orden de la próxima simulación. No se agregó
editor de revisiones productivas ni se cambió la versión del algoritmo v1-greedy-3.

## Reconciliation, concurrencia e idempotencia

Cambios de prioridad, compromiso, estado y hechos relevantes crean una revisión
operativa y vuelven stale escenarios pendientes de la planta. El change_summary
incluye project_id y current_affected, determinado por referencias reales desde
CURRENT. La consulta de proyecto y el detalle operativo reutilizan ese indicador
persistente. Cambios descriptivos conservan las revisiones industriales.
No hay reprogramación, publicación ni cambio de CURRENT automático.

Las escrituras bloquean organización, planta y entidad según el caso; usan
expected_row_version para rechazar pérdida silenciosa de actualización. Un
conflicto de versión tiene código PROJECT_INTAKE_VERSION_CONFLICT y muestra:
“El proyecto cambió desde que lo abriste. Actualizá la información antes de guardar.”
Otros conflictos conservan su motivo real, por ejemplo ejecución en curso.

Todas las mutaciones HTTP de intake, incluido el POST /projects anterior, requieren
Idempotency-Key UUID. El digest incluye organización, planta, actor, acción,
destino, versión y payload. Replay devuelve el mismo resultado sin duplicar hechos;
reutilizar clave con otro payload/contexto es 409. El test previo de alta se adaptó
para enviar el header ahora obligatorio; los restantes tests existentes se mantienen.
Frontend congela cuerpo y clave para respuestas inciertas y reintenta esa intención.
Una intención nueva usa otra clave. El reintento no persiste tras recargar el navegador.

Los formularios conservan input ante error y sólo cierran con éxito. Ante 409,
ACTUALIZAR INFORMACIÓN es una acción explícita que carga la versión nueva; no hay
last-write-wins. Los editores se aíslan por ID de proyecto para evitar mezclar rutas
y callbacks. Inputs y selects tienen nombres accesibles; los selects usan label/for.

## API y UI

| Método | Ruta | Uso |
|---|---|---|
| GET | /project-intake/options | Clientes, prioridades y contexto de planta |
| GET | /projects | Listado y filtros |
| POST | /projects | Alta reutilizando CREATE_PROJECT |
| GET | /projects/{id} | Detalle enriquecido |
| PATCH | /projects/{id} | Datos administrativos y row_version |
| POST | /projects/{id}/status | Transición controlada |
| POST | /projects/{id}/measurement | Medición realizada/corrección histórica |
| POST | /projects/{id}/replanteo | Replanteo realizado/corrección histórica |

Se conservan las rutas anteriores de lotes/definición; no se duplican para intake.
Los routers construyen comandos y delegan a application/UoW, sin reglas de negocio.
Los contratos validan inputs, tenant viene de contexto y el SQL está parametrizado.

PROYECTOS está en la navegación principal. Rutas `/projects`, `/projects/new` y
`/projects/:projectId`. Detalle: Resumen, Cliente/obra, Fechas, Medición/replanteo,
Estado, Definición productiva y Planificación. Los enlaces a tablero/Gantt/operación
se ofrecen para operaciones que existen en CURRENT, evitando destinos sin detalle
operativo. Hay loading, empty, error y retry. Se mantiene React, TanStack Query,
React Router, fetch y tipos derivados del OpenAPI generado.

## Validación y performance

La validación inicial reprodujo 344 backend tests sobre PostgreSQL 18.6 real.
Cada corrida utilizó `scripts/test_postgres_disposable.py`: M0–M10 desde cero,
8 schemas/87 tablas, rol/base aleatorios propios y limpieza finally.

| Validación final | Resultado |
|---|---|
| Backend completo PostgreSQL 18.6 | 376 passed, 0 failed, 37,14 s |
| Baseline backend preservado + nuevos | 344 + 32 |
| Vitest completo | 90 passed, 0 failed (69 + 21) |
| Playwright completo Edge | 107 passed, 13 skips preexistentes, 0 failed |
| Playwright proyectos, incluido en el total | 28/28, sin skips |
| Playwright maestros, incluido en el total | 28/28, sin skips |
| Total aprobado sin duplicar subconjuntos | 573 pruebas (492 + 81) |
| TypeScript / Vite build | Aprobados |
| OpenAPI y tipos generados | Regenerados desde FastAPI real; comparación exacta verde |
| M0–M10 desde cero | 8 schemas y 87 tablas físicas; cero migraciones nuevas |
| git diff --check | Aprobado |

Los 13 skips son los responsive previos de Gantt. No se agregaron omisiones para
proyectos. Hubo dos warnings backend de dependencias Starlette/httpx y alias anyio.
Una corrida inicial emitió también el warning conocido de alias Pydantic bajo
concurrencia; no apareció en la última. Vite advierte bundle grande: JavaScript
1.768,33 kB minificado, 354,56 kB gzip. No se actualizaron dependencias.

Playwright emitió los warnings conocidos de NO_COLOR/FORCE_COLOR y un error proxy
ECONNREFUSED al finalizar un caso previo de maestros con API simulada, sin fallas.
Después de los 120 resultados se detuvo únicamente su Vite preview; el runner
finalizó con exit code 0. No se cerraron servidores ni navegadores ajenos.

La cobertura nueva incluye 32 casos PostgreSQL, 21 Vitest y 28 ejecuciones
Playwright de proyectos (7 casos × 4 viewports). Cubre alta, edición, filtros,
fechas separadas, hechos, transiciones, archivo, historia, idempotencia contextual,
concurrencia, rollback, 404/409/422, snapshot OpenAPI, reconciliation y admisión al
scheduler. Los cuatro viewports son 1440×900, 1366×768, 1024×768 y 390×844.

Benchmark PostgreSQL de 100 proyectos: **128,78 ms**, **84.552 bytes**, **5 consultas**.
La cantidad de consultas es constante; no hay N+1 por proyecto. Incluye el transporte
TestClient. La UI mide render y búsqueda local con fixtures de 100 proyectos; sus
mediciones no se presentan como tiempos SQL ni como garantía productiva.
Playwright usa API simulada determinista; la persistencia y el orden real del
scheduler se prueban separadamente con HTTP/FastAPI y PostgreSQL.

| Viewport | Render inicial de 100 tarjetas | Búsqueda hasta una tarjeta |
|---|---:|---:|
| 1440×900 | 501 ms | 95 ms |
| 1366×768 | 286 ms | 65 ms |
| 1024×768 | 361 ms | 61 ms |
| 390×844 | 282 ms | 62 ms |

El payload simulado fue de 84.071 bytes. No hubo desborde horizontal en la prueba.
Los flujos de alta se completaron en aproximadamente 1–1,3 s de ejecución automatizada
con datos disponibles; no se presenta ese tiempo como medición de una persona real.

Errores encontrados y corregidos: casteo enum/text ambiguo en cambio de estado;
asociación explícita de labels de selects; fixtures de frontend que devolvían un
estado viejo después de archivar; sincronización de opciones antes de convertir
horarios; enlaces limitados a operaciones materializadas en CURRENT.

## Límites y seguridad

- Fecha prevista de medición y ubicación de obra: fuera del alcance acordado sin migración.
- Sin CRM, alta/edición global de clientes, clonado ni numerador comercial nuevo.
- Sin paginación/virtualización masiva; listado validado con 100 proyectos.
- Sin cancelar ejecución real desde administración ni restaurar archivos históricos.
- Sin editor industrial, nueva definición de lotes/rutas o portal cliente nuevo.
- No se envían comunicaciones ni se altera su fecha desde el formulario.
- Autenticación diferida: **DEV ONLY / BLOCKER FOR PRODUCTION**; no login, usuarios,
  passwords, Supabase Auth, JWT ni RBAC productivo. Multitenancy no se relaja.

No se accedió, inspeccionó, ejecutó ni modificó App de Compras ni BACKUP Produccion
Besten recuperado. No se leyó pgpass.conf ni se persistieron credenciales.
M0–M10 no se modificaron y no se agregó una tabla 88. Sin commit automático.

Al finalizar, PostgreSQL 18.6 seguía operativo, sin bases ni roles temporales del
runner. TEST_DATABASE_URL y PGPASSWORD estaban ausentes del proceso principal.
No se modificó pg_hba.conf. Outputs, node_modules y caches continúan ignorados.
El escaneo final no encontró secretos nuevos; los placeholders previos de
.env.example se verificaron sin imprimir sus valores y quedaron sin modificar.
No se incorporaron .env, credenciales, logs, bases, certificados ni claves.

Conclusión formal: **PROJECT_INTAKE_VALIDATED**. Fecha prevista de medición y
ubicación de obra permanecen explícitamente fuera del alcance aprobado.
