# Etapa 3 — Validación de migraciones PostgreSQL V1

## 1. Resultado ejecutivo

Se implementaron once migraciones forward-only para las 87 tablas y 8 schemas. La verificación estática pasó completamente y no detectó tablas faltantes, FK tenant-owned inseguras ni cascadas destructivas.

La cadena M0–M10 y las suites ampliadas se validaron realmente sobre **PostgreSQL 18.6 x86_64 para Windows**. Después de corregir una brecha transaccional real en el superseding de `RemainingEstimateRevision`, dos eliminaciones/recreaciones finales completas produjeron el mismo esquema y pasaron todas las pruebas sin intervención manual.

## 2. Migraciones creadas

| Orden | Archivo | Tablas |
|---:|---|---:|
| M0 | `000_extensions_schemas_types.sql` | 0 |
| M1 | `001_core_identity.sql` | 7 |
| M2 | `002_capacity.sql` | 13 |
| M3 | `003_production.sql` | 34 |
| M4 | `004_planning_state.sql` | 8 |
| M5 | `005_scheduling.sql` | 10 |
| M6 | `006_execution.sql` | 5 |
| M7 | `007_portal.sql` | 7 |
| M8 | `008_integration_audit.sql` | 3 |
| M9 | `009_advanced_constraints_indexes.sql` | 0 |
| M10 | `010_minimum_seed.sql` | 0 |
| **Total** | **11 migraciones** | **87** |

## 3. Estructura implementada

- Schemas declarados: **8**.
- Tablas declaradas: **87**, todas distintas y coincidentes 1:1 con el diccionario.
- PK inline deterministas: **87**.
- Constraints nombradas: **617**.
  - FK tenant-safe/históricas: **297**.
  - UNIQUE: **159**.
  - CHECK: **154**.
  - EXCLUDE: **7**.
- Constraints de catálogo esperadas incluyendo PK: **704**.
- `CREATE INDEX` explícitos: **37**.
  - familias secundarias aprobadas `ix01`–`ix28`: **28**;
  - índices únicos parciales adicionales: **9**.
- Índices reales incluyendo los generados por PK/UNIQUE/EXCLUDE: **290**, confirmados en servidor.
- Extensiones: `pgcrypto`, `btree_gist`.

PostgreSQL real confirmó: **87 PK, 297 FK, 159 UNIQUE, 154 CHECK, 7 EXCLUDE y 290 índices**. PostgreSQL 18 registra además **816 constraints `NOT NULL`** con `contype='n'`; no se suman a los 704 constraints nombrados/PK históricos porque su representación de catálogo depende de la versión. También quedaron confirmadas 4 funciones mínimas, 5 triggers de usuario habilitados y las 2 extensiones requeridas.

## 4. Seguridad e integridad estructural

Implementado:

- `organization_id` en las 86 tablas tenant-owned;
- PK UUID simple y clave candidata `(organization_id,id)`;
- 297 FK declaradas con `organization_id` cuando el padre es tenant-owned;
- cero `ON DELETE CASCADE`;
- privilegios `PUBLIC` revocados en schemas/tablas/secuencias;
- identidad externa `auth_subject`, sin passwords;
- RLS documentada pero no activada sin proveedor de claims;
- links públicos con hash de 32 bytes y único activo por proyecto;
- inbox idempotente y outbox con clave lógica.

## 5. Temporalidad

M9 define siete EXCLUDE:

1. roles vigentes sin solapamiento equivalente;
2. skills vigentes sin solapamiento;
3. versiones publicadas sin vigencias superpuestas;
4. persona sin doble asignación dentro de solución;
5. recurso exclusivo sin doble reserva dentro de solución;
6. ocupación planificada sin solapamiento dentro de solución;
7. ocupación real efectiva sin solapamiento global.

El contexto `schedule_solution_id` permite que escenarios alternativos reserven el mismo recurso en el mismo rango. Las cadenas padre→segmento→persona/recurso usan además FK compuestas con la solución para impedir IDs contextuales inconsistentes.

## 6. RemainingEstimateRevision

D089/D090 implementan:

- revisión secuencial y único restante vigente;
- cutoff, input bruto, modo, motivo, evento y state revision;
- ejecutado, restante y total actualizado con fórmula local;
- `LABOR_WORK`, `ACTIVE_PHYSICAL_USE` y `PHYSICAL_OCCUPATION` mediante enum/check;
- estimación original separada e inmutable en ejecución.

La lógica del comando no fue implementada, conforme al alcance.

## 7. Pruebas disponibles

- `db/verify/static_verify.ps1`: inventario, diccionario, transacciones, tenant FK, cascadas, índices y exclusiones.
- `db/verify/verify_schema.sql`: catálogo real, tablas esperadas, PK, extensiones, tenant FK y cascadas.
- `db/verify/temporal_scenarios.sql`: fixtures transaccionales para escenarios alternativos, exclusión dentro de solución, cross-tenant y snapshots.
- `db/verify/apply_with_psql.ps1`: aplica M0–M10 y ejecuta las dos verificaciones SQL.

