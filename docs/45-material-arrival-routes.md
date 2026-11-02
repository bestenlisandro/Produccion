# Rutas de llegada de material

Implementación piloto sobre `master`. Checkpoint previo: `5e8b7eb`,
`Gantt V2 and planning integrity validated`. Esta fase queda sin commit y sin push.

## Fuente funcional y cotejo

Fuente principal: [Plantilla reparada](Specs/Plantilla_Precedencias_Produccion_Besten_v5_REPARADA.xlsx),
hojas **Matriz por caso**, **Casos de llegada** e **Instrucciones**.
SHA-256: `8c433642b8fae90358cbc63bf17cdebcb394bbd32476d410a2def78c187532f7`.
Se leyó sin modificarla. Ninguna versión anterior se usa como fuente.
La prueba `test_templates_match_approved_repaired_workbook` extrae directamente
la matriz y coteja las operaciones activas, la aplicabilidad y cada predecesora
inmediata de los cinco casos, incluyendo todos los opcionales activos.

## Cinco rutas

| Código estable | Cómo llega | Melaminas | Fondos 3 / 5,5 mm |
| --- | --- | --- | --- |
| MATERIAL_ROUTE_1 | Todo cortado y pegado; fondos enteros | Procesados aplicables | Corte independiente |
| MATERIAL_ROUTE_2 | Todo cortado y pegado; fondos cortados | Procesados aplicables | Sin trabajo interno |
| MATERIAL_ROUTE_3 | Tableros enteros | Corte → Pegado → procesados por espesor | Corte independiente |
| MATERIAL_ROUTE_4 | Melaminas cortadas sin pegado; fondos enteros | Pegado → procesados | Corte independiente |
| MATERIAL_ROUTE_5 | Todo cortado y pegado excepto 15 mm y fondos enteros | 18/12 listas; 15: Corte → Pegado → procesados | Corte independiente |

La selección de materiales por lote permite omitir espesores y fondos ausentes.
Para fondos nunca se generan Pegado, Múltiple, Procesado sin Múltiple ni Ranurado.
Para melaminas se consideran 18, 15 y 12 mm. No se agregan dependencias ficticias
para material que llega cortado y pegado.

### Aplicabilidad exacta de los procesados

`Sí` significa sugerido automáticamente cuando el material está presente.
`Opcional` significa **Según proyecto**: se incluye sólo al marcarlo.
`No` no se ofrece como candidato; permanece la edición manual libre del DAG.

| Operación funcional | Caso 1 | Caso 2 | Caso 3 | Caso 4 | Caso 5 |
| --- | --- | --- | --- | --- | --- |
| MUL-18 | Sí | Sí | Sí | Sí | Sí |
| MUL-15 | Opcional | Opcional | Sí | Sí | Sí |
| MUL-12 | Opcional | No | Sí | Sí | Sí |
| SIN-18 | Sí | Sí | Sí | Sí | Sí |
| SIN-15 | No | No | Sí | Sí | Sí |
| SIN-12 | Opcional | No | Sí | Sí | Sí |
| RAN-18 | Opcional | Opcional | Opcional | Opcional | Opcional |
| RAN-15 | Opcional | Opcional | No | Opcional | Opcional |

En particular, Caso 2 no ofrece MUL-12 y Caso 3 no ofrece RAN-15. Estas
restricciones provienen de la matriz reparada. No existe Ranurado 12 en el catálogo.

## Modelo y migración mínima M14

Se reutilizan lotes, operaciones, fases, catálogos de etapas, precedencias,
rutas publicadas específicas del lote y snapshots existentes.
La llegada es intención de plantilla del lote, no una ruta rígida del scheduler.

M14 agrega únicamente `core.project_lots.material_arrival jsonb NULL`, con
CHECK de objeto. Contiene `route_code`, `materials` y `optional_process_codes`.
No agrega tablas ni catálogos persistidos: siguen siendo ocho schemas y 87 tablas.
Los códigos de ruta viven en el catálogo versionado en código de dominio.
El catálogo existente no tiene un campo de configuración del lote adecuado:
`route_version_id` identifica otra entidad, las operaciones pueden eliminarse,
y duplicar la selección en sus settings o depender de auditoría sería frágil.
La columna nullable evita esas alternativas y conserva los lotes anteriores sin
selección automática. Los snapshots nuevos incluyen el campo sólo si fue elegido;
los históricos y la canonicalización de lotes sin selección no reciben una clave NULL.
El replay de comandos antiguos normaliza la ausencia y NULL del campo aditivo.

M0–M13 no se modificaron. Se entrega rollback M14. El verificador físico ahora
espera 157 CHECKs en vez de 156 y el runner informa M0–M14. Una prueba aplica
rollback/reaplicación en una transacción descartable y comprueba la preservación
de todos los campos anteriores de un lote existente.

**Estado al cerrar la implementación inicial:** M14 se había aplicado sólo en
bases descartables. **Actualización 2026-11-02:** M14 ya fue aplicada y validada
en la base real mediante el runner oficial. Ver [validación real](46-m14-real-db-validation.md).
No hay migración automática al arrancar.

