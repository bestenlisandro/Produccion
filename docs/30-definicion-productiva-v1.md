# Definición productiva V1 — Etapa 7.3

Estado: **PRODUCT_DEFINITION_VALIDATED** para el alcance DEV documentado.
Autenticación productiva diferida.
Directorio exclusivo: `C:\Users\BESTEN-01\Documents\ChatGPT\Produccion Besten`.
Branch `master`, HEAD de partida `2d7333e289fb2e3b814751df725c22a2ab15fecd`
(`Project intake validated`), working tree limpio al iniciar.
Sin commit automático ni push.

## Auditoría y compuerta de modelo

Se revisaron README, modelo lógico, cierre lógico, esquema físico, diccionario,
arquitectura backend, contrato API, motor y cierres de maestros/proyectos, además
de las migraciones y las cinco implementaciones productivas existentes.
Las referencias del pedido `07-modelo-fisico-postgresql-v1.md` y
`21-planning-engine-v1.md` corresponden en este repositorio a
`07-esquema-fisico-postgresql-v1.md` y `21-motor-planificacion-v1.md`.

Las 87 tablas alcanzan. No se agrega tabla, migración ni catálogo comercial.
M0–M10 se aplicaron desde cero con el runner descartable: 8 schemas / 87 tablas.

| Concepto | Modelo real y decisión |
|---|---|
| Proyecto | `core.projects`; sigue siendo la unidad administrativa de 7.2 |
| Lote / producto / ítem | `core.project_lots`, con código, nombre, descripción, cantidad, unidad y orden; no se duplica producto |
| Production batch compartido | `production.production_batches` conserva su significado de agrupamiento operativo; no se reutiliza como ítem comercial |
| Ruta | `route_templates`, `route_versions`, pasos y precedencias; asignación histórica `lot_route_assignments` |
| Operación | `required_operations`, instanciada desde un maestro activo |
| Fase | `required_operation_phases`; secuencia dentro de su operación |
| Duración | Minutos enteros canónicos; mayor que cero para congelar |
| Personas / skills | `operation_labor_requirements`; cantidad mínima/máxima, trabajo en minutos-persona y skill; sin asignación de personas concretas |
| Centro / recursos | `operation_physical_requirements`; centro, tipo y/o grupo, cantidad, demanda y modo de uso |
| Revisión congelada | `product_definition_revisions`, snapshot canónico inmutable por planta |
| Concurrencia | `projects.row_version`, locks existentes y conflicto explícito |
| Trazabilidad | Eventos existentes y `audit_entries`, incluida identidad de intención/borrador |

Los requisitos físicos no tienen selector directo de una máquina individual.
La interfaz ofrece centro, tipo y grupo activos; el scheduler elige el recurso
concreto disponible. Los requisitos humanos no tienen nivel mínimo propio: no se
inventa una columna ni se convierte una persona en un requisito abstracto.
La capacidad nominal del centro no se copia a una operación: se guarda únicamente
`capacity_units`, demanda de cada fase.

## Borrador y comandos reutilizados

Los datos del borrador permanecen normalizados. La auditoría registra su lifecycle,
la identidad de borrador y el resultado idempotente; no se esconde una definición
editable completa en settings ni se crea una tabla paralela.

El guardado del agregado reutiliza, dentro de una transacción:
`CREATE_PRODUCTION_BATCH`, `DEFINE_BATCH_ROUTE`, `CREATE_REQUIRED_OPERATION` y
`CREATE_REQUIRED_OPERATION_PHASE`. Se agregan únicamente lectura, edición,
validación y coordinación de freeze/new-revision. El congelado reutiliza
`CREATE_PRODUCT_DEFINITION_REVISION`, incluida su genealogía, hash y revisión
operativa. Application delega al UoW; los routers no contienen reglas productivas.

Se puede guardar un borrador incompleto. Se pueden agregar y editar múltiples
lotes, operaciones y fases, quitar operaciones/fases y reordenarlas con botones.
Quitar archiva las filas normalizadas: mantiene identidades referenciadas por planes
e historia. Los requerimientos físicos conservan IDs; los retirados dejan de ser
obligatorios. No hay DELETE de revisiones congeladas.

