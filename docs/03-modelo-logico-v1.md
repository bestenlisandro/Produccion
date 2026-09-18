# Modelo lógico de datos V1

Estado: propuesta para revisión previa a migraciones y código de persistencia.

## 1. Objetivo y límites

El modelo soporta configuración, planificación, simulación, publicación, ejecución y seguimiento público. No define todavía tablas físicas, tipos SQL, índices finales ni contratos HTTP.

La separación central es:

```text
Proyecto -> Lote -> Operación requerida -> Fase requerida
                                            |
                                            v
                                  Solución de programación
                                            |
                                            v
                              Asignación de fase + segmentos
                         |
            +------------+------------+
            |                         |
     Personas asignadas       Recursos físicos reservados
                                      |
                              Ocupación física continua
```

Una operación requerida describe **qué debe hacerse**. Sus fases describen las partes de trabajo planificables sin convertirlas en operaciones comerciales independientes. Una asignación de fase describe **cuándo y con qué recursos se propone realizar ese trabajo** dentro de una solución. Una simulación y un plan vigente pueden contener asignaciones diferentes para la misma definición productiva congelada sin modificarla.

## 2. Convenciones

- Identificadores internos opacos y estables.
- Fechas con zona horaria; zona inicial `America/Buenos_Aires`.
- Duraciones y trabajo almacenados en minutos enteros.
- Catálogos configurables en lugar de enums hardcodeados cuando el negocio pueda ampliarlos.
- Estados técnicos finitos sí pueden implementarse como enums controlados.
- Registros históricos y soluciones publicadas son inmutables.
- Las entidades integrables incluyen `source_system` y `external_reference`.
- Los nombres Daniel, Maximiliano y Lisandro son datos iniciales, nunca reglas.

## 3. Identidad y permisos

### `UserAccount`

Usuario que accede al sistema. Puede estar vinculado opcionalmente con una persona productiva.

Campos lógicos principales: identidad externa, nombre visible, estado, zona horaria y `employee_id` opcional.

### `Role`, `Permission`, `UserRole`, `RolePermission`

Permiten configurar de forma independiente:

- `PLAN_SIMULATE`;
- `PLAN_CONFIRM`;
- `CLIENT_PUBLISH`.

Cardinalidades:

- `UserAccount N:M Role` mediante `UserRole`.
- `Role N:M Permission` mediante `RolePermission`.
- `Employee 0..1:0..1 UserAccount` en V1.

## 4. Proyectos, lotes e hitos

### `Customer`

Cliente comercial. Un cliente puede tener varios proyectos.

### `Project`

Unidad comercial y administrativa.

Datos principales: código único, cliente, nombre, descripción, responsable comercial, prioridad, estado derivado, fechas de aceptación/medición/inicio deseado, fecha comprometida y datos de cierre.

La prioridad es manual. El atraso genera advertencia, no modifica el valor.

### `ProjectLot`

Unidad parcial habilitable y planificable. Contiene descripción, material o familia principal, estado derivado y secuencia visual.

Un proyecto tiene uno o más lotes. Cada lote puede tener su propia ruta, materiales, planos y avance.

### `MilestoneDefinition`, `ProjectMilestone`

`MilestoneDefinition` configura hitos como fabricación terminada, instalación terminada y proyecto cerrado.

`ProjectMilestone` registra el hecho real o confirmado de alcanzar el hito. Las fechas calculadas dentro de una simulación no se guardan aquí, sino en `SolutionMilestone`.

### `SolutionMilestone`

Proyección de un hito para un proyecto dentro de una `ScheduleSolution`. Permite comparar fechas entre el plan vigente y una simulación sin sobrescribir hechos ni compromisos.

Cardinalidades:

- `Customer 1:N Project`.
- `Project 1:N ProjectLot`.
- `Project 1:N ProjectMilestone`.
- `ScheduleSolution 1:N SolutionMilestone`.
- `Project 1:N SolutionMilestone` a través de distintas soluciones.

## 5. Operaciones, rutas y precedencias

### `OperationDefinition`

Catálogo parametrizable: Medición, Replanteo, Pedido, Planos, Descarga, Corte, Pegado, Perforado, Armado, Instalación y otras futuras.

Configura categoría, unidad de estimación, política de división inicial y comportamiento general. No contiene nombres de personas ni máquinas concretas.

### `RouteTemplate`, `RouteVersion`

Una ruta tiene versiones. Una versión publicada queda inmutable cuando se asigna a un lote.

### `RouteStep`

Paso de una versión de ruta. Referencia una definición de operación y contiene configuración general del paso.

### `RouteStepPhaseTemplate`

Plantilla de una o más fases secuenciales de un paso de ruta. Contiene valores por defecto de duración, horas-persona, equipo mínimo/máximo, división, gates y requerimientos físicos/humanos. Las rutas simples contienen una sola fase. Al instanciar un lote, genera `RequiredOperationPhase` y sus requerimientos concretos.

### `RouteStepPrecedence`

Arista dirigida entre dos pasos. V1 utiliza fin-a-inicio. El grafo debe ser acíclico.

### `LotRouteAssignment`

Fija qué versión de ruta usa un lote y desde cuándo. Cambiar la plantilla no modifica lotes existentes.

### `RequiredOperation`

Instancia concreta de trabajo necesario para un proyecto o lote. Es independiente de cualquier plan.

Contiene:

