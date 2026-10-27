# Piloto 1 — etapas productivas y operaciones concretas

Fecha: 2026-10-27. Repositorio exclusivo: Produccion Besten, `master`, base
`6e87f1fa8121b625211dc3613b10ad965dd6a8f1`. Sin commit ni push.

## Auditoría y modelo

`production.operation_definitions` ya clasifica operaciones mediante una FK
tenant-scoped. No contenía un orden de presentación. Las operaciones concretas
ya tienen nombre propio, fases y precedencias; no hacía falta otra entidad de
etapas. El editor anterior repetía la selección de tipo dentro de cada tarjeta,
usaba nombres del catálogo como nombre inicial y reconstruía una cadena de
dependencias al agregar, reordenar o eliminar operaciones.

Se reutiliza ese catálogo como etapa. La jerarquía es proyecto → lote/producto →
etapa → operación concreta → fase → requerimientos. La etapa clasifica; no fija
duración, skill, personas, centro, recurso ni capacidad. Los campos técnicos
anteriores del catálogo se conservan por compatibilidad y no se propagan como
requerimientos nuevos. El algoritmo del scheduler no cambió.

## Catálogo y esquema

M12 agrega solamente `operation_definitions.display_order`, entero positivo,
NOT NULL, default 1000 para catálogos anteriores sin orden definido. Se conserva
el aislamiento por organización. M0–M11 permanecen sin modificaciones. Continúan
existiendo 8 schemas y 87 tablas; el verificador comprueba 155 restricciones CHECK.

`db/operations/besten_standard_stages.sql` se ejecuta únicamente sobre la
organización Besten existente. Es transaccional e idempotente: conserva IDs,
códigos utilizados, estados y referencias, actualiza etiquetas/orden y agrega
sólo tres registros. No contiene credenciales ni crea organizaciones ficticias.

| Orden | Código | Nombre |
| --- | --- | --- |
| 1 | PREPARACION_PROYECTO | Preparación del Proyecto |
| 2 | CORTE_ESCUADRADORA | Corte |
| 3 | PEGADO | Pegado de Cantos |
| 4 | PERFORADORA_MULTIPLE | Procesado con Múltiple |
| 5 | PROCESADO_SIN_MULTIPLE | Procesado sin Múltiple |
| 6 | ARMADO | Armado |
| 7 | CONTROL_CALIDAD | Control de Calidad |
| 8 | EMBALAJE | Embalaje |
| 9 | INSTALACION | Instalación |

La migración y el script de catálogo se aplicaron en una sola transacción en
`produccion_besten`, después de validar en base descartable. El downgrade de
esquema está en `db/rollback/012_standard_stage_order.sql`: elimina la extensión
de orden sin borrar filas, IDs ni relaciones. Como todo downgrade que retira una
columna, deja de conservar sus valores de orden; no revierte etiquetas del
catálogo ni elimina las etapas nuevas. Debe coordinarse con una versión anterior
de la aplicación. La prueba down/up comprueba preservación de IDs/códigos/nombres.

## Autoría, numeración y precedencias

El editor muestra encabezados derivados del catálogo, sin inputs para el nombre
de etapa. Cada etapa ofrece AGREGAR OPERACIÓN, que fija su única FK de
clasificación y deja el nombre concreto vacío para que el usuario lo escriba.
Ese nombre es obligatorio y libre. No existe el selector duplicado de tipo.
CAMBIAR ETAPA es explícito y conserva identidad, fases y precedencias.

`2.1 Corte de fondos` es una presentación de `display_order` y el índice dentro
de esa etapa; sólo `Corte de fondos` se guarda en `name`. Armado sigue siendo 6
aunque falten etapas anteriores. Las etapas sin operaciones no bloquean el lote.

El orden de autoría se conserva en el JSON existente
`required_operations.settings.editor_position`. Subir/bajar intercambia sólo
operaciones de la misma etapa; los IDs permanecen. Eliminar quita referencias a
la operación eliminada y renumera la presentación de sus hermanas, sin crear
una dependencia de reemplazo.

Las precedencias se eligen explícitamente entre operaciones concretas del lote.
Una lista vacía permite paralelismo. El backend valida pertenencia, autorreferencia
y ciclos, pero ya no exige que el orden visual sea topológico. Conservar una
precedencia también conserva su fila, tipo, lag y fuente; la numeración no los
reescribe. Las rutas manuales reproducen los vínculos explícitos.