La ruta puede partir de una versión publicada existente o definirse manualmente
con las operaciones seleccionadas del maestro. En el segundo caso se usa una ruta
propia del lote sobre las tablas de rutas existentes, con versiones publicadas que
no se editan. Cambiar su contenido crea otra versión y cierra la asignación anterior
mediante DEFINE_BATCH_ROUTE. Esto no implementa un catálogo de plantillas de
productos, clonado comercial ni automatismos de producción repetitiva.
Las operaciones requeridas son la secuencia instanciada editable: ajustar esta
secuencia no reescribe una ruta base publicada.

En UI, subir/bajar establece precedencias fin-a-inicio entre operaciones sucesivas.
La API admite DAGs del mismo lote y exige un orden topológico consistente. Se
rechazan autorreferencias, ciclos, referencias fuera del lote y códigos repetidos.
Las fases se ordenan mediante `sequence_no`, sin un segundo grafo interno.

## Validación, freeze e historia

La validación devuelve una lista de errores: lote ausente, ruta ausente/inactiva,
operaciones/fases faltantes, duración cero, requisitos incoherentes, maestros
inactivos/inexistentes/de otra planta, ciclos y orden inconsistente.
Los borradores incompletos se conservan, pero las violaciones de grafo, identidad y
maestros activos se rechazan al guardar. Inputs estructuralmente inválidos son 422.

CONGELAR DEFINICIÓN pide confirmación y requiere guardar previamente los cambios.
Genera el snapshot completo y mueve sólo el puntero de definición productiva.
No ejecuta scheduler ni publica CURRENT. Congelar un proyecto conserva el contenido
congelado de los otros proyectos de la planta, aunque éstos tengan otro borrador.

La revisión es por planta: los números mostrados son los reales, no un contador
ficticio por proyecto. Las revisiones anteriores se muestran con fecha, estado,
lotes, operaciones y contenido histórico. El contenido congelado se lee del
snapshot, sin reinterpretar nombres/requisitos mediante selects de maestros activos.
Inactivar un maestro no altera esa lectura; una nueva definición debe corregir su
uso antes de congelarse.

CREAR NUEVA REVISIÓN abre un borrador con identidad distinta y contenido derivado
de la vista normalizada anterior. Modificarlo no altera snapshots anteriores.
Si no existen cambios semánticos, el comando existente deduplica la revisión; el
editor lo informa como conflicto sin aparentar haber creado otra revisión.
Reactivar exactamente una revisión histórica no vigente mantiene el rechazo V1.

## Scheduler, CURRENT y ejecución

La auditoría detectó que el loader anterior materializaba demanda desde las tablas
corrientes, aunque adjuntaba el snapshot congelado. Para proyectos congelados por
este editor se reconstruyen duración, fases, requisitos, orden y precedencias desde
su snapshot semántico. Se resuelven identidades normalizadas estables, incluidas
filas archivadas por el siguiente borrador. Capacidad, calendarios, prioridad y
compromisos operativos actuales siguen su contrato existente.

`editor_frozen_projects` es una extensión aditiva del documento canónico para
identificar este contrato de lectura. No almacena UUID, credenciales ni datos de
capacidad mutable. Los snapshots anteriores conservan el loader compatible V1.
El algoritmo sigue siendo `v1-greedy-3`.

Un proyecto nuevo sin freeze no entra a planificación, incluso con lotes y fases.
Con freeze válido puede alimentar una simulación si está activo y satisface las
reglas operativas existentes. Congelar no activa automáticamente el proyecto.

El nuevo freeze genera revisión operativa, marca escenarios pendientes stale y
persiste `current_affected` cuando el proyecto aparece en CURRENT. No modifica el
puntero, resultados, asignaciones ni segmentos del plan publicado. Las pruebas
comparan los resultados publicados completos antes/después.

Mientras hay un borrador industrial pendiente, START_OPERATION no puede consumir
estimaciones editables sin congelar. El inicio devuelve un conflicto explícito;
congelar habilita de nuevo el flujo existente. La edición de proyectos que ya tienen
cualquier ejecución registrada se rechaza: rediseñar trabajo ejecutado necesita un
flujo específico, separado de estimación restante. No se manipula ejecución real ni
RemainingEstimateRevision desde este editor. Los locks de operaciones impiden que
un inicio concurrente deje pasar una edición sobre ejecución recién registrada.

