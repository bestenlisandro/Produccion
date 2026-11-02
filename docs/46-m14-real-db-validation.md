# Aplicación real de M14 y validación del piloto

Fecha: 2026-11-02, America/Buenos_Aires. Proyecto exclusivamente Producción Besten,
branch `master`. Checkpoint preservado: `5e8b7eb`. Sin commit ni push de esta fase.

## Precheck y alcance autorizado

PostgreSQL 18.6 activo, base `produccion_besten`, propietario y rol migrador
`postgres`. Runtime con `produccion_besten_app`, `APP_ENV=development` y código
actual. Se verificó la configuración sin imprimir credenciales.

Antes: ocho schemas de aplicación, 87 tablas, 1086 columnas, cero constraints
sin validar. Se corroboraron los objetos M0–M13 y en particular los campos
`operation_definitions.display_order` y `required_operation_phases.required_people`.
La columna M14 no existía. A685 activa, revisiones 1–4, última liberación
PROJECT_PRODUCTION_RELEASED para definición REV 4, CURRENT V1, ocho escenarios
y cero ejecuciones.

Baseline consistente mediante transacción REPEATABLE READ y read-only:
`test-results/m14-real/before-tables.json` y `before-summary.json`. Incluye
conteo y SHA-256 por cada una de las 87 tablas, hashes de snapshots, row_version
de A685 e identificadores de contexto. No se accedió a otras bases de negocio.

## Auditoría y aplicación de la migración

M14 agrega `core.project_lots.material_arrival jsonb NULL`, sin DEFAULT ni UPDATE
de datos históricos, y CHECK `ck_project_lots_material_arrival` que acepta NULL
u objeto JSON. No altera operaciones, precedencias, rutas asignadas ni snapshots.
Su rollback elimina exactamente ese CHECK y esa columna. No se ejecutó rollback
en la base real.

La migración usa BEGIN/COMMIT y falla ante columna ya existente; no enmascara
duplicados con IF NOT EXISTS. El proyecto **no tiene tabla de historial de
migraciones**: no se inventó una ni se agregó una tabla para registrar M14.
El estado M0–M14 se verifica por los objetos del esquema y la evidencia del runner;
no significa que existan quince registros en una tabla de migraciones.

El runner oficial `db/verify/apply_with_psql.ps1` conservaba un contador fijo de
12 y sólo servía para instalación desde cero. Se corrigió para validar una
secuencia contigua desde 000, derivar su cantidad y permitir `-FromMigration 14`.
`-SchemaOnly` mantiene `verify_schema.sql` y excluye los fixtures temporales de
`temporal_scenarios.sql`. No cambió la lógica productiva.
`static_verify.ps1` también deriva la cantidad y rechaza huecos o nombres inválidos.
Se auditaron scripts/tests/utilidades; no quedaron otros contadores antiguos
afectados. M0–M13 no se modificaron.

Comando utilizado, sin credenciales literales:

```powershell
.\db\verify\apply_with_psql.ps1 `
  -DatabaseUrl 'host=127.0.0.1 port=5432 dbname=produccion_besten user=postgres' `
  -PsqlPath 'C:\Program Files\PostgreSQL\18\bin\psql.exe' `
  -FromMigration 14 -SchemaOnly
