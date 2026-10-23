# Instalaciones V1 — Etapa 7.5

Estado: **INSTALLATION_VALIDATED** para el alcance DEV solicitado. Autenticación productiva diferida.
Directorio: `C:\Users\BESTEN-01\Documents\ChatGPT\Produccion Besten`.
Branch: master. Checkpoint inicial: `8865fa91f359f6f88a2d9df7c438fecfdd1ede74`.
No commit ni push automáticos.

## Auditoría y decisión de dominio

Se contrastaron README, modelo lógico/cierre, esquema físico, diccionario,
arquitectura backend, contrato API, scheduler, reprogramación, promoción,
definición productiva y preparación/liberación con las migraciones y adaptadores.
Los documentos vigentes son `07-esquema-fisico-postgresql-v1.md`,
`21-motor-planificacion-v1.md`, `23-reprogramacion-desvios-v1.md` y
`24-promocion-programa-v1.md`. No se supusieron los nombres alternativos del prompt.

La auditoría inicial detuvo implementación con INSTALLATION_MODEL_GAP: no había
ubicación estructurada por proyecto. El usuario autorizó expresamente M11 y seis
campos separados, con máximo una ubicación principal por proyecto.

**V1 soporta una ubicación principal de instalación por proyecto.**
Múltiples sitios por proyecto requerirían entidad installation_sites; no se implementa.

## M11 y compatibilidad

`db/migrations/011_installation_location.sql` agrega a `core.projects`:

- installation_site_name;
- installation_address;
- installation_locality;
- installation_contact_name;
- installation_contact_phone;
- installation_access_notes.

Son columnas text nullable, sin defaults ni backfill ficticio. Contacto/teléfono
son específicos de obra, independientes de customer.email/customer.phone.
Access notes sólo representa indicaciones operativas; la dirección tiene campo propio.
No se utiliza notes, privacy_metadata ni required_operations.settings como ubicación.

M0–M10 históricos intactos. M11 = ubicación de instalación V1. Se mantienen
8 schemas y 87 tablas. El runner crea un proyecto antes de M11, comprueba que
sobrevive con su descripción y seis NULL, y retira ese fixture. Aplica además
verify_schema.sql y temporal_scenarios.sql con rollback. Las constraints históricas
permanecen: verificación estática de 617 constraints nombradas, 297 FKs,
7 exclusiones y cero cascadas destructivas o FKs inseguras por tenant.
La validación usa exclusivamente bases/roles descartables propios; no migra bases
persistentes ni inspecciona archivos de credenciales.

## Modelo y definición

Instalación es `production.required_operations.operation_kind='installation'`.
Se mantienen fases, operation_labor_requirements, operation_physical_requirements,
operation_precedences, installation_lot_coverages y customer_availability_windows.
No se crea instalación paralela ni segundo scheduler. No se hardcodean personas,
skills, recursos, centros ni nombres de operaciones.

El editor permite seleccionar Producción/Instalación. El tipo se guarda, participa
del hash industrial y se conserva en la revisión congelada y en su loader. Una
instalación requiere equipo obligatorio válido de 1 a 3 personas por requisito.
Fases sin equipo pueden permanecer como borrador incompleto, pero no congelarse.
Una revisión nueva usa el ciclo de 7.3/7.4 y requiere release si cambió industrialmente.
Proyectos con ejecución registrada conservan la restricción de no rediseñarse en el editor.

## Readiness y fechas

INSTALLATION READINESS es derivado y separado de PRODUCTION READINESS; no se guarda
installation_ready=true. Se evalúan definición congelada y release vigente,
maestros activos, requisitos humanos, recursos definidos, dirección y localidad.
Nombre de obra y contacto son opcionales. La capacidad disponible en un hueco real
la determina el scheduler, no un booleano de preparación.

`ready_to_schedule` permite que la instalación futura compita en el plan, aun si
su producción precedente todavía no se ejecutó. `ready_to_start` exige además
precedencias realmente finalizadas. START_OPERATION reevalúa bajo locks y rechaza
un timestamp anterior al fin real de sus precedencias y su lag. Un error de
ubicación agrega INSTALLATION_LOCATION_MISSING a las fases de instalación;
la producción puede continuar. Operaciones ya terminadas no necesitan renovar readiness.

