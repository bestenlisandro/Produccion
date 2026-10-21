# Administración de maestros operativos V1 — Etapa 7.1

Estado al 21 de octubre de 2026: **MASTER_DATA_ADMIN_VALIDATED** para el alcance
local DEV de esta etapa. Autenticación productiva continúa diferida.

## Entorno y recuperación

Directorio exclusivo: `C:\Users\BESTEN-01\Documents\ChatGPT\Produccion Besten`.
Branch `master`; HEAD `dc80851938a31433dbbf4d7a2887ec066e49f395`.
Se preservó el working tree recibido: 12 archivos versionados modificados y
12 archivos nuevos al inicio, incluidos los tres archivos de master-data frontend.
No se restauraron archivos ni se ejecutaron reset, clean, stash, rebase o squash.
No se realizó commit ni push.

La primera recuperación quedó correctamente detenida por falta de Python 3.11 y
PostgreSQL 18. En la reanudación se comprobaron Python **3.11.9**, `.venv` recreado
con ese intérprete y PostgreSQL **18.6** operativo en `127.0.0.1:5432`.
Git es 2.56.0.windows.2 y Node v24.19.0. npm no está disponible en el PATH de esta
sesión: build y pruebas se ejecutaron mediante los mismos entrypoints Node de los
scripts versionados. No se actualizaron dependencias ni lockfile.

La credencial administrativa existente se utilizó mediante libpq sin leer,
imprimir ni copiar pgpass.conf. El runner `scripts/test_postgres_disposable.py`
crea un rol NOLOGIN y una base aleatorios propios. Las conexiones de tests adoptan
ese rol mediante options; no se generan ni persisten contraseñas. TEST_DATABASE_URL
existe sólo en el entorno del subprocess pytest. La limpieza se ejecuta en finally.
El runner no usa bases de otras aplicaciones.

## Estructuras reutilizadas y entidades

M0–M10 permanecen intactas: **11 archivos, 8 schemas y 87 tablas** aplicados desde
cero y comprobados en el catálogo PostgreSQL. No se agregaron migraciones.

- Personas: `capacity.employees`; identidad de producción separada de cuentas de
  usuario. Código, nombre, calendario y centro habitual; create/update y estados.
- Skills: `capacity.skills`; código único por organización, nombre, descripción,
  categoría y estados. Skills inactivas no satisfacen requirements futuros.
- Persona–skill: `capacity.employee_skills`, con vigencia daterange y auditoría.
- Centros: `capacity.work_centers`; modo exclusivo/acumulativo, capacidad nominal,
  unidad y calendario opcional, con herencia del calendario base de planta.
- Recursos: `capacity.physical_resources` y tipos existentes. Se valida pertenencia
  del centro a la planta. Cambiar de centro persiste realmente el nuevo vínculo.
  Recursos, centros o tipos inactivos quedan excluidos de nuevas planificaciones.
- Calendarios: `capacity.calendars`, `calendar_working_intervals` y
  `calendar_exceptions`; horarios locales interpretados mediante timezone IANA.
- Planta: `core.plants`; código, nombre, timezone, calendario base y umbral de
  comunicación. IDs, organización, punteros CURRENT y revisiones no se exponen
  como configuración editable.

Activar/desactivar conserva filas, referencias e historia de ejecución y planes.
Calendarios también tienen endpoint de estado y control explícito en frontend.
Las ediciones principales requieren `expected_row_version`; un conflicto es 409.
Las referencias de otra organización/planta se ocultan mediante 404 según el
alcance físico de cada entidad. Calendarios y skills son compartidos por organización.

## Historia y vigencia persona–skill

Asignar una habilitación inserta una fila nueva. Si el rango reemplaza parte de una
habilitación, se conserva el tramo anterior y se inserta el tramo posterior cuando
corresponde. No se reutiliza silenciosamente la última fila para cambiar su pasado.
La exclusión M9 impide rangos solapados entre habilitaciones enabled.

