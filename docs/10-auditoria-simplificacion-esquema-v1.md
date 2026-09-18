# Etapa 2.2 — Auditoría de simplificación del esquema físico V1

## 1. Resumen ejecutivo

El esquema completo de 107 tablas es correcto, coherente y defendible como arquitectura objetivo. Sin embargo, no todas sus abstracciones necesitan materializarse antes de la primera migración.

La auditoría identifica 20 tablas cuya responsabilidad puede diferirse o incorporarse limpiamente en otra estructura para V1:

- 15 candidatas a fusión;
- 5 diferibles;
- ninguna eliminación de conceptos centrales;
- ninguna fusión entre persona y recurso físico, trabajo y ocupación, ejecución y planificación, escenario y plan vigente, ni estado interno y estado público.

La opción recomendada contiene **87 tablas en los mismos 8 schemas**. Conserva las 66 tablas imprescindibles y las 21 convenientes. No elimina las estructuras de materiales/recepciones, integración idempotente, estimación restante, capacidad finita, portal seguro ni auditoría general porque hacerlo abriría brechas concretas en los casos aprobados.

Esta propuesta todavía no modifica los documentos 07 y 08. Antes de migrar deberá aprobarse y, recién entonces, producir una revisión física consolidada.

## 2. Criterio de V1

La V1 pragmática sigue incluyendo el ciclo profesional completo: proyectos, lotes, rutas, operaciones y fases; personas, habilidades, máquinas, bancos, centros, calendarios, indisponibilidades y horas extra; materiales simplificados con recepción parcial e idempotencia; planos, herrajes e instalación; planificación finita explicable; escenarios, comparación, promoción y versionado; ejecución real y estimación restante multidimensional; portal público seguro; múltiples usuarios y aislamiento por organización.

La reducción solo aplica cuando se cumple al menos una condición:

1. una relación es 1:1 en V1 y puede expresarse mediante columnas tipadas en la entidad propietaria;
2. un catálogo configurable puede ser un código cerrado de aplicación sin perder reglas de negocio;
3. una tabla repite evidencia ya preservada por versión, evento o auditoría;
4. una cabecera tiene relación estrictamente 1:1 con su resultado;
5. la funcionalidad puede derivarse de datos existentes con una regla V1 explícita.

No se propone reemplazar relaciones centrales por JSONB opaco ni arrays difíciles de consultar.

## 3. Distribución actual y propuesta

| Schema | Actual | Opción V1 | Diferencia | Observación |
|---|---:|---:|---:|---|
| `core` | 11 | 10 | -1 | Roles V1 cerrados en la asignación de usuario |
| `capacity` | 17 | 13 | -4 | Un calendario base directo por propietario |
| `production` | 34 | 31 | -3 | Herrajes e instalación usan entidades productivas ya existentes |
| `planning` | 25 | 18 | -7 | Se fusionan cabeceras 1:1 y se difiere historia auxiliar duplicada |
| `execution` | 6 | 5 | -1 | Pausas tipadas dentro de la línea temporal de ejecución |
| `portal` | 10 | 7 | -3 | Recomendación derivada y auditoría general en lugar de historiales paralelos |
| `integration` | 2 | 2 | 0 | Idempotencia de Compras y publicación confiable siguen cubiertas |
| `audit` | 2 | 1 | -1 | La promoción queda en versión del plan más auditoría general |
| **Total** | **107** | **87** | **-20** | Sin reducir schemas ni conceptos esenciales |

Clasificación total: **66 A**, **21 B**, **5 C** y **15 D**.

## 4. Clasificación de las 107 tablas

### 4.1 `core`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D001 `organizations` | core | A — IMPRESCINDIBLE V1 | Tenant, configuración y aislamiento comercial | Mantener |
| D002 `plants` | core | A — IMPRESCINDIBLE V1 | Ámbito operativo, zona horaria y punteros vigentes | Mantener; recibir calendario base y puntero del plan V1 |
| D003 `user_profiles` | core | A — IMPRESCINDIBLE V1 | Identidad de múltiples usuarios sin guardar credenciales | Mantener |
| D004 `roles` | core | D — CANDIDATA A FUSIÓN | Roles configurables por organización exceden V1; los permisos técnicos ya son allowlist de aplicación | Fusionar como `role_code` cerrado en D005; `POSIBLE_SOBREINGENIERIA` |
| D005 `user_roles` | core | A — IMPRESCINDIBLE V1 | Asignación de rol, planta, vigencia y trazabilidad | Mantener con `role_code` |
| D006 `customers` | core | A — IMPRESCINDIBLE V1 | Propietario comercial y destinatario del portal | Mantener |
| D007 `project_priorities` | core | B — CONVENIENTE V1 | Evita rangos mágicos y permite prioridad explicable | Mantener |
| D008 `projects` | core | A — IMPRESCINDIBLE V1 | Agregado comercial/productivo principal | Mantener |
| D009 `project_lots` | core | A — IMPRESCINDIBLE V1 | Unidad independiente de precedencia, material y ruta | Mantener; recibir estado de herrajes V1 |
| D010 `milestone_definitions` | core | B — CONVENIENTE V1 | Unifica hitos internos, soluciones y portal sin códigos libres | Mantener |
| D011 `project_milestones` | core | B — CONVENIENTE V1 | Historia real de hitos distinta de fechas estimadas | Mantener |