```

El log `test-results/m14-real/apply-m14.log` acredita que sólo se aplicó
014_material_arrival.sql, con COMMIT y verificación estructural aprobada.
El verificador utiliza una tabla TEMP de nombres esperados y ROLLBACK; no inserta
datos productivos. No se ejecutaron fixtures ni simulaciones en la base real.

## Resultado estructural y contenido

| Medida | Antes | Después |
| --- | --- | --- |
| Schemas de aplicación | 8 | 8 |
| Tablas de aplicación | 87 | 87 |
| Columnas de aplicación | 1086 | 1087 |
| CHECKs | 156 | 157 |
| Constraints sin validar | 0 | 0 |
| Catálogo de migraciones | 000–013 aplicadas por esquema | 000–014, 15 archivos totales |

Nueva columna JSONB nullable, sin DEFAULT; CHECK presente y validado.
Todos los lotes conservan `material_arrival IS NULL`, incluido A685.
Los conteos y SHA-256 de **87/87 tablas son idénticos**, excluyendo únicamente
la nueva clave NULL de la representación JSON de `core.project_lots`.
Evidencia: `after-tables-normalized.json`, `after-summary.json` y comprobación
final posterior a los GET y a la inspección de navegador.

A685, REV 1–4, REV 4 released, CURRENT V1, ocho escenarios y cero ejecuciones
permanecen intactos. Sin REV 5, selección de ruta, CURRENT V2, simulaciones,
aceptaciones, altas productivas ni ejecuciones nuevas.

## Servicios y smoke real

No había listeners en 8000/5173 en el precheck. Se iniciaron exclusivamente los
servicios de este proyecto, en segundo plano, sin tocar procesos de otras apps.
Backend con APP_ENV development y PYTHONPATH al `src` de este workspace.
Frontend Vite con puerto estricto y contexto DEV del piloto.

HTTP 200 para:

- `/health`
- `/projects`
- `/master-data/snapshot`
- `/planning/current/gantt` con `from=2026-09-01T00:00:00Z` y
  `to=2026-09-30T00:00:00Z`
- `/product-definition/options`
- `/product-definition/material-arrival-routes`
- `/projects/{A685-id}/product-definition`

El Gantt exige rango explícito, con zona horaria y hasta 31 días. Los intentos
sin esos parámetros devolvieron los errores de validación previstos; la petición
válida devolvió 200. No se modificaron esas reglas.
La definición real de A685 devuelve frozen, revisiones 1–4 y selección NULL.
Evidencia: `test-results/m14-real/http-smoke.json`.

Frontend disponible en **http://127.0.0.1:5173**, backend en 8000. Logs y PIDs de
arranque en `test-results/m14-real/`. Los servicios quedan disponibles.

## Inspección visual sin guardar datos reales

Se abrió A685 realmente y se verificó CONGELADA / Sólo lectura, sin configurador
editable. Para inspeccionar el selector sin crear REV 5 ni un proyecto real,
se representó un borrador vacío **sólo en memoria del navegador**, sustituyendo
únicamente su GET de definición para un UUID de prueba. Opciones y catálogo
vinieron del backend real; no se sustituyeron las cinco rutas.

Se abrió «Cómo llega el material», recorrieron las cinco opciones y verificaron
los nombres humanos y sus resúmenes, incluyendo 15 mm Corte → Pegado en Caso 5.
El nombre abreviado del Caso 5 se complementa con su resumen; no se muestran
códigos técnicos como texto principal. No se cambió el catálogo ni lógica funcional.
Se revisaron escritorio 1366 y móvil 390, sin overflow horizontal.
Todas las escrituras HTTP se bloquearon durante la inspección; **cero solicitudes
de escritura intentadas**, sin regenerar, guardar ni congelar.

Capturas y evidencia en `test-results/m14-real/`: `a685-frozen.png`,
`routes-1366.png`, `routes-390.png`, `visual-readonly.json`.

## Fuente y pruebas

La fuente sigue siendo `docs/Specs/Plantilla_Precedencias_Produccion_Besten_v5_REPARADA.xlsx`.
No se modificó; SHA-256 conservado:
`8c433642b8fae90358cbc63bf17cdebcb394bbd32476d410a2def78c187532f7`.

Sin cambios de lógica funcional ni TS, no se repitieron suites completas.
En PostgreSQL descartable: **31 passed**, incluyendo 22 tests de dominio de
material arrival, ocho de integración y un test nuevo del runner oficial M14.
Este último aplica rollback/reaplicación sólo en la DB descartable, verifica
preservación de campos y comprueba que la segunda aplicación se rechaza sin
modificar datos. Base y rol descartables eliminados al finalizar.
`static_verify.ps1` aprobado: 15 migraciones, ocho schemas, 87 tablas, cero FKs
inseguras entre tenants y cero cascadas destructivas.
Smoke backend y navegador aprobados; git diff --check y secret scan aprobados.

## Git y límites

Cambios propios de esta tarea: `db/verify/apply_with_psql.ps1`, ajuste del contador
derivado en `db/verify/static_verify.ps1`, nuevo
`tests/integration/test_m14_migration_runner.py`, este informe y actualización
de estado en docs/45. Se preservaron todos los cambios de rutas anteriores.
El estado completo y diff --stat se guardan en `test-results/m14-real/`.
Sin staging, commit ni push. App de Compras y backup no fueron accedidos.


## Checkpoint local autorizado

Después de M14_REAL_DB_VALIDATED se auditó nuevamente la fase completa para el
checkpoint `Material arrival routes validated`, sin modificar lógica funcional.
Los estados Git descriptos anteriormente son los del cierre de cada fase previa.

Precheck final: 31 tests relevantes de material arrival y migration runner
aprobados, cero fallas. Base/rol descartables eliminados. Git diff --check y
secret scan aprobados. La verificación real fue exclusivamente READ-ONLY:
87/87 hashes históricos y conteos iguales al baseline, ocho schemas, M14 presente
con CHECK validado y todos los material_arrival históricos en NULL. A685 conserva
REV 1–4, REV 4 released, CURRENT V1, ocho escenarios y cero ejecuciones.
La planilla aprobada conserva el SHA-256 indicado arriba.

Se incluyen únicamente estos 27 archivos de la fase (12 modificados y 15 nuevos):

- `db/migrations/014_material_arrival.sql`
- `db/rollback/014_material_arrival.sql`
- `db/verify/apply_with_psql.ps1`
- `db/verify/static_verify.ps1`
- `db/verify/verify_schema.sql`
- `docs/45-material-arrival-routes.md`
- `docs/46-m14-real-db-validation.md`
- `docs/Specs/Plantilla_Precedencias_Produccion_Besten_v5_REPARADA.xlsx`
- `frontend/openapi.json`
- `frontend/scripts/material-arrival-ui-live.mjs`
- `frontend/src/api/schema.d.ts`
- `frontend/src/features/projects/MaterialArrivalEditor.test.tsx`
- `frontend/src/features/projects/MaterialArrivalEditor.tsx`
- `frontend/src/features/projects/ProductEditor.module.css`
- `frontend/src/features/projects/ProductEditor.tsx`
- `frontend/src/test/materialArrivalFixture.json`
- `scripts/test_postgres_disposable.py`
- `src/production_besten/api/product_editor_routes.py`
- `src/production_besten/api/product_editor_schemas.py`
- `src/production_besten/domain/material_arrival.py`
- `src/production_besten/domain/precedence.py`
- `src/production_besten/persistence/product_definition_uow.py`
- `src/production_besten/persistence/product_editor_uow.py`
- `tests/integration/test_m14_migration_runner.py`
- `tests/integration/test_material_arrival.py`
- `tests/integration/test_material_arrival_browser.py`
- `tests/unit/test_material_arrival.py`

No se incluye evidencia temporal de test-results ni ningún archivo de otras apps.
El hash definitivo del commit queda registrado en Git y en el informe de cierre.
Sin push. App de Compras y backup no fueron accedidos.