Quitar una skill rige desde la fecha local de planta: cierra el rango vigente,
conserva el tramo histórico habilitado y cancela las habilitaciones futuras.
Una fila cerrada puede seguir teniendo enabled=true porque ese valor conserva su
validez histórica; la vigencia actual depende también del rango semiabierto.
Un alta anulada en su mismo día queda deshabilitada sin crear un rango vacío.
La auditoría registra la colección previa y la colección posterior de asignaciones.
La fecha por defecto se calcula en backend con IANA de planta; el scheduler usa
esa misma zona para comprobar vigencias de skills durante su horizonte.

## Capacidad nominal del centro

El scheduler carga `aggregate_capacity` desde PostgreSQL en `WorkCenterData` y lo
incluye en su snapshot de entrada. El modo exclusivo equivale a capacidad 1.
Cada demanda física consume unidades tanto del recurso seleccionado como de su
centro. Recursos distintos del mismo centro comparten ese límite; los centros y
sus calendarios también limitan la asignación.

Regresión real: PATCH de centro con capacidad 2 → DB conserva 2 → snapshot de
scheduler contiene 2 → dos demandas unitarias comienzan simultáneamente → demandas
adicionales se desplazan al liberar capacidad. Se verifican también capacidades 1
 y 3. Nunca se admite sobrecarga para satisfacer una intención manual.

Se consideran demandas planificadas, usos reales y ocupaciones reales de estaciones.
Una ocupación mantiene capacidad durante los huecos entre jornadas; no duplica el
uso real simultáneo de esa misma estación. Como physical_occupations no tiene una
columna de demanda, para ocupaciones reales se reserva conservadoramente la
capacidad nominal del recurso. No se agregó una migración por ese motivo.
Las unidades nominales del centro y las demandas deben configurarse coherentemente;
esta etapa no introduce conversiones entre unidades físicas.

Las regresiones anteriores de capacidad de recurso preparaban centros de capacidad
1 pero esperaban simultaneidad mayor. Se corrigió exclusivamente su fixture para
que el centro no sea el cuello de botella en esas pruebas. Las nuevas regresiones
prueban el límite de centro independientemente; no se debilitó el scheduler.

## Calendarios, ventanas y excepciones

El snapshot incluye todas las vigencias, también las históricas y futuras.
Frontend selecciona ventanas por `valid_from <= effective_from < valid_to`, con
extremos abiertos cuando corresponda. `effective_from` es explícito en el contrato.
Editar una jornada reemplaza el tramo desde esa fecha hasta la próxima frontera
existente, preservando el pasado y las programaciones posteriores, incluidos finales
finitos sin una nueva programación inmediata. Los rangos son semiabiertos.
Se rechazan ventanas semanales solapadas y órdenes locales inválidos.

La fecha inicial del editor se obtiene mediante Intl.DateTimeFormat en la zona IANA
del calendario, sin recortar una fecha UTC. El backend usa la zona de planta para
habilitaciones y la zona del calendario para horarios/excepciones. Los cambios de
timezone no convierten timestamps históricos.

Las excepciones admiten create/update, fecha, efecto add/remove/replace, horario,
factor y descripción. Un PATCH puede moverlas a otro calendario de la misma
organización: valida el destino, persiste calendar_id y convierte el rango local
usando la zona destino. No se acepta un campo para después ignorarlo.
El formulario permite elegir explícitamente ese calendario. Inicio/fin deben
informarse juntos y estar ordenados. Horas inexistentes o ambiguas por DST se
rechazan, dado que este contrato local no incluye un selector de fold.

Los factores de capacidad se cargan desde ventanas y excepciones y afectan la
capacidad acumulativa de recursos y centros durante el tramo correspondiente.
La disponibilidad de personas conserva su semántica discreta y sus horarios.

## Impacto, CURRENT y reconciliation

`_usage_counts()` obtiene en una consulta los números de **operaciones distintas
referenciadas por CURRENT**, no el número de segmentos ni referencias maestras
ajenas al plan. Incluye personas, recursos, centros, requirements de skills,
calendarios de personas/recursos/centros y **calendario base de planta**.
Persona–skill cruza empleado y skill requerida. Un calendario sin uso relevante
no presenta un conteo artificial por tener referencias maestras.

