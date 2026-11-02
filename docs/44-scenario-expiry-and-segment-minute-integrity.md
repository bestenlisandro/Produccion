# Integridad de aceptación y minutos de segmentos — piloto

Fecha: 2026-10-29. Base Git: master, df97bebe61a772ec79717b4b52c07cdd6f24e815.

## Incidente y evidencia histórica

CURRENT V1, `1edc7836-e0d0-47fa-bab5-8a3627634b10`, fue publicado el
28/10/2026 a las 14:55:28.692703 en America/Argentina/Cordoba. Proviene del
escenario `df55a037-431b-4d50-aad8-9713a376d02b` y de la solución
`a0736319-747b-409a-b6cd-97f0151602c6`, calculada el 27/10/2026 a las
15:08:45.231477. Utiliza REV 4 de A685.

El evento SCENARIO_PROMOTED, audit ID
`0d456a2e-4dd3-4f7b-a265-6293f8db1419`, registra ACCEPT_REPLAN para el actor
DEV Maximiliano; el outbox registra PLAN_VERSION_PROMOTED. La última operación
terminaba el 28/10 a las 13:13:45.231477, antes de la aceptación, sin ejecución
registrada. El actor persistido no acredita por sí solo la identidad física
de quien operó la interfaz.

Armado tenía intervalos que sumaban exactamente 120 minutos, pero 119 minutos
persistidos y remaining=1. Instalación sumaba exactamente 180 minutos, con 179
persistidos y remaining=1. No faltaba tiempo asignado: el error era contable.

## Regla de aceptación

La aceptación anterior verificaba estado ready, solución completa, revisiones,
base CURRENT, actor y promoción concurrente. No evaluaba si el trabajo había
quedado temporalmente vencido.

Ahora la regla pura de dominio `scenario_expired` inspecciona las fechas aware
de todas las operaciones de la solución. Para una operación sin evidencia de
inicio real, rechaza si scheduled_start < now o scheduled_end <= now. Esto
cubre tanto trabajo terminado en el calendario propuesto como trabajo que ya
debería haber comenzado. Un inicio exactamente igual a now aún es aceptable.
La antigüedad de scenario.created_at no participa de la decisión.

La evidencia de inicio es operation_executions.started_at no nulo, para la
misma organización y operación. Una operación realmente iniciada no vence por
su inicio planificado pasado; las validaciones de bases y estado siguen
vigentes. No se agrega tolerancia temporal ni se convierten fechas a naive.
La aceptación utiliza la zona IANA de la planta, incluida Cordoba.

El adaptador consulta la solución completa, sin filtrar por rango visible del
Gantt. Tras adquirir los locks y consultar los tiempos, lee el reloj inyectable
y valida antes de cerrar versiones, insertar un plan o escribir audit/outbox.
El rechazo lanza ScenarioExpired, derivado de ReplanConflict; el manejador
existente responde HTTP 409 con código SCENARIO_EXPIRED y mensaje seguro:

> Esta simulación quedó desactualizada porque contiene operaciones planificadas en el pasado. Generá una nueva simulación antes de confirmar el plan.

Con CURRENT existente, no cambia el puntero, el plan ni sus intervalos de
vigencia. Sin CURRENT, no se crea la primera versión. No hay aceptación parcial,
regeneración ni replanificación automática. Un replay de un ACCEPT ya exitoso
se resuelve antes de la nueva regla y devuelve el mismo plan, aunque el reloj
haya avanzado: no representa una nueva promoción.

## Presentación

GanttScenarioResponse agrega `expired`, calculado read-only con la misma regla
de dominio y el reloj inyectable de la aplicación. No cambia el status persistido
del escenario ni su historia. Se conserva la distinción entre stale por cambios
de base y vencimiento por reloj.

El Gantt muestra SIMULACIÓN DESACTUALIZADA, una explicación accionable y
CONFIRMAR NUEVO PLAN deshabilitado. La propuesta continúa disponible para
revisión y detalle. Mientras hay una propuesta seleccionada se refresca cada
30 segundos. Si vence entre lectura y aceptación, el backend vuelve a comprobar
la regla y la UI muestra el error específico; el sistema común de notificaciones
también informa el fallo sin anunciar éxito. La autoridad sigue en backend.

