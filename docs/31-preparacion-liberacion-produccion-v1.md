# Preparación y liberación a producción V1 — Etapa 7.4

Estado: **PRODUCTION_RELEASE_VALIDATED** en el alcance DEV documentado.
Autenticación productiva diferida.
Directorio: `C:\Users\BESTEN-01\Documents\ChatGPT\Produccion Besten`.
Branch `master`, checkpoint inicial `a2e7803718fb8b44dddbd86258d104519eaa58c2`
(`Product definition editor validated`); working tree limpio al iniciar.
Sin commit ni push automáticos.

## Auditoría y compuerta de modelo

Se revisaron README, modelo lógico/cierre, esquema físico, diccionario, arquitectura,
contrato API, scheduler, reprogramación, promoción, proyectos y editor productivo;
también migraciones y adaptadores reales. Los nombres vigentes son
`07-esquema-fisico-postgresql-v1.md`, `21-motor-planificacion-v1.md`,
`23-reprogramacion-desvios-v1.md` y `24-promocion-programa-v1.md`.

No existe una columna específica de release en Project. Sí existe un modelo formal
para hechos operativos: `planning.effective_events`, con tipo, entidad, actor,
fecha efectiva, payload versionado, revisión operativa, referencia externa única e
historia compensatoria. Permite representar la decisión explícita sin agregar una
columna redundante ni reutilizar el estado administrativo del proyecto.

| Concepto | Estructura reutilizada |
|---|---|
| Estado administrativo | `core.projects.status`: draft/active/inactive/archived |
| Medición/replanteo realizados | `milestone_definitions` / `project_milestones` y superseding de 7.2 |
| Definición industrial | ProductDefinitionRevision, snapshot congelado y borrador normalizado de 7.3 |
| Requisitos del proceso | `operation_gates`, por operación/fase, con targets tipados |
| Material requerido | `material_requirements`, asignaciones netas y recepciones propias existentes |
| Planos/documentos | `drawing_packages` y `drawing_releases` |
| Herrajes | Estado/disponibilidad del lote, sólo si un gate lo exige |
| Release/retiro | EffectiveEvent versionado, entidad project, con revisión y evidencia |
| Concurrencia | `projects.row_version`, token de evaluación, locks organización/planta/proyecto |
| Reconciliation | PlanningStateRevision, head, change_summary y escenarios stale |
| CURRENT | PlanVersion y resultados publicados: no se reescriben |

No hay brecha estructural indispensable para este alcance. Cero migraciones.
M0–M10 se reproducen desde cero con 8 schemas y 87 tablas.
No se crea tabla 88 ni un booleano manual ready=true.

## Freeze ≠ release

Freeze significa que existe una definición industrial reproducible. Release es
una autorización humana explícita para próximas simulaciones. Completar el último
requisito o congelar no libera automáticamente.

El estado efectivo de release se deriva del último evento
`PROJECT_PRODUCTION_RELEASED` / `PROJECT_PRODUCTION_WITHDRAWN` de ese proyecto,
ordenado por revisión operativa y tiempo. Ambos usan payload_schema_version=1.
El retiro agrega un evento compensatorio enlazado al anterior: no lo elimina.

La autorización registra la ProductDefinitionRevision vigente, su número, el hash
semántico de la demanda industrial del proyecto, la evaluación/checklist y el actor
DEV lógico. Se conserva toda la historia. El hash industrial abarca lotes y
operaciones, excluyendo prioridad, compromiso y demás cabecera administrativa.

Una nueva revisión con contenido industrial distinto requiere una nueva liberación.
El freeze de otro proyecto no revoca ésta si su demanda sigue idéntica. Prioridad y
compromiso continúan siendo dimensiones operativas propias y generan reconciliation
mediante los comandos existentes; no se confunden con autorización productiva.

## Readiness derivado

GET calcula qué falta y no guarda un estado manual ni crea eventos. Devuelve
NO LISTO, LISTO, LIBERADO o BLOQUEADO, requisitos individuales, revisión, hora de
esta evaluación y token de concurrencia. No se presenta la hora de evaluación como
un hecho persistido. El proyecto debe estar activo; activarlo no equivale a liberarlo.

