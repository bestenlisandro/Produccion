# Etapa 3.1 — Cierre de migraciones PostgreSQL V1

Fecha de validación: 2026-09-01  
Estado: **CERRADA**

## 1. Alcance validado

Se aplicaron y verificaron las once migraciones M0–M10 del esquema físico V1 sobre una base PostgreSQL local, limpia y descartable. La validación cubrió catálogo, constraints, índices, extensiones, funciones/triggers mínimos, aislamiento entre organizaciones, temporalidad, recursos exclusivos, ocupación nocturna y las tres revisiones centrales del modelo.

No se desarrollaron backend, API, frontend, Gantt, portal ni motor APS. No se realizó ningún commit.

## 2. Entorno real

| Elemento | Resultado |
|---|---|
| Servidor | PostgreSQL 18.6 |
| Build | `x86_64-windows`, MSVC 19.44.35228, 64-bit |
| Cliente | `psql 18.6` |
| Servicio | `postgresql-x64-18` |
| Endpoint | `127.0.0.1:5432` |
| Base descartable | `produccion_besten_test` |
| `pgcrypto` | 1.4 |
| `btree_gist` | 1.8 |

Se usó un rol temporal limitado a la validación. La contraseña administrativa no se guardó en archivos ni documentación.

Al finalizar se eliminaron `produccion_besten_test` y el rol `codex_migration_validation`; el servicio PostgreSQL quedó operativo y sin objetos de prueba residuales.

## 3. Migraciones ejecutadas

| Orden | Archivo | Resultado final |
|---:|---|---|
| M0 | `000_extensions_schemas_types.sql` | Aprobada |
| M1 | `001_core_identity.sql` | Aprobada |
| M2 | `002_capacity.sql` | Aprobada |
| M3 | `003_production.sql` | Aprobada |
| M4 | `004_planning_state.sql` | Aprobada |
| M5 | `005_scheduling.sql` | Aprobada |
| M6 | `006_execution.sql` | Aprobada después de corrección mínima |
| M7 | `007_portal.sql` | Aprobada |
| M8 | `008_integration_audit.sql` | Aprobada |
| M9 | `009_advanced_constraints_indexes.sql` | Aprobada |
| M10 | `010_minimum_seed.sql` | Aprobada |

Las once migraciones conservan `BEGIN/COMMIT`, se aplican en orden lexical y la auditoría estática sigue aprobada.

## 4. Primera aplicación sin cambios preventivos

La primera aplicación de M0–M10 se ejecutó exactamente como estaba implementada. Terminó correctamente y las suites originales confirmaron:

- 8 schemas;
- 87 tablas;
- 87 PK;
- 297 FK;
- 7 EXCLUDE;
- 290 índices;
- escenarios alternativos solapables;
- rechazo cross-organization;
- snapshot histórico preservado.

Después se ampliaron únicamente los scripts de verificación para cubrir los casos exigidos por la Etapa 3.1 que todavía no tenían prueba ejecutable.

## 5. Error real de modelo y causa raíz

La prueba de reemplazo de una `RemainingEstimateRevision` reprodujo este error:

```text
ERROR: inserción o actualización en la tabla «remaining_estimate_revisions»
viola la llave foránea «fk_execution_remaining_revisions_superseded_by»
DETAIL: La llave (organization_id, superseded_by_id)=(...001, ...048)
no está presente en la tabla «remaining_estimate_revisions».
```

Causa raíz:

1. la revisión anterior debía actualizar `superseded_by_id` hacia la nueva;
2. la FK inmediata exigía que la nueva ya existiera;
3. insertar primero la nueva era imposible porque el índice parcial permite una sola revisión vigente;
4. por lo tanto, ninguna secuencia válida podía materializar el superseding atómico.

Corrección mínima aplicada en M6:

```sql
CONSTRAINT fk_execution_remaining_revisions_superseded_by
  FOREIGN KEY (organization_id,superseded_by_id)
  REFERENCES execution.remaining_estimate_revisions(organization_id,id)
  ON DELETE RESTRICT
  DEFERRABLE INITIALLY DEFERRED
```

No se cambiaron tablas, columnas, cardinalidades ni semántica funcional. La corrección permite actualizar la revisión anterior e insertar su sucesora en la misma transacción; `SET CONSTRAINTS ALL IMMEDIATE` prueba que la relación queda íntegra antes del commit/rollback.

## 6. Ajustes de las verificaciones

`verify_schema.sql` ahora comprueba y reporta explícitamente:

- PK, FK, UNIQUE, CHECK y EXCLUDE;
- índices reales;
- extensiones requeridas;
- cuatro funciones mínimas;
- cinco triggers de usuario habilitados;
- ausencia de FK tenant-owned sin `organization_id`;
- ausencia de `ON DELETE CASCADE` destructivo.

`temporal_scenarios.sql` ahora prueba además:

- solapamiento permitido entre soluciones alternativas;
- rechazo de reserva física y asignación humana solapadas dentro de la misma solución;
- compatibilidad de intervalos contiguos `[inicio, fin)`;
- ocupación física nocturna sin horas-persona;
- rechazo de ocupación física incompatible dentro de una solución;
- aislamiento cross-organization;
- `ProductDefinitionRevision` histórica y número único;
- avance y unicidad de `PlanningStateRevision`;
- rechazo de solución cuyas bases no coinciden con el escenario;
- triggers de coherencia operación/lote, instalación y uso real sobre segmento `WORK`;
- snapshot original de ejecución inalterado;
- fórmula ejecutado + restante = total actualizado;
- dimensiones `LABOR_WORK`, `ACTIVE_PHYSICAL_USE` y `PHYSICAL_OCCUPATION` separadas;
- una sola `RemainingEstimateRevision` vigente;
- superseding atómico y avance del state head.

Los fixtures se ejecutan dentro de una transacción y terminan con `ROLLBACK`.

## 7. Catálogo real confirmado

| Objeto | Cantidad |
|---|---:|
| Schemas de aplicación | 8 |
| Tablas | 87 |
| Primary keys | 87 |
| Foreign keys | 297 |
| UNIQUE constraints | 159 |
| CHECK constraints | 154 |
| EXCLUDE constraints | 7 |
| Índices totales | 290 |
| Funciones mínimas | 4 |
| Triggers de usuario habilitados | 5 |
| Extensiones requeridas | 2 |
| Cascadas destructivas | 0 |

PostgreSQL 18 registra adicionalmente 816 constraints `NOT NULL` con `contype='n'`. Se reportan por separado porque esta representación de catálogo es específica de versiones recientes y no altera los 617 constraints nombrados ni las 87 PK previstas en la documentación.

## 8. Reproducibilidad final

Una vez estabilizadas migraciones y pruebas se realizó la secuencia obligatoria:

### Recreación final 1

1. `DROP DATABASE produccion_besten_test WITH (FORCE)`;
2. creación vacía de `produccion_besten_test`;
3. aplicación M0–M10;
4. ejecución de `verify_schema.sql`;
5. ejecución de `temporal_scenarios.sql`.

Resultado: código 0, catálogo esperado y `temporal_and_tenant_tests_passed`.

### Recreación final 2

Se eliminó completamente la base anterior y se repitieron los cinco pasos sin intervención manual.

Resultado: código 0, mismos conteos, `temporal_and_tenant_tests_passed` y `Migrations and verification completed successfully.`

## 9. Otros errores encontrados durante la validación

Además de la brecha del modelo se corrigieron dos errores del arnés de prueba, sin impacto en el DDL de dominio:

1. PostgreSQL 18 consideró ambiguo concatenar un literal `unknown` con `pg_constraint.contype` (`"char"`) en una consulta exploratoria. Se resolvió con `contype::text`.
2. `SET CONSTRAINTS fk_execution_remaining_revisions_superseded_by IMMEDIATE` no encontró el constraint fuera del `search_path`. El test se corrigió a `SET CONSTRAINTS ALL IMMEDIATE` y se recreó nuevamente la base completa.

Después de cada cambio de archivo se descartó la base y se reaplicó toda la cadena; nunca se continuó sobre un esquema parcialmente corregido.

## 10. Riesgos residuales

- RLS continúa diferido hasta definir proveedor de identidad/claims y su suite de seguridad.
- Capacidad acumulativa, DAG, suma material y transiciones complejas siguen perteneciendo al servicio y al motor APS.
- La protección append-only completa dependerá también de roles/privilegios de aplicación.
- Los 290 índices requieren futuras pruebas `EXPLAIN` con volumen representativo.
- Falta validar concurrencia real de promoción, locks y actualización simultánea desde la futura capa de aplicación.
- PostgreSQL 18 fue el runtime validado; una matriz multi-versión podría agregarse más adelante si la política de despliegue exige soportar PostgreSQL 15–17.

Estos riesgos no invalidan la consistencia ni reproducibilidad del esquema físico V1.

## 11. Conclusión formal

**`MIGRACIONES_V1_VALIDADAS_EN_POSTGRESQL`**
