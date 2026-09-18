# Diccionario de datos PostgreSQL V1 simplificado

## 1. Convenciones

Este diccionario es la definición física autoritativa de la V1 pragmática. Contiene **87 tablas en 8 schemas**. Los identificadores `Dnnn` se mantienen estables respecto del diseño anterior; los huecos son IDs retirados y su trazabilidad está en `docs/11-cierre-esquema-fisico-v1.md`.

Categorías de mutabilidad:

- `M`: mutable con control optimista, baja lógica o máquina de estados;
- `V`: versionada o con lifecycle controlado; la historia no se reescribe;
- `A`: append-only o inmutable después de insert/finalización.

Columnas comunes tenant-owned salvo indicación: `id uuid PK`, `organization_id uuid FK`, `created_at timestamptz`, `created_by uuid FK ?`, `updated_at timestamptz ?`, `row_version bigint` para `M`. Todas las FK entre entidades tenant-owned deben impedir referencias cruzadas mediante claves compuestas o validación equivalente. `tstzrange` usa límites `[)`.

Resumen:

| Schema | Tablas | M | V | A |
|---|---:|---:|---:|---:|
| `core` | 10 | 9 | 0 | 1 |
| `capacity` | 13 | 10 | 2 | 1 |
| `production` | 31 | 15 | 12 | 4 |
| `planning` | 18 | 2 | 4 | 12 |
| `execution` | 5 | 0 | 2 | 3 |
| `portal` | 7 | 2 | 4 | 1 |
| `integration` | 2 | 2 | 0 | 0 |
| `audit` | 1 | 0 | 0 | 1 |
| **Total** | **87** | **40** | **24** | **23** |

## 2. Schema `core` — 10 tablas

### D001 `core.organizations` — M

`slug text UQ`; `legal_name text`; `display_name text`; `default_timezone text`; `status text`; `settings jsonb = {}`. Slug normalizado; timezone IANA validada; baja lógica.

### D002 `core.plants` — M

`code text`; `name text`; `timezone text`; `base_calendar_id uuid FK capacity.calendars`; `communication_calendar_id uuid FK capacity.calendars ?`; `communication_threshold_business_days smallint = 1`; `current_product_definition_revision_id uuid FK production.product_definition_revisions ?`; `current_plan_version_id uuid FK planning.plan_versions ?`; `promotion_lock_version bigint = 1`; `settings jsonb = {}`. UQ organización/código; calendarios de la misma organización; umbral no negativo; punteros de la misma planta.

### D003 `core.user_profiles` — M

`auth_subject text UQ`; `display_name text`; `email text ?`; `status text`; `last_seen_at timestamptz ?`. Referencia identidad externa; nunca password propio.

### D005 `core.user_roles` — M

`user_profile_id uuid FK`; `role_code text`; `plant_id uuid FK ?`; `valid_during daterange`; `assigned_by uuid FK`. Roles V1 cerrados y permisos definidos por allowlist de aplicación; no solapar la misma asignación usuario/rol/planta.

### D006 `core.customers` — M

`code text ?`; `display_name text`; `email text ?`; `phone text ?`; `notes text ?`; `privacy_metadata jsonb = {}`. UQ de código cuando exista; datos personales fuera de snapshots públicos.

### D007 `core.project_priorities` — M

`code text`; `name text`; `rank smallint > 0`; `color text ?`; `is_default boolean = false`. UQ organización/código y organización/rank; un default parcial por organización.

### D008 `core.projects` — M

`plant_id uuid FK`; `customer_id uuid FK`; `code text`; `name text`; `description text ?`; `commercial_owner_id uuid FK ?`; `priority_id uuid FK`; `status text`; `accepted_on date ?`; `desired_start_at timestamptz ?`; `committed_date date ?`; `closed_at timestamptz ?`. UQ organización/código.

### D009 `core.project_lots` — M

`project_id uuid FK`; `code text`; `name text`; `description text ?`; `sequence_no smallint`; `quantity numeric(14,4) ?`; `unit text ?`; `status text`; `hardware_status text`; `hardware_available_at timestamptz ?`; `hardware_source_event_id uuid FK planning.effective_events ?`. UQ proyecto/código y proyecto/secuencia. El estado de herrajes 1:1 vive en el lote.

### D010 `core.milestone_definitions` — M

