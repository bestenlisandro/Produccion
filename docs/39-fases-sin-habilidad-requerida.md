# Piloto 1 — fases sin habilidad requerida

Fecha: 2026-10-27. Repositorio exclusivo: Produccion Besten. Branch `master`;
base `469a999583aa6d1065fccd1c1589148d244dab20`. Sin commit ni push.

## Auditoría y problema

Las fases se guardan en `production.required_operation_phases`. Los requisitos
humanos específicos constituyen una colección en
`production.operation_labor_requirements`: cada fila tiene skill_id NOT NULL,
FK tenant-scoped a una habilidad real, min_people/max_people y work_minutes.
Varias filas representan roles distintos, con equipos disjuntos según el motor
existente. No había una cantidad de personas independiente de esos roles.

Una colección vacía ya era válida en fases de producción, pero `_teams` devolvía
un equipo vacío: significaba trabajo sin consumo humano. Eliminar la habilidad
no podía expresar «una persona cualquiera». Instalación además exigía al menos
un requisito humano específico. No se podía resolver correctamente añadiendo
sólo un placeholder en el selector o dejando un UUID nulo.

## Semántica final

- `required_people > 0` y `labor_requirements: []`: cantidad de personas activas
  y disponibles, sin filtro por habilidad. Se consumen y reservan personas reales.
- Si hay requisitos de habilidad, se conserva el matching existente por rol,
  mínimos/máximos, equipo disjunto y vigencia de la skill. `required_people`
  es además un mínimo total; no se completa un equipo cualificado con personas
  sin las skills necesarias. Un mínimo incompatible con los máximos de los roles
  se rechaza en el editor.
- `required_people: 0` sin requisitos humanos mantiene el modo automático que
  ya existía. No se convierte en «cualquier persona». Los requisitos con skill
  existentes siguen demandando sus personas aunque el nuevo campo sea cero.
- La duración no se divide por el número de personas de una fase genérica. Una
  fase de 20 minutos y dos personas reserva ambas durante esos 20 minutos. No se
  inventa productividad ni se cambia la regla de escalado de trabajo cualificado.

Ejemplos: Acomodar materiales, 20 minutos, una persona y ninguna skill; Mover
placas, 15 minutos, dos personas y ninguna skill; Perforado, 60 minutos, una
persona con la skill real de Perforadora Múltiple. La excepción no depende de
etapa: está disponible también en Preparación, Control de Calidad y Embalaje.

## Representación y M13

M13 añade una única columna:
`production.required_operation_phases.required_people smallint NOT NULL DEFAULT 0`,
con CHECK no negativo. Los contratos validan también el límite de smallint.
No hay nuevas tablas ni skill ficticia. La colección vacía se representa con
cero filas en operation_labor_requirements, sin cambiar su FK NOT NULL.

La columna es necesaria porque los requisitos existentes ligaban inseparablemente
la cantidad humana con una skill y la fase no tenía un campo equivalente. Usar
una colección vacía por sí sola habría seguido consumiendo cero personas. No se
crearon una segunda colección de skills ni una columna nullable artificial.

M0–M12 no cambian. Se mantienen 8 schemas, 87 tablas y ahora 156 CHECKs. La ruta
manual guarda el contador como metadato en el JSON settings ya existente de su
plantilla de fase; la demanda efectiva está en la fase concreta. El snapshot de
definición captura required_people cuando es positivo. Omitir cero evita cambiar
el significado y el hash de snapshots históricos que no tenían ese campo.

`db/rollback/013_phase_required_people.sql` retira la columna sólo cuando todos
sus valores son cero. Rechaza explícitamente el downgrade si se perdería demanda
humana nueva; no borra ni transforma esa información. Se probó down/up con datos
anteriores, preservación de columnas anteriores y la protección ante valores
positivos. La coordinación con la versión de aplicación anterior sigue siendo
necesaria al hacer un downgrade; no se ejecutó rollback sobre la base real.

## API y persistencia

EditorPhase y CreatePhaseRequest incluyen required_people con default 0 para
compatibilidad. La operación de dominio valida el valor y la persistencia lo
guarda tanto al crear como al editar la fase. GET de definición devuelve el
contador y la colección real de requisitos: `[]` no es null, un UUID especial
ni una skill llamada Ninguna.

Guardar/reabrir, validar, congelar y abrir una nueva revisión conservan la
demanda y la ausencia de skill. Los datos de fase siguen perteneciendo a la
operación concreta; no se trasladan al catálogo de etapas.

La intención idempotente del editor ignora únicamente el nuevo campo de fase
cuando vale cero, para conservar claves calculadas antes de M13; no ignora
metadatos del usuario. Un valor positivo sí cambia la intención. La API de
creación de fase también incluye la cantidad en el replay y entiende cero
cuando el evento anterior a M13 no la contenía. Un retry no crea otra fase.