### 4.2 `capacity`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D012 `work_centers` | capacity | A — IMPRESCINDIBLE V1 | Agrupación operativa y capacidad agregada | Mantener; recibir calendario base opcional |
| D013 `employees` | capacity | A — IMPRESCINDIBLE V1 | Recurso humano separado del usuario y de máquinas | Mantener; recibir calendario base |
| D014 `skills` | capacity | A — IMPRESCINDIBLE V1 | Elegibilidad humana parametrizable | Mantener |
| D015 `employee_skills` | capacity | A — IMPRESCINDIBLE V1 | Relación N:M con vigencia | Mantener |
| D016 `physical_resource_types` | capacity | B — CONVENIENTE V1 | Tipifica banco, máquina y otros recursos sin hardcodear nombres | Mantener |
| D017 `physical_resources` | capacity | A — IMPRESCINDIBLE V1 | Máquina/banco concreto, capacidad y modo de scheduling | Mantener; recibir calendario base |
| D018 `physical_resource_groups` | capacity | B — CONVENIENTE V1 | Permite selección entre recursos equivalentes | Mantener |
| D019 `physical_resource_group_members` | capacity | B — CONVENIENTE V1 | Relación N:M y prioridad de alternativas | Mantener |
| D020 `calendars` | capacity | A — IMPRESCINDIBLE V1 | Identidad y zona horaria de disponibilidad | Mantener |
| D021 `calendar_working_intervals` | capacity | A — IMPRESCINDIBLE V1 | Jornadas, turnos y vigencia | Mantener |
| D022 `calendar_exceptions` | capacity | A — IMPRESCINDIBLE V1 | Feriados y cambios puntuales | Mantener |
| D023 `plant_calendar_assignments` | capacity | D — CANDIDATA A FUSIÓN | En V1 existe un calendario base por planta | Mover `calendar_id` a D002; `POSIBLE_SOBREINGENIERIA` para overlays múltiples |
| D024 `work_center_calendar_assignments` | capacity | D — CANDIDATA A FUSIÓN | Un calendario base opcional basta para el centro | Mover `calendar_id` a D012 |
| D025 `employee_calendar_assignments` | capacity | D — CANDIDATA A FUSIÓN | Un calendario base más indisponibilidades cubre V1 | Mover `calendar_id` a D013; `POSIBLE_SOBREINGENIERIA` para múltiples asignaciones simultáneas |
| D026 `physical_resource_calendar_assignments` | capacity | D — CANDIDATA A FUSIÓN | Un calendario base más indisponibilidades cubre V1 | Mover `calendar_id` a D017 |
| D027 `resource_unavailabilities` | capacity | A — IMPRESCINDIBLE V1 | Ausencias y paradas reales con rango y corrección | Mantener |
| D028 `overtime_authorizations` | capacity | A — IMPRESCINDIBLE V1 | Evita consumir capacidad extraordinaria silenciosamente | Mantener |