- proyecto y lote opcional;
- definición y paso de ruta de origen;
- duración o trabajo-persona total derivado de sus fases;
- política de división;
- estado de ejecución;
- fecha mínima externa opcional;
- versión de sus parámetros instanciados.

Las operaciones administrativas pueden pertenecer al proyecto; las productivas pertenecen normalmente a un lote. Toda operación tiene al menos una fase, aunque para Corte u otras operaciones simples esa única fase pueda tener el mismo nombre que la operación.

### `RequiredOperationPhase`

Unidad de trabajo planificable dentro de una operación requerida. Contiene referencia opcional a su plantilla de origen, orden, nombre, estimación original de duración y/o trabajo-persona, política de división y estado. La estimación original queda congelada dentro de `ProductDefinitionRevision`; los cambios durante ejecución se registran como pronósticos separados. En V1 las fases de una misma operación son secuenciales según `sequence_no`; no se introduce un segundo grafo interno.

Ejemplo de Armado:

```text
Fase 1: Prearmado
    -> puede trabajar sin herrajes
    -> personas + banco
Fase 2: Terminación
    -> gate START: herrajes disponibles
    -> personas + banco
    -> permite finalizar Armado
```

La suma de trabajo de sus fases representa el trabajo total estimado de la operación. El tiempo entre fases es espera: no consume personas ni capacidad productiva. Una `PhysicalOccupation` puede o no mantenerse abierta durante esa espera.

### `OperationPrecedence`

Precedencia entre operaciones requeridas ya instanciadas. Conserva la regla aunque posteriormente cambie la plantilla.

### `OperationGate`

Condición requerida en uno de dos momentos:

- `START`: debe cumplirse para comenzar;
- `COMPLETE`: debe cumplirse para considerar terminada la operación.

Se asocia a una fase o a la operación completa y puede apuntar a material, planos, herrajes, hito, fecha externa u otra condición configurada. Para Armado en fases, los herrajes imprescindibles son normalmente un gate `START` de Terminación. Un gate `COMPLETE` sigue disponible para condiciones que no requieren trabajo posterior.

Cardinalidades:

- `RouteTemplate 1:N RouteVersion`.
- `RouteVersion 1:N RouteStep`.
- `RouteStep 1:N RouteStepPhaseTemplate`, con al menos una plantilla de fase.
- `RouteStep N:M RouteStep` mediante precedencias.
- `ProjectLot 1:N LotRouteAssignment`, con una asignación activa.
- `ProjectLot 1:N RequiredOperation` para producción.
- `Project 1:N RequiredOperation` para tareas de proyecto.
- `RequiredOperation 1:N RequiredOperationPhase`, con al menos una fase.
- `RequiredOperation N:M RequiredOperation` mediante `OperationPrecedence`.
- `RequiredOperation/RequiredOperationPhase 1:N OperationGate` según alcance.

### `ProductDefinitionRevision`

Revisión inmutable de la definición productiva usada por una simulación o versión del programa. Pertenece a una planta y posee número secuencial, revisión padre opcional, escenario origen opcional, fecha, autor, causa, hash canónico y snapshot.

El snapshot contiene exclusivamente datos necesarios para reconstruir la demanda productiva de ese cálculo:

- proyectos y lotes incluidos;
- cantidades relevantes;
- versiones de rutas;
- operaciones y fases;
- precedencias y gates;
- requerimientos de recursos y habilidades;
- estimaciones y políticas de división.

Estrategia V1: los datos operativos actuales continúan normalizados; al cambiar una definición planificable se genera una nueva revisión inmutable con un documento canónico y referencias a las entidades/versiones origen. Una hipótesis que cambia rutas, fases, requerimientos o estimaciones genera antes del cálculo una revisión derivada vinculada al escenario. `SchedulingRun`, `ScheduleSolution` y `PlanVersion` conservan la revisión exacta utilizada.

`Plant.current_product_definition_revision_id` identifica la definición efectiva. Confirmar un escenario puede mover ese puntero a su revisión derivada sin modificarla; rechazarlo conserva la revisión hipotética únicamente para auditoría.

Esta solución evita versionar individualmente todas las tablas desde la primera versión, permite reconstrucción exacta y mantiene consultas operativas simples. El hash verifica integridad; el snapshot no reemplaza las relaciones normalizadas actuales.

Cardinalidades:

- `Plant 1:N ProductDefinitionRevision`.
- `ProductDefinitionRevision 1:N ScheduleSolution`.
- Cada solución referencia exactamente una revisión de definición productiva.

## 6. Centros, recursos físicos, personas y habilidades

### `Plant`

Ámbito físico de capacidad y planificación. V1 utiliza una sola planta, pero la entidad evita hardcodear esa suposición en calendarios, revisiones y planes.

### `WorkCenter`

Agrupador organizativo perteneciente a una planta: Corte, Pegado, Perforado, Armado, Administración o Instalación. No es por sí mismo una máquina ni una reserva concreta.

### `PhysicalResourceType`, `PhysicalResourceGroup`, `PhysicalResource`

`PhysicalResource` representa una unidad concreta como Escuadradora 1, Perforadora 1, Banco 1 o Banco 2.

El tipo describe su clase; el grupo permite seleccionar recursos equivalentes. Cada recurso tiene centro, estado, capacidad unitaria inicial y calendario.