Los IDs COR/PEG/MUL/SIN/RAN/ARM de la planilla son referencias funcionales.
Las operaciones concretas reciben un prefijo aleatorio para evitar colisiones
entre lotes; las filas conservan UUIDs de base de datos y etapas existentes:

| Referencia | Etapa existente |
| --- | --- |
| COR / RAN | CORTE_ESCUADRADORA |
| PEG | PEGADO |
| MUL | PERFORADORA_MULTIPLE |
| SIN | PROCESADO_SIN_MULTIPLE |
| ARM | ARMADO |

Ranurado es una operación concreta en Corte porque la matriz exige escuadradora.
No se agrega una décima etapa ni se configura automáticamente una máquina.
La generación falla con un mensaje si falta una etapa activa requerida.

## Precedencias, terminales y paralelismo

Por cada melamina entera se crea COR → PEG. Cada procesado activo de ese espesor
depende sólo de PEG. Para Caso 4, PEG es raíz; para material ya listo el procesado
es raíz. Múltiple, Sin Múltiple y Ranurado son ramas hermanas posteriores al mismo
Pegado cuando corresponde, nunca una cadena implícita entre procesados.

`terminals` valida el DAG, reúne los códigos presentes como predecesores y devuelve
los nodos que no tienen sucesor activo. Se calcula sobre la estructura seleccionada
antes de agregar Armado. Armado recibe exactamente esos terminales; se valida
nuevamente el DAG completo. Una cadena sólo aporta su último nodo; dos o tres
ramas aportan sus respectivos últimos nodos. Los opcionales desactivados no están
en el grafo ni bloquean Armado. No hay lista global fija ni dependencias transitivas
redundantes. Un lote de fondos ya cortados puede generar únicamente Armado.

El detector de ciclos existente se extrajo sin cambiar comportamiento a
`domain/precedence.py`; los consumidores anteriores conservan `_has_cycle` como
alias. No se creó un segundo motor de precedencias.

No existe un campo «puede ir en paralelo». La ausencia de dependencia permite al
scheduler decidir la superposición con personas, skills, centros, recursos y
calendarios. No se modificaron scheduler, CURRENT, simulaciones ni Gantt.

## API y experiencia de edición

- GET `/product-definition/material-arrival-routes`: cinco nombres humanos,
  resúmenes y candidatos por material. Requiere contexto válido de organización/planta.
- POST `/product-definition/material-arrival-preview`: valida la selección y
  resuelve las etapas activas del tenant. Devuelve operaciones editables sin
  persistir, auditar, simular, congelar ni cambiar revisiones.
- El PUT de definición existente guarda la selección junto con el DAG del lote,
  en la misma transacción y con los locks/versiones/idempotencia ya existentes.

En el lote aparece **Cómo llega el material**. **CONFIGURAR LLEGADA DEL MATERIAL**
abre el selector de cinco rutas, su nombre completo y resumen, los materiales
presentes y checklists de procesados Según proyecto. Los «Sí» se explican como
sugeridos por la ruta. Se puede cerrar la configuración sin alterar operaciones.

Cambiar el selector, materiales u opcionales prepara una propuesta local: no
reemplaza el DAG ni guarda una selección que todavía no fue aplicada.
**REGENERAR DESDE RUTA** aplica la propuesta. Si ya hay operaciones, requiere
confirmación explícita que enumera qué se reemplaza, incluido trabajo manual.
Cancelar o un error conserva el trabajo. Durante la petición se deshabilitan
la edición y las acciones del proyecto para evitar sobrescribir cambios concurrentes.

Las operaciones se identifican como sugeridas; después siguen siendo editables:
nombres, altas/bajas, precedencias explícitas, fases, personas, skills, recursos y
duraciones. La plantilla **no inventa duraciones ni recursos**: genera operaciones
sin fases y explica que hay que completarlas antes de congelar. El borrador puede
guardarse incompleto; la validación existente impide congelarlo hasta completarlo.
Las modificaciones manuales posteriores no regeneran automáticamente el grafo;
el usuario sigue siendo responsable de sus precedencias explícitas, incluido Armado.
Volver a regenerar recalcula terminales sobre la selección y reemplaza la estructura
completa del lote, con confirmación; no es una mezcla parcial de ramas.

Una revisión frozen oculta el configurador. El servidor sigue rechazando el PUT
de una revisión congelada. Sólo **CREAR NUEVA REVISIÓN** abre un borrador y preserva
el snapshot histórico. No se crea ninguna revisión automáticamente.

## Pruebas y validación

- Dominio: fixtures exactos para cinco rutas; cotejo independiente contra el XLSX;
  terminales de 1/2/3 ramas; opcionales activos/inactivos; fondos ausentes/presentes;
  Múltiple + Sin Múltiple; inmediatas sin redundancias; ciclos y referencias inválidas;
  catálogos incompletos, códigos concretos diferentes entre generaciones.
- Integración PostgreSQL: preview sin efectos; guardado/recarga/congelado por cada
  caso; inmutabilidad; nueva revisión con histórico intacto; varias selecciones por
  lote; autoridad del DAG manual; validación; M14 nullable y rollback/reaplicación.