`code text`; `name text`; `category text`; `sequence_no smallint`; `is_system boolean = false`. UQ organización/código.

### D011 `core.project_milestones` — A

`project_id uuid FK`; `milestone_definition_id uuid FK`; `occurred_at timestamptz`; `source_event_id uuid FK ?`; `notes text ?`; `supersedes_id uuid FK self ?`. Hechos reales corregidos por superseding.

## 3. Schema `capacity` — 13 tablas

### D012 `capacity.work_centers` — M

`plant_id uuid FK`; `code text`; `name text`; `capacity_mode text`; `aggregate_capacity numeric(12,4) ?`; `capacity_unit text ?`; `base_calendar_id uuid FK calendars ?`. UQ planta/código; capacidad positiva cuando aplique.

### D013 `capacity.employees` — M

`plant_id uuid FK`; `code text`; `display_name text`; `user_profile_id uuid FK ?`; `status text`; `default_work_center_id uuid FK ?`; `base_calendar_id uuid FK calendars`; `metadata jsonb = {}`. UQ planta/código y user_profile cuando exista.

### D014 `capacity.skills` — M

`code text`; `name text`; `description text ?`; `category text ?`. UQ organización/código.

### D015 `capacity.employee_skills` — V

`employee_id uuid FK`; `skill_id uuid FK`; `valid_during daterange`; `level numeric(6,3) ?`; `enabled boolean = true`; `approved_by uuid FK ?`. EXCLUDE empleado/skill/vigencia para filas habilitadas.

### D016 `capacity.physical_resource_types` — M

`code text`; `name text`; `resource_kind text`; `default_scheduling_mode text`; `default_capacity_unit text ?`. UQ organización/código. Tipifica máquina, banco u otro recurso sin nombres hardcodeados.

### D017 `capacity.physical_resources` — M

`plant_id uuid FK`; `work_center_id uuid FK`; `resource_type_id uuid FK`; `code text`; `name text`; `scheduling_mode text`; `capacity_units numeric(12,4)`; `capacity_unit text ?`; `status text`; `is_mobile boolean = false`; `base_calendar_id uuid FK calendars`. UQ planta/código; capacidad positiva.

### D018 `capacity.physical_resource_groups` — M

`plant_id uuid FK`; `code text`; `name text`; `selection_policy text`; `description text ?`. UQ planta/código.

### D019 `capacity.physical_resource_group_members` — M

`group_id uuid FK`; `physical_resource_id uuid FK`; `valid_during daterange`; `priority smallint ?`. UQ grupo/recurso/vigencia; misma planta.

### D020 `capacity.calendars` — M

`code text`; `name text`; `timezone text`; `calendar_kind text`; `description text ?`. UQ organización/código.

### D021 `capacity.calendar_working_intervals` — M

`calendar_id uuid FK`; `weekday smallint 1..7`; `local_start time`; `local_end time`; `shift_code text ?`; `capacity_factor numeric(12,6) = 1`; `valid_during daterange`. Start menor que end; factor positivo; no solapamiento ambiguo por servicio.

### D022 `capacity.calendar_exceptions` — M

`calendar_id uuid FK`; `exception_date date`; `time_range tstzrange ?`; `effect text`; `capacity_factor numeric(12,6) ?`; `reason text ?`. Efecto `add/remove/replace`; rango válido.

### D027 `capacity.resource_unavailabilities` — A

`employee_id uuid FK ?`; `physical_resource_id uuid FK ?`; `time_range tstzrange`; `reason_code text`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. Exactamente un owner; rango válido; GiST por owner/rango.

### D028 `capacity.overtime_authorizations` — V

`plant_id uuid FK`; `project_id uuid FK ?`; `scenario_id uuid FK ?`; `employee_id uuid FK ?`; `physical_resource_id uuid FK ?`; `work_center_id uuid FK ?`; `time_range tstzrange`; `max_minutes bigint ?`; `approved_by uuid FK`; `reason text`; `revoked_at timestamptz ?`; `revoked_by uuid FK ?`. Al menos un scope; autorización no es reserva.

## 4. Schema `production` — 31 tablas

### D029 `production.operation_definitions` — M

`code text`; `name text`; `category text`; `default_estimate_unit text`; `default_split_policy text`; `description text ?`; `is_system boolean = false`. UQ organización/código.