Un banco es un recurso físico de tipo `BENCH`; no requiere lógica basada en su nombre.

### `Employee`

Recurso humano productivo o administrativo. Se mantiene separado de `PhysicalResource` porque tiene habilidades, permisos laborales y horas-persona.

### `Skill`, `EmployeeSkill`

Habilidad configurable y habilitación de una persona, con vigencia, nivel opcional y estado. Permite representar habilidades futuras sin alterar la operación.

### `OperationPhysicalRequirement`

Requerimiento de una fase: tipo o grupo físico permitido, cantidad y obligatoriedad. Ejemplo: una perforadora del grupo Perforadoras. Una operación de una sola fase conserva el comportamiento simple de V1.

### `OperationLaborRequirement`

Requerimiento humano de una fase: cantidad mínima/máxima, habilidad necesaria y factor de productividad por tamaño de equipo.

Cardinalidades:

- `Plant 1:N WorkCenter`.
- `WorkCenter 1:N PhysicalResource`.
- `PhysicalResourceType 1:N PhysicalResource`.
- `PhysicalResourceGroup N:M PhysicalResource`.
- `Employee N:M Skill` mediante `EmployeeSkill`.
- `RequiredOperationPhase 1:N OperationPhysicalRequirement`.
- `RequiredOperationPhase 1:N OperationLaborRequirement`.

Invariante: declarar que una operación requiere un centro no reemplaza la reserva de la máquina o banco concreto.

## 7. Calendarios, capacidad e indisponibilidades

### `Calendar`

Definición reutilizable de jornada.

### `CalendarWorkingInterval`

Intervalo recurrente por día de semana. Los descansos se representan como separación entre intervalos laborales, no como capacidad disponible.

### `CalendarException`

Excepción fechada de la definición compartida: feriado, cierre general o capacidad adicional aplicable a todos los recursos que usan el calendario.

### `PlantCalendarAssignment` (`CALENDARIO_PLANTA`)

Asigna el calendario general de planta durante un rango de vigencia. Define días laborables, turnos, horarios ordinarios, feriados, cierres y excepciones generales.

### `WorkCenterCalendarAssignment`

Calendario opcional de un centro que restringe o complementa el de planta. Permite, por ejemplo, que Administración y Taller tengan turnos diferentes.

### `EmployeeUnavailability`

Ausencia, vacaciones, licencia o indisponibilidad parcial de una persona concreta. Conserva intervalo, tipo, motivo, autor y estado.

### `PhysicalResourceUnavailability`

Mantenimiento, avería o indisponibilidad parcial de una máquina o banco concreto. Conserva intervalo, causa, evento origen y estado.

### `EmployeeCalendarAssignment`

Asigna un calendario a una persona durante un período de vigencia.

### `PhysicalResourceCalendarAssignment`

Asigna un calendario a una máquina o banco. Se usan entidades separadas para conservar claves foráneas reales y evitar referencias polimórficas sin integridad.

### `OvertimeAuthorization`

Autoriza capacidad extraordinaria para un período y alcance definidos. Puede limitarse por proyecto, escenario, persona, recurso físico o combinación, con minutos máximos y aprobador.

La autorización no reserva capacidad: habilita al motor a considerarla. El consumo real queda asociado a segmentos programados.

### Derivación de capacidad efectiva

Para una persona que trabaja en un centro:

```text
calendario de planta
INTERSECCIÓN calendario del centro
INTERSECCIÓN calendario individual
MENOS indisponibilidades
MÁS intervalos extraordinarios explícitamente autorizados
```

Para una máquina o banco se utiliza planta, centro y calendario del recurso. Los calendarios particulares complementan o restringen la base, pero nunca generan horas extraordinarias utilizables sin autorización.

Trabajo realizado y ocupación física no forman parte de esta fórmula. Una ocupación puede atravesar un cierre o fin de semana sin generar capacidad ni trabajo.

Cardinalidades:

- `Calendar 1:N CalendarWorkingInterval`.
- `Calendar 1:N CalendarException`.
- `Plant 1:N PlantCalendarAssignment`.
- `WorkCenter 1:N WorkCenterCalendarAssignment`.
- `Employee 1:N EmployeeCalendarAssignment`.
- `PhysicalResource 1:N PhysicalResourceCalendarAssignment`.
- `Employee 1:N EmployeeUnavailability`.
- `PhysicalResource 1:N PhysicalResourceUnavailability`.
- `Scenario 0:N OvertimeAuthorization`.

## 8. Materiales, proveedores y planos

### `MaterialRequirement`

Necesidad simplificada de un lote: descripción/código externo, cantidad, unidad, obligatoriedad y operación o gate que habilita.

### `Supplier`, `SupplierOrder`, `SupplierOrderLine`

Registro productivo simplificado de pedidos. Puede ser manual o una proyección recibida desde la aplicación de Compras.

### `SupplierDelivery`, `SupplierDeliveryLine`

Entrega real o recepción parcial. No se edita destructivamente: correcciones y devoluciones se registran como movimientos compensatorios.

### `MaterialAllocation`

Asigna cantidad de una entrega a un requerimiento de lote. La suma asignada determina la cobertura productiva; recibir material no lo asigna automáticamente a todos los lotes.

### `DrawingPackage`, `DrawingRelease`

Paquete de planos requerido para un lote y sus liberaciones/versiones. Producción solo se habilita con una liberación vigente y aprobada.