## 8. Pruebas ejecutadas

### 8.1 Verificación estática — APROBADA

Resultado reproducible:

```text
migrations: 11
schemas: 8
tables: 87
named_constraints: 617
foreign_keys: 297
declared_indexes: 37
approved_secondary_index_families: 28
exclusion_constraints: 7
tenant_unsafe_foreign_keys: 0
destructive_cascades: 0
Static migration verification passed.
```

También se comprobó:

- 87 nombres SQL coinciden exactamente con las 87 entradas del diccionario;
- 11 archivos tienen `BEGIN/COMMIT`;
- 654 nombres de constraints/índices no exceden 63 caracteres ni colisionan por truncamiento;
- no hay archivos de tabla adicionales ni nombres hardcodeados de empleados/clientes.

### 8.2 Aplicación PostgreSQL limpia — APROBADA

Entorno real:

- servidor: `PostgreSQL 18.6 on x86_64-windows, compiled by msvc-19.44.35228, 64-bit`;
- servicio: `postgresql-x64-18`;
- conexión: `127.0.0.1:5432`;
- base descartable: `produccion_besten_test`;
- extensiones: `pgcrypto 1.4` y `btree_gist 1.8`.

La primera aplicación sin cambios preventivos aplicó M0–M10 y pasó las verificaciones originales. Al ampliar los casos de ejecución/restante se detectó una brecha real, se aplicó la corrección mínima y se recreó siempre la base desde cero. La cadena corregida pasó una corrida de estabilización y dos recreaciones finales completas idénticas.

Resultado de catálogo repetido en ambas recreaciones finales:

```text
schemas: 8
tables: 87
primary_keys: 87
foreign_keys: 297
unique_constraints: 159
check_constraints: 154
exclusions: 7
indexes: 290
minimum_functions: 4
enabled_user_triggers: 5
required_extensions: 2
destructive_cascades: 0
```

`temporal_scenarios.sql` terminó en ambas corridas con `temporal_and_tenant_tests_passed` y rollback completo de fixtures.

## 9. Errores encontrados y corregidos

1. Las referencias externas opcionales de proveedor/pedido/entrega/evento usaban inicialmente semántica de NULL no distinto. Se corrigieron a índices únicos parciales `WHERE external_reference IS NOT NULL`.
2. IDs de segmento/padre y `schedule_solution_id` tenían FK independientes. Se agregaron claves/FK compuestas para impedir mezclar soluciones y eludir exclusiones.
3. La exclusión de vigencias se limitaba inicialmente a estado `published`. Se extendió a toda la historia para impedir intervalos solapados.
4. Se agregaron constraints de misma planta para Current, bases de escenario y revisiones.
5. Se agregaron triggers mínimos para operación/lote, operación de instalación, usos reales sobre segmento WORK y coherencia solución/escenario.
6. La validación real detectó que `fk_execution_remaining_revisions_superseded_by` era inmediata. Esto hacía imposible reemplazar una revisión vigente: actualizar la anterior fallaba porque la sucesora aún no existía, e insertar la sucesora primero chocaba con el índice de único vigente. Se corrigió exclusivamente esa FK a `DEFERRABLE INITIALLY DEFERRED`.
7. Se ampliaron las verificaciones de catálogo y escenarios. El test usa `SET CONSTRAINTS ALL IMMEDIATE` para forzar la validación de la transición antes del rollback.

No se agregó una tabla 88 ni se detectó `BRECHA_IMPLEMENTACION` estructural.

## 10. Riesgos residuales

- RLS requiere proveedor Auth y suite propia antes de habilitarse.
- DAG, capacidad acumulativa, suma material, estados append-only por permisos y transiciones complejas siguen correctamente asignados al servicio/motor.
- Los planes de ejecución e índices deberán validarse con `EXPLAIN` y volumen representativo.
- PostgreSQL 18 expone `NOT NULL` en `pg_constraint`; cualquier automatización de conteo total debe distinguir esta diferencia respecto de versiones anteriores.
- La validación demuestra integridad física y escenarios representativos, no reemplaza pruebas futuras de concurrencia del servicio ni del motor APS.

## 11. Reproducibilidad

La comprobación final obligatoria se ejecutó dos veces con esta secuencia:

1. eliminar `produccion_besten_test` con conexiones forzadas;
2. crearla vacía;
3. ejecutar M0–M10 en orden lexical mediante `apply_with_psql.ps1`;
4. ejecutar `verify_schema.sql`;
5. ejecutar `temporal_scenarios.sql`;
6. confirmar conteos y resultados;
7. eliminarla y repetir desde cero.

Ambas ejecuciones terminaron con código 0 y `Migrations and verification completed successfully.`

## 12. Conclusión formal

El DDL está implementado, auditado estáticamente, aplicado en PostgreSQL real y reproducido dos veces desde una base vacía con todas las verificaciones aprobadas.

**`MIGRACIONES_V1_VALIDADAS_EN_POSTGRESQL`**