Estados derivados: NO LISTA, LISTA, PROGRAMADA, EN CURSO, FINALIZADA y BLOQUEADA.
La instalación se consulta en la definición congelada vigente; un borrador no se
presenta como demanda autorizada ni reemplaza una revisión anterior del plan.

Compromiso e inicio deseado del proyecto se muestran separados de fechas planificadas
por CURRENT, inicio real y final real. No se copia la fecha del plan a committed_date.
No se agrega una segunda fecha comprometida específica de instalación: el modelo
existente dispone de committed_date del proyecto, earliest_start_at por operación
y ventanas del cliente. No se implementa edición de esas ventanas en una agenda paralela.

## Scheduler, personas, recursos y calendarios

Se reutiliza v1-greedy-3. Las precedencias reales ordenan producción e instalación.
Personas y recursos se reservan en las mismas tablas que el resto del trabajo.
Las asignaciones no se superponen con producción, máquinas, bancos u otras
instalaciones. Se conservan las capacidades exclusive/cumulative existentes.
Los requisitos físicos usan tipos, grupos y centros configurados, sin flota ni stock.

La duración divisible se reparte en ventanas laborales, no en horas continuas.
Se intersectan calendarios de planta, personas, recursos y centros aplicables,
excepciones e indisponibilidades existentes. No se inventan horas extraordinarias.
Las pruebas verifican horas/un día/múltiples jornadas y excepciones remove/replace.

El motor mantiene el mismo equipo entre segmentos de una misma fase, incluso
entre días. Fases distintas o un replan pueden reasignar personas; no se promete
continuidad obligatoria entre fases/revisiones ni se agrega optimizador nuevo.
El equipo real de un tramo se registra explícitamente, preservando su historia.

## Plan, Gantt, tablero y agenda

GET /installations produce una agenda desde operaciones congeladas, CURRENT,
asignaciones y ejecución. No persiste reservas paralelas. El detalle del proyecto
incluye sección de instalación con sitio, contacto, equipo, duración, plan y realidad.
La agenda permite buscar por proyecto/cliente/dirección y filtrar estado, hoy y atrasadas.
Hoy usa las fechas locales de segmentos asignados; incluye continuaciones multidía
y no supone trabajo en fines de semana intermedios sin segmentos.
Los UUID se usan para navegación/contratos, no como etiquetas visibles.

Las instalaciones aparecen automáticamente en Gantt y tablero por ser operaciones
normales del plan. Se verifican ambos endpoints contra la solución aceptada real.
La acción SIMULAR PLAN DE INSTALACIÓN usa REPLAN_PROJECT sobre CURRENT. Confirmar
usa ACCEPT_REPLAN y sus locks/versiones/base state. Simular nunca publica CURRENT.
Esta acción presupone el contexto de plan vigente del baseline; no amplía la
política de publicación inicial diferida en 7.4.
Mover una actividad usa las hipótesis existentes de Gantt y aceptación explícita.

## Ejecución y fin de jornada

Se reutilizan START_OPERATION, REGISTER_EXECUTION_SEGMENT, UPDATE_REMAINING_ESTIMATE
y FINISH_OPERATION. Un inicio sobre operación terminada o proyecto suspendido/
archivado se rechaza; no existe reapertura silenciosa. El inicio no inventa horas
ni usos reales: la ocupación efectiva se registra con los tramos, como en el dominio base.

La UI permite iniciar, registrar tramo/fin de jornada, seleccionar equipo y recursos
asignados utilizados, guardar restante y finalizar fase. Registrar un tramo deja la
operación en curso para continuar otro día. No se agrega comando PAUSE ficticio ni
porcentaje manual. El dominio registra segmentos y usuarios/recursos reales y
rechaza solapamientos, equipo fuera de planta y ausencia de requisitos obligatorios.

Duración prevista/ejecutada se muestra en minutos de tramo; restante humano se
identifica como minutos-persona. Para una instalación prevista en 10 horas con
una persona, se registran 6 horas reales y 6 horas restantes: total actualizado
12 horas. REPLAN_FROM_OPERATION recalcula futuro y conserva tramos históricos;
CURRENT y resultados anteriores permanecen hasta ACCEPT_REPLAN.

## Cierre y cancelación

POST /projects/{id}/complete exige definición congelada no vacía y todas sus
operaciones obligatorias completadas, incluida instalación cuando existe.
Bloquea proyecto/operaciones, verifica row_version, archiva administrativamente y
registra fecha/actor mediante auditoría PROJECT_INTAKE_COMPLETE. El retry compatible
no duplica cierre. No se borra ejecución ni se reabre lo finalizado.