Se evalúan:

- Definición congelada con demanda/fases válidas.
- Ausencia de borrador pendiente para una nueva liberación.
- Tipos de operación, centros, skills y selectores físicos activos y del ámbito correcto.
- Hitos requeridos por los gates del snapshot congelado.
- Materiales obligatorios del snapshot y materiales apuntados por gates.
- Paquetes documentales requeridos y planos apuntados por gates.
- Herrajes y fechas explícitas de los gates aplicables.

Medición y replanteo NO se hacen universales. Sin gate correspondiente se muestran
como no exigidos por el proceso; si existe, un hecho realizado satisface el requisito
y su ausencia bloquea. Se reutilizan los formularios y hechos de 7.2. No se agrega
fecha prevista ni ubicación de obra. Otros hitos configurados también se evalúan.

Para materiales se compara cantidad requerida con asignaciones netas de recepciones
realizadas, respetando hechos superseded. Son estructuras propias preexistentes de
Producción Besten; no se añade stock, compras, proveedores ni órdenes de compra,
ni se consulta la aplicación de Compras. No hay marca ficticia en notas.

Para documentación se comprueba liberación vigente, realizada y no retirada.
No se implementa un gestor documental. Los datos de recepción y documentación se
consultan; sus módulos de mantenimiento/integración no se construyen aquí.

V1 evalúa conservadoramente todos los gates obligatorios antes de liberar el
proyecto completo, incluidos before_finish. No hay liberación parcial por lote/fase.
Readiness no promete disponibilidad horaria ni una solución factible: calendarios,
fechas futuras, disponibilidad real, capacidad y asignaciones siguen en el scheduler.

## Decisión explícita, retiro y concurrencia

La tarjeta muestra el checklist antes de habilitar LIBERAR A PRODUCCIÓN. Pide:
“Este proyecto quedará disponible para las próximas simulaciones de planificación.
El plan vigente no será modificado automáticamente.” Cancelar no hace una escritura.
No se muestra éxito optimista ante rechazo backend.

Release/retiro escriben evento, revisión operativa, auditoría y row_version en una
transacción. Registran current_affected cuando hay resultados del proyecto en
CURRENT y vuelven stale escenarios pendientes de la planta. No mueven el puntero
CURRENT, operaciones, asignaciones ni segmentos publicados; tampoco inician ejecución.

RETIRAR DE PLANIFICACIÓN afecta elegibilidad futura. Se rechaza si existe ejecución
registrada. Con CURRENT y sin ejecución, retira de futuras simulaciones y requiere
reconciliation, conservando los resultados actuales. No cancela trabajo real.

Cada mutación requiere Idempotency-Key, expected_row_version, evaluation_token y
motivo. El digest de intención incluye tenant, planta, actor, destino, acción y
payload completo. Replay devuelve el mismo resultado sin duplicar evento, revisión
ni simulación. Otra intención con la misma clave es 409.

El token incorpora versión de proyecto, definición, head operativo, último evento
y checklist. Se recalcula bajo locks antes de aceptar la decisión. Cambios de
proyecto, revisión, gate/hito o maestro relevante rechazan una evaluación anterior.
Mensaje: “El proyecto cambió desde que verificaste su preparación. Actualizá y volvé
a revisar antes de liberar.” Se prueban decisiones concurrentes reales, sin
last-write-wins. Los SQL usan parámetros y los handlers mantienen errores seguros.
Organization/plant del contexto se verifican en lecturas y escrituras.

## Scheduler, revisiones y CURRENT

La carga del scheduler exige un evento de release vigente que autorice la demanda
congelada. Freeze sin release queda excluido, incluso con prioridad alta o atraso.
La lista explícita de proyectos tampoco evita esa compuerta.
En definiciones canónicas también se comprueban las condiciones reales de readiness;
los blockers posteriores de recursos/gates no se convierten en trabajo autorizado.

Un borrador nuevo sobre REV 1 liberada no sustituye la demanda autorizada: REV 1
puede seguir en simulaciones, pero ready para liberar el borrador es falso. Tras
freeze de REV 2 industrialmente distinta, se exige release de REV 2. CURRENT
conserva la revisión anterior, se genera reconciliation y escenarios anteriores
quedan stale. Las próximas simulaciones usan la revisión autorizada correspondiente.