### `HardwareReadiness`

Control simplificado por lote con estado Disponible, Pendiente, Recibido o No aplica. Puede actuar como gate de finalización del armado.

Cardinalidades:

- `ProjectLot 1:N MaterialRequirement`.
- `SupplierOrder 1:N SupplierOrderLine`.
- `SupplierOrder 1:N SupplierDelivery`.
- `SupplierDelivery 1:N SupplierDeliveryLine`.
- `SupplierDeliveryLine N:M MaterialRequirement` mediante `MaterialAllocation`.
- `ProjectLot 1:N DrawingPackage`.
- `DrawingPackage 1:N DrawingRelease`.
- `ProjectLot 0..1:1 HardwareReadiness`.

## 9. Lotes productivos compartidos

### `ProductionBatch`, `ProductionBatchVersion`, `ProductionBatchMember`

`ProductionBatch` identifica el agrupamiento productivo. Cada cambio de composición crea una `ProductionBatchVersion` inmutable. Sus miembros son fases requeridas compatibles de uno o más proyectos y comparten una ejecución con duración manual.

- Una fase puede pertenecer como máximo a una versión activa de lote productivo por propósito.
- La asignación se hace al lote productivo una sola vez.
- La terminación libera las sucesoras de todos sus miembros.
- La distribución analítica de tiempo entre proyectos no crea reservas adicionales.
- Una solución referencia la versión exacta utilizada; retirar o agregar un miembro genera otra versión y no altera soluciones históricas.

Cardinalidades:

- `ProductionBatch 1:N ProductionBatchVersion`.
- `ProductionBatchVersion 1:N ProductionBatchMember`.
- `ProductionBatchMember N:1 RequiredOperationPhase`.

## 10. Plan, solución, asignación y ocupación

### `PlanningPlan`

Corriente de planificación de una planta, inicialmente un único taller. Contiene versiones sucesivas.

### `ScheduleSolution`

Resultado inmutable de un cálculo. Puede ser propuesta de un escenario o solución publicada. Conserva horizonte, versión del algoritmo, parámetros, revisión de definición productiva y revisión del estado operativo.

### `OperationPlanResult`

Resultado de una operación requerida dentro de una solución:

- `PLANNED`;
- `FROZEN`;
- `BLOCKED`;
- `OUT_OF_HORIZON`;
- `COMPLETED`;
- `CANCELLED`.

Existe exactamente uno por operación incluida en el snapshot. Una operación fuera del horizonte conserva resultado y explicación aunque ninguna de sus fases tenga asignación.

### `PhasePlanResult`

Resultado de una fase requerida dentro de una solución. Registra estado, trabajo planificado/pendiente, explicación y `remaining_estimate_revision_id` utilizado cuando la fase está en ejecución. Una operación de una sola fase mantiene la misma experiencia funcional que el modelo anterior.

### `PlannedPhaseAssignment`

Asignación concreta propuesta para una fase o para una versión de lote productivo compartido dentro de una solución. No modifica la operación/fase requerida ni la revisión productiva.

### `AssignmentSegment`

Intervalo laboral efectivo. Permite continuar una operación entre jornadas y conservar equipos diferentes por segmento en instalación.

### `HumanSegmentAssignment`

Vincula personas concretas con un segmento y registra minutos normales/extraordinarios y trabajo-persona aportado.

### `PhysicalResourceReservation`

Reserva una máquina o banco concreto durante un segmento laboral.

### `PhysicalOccupation`

Reserva física continua, especialmente para bancos. Tiene inicio, final opcional, recurso, lote/operación/fase, motivo de liberación y fuente:

- planificada dentro de una solución;
- real, derivada de ejecución.

La ocupación puede atravesar períodos no laborales y existir sin asignación humana. El final planificado y la liberación real son instantes distintos; una ocupación real abierta prevalece como restricción sobre todas las simulaciones hasta que un evento efectivo registre su liberación.

### `PlanVersion`

Versión publicada e inmutable de `PlanningPlan`. Referencia una `ScheduleSolution`, su revisión productiva y operativa, número secuencial, versión anterior, escenario origen, usuario confirmador, fecha y motivo.

Solo una versión puede estar `CURRENT` por plan.

Cardinalidades:

- `Plant 1:N PlanningPlan`.
- `PlanningPlan 1:N PlanVersion`.
- `PlanVersion 1:1 ScheduleSolution`.
- `ScheduleSolution 1:N OperationPlanResult`.
- `OperationPlanResult 1:N PhasePlanResult`.
- `PhasePlanResult 0..1:1 PlannedPhaseAssignment`.
- `PlannedPhaseAssignment 1:N AssignmentSegment`.
- `AssignmentSegment N:M Employee` mediante `HumanSegmentAssignment`.
- `AssignmentSegment N:M PhysicalResource` mediante `PhysicalResourceReservation`.
- `ScheduleSolution 1:N PhysicalOccupation` planificada.

## 11. Escenarios, eventos e impacto

### `EffectiveEvent` (`EVENTO_EFECTIVO`)

Hecho que ocurrió y modifica el estado operativo real: material recibido, ausencia, avería, operación terminada o banco liberado. Conserva tipo, fecha efectiva, entidad afectada, autor, payload, causa y revisión operativa generada. Es append-only; una corrección usa un evento compensatorio.

### `SimulationHypothesis` (`HIPOTESIS_SIMULACION`)