### D030 `production.route_templates` — M

`code text`; `name text`; `description text ?`; `status text`. UQ organización/código.

### D031 `production.route_versions` — V

`route_template_id uuid FK`; `version_no bigint`; `status text`; `published_at timestamptz ?`; `published_by uuid FK ?`; `supersedes_id uuid FK self ?`; `notes text ?`. UQ template/versión; inmutable publicada.

### D032 `production.route_steps` — V

`route_version_id uuid FK`; `operation_definition_id uuid FK`; `code text`; `name text`; `sequence_hint smallint ?`; `settings jsonb = {}`. UQ versión/código; composición inmutable cuando la versión se publica.

### D033 `production.route_step_phase_templates` — V

`route_step_id uuid FK`; `sequence_no smallint`; `code text`; `name text`; `estimate_kind text`; `original_estimate_minutes bigint`; `split_policy text`; `min_team smallint ?`; `max_team smallint ?`; `settings jsonb = {}`. UQ paso/secuencia y paso/código; valores no negativos.

### D034 `production.route_step_precedences` — V

`route_version_id uuid FK`; `predecessor_step_id uuid FK`; `successor_step_id uuid FK`; `precedence_type text = finish_start`; `lag_minutes bigint = 0`. UQ arista; no self; DAG al publicar.

### D035 `production.lot_route_assignments` — V

`project_lot_id uuid FK`; `route_version_id uuid FK`; `valid_during tstzrange`; `is_active boolean`; `assigned_by uuid FK`; `reason text ?`. Un activo parcial por lote.

### D036 `production.required_operations` — M

`project_id uuid FK`; `project_lot_id uuid FK ?`; `operation_definition_id uuid FK`; `route_step_id uuid FK ?`; `operation_kind text`; `code text`; `name text`; `status text`; `earliest_start_at timestamptz ?`; `cancelled_at timestamptz ?`; `settings jsonb = {}`. `operation_kind` incluye `production` e `installation`; UQ proyecto/lote/código.

### D037 `production.required_operation_phases` — M

`required_operation_id uuid FK`; `route_step_phase_template_id uuid FK ?`; `sequence_no smallint`; `code text`; `name text`; `estimate_kind text`; `original_estimate_minutes bigint`; `split_policy text`; `status text`; `earliest_start_at timestamptz ?`. UQ operación/secuencia/código; mínimo una fase al publicar.

### D038 `production.operation_precedences` — M

`predecessor_operation_id uuid FK`; `successor_operation_id uuid FK`; `precedence_type text`; `lag_minutes bigint = 0`; `source text`; `active boolean = true`. UQ arista activa; no self; DAG validado.

### D039 `production.operation_gates` — M

`required_operation_id uuid FK`; `required_operation_phase_id uuid FK ?`; `timing text`; `gate_type text`; `material_requirement_id uuid FK ?`; `drawing_package_id uuid FK ?`; `hardware_project_lot_id uuid FK ?`; `milestone_definition_id uuid FK ?`; `available_at timestamptz ?`; `config jsonb = {}`. Target exactamente uno según tipo. Un gate de herrajes puede aplicarse antes de una fase de terminación sin bloquear prearmado.

### D040 `production.operation_labor_requirements` — M

`required_operation_phase_id uuid FK`; `skill_id uuid FK`; `min_people smallint`; `max_people smallint`; `work_minutes bigint`; `productivity_curve jsonb`; `is_mandatory boolean = true`. `1 ≤ min ≤ max`; trabajo no negativo.

### D041 `production.operation_physical_requirements` — M

`required_operation_phase_id uuid FK`; `physical_resource_type_id uuid FK ?`; `physical_resource_group_id uuid FK ?`; `work_center_id uuid FK ?`; `quantity numeric(12,4)`; `capacity_units numeric(12,4)`; `is_mandatory boolean = true`; `usage_mode text`. Al menos un selector; valores positivos.

### D042 `production.product_definition_revisions` — A

`plant_id uuid FK`; `revision_no bigint`; `parent_revision_id uuid FK self ?`; `source_scenario_id uuid FK ?`; `snapshot_schema_version smallint`; `canonicalization_version smallint`; `canonical_snapshot jsonb`; `snapshot_sha256 bytea`; `reason text ?`. UQ planta/revisión y planta/hash; hash de 32 bytes; absolutamente inmutable.