- Vitest: cinco opciones, descripción, aplicabilidad reparada, sugerencias, selección
  de materiales/opcionales, cancelación/confirmación, cambio de ruta sin destrucción,
  guardado de selección aplicada, edición de nombres, frozen y error de generación.
- Playwright real: `test_material_arrival_browser.py` inicia API y Vite efímeros
  contra el PostgreSQL descartable del runner. Ocho recorridos: Casos 3 y 5 en
  1440/1366/1024/390 px. Activa/desactiva opcionales, inspecciona predecesoras visibles,
  agrega fases/duraciones, guarda, congela y verifica rechazo HTTP 409 de edición.
  Comprueba ausencia de overflow y conserva screenshots. Verifica CURRENT y cantidades
  de escenarios/ejecuciones del fixture sin generar nuevos.

Resultados finales:

- Backend completo: **629 passed**, 0 fallas, PostgreSQL descartable eliminado.
  Incluye los 22 tests de dominio nuevos, ocho de integración nuevos y el test
  Playwright real de ocho recorridos. Se conservan dos deprecaciones conocidas.
- Vitest completo: **226 passed / 20 archivos**, 0 fallas. Después del ajuste
  visual final se repitieron sólo los seis tests del configurador: todos pasan.
- Playwright de regresión relevante: **72 passed**, 0 fallas ni skips; editor
  completo, Gantt V2, históricos y scenario expiry, cuatro viewports.
- TypeScript y Vite build: aprobados. Persiste el warning conocido de bundle grande.
- OpenAPI exportado y tipos generados/sincronizados.
- `git diff --check`: aprobado (sólo avisos de conversión LF/CRLF conocidos).
- Verificación estática de migraciones: aprobada; 15 archivos M0–M14, ocho schemas, 87 tablas. Se actualizó su contador anterior de 12 archivos.
- Secret scan: cero candidatos en archivos seguidos y nuevos de texto.
- La ejecución Playwright inicial quedó detenida al cerrar su webServer; se
  interrumpió y se obtuvo salida 0 iniciando Vite preview por separado. Las
  ejecuciones verificables de checkpoint y cierre pasaron, sin cambiar tests.

El backend completo incluye el test de navegador real y el runner elimina
siempre la base/rol descartables. Sus capturas están en
`test-results/material-arrival/`, fuera del directorio que limpia Playwright CLI.

## Datos reales y alcance

Baseline read-only de las 87 tablas en `test-results/material-routes-baseline.json`,
con cantidad de filas y SHA-256 de su contenido canónico. Estado inicial: A685
activa, REV 1–4, ocho escenarios y cero ejecuciones. La comparación final debe
demostrar igualdad completa, además de REV 4 released y CURRENT V1.
La comprobación final efectivamente confirmó **87/87 tablas idénticas** en filas
+ SHA-256. A685 activa, REV 1–4, último evento PROJECT_PRODUCTION_RELEASED
con definition_revision_no=4, CURRENT V1, ocho escenarios y cero ejecuciones.
Resultado read-only en `test-results/material-routes-data-verification.json`.
No hay REV 5, escenario 9 ni CURRENT V2.
No se accede a App de Compras ni a BACKUP Produccion Besten recuperado.
No se elige ruta para A685, no se crea REV 5, no se simula ni se acepta un plan.

## Archivos de esta fase

Modificados:

- `db/verify/verify_schema.sql`
- `db/verify/static_verify.ps1`
- `frontend/openapi.json`
- `frontend/src/api/schema.d.ts`
- `frontend/src/features/projects/ProductEditor.module.css`
- `frontend/src/features/projects/ProductEditor.tsx`
- `scripts/test_postgres_disposable.py`
- `src/production_besten/api/product_editor_routes.py`
- `src/production_besten/api/product_editor_schemas.py`
- `src/production_besten/persistence/product_definition_uow.py`
- `src/production_besten/persistence/product_editor_uow.py`

Nuevos / sin seguimiento:

- `db/migrations/014_material_arrival.sql`
- `db/rollback/014_material_arrival.sql`
- `docs/45-material-arrival-routes.md`
- `docs/Specs/Plantilla_Precedencias_Produccion_Besten_v5_REPARADA.xlsx` (aportada por el usuario, intacta)
- `frontend/scripts/material-arrival-ui-live.mjs`
- `frontend/src/features/projects/MaterialArrivalEditor.tsx`
- `frontend/src/features/projects/MaterialArrivalEditor.test.tsx`
- `frontend/src/test/materialArrivalFixture.json`
- `src/production_besten/domain/material_arrival.py`
- `src/production_besten/domain/precedence.py`
- `tests/integration/test_material_arrival.py`
- `tests/integration/test_material_arrival_browser.py`
- `tests/unit/test_material_arrival.py`

Estado Git al cerrar la implementación inicial, antes de la aplicación real y del checkpoint: 11 archivos modificados y 13 nuevos, sin staging.
La carpeta `docs/Specs/` aparece agrupada como untracked en `git status --short`.
No hay segundo commit ni push. Scheduler y Gantt no tienen diff contra el checkpoint.
