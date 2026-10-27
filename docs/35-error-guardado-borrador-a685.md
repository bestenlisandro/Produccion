# Piloto 1 — error real al guardar el borrador de A685

Base: `master`, `286fe01db3da92883294e4279ba5365c7aad8a45`.
Clasificación: **BUG_BACKEND — configuración de permisos del rol runtime**.

## Evidencia del fallo real

El log del backend registra HTTP **500** en:

`PUT /projects/7e3f3c2e-d102-41b6-b2b0-ff2780af99a1/product-definition`.

El traceback termina en `product_editor_uow.py`, `editor_execute`, al ejecutar:

```sql
UPDATE audit.audit_entries
SET after_data = CAST(:result AS jsonb)
WHERE id = :id AND organization_id = :org;
```

Excepción: `psycopg.errors.InsufficientPrivilege`, envuelta por
`sqlalchemy.exc.ProgrammingError`: permiso denegado a `audit_entries`.
La reproducción identifica SQLSTATE **42501** en esa misma sentencia.

El rol `produccion_besten_app` tenía SELECT e INSERT en auditoría, pero no UPDATE
de `after_data`. El editor inserta el registro de lifecycle y completa su resultado
para replay dentro de la misma transacción. Por eso el fallo ocurre al final del
guardado, después de construir el borrador, y no por una constraint de fases.

El log conserva la sentencia y un resultado serializado truncado, no el cuerpo
HTTP completo. No se atribuye al usuario un payload completo que no se capturó.
La entrada conocida es un lote con Corte / Escuadradora, Perforadora Múltiple,
Armado e Instalación sin fases. El resultado del traceback incluye errores
orientativos de fases pendientes, coherentes con un borrador incompleto permitido.

## Estado real y rollback

Antes de corregir se verificó:

- Un único cliente: `Nico Del Castillo`, sin teléfono ni email.
- Proyecto A685 / Alacenas, ID `7e3f3c2e-d102-41b6-b2b0-ff2780af99a1`.
- Estado activo y row_version **5**.
- Cero lotes, operaciones, fases y revisiones productivas persistidas.
- Cero entradas `PRODUCT_EDITOR_*` persistidas.
- Sin CURRENT ni revisión productiva actual.

El UPDATE fallido no dejó el resultado parcial ni incrementó la versión del
proyecto: el rollback de la transacción funcionó. Los datos pendientes del lote
y sus operaciones permanecen exclusivamente en el formulario del usuario.

## Corrección mínima

Se aplicó en `produccion_besten`, mediante su propietario:

```sql
GRANT UPDATE (after_data) ON TABLE audit.audit_entries TO produccion_besten_app;
```

El procedimiento repetible está en
`db/operations/editor_audit_result_permission.sql`. Es una reparación operativa
de ACL, **no una migración ni un cambio del schema**. No concede UPDATE general,
UPDATE de metadata, DELETE, propiedad ni privilegios administrativos. El rol
conserva NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION y NOBYPASSRLS.

Los permisos se hacen efectivos en las conexiones existentes. No se reinició el
backend ni se modificó el frontend: no se provoca una recarga/HMR que pueda perder
el formulario real. No se pulsó Guardar ni Reintentar sobre A685.

## Borrador, validación y freeze

La semántica existente ya permite operaciones con **0 fases en borrador**:

- GUARDAR BORRADOR persiste la edición progresiva y devuelve HTTP 200 con los
  errores pendientes en `errors`.
- VALIDAR devuelve HTTP 200 con esa información, sin congelar.
- CONGELAR exige una definición completa; en el caso sin fases devuelve HTTP
  **400** de dominio con explicación de lo faltante, conforme al contrato actual.

No fue necesario cambiar estas reglas. El fallo de infraestructura no se convirtió
en un rechazo de datos del usuario ni se flexibilizaron los requisitos de freeze.

## Pruebas

`tests/integration/test_editor_runtime_permissions.py` agrega un rol NOLOGIN
restringido en una base descartable. Evita el punto ciego de probar únicamente
como propietario de las tablas.

El primer caso reproduce proyecto A685, lote y cuatro operaciones sin fases:
sin el permiso obtiene 500/42501, y verifica rollback comparando filas completas.
Aplica el mismo SQL operativo, adaptando únicamente el nombre del rol descartable;
la **misma petición y misma Idempotency-Key** obtiene 200. Un nuevo retry devuelve
replay, sin duplicar el lote ni las cuatro operaciones. También comprueba VALIDAR
y el rechazo comprensible de CONGELAR.

El segundo caso inyecta un fallo después de completar el resultado de auditoría
con el permiso corregido y confirma rollback atómico de proyecto, demanda,
precedencias, planning state, eventos y auditoría.

Suite relevante completa: **51 passed, 0 failed**, con los dos warnings de
dependencias conocidos. Bases y roles descartables eliminados. No se crearon
fixtures ni se ensayó el guardado en `produccion_besten`.

No cambia el código de aplicación, contrato HTTP, OpenAPI, tipos ni interfaz.
Vitest, Playwright y build no se repiten para este ajuste exclusivamente de ACL;
la validación anterior sigue siendo 164 Vitest, 202 Playwright/14 skips y build
aprobado. No se requiere recargar la pantalla del usuario.

## Entrega

La acción pendiente corresponde al usuario: pulsar **REINTENTAR GUARDADO** en la
pantalla que conserva el borrador. No se hizo commit ni push. App de Compras y
backup no fueron accedidos, inspeccionados ni modificados.