Se preservan Gantt Operativo V2, contraste, agrupaciones y navegación. No se
añadió un rediseño ni se modificó CURRENT para mostrar advertencias.

## Minutos: causa y algoritmo

El scheduler usaba dos truncamientos independientes: al puntuar ventanas de
asignación parcial y al calcular work_minutes de cada PlannedSegment. Después
sumaba los enteros ya truncados. Los segundos y microsegundos del inicio local
hacen que dos fracciones complementarias pierdan un minuto al truncarse.

La corrección suma timedelta exactos, con precisión de microsegundos, y aplica
la conversión entera sobre el acumulado. Para cada segmento persiste la
diferencia entre el acumulado entero actual y el anterior. Las fracciones se
arrastran al segmento siguiente; el total coincide con una única conversión de
la duración conjunta. El puntaje parcial también convierte después de sumar.

Ejemplos de regresión, con inicio terminado en 45.231477 segundos:

| Caso | Duraciones de segmentos | Minutos enteros de segmentos | Total / restante |
|---|---|---|---|
| Continuo | 20 min | 20 | 20 / 0 |
| Armado, overnight | 31 min 14.768523 s + 88 min 45.231477 s | 31 + 89 | 120 / 0 |
| Instalación, almuerzo | 151 min 14.768523 s + 28 min 45.231477 s | 151 + 29 | 180 / 0 |

No se alteran timestamps, selección de personas/recursos, calendarios, consumo
de intervalos, split ni precedencias. El restante de la fase se compara con la
duración efectiva que el scheduler debe cubrir; esto también evita mezclar
minutos de trabajo escalable con minutos de duración. No cambia el servicio
UPDATE_REMAINING_ESTIMATE ni se reescribe ninguna estimación real.

La versión del scheduler pasa a v1-greedy-5 para identificar los resultados
nuevos. Las soluciones históricas conservan su algoritmo, hashes, intervalos
y minutos originales. No hay migraciones ni backfill.

## Invariantes y pruebas

- Fechas aware; comparación consistente entre UTC y Cordoba; reloj inyectable.
- Propuesta antigua con trabajo futuro aceptable; trabajo pasado o ya iniciado
  sólo en la propuesta se rechaza si no hay ejecución real.
- Rechazo atómico con y sin CURRENT; sin audit/outbox de promoción nuevos.
- HTTP 409 SCENARIO_EXPIRED, detalle Gantt fuera del rango visible y estado
  preventivo; carrera entre lectura y ACCEPT manejada por backend y UI.
- Retry exitoso idempotente, tenant isolation, concurrencia y rollback.
- Duraciones exactas de 20, 120 y 180 minutos verificadas en dominio y PostgreSQL
  descartable, incluidos almuerzo y cambio de jornada.
- Solución completa con toda su duración asignada: remaining=0 y suma de minutos
  de segmentos igual al total persistido de asignación y fase.
- Regresión de UPDATE_REMAINING_ESTIMATE y flujos de ejecución/instalación.

Los fixtures históricos de aceptación usan relojes controlados, con avance de
microsegundos entre publicaciones sucesivas. Sus intervalos de validez se
preparan en ese mismo calendario. El benchmark prepara trabajo futuro respecto
de su instante fijo de aceptación. Los tests no se conectan a la base del piloto.

## Validación final

| Comprobación | Resultado |
|---|---|
| Backend completo, PostgreSQL descartable | 596 passed, 0 fallas |
| Vitest completo | 211 passed, 18 archivos, 0 fallas |
| Playwright completo, Edge, cuatro viewports | 266 passed, 14 skips preexistentes, 0 fallas |
| Nuevos E2E de vencimiento, incluidos arriba | 8 casos en cuatro viewports |
| TypeScript y Vite | Aprobados |
| OpenAPI y tipos | Generados y sincronizados; igualdad con create_app().openapi() comprobada |
| git diff --check | Aprobado; avisos de conversión LF/CRLF sin errores de whitespace |
| Migraciones nuevas | 0; M0–M13 sin modificaciones; 8 schemas / 87 tablas |
| Integridad de base real | Conteos y hashes de 87 tablas idénticos antes/después |
| Secret scan | Sin candidatos nuevos; sólo dos URLs de ejemplo preexistentes en .env.example intacto |