### 4.3 `production`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D029 `operation_definitions` | production | A — IMPRESCINDIBLE V1 | Catálogo parametrizable de operaciones | Mantener |
| D030 `route_templates` | production | A — IMPRESCINDIBLE V1 | Reutilización controlada de rutas | Mantener |
| D031 `route_versions` | production | B — CONVENIENTE V1 | Evita modificar rutas históricas y asegura reproducibilidad | Mantener |
| D032 `route_steps` | production | A — IMPRESCINDIBLE V1 | Composición de la ruta | Mantener |
| D033 `route_step_phase_templates` | production | A — IMPRESCINDIBLE V1 | Fases y estimaciones originales de plantilla | Mantener |
| D034 `route_step_precedences` | production | A — IMPRESCINDIBLE V1 | Grafo reusable de la ruta | Mantener |
| D035 `lot_route_assignments` | production | B — CONVENIENTE V1 | Asigna versión concreta y conserva historia | Mantener |
| D036 `required_operations` | production | A — IMPRESCINDIBLE V1 | Operación requerida real del proyecto/lote | Mantener; representar instalación como categoría/subtipo |
| D037 `required_operation_phases` | production | A — IMPRESCINDIBLE V1 | Unidad de estimación y asignación efectiva | Mantener |
| D038 `operation_precedences` | production | A — IMPRESCINDIBLE V1 | Grafo instanciado y precedencias manuales | Mantener |
| D039 `operation_gates` | production | A — IMPRESCINDIBLE V1 | Material, plano, herraje e hito como restricciones temporales | Mantener |
| D040 `operation_labor_requirements` | production | A — IMPRESCINDIBLE V1 | Trabajo, habilidad y equipo humano | Mantener |
| D041 `operation_physical_requirements` | production | A — IMPRESCINDIBLE V1 | Máquina, banco, centro y modo de uso | Mantener |
| D042 `product_definition_revisions` | production | A — IMPRESCINDIBLE V1 | Snapshot reproducible e inmutable de entrada productiva | Mantener |
| D043 `production_batches` | production | A — IMPRESCINDIBLE V1 | Lote de ejecución compartida entre operaciones | Mantener |
| D044 `production_batch_versions` | production | A — IMPRESCINDIBLE V1 | Congela composición/estimación publicada | Mantener |
| D045 `production_batch_members` | production | A — IMPRESCINDIBLE V1 | Relación N:M del lote productivo | Mantener |
| D046 `suppliers` | production | B — CONVENIENTE V1 | Identidad estable para pedidos/recepciones y futura integración | Mantener |
| D047 `material_requirements` | production | A — IMPRESCINDIBLE V1 | Gate material por lote y cantidad | Mantener |
| D048 `supplier_orders` | production | B — CONVENIENTE V1 | Promesas de entrega y trazabilidad con Compras | Mantener |
| D049 `supplier_order_lines` | production | B — CONVENIENTE V1 | Cantidad/unidad por ítem sin JSON opaco | Mantener |
| D050 `supplier_deliveries` | production | A — IMPRESCINDIBLE V1 | Hecho idempotente de recepción/devolución | Mantener |
| D051 `supplier_delivery_lines` | production | A — IMPRESCINDIBLE V1 | Movimientos parciales por material | Mantener |
| D052 `material_allocations` | production | A — IMPRESCINDIBLE V1 | Distribuye una recepción entre lotes sin sobreasignar | Mantener |
| D053 `drawing_packages` | production | A — IMPRESCINDIBLE V1 | Gate de planos por lote | Mantener |
| D054 `drawing_releases` | production | B — CONVENIENTE V1 | Correcciones y liberaciones históricas | Mantener |
| D055 `hardware_readiness` | production | D — CANDIDATA A FUSIÓN | Existe como único estado 1:1 del lote | Incorporar `hardware_status`, `hardware_available_at` y evento fuente en D009; gate apunta al lote |
| D056 `installation_work_packages` | production | D — CANDIDATA A FUSIÓN | Duplica operación, estimación y equipo; tiene FK 1:1 a operación requerida | Usar D036 como operación de tipo instalación y D037/D040 para tiempo/equipo; `POSIBLE_SOBREINGENIERIA` |
| D057 `installation_lot_coverages` | production | B — CONVENIENTE V1 | La instalación puede cubrir varios lotes y viceversa | Mantener, apuntando a la operación de instalación |
| D058 `customer_availability_windows` | production | A — IMPRESCINDIBLE V1 | Restricción temporal propia de instalación | Mantener, apuntando a la operación de instalación |
| D059 `installation_progress_entries` | production | D — CANDIDATA A FUSIÓN | Duplica parcialmente ejecución y evento efectivo | Registrar progreso derivable desde ejecución o evento `INSTALLATION_PROGRESS_UPDATED`; proyectar a D095 |
| D105 `route_phase_labor_requirement_templates` | production | B — CONVENIENTE V1 | Evita perder integridad en plantillas de trabajo | Mantener |
| D106 `route_phase_physical_requirement_templates` | production | B — CONVENIENTE V1 | Evita JSON para requerimientos físicos de plantilla | Mantener |
| D107 `route_phase_gate_templates` | production | B — CONVENIENTE V1 | Instancia gates de manera reproducible | Mantener |