### D043 `production.production_batches` — M

`plant_id uuid FK`; `code text`; `name text`; `operation_definition_id uuid FK`; `status text`; `description text ?`. UQ planta/código.

### D044 `production.production_batch_versions` — V

`production_batch_id uuid FK`; `version_no bigint`; `status text`; `manual_estimate_minutes bigint`; `published_at timestamptz ?`; `published_by uuid FK ?`; `supersedes_id uuid FK self ?`. UQ batch/versión; publicada inmutable.

### D045 `production.production_batch_members` — V

`production_batch_version_id uuid FK`; `required_operation_phase_id uuid FK`; `allocation_factor numeric(12,6) ?`; `sequence_hint smallint ?`. UQ versión/fase; factor positivo.

### D046 `production.suppliers` — M

`code text`; `name text`; `external_reference text ?`; `source_system text = production`; `status text`; `contact jsonb = {}`. UQ organización/código y fuente/referencia cuando exista.

### D047 `production.material_requirements` — M

`project_lot_id uuid FK`; `code text`; `description text`; `required_quantity numeric(14,4)`; `unit text`; `is_mandatory boolean`; `needed_at timestamptz ?`; `status text`. UQ lote/código; cantidad positiva.

### D048 `production.supplier_orders` — M

`supplier_id uuid FK`; `project_id uuid FK ?`; `order_number text ?`; `status text`; `ordered_at timestamptz ?`; `promised_at timestamptz ?`; `source_system text`; `external_reference text ?`; `revision bigint = 1`. UQ fuente/referencia cuando exista.

### D049 `production.supplier_order_lines` — M

`supplier_order_id uuid FK`; `line_no smallint`; `material_code text`; `description text`; `ordered_quantity numeric(14,4)`; `unit text`; `promised_at timestamptz ?`. UQ orden/línea; cantidad positiva.

### D050 `production.supplier_deliveries` — A