Comandos de validación:

```powershell
.\.venv\Scripts\python.exe scripts/test_postgres_disposable.py -q --tb=short
cd frontend
npm test
npm run api:generate
npm run build
$env:PLAYWRIGHT_CHANNEL='msedge'
npm run test:e2e -- --workers=2 --reporter=line
```

Los tests backend crearon y eliminaron exclusivamente su base y rol aleatorios
descartables; las variables de conexión fueron sólo del proceso hijo. La base
produccion_besten sólo se consultó con transacciones read-only.

El primer intento E2E no pudo lanzar Chromium porque falta su ejecutable local;
se usó Edge instalado. El primer pase completo con Edge terminó los casos pero
quedó detenido en el cierre del preview administrado por Playwright. Se cerró
ese runner y se repitió con un preview de pruebas levantado por separado y
reuseExistingServer: el pase final terminó con exit code 0. No se cambió la
configuración persistida de Playwright ni se tocaron los servidores del piloto.

Persisten el aviso de bundle grande de Vite y tres warnings backend de
dependencias (dos deprecaciones de Starlette y un aviso de alias de Pydantic
en un test concurrente). No representan fallas de las suites.

## Integridad del piloto y compatibilidad

CURRENT V1 se conserva como evidencia del incidente: no se reparan minutos,
fechas, promoted_at ni audit trail. No se modifica A685, sus REV 1–4, release,
maestros ni planificación real. No se genera escenario 9 ni CURRENT V2 ni
ejecución nueva. Se comparan conteos y hashes de las 87 tablas antes y después,
mediante conexiones PostgreSQL con default_transaction_read_only=on.

La comparación confirmó las 87 tablas sin diferencias de conteos ni hashes:
A685 intacto; REV 1–4 intactas y REV 4 released; 8 escenarios, CURRENT V1 y
ninguna ejecución nueva. Los 10 archivos sin rastrear preexistentes, incluidos
docs/41 y docs/43, conservan sus hashes. Los cambios acumulados son 22 archivos
modificados y 17 nuevos; esta tarea agregó 7 archivos y modificó 19 respecto
del contenido inicial, preservando las mejoras previas.

Los cambios anteriores de Gantt V2, contraste y docs/41 y docs/43 se preservan.
No se hace commit ni push. App de Compras y backup quedan fuera de acceso.

## Paso posterior para obtener CURRENT V2

Después de cargar esta versión del backend y frontend, el responsable deberá
solicitar explícitamente una nueva simulación desde un corte temporal vigente,
revisar operaciones, capacidad, personas, recursos y fecha comprometida, y
aceptarla explícitamente mientras siga siendo válida. Esa promoción creará V2
y conservará V1 como versión histórica. Estos pasos no se ejecutan en esta tarea.

## Estado Git acumulado

Se preservan los cambios anteriores y se agregan estos ajustes, sin staged,
commit ni push. El diff stat siguiente no incluye archivos nuevos sin rastrear.