### 4.4 `planning`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D060 `planning_state_heads` | planning | A — IMPRESCINDIBLE V1 | Revisión global O(1) y serialización de cambios | Mantener |
| D061 `planning_state_revisions` | planning | A — IMPRESCINDIBLE V1 | Versiona el estado operativo usado por escenarios | Mantener |
| D062 `planning_state_changes` | planning | C — DIFERIBLE | Detalle por entidad se superpone con eventos, auditoría y metadata de revisión | Diferir; guardar resumen estructurado en D061 y causas en D064/D104; `POSIBLE_SOBREINGENIERIA` |
| D063 `event_types` | planning | D — CANDIDATA A FUSIÓN | V1 no necesita que los tipos de evento sean configurables por tenant | Usar `event_type_code` y versión de payload en D064, validados por aplicación |
| D064 `effective_events` | planning | A — IMPRESCINDIBLE V1 | Hechos operativos, compensación e idempotencia | Mantener con código de tipo directo |
| D065 `manual_exception_reasons` | planning | D — CANDIDATA A FUSIÓN | Catálogo configurable no aporta una regla V1 que no pueda cerrar la aplicación | Mover `reason_code`/`reason_text` y regla de aprobación a D066 |
| D066 `manual_exceptions` | planning | B — CONVENIENTE V1 | Overrides explícitos, acotados y auditables | Mantener |
| D067 `planning_locks` | planning | A — IMPRESCINDIBLE V1 | Congela ejecución y decisiones manuales | Mantener |
| D068 `planning_plans` | planning | D — CANDIDATA A FUSIÓN | V1 necesita un programa publicado por planta; los alternativos son escenarios | Mover Current/promoción a D002/D060 y `plant_id` a versiones/escenarios/locks; `POSIBLE_SOBREINGENIERIA` para múltiples planes por planta |
| D069 `plan_versions` | planning | A — IMPRESCINDIBLE V1 | Historia inmutable del programa confirmado | Mantener, con `plant_id` como agregado V1 |
| D070 `scenarios` | planning | A — IMPRESCINDIBLE V1 | Aísla simulación del programa vigente | Mantener, con `plant_id` |
| D071 `simulation_hypotheses` | planning | A — IMPRESCINDIBLE V1 | Conserva intención sin mutar realidad | Mantener |
| D072 `scenario_effective_events` | planning | C — DIFERIBLE | La revisión base ya determina el conjunto efectivo y la hipótesis puede guardar el evento disparador | Diferir; `trigger_event_id` directo en D070/D071; `POSIBLE_SOBREINGENIERIA` N:M para V1 |
| D073 `impact_analyses` | planning | D — CANDIDATA A FUSIÓN | En V1 hay una comparación por ejecución/solución y la cabecera es 1:1 | Llevar baseline, resumen y comparación a D076; D074 apunta a esa solución |
| D074 `impact_items` | planning | A — IMPRESCINDIBLE V1 | Impacto explicable por entidad y fecha | Mantener; también representa `COMMUNICATION_RECOMMENDED` |
| D075 `scheduling_runs` | planning | D — CANDIDATA A FUSIÓN | Relación declarada 1:1 con D076 | Fusionar tiempos, algoritmo, input, hash y diagnósticos en D076; `POSIBLE_SOBREINGENIERIA` mientras no haya varias soluciones por run |
| D076 `schedule_solutions` | planning | A — IMPRESCINDIBLE V1 | Resultado contextual, reproducible e inmutable | Mantener ampliada con datos de run/comparación |
| D077 `operation_plan_results` | planning | A — IMPRESCINDIBLE V1 | Resultado y bloqueo explicable por operación | Mantener |
| D078 `phase_plan_results` | planning | A — IMPRESCINDIBLE V1 | Detalle por fase y revisión restante utilizada | Mantener |
| D079 `planned_phase_assignments` | planning | A — IMPRESCINDIBLE V1 | Asignación lógica de fase o batch | Mantener |
| D080 `assignment_segments` | planning | A — IMPRESCINDIBLE V1 | División entre jornadas y horas extra | Mantener |
| D081 `human_segment_assignments` | planning | A — IMPRESCINDIBLE V1 | Personas concretas por segmento | Mantener |
| D082 `physical_resource_reservations` | planning | A — IMPRESCINDIBLE V1 | Recursos concretos/capacidad por segmento | Mantener |
| D083 `physical_occupations` | planning | A — IMPRESCINDIBLE V1 | Ocupación continua separada del trabajo | Mantener sin simplificar |
| D084 `solution_milestones` | planning | A — IMPRESCINDIBLE V1 | Fechas estimadas comparables por solución | Mantener |

### 4.5 `execution`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D085 `operation_executions` | execution | A — IMPRESCINDIBLE V1 | Ejecución real y snapshot original | Mantener |
| D086 `execution_segments` | execution | A — IMPRESCINDIBLE V1 | Trabajo real inmutable por fase | Mantener; admitir segmentos tipados de pausa con trabajo cero |
| D087 `execution_pauses` | execution | D — CANDIDATA A FUSIÓN | La pausa pertenece a la misma línea temporal y no tiene relaciones propias adicionales | Fusionar en D086 mediante `segment_kind`, `reason` y regla `work_minutes=0` |
| D088 `actual_resource_usages` | execution | A — IMPRESCINDIBLE V1 | Personas/recursos reales distintos del plan | Mantener |
| D089 `remaining_estimate_revisions` | execution | A — IMPRESCINDIBLE V1 | Original, ejecutado, restante y total actualizado sin reescritura | Mantener sin simplificar |
| D090 `remaining_resource_estimates` | execution | A — IMPRESCINDIBLE V1 | Separa `LABOR_WORK`, `ACTIVE_PHYSICAL_USE` y `PHYSICAL_OCCUPATION` | Mantener sin simplificar |

### 4.6 `portal`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D091 `public_stage_definitions` | portal | A — IMPRESCINDIBLE V1 | Vocabulario público separado del interno | Mantener |
| D092 `public_stage_mapping_sets` | portal | B — CONVENIENTE V1 | Versiona la lógica interno→público | Mantener |
| D093 `public_stage_mapping_rules` | portal | B — CONVENIENTE V1 | Reglas consultables y validables sin JSON monolítico | Mantener |
| D094 `public_tracking_links` | portal | A — IMPRESCINDIBLE V1 | Token hash, revocación y rotación segura | Mantener |
| D095 `public_project_projections` | portal | A — IMPRESCINDIBLE V1 | Frontera allowlist entre datos internos y públicos | Mantener |
| D096 `public_timeline_entries` | portal | B — CONVENIENTE V1 | Historial publicable y moderado para el cliente | Mantener |
| D097 `communicated_dates` | portal | A — IMPRESCINDIBLE V1 | Fecha efectivamente comunicada, actor y canal | Mantener |
| D098 `communication_policies` | portal | C — DIFERIBLE | Una política configurable/versionada por tenant excede V1 | Usar columnas tipadas con calendario y umbral seguro en D001/D002; `POSIBLE_SOBREINGENIERIA` |
| D099 `communication_recommendations` | portal | C — DIFERIBLE | La recomendación ya es un impacto derivado del escenario | Usar D074 con tipo `COMMUNICATION_RECOMMENDED`; aprobación crea D097 y auditoría/outbox |
| D100 `public_publication_history` | portal | C — DIFERIBLE | Duplica proyección, timeline, fechas comunicadas y auditoría general | Diferir; auditar before/after público en D104; `POSIBLE_SOBREINGENIERIA` salvo requisito legal de snapshot exacto |