OpenAPI y los tipos TypeScript se regeneraron. El documento OpenAPI del backend
local coincide con el exportado. Las respuestas históricas de audit pueden
seguir omitiendo el campo: la deserialización usa su valor histórico cero.

## Frontend

Personas necesarias se presenta separada del selector de habilidad. Las fases
nuevas comienzan con una persona y ninguna skill. Se muestra **Sin habilidad
requerida**, junto con la demanda de personas disponibles. Agregar una habilidad
crea un requisito real; quitar la última conserva la cantidad de personas y
vuelve al estado sin habilidad, sin introducir placeholders persistidos.

Con una sola habilidad, el control de personas actualiza su mínimo/máximo como
antes. Con varias habilidades se mantienen cantidades por rol y se muestra la
demanda total efectiva. Las fases antiguas sin demanda humana siguen mostrando
su modo existente; no se les asigna automáticamente una persona.

La historia congelada muestra cantidad y ausencia de habilidad según su propio
snapshot. No usa una skill por defecto ni modifica el catálogo al editar.

## Scheduler, instalación y ejecución

PhaseData lleva la cantidad independiente. Sin labor específica, el scheduler
enumera combinaciones de empleados elegibles, del tamaño solicitado, sin repetir
IDs ni filtrar skills. Usa después el mismo cálculo de ventanas de calendario,
excepciones, indisponibilidad, asignaciones y solapamientos que los equipos
cualificados. La consulta de capacidad conserva sus filtros de planta/tenant y
personas activas. El test PostgreSQL usa Mariano, Emiliano y Gonzalo sin skills,
y excluye un cuarto empleado inactivo.

No disponer de suficientes personas produce REQUIRED_PEOPLE_UNAVAILABLE;
REQUIRED_SKILL_UNAVAILABLE se reserva para una habilidad realmente requerida.
El tablero distingue ambas situaciones. Se incrementa la versión del motor a
`v1-greedy-4` para identificar esta nueva semántica; los escenarios históricos
conservan su versión y snapshots originales.

Las asignaciones se persisten por employee_id, sin skill inventada. Los
replanificados conservan la cantidad a través de PhaseData. El cargador de
demanda congelada toma required_people del snapshot y usa cero cuando falta,
evitando que un contador modificado en un borrador se filtre a una revisión
anterior.

Instalación admite equipo genérico de 1–6 personas, conserva los límites
existentes y muestra el contador aunque no tenga skill. El registro de un
segmento real comprueba el mínimo humano independiente antes de las verificaciones
habituales de actividad, solapamientos y recursos. Las verificaciones de skills
reales permanecen activas cuando hay esos requisitos.

## Pruebas y validación

- Backend completo: **573 aprobadas**, con los dos warnings de dependencias ya
  conocidos. Veinte casos específicos de este ajuste también aprobaron en una
  base descartable, sin sumarlos de nuevo al total.
- Siete casos unitarios cubren equipos genéricos de una/dos personas, calendario,
  indisponibilidad, reserva sin solapamiento, skill real restrictiva, falta de
  personas y modo automático histórico; también la normalización idempotente.
- Trece casos PostgreSQL cubren autoría/freeze/nueva revisión en Preparación,
  Control y Embalaje, ausencia de filas de skill, matching con empleados activos,
  persistencia de asignaciones y aislamiento del snapshot frente a un borrador,
  validaciones, instalación y upgrade/downgrade M13.
- Vitest completo: **177 aprobadas**. Incluye fase nueva, guardar y volver a
  montar el editor, agregar/quitar la última skill, preservar cantidades antiguas
  y mensajes de disponibilidad sin skill.
- Editor Playwright: **40/40**, en cuatro resoluciones. El caso nuevo comprueba
  guardar, recargar, agregar una skill real, eliminarla y volver a recargar sin
  default ni skill ficticia. Un selector exacto del test se corrigió para usar
  el rol accesible del combo; no fue un fallo de guardado de la aplicación.
- TypeScript y Vite build aprobados. Subsiste el warning conocido de bundle
  grande. OpenAPI sincronizado. Se ejecutan diff-check y escaneo de secretos.

Todas las simulaciones de prueba y cambios de datos de fixtures usan la base
descartable y roles temporales propios; su limpieza se verificó. Ninguna prueba
genera ni acepta una simulación en produccion_besten.

## Base real

Se aplicó únicamente M13, transaccionalmente, con cero como default de todas las
fases anteriores. No hubo UPDATE de datos reales, nuevos registros, skills,
revisiones, planes ni simulaciones. No cambiaron las asignaciones de Mariano,
Emiliano o Gonzalo. Continúan seis skills reales y 14 vínculos persona–skill.

Nico Del Castillo / A685 Alacenas sigue activo y released; REV 1 y REV 2 se
conservan congeladas, CURRENT NULL y siete simulaciones históricas. También se
conserva el borrador que ya estaba abierto antes de esta tarea. No se creó REV 3.