Un proyecto sin instalación se cierra al terminar sus demás operaciones. Archivar
administrativamente por el flujo anterior conserva su significado: no prueba
finalización operativa. `completed` sólo es verdadero cuando también se verifican
todas las operaciones de la definición. No se cierra con instalación pendiente.
La redefinición/cancelación futura respeta el lifecycle del editor; con ejecución
no se elimina ni se rediseña desde este flujo.

## API, concurrencia e idempotencia

- GET /installations y GET /projects/{id}/installations.
- PATCH /projects/{id}/installation-location: seis campos + expected_row_version.
- POST /projects/{id}/installation-plan: cutoff_at, horizon_end y reason.
- POST /installations/{operation_id}/remaining-estimate: contrato existente de
  restante + expected_revision_no; respuesta tipada con revisión y totales.
- POST /projects/{id}/complete: expected_row_version.

Los comandos nuevos exigen Idempotency-Key. Ubicación/cierre reutilizan el UoW de
proyectos. Restante reutiliza el UoW de estimación en la misma transacción que su
registro idempotente; compara hash contextual y revisión esperada. Concurrencia
incompatible devuelve 409, no overwrite. Retry de inicio/tramo/finish reutiliza
los mecanismos existentes. La UI conserva intención/clave ante resultado incierto.
Los errores no muestran SQL ni secretos; consultas parametrizadas y contexto DEV
filtran organización y planta. No se implementa autenticación productiva.

## Pruebas y rendimiento

Resultados finales:

| Validación | Resultado |
|---|---|
| Backend completo | 509 passed; 42 casos nuevos de instalaciones incluidos |
| Vitest completo | 154 passed; 20 nuevos incluidos |
| Playwright completo | 187 passed; 13 skips responsive preexistentes |
| Instalaciones Playwright | 32/32 (8 casos × 4 resoluciones), incluidos en el total |
| Total sin duplicar subconjuntos | **850 pruebas aprobadas** |
| TypeScript / Vite | Aprobados |
| OpenAPI | Igualdad exacta con FastAPI; tipos regenerados con openapi-typescript |
| Migraciones | M0–M11, 8 schemas, 87 tablas; M0–M10 idénticas a HEAD |
| Verificaciones SQL | verify_schema y temporal_scenarios aprobadas con rollback |
| Verificación estática | 12 migraciones; constraints y aislamiento intactos |

Backend final: 186,75 segundos. Los subconjuntos y benchmarks repetidos no se
suman nuevamente al total. La cadena PostgreSQL incluye producción/instalación,
programación/aceptación, Gantt/tablero, ejecución real, demora de 10 a 12 horas,
replan explícito, conservación de CURRENT y cierre final.

Las pruebas PostgreSQL nuevas cubren ubicación, históricos, contactos, update,
rollback, concurrency real, replay, aislamiento tenant/plant, tipos de operación,
calendarios, equipo de 1/2/3 personas, maestros inactivos, duración, conflictos
humanos, Gantt/tablero, precedencias reales, start/tramos/remaining/finish,
demora/replan/accept, CURRENT, cierre con/sin instalación y cierre impedido.

Playwright prueba la interfaz con HTTP simulado; la cadena de negocio y persistencia
se valida adicionalmente contra PostgreSQL real. No se presenta el browser mock
como una prueba del scheduler real. Se usan 1440×900, 1366×768, 1024×768 y 390×844.

GET /installations, muestra PostgreSQL de un proyecto con 50 operaciones de
instalación: **67,92 ms, 22 consultas, 29.811 bytes**. La consulta está agrupada;
no ejecuta lecturas por cada instalación. El benchmark frontend usa 50 proyectos
con una instalación cada uno: 604,15 ms (1440), 558,49 ms (1366),
593,06 ms (1024) y 472,67 ms (390), con HTTP simulado. Se verificó ausencia de
overflow horizontal y se inspeccionó visualmente la captura móvil final.

## Problemas corregidos y límites

- Ubicación ausente: M11 autorizada, seis campos estructurados nullable.
- El editor sólo generaba operation_kind=production: ahora conserva el tipo elegido.
- Loader de borradores: operation_kind también se recupera de snapshot inmutable.
- Reapertura: un inicio no crea otra ejecución para una operación finalizada.
- Readiness temporal: PostgreSQL clock_timestamp() es el reloj de evaluación,
  coherente con recepciones/liberaciones recién registradas. Evita discrepancias
  entre reloj de aplicación y base sin tolerancias que admitan hechos futuros.