### 4.7 `integration`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D101 `inbox_messages` | integration | A — IMPRESCINDIBLE V1 | CA-24 exige idempotencia de eventos de Compras | Mantener aunque la conexión se active después; también sirve a importación manual/API |
| D102 `outbox_messages` | integration | B — CONVENIENTE V1 | Publicación y comunicación confiables sin acoplar transacciones externas | Mantener |

### 4.8 `audit`

| Tabla | Schema | Clasificación | Motivo | Acción recomendada |
|---|---|---|---|---|
| D103 `scenario_promotions` | audit | D — CANDIDATA A FUSIÓN | D069 ya contiene escenario, versión previa, revisiones, actor y momento; D104 conserva transacción | Eliminar cabecera especializada y registrar `SCENARIO_PROMOTED` en D104 dentro del mismo commit |
| D104 `audit_entries` | audit | A — IMPRESCINDIBLE V1 | Auditoría transversal de acciones sensibles | Mantener |

## 5. Sobreingeniería detectada

Se marcaron como `POSIBLE_SOBREINGENIERIA` únicamente estructuras cuya generalidad no está exigida por V1:

- roles y permisos configurables por organización;
- múltiples asignaciones/overlays de calendario por propietario;
- subtipo físico separado para instalación cuando ya es una operación planificable;
- detalle duplicado de cada cambio de `PlanningStateRevision`;
- catálogos tenant-configurables de eventos y motivos de excepción;
- múltiples programas publicados simultáneamente por planta;
- relación N:M entre escenario y eventos efectivos;
- cabeceras 1:1 de run, solución y análisis;
- políticas de comunicación versionadas y tabla propia de recomendaciones;
- snapshot histórico público adicional a timeline, fechas y auditoría.

No se consideran sobreingeniería las tablas de fases, requerimientos, segmentos, asignaciones humanas, reservas físicas, ocupaciones, estimación restante, recepción/asignación material, snapshots productivos o proyección pública. Cada una protege una distinción o cardinalidad real.

## 6. Simplificaciones propuestas y trazabilidad

### 6.1 Tablas a mantener

La opción B mantiene todas las clasificadas A o B: **87 tablas**. Las B permanecen porque, aunque exista una alternativa más austera, retirarlas introduciría JSON opaco, pérdida de integridad N:M, menor reproducibilidad o una migración futura desproporcionada. El inventario autoritativo es la clasificación de la sección 4.

### 6.2 Tablas candidatas a fusión

Se fusionan **15 tablas**: D004, D023–D026, D055, D056, D059, D063, D065, D068, D073, D075, D087 y D103. Su responsabilidad no desaparece: pasa a columnas tipadas, códigos de aplicación o historia autoritativa ya existente.

### 6.3 Tablas diferibles

Se difieren **5 tablas**: D062, D072 y D098–D100. No se crearán en las migraciones V1 si se aprueba la opción B. Sus casos quedan cubiertos mediante revisión/evento/auditoría, evento disparador directo, configuración tipada e impactos de escenario.

### 6.4 Impacto individual