El loader mantiene compatibilidad con snapshots históricos vacíos del backend,
pero también para ellos exige un evento explícito de liberación. No hay bypass
productivo que libere por antigüedad, prioridad o estado active.

Los fixtures históricos de las pruebas anteriores se preparan explícitamente como
trabajo ya liberado. Sus hechos de bootstrap están sólo en tests; no se aplican en
la aplicación, en GET ni como efecto de simular en producción. Los tests nuevos
invocan el scheduler directamente, sin ese bootstrap, para demostrar exclusión sin
release. Las regresiones de 7.3 que prueban scheduler agregan su precondición explícita.

## API y simulación separada

| Método | Ruta | Uso |
|---|---|---|
| GET | `/projects/{id}/production-readiness` | Evaluación derivada, checklist e historia |
| GET | `/projects/production-readiness` | Evaluación en lote |
| POST | `/projects/{id}/release` | Decisión explícita |
| POST | `/projects/{id}/unrelease` | Retiro no destructivo |
| POST | `/projects/{id}/simulations` | Simulación explícita de proyecto liberado |

No se agrega POST evaluate: GET ya evalúa naturalmente. Los routers sólo construyen
la llamada a application/UoW. Los resultados de proyectos incluyen readiness para
que listado y detalle no hagan una petición por cada tarjeta.

Se detectó que no existía un endpoint para generar una simulación de proyecto nuevo.
El nuevo endpoint reutiliza GenerateSchedule y el UoW/greedy existentes dentro de la
misma transacción auditada e idempotente. No crea un motor, job ni promoción paralelos.
Pide horizonte con timezone; la UI identifica sus límites diarios como UTC.
Devuelve escenario, solución y cantidades de fases planificadas/bloqueadas.

Generar esa simulación tampoco cambia CURRENT. La aceptación sigue en el flujo
existente de revisión/promoción: ACCEPT_REPLAN admite escenarios replan listos,
no convierte automáticamente una simulación inicial en un plan publicado. No se
amplía silenciosamente esa política ni se inventa publicación inicial en 7.4.
Las regresiones existentes de aceptación atómica se conservan.

## Frontend

Tarjeta PREPARACIÓN PARA PRODUCCIÓN en `/projects/:projectId`: estado, checklist,
REV X, hora de evaluación, actualización explícita, release, confirmación y retiro.
Tras release ofrece GENERAR SIMULACIÓN por separado y muestra su resultado; enlaza
con planificación sin aceptar un escenario automáticamente. No añade navegación
principal, autosave ni asignaciones manuales.

Listado: indicador compacto de preparación y filtro. Prioridad y atraso mantienen
su significado; no autorizan la entrada al scheduler.
Hay loading, error, retry, conservación de pantalla y conflicto visible. Ante una
respuesta incierta se reintenta la misma intención con la misma key, bloqueando
otras acciones hasta resolverla. La intención no sobrevive una recarga del navegador.
No se muestran UUID al usuario. La tarjeta usa todo el ancho de la grilla y controles
adaptables para 1440×900, 1366×768, 1024×768 y 390×844.

## Validación y rendimiento

| Validación final | Resultado |
|---|---|
| Backend PostgreSQL completo | **467 passed**, 0 failed, 160,70 s |
| Baseline backend + nuevos | 425 + 42 |
| Vitest completo | **134 passed**, 0 failed (118 + 16) |
| Playwright completo Edge | **155 passed**, 13 skips preexistentes, 0 failed |
| Playwright release, incluido arriba | **20/20**, cinco flujos en cuatro viewports |
| Total sin duplicar subconjuntos | **756 pruebas** (678 + 78) |
| TypeScript / Vite | Aprobados |
| OpenAPI y tipos | Generados desde FastAPI real; comparación completa verde |
| M0–M10 desde cero | 8 schemas / 87 tablas; cero migraciones nuevas |
| git diff --check | Aprobado |
| Secretos | 195 archivos escaneados, cero secretos nuevos |