Una modificación operativa crea una `planning.planning_state_revisions`, actualiza
`planning_state_heads` y marca stale los escenarios pendientes basados en revisiones
anteriores. Se reutilizan estructuras y estados existentes. La escritura ocurre en
la misma transacción que el maestro y la auditoría. Los locks siguen el orden
planta → head → entidad. Las ediciones descriptivas de entidades principales y los
no-op numéricos no adelantan la revisión. Las ediciones de ventanas, excepciones y
habilitaciones invalidan conservadoramente los escenarios correspondientes.

Los cambios de entidades locales afectan su planta. Skills y calendarios son
compartidos: sus cambios invalidan conservadoramente escenarios de las plantas de
la organización. El conteo y el indicador de impacto en CURRENT se calculan para
cada planta; no se afirma uso CURRENT en plantas donde no existe.

El change_summary registra `current_affected`. La consulta de detalle operativo
expone persistentemente `plan_requires_reconciliation` cuando hay revisiones
relevantes posteriores a la del plan vigente; no depende de conservar el mensaje
transitorio del formulario. Una nueva persona puede volver stale una simulación
porque cambia la oferta, sin afirmar que CURRENT usaba esa nueva persona.
Mover una excepción considera también su calendario anterior para el impacto.

Se probaron persona, skill de persona, recurso, centro, reducción de capacidad,
jornada de calendario, estado de calendario y cambio de calendario de planta.
En todos los casos relevantes CURRENT, sus filas y sus segmentos permanecen
idénticos; un escenario previo no puede promoverse y devuelve conflicto stale.
No hay reprogramación ni promoción automática.

## Idempotencia y transacciones

Las mutaciones requieren Idempotency-Key UUID. El digest incluye organización,
planta, actor, acción, tipo, entidad destino, payload y versión esperada.
Misma intención/contexto devuelve replay sin repetir auditoría o revisión;
cambiar planta, actor o payload con la misma clave produce conflicto.

Entradas antiguas sin contexto versionado sólo se reproducen si el hash anterior,
el actor y la planta pueden comprobarse desde el resultado persistido. Si una
entrada compartida antigua no contiene evidencia de planta, se rechaza como
conflicto: no se infiere un contexto que permitiría replay cruzado.

Frontend congela una copia del comando y su clave hasta confirmar el resultado.
Un error de red/5xx habilita REINTENTAR GUARDADO con ese mismo comando/clave.
Una intención nueva usa otra clave. Errores definitivos conservan inputs para
corregir y volver a guardar. No se limpia/cierra el formulario hasta éxito.
El reintento vive en la sesión montada, no sobrevive una recarga del navegador.

## API y frontend

Prefijo `/master-data`; **22 operaciones HTTP**, incluido GET `/snapshot`.

| Entidad | Operaciones |
|---|---|
| people | POST colección, PATCH ID, POST ID/status |
| people/ID/skills/SKILL | PUT asignar, DELETE quitar |
| skills | POST colección, PATCH ID, POST ID/status |
| work-centers | POST colección, PATCH ID, POST ID/status |
| resources | POST colección, PATCH ID, POST ID/status |
| calendars | POST colección, PATCH ID, POST ID/status, PUT ID/windows |
| calendar-exceptions | POST colección, PATCH ID |
| plant | PATCH configuración contextual |

React, TypeScript, TanStack Query y fetch conservan la arquitectura existente.
Los editores de personas, skills, centros, recursos y calendarios se remontan por
entity_id para impedir mezcla de identidad/controles al seleccionar otro registro.
Los labels tienen asociación explícita y nombres diferenciados para descripciones
de calendario y excepción. Hay loading, empty, error, retry y warnings CURRENT.

OpenAPI fue exportado desde la aplicación FastAPI real con el script versionado;
los tipos se regeneraron mediante openapi-typescript, sin edición manual.
Un test compara exactamente el JSON exportado con app.openapi() real.
La exportación construye el engine PostgreSQL y no usa SQLite como sustituto.

## Validación final y benchmark