Cambio que solo existe dentro de un escenario: entrega tardía, ausencia futura supuesta, prioridad alternativa u horas extra hipotéticas. Pertenece a un escenario y nunca modifica proyectos, calendarios, materiales ni ejecución real.

### `ManualException` (`EXCEPCION_MANUAL`)

Decisión autorizada que modifica de manera excepcional una regla: forzar asignación, habilitar horas extra, bloquear recurso, permitir división intradía o cambiar excepcionalmente una duración. Conserva alcance, vigencia, autorizador, motivo y estado.

Para simular una excepción antes de aplicarla se crea primero una `SimulationHypothesis`. Al confirmar, la transacción puede materializar una `ManualException` efectiva y su `EffectiveEvent`; nunca se reutiliza la hipótesis como si fuera un hecho.

Cada tipo de excepción declara qué regla configurable puede modificar. “Forzar asignación” fija una preferencia o recurso concreto, pero no autoriza doble reserva, habilidad inexistente ni otra violación física no dispensable; si el resultado continúa siendo inviable, el escenario debe informarlo.

### `PlanningLock`

Congelamiento explícito aplicado a una operación iniciada o decisión firme. Define alcance —segmentos ejecutados, comienzo, personas, recurso físico, ocupación o segmentos futuros—, vigencia, origen y motivo. Permite explicar qué no puede mover una reprogramación.

### `PlanningStateRevision`

Contador monotónico por planta que identifica una fotografía lógica del estado planificable. Toda transacción que modifica capacidad, materiales, planos, prioridades, lotes, rutas, estimaciones, calendarios, horas extra, ejecución, ocupación física o eventos efectivos incrementa la revisión una sola vez.

### `PlanningStateChange`

Detalle auditable de qué entidades provocaron una revisión. Evita comparar manualmente timestamps y permite explicar por qué un escenario quedó obsoleto.

### `Scenario`

Simulación basada obligatoriamente en una `PlanVersion`, una `PlanningStateRevision` y una `ProductDefinitionRevision` base. Estados: Draft, Calculating, Ready, Rejected, Confirmed, Stale (`ESCENARIO_OBSOLETO`) o Failed.

`base_product_definition_revision_id` identifica la definición efectiva desde la que parte. Si las hipótesis modifican definición, el run y la solución referencian otra revisión derivada e inmutable como `input_product_definition_revision_id`.

Contiene horizonte —90 días por defecto configurable—, permisos de horas extra y parámetros de simulación.

### `ScenarioEffectiveEvent`

Relaciona uno o más eventos efectivos con el escenario que evalúa sus consecuencias. Las hipótesis pertenecen directamente al escenario y se mantienen separadas.

### `ImpactAnalysis`, `ImpactedOperation`

Registra proyectos, operaciones, recursos e hitos que deben reconsiderarse y la razón de inclusión.

### `SchedulingRun`

Ejecución reproducible: snapshot canónico inmutable de todos los datos de entrada, hash del snapshot, revisión productiva de entrada —base o derivada—, revisión operativa base, versión de algoritmo, parámetros, comienzo/fin, estado y diagnóstico. El snapshot incluye la capacidad y disponibilidad efectivamente leídas; las revisiones permiten detectar obsolescencia y el documento permite reconstrucción exacta. Un escenario puede tener varios intentos; una solución identifica el run que la produjo.

### `SchedulingExplanation`, `SchedulingBlocker`

Explica fechas de liberación, recursos evaluados, principal limitante, asignación precedente, horizonte y utilización de capacidad extraordinaria.

Cardinalidades:

- `Plant 1:N PlanningStateRevision`.
- `PlanningStateRevision 1:N PlanningStateChange`.
- `PlanVersion 1:N Scenario` como versión base.
- `Scenario N:M EffectiveEvent` mediante `ScenarioEffectiveEvent`.
- `Scenario 1:N SimulationHypothesis`.
- `ManualException N:1 UserAccount` como autorizador.
- `Scenario 1:N SchedulingRun`.
- `SchedulingRun 0..1:1 ScheduleSolution`.
- `ImpactAnalysis 1:N ImpactedOperation`.
- `OperationPlanResult 1:N SchedulingBlocker`.

## 12. Promoción de escenario a plan vigente

Confirmar no copia ni sobrescribe asignaciones del plan actual. La operación transaccional es:

1. Verificar permiso `PLAN_CONFIRM`.
2. Bloquear lógicamente el `PlanningPlan` durante la publicación.
3. Comprobar que `Scenario.base_plan_version_id` sigue siendo la versión `CURRENT`.
4. Comprobar que `Scenario.base_planning_state_revision_id` sigue siendo la revisión operativa vigente y que `base_product_definition_revision_id` sigue siendo la definición efectiva desde la cual se simuló.
5. Comprobar que el escenario está Ready, su solución completa y sus invariantes aprobadas.
6. Materializar únicamente las hipótesis aprobadas como cambios reales, `ManualException` y/o `EffectiveEvent`; si cambian definición, adoptar como vigente la revisión derivada exacta usada por la solución, y si cambian estado, crear la revisión operativa resultante.
7. Marcar la versión anterior como `SUPERSEDED`.
8. Insertar una nueva `PlanVersion` que referencia la solución inmutable, la revisión productiva efectiva y la revisión operativa resultante.
9. Marcar el escenario `CONFIRMED` y los escenarios hermanos basados en revisiones anteriores como `STALE`.
10. Registrar auditoría con usuario, versiones, revisiones, escenario, fecha y motivo.
11. Emitir eventos mediante outbox para actualizar capacidad, portal y recomendaciones de comunicación.
12. Confirmar toda la transacción o revertirla completa.