- Refresco de UI: el comando espera invalidaciones antes de permitir otra acción;
  la prueba móvil espera explícitamente EN CURSO antes de editar el tramo.
- Proyectos sin demanda no ofrecen enlace de planificación desde instalación.

No hay múltiples sitios, CRM, mapas, GPS, rutas vehiculares, portal, notificaciones,
flota, compras, proveedores/stock nuevos, auth, PWA, realtime ni optimización nueva.
La fecha prevista de medición y plantillas reutilizables continúan diferidas.
Las pruebas no envían mensajes ni acceden a App de Compras o al backup.
Warnings finales: dos deprecaciones backend (httpx/Starlette y alias de AnyIO),
NO_COLOR/FORCE_COLOR en Playwright y bundle Vite grande (1.799,57 kB; gzip 361,88 kB).
En una corrida intermedia apareció también un warning Pydantic sobre alias del
header de planta; no apareció en la corrida backend final. Chromium descargado
no estaba disponible: Playwright se ejecutó con Microsoft Edge instalado, sin
instalar navegadores ni cambiar configuración global.

## Seguridad, PostgreSQL y Git

Escaneo de 204 archivos versionados/nuevos: sin candidatos a secretos nuevos.
.env.example conserva dos placeholders locales idénticos al checkpoint anterior.
No se incluyen .env, credenciales, logs, caches, node_modules, dist, test-results
ni playwright-report. Los scripts no incorporan passwords ni claves.
Git diff --check aprobado. Sin staging, commit ni push; HEAD y branch originales.
PostgreSQL descartable se elimina en finally, junto con su role NOLOGIN; las
variables de conexión se pasan sólo al proceso hijo y no quedan en el padre.
Comprobación final: Python 3.11.9, PostgreSQL 18.6 operativo, cero bases y roles
besten_test_% residuales, TEST_DATABASE_URL y PGPASSWORD ausentes en el padre.
Se detuvo únicamente el servidor Vite creado para esta validación.
App de Compras y BACKUP Produccion Besten recuperado no fueron accedidos,
inspeccionados ni modificados.


## Archivos del alcance

38 archivos: 29 modificados y 9 nuevos.

- `README.md`
- `db/verify/apply_with_psql.ps1`
- `db/verify/static_verify.ps1`
- `docs/07-esquema-fisico-postgresql-v1.md`
- `docs/08-diccionario-datos-v1.md`
- `docs/12-plan-migraciones-postgresql-v1.md`
- `docs/20-contrato-api-interna-v1.md`
- `docs/21-motor-planificacion-v1.md`
- `frontend/openapi.json`
- `frontend/src/api/schema.d.ts`
- `frontend/src/features/projects/ProductEditor.tsx`
- `frontend/src/features/projects/Projects.module.css`
- `frontend/src/features/projects/Projects.tsx`
- `frontend/src/main.tsx`
- `frontend/src/routes/Root.tsx`
- `frontend/tests/product-editor.spec.ts`
- `frontend/tests/production-release.spec.ts`
- `frontend/tests/projects.spec.ts`
- `scripts/test_postgres_disposable.py`
- `src/production_besten/api/app.py`
- `src/production_besten/api/product_editor_schemas.py`
- `src/production_besten/api/project_intake_routes.py`
- `src/production_besten/api/project_intake_schemas.py`
- `src/production_besten/persistence/execution_uow.py`
- `src/production_besten/persistence/frozen_editor_demand.py`
- `src/production_besten/persistence/product_editor_uow.py`
- `src/production_besten/persistence/production_release_uow.py`
- `src/production_besten/persistence/project_intake_uow.py`
- `src/production_besten/persistence/scheduling_uow.py`
- `db/migrations/011_installation_location.sql`
- `docs/32-instalaciones-v1.md`
- `frontend/src/features/projects/Installations.test.tsx`
- `frontend/src/features/projects/Installations.tsx`
- `frontend/src/test/installationFixture.ts`
- `frontend/tests/installations.spec.ts`
- `src/production_besten/api/installation_routes.py`
- `src/production_besten/persistence/installation_queries.py`
- `tests/integration/test_installations.py`
