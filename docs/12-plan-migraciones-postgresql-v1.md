# Etapa 3 — Plan de migraciones PostgreSQL V1

## 1. Objetivo

Materializar las 87 tablas y 8 schemas del esquema físico V1 simplificado mediante migraciones deterministas, aplicables sobre PostgreSQL limpio y sin depender de Supabase.

## 2. Convención de archivos

Las migraciones vivirán en `db/migrations`, serán forward-only, numeradas y ejecutadas en orden lexical. Cada archivo usa transacción explícita salvo operaciones que PostgreSQL no permita transaccionar. No se implementan `down migrations` destructivas: el rollback de desarrollo consiste en eliminar y recrear la base; en ambientes con datos se corrige mediante una migración compensatoria.

## 3. Orden final

| Orden | Archivo | Responsabilidad | Tablas |
|---:|---|---|---:|
| M0 | `000_extensions_schemas_types.sql` | `pgcrypto`, `btree_gist`, 8 schemas, tipos cerrados y funciones utilitarias | 0 |
| M1 | `001_core_identity.sql` | Organización, plantas, identidad externa, roles cerrados, clientes, prioridades e hitos | 7 |
| M2 | `002_capacity.sql` | Centros, personas, skills, recursos, calendarios, indisponibilidad y horas extra | 13 |
| M3 | `003_production.sql` | Proyectos/lotes/hitos más las 31 tablas productivas | 34 |
| M4 | `004_planning_state.sql` | State head/revisions, eventos, excepciones, locks, versiones, escenarios e hipótesis | 8 |
| M5 | `005_scheduling.sql` | Solución/run/impacto, resultados, asignaciones, reservas, ocupaciones e hitos | 10 |
| M6 | `006_execution.sql` | Ejecución, segmentos, usos reales y estimaciones restantes | 5 |
| M7 | `007_portal.sql` | Mapping, token, proyección, timeline y fechas comunicadas | 7 |
| M8 | `008_integration_audit.sql` | Inbox, outbox y auditoría | 3 |
| M9 | `009_advanced_constraints_indexes.sql` | FK cíclicas/diferidas, EXCLUDE, checks e índices secundarios | 0 |
| M10 | `010_minimum_seed.sql` | Seed técnico mínimo; V1 no inserta datos productivos ficticios | 0 |
|  | **Total** |  | **87** |

## 4. Dependencias y ciclos

La secuencia sugerida originalmente no podía aplicarse literalmente por estos ciclos:

- planta → calendario, revisión productiva y versión vigente;
- state revision ↔ effective event;
- plan version → solución y escenario, mientras escenario → plan version;
- excepción ↔ hipótesis;
- resultados de fase ↔ asignación compartida;
- ocupación/lock → ejecución futura;
- entidades productivas → evento efectivo futuro.

Estrategia:

1. crear primero columnas UUID y la tabla propietaria;
2. agregar FK cíclicas en M9 mediante `ALTER TABLE`;
3. mantener punteros Current nullable durante bootstrap;
4. usar `DEFERRABLE INITIALLY DEFERRED` solo donde una transacción legítima crea ambos extremos;
5. usar `ON DELETE RESTRICT/NO ACTION`, nunca cascadas desde historia.

## 5. Multitenancy

Cada tabla tenant-owned incluye `organization_id`. Conserva PK UUID simple y agrega UNIQUE `(organization_id,id)` para FK compuestas. Las referencias de negocio usan `(organization_id, foreign_id)` siempre que ambos extremos sean tenant-owned. Las reglas que además exigen misma planta se validan mediante claves compuestas específicas o constraints diferidos de servicio cuando una simple FK no alcanza.

## 6. Constraints inmediatos y posteriores

Se crean inmediatamente:

- PK, NOT NULL y defaults;
- checks locales de cantidades, rangos y discriminadores;
- uniques sin ciclos;
- FK cuya tabla ya existe;
- hashes de 32 bytes;
- checks de dimensiones restantes.

M9 agrega:

- FK cíclicas;
- punteros Current y referencias históricas tardías;
- exclusiones GiST por solución/persona/recurso/rango;
- ocupación real/planificada contextual;
- índices parciales y de consulta;
- checks diferibles que pueden expresarse con FK/constraint trigger mínimo.

El DAG, capacidad acumulativa, fórmulas agregadas, transiciones de estado complejas y canonicalización pertenecen al servicio/motor y se documentan como invariantes no reducibles a CHECK.

## 7. Extensiones

- `pgcrypto`: UUID/hash cuando el servicio no los provea y verificación futura de snapshots.
- `btree_gist`: combinación UUID/boolean/rango en EXCLUDE.

No se crean objetos `auth.*`; `core.user_profiles.auth_subject` enlazará desde aplicación con Supabase Auth o equivalente.

## 8. Temporalidad

Todos los rangos se validan no vacíos y usan `[)`. Las exclusiones de planificación incluyen `schedule_solution_id`, por lo que alternativas S18/S19 pueden solaparse. Las ocupaciones reales efectivas usan exclusión sin solution context. Capacidad acumulativa queda para el motor.

## 9. Append-only y borrado

No se añaden triggers universales. PK/FK y privilegios base evitan destrucción accidental; no hay `ON DELETE CASCADE` desde proyecto, escenario, versión, ejecución, evento o revisión. La futura cuenta de aplicación recibirá permisos por schema y operaciones; eventos, versiones, soluciones finales y auditoría se modificarán únicamente mediante servicios autorizados o compensaciones.

## 10. Seed mínimo

No se insertan empleados, clientes, recursos, organizaciones ni proyectos. Los roles/tipos cerrados son enums/checks. La configuración de una organización, calendarios, etapas públicas y rutas será un flujo de onboarding futuro. Los fixtures de verificación se mantienen fuera de migraciones.

## 11. Rollback

- Desarrollo/base efímera: recrear base limpia y reaplicar M0–M10.
- Migración fallida: la transacción del archivo revierte completa.
- Ambiente con datos: migración forward compensatoria; nunca editar una migración ya aplicada.
- No se provee script que borre schemas productivos por seguridad.

## 12. Validación

`db/verify/verify_schema.sql` comprobará:

1. 8 schemas y 87 tablas exactas;
2. PK en cada tabla;
3. ownership tenant y FK compuestas;
4. extensiones;
5. exclusión de persona/recurso dentro de solución;
6. coexistencia entre soluciones;
7. rechazo cross-organization;
8. snapshot/hash histórico;
9. ausencia de cascadas destructivas críticas;
10. conteos de constraints e índices.

`db/verify/temporal_scenarios.sql` contendrá una prueba transaccional con fixtures descartables. La validación real se ejecutará mediante PostgreSQL local si el entorno está disponible; de lo contrario se marcará explícitamente como pendiente y no se declararán migraciones validadas.

## 13. Riesgos

- Las muchas FK tenant-safe aumentan DDL e índices, pero evitan aislamiento dependiente de la aplicación.
- Los ciclos exigen que M9 permanezca sincronizada con los archivos base.
- EXCLUDE requiere `btree_gist` disponible.
- RLS no debe activarse hasta disponer de un proveedor de claims verificable; la estrategia se documenta aparte.
- El total exacto de índices incluye índices automáticos de PK/UNIQUE/EXCLUDE y puede variar por versión PostgreSQL; se distingue de las 28 familias secundarias explícitas.

No se detecta `BRECHA_IMPLEMENTACION` en el plan. Se autoriza continuar con el DDL dentro de esta Etapa 3.