```text
 M frontend/openapi.json
 M frontend/src/api/schema.d.ts
 M frontend/src/features/gantt/GanttPage.module.css
 M frontend/src/features/gantt/GanttPage.test.tsx
 M frontend/src/features/gantt/GanttPage.tsx
 M frontend/src/features/gantt/GanttTimeline.tsx
 M frontend/src/features/gantt/time.ts
 M frontend/src/test/fixtures.ts
 M src/production_besten/api/dependencies.py
 M src/production_besten/api/routes.py
 M src/production_besten/api/schemas.py
 M src/production_besten/domain/errors.py
 M src/production_besten/domain/scheduling/engine.py
 M src/production_besten/persistence/api_queries.py
 M src/production_besten/persistence/scheduling_uow.py
 M tests/integration/conftest.py
 M tests/integration/test_accept_replan.py
 M tests/integration/test_basic_scheduler.py
 M tests/integration/test_initial_simulation_review.py
 M tests/integration/test_installations.py
 M tests/integration/test_replanning.py
 M tests/unit/test_cumulative_scheduler.py
?? docs/41-gantt-operativo-v2.md
?? docs/43-cloud-readiness-audit.md
?? docs/44-scenario-expiry-and-segment-minute-integrity.md
?? frontend/src/features/gantt/OperationalTimeline.module.css
?? frontend/src/features/gantt/OperationalTimeline.test.tsx
?? frontend/src/features/gantt/contrast.test.tsx
?? frontend/src/features/gantt/ganttTokens.css
?? frontend/src/features/gantt/operationalModel.ts
?? frontend/src/test/ganttV2Fixture.ts
?? frontend/tests/gantt-contrast.spec.ts
?? frontend/tests/gantt-v2.spec.ts
?? frontend/tests/scenario-expiry.spec.ts
?? src/production_besten/domain/scenario_expiry.py
?? src/production_besten/persistence/scenario_expiry.py
?? tests/integration/test_segment_minute_integrity.py
?? tests/unit/test_scenario_expiry.py
?? tests/unit/test_segment_minute_integrity.py
```

```text
 frontend/openapi.json                              | 118 +++++++++++++
 frontend/src/api/schema.d.ts                       |  36 ++++
 frontend/src/features/gantt/GanttPage.module.css   |  25 +--
 frontend/src/features/gantt/GanttPage.test.tsx     |  31 ++++
 frontend/src/features/gantt/GanttPage.tsx          | 105 +++++++----
 frontend/src/features/gantt/GanttTimeline.tsx      | 191 +++++++++------------
 frontend/src/features/gantt/time.ts                |  10 +-
 frontend/src/test/fixtures.ts                      |   2 +-
 src/production_besten/api/dependencies.py          |   2 +-
 src/production_besten/api/routes.py                |   2 +-
 src/production_besten/api/schemas.py               |  15 ++
 src/production_besten/domain/errors.py             |   4 +
 src/production_besten/domain/scheduling/engine.py  |  14 +-
 src/production_besten/persistence/api_queries.py   |  55 +++++-
 .../persistence/scheduling_uow.py                  |  31 +++-
 tests/integration/conftest.py                      |  14 ++
 tests/integration/test_accept_replan.py            |  17 +-
 tests/integration/test_basic_scheduler.py          |   4 +-
 .../integration/test_initial_simulation_review.py  |  81 ++++++++-
 tests/integration/test_installations.py            |   4 +-
 tests/integration/test_replanning.py               |   4 +-
 tests/unit/test_cumulative_scheduler.py            |   2 +-
 22 files changed, 557 insertions(+), 210 deletions(-)
```

## Complemento: selector de escenarios históricos (2026-10-29)

### Causa y alcance

El filtro estaba exclusivamente en PostgresApiQueries.gantt:
`AND (s.scenario_kind='replan' OR p.current_plan_version_id IS NULL)`.
Además sólo admitía status ready/stale, ocultando confirmed. El frontend mostraba
las opciones recibidas, pero ocultaba el botón de confirmación para stale y
trataba cualquier initial como primera simulación sin CURRENT. El read model
sustituía la solución base por la initial seleccionada incluso con CURRENT.

Se separan visibilidad y elegibilidad. Se listan initial/replan con solución,
status ready/stale/confirmed, de la misma organización y planta, con un límite
de 50 opciones y orden created_at DESC/id DESC. El frontend conserva ese orden
temporal y muestra fecha/hora local con año y segundos, tipo y etiquetas
Vigente/revisable, Histórica, Desactualizada o Confirmada. No usa UUID como
etiqueta principal. Son categorías derivadas; no se agrega estado persistido.

El vencimiento de las opciones reutiliza scenario_expired, con una consulta
batched de tiempos y ejecuciones para evitar N+1. El caso CURRENT sin escenario
pasa de seis a siete consultas, independientemente del número de operaciones.

La relación plan_versions.source_scenario_id identifica el origen del CURRENT.
Se expone origin_plan_version_number y se muestra ORIGEN DE CURRENT V1 cuando
corresponde; no se infiere la relación a partir del nombre o de las fechas.
El contrato de opciones incorpora scenario_kind, expired y el origen opcional;
el detalle seleccionado incorpora también el origen opcional.