## API, idempotencia y aislamiento

| Método | Ruta | Resultado |
|---|---|---|
| GET | `/product-definition/options` | Maestros activos y rutas publicadas |
| GET | `/projects/{id}/product-definition` | Borrador, validación e historia |
| PUT | `/projects/{id}/product-definition` | Guardado atómico del borrador completo |
| POST | `/projects/{id}/product-definition/validate` | Validación persistida/idempotente |
| POST | `/projects/{id}/product-definition/freeze` | Congelado explícito |
| POST | `/projects/{id}/product-definition/new-revision` | Nuevo borrador derivado |

No se duplican los endpoints de comandos individuales existentes. Todas las nuevas
mutaciones requieren Idempotency-Key y expected_row_version. El digest incorpora
organización, planta, actor, proyecto, acción, versión y payload completo. Replay
retorna el resultado original; otra intención con la misma clave da 409. No duplica
freeze. El conflicto de edición tiene código PRODUCT_EDITOR_VERSION_CONFLICT y
mensaje: “La definición productiva cambió desde que la abriste. Actualizá antes de
guardar.” No hay last-write-wins silencioso; se prueban dos guardados concurrentes.

Las consultas verifican organización y planta del proyecto. IDs de lotes,
operaciones y fases se comprueban contra sus padres. Centros/grupos pertenecen a
la planta; las demás referencias al tenant. SQL usa parámetros. Errores de
persistencia se mantienen seguros mediante los handlers existentes.

## Interfaz

Desde `/projects/:projectId`, DEFINIR PRODUCCIÓN abre
`/projects/:projectId/product-definition`. Hay empty/loading/error/retry,
formularios de lotes y ruta, operaciones expandibles, fases, duración en minutos,
centros, demanda, personas, skills y tipos/grupos de recursos. No se muestran UUID
ni foreign keys. Los nombres productivos provienen de maestros.

Ante errores, el formulario conserva su input. Un 409 ofrece actualización
explícita. Ante resultado incierto, se bloquean nuevas intenciones y se reintenta
el mismo cuerpo con la misma key; esa intención no sobrevive una recarga del
navegador. Congelado se presenta en sólo lectura, desde el snapshot histórico.
No hay drag sofisticado, asignación humana manual ni comparación gráfica compleja.

## Pruebas y benchmark

| Validación | Resultado |
|---|---|
| Backend PostgreSQL completo | **425 passed**, 0 failed, 57,62 s |
| Backend baseline + nuevos | 376 + 49 |
| Vitest completo | **118 passed**, 0 failed (90 + 28) |
| Playwright completo Edge | **135 passed**, 13 skips preexistentes, 0 failed |
| Playwright editor, incluido en total | **28/28**; repetido después de ajustar la vista histórica |
| Total aprobado sin duplicar subconjuntos | **678 pruebas** (573 + 105) |
| TypeScript / Vite | Aprobados |
| OpenAPI / tipos | Exportados desde FastAPI real y regenerados; comparación exacta verde |
| Migraciones | M0–M10 desde cero: 8 schemas / 87 tablas; cero nuevas |
| Git / secretos | diff --check aprobado; 184 archivos escaneados, sin secretos nuevos |

El primer intento de iniciar herramientas frontend usó npm, ausente en PATH; se
utilizaron Node y las CLI locales instaladas. Una invocación inicial de Playwright
apuntó a un archivo todavía no creado y terminó sin pruebas; las corridas válidas
posteriores son las que se contabilizan arriba. Se corrigieron expectativas del
fixture de capacidad (centro y recurso acumulativos), timestamps de resultados de
prueba y el nombre real del campo de duración del input scheduler. No se relajaron
invariantes ni se agregaron skips para obtener los resultados.

Las correcciones de implementación cubren lectura congelada frente a borradores,
conservación de demanda retirada, precaución de ejecución antes de freeze,
inmutabilidad de la lectura histórica con maestros inactivos y publicación de
rutas manuales únicamente cuando sus operaciones tienen fases/duraciones válidas.