Si la versión base o la revisión operativa no siguen vigentes, el escenario pasa a `STALE`; se conserva para auditoría y no puede publicarse hasta recalcularse. No se comparan manualmente timestamps individuales.

## 13. Ejecución real

### `OperationExecution`, `ExecutionSegment`, `ExecutionPause`

Registra inicio, pausas, reinicios, finalización, personas, recursos y trabajo real. Puede existir sin planificación previa.

Cuando tiene origen planificado, `OperationExecution` conserva referencias opcionales e inmutables `origin_plan_version_id` y `origin_operation_plan_result_id`, además de la operación requerida. Cada `ExecutionSegment` identifica la fase ejecutada y puede conservar `origin_assignment_segment_id`. De esta forma puede compararse lo previsto con lo real sin modificar el plan original.

Los segmentos ejecutados son hechos y no se mueven en simulaciones posteriores. Registran personas y recursos realmente utilizados, aunque difieran de los previstos.

Una operación de armado puede quedar en estado `WAITING_FOR_INPUT` si agotó el trabajo físicamente posible y falta un gate de finalización, como herrajes.

### `ActualResourceUsage`

Uso real de persona o recurso físico, separado de lo planificado.

La diferencia estimado/real se calcula sin reescribir la estimación histórica utilizada por el plan.

Cardinalidades:

- `OperationExecution N:0..1 PlanVersion` como origen.
- `OperationExecution N:0..1 OperationPlanResult` como resultado previsto.
- `ExecutionSegment N:0..1 AssignmentSegment` como segmento previsto.
- `OperationExecution 1:N ExecutionSegment`.
- `ExecutionSegment 1:N ActualResourceUsage`.

### `RemainingEstimateRevision`

Revisión append-only del pronóstico futuro de una operación en ejecución. Apunta a la ejecución y operación; puede identificar la fase activa al momento del corte. Conserva autor, fecha, modo de ingreso, motivo, revisión anterior y `PlanningStateRevision` generada.

Modos de ingreso admitidos por el dominio:

- sumar o restar minutos al restante;
- ingresar trabajo restante;
- ingresar una nueva hora estimada de finalización;
- fijar una nueva liberación física prevista;
- futura edición mediante Gantt, normalizada a uno de los modos anteriores.

Registra como fotografía:

- estimación original proveniente de la revisión productiva;
- trabajo real acumulado al momento del cambio;
- estimación restante vigente;
- estimación total actualizada derivada como ejecutado más restante.

La estimación original y el ejecutado no se editan desde esta entidad. Una corrección crea otra revisión.

Después del corte, el restante operativo visible se deriva descontando el uso real compatible registrado desde `cutoff_at`; esa derivación no altera la revisión. Una nueva apreciación del usuario, en cambio, siempre crea otra revisión.

### `RemainingResourceEstimate`

Detalle hijo que define qué demanda futura cambia e identifica la fase a la que pertenece. Tipos iniciales:

- `LABOR_WORK`: minutos-persona restantes, habilidad y equipo previsto;
- `ACTIVE_PHYSICAL_USE`: minutos futuros de uso activo de máquina, banco u otro recurso;
- `PHYSICAL_OCCUPATION`: instante estimado de liberación o duración adicional de ocupación sin implicar trabajo.

Puede referenciar un requerimiento genérico o un recurso concreto ya comprometido. En una operación multifase, los detalles de todas las fases incompletas permiten calcular el restante de la operación; las fases futuras no modificadas conservan su estimación vigente. No existe propagación automática entre tipos: extender trabajo humano no extiende una máquina o banco salvo que el usuario/regla lo indique; extender ocupación física tampoco crea horas-persona.

### Flujo de impacto

Confirmar una nueva estimación restante registra un `EffectiveEvent` de tipo `REMAINING_ESTIMATE_UPDATED` e incrementa `PlanningStateRevision`. El programa vigente no cambia.

La detección de impacto utiliza la última revisión para identificar:

- segmentos futuros insuficientes;
- personas y recursos que deberían prolongarse;
- reservas y ocupaciones que entrarían en conflicto;
- operaciones sucesoras;
- proyectos que compiten por los mismos recursos;
- hitos y fechas estimadas afectados.

Se crea un escenario basado en el plan Current y en la nueva revisión operativa. Sus asignaciones futuras pueden prolongarse o acortarse, pero todos los segmentos realmente ejecutados permanecen congelados. Rechazar el escenario conserva la versión publicada anterior y el nuevo pronóstico operativo continúa visible como advertencia pendiente.

Cardinalidades:

- `OperationExecution 1:N RemainingEstimateRevision`.
- `RemainingEstimateRevision 1:N RemainingResourceEstimate`.
- `RemainingResourceEstimate N:1 RequiredOperationPhase`.
- Solo una revisión de estimación restante es vigente por ejecución; las anteriores permanecen auditables.

## 14. Instalación

### `InstallationWorkPackage`

Trabajo de instalación de un proyecto, vinculado a una operación requerida y opcionalmente a uno o más lotes mediante `InstallationLotCoverage`.