### Comparación y confirmación

Con CURRENT se mantienen sus operaciones, asignaciones y segmentos como base.
Las fechas de la solución seleccionada se comparan en memoria contra CURRENT,
no contra la base histórica almacenada al generar el escenario. Se muestran las
diferencias temporales, finales por proyecto y ambas fechas por operación,
también en la presentación móvil. En escritorio el initial histórico utiliza
la misma superposición que un replan, sin convertir las barras CURRENT en
barras de primera simulación. Una operación presente sólo en el histórico se
incluye sin atribuirle una programación vigente inexistente.

Los detalles operativos y las asignaciones de la base siguen correspondiendo a
CURRENT. Este ajuste compara las fechas; no recalcula soluciones, capacidades,
recursos, precedencias ni alertas comerciales de dominio. Los datos de la
simulación y su comparación persistida permanecen intactos.

CONFIRMAR NUEVO PLAN permanece visible para la selección. Se deshabilita por
confirmed, expired, stale, estado distinto de ready, solución incompleta o
initial con CURRENT existente. Un texto próximo al botón, asociado mediante
aria-describedby, explica la razón. Un escenario confirmado no puede volver a
promoverse. El histórico vencido muestra:

> SIMULACIÓN DESACTUALIZADA. Esta propuesta contiene operaciones planificadas en el pasado. Generá una nueva simulación para poder confirmarla.

El backend continúa siendo autoridad para cada ACCEPT. No se cambió ningún
archivo del scheduler, de las reglas de vencimiento ni del comando de promoción.
Un initial futuro, completo y sin CURRENT conserva la aceptación explícita;
un replan futuro válido sigue siendo revisable y confirmable. Los reintentos,
locks y validaciones de bases se conservan.

### Validación del complemento

- Backend relevante: 100 passed, 0 fallas, PostgreSQL descartable eliminado.
  Incluye API/read model, iniciales, históricos, origen confirmado, aislamiento,
  aceptación, Gantt asistido, horizonte local y regresiones de minutos/expiry.
- Vitest completo final: 220 passed, 19 archivos, 0 fallas.
- Playwright relevante: 78 passed, 14 skips preexistentes, 0 fallas, Edge,
  cuatro viewports. Incluye 4 casos nuevos de históricos y las regresiones de
  primer plan, propuesta futura, stale y expiry.
- Tras agregar los nombres y las fechas de cada operación a la comparación,
  el subconjunto final de históricos/Gantt/primer plan: 33 passed, 7 skips,
  0 fallas. Es un subconjunto repetido; no se suma al total anterior.
- TypeScript/Vite aprobados; OpenAPI/tipos generados y sincronizados.
- git diff --check aprobado. Secret scan sin candidatos nuevos; las dos URLs
  de ejemplo preexistentes de .env.example continúan intactas.
- Continúan el warning de bundle grande y las deprecaciones backend conocidas.

Comprobación real exclusivamente GET/read-only tras reiniciar el backend:
CURRENT V1 con 8 opciones; selección de initial stale/expired con botón visible
inhabilitado; origen confirmado de CURRENT V1 con cuatro diferencias UNCHANGED.
Se comprobó también en el navegador del piloto, sin invocar ACCEPT ni simular.
Frontend Vite y backend quedan disponibles en 5173 y 8000.

La comparación final de las 87 tablas con el baseline del inicio del ajuste
confirma datos intactos: A685, REV 1–4, REV 4 released, CURRENT V1, 8 escenarios
y ninguna ejecución nueva. Sin escenario 9, CURRENT V2, migraciones, commit ni
push. App de Compras y backup no fueron accedidos.

Archivos del complemento: api_queries.py y schemas.py; GanttPage.tsx,
GanttTimeline.tsx y scenarioPresentation.ts; contratos OpenAPI/tipos y fixtures;
tests del read model, iniciales, presentación y timeline; gantt.spec.ts y el
nuevo gantt-historical.spec.ts. Esta sección complementa el informe sin duplicar
el documento de Gantt V2. Los cambios anteriores se preservan.