| Tabla afectada | Cambio | Motivo y beneficio | Riesgo | Invariantes / casos | Reversibilidad futura |
|---|---|---|---|---|---|
| D004 | Fusionar en D005 | Roles V1 cerrados; una tabla y joins menos | Sin roles personalizados | INV-24; CA-22 | Alta: crear catálogo y migrar códigos |
| D023–D026 | Fusionar en D002/D012/D013/D017 | Un calendario base directo; configuración más simple | No soporta overlays/múltiples calendarios simultáneos | INV-09/19; CA-09/13/28 | Media: crear tablas y poblar desde punteros |
| D055 | Fusionar en D009 | Herrajes son estado 1:1 del lote | Futuras entregas de herrajes por componente exigirían entidad propia | INV-05/22; CA-25; CD-01 | Alta: extraer columnas a entidad |
| D056 | Fusionar en D036/D037/D040 | Instalación ya posee operación, fases, trabajo y equipo | Metadatos comerciales futuros del paquete requerirían extensión | INV-11; CA-11/12; CD-04/05 | Alta: crear subtipo desde operaciones categoría instalación |
| D059 | Fusionar en D064/D085–D088 | Progreso deriva de ejecución o evento explícito | Porcentaje manual necesita evento bien tipado | INV-18/39; portal | Alta: proyectar eventos existentes a nueva tabla |
| D062 | Diferir | Evita tercer historial de un mismo cambio | Menos consultas directas “qué revisión tocó esta entidad” | INV-33/37; CA-33 | Alta: poblar hacia adelante; historia anterior queda en eventos/audit |
| D063 | Fusionar en D064 | Códigos/payloads V1 son contrato de aplicación | Cambiar tipos sin deploy no será posible | INV-21/37; CA-24/39 | Alta: crear catálogo desde códigos observados |
| D065 | Fusionar en D066 | Motivos V1 cerrados y auditables | Sin administración tenant de motivos | INV-32 | Alta: crear catálogo y mapear códigos |
| D068 | Fusionar en D002/D060/D069/D070/D067 | Un plan publicado por planta; escenarios ya representan alternativas | Futuro multi-plan por planta requiere nuevo agregado y migración | INV-15/16/17/33/45; CA-15–17/44 | Media: crear plan y asociar historia por planta |
| D072 | Diferir | Base revision + evento disparador cubren V1 | No modela subconjuntos arbitrarios de eventos por escenario | INV-31/33; CA-33/34 | Alta: agregar puente cuando haya ese caso |
| D073 | Fusionar en D076 | Comparación 1:1 con run/solución | Múltiples análisis sobre una solución requerirán cabecera | CA-20/30/31/40/41 | Alta: separar columnas a cabecera |
| D075 | Fusionar en D076 | Run y solución son 1:1 por diseño actual | Varias soluciones por una corrida exigirán separación | INV-14/29/30; CA-21 | Media-alta: extraer datos de run conservando IDs |
| D087 | Fusionar en D086 | Una línea temporal tipada evita tabla paralela | Checks deben impedir confundir pausa con trabajo | INV-18/28/39; CA-43; CD-20 | Alta: separar filas `PAUSE` si fuera necesario |
| D098 | Diferir | Dos columnas tipadas cubren calendario/umbral V1 | Sin múltiples políticas históricas | INV-25; CA-31; CD-17 | Alta: crear política desde configuración vigente |
| D099 | Diferir | Recomendación es impacto del escenario; aprobación se evidencia al comunicar | No hay workflow autónomo de recomendaciones | INV-25; CA-31; UX-10 | Alta: migrar futuros impact items a workflow |
| D100 | Diferir | D095/D096/D097 + D104 ya dan historial suficiente | No existe snapshot público legal completo por publicación | INV-24; CA-22/23/36 | Media: historia exacta anterior dependerá de auditoría |
| D103 | Fusionar en D069/D104 | Elimina duplicación de promoción manteniendo transacción | Consultas de promociones requieren join plan/audit | INV-15/16; CA-16 | Alta: crear vista o tabla derivada |

Ninguna simplificación modifica D089 ni D090. Continúa siendo representable: original 10 h, ejecutado 7 h, restante 5 h y total actualizado 12 h, con dimensiones humana, uso físico activo y ocupación física independientes.

## 7. Análisis de los ocho schemas

| Schema | Decisión | Justificación |
|---|---|---|
| `core` | `MANTENER` | Define tenant, usuarios, clientes y agregados comerciales; facilita ownership y futura RLS |
| `capacity` | `MANTENER` | Aísla calendarios y recursos de la definición productiva; simplificar cuatro puentes no elimina el límite |
| `production` | `MANTENER` | Conserva rutas, operaciones, materiales, planos e instalación como verdad productiva |
| `planning` | `MANTENER` | Soluciones inmutables y escenarios requieren permisos y ciclo de vida propios |
| `execution` | `MANTENER` | Los hechos reales no deben mezclarse físicamente con reservas planificadas |
| `portal` | `MANTENER` | Es una frontera de seguridad; nunca debe exponer tablas internas directamente |
| `integration` | `MANTENER` | Inbox/outbox desacoplan Compras y entregas externas; no comparten tablas de negocio |
| `audit` | `MANTENER` | Permisos append-only y retención transversal justifican el límite aunque quede una tabla |

Reducir schemas no disminuye de forma material el costo de migraciones y sí debilita permisos, ownership y comprensión. La recomendación mantiene los ocho.

## 8. Integración con Compras

Las dos tablas de `integration` se conservan. D101 no obliga a implementar ahora la API de Compras: proporciona el punto idempotente necesario cuando se active y cubre CA-24. D102 permite que promociones, publicaciones públicas y futuras comunicaciones produzcan mensajes solo después del commit.

La aplicación de Compras seguirá siendo un bounded context independiente. Proveedor, pedido y recepción pertenecen a Producción solo como copia operativa mínima necesaria para planificar; nunca se comparten tablas entre aplicaciones.

## 9. Portal y auditoría

La opción pragmática conserva siete tablas del portal:

- definición y mapping público: D091–D093;
- link seguro: D094;
- proyección allowlist: D095;
- timeline visible: D096;
- fecha comunicada: D097.

Elimina tres historiales/workflows paralelos. El umbral de comunicación se configura mediante columnas tipadas en organización/planta; la recomendación vive como `impact_item` de escenario; aprobar crea una fecha comunicada y, si corresponde, outbox en una transacción auditada. D104 registra antes/después exclusivamente de la proyección pública, sin copiar datos internos sensibles.