Configura trabajo-persona, equipo mínimo/máximo y estado.

### `CustomerAvailabilityWindow`

Intervalos obligatorios del cliente. Todo segmento planificado debe quedar contenido en alguno de ellos.

### `InstallationProgressEntry`

Historial del porcentaje instalado de 0 a 100, con fecha, usuario y observación. No se deriva automáticamente de horas consumidas.

Cardinalidades:

- `Project 1:N InstallationWorkPackage`.
- `InstallationWorkPackage N:M ProjectLot` mediante coberturas.
- `InstallationWorkPackage 1:N CustomerAvailabilityWindow`.
- `InstallationWorkPackage 1:N InstallationProgressEntry`.

## 15. Portal público y comunicaciones

### `PublicTrackingLink`

Enlace de solo lectura con `token_hash` único, estado, creación, expiración opcional, revocación y regeneración. El token original no se almacena.

### `PublicStageDefinition`

Configura las ocho etapas comerciales, orden, textos y peso opcional para porcentaje general.

### `PublicStageMappingSet`, `PublicStageMappingRule`

Configuración versionada independiente que transforma hechos internos en una etapa pública:

```text
estado/hito interno -> predicado tipado -> etapa pública
```

Las reglas son ordenadas, auditables y utilizan un vocabulario permitido —hitos, estados agregados, materiales disponibles, producción iniciada, porcentaje instalado y cierre—. No contienen expresiones libres ni referencias a nombres de personas o recursos. Cambiar el mapping no modifica rutas, operaciones ni motor de scheduling.

### `PublicProjectProjection`

Proyección limitada: proyecto público, etapa, avance general opcional, porcentaje de instalación, fecha comunicada y novedad aprobada. Referencia la versión interna, mapping set y regla que la produjeron sin exponerlos al cliente. El portal consume solamente esta proyección mediante una allowlist.

### `PublicTimelineEntry`

Hito o novedad explícitamente publicable. No copia automáticamente eventos internos sensibles.

### `CommunicatedDate`

Historial de fechas comunicadas al cliente. Permite comparar una simulación contra la última fecha publicada.

### `CommunicationPolicy`

Política parametrizable vinculada explícitamente a un calendario comercial. V1: más de un día hábil de diferencia genera recomendación.

### `CommunicationRecommendation`

Resultado de comparación con fecha anterior, nueva fecha, diferencia en días hábiles, motivo, escenario y estado de aprobación. Nunca equivale a envío automático.

Cardinalidades:

- `Project 1:N PublicTrackingLink` con cero o uno activo.
- `PublicStageMappingSet 1:N PublicStageMappingRule`.
- `PublicStageMappingRule N:1 PublicStageDefinition`.
- `Project 1:1 PublicProjectProjection` vigente.
- `Project 1:N PublicTimelineEntry`.
- `Project 1:N CommunicatedDate`.
- `Scenario 0:N CommunicationRecommendation`.

## 16. Integración con Compras y eventos técnicos

### `OutboxMessage`, `InboxMessage`

Outbox publica eventos confirmados; inbox garantiza recepción idempotente. La combinación `source_system + idempotency_key` es única.

Los pedidos y entregas pueden registrarse localmente o sincronizarse. Compras no escribe tablas del planificador y Producción conserva la asignación del material al lote.

## 17. Restricciones e invariantes

### Integridad estructural

1. Todo proyecto tiene al menos un lote antes de entrar en producción.
2. Una versión de ruta asignada no se modifica.
3. El grafo de precedencias no contiene ciclos.
4. Una operación sucesora no se completa antes de sus predecesoras.
5. Un gate `START` de fase se cumple antes del primer segmento de esa fase; un gate `COMPLETE`, antes de completarla u operación correspondiente.

### Capacidad

6. Una persona no tiene segmentos superpuestos dentro de una solución.
7. Un recurso físico unitario no tiene reservas superpuestas dentro de una solución.
8. Dos ocupaciones físicas del mismo banco no se superponen dentro de una solución ni contra ocupaciones reales activas.
9. Todo segmento respeta la intersección aplicable de calendario de planta, centro, persona/recurso, indisponibilidades y autorizaciones extraordinarias.
10. Toda persona asignada posee la habilidad vigente requerida.
11. Se cumplen cantidades mínimas/máximas de equipo y recursos simultáneos.

### Planificación y simulación

12. Existe un resultado por operación y por fase dentro de cada solución.
13. `OUT_OF_HORIZON` no equivale a imposible ni cancelada.
14. Una solución Ready es inmutable.
15. Solo existe una versión Current por plan.
16. Publicar requiere que la versión base siga Current y que la revisión operativa base continúe vigente.
17. Simular nunca actualiza una versión ni sus asignaciones.
18. Las operaciones iniciadas conservan sus segmentos ejecutados y las referencias al plan de origen.
19. Las horas extra consumidas tienen autorización aplicable.

### Materiales y portal

20. La asignación acumulada a un requerimiento no supera la recepción neta disponible.
21. Una recepción duplicada por integración no duplica cantidades.
22. El armado no termina con gate de herrajes imprescindible incumplido.
23. Solo existe un enlace público activo por proyecto, salvo decisión futura explícita.
24. La proyección pública no contiene personas, recursos, costos, prioridades ni otros proyectos.
25. Una recomendación de comunicación nunca envía por sí sola un mensaje.