La nueva suite detectó un desborde tablet de dos píxeles en los formularios
preexistentes de medición/replanteo. Se corrigió su mínimo de grilla para respetar
el ancho disponible; no se ocultó el overflow ni se omitió el caso. Después de la
corrección pasaron los 155 casos y se inspeccionó la captura móvil de la tarjeta.
También se ajustó la serialización HTTP del resultado completo del scheduler y
se regeneró OpenAPI; la comparación de contrato quedó verde.

Baseline: 425 backend, 118 Vitest, 135 Playwright y 13 skips responsive preexistentes.
No se elimina ninguna prueba para obtener el nuevo comportamiento.

Las expectativas de igualdad de Project omiten sólo la hora derivada de evaluación,
que cambia legítimamente entre lecturas. El presupuesto del benchmark antiguo se
ajusta a incluir el checklist en lote; una prueba nueva compara cantidad de consultas
para 2 y 100 proyectos y verifica que es constante.

Cobertura nueva: estados, milestones aplicables/N/A, freeze independiente,
release/retiro, idempotencia/retry/conflicto, concurrencia, cross tenant/plant,
rollback, inputs, simulación HTTP, cadena real PostgreSQL con medición y replanteo,
materiales/planos propios, ejecución iniciada, CURRENT intacto, REV 2 y stale,
prioridad/compromiso conservados y rendimiento en lote.

El navegador Playwright usa HTTP simulado determinista. Los hechos y la cadena
HTTP/FastAPI→PostgreSQL→scheduler se prueban separadamente sobre PostgreSQL real;
no se presenta el mock como una prueba browser→DB integral.

Mediciones representativas: readiness de un proyecto, **15,25 ms**, **15 consultas**,
**1.405 bytes**. Listado de 100 proyectos con indicador: **126,71 ms**, **20 consultas**,
**233.205 bytes**. Incluyen TestClient, no son SLA. No hay consultas por proyecto.

## Límites y seguridad

- RequestContext DEV existente. Autenticación: DEV ONLY / BLOCKER FOR PRODUCTION.
  Sin login, usuarios, passwords, Supabase Auth, JWT ni RBAC productivo.
- Fecha prevista de medición, ubicación de obra y plantillas reutilizables siguen
  diferidas. Instalación completa se reserva para 7.5.
- Sin alta de compras/stock/proveedores/órdenes, portal cliente, dashboards, PWA,
  realtime ni optimización matemática adicional.
- No hay UI nueva para configurar gates ni mantener recepciones/documentos;
  se reutilizan requisitos/factos y comandos productivos existentes.
- Se conserva el límite 7.3 de no rediseñar trabajo con ejecución registrada.
- No se autoriza una definición nueva si sólo existe un borrador.
- Persisten warnings Starlette/httpx, alias anyio y NO_COLOR/FORCE_COLOR.
- Vite advierte bundle grande: JavaScript 1.787,21 kB, 359,01 kB gzip.
- Hubo un proxy ECONNREFUSED al desmontar rutas simuladas en una corrida intermedia;
  no se presenta como una falla del backend ni se agregó un skip.

App de Compras y BACKUP Produccion Besten recuperado no fueron accedidos,
inspeccionados, ejecutados ni modificados. Sin migraciones nuevas ni commit automático.
Al cierre se verificaron Python 3.11.9 y PostgreSQL 18.6 operativo, cero bases y
roles descartables y ausencia de TEST_DATABASE_URL/PGPASSWORD en el proceso principal.
No se leyó pgpass.conf ni se modificó pg_hba.conf. Las credenciales no se imprimieron
ni persistieron; las variables del runner se limitaron al hijo.

El escaneo por patrones de 195 archivos no encontró secretos nuevos. Los dos
placeholders preexistentes de .env.example quedaron intactos y no se imprimieron.
No se incluyen .env, pgpass, node_modules, dist, test-results, playwright-report,
logs, caches, bases, certificados ni claves. git diff --check pasó; el hard break
Markdown previo de docs/21 línea 3 se conservó, sin introducir whitespace nuevo.
Estado Git final: 15 modificados y 11 nuevos; índice vacío, HEAD sin cambios,
sin commit ni push. Se cerró la sesión de preview propia de la validación.

Conclusión formal: **PRODUCTION_RELEASE_VALIDATED**.