La auditoría no reemplaza historia natural: ejecuciones, eventos, estimaciones restantes, versiones y fechas comunicadas siguen append-only. Solo evita repetir la misma promoción o publicación en una segunda tabla especializada cuando las claves autoritativas ya existen.

## 10. Opción A — Esquema completo

Mantiene las 107 tablas actuales.

Ventajas:

- soporta desde el inicio roles personalizados, overlays de calendario, múltiples planes y políticas de comunicación versionadas;
- permite consultas históricas especializadas sin depender de auditoría general;
- reduce migraciones futuras si esas capacidades se confirman;
- sus 45 invariantes y 44 casos ya tienen estrategia física documentada.

Costos y riesgos:

- más migraciones, repositorios, fixtures, permisos y pruebas antes de obtener valor operativo;
- más transacciones multi-tabla y más estados que mantener coherentes;
- mayor superficie para errores en una V1 con un único flujo real por cada abstracción;
- onboarding y soporte más difíciles;
- posibilidad de cristalizar contratos todavía no validados por uso.

No es un mal diseño; es una arquitectura objetivo más amplia que la primera entrega.

## 11. Opción B — Esquema V1 pragmático

Implementa 87 tablas: 66 imprescindibles y 21 convenientes. Fusiona o difiere 20 sin eliminar conceptos del modelo lógico.

Condiciones obligatorias:

1. una planta posee exactamente un plan publicado V1;
2. cada propietario posee como máximo un calendario base, complementado con excepciones, indisponibilidades y horas extra;
3. roles, tipos de evento y motivos de excepción usan códigos versionados en la aplicación;
4. instalación es una operación requerida tipada;
5. una corrida produce una solución y una comparación;
6. las recomendaciones de comunicación son impactos derivados y nunca envían ni publican sin una acción aprobada;
7. auditoría, eventos y versiones conservan las causas que reemplazan historiales auxiliares diferidos.

Ventajas:

- veinte tablas, veinte repositorios potenciales y varias coordinaciones transaccionales menos;
- modelo físico más cercano a los flujos que realmente usará la planta;
- conserva relaciones normalizadas donde existe cardinalidad o integridad real;
- permite recuperar cada capacidad diferida sin rediseñar el núcleo APS.

Riesgos:

- introducir roles personalizados, overlays de calendario o múltiples planes exigirá migraciones;
- algunas consultas históricas dependerán de eventos/auditoría en lugar de una tabla especializada;
- la fusión run/solución debe revisarse antes de admitir varias soluciones por corrida;
- las convenciones de códigos cerrados deben estar versionadas y probadas, no dispersas en la UI.

## 12. Comparación de complejidad

| Dimensión | Opción A — 107 | Opción B — 87 |
|---|---|---|
| Corrección APS V1 | Completa | Completa bajo las siete condiciones explícitas |
| Migraciones iniciales | Mayor | 20 tablas menos |
| Transacciones principales | Más cabeceras/puentes | Menos joins 1:1 y catálogos |
| Reprogramación | Soportada | Soportada con igual frontera de comandos |
| Trazabilidad | Especializada y redundante | Suficiente, repartida entre historia natural/evento/audit |
| Configuración avanzada | Disponible desde el inicio | Diferida hasta necesidad real |
| Multitenancy | Preparado | Preparado; `organization_id`, ownership y usuarios se conservan |
| Portal seguro | 10 tablas | 7 tablas, misma proyección pública separada |
| Integración Compras | Preparada | Igualmente preparada |
| Reversibilidad | No aplica | Alta en 16 cambios, media en 4; ninguna baja |

El ahorro no debe medirse solo por 20 tablas: reduce especialmente estados configurables y transacciones 1:1 que la V1 todavía no necesita.

## 13. Revalidación de las 45 invariantes

| Invariantes | Resultado en opción B | Ajuste de estrategia |
|---|---|---|
| INV-01–INV-05 | 5/5 preservadas | Proyecto/lote, rutas, precedencias y gates permanecen; herrajes 1:1 pasan a lote |
| INV-06–INV-13 | 8/8 preservadas | Asignaciones humanas, reservas, ocupaciones, calendarios, skills, equipo y resultados siguen separados |
| INV-14–INV-17 | 4/4 preservadas | Solución inmutable; Current por planta; promoción bloqueada; escenarios no escriben versiones |
| INV-18–INV-22 | 5/5 preservadas | Ejecución/eventos/materiales/inbox y gates permanecen; pausa tipada sigue append-only |
| INV-23–INV-25 | 3/3 preservadas | Link/proyección separados; comunicación solo desde aprobación que crea D097 + outbox/audit |
| INV-26–INV-32 | 7/7 preservadas | Fases, gates, ocupación, snapshots, hipótesis y excepciones siguen explícitos |
| INV-33–INV-37 | 5/5 preservadas | Head y revisiones conservan comparación O(1); detalles usan evento/audit; batches y mapping siguen versionados |
| INV-38–INV-45 | 8/8 preservadas | Original, ejecutado, restante, dimensiones, locks, escenarios y rechazo no cambian |