| Comprobación | Resultado |
|---|---|
| Primeros tests recuperados, antes de corregir | 10 passed, 0 failed, 2,31 s |
| Backend completo final PostgreSQL 18.6 | 344 passed, 0 failed, 26,61 s |
| Maestros recuperados y regresiones nuevas incluidas | 68 pruebas (10 + 58) |
| Baseline anterior al disco | 276; total final 276 + 68 = 344 |
| Vitest completo | 69 passed, 0 failed |
| Playwright completo Edge, cuatro viewports | 79 passed, 13 skipped, 0 failed |
| Maestros dentro de Playwright completo | 28/28, sin omisiones |
| Total aprobado, sin contar subconjuntos dos veces | 492 pruebas |
| TypeScript y Vite build | Aprobados |
| OpenAPI exportado vs FastAPI real | Coincidencia exacta |
| M0–M10 desde cero | 8 schemas, 87 tablas en catálogo |
| git diff --check | Aprobado |

Las omisiones Playwright son preexistentes: 10 casos Gantt excluidos en smartphone
 y 3 ejecuciones del caso exclusivo smartphone en desktop/tablet. No se agregaron
skips. Playwright usa API simulada para probar UI; la persistencia y el scheduler
se prueban separadamente mediante HTTP/FastAPI y PostgreSQL real. No se presenta
la prueba de recarga del mock como evidencia de persistencia SQL.

Benchmark real de snapshot: 50 personas, 20 skills, 20 recursos y calendario/centro
representativos; **114,19 ms**, payload **31.691 bytes**, **10 consultas SQL**.
La prueba limita el número de consultas para detectar N+1. El tiempo incluye
transporte TestClient y preparación HTTP local, no constituye un SLA.
Benchmark de render Playwright con payload simulado de 34.929 bytes: 1440 px
305 ms; 1366 px 325 ms; 1024 px 323 ms; 390 px 271 ms. Sin desborde horizontal.

Comando reproducible desde la raíz:

```powershell
.\.venv\Scripts\python.exe scripts/test_postgres_disposable.py -q
```

El runner aplica migraciones desde cero, valida catálogo, ejecuta pytest y elimina
su base y rol. No guarda credenciales ni cambia pg_hba.conf.

## Warnings, límites y seguridad

La corrida final backend produjo dos warnings de dependencias: deprecación de
httpx con Starlette TestClient y del alias anyio.abc.BlockingPortal. No se
actualizaron paquetes para silenciarlos. Una corrida intermedia emitió además un
warning Pydantic de alias en contexto concurrente; no apareció en la corrida final.
Vite advierte bundle grande: JavaScript 1.752,72 kB minificado (350,93 kB gzip).
Playwright emitió advertencias NO_COLOR/FORCE_COLOR y una conexión proxy rechazada
durante teardown de un caso con rutas simuladas, sin fallas de pruebas. Tras todos
los resultados se cerró sólo su proceso Vite preview para permitir terminar al runner
con exit code 0; no se cerraron procesos ajenos.

No se implementan login, usuarios, passwords, JWT, Supabase Auth ni RBAC productivo.
El contexto DEV **no es una solución de autenticación para producción**. Aislamiento
y validaciones tenant se mantienen. No se introducen stock, compras, proveedores,
PWA, realtime ni funciones ajenas a administración de maestros.

Al finalizar se comprobaron PostgreSQL operativo, ausencia de bases/roles del
prefijo descartable, TEST_DATABASE_URL/PGPASSWORD ausentes en el proceso principal,
pgpass fuera del repo y outputs/caches ignorados. pg_hba.conf no fue modificado.
El escaneo de archivos versionados y nuevos no ignorados no encontró candidatos
a passwords en URLs PostgreSQL, claves privadas ni formatos comunes de tokens.
Es un escaneo por patrones y no una garantía absoluta de ausencia de secretos.
App de Compras y BACKUP Produccion Besten recuperado no fueron accedidos,
inspeccionados, ejecutados ni modificados.

Conclusión: **MASTER_DATA_ADMIN_VALIDATED** en el alcance DEV solicitado.
Sin migraciones nuevas y sin commit automático.