Las fases conservan duración, división/interrupción, equipo, skills, centro,
recurso, demanda y sus IDs. Los nombres de operación continúan identificando
trabajos concretos en Gantt, tablero, ejecución, remaining estimate e instalación.
La prueba de integración agenda operaciones de Preparación, Control y Embalaje
con sus fases/requerimientos existentes y permite revisar el escenario inicial
sin crear CURRENT. Esto se realiza sólo en la base descartable.

## Contratos y configuración

- `/product-definition/options` devuelve las etapas ordenadas, con código,
  nombre, `display_order` y estado. Las inactivas siguen identificando operaciones
  existentes, pero no permiten agregar trabajo nuevo ni congelar trabajo inválido.
- La respuesta de definición agrega `stage_code`, `stage_name`, `stage_order` y
  `operation_order`. La FK `operation_definition_id` es la fuente de verdad;
  metadatos de presentación que un cliente reenvíe se ignoran y recalculan. Estos
  campos aditivos son nullable para reproducir respuestas de audit anteriores a
  M12 sin errores ni reescribirlas; las lecturas nuevas los calculan del catálogo.
- Los comandos existentes mantienen sus convenciones de Idempotency-Key,
  control de versión, aislamiento, auditoría y rollback.
- Configuración incorpora Etapas productivas, ordenadas, con código/nombre/orden/
  estado. Usa el servicio de maestros existente: POST/PATCH `/master-data/stages`
  y POST `/master-data/stages/{id}/status`. El código es estable al editar. Se
  desactiva en vez de eliminar destructivamente.
- OpenAPI y TypeScript fueron regenerados; el OpenAPI del backend local coincide
  con el archivo exportado.

## Compatibilidad histórica

Los snapshots congelados anteriores guardaban el código del catálogo, pero no
su etiqueta ni orden. No se los rellena ni reinterpreta retrospectivamente con
labels actuales: la vista histórica muestra ese código inmutable y los nombres
concretos/fases capturados. El cambio de etiquetas no cambia el contenido histórico.

Al congelar explícitamente una definición nueva, sólo el proyecto que se congela
captura `stage_name`, `stage_order` y el índice de operación en su nuevo snapshot.
Los proyectos restantes conservan su snapshot anterior. Las revisiones nuevas
muestran esa clasificación capturada al consultar historia, incluso después de
editar el catálogo. REV 1 y REV 2 reales no fueron modificadas ni recalculadas.

## Validación

Se ejecutaron backend completo, Vitest completo, Playwright completo y regresiones
del editor, TypeScript, Vite build, exportación de OpenAPI y diff-check. Los nuevos
casos cubren encabezado independiente del nombre, dos operaciones/renumeración,
IDs estables, Armado 6, etapas vacías, nombre obligatorio, fases intactas, cambio
explícito de etapa, paralelismo y precedencias, congelados, administración con
retry/concurrencia/tenant, catálogo idempotente, down/up M12 y primera simulación.

Backend completo: **553 aprobadas**. Vitest completo: **175 aprobadas**. Después
se verificó además compatibilidad de replay histórico anterior a M12 dentro de
las regresiones de etapas/editor/primer escenario: **59/59 aprobadas**, sin duplicar esos subconjuntos
en el total. Total único backend + Vitest + Playwright: **954 aprobadas**.

Playwright completo: 226 aprobadas y 14 omisiones preexistentes, con Microsoft
Edge configurado por `PLAYWRIGHT_CHANNEL=msedge`. El intento inicial con el canal
por defecto no pudo iniciar por ausencia de Chromium; se interrumpió. La ejecución
con Edge terminó con exit 0; se cerró el preview de pruebas para completar su
teardown. Tras el ajuste de alineación CSS: editor 36/36 en cuatro resoluciones.
Se inspeccionaron capturas de escritorio y móvil. Subsiste el warning de bundle
grande de Vite y los dos warnings conocidos de dependencias backend.

## Estado real preservado

Besten / Vera Mujica / A685 Alacenas / Nico Del Castillo. Proyecto activo,
medición realizada y replanteo completado; liberación existente sobre REV 2,
CURRENT NULL. Se mantienen las dos revisiones congeladas y las siete simulaciones
que ya existían al iniciar esta tarea. No se generó ni aceptó una simulación real.