Cobertura formal: **45/45 preservadas**. Cambian mecanismos físicos de INV-09, INV-15/16, INV-25, INV-33 y INV-37, pero no su semántica.

## 14. Revalidación de casos y casos difíciles

### 14.1 Casos de aceptación

| Casos | Resultado | Observación |
|---|---|---|
| CA-01–CA-13 | 13/13 | Recursos, material, ocupación, instalación, calendario y horas extra permanecen normalizados |
| CA-14–CA-21 | 8/8 | Locks, escenarios, Current por planta, batches, explicación y hash reproducible permanecen |
| CA-22–CA-24 | 3/3 | Proyección/link e inbox idempotente se mantienen |
| CA-25–CA-29 | 5/5 | Fases, gates, simultaneidad, múltiples bancos y fuera de horizonte no se simplifican |
| CA-30–CA-36 | 7/7 | Hitos, ejecución de origen, staleness, hipótesis, snapshot y mapping permanecen; CA-31 usa impacto tipado + aprobación D097 |
| CA-37–CA-44 | 8/8 | D089/D090 y separación ejecución/solución se mantienen íntegramente |

Cobertura formal: **44/44 representables**.

### 14.2 Casos difíciles

| Casos difíciles | Resultado | Estructuras críticas conservadas |
|---|---|---|
| CD-01–CD-05 | 5/5 | Gate de herrajes, ocupación, bancos, equipo y ventanas de instalación |
| CD-06–CD-10 | 5/5 | Material allocation, inbox, route version, batch y out-of-horizon |
| CD-11–CD-15 | 5/5 | State revision, locks de promoción/ejecución, overtime y skill vigente |
| CD-16–CD-18 | 3/3 | Indisponibilidad, comparación con fecha comunicada y rotación de token |
| CD-19–CD-22 | 4/4 | Proyección separada, corrección append-only, timezone y commit atómico/auditado |

Cobertura formal: **22/22 preservados**.

## 15. Revalidación de UX y comandos de reprogramación

| Caso UX | Resultado en opción B | Soporte principal |
|---|---|---|
| UX-01 | SOPORTADO | D089/D090 → state revision → escenario/solución |
| UX-02 | SOPORTADO | Evento/finalización libera futuro solo en simulación |
| UX-03 | SOPORTADO | Hipótesis `MOVE_ACTIVITY` y reservas contextuales |
| UX-04 | SOPORTADO | Resultados, blocker e impact items |
| UX-05 | SOPORTADO | Precedencias, capacidad y múltiples impact items |
| UX-06 | SOPORTADO | Current por planta no cambia al cancelar |
| UX-07 | SOPORTADO | D069 + puntero Current + D104 en commit único |
| UX-08 | SOPORTADO | D085/D086/D088 inmutables; solo futuro recalculado |
| UX-09 | SOPORTADO | D083 y dimensión `PHYSICAL_OCCUPATION` de D090 |
| UX-10 | SOPORTADO | D084/D074 contra D097 antes de confirmar |

Cobertura UX: **10/10 soportados**.

| Comando | Resultado | Cambio interno respecto de 107 tablas |
|---|---|---|
| `UPDATE_REMAINING_ESTIMATE` | SOPORTADO | Igual; D089/D090 no cambian |
| `RESIZE_SCHEDULED_ACTIVITY` | SOPORTADO | Hipótesis y solución fusionada con run |
| `MOVE_SCHEDULED_ACTIVITY` | SOPORTADO | Igual frontera; calendarios base directos |
| `REPLAN_FROM_OPERATION` | SOPORTADO | Escenario por planta y cierre de impacto |
| `REPLAN_PROJECT` | SOPORTADO | Igual; impact items permanecen |
| `ACCEPT_REPLAN` | SOPORTADO | D069 + Current de planta + D104 reemplazan D068/D103 |
| `REJECT_REPLAN` | SOPORTADO | Estado del escenario; Current y restante efectivo intactos |

No se introduce manipulación técnica en la interfaz. El flujo continúa siendo:

> veo demora → modifico tiempo → sistema simula → veo impacto → confirmo

## 16. Recomendación final

Recomiendo aprobar la opción B y luego actualizar explícitamente los documentos 07 y 08 antes de escribir la primera migración. La reducción se concentra en generalización todavía no validada y duplicación física; no en reglas productivas.

El esquema completo debe conservarse como referencia de evolución, especialmente para roles personalizados, overlays de calendario, multi-plan, múltiples soluciones por run y workflow avanzado de comunicaciones.

Resultado de la reauditoría pragmática:

- 87 tablas V1;
- 8 schemas mantenidos;
- 45/45 invariantes preservadas;
- 44/44 casos de aceptación representables;
- 22/22 casos difíciles preservados;
- UX-01–UX-10 y 7/7 comandos soportados;
- **0 `BRECHA_ESQUEMA_FISICO`**.

**`SIMPLIFICAR_ESQUEMA_ANTES_DE_MIGRACIONES`**

Este documento es una propuesta. No modifica todavía el esquema físico aprobado ni autoriza SQL, migraciones, Supabase, backend, frontend o motor.