### Revisiones, fases y trazabilidad

26. Toda operación requerida posee al menos una fase y el trabajo total equivale a la suma de sus fases.
27. Una fase no comienza antes de completar la fase anterior ni antes de cumplir sus gates de inicio.
28. Un intervalo de espera sin segmento no consume horas-persona ni capacidad productiva; una ocupación física puede permanecer activa.
29. Una `ProductDefinitionRevision` utilizada por una solución es inmutable y su hash corresponde al snapshot canónico.
30. Toda solución identifica exactamente una revisión productiva y una revisión del estado operativo.
31. Una `SimulationHypothesis` solo afecta a su escenario y no modifica estado real.
32. Toda `ManualException` efectiva tiene alcance, vigencia, autorizador y motivo; una excepción hipotética se representa primero como hipótesis.
33. Un escenario se marca `STALE` si cambia su versión base o su revisión del estado operativo, y se conserva para auditoría.
34. La ejecución real puede existir sin plan; si tiene origen, conserva referencias inmutables a versión, asignación y segmento previstos.
35. Toda versión de lote productivo publicada es inmutable y una solución referencia su composición exacta.
36. Toda etapa pública se obtiene mediante una versión de mapping y el portal no evalúa estados técnicos directamente.
37. Una revisión operativa se incrementa atómicamente una sola vez por transacción planificablemente relevante y registra sus cambios.

### Estimaciones durante ejecución

38. La estimación original pertenece a la revisión productiva y nunca se sobrescribe por ejecución o reprogramación.
39. El trabajo ejecutado se deriva de segmentos/uso real append-only; una estimación restante no puede editarlo.
40. La estimación total actualizada de trabajo se calcula como trabajo real acumulado al corte más trabajo restante vigente, conservando unidad y dimensión.
41. Solo una `RemainingEstimateRevision` es vigente por ejecución, pero todas las revisiones anteriores permanecen auditables.
42. Registrar o corregir una estimación restante genera un evento efectivo e incrementa `PlanningStateRevision`; no actualiza `PlanVersion`.
43. Trabajo humano, uso físico activo y ocupación física futura se modifican por detalles independientes; no se propagan implícitamente.
44. Una solución de extensión o reducción conserva todos los segmentos ejecutados y solo propone cambios futuros.
45. Rechazar una reprogramación no cambia el plan Current ni elimina el pronóstico operativo que originó la advertencia.

## 18. Cardinalidades resumidas

| Origen | Relación | Destino |
|---|---:|---|
| Customer | 1:N | Project |
| Project | 1:N | ProjectLot |
| ProjectLot | 1:N | RequiredOperation |
| RequiredOperation | N:M | RequiredOperation mediante precedencia |
| RouteStep | 1:N | RouteStepPhaseTemplate |
| RequiredOperation | 1:N | RequiredOperationPhase |
| RequiredOperationPhase | 1:N | Gates y requerimientos de recursos |
| Employee | N:M | Skill |
| Plant | 1:N | WorkCenter y PlanningPlan |
| WorkCenter | 1:N | PhysicalResource |
| Calendar | 1:N | Intervalos y excepciones |
| Plant | 1:N | PlantCalendarAssignment |
| WorkCenter | 1:N | WorkCenterCalendarAssignment |
| Employee | 1:N | Indisponibilidades humanas |
| PhysicalResource | 1:N | Indisponibilidades físicas |
| ProjectLot | 1:N | MaterialRequirement |
| SupplierDeliveryLine | N:M | MaterialRequirement mediante asignación |
| PlanningPlan | 1:N | PlanVersion |
| PlanVersion | 1:1 | ScheduleSolution |
| Plant | 1:N | ProductDefinitionRevision y PlanningStateRevision |
| Scenario | N:1 | PlanVersion base |
| Scenario | N:1 | PlanningStateRevision base |
| Scenario | 1:N | SimulationHypothesis |
| Scenario | 1:N | SchedulingRun |
| ScheduleSolution | 1:N | OperationPlanResult |
| OperationPlanResult | 1:N | PhasePlanResult |
| PhasePlanResult | 0..1:1 | PlannedPhaseAssignment |
| PlannedPhaseAssignment | 1:N | AssignmentSegment |
| AssignmentSegment | N:M | Employee |
| AssignmentSegment | N:M | PhysicalResource |
| ProductionBatch | 1:N | ProductionBatchVersion |
| ProductionBatchVersion | 1:N | ProductionBatchMember |
| OperationExecution | N:0..1 | PlanVersion/segment de origen |
| OperationExecution | 1:N | RemainingEstimateRevision |
| RemainingEstimateRevision | 1:N | RemainingResourceEstimate |
| Project | 1:N | InstallationWorkPackage |
| Project | 1:N | PublicTrackingLink |
| Project | 1:1 | PublicProjectProjection vigente |
| PublicStageMappingSet | 1:N | PublicStageMappingRule |

## 19. Decisiones de implementación postergadas

Estas no son reglas funcionales abiertas; se resolverán al diseñar el esquema físico:

- UUID frente a otro identificador opaco.
- Uso de rangos temporales y restricciones de exclusión de PostgreSQL.
- Catálogos mediante tablas o enums SQL según su variabilidad.
- Estrategia de particionado para auditoría y eventos a largo plazo.
- Forma física del documento canónico y sus referencias auxiliares dentro de `ProductDefinitionRevision`.