La huella agregada de las filas originales de las 87 tablas, excluyendo sólo
la columna nueva required_people de las fases, es idéntica antes/después:
`79fe0f7ea2469e51e1189f65c27fd06d070b6b214e17486cbd9f2bc67b9599a7`.
Además se comprobó que el nuevo campo vale cero en todas las fases reales.
Esto preserva row_version, timestamps, operaciones, fases, revisiones, maestros,
planning state, audit, escenarios y soluciones.

App de Compras y el backup no fueron accedidos ni modificados. No se añadieron
credenciales ni archivos de entorno. Autenticación productiva sigue diferida.

## Cierre de validación y Git

Playwright completo final: **230 aprobadas**, 14 omisiones preexistentes, cero
fallas. Editor: 40/40 en las cuatro resoluciones. Se inspeccionaron las capturas
de la nueva sección de personas/habilidades. Total único, sin duplicar
subconjuntos: **573 + 177 + 230 = 980 pruebas aprobadas**.

Escaneo de 236 archivos: cero candidatos nuevos a secretos; dos coincidencias
de ejemplo preexistentes sin cambios. Diff-check y whitespace de archivos nuevos
aprobados. No hay artefactos temporales, credenciales, logs ni caches entre los
archivos propuestos. Branch y HEAD siguen en la base indicada; nada staged.

`git status --short`:

```text
 M db/verify/verify_schema.sql
 M frontend/openapi.json
 M frontend/src/api/schema.d.ts
 M frontend/src/features/daily-board/presentation.test.ts
 M frontend/src/features/daily-board/presentation.ts
 M frontend/src/features/projects/ProductEditor.test.tsx
 M frontend/src/features/projects/ProductEditor.tsx
 M frontend/tests/product-editor.spec.ts
 M scripts/test_postgres_disposable.py
 M src/production_besten/api/product_editor_schemas.py
 M src/production_besten/api/routes.py
 M src/production_besten/api/schemas.py
 M src/production_besten/domain/product_definition.py
 M src/production_besten/domain/scheduling/engine.py
 M src/production_besten/domain/scheduling/models.py
 M src/production_besten/persistence/execution_uow.py
 M src/production_besten/persistence/frozen_editor_demand.py
 M src/production_besten/persistence/installation_queries.py
 M src/production_besten/persistence/product_definition_uow.py
 M src/production_besten/persistence/product_editor_uow.py
 M src/production_besten/persistence/scheduling_uow.py
 M tests/integration/test_accept_replan.py
 M tests/integration/test_basic_scheduler.py
 M tests/unit/test_cumulative_scheduler.py
?? db/migrations/013_phase_required_people.sql
?? db/rollback/013_phase_required_people.sql
?? docs/39-fases-sin-habilidad-requerida.md
?? tests/integration/test_optional_skill.py
?? tests/unit/test_optional_skill.py
```

`git diff --stat` (tracked; los cinco archivos nuevos se listan arriba):

```text
 db/verify/verify_schema.sql                        |  2 +-
 frontend/openapi.json                              | 14 +++++++++++
 frontend/src/api/schema.d.ts                       | 10 ++++++++
 .../src/features/daily-board/presentation.test.ts  |  2 +-
 frontend/src/features/daily-board/presentation.ts  |  3 ++-
 .../src/features/projects/ProductEditor.test.tsx   | 29 ++++++++++++++++++++++
 frontend/src/features/projects/ProductEditor.tsx   |  7 +++---
 frontend/tests/product-editor.spec.ts              | 26 +++++++++++++++++++
 scripts/test_postgres_disposable.py                |  2 +-
 .../api/product_editor_schemas.py                  |  1 +
 src/production_besten/api/routes.py                |  2 +-
 src/production_besten/api/schemas.py               |  1 +
 src/production_besten/domain/product_definition.py |  3 +++
 src/production_besten/domain/scheduling/engine.py  | 15 +++++++----
 src/production_besten/domain/scheduling/models.py  |  1 +
 src/production_besten/persistence/execution_uow.py |  3 +++
 .../persistence/frozen_editor_demand.py            |  1 +
 .../persistence/installation_queries.py            |  4 +--
 .../persistence/product_definition_uow.py          | 13 +++++-----
 .../persistence/product_editor_uow.py              | 27 +++++++++++++++-----
 .../persistence/scheduling_uow.py                  |  2 +-
 tests/integration/test_accept_replan.py            |  2 +-
 tests/integration/test_basic_scheduler.py          |  4 +--
 tests/unit/test_cumulative_scheduler.py            |  2 +-
 24 files changed, 144 insertions(+), 32 deletions(-)
```

Conclusión: **PILOT_OPTIONAL_SKILL_IMPLEMENTED**.