`supplier_order_id uuid FK ?`; `supplier_id uuid FK`; `delivered_at timestamptz`; `delivery_kind text`; `source_system text`; `external_reference text ?`; `effective_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. UQ externa; hecho/compensación.

### D051 `production.supplier_delivery_lines` — A

`supplier_delivery_id uuid FK`; `supplier_order_line_id uuid FK ?`; `line_no smallint`; `material_code text`; `quantity numeric(14,4)`; `unit text`; `movement_sign smallint IN (-1,1)`. UQ entrega/línea; cantidad positiva.

### D052 `production.material_allocations` — A

`supplier_delivery_line_id uuid FK`; `material_requirement_id uuid FK`; `quantity numeric(14,4)`; `unit text`; `movement_sign smallint`; `supersedes_id uuid FK self ?`. Suma neta transaccional; no update/delete.

### D053 `production.drawing_packages` — M

`project_lot_id uuid FK`; `code text`; `name text`; `status text`; `required boolean = true`. UQ lote/código.

### D054 `production.drawing_releases` — V

`drawing_package_id uuid FK`; `release_no bigint`; `status text`; `released_at timestamptz ?`; `released_by uuid FK ?`; `document_reference text ?`; `supersedes_id uuid FK self ?`; `effective_event_id uuid FK ?`. UQ paquete/release; publicada inmutable.

### D057 `production.installation_lot_coverages` — M

`installation_operation_id uuid FK required_operations`; `project_lot_id uuid FK`; `coverage_percent numeric(5,2) ?`. La operación debe tener `operation_kind=installation`; UQ operación/lote; porcentaje 0–100.

### D058 `production.customer_availability_windows` — V

`installation_operation_id uuid FK required_operations`; `time_range tstzrange`; `mandatory boolean = true`; `source text`; `notes text ?`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. Operación de instalación; rango no vacío; GiST.

### D105 `production.route_phase_labor_requirement_templates` — V

`route_step_phase_template_id uuid FK`; `skill_id uuid FK`; `min_people smallint`; `max_people smallint`; `work_minutes bigint`; `productivity_curve jsonb`; `is_mandatory boolean = true`. `1 ≤ min ≤ max`; trabajo no negativo.

### D106 `production.route_phase_physical_requirement_templates` — V

`route_step_phase_template_id uuid FK`; `physical_resource_type_id uuid FK ?`; `physical_resource_group_id uuid FK ?`; `work_center_id uuid FK ?`; `quantity numeric(12,4)`; `capacity_units numeric(12,4)`; `usage_mode text`; `is_mandatory boolean = true`. Al menos un selector; valores positivos.

### D107 `production.route_phase_gate_templates` — V

`route_step_phase_template_id uuid FK`; `timing text`; `gate_type text`; `target_kind text`; `parameters jsonb = {}`; `is_mandatory boolean = true`. Predicado tipado e instanciable como D039.

## 5. Schema `planning` — 18 tablas

### D060 `planning.planning_state_heads` — M

`plant_id uuid PK/FK`; `organization_id uuid FK`; `current_revision_id uuid FK planning_state_revisions`; `current_revision_no bigint`; `row_version bigint = 1`; `updated_at timestamptz`; `updated_by uuid FK ?`. Una fila por planta; lock `FOR UPDATE`.

### D061 `planning.planning_state_revisions` — A

`plant_id uuid FK`; `revision_no bigint`; `reason text`; `trigger_event_id uuid FK effective_events ?`; `transaction_key uuid`; `change_summary jsonb = {}`. UQ planta/revisión y transaction_key; append-only. El resumen no sustituye eventos/auditoría.

### D064 `planning.effective_events` — A

`plant_id uuid FK`; `event_type_code text`; `payload_schema_version smallint`; `occurred_at timestamptz`; `effective_at timestamptz`; `entity_type text`; `entity_id uuid`; `payload jsonb`; `cause text ?`; `planning_state_revision_id uuid FK ?`; `source_system text`; `external_reference text ?`; `supersedes_id uuid FK self ?`. Tipos/payloads allowlist de aplicación; UQ fuente/referencia.

### D066 `planning.manual_exceptions` — V

`plant_id uuid FK`; `reason_code text`; `reason_text text`; `scenario_id uuid FK ?`; `project_id uuid FK ?`; `required_operation_id uuid FK ?`; `required_operation_phase_id uuid FK ?`; `employee_id uuid FK ?`; `physical_resource_id uuid FK ?`; `work_center_id uuid FK ?`; `time_range tstzrange ?`; `exception_kind text`; `parameters jsonb`; `approved_by uuid FK`; `approved_at timestamptz`; `revoked_at timestamptz ?`; `revoked_by uuid FK ?`; `source_hypothesis_id uuid FK ?`. Al menos un scope; códigos y aprobaciones validados por aplicación.

### D067 `planning.planning_locks` — V

`plant_id uuid FK`; `required_operation_id uuid FK ?`; `required_operation_phase_id uuid FK ?`; `plan_version_id uuid FK ?`; `assignment_segment_id uuid FK ?`; `employee_id uuid FK ?`; `physical_resource_id uuid FK ?`; `lock_scope text`; `valid_during tstzrange ?`; `reason text`; `source_execution_id uuid FK ?`; `released_at timestamptz ?`; `released_by uuid FK ?`. Scope coherente; historia conservada.

### D069 `planning.plan_versions` — A

`plant_id uuid FK`; `version_no bigint`; `schedule_solution_id uuid FK`; `product_definition_revision_id uuid FK`; `planning_state_revision_id uuid FK`; `previous_version_id uuid FK self ?`; `source_scenario_id uuid FK`; `status text`; `valid_during tstzrange`; `confirmed_at timestamptz`; `confirmed_by uuid FK`; `reason text ?`. UQ planta/versión; EXCLUDE planta/vigencia; inmutable.

### D070 `planning.scenarios` — M

`plant_id uuid FK`; `scenario_kind text`; `base_plan_version_id uuid FK ?`; `base_state_revision_id uuid FK`; `base_product_definition_revision_id uuid FK`; `trigger_event_id uuid FK ?`; `code text`; `name text`; `status text`; `horizon_days smallint = 90`; `horizon_range tstzrange`; `parameters jsonb = {}`; `requested_by uuid FK`; `started_at timestamptz ?`; `completed_at timestamptz ?`; `rejected_at timestamptz ?`; `rejection_reason text ?`. UQ planta/código; base plan null solo para bootstrap `initial`.

### D071 `planning.simulation_hypotheses` — A

`scenario_id uuid FK`; `hypothesis_no smallint`; `hypothesis_type text`; `target_type text`; `target_id uuid ?`; `parameters jsonb`; `description text`; `source_revision_id uuid FK ?`; `source_event_id uuid FK ?`; `materialized_exception_id uuid FK ?`; `materialized_event_id uuid FK ?`. UQ escenario/número; no modifica estado real.

### D074 `planning.impact_items` — A

`schedule_solution_id uuid FK`; `project_id uuid FK ?`; `required_operation_id uuid FK ?`; `required_operation_phase_id uuid FK ?`; `employee_id uuid FK ?`; `physical_resource_id uuid FK ?`; `milestone_definition_id uuid FK ?`; `impact_kind text`; `delta_minutes bigint ?`; `old_value jsonb ?`; `new_value jsonb ?`; `reason jsonb`. Al menos un target. `COMMUNICATION_RECOMMENDED` es un impacto; aprobarlo crea D097, auditoría y outbox.

### D076 `planning.schedule_solutions` — V

`scenario_id uuid FK`; `run_no bigint`; `status text`; `algorithm_version text`; `input_product_definition_revision_id uuid FK`; `base_state_revision_id uuid FK`; `input_snapshot jsonb`; `input_sha256 bytea`; `parameters jsonb`; `started_at timestamptz`; `finished_at timestamptz ?`; `diagnostics jsonb = {}`; `horizon_range tstzrange`; `solution_sha256 bytea ?`; `metrics jsonb = {}`; `ready_at timestamptz ?`; `failed_reason text ?`; `baseline_solution_id uuid FK self ?`; `impact_summary jsonb = {}`; `comparison jsonb = {}`. UQ escenario/run; hash de 32 bytes; una fila representa run, solución y análisis final; inmutable al quedar `ready/failed`.

### D077 `planning.operation_plan_results` — A

`schedule_solution_id uuid FK`; `required_operation_id uuid FK`; `result_status text`; `planned_start_at timestamptz ?`; `planned_end_at timestamptz ?`; `remaining_work_minutes bigint ?`; `explanation jsonb`; `critical_resource_id uuid FK ?`; `blocker_assignment_id uuid FK planned_phase_assignments ?`. UQ solución/operación.

### D078 `planning.phase_plan_results` — A

`operation_plan_result_id uuid FK`; `schedule_solution_id uuid FK`; `required_operation_phase_id uuid FK`; `result_status text`; `remaining_estimate_revision_id uuid FK execution.remaining_estimate_revisions ?`; `shared_assignment_id uuid FK planned_phase_assignments ?`; `planned_work_minutes bigint ?`; `remaining_work_minutes bigint ?`; `explanation jsonb`. UQ solución/fase.

### D079 `planning.planned_phase_assignments` — A

`phase_plan_result_id uuid FK ?`; `production_batch_version_id uuid FK ?`; `schedule_solution_id uuid FK`; `assignment_kind text`; `planned_start_at timestamptz`; `planned_end_at timestamptz`; `work_minutes bigint`; `status text`. Exactamente phase result o batch version; rango derivado válido.

### D080 `planning.assignment_segments` — A

`planned_phase_assignment_id uuid FK`; `schedule_solution_id uuid FK`; `segment_no smallint`; `time_range tstzrange`; `normal_minutes bigint`; `overtime_minutes bigint = 0`; `work_minutes bigint`; `status text`. UQ asignación/segmento; minutos no negativos.

### D081 `planning.human_segment_assignments` — A

`assignment_segment_id uuid FK`; `schedule_solution_id uuid FK`; `employee_id uuid FK`; `time_range tstzrange`; `normal_minutes bigint`; `overtime_minutes bigint`; `work_minutes bigint`; `overtime_authorization_id uuid FK ?`; `exclusive_guard boolean = true`. UQ segmento/persona; EXCLUDE solución/persona/rango.

### D082 `planning.physical_resource_reservations` — A

`assignment_segment_id uuid FK`; `schedule_solution_id uuid FK`; `physical_resource_id uuid FK`; `time_range tstzrange`; `capacity_units numeric(12,4)`; `exclusive_guard boolean`; `usage_mode text`; `overtime_authorization_id uuid FK ?`. UQ segmento/recurso; EXCLUDE parcial solución/recurso/rango para exclusivos.

### D083 `planning.physical_occupations` — V

`schedule_solution_id uuid FK ?`; `operation_execution_id uuid FK ?`; `project_lot_id uuid FK`; `required_operation_phase_id uuid FK ?`; `physical_resource_id uuid FK`; `source_kind text`; `time_range tstzrange`; `planned_release_at timestamptz ?`; `actual_released_at timestamptz ?`; `release_event_id uuid FK ?`; `supersedes_id uuid FK self ?`; `is_effective boolean`. Exactamente solución o ejecución según fuente; EXCLUDE contextual para plan y exclusivo global para ocupación real efectiva.

### D084 `planning.solution_milestones` — A

`schedule_solution_id uuid FK`; `project_id uuid FK`; `milestone_definition_id uuid FK`; `estimated_at timestamptz`; `critical_path jsonb ?`; `confidence_metadata jsonb = {}`. UQ solución/proyecto/hito.

## 6. Schema `execution` — 5 tablas

### D085 `execution.operation_executions` — V

`required_operation_id uuid FK`; `source_product_definition_revision_id uuid FK`; `original_estimate_snapshot jsonb`; `status text`; `origin_plan_version_id uuid FK ?`; `origin_operation_plan_result_id uuid FK ?`; `started_at timestamptz ?`; `paused_at timestamptz ?`; `completed_at timestamptz ?`; `cancelled_at timestamptz ?`; `remaining_state text ?`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. Definición y estimación original congeladas.

### D086 `execution.execution_segments` — A

`operation_execution_id uuid FK`; `required_operation_phase_id uuid FK ?`; `origin_assignment_segment_id uuid FK ?`; `segment_no bigint`; `time_range tstzrange`; `segment_kind text`; `work_minutes bigint`; `reason text ?`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. UQ ejecución/segmento. `WORK` exige fase y trabajo no negativo; `PAUSE` exige trabajo cero y motivo. Corrección por superseding.

### D088 `execution.actual_resource_usages` — A

`execution_segment_id uuid FK`; `employee_id uuid FK ?`; `physical_resource_id uuid FK ?`; `time_range tstzrange`; `work_minutes bigint`; `capacity_units numeric(12,4) ?`; `usage_kind text`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. Exactamente persona o recurso; solo segmento `WORK`.

### D089 `execution.remaining_estimate_revisions` — V

`operation_execution_id uuid FK`; `revision_no bigint`; `previous_revision_id uuid FK self ?`; `cutoff_at timestamptz`; `input_mode text`; `raw_input jsonb`; `reason text ?`; `effective_event_id uuid FK`; `planning_state_revision_id uuid FK`; `executed_labor_minutes_at_cutoff bigint`; `remaining_labor_minutes bigint`; `updated_total_labor_minutes bigint`; `superseded_at timestamptz ?`; `superseded_by_id uuid FK self ?`. UQ ejecución/revisión; único parcial vigente; valores no negativos. Original nunca se modifica.

### D090 `execution.remaining_resource_estimates` — A

`remaining_estimate_revision_id uuid FK`; `required_operation_phase_id uuid FK`; `dimension text`; `skill_id uuid FK ?`; `min_people smallint ?`; `max_people smallint ?`; `physical_requirement_id uuid FK ?`; `physical_resource_id uuid FK ?`; `remaining_minutes bigint ?`; `expected_release_at timestamptz ?`; `capacity_units numeric(12,4) ?`; `details jsonb = {}`. Columnas coherentes con `LABOR_WORK`, `ACTIVE_PHYSICAL_USE` o `PHYSICAL_OCCUPATION`.

## 7. Schema `portal` — 7 tablas

### D091 `portal.public_stage_definitions` — M

`code text`; `name text`; `sequence_no smallint`; `default_weight numeric(12,6) ?`; `display_copy jsonb`; `is_final boolean = false`. UQ organización/código/secuencia.

### D092 `portal.public_stage_mapping_sets` — V

`code text`; `version_no bigint`; `status text`; `published_at timestamptz ?`; `published_by uuid FK ?`; `supersedes_id uuid FK self ?`; `description text ?`. UQ organización/código/versión; publicada inmutable.

### D093 `portal.public_stage_mapping_rules` — V

`mapping_set_id uuid FK`; `rule_no smallint`; `public_stage_definition_id uuid FK`; `predicate_type text`; `predicate jsonb`; `priority smallint`; `stop_on_match boolean = true`. UQ set/regla y set/prioridad; predicados allowlist.

### D094 `portal.public_tracking_links` — V

`project_id uuid FK`; `token_hash bytea`; `status text`; `activated_at timestamptz`; `expires_at timestamptz ?`; `revoked_at timestamptz ?`; `revoked_by uuid FK ?`; `replaced_by_id uuid FK self ?`; `last_accessed_at timestamptz ?`. Hash 32 bytes; UQ hash y único parcial activo por proyecto.

### D095 `portal.public_project_projections` — M

`project_id uuid UQ FK`; `source_plan_version_id uuid FK ?`; `mapping_set_id uuid FK`; `mapping_rule_id uuid FK`; `public_stage_id uuid FK`; `display_name text`; `progress_percent numeric(5,2) ?`; `installation_percent numeric(5,2) ?`; `communicated_date date ?`; `public_notice text ?`; `allowed_payload jsonb`; `published_at timestamptz`; `published_by uuid FK`. Proyección allowlist; porcentajes 0–100; privilegios separados de tablas internas.

### D096 `portal.public_timeline_entries` — V

`project_id uuid FK`; `occurred_at timestamptz`; `title text`; `body text ?`; `public_stage_id uuid FK ?`; `visibility_status text`; `published_at timestamptz ?`; `published_by uuid FK ?`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. Publicación explícita; nunca copia payload interno completo.

### D097 `portal.communicated_dates` — A

`project_id uuid FK`; `date_kind text`; `communicated_date date`; `source_plan_version_id uuid FK ?`; `approved_by uuid FK`; `communicated_at timestamptz`; `channel text ?`; `supersedes_id uuid FK self ?`; `reason text ?`. Historia append-only; última efectiva mediante view. Una recomendación se deriva en D074 y no envía nada por sí misma.

## 8. Schema `integration` — 2 tablas

### D101 `integration.inbox_messages` — M técnico

`source_system text`; `idempotency_key text`; `message_type text`; `message_schema_version smallint`; `received_at timestamptz`; `payload jsonb`; `payload_sha256 bytea`; `status text`; `processed_at timestamptz ?`; `error jsonb ?`; `retry_count integer = 0`. UQ fuente/idempotencia; payload inmutable; solo estado técnico actualizable.

### D102 `integration.outbox_messages` — M técnico

`aggregate_type text`; `aggregate_id uuid`; `event_type text`; `event_schema_version smallint`; `logical_key text`; `payload jsonb`; `occurred_at timestamptz`; `available_at timestamptz`; `status text`; `published_at timestamptz ?`; `retry_count integer = 0`; `last_error jsonb ?`. UQ organización/logical_key; payload inmutable; índice parcial pendientes.

## 9. Schema `audit` — 1 tabla

### D104 `audit.audit_entries` — A

`actor_user_id uuid FK ?`; `action_code text`; `entity_type text`; `entity_id uuid`; `occurred_at timestamptz`; `request_id uuid ?`; `transaction_key uuid ?`; `before_data jsonb ?`; `after_data jsonb ?`; `metadata jsonb = {}`; `source_event_id uuid FK ?`; `supersedes_id uuid FK self ?`. Append-only; datos sensibles minimizados. La promoción registra `SCENARIO_PROMOTED` con versión previa/nueva y revisiones dentro del mismo commit.

## 10. Totales físicos

- Schemas: **8**.
- Tablas: **87**.
- Mutables/técnicas/proyecciones (`M`): **40**.
- Versionadas o de lifecycle controlado (`V`): **24**.
- Append-only/inmutables (`A`): **23**.
- Constraints relevantes documentadas en el esquema físico: **68**, sin contar PK/FK/NOT NULL básicos.
- Familias de índices secundarios explícitos: **28**, además de índices creados por PK, UNIQUE y EXCLUDE.

No existen tablas activas para roles configurables, asignaciones de calendario, estado separado de herrajes, paquete/progreso separado de instalación, detalle auxiliar de revisión, catálogos de evento/excepción, contenedor de plan, puente escenario/evento, cabeceras separadas de impacto/run, pausas separadas, workflow especializado de comunicación/publicación o promoción especializada.