**Diferencia previa respecto al prompt:** ya existía un borrador abierto por
`PRODUCT_EDITOR_NEW_REVISION` a las 09:12:35 del 27/10/2026, con row_version 22.
Fue anterior a esta intervención y se conservó. REV 2 continúa congelada y
liberada; no se creó automáticamente otra revisión ni se guardó ese borrador.
Tampoco se corrigieron centros/recursos de A685. El catálogo es el único conjunto
de datos reales actualizado.

La huella SHA-256 agregada de las filas completas de las otras 86 tablas,
ordenadas por su JSON, coincide antes/después:
`283eb7ec7c64ff50c57bde99f247d97d8579e962e32f5453e660ff0a43259c96`.
Esto incluye proyectos/lotes/operaciones/fases, revisiones, planning state,
CURRENT, escenarios/soluciones, maestros de capacidad y audit. La comprobación
final fue read-only. La UI real se abrió bloqueando toda petición distinta de
GET: nueve etapas, cuatro operaciones y cuatro fases, cero mutaciones.

App de Compras y el backup no fueron accedidos ni modificados. No se añadieron
credenciales, variables persistentes de conexión ni archivos de entorno.
Autenticación productiva continúa diferida.

## Revisión Git

19 archivos modificados y 5 nuevos; nada staged. HEAD y branch sin cambios.

`git status --short`:

```text
 M db/verify/verify_schema.sql
 M frontend/openapi.json
 M frontend/src/api/client.ts
 M frontend/src/api/schema.d.ts
 M frontend/src/features/master-data/MasterDataPage.test.tsx
 M frontend/src/features/master-data/MasterDataPage.tsx
 M frontend/src/features/projects/ProductEditor.module.css
 M frontend/src/features/projects/ProductEditor.test.tsx
 M frontend/src/features/projects/ProductEditor.tsx
 M frontend/src/test/productEditorFixture.ts
 M frontend/tests/product-editor.spec.ts
 M scripts/test_postgres_disposable.py
 M src/production_besten/api/master_data_routes.py
 M src/production_besten/api/master_data_schemas.py
 M src/production_besten/api/product_editor_schemas.py
 M src/production_besten/domain/master_data.py
 M src/production_besten/persistence/master_data_uow.py
 M src/production_besten/persistence/product_editor_uow.py
 M tests/integration/test_product_editor.py
?? db/migrations/012_standard_stage_order.sql
?? db/operations/besten_standard_stages.sql
?? db/rollback/
?? docs/38-etapas-productivas-y-operaciones-concretas.md
?? tests/integration/test_standard_stages.py
```

`git diff --stat` (archivos tracked; los cinco nuevos se listan arriba):

```text
 db/verify/verify_schema.sql                        |   2 +-
 frontend/openapi.json                              | 689 +++++++++++++++++++--
 frontend/src/api/client.ts                         |   2 +-
 frontend/src/api/schema.d.ts                       | 264 +++++++-
 .../features/master-data/MasterDataPage.test.tsx   |  14 +
 .../src/features/master-data/MasterDataPage.tsx    |  12 +-
 .../src/features/projects/ProductEditor.module.css |   4 +
 .../src/features/projects/ProductEditor.test.tsx   |  40 +-
 frontend/src/features/projects/ProductEditor.tsx   |  23 +-
 frontend/src/test/productEditorFixture.ts          |   2 +-
 frontend/tests/product-editor.spec.ts              |  43 +-
 scripts/test_postgres_disposable.py                |   2 +-
 src/production_besten/api/master_data_routes.py    |  20 +
 src/production_besten/api/master_data_schemas.py   |  12 +
 .../api/product_editor_schemas.py                  |  37 +-
 src/production_besten/domain/master_data.py        |   2 +-
 .../persistence/master_data_uow.py                 |  18 +-
 .../persistence/product_editor_uow.py              |  36 +-
 tests/integration/test_product_editor.py           |   2 +-
 19 files changed, 1148 insertions(+), 76 deletions(-)
```

`git diff --check`: aprobado. Escaneo de 231 archivos: cero candidatos nuevos
a secretos; dos coincidencias de ejemplo preexistentes sin cambios. No se
incluyen artefactos de pruebas, logs, caches, binarios, entornos ni credenciales.

Conclusión: **PILOT_STANDARD_STAGES_IMPLEMENTED**.