Baseline preservado: 376 backend, 90 Vitest y 107 Playwright, con 13 omisiones
responsive preexistentes. Las expectativas previas del botón deshabilitado de 7.2
se actualizan para comprobar la acción ahora habilitada; no se quitan pruebas.

La cobertura PostgreSQL incluye lotes múltiples, edición, rutas publicadas/manuales,
operaciones/fases, duración, requisitos, demanda acumulativa, habilidades/recursos
realmente asignados, DAG, maestros inactivos, freeze idempotente, inmutabilidad,
nueva revisión, borrado lógico, carga congelada frente a borrador cambiado/vacío,
proyecto sin freeze, conservación de otros proyectos, reconciliation, CURRENT,
scenarios stale, concurrencia real, aislamiento, rollback, 404/409/422 y ejecución.
OpenAPI se exporta desde FastAPI real; los tipos se regeneran con openapi-typescript.
La prueba OpenAPI del backend compara el documento generado completo.

Playwright prueba UI real con HTTP simulado determinista. La persistencia y el
recorrido HTTP/FastAPI→PostgreSQL→scheduler se prueban aparte sobre PostgreSQL real;
no se presenta el mock como medición SQL ni como un ensayo browser→DB completo.

Fixture: 1 proyecto / 5 lotes / 50 operaciones / 100 fases. Lectura HTTP con
PostgreSQL: **45,08 ms, 69.663 bytes, 17 consultas**, constante respecto del número
de operaciones; no N+1 en esta lectura. El freeze conserva el constructor de
snapshot V1, que realiza consultas por agregado; no se atribuye al freeze ese
benchmark ni se promete un SLA.

Render Playwright con fixture simulado de 24.619 caracteres JSON:
1440×900 803 ms; 1366×768 692 ms; 1024×768 758 ms; 390×844 643 ms.
Sin desborde horizontal; captura móvil inspeccionada visualmente.

## Límites, warnings y seguridad

- Autenticación: DEV ONLY / BLOCKER FOR PRODUCTION. Se conserva RequestContext DEV;
  no login, usuarios, passwords, JWT, Supabase Auth ni RBAC productivo.
- Plantillas productivas reutilizables, compras, stock, proveedores, portal cliente,
  PWA, realtime y optimización matemática continúan diferidos.
- No se agregan ubicación de obra ni fecha prevista de medición, límites aceptados en 7.2.
- La UI ofrece secuencia lineal robusta; DAGs más generales se validan en backend.
- La UI administra duración transcurrida y requisitos abstractos; no añade curvas
  avanzadas de productividad, selección de personas concretas ni edición de gates.
  Los gates existentes se conservan en las revisiones.
- Proyectos con ejecución registrada no se rediseñan desde este editor.
- Persisten dos warnings de dependencias Starlette/httpx y alias anyio.
- Vite advierte bundle de 1.781,74 kB (357,55 kB gzip); no se cambian dependencias.
- Playwright mantiene los avisos NO_COLOR/FORCE_COLOR preexistentes.

App de Compras y BACKUP Produccion Besten recuperado no fueron accedidos,
inspeccionados, ejecutados ni modificados. No se leyó pgpass.conf ni se modificó
pg_hba.conf. El runner elimina sus bases y roles en finally; las variables de
conexión se limitan al proceso hijo. Al cierre se verificaron Python 3.11.9,
PostgreSQL 18.6 operativo, cero bases/roles descartables y ausencia de
TEST_DATABASE_URL/PGPASSWORD en el proceso principal. git diff --check pasó,
incluida revisión de whitespace en archivos nuevos. El escaneo por patrones de
184 archivos no encontró secretos nuevos; los dos placeholders previos de
.env.example se verificaron sin imprimir valores y quedaron intactos.
No se incluyen .env, pgpass, node_modules, dist, test-results, playwright-report,
logs, caches, bases, certificados ni claves. Hay 11 archivos modificados y 12
nuevos, sin staging, commit ni push.

Conclusión formal: **PRODUCT_DEFINITION_VALIDATED** en el alcance DEV documentado.
