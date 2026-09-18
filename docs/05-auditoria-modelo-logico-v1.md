# Auditoría del modelo lógico V1

Estado: revisión formal previa al esquema físico.  
Documentos auditados: decisiones funcionales V1, casos de aceptación, modelo lógico y casos difíciles.  
Alcance: documentación solamente; no se crearon tablas, migraciones, endpoints, frontend ni motor.

## 1. Resumen ejecutivo

El modelo tiene una base correcta y separa adecuadamente proyecto, lote, operación requerida, solución, asignación, segmento, ejecución, persona y recurso físico. También representa correctamente versiones inmutables, escenarios paralelos, ocupación física de bancos, horas extraordinarias y portal público desacoplado.

La auditoría encontró **seis brechas del modelo** y recomienda **ocho casos adicionales de aceptación**. Ninguna exige cambiar las reglas funcionales aprobadas, pero las seis brechas deben corregirse en el documento lógico antes de diseñar el esquema físico:

1. Falta una entidad explícita para el calendario general de planta.
2. Falta versionar la composición de los lotes productivos compartidos.
3. Falta distinguir cambios hipotéticos de escenario de eventos ya efectivos.
4. Falta una revisión global de datos planificables para detectar escenarios obsoletos aunque no haya cambiado la versión del plan.
5. Falta vincular explícitamente la ejecución real con la versión/asignación publicada de origen.
6. Falta una regla configurable que derive etapas públicas desde hechos internos.

Adicionalmente, el tratamiento de herrajes mediante un gate de finalización es válido para ejecución, pero necesita una decisión de modelado antes del esquema físico para representar trabajo planificable anterior y posterior a la llegada de herrajes. Se clasifica como parte de la brecha 3/operaciones por fases y se detalla en la sección de brechas.

Conclusión de esta auditoría: **`MODELO_REQUIERE_AJUSTES`**.

## 2. Matriz de trazabilidad

Abreviaturas: `INV-n` refiere a la invariante numerada en el modelo; `CA-nn` a casos de aceptación; `CD-nn` a casos difíciles.

| Regla funcional | Entidades involucradas | Restricciones/invariantes | Caso de aceptación | Caso difícil |
|---|---|---|---|---|
| Prioridad manual antes que fecha comprometida | `Project`, `PlanningEvent`, `Scenario`, `ScheduleSolution` | Orden total determinista; atraso no cambia prioridad; simulación no muta proyecto | CA-18, CA-21 | CD-13; falta prueba de cambio hipotético de prioridad |
| Proyecto dividido en lotes independientes | `Project`, `ProjectLot`, `RequiredOperation` | INV-1; cada operación productiva pertenece a un lote; no hay exclusividad global por proyecto | CA-03, CA-05 | CD-3, CD-6 |
| Ruta diferente por lote | `RouteTemplate`, `RouteVersion`, `LotRouteAssignment`, `RouteStep`, `OperationPrecedence` | INV-2, INV-3, INV-4 | CA-04, CA-05 | CD-8 |
| Material como condición de inicio | `MaterialRequirement`, `SupplierDelivery`, `MaterialAllocation`, `OperationGate START` | INV-5, INV-20, INV-21 | CA-02, CA-03 | CD-6, CD-7 |
| Planos como condición de inicio | `DrawingPackage`, `DrawingRelease`, `OperationGate START` | INV-5 | CA-02 | Sin caso difícil específico; cobertura suficiente en combinación |
| Herrajes como condición de finalización | `HardwareReadiness`, `OperationGate COMPLETE`, `OperationExecution` | INV-5, INV-22 | **FALTA_CA** | CD-1; `BRECHA_MODELO` para trabajo previo/posterior al gate |
| Corte y pegado simultáneos si hay recursos | Operaciones requeridas independientes, segmentos, asignaciones humanas y reservas físicas | INV-6, INV-7, INV-10, INV-11; ninguna exclusividad por proyecto/centro | **FALTA_CA** | No existe caso difícil directo |
| Operación con una o dos personas | `OperationLaborRequirement`, `AssignmentSegment`, `HumanSegmentAssignment` | INV-6, INV-10, INV-11; trabajo-persona consistente | CA-01, CA-06 | CD-4 y caso numérico de la sección 5 |
| Instalación con equipos variables | `InstallationWorkPackage`, `AssignmentSegment`, `HumanSegmentAssignment`, `CustomerAvailabilityWindow` | INV-6, INV-9, INV-10, INV-11 | CA-11, CA-12 | CD-4, CD-5 |
| Banco ocupado sin personal | `PhysicalOccupation`, `PhysicalResourceReservation`, `HumanSegmentAssignment` | INV-8; ocupación continua independiente de segmentos laborales | CA-07 | CD-2 |
| Un proyecto puede ocupar dos bancos | Dos `RequiredOperation`/lotes y dos `PhysicalOccupation` | INV-8 solo por recurso concreto; ninguna exclusión por proyecto | CA-08 no lo prueba expresamente | CD-3; falta CA específico |
| Horas extraordinarias autorizadas | `Calendar`, `OvertimeAuthorization`, `HumanSegmentAssignment` | INV-9, INV-19 | CA-13 | CD-14 |
| Operaciones iniciadas no se mueven | `OperationExecution`, `ExecutionSegment`, `OperationPlanResult FROZEN` | INV-14, INV-18 | CA-14 | CD-13; alcance de congelamiento debe formalizarse |
| Operaciones divididas entre jornadas | `RequiredOperation.splitting_policy`, `AssignmentSegment`, `ExecutionSegment` | Segmentos no superpuestos; no fragmentación intradía sin decisión | Cobertura parcial CA-06 | CD-16; falta CA directo |
| Horizonte móvil configurable de 90 días | `Scenario`, `SchedulingRun`, `ScheduleSolution` | Horizonte almacenado en snapshot/resultado | **FALTA_CA** | CD-10 |
| Resultado `OUT_OF_HORIZON` | `OperationPlanResult` | INV-12, INV-13 | **FALTA_CA** | CD-10 |
| Fechas estimadas por solución | `SolutionMilestone`, `ScheduleSolution`, `OperationPlanResult` | Una fecha calculada pertenece a una solución inmutable | CA-20 indirecto | CD-10, CD-19; falta CA de hitos comparados |
| Fechas comprometidas y comunicadas | `Project`, `CommunicatedDate`, `PublicProjectProjection` | Historial; no se sobrescribe por simulación | CA-18, CA-22 | CD-17, CD-19 |
| Simulación no modifica plan | `Scenario`, `SchedulingRun`, `ScheduleSolution`, `PlanVersion` | INV-14, INV-16, INV-17 | CA-15 | CD-11, CD-12, CD-19 |
| Versiones del programa | `PlanningPlan`, `PlanVersion`, `ScheduleSolution` | INV-15, INV-16; publicación atómica | CA-16, CA-17 | CD-12, CD-22 |
| Ejecución real separada | `OperationExecution`, `ExecutionSegment`, `ActualResourceUsage` | INV-18; hechos ejecutados inmutables | **FALTA_CA** | CD-1, CD-13, CD-20; falta vínculo explícito a versión origen |
| Portal público de solo lectura | `PublicTrackingLink`, `PublicProjectProjection`, `PublicTimelineEntry` | INV-23, INV-24 | CA-22, CA-23 | CD-18, CD-19 |
| Estado público derivado por configuración | `PublicStageDefinition`, `PublicProjectProjection` | INV-24; no depender directamente del enum técnico | CA-22 parcial | CD-19; `BRECHA_MODELO`: falta `PublicStageMapping` |
| Recomendación por cambio mayor a un día hábil | `CommunicationPolicy`, `CommunicatedDate`, `CommunicationRecommendation` | INV-25; aprobación humana | **FALTA_CA** | CD-17, CD-19 |
| Recepciones provenientes de Compras idempotentes | `InboxMessage`, `SupplierDelivery`, `MaterialAllocation` | INV-20, INV-21 | CA-24 | CD-6, CD-7 |

### Cobertura faltante recomendada

Agregar después de ajustar el modelo:

- CA-25: armado parcial no puede finalizar sin herrajes y requiere trabajo final después de recibirlos.
- CA-26: corte y pegado simultáneos con personas y máquinas distintas.
- CA-27: dos lotes del mismo proyecto ocupan simultáneamente Banco 1 y Banco 2.
- CA-28: operación dividida entre jornadas sin fragmentación intradía automática.
- CA-29: operación y sucesoras quedan `OUT_OF_HORIZON` sin considerarse imposibles.
- CA-30: fechas de hitos diferentes entre plan vigente y escenario sin sobrescritura.
- CA-31: recomendación de comunicación calculada con calendario de días hábiles y aprobación humana.
- CA-32: ejecución real conserva referencia a la asignación/version publicada de origen.

## 3. Revisión de las 25 invariantes

La columna “DB” indica si una parte significativa puede convertirse posteriormente en constraint; no implica implementarlo en esta etapa.

| Invariante | Problema que evita | Capa principal | DB | Validación de negocio y caso límite |
|---:|---|---|---|---|
| INV-1 | Proyecto productivo sin unidad planificable | Dominio + transacción | Parcial: FK y conteo diferido | Debe permitirse crear proyecto borrador sin lote; exigir lote al cambiar de etapa, no al insertar |
| INV-2 | Cambios retroactivos de rutas históricas | Dominio + DB | Sí: estado inmutable/trigger o permisos | Corregir un error exige nueva versión, nunca editar la usada |
| INV-3 | Ciclos que hacen imposible el orden topológico | Dominio | No fácilmente con constraint simple | Validar grafo completo al publicar; contemplar precedencias agregadas manualmente |
| INV-4 | Sucesora terminada antes de predecesora | Dominio + ejecución | Parcial: fechas simples, no todo el grafo | Cancelaciones, excepciones aprobadas y datos reales importados requieren tratamiento explícito |
| INV-5 | Inicio/finalización sin insumos obligatorios | Dominio | Parcial: FK/estado; no condición temporal completa | Herrajes requieren distinguir trabajo previo y posterior; brecha documentada |
| INV-6 | Persona duplicada en el mismo tiempo | Motor + DB | Sí, por solución con exclusión temporal | Debe considerar uso real activo además de reservas del escenario |
| INV-7 | Máquina/banco reservado dos veces | Motor + DB | Sí, por solución y rango temporal | Recursos con capacidad mayor a uno exigirían capacidad acumulada, no exclusión binaria |
| INV-8 | Dos muebles ocupando el mismo banco | Motor + DB | Sí para ocupaciones de una solución; cruce con hechos requiere validación | Final abierto de ocupación y ocupación real activa son casos críticos |
| INV-9 | Trabajo fuera de disponibilidad o sin autorización | Motor + dominio | Parcial; intervalos múltiples no caben en un check simple | Plant calendar faltante; ocupación física no debe evaluarse como trabajo |
| INV-10 | Persona sin habilidad vigente | Dominio + motor | Parcial mediante FK; vigencia requiere validación temporal | Habilidad que vence dentro de una operación dividida |
| INV-11 | Equipo o recurso insuficiente/excesivo | Motor + dominio | Parcial: cantidades positivas; agregación no simple | Equipo variable por segmento de instalación y productividad no lineal futura |
| INV-12 | Operación ausente o duplicada dentro del resultado | DB | Sí: unique `(solution, required_operation)` | Lotes productivos necesitan definir si el resultado está en batch y/o miembro sin duplicar trabajo |
| INV-13 | Confundir falta de horizonte con imposibilidad | Dominio + interfaz | Sí para enum; semántica en dominio | Sucesoras de una operación fuera de horizonte deben conservar causa transitiva |
| INV-14 | Resultado reproducible alterado después del cálculo | Dominio + DB | Parcial: inmutabilidad por estado/trigger | Una explicación tardía no debería modificar una solución Ready; crear nueva revisión |
| INV-15 | Dos programas vigentes simultáneos | Transacción + DB | Sí: índice único parcial por plan | Publicación concurrente; cubierto por CD-12 y CD-22 |
| INV-16 | Confirmar escenario basado en plan reemplazado | Transacción | Parcial: FK no alcanza; requiere bloqueo/comparación | También puede quedar obsoleto por ejecución/ausencia sin nueva versión; brecha de revisión global |
| INV-17 | Que simular cambie reservas vigentes | Arquitectura + transacción | Sí por separación de tablas/relaciones y permisos | Evitar que vistas o proyecciones tomen por error la última solución en vez de Current |
| INV-18 | Reescribir hechos ya ejecutados | Dominio + DB | Parcial: append-only/auditoría | Correcciones reales deben ser compensatorias o versionadas; CD-20 |
| INV-19 | Uso encubierto de capacidad extraordinaria | Motor + dominio | Parcial: FK a autorización; alcance temporal y sujeto requiere validación | Autorización específica de proyecto no se comparte con otro; CD-14 |
| INV-20 | Sobreasignar material recibido | Dominio + transacción | Parcial: agregación concurrente requiere bloqueo | Devoluciones pueden volver negativo el disponible, pero no el historial |
| INV-21 | Duplicar recepciones de integración | DB + transacción | Sí: unique `(source_system, idempotency_key)` | Eventos corregidos deben tener nueva clave y referencia al anterior |
| INV-22 | Declarar armado terminado sin herrajes | Dominio | Parcial: estado/gate, no toda la transición | Recibir herrajes no implica terminar; queda trabajo final pendiente |
| INV-23 | Más de un enlace público vigente accidentalmente | DB | Sí: índice único parcial por proyecto | Si en el futuro se permiten varios destinatarios deberá versionarse la política |
| INV-24 | Filtrar información sensible al cliente | Arquitectura + API + pruebas | No mediante un único constraint | Campos JSON libres o textos de novedades pueden filtrar datos; necesitan allowlist y moderación |
| INV-25 | Enviar comunicación sin aprobación | Dominio + integración | Parcial: estados y FK a aprobación | Un reintento del canal tampoco debe saltear aprobación; outbox solo después de aprobar |

### Resultado de la revisión de invariantes

- Las 25 invariantes son pertinentes y no se contradicen.
- INV-5, INV-9, INV-16 e INV-18 revelan brechas concretas del modelo actual.
- INV-24 necesita una estrategia de proyección por allowlist, no solamente permisos.
- Ninguna invariante debería depender exclusivamente de la interfaz.

## 4. Auditoría específica del scheduling

### Separación conceptual

| Concepto | Entidad | Naturaleza |
|---|---|---|
| Qué hay que hacer | `RequiredOperation` | Demanda productiva independiente del plan |
| Resultado para esa demanda en una solución | `OperationPlanResult` | Estado calculado, incluso bloqueado o fuera de horizonte |
| Cuándo se propone hacer | `PlannedOperationAssignment` | Asignación dentro de una solución concreta |
| Fracción temporal programada | `AssignmentSegment` | Intervalo laboral planificado |
| Quién se propone que trabaje | `HumanSegmentAssignment` | Persona concreta por segmento |
| Qué recurso se propone usar | `PhysicalResourceReservation` | Reserva física durante trabajo |
| Qué puesto permanece ocupado | `PhysicalOccupation` | Intervalo continuo, laboral o no |
| Qué ocurrió realmente | `OperationExecution` y `ExecutionSegment` | Hechos de ejecución |
| Quién/recurso se usó realmente | `ActualResourceUsage` | Consumo real, no planificado |

La separación es conceptualmente correcta. Debe mantenerse también en el esquema físico: no conviene una única tabla de “tareas” con columnas planificadas y reales mezcladas.

### Caso numérico de armado

Supuesto: “10 horas” significa 10 horas-persona, de acuerdo con la regla validada de armado.

```text
Día 1: 1 persona x 6 h = 6 h-persona
Día 2: 2 personas x 2 h = 4 h-persona
Total                         10 h-persona
Duración productiva transcurrida: 8 horas de segmentos
```

Representación:

1. Un `RequiredOperation` de Armado con `work_minutes = 600`, equipo mínimo uno y máximo dos.
2. Una asignación dentro de la solución publicada.
3. Dos `AssignmentSegment`: seis horas el Día 1 y dos horas el Día 2.
4. Un `HumanSegmentAssignment` de 360 minutos el Día 1.
5. Dos `HumanSegmentAssignment` de 120 minutos cada uno el Día 2.
6. Una `PhysicalOccupation` del banco desde el comienzo del Día 1 hasta las 12:00 del Día 2, sin interrupción nocturna.
7. Dos `ExecutionSegment` reales con sus usos humanos reales.
8. Liberación exacta a las 12:00, con causa automática por operación configurada o acción de usuario auditada.

El modelo representa correctamente trabajo humano, duración productiva, segmentos y ocupación continua. Debe aclararse en el ajuste lógico que el final de la ocupación es un instante real independiente del final planificado y que una liberación real abierta prevalece sobre propuestas de simulación.

### Simultaneidad de corte y pegado

El modelo la permite porque no existe exclusividad por proyecto ni por centro de trabajo. Dos operaciones pueden superponerse si usan máquinas y personas concretas diferentes y sus precedencias propias lo permiten. Debe agregarse una prueba de aceptación explícita para evitar introducir posteriormente un bloqueo global por centro o proyecto.

### División entre jornadas

`AssignmentSegment` permite varios días y conserva la duración real de cada tramo. Falta representar expresamente la decisión manual que autoriza una fragmentación intradía excepcional. Se recomienda `SchedulingOverride` auditado, con operación, escenario, tipo, autor y motivo.

## 5. Ejecución conceptual de los 22 casos difíciles

### CD-1 — Herrajes como condición de finalización — `BRECHA_MODELO`

- **Entidades:** `RequiredOperation`, `OperationGate COMPLETE`, `HardwareReadiness`, `OperationExecution`, `ExecutionSegment`, `PhysicalOccupation`.
- **Transición:** En ejecución → Esperando insumo → En ejecución → Terminada.
- **Versión/escenario:** los hechos pertenecen a la ejecución del plan vigente; escenarios posteriores los reciben congelados.
- **Recursos:** personas y banco; el banco puede seguir ocupado durante la espera.
- **Persistir:** trabajo realizado, trabajo restante, gate incumplido, ocupación real y posterior liberación.
- **No modificar:** segmentos ejecutados ni versión histórica.
- **Resultado:** representable para ejecución, pero no queda definido cuánto trabajo puede planificarse antes y después del gate. Se requiere fase de operación o partición explícita de trabajo alrededor del gate.

### CD-2 — Banco ocupado sin mano de obra — APTO

- **Entidades:** asignación, segmentos, personas, `PhysicalOccupation`.
- **Transición:** trabajo Día 1 → ocupación sin trabajo → trabajo Día 2 → liberación.
- **Versión/escenario:** cada solución posee ocupación planificada; la ejecución posee ocupación real.
- **Recursos:** Banco 1 y personas solo en segmentos laborales.
- **Persistir:** intervalo continuo y segmentos separados.
- **No modificar:** calendarios para simular ocupación; la ocupación no crea horas trabajadas.
- **Resultado:** representable limpiamente.

### CD-3 — Un proyecto ocupa ambos bancos — APTO

- **Entidades:** proyecto, dos lotes/operaciones, dos asignaciones y dos ocupaciones.
- **Transición:** ambos armados pueden estar En ejecución simultáneamente.
- **Versión/escenario:** misma solución.
- **Recursos:** Banco 1, Banco 2 y equipos humanos no superpuestos.
- **Persistir:** dos ocupaciones independientes con el mismo proyecto.
- **No modificar:** no agregar exclusión por proyecto.
- **Resultado:** apto; falta CA específico.

### CD-4 — Cambio de equipo en instalación — APTO

- **Entidades:** `InstallationWorkPackage`, asignación, segmentos y asignaciones humanas.
- **Transición:** Programada → En ejecución parcial → En ejecución → Terminada.
- **Versión/escenario:** una asignación de una solución; ejecución real separada.
- **Recursos:** tres personas el primer día y dos u otra combinación el siguiente.
- **Persistir:** trabajo-persona aportado por segmento y equipo concreto.
- **No modificar:** trabajo estimado histórico.
- **Resultado:** apto.

### CD-5 — Ventanas discontinuas del cliente — APTO

- **Entidades:** paquete de instalación, ventanas y segmentos.
- **Transición:** trabajo parcial entre ventanas permitidas.
- **Versión/escenario:** solución en evaluación.
- **Recursos:** personas compartidas con producción.
- **Persistir:** dos ventanas y segmentos contenidos.
- **No modificar:** no convertir el intervalo intermedio en capacidad disponible del cliente.
- **Resultado:** apto.

### CD-6 — Recepción parcial compartida — APTO

- **Entidades:** entrega/líneas, requerimientos y asignaciones de material.
- **Transición:** lote habilitado → devolución compensatoria → lote nuevamente bloqueado.
- **Versión/escenario:** el hecho de material cambia; genera evento y escenario, no reescritura del plan.
- **Recursos:** material, sin recurso de capacidad.
- **Persistir:** movimientos originales y compensatorios, asignaciones netas e impacto.
- **No modificar:** recepción histórica original.
- **Resultado:** apto con transacción para evitar sobreasignación.

### CD-7 — Evento duplicado desde Compras — APTO

- **Entidades:** `InboxMessage`, entrega y movimiento.
- **Transición:** recibido → procesado; segundo intento → duplicado reconocido.
- **Versión/escenario:** solo se crea impacto una vez.
- **Recursos:** ninguno.
- **Persistir:** clave idempotente, primer resultado y registro del reintento si se desea.
- **No modificar:** cantidades después del segundo envío.
- **Resultado:** apto.

### CD-8 — Modificación de ruta utilizada — APTO

- **Entidades:** plantilla, versiones, asignación de ruta y operaciones instanciadas.
- **Transición:** versión anterior permanece publicada; nueva versión recibe el cambio.
- **Versión/escenario:** lotes existentes conservan su versión.
- **Recursos:** requerimientos copiados o instanciados de la versión correcta.
- **Persistir:** nueva versión y autoría.
- **No modificar:** pasos/precedencias históricos.
- **Resultado:** apto.

### CD-9 — Cambio de miembros de lote productivo — `BRECHA_MODELO`

- **Entidades:** `ProductionBatch`, miembros, operaciones y solución publicada.
- **Transición:** composición propuesta A → composición B.
- **Versión/escenario:** una versión publicada debe seguir apuntando a la composición A.
- **Recursos:** reserva compartida única.
- **Persistir:** ambas composiciones y motivo del cambio.
- **No modificar:** miembros utilizados por soluciones históricas.
- **Resultado:** el modelo actual no versiona la composición. Se requiere `ProductionBatchVersion` y miembros inmutables por versión.

### CD-10 — Operación fuera del horizonte — APTO

- **Entidades:** escenario, solución, resultados y explicaciones.
- **Transición:** Lista → `OUT_OF_HORIZON`; al ampliar horizonte, nueva solución puede quedar Planned.
- **Versión/escenario:** la primera solución permanece inmutable.
- **Recursos:** se informa el último recurso/intervalo evaluado cuando corresponda.
- **Persistir:** horizonte, resultado y causa transitiva de sucesoras.
- **No modificar:** operación requerida ni solución previa.
- **Resultado:** apto; falta CA explícito.

### CD-11 — Ausencia posterior a simulación — `BRECHA_MODELO`

- **Entidades:** escenario, run, snapshot, indisponibilidad y versión vigente.
- **Transición:** Ready → Stale.
- **Versión/escenario:** puede seguir basada en la misma V5 aunque cambiaron datos planificables.
- **Recursos:** persona ausente y operaciones dependientes.
- **Persistir:** revisión de datos usada y revisión vigente.
- **No modificar:** solución Ready histórica.
- **Resultado:** comparar solo `base_plan_version_id` es insuficiente. Se requiere `PlanningDataRevision` o mecanismo equivalente.

### CD-12 — Dos confirmaciones concurrentes — APTO CON TRANSACCIÓN

- **Entidades:** plan, V5, S18/S19, soluciones y auditoría.
- **Transición:** una simulación Ready → Confirmed; la otra → Stale.
- **Versión/escenario:** solo una crea V6.
- **Recursos:** todos los incluidos en las soluciones.
- **Persistir:** V6, escenario origen y obsolescencia de la otra simulación.
- **No modificar:** V5 ni asignaciones de S19.
- **Resultado:** apto mediante bloqueo y unicidad de Current.

### CD-13 — Operación iniciada frente a prioridad — AJUSTE RECOMENDADO

- **Entidades:** ejecución, segmentos reales, asignación vigente, escenario y resultados Frozen.
- **Transición:** la operación iniciada conserva hechos y restricciones; B cambia solo capacidad libre.
- **Versión/escenario:** escenario basado en plan vigente y estado real.
- **Recursos:** personas, máquina/banco ya comprometidos.
- **Persistir:** alcance concreto del congelamiento.
- **No modificar:** segmentos reales ni recursos ya comprometidos según la política aprobada.
- **Resultado:** `FROZEN` es demasiado agregado para explicar qué quedó bloqueado. Se recomienda `PlanningLock` con alcance.

### CD-14 — Capacidad normal y extraordinaria — APTO

- **Entidades:** calendario, autorización, segmentos y asignaciones humanas.
- **Transición:** capacidad normal consumida → tramo extraordinario autorizado.
- **Versión/escenario:** la autorización pertenece al escenario/alcance y su uso a la solución.
- **Recursos:** persona y, si corresponde, recurso físico.
- **Persistir:** minutos normales y extra separados, autorización y aprobador.
- **No modificar:** calendario normal para “crear” horas extra.
- **Resultado:** apto; normalizar alcance de autorización en esquema físico.

### CD-15 — Habilidad con vigencia — APTO

- **Entidades:** persona, habilidad, habilitación vigente y segmentos.
- **Transición:** no elegible → elegible desde fecha efectiva.
- **Versión/escenario:** cada run evalúa la vigencia en sus segmentos.
- **Recursos:** persona y perforadora.
- **Persistir:** rango de vigencia.
- **No modificar:** catálogo de operación.
- **Resultado:** apto; validar si una habilidad vence dentro de un segmento.

### CD-16 — Recurso fuera de servicio parcialmente — AJUSTE RECOMENDADO

- **Entidades:** indisponibilidad física, política de división, segmentos y escenario.
- **Transición:** intervalo disponible → mantenimiento → disponible.
- **Versión/escenario:** solución propuesta.
- **Recursos:** perforadora y personas.
- **Persistir:** si el usuario autoriza fragmentación intradía, su decisión y motivo.
- **No modificar:** política general de la operación.
- **Resultado:** el cálculo es representable; falta `SchedulingOverride` para la excepción explícita.

### CD-17 — Cambio de fecha y comunicación — AJUSTE RECOMENDADO

- **Entidades:** fecha comunicada, política, recomendación y calendario hábil.
- **Transición:** comparación → advertencia o recomendación → aprobación/rechazo.
- **Versión/escenario:** recomendación vinculada al escenario confirmado o evaluado, según política.
- **Recursos:** calendario comercial, no recursos productivos.
- **Persistir:** ambas fechas, diferencia, calendario y motivo.
- **No modificar:** fecha comunicada hasta aprobación/publicación.
- **Resultado:** falta referencia explícita de `CommunicationPolicy` al calendario usado para días hábiles.

### CD-18 — Regeneración de enlace — APTO

- **Entidades:** enlaces y proyección pública.
- **Transición:** activo anterior → revocado; nuevo → activo.
- **Versión/escenario:** independiente de versiones productivas.
- **Recursos:** ninguno.
- **Persistir:** hash, revocación, autor y nuevo enlace.
- **No modificar:** proyección del proyecto.
- **Resultado:** apto mediante transacción y unicidad parcial.

### CD-19 — Proyección pública y plan interno — `BRECHA_MODELO`

- **Entidades:** escenario, versión, proyección, fecha comunicada y etapas.
- **Transición:** simulación no visible → plan confirmado → recomendación → publicación aprobada.
- **Versión/escenario:** el portal no toma datos de una solución no publicada.
- **Recursos:** ninguno visible públicamente.
- **Persistir:** versión fuente y aprobación.
- **No modificar:** fecha pública ante mera simulación o confirmación sin publicación.
- **Resultado:** falta una regla persistida de mapeo entre hechos internos y etapa pública.

### CD-20 — Corrección de ejecución real — APTO CON REGLA APPEND-ONLY

- **Entidades:** ejecución, segmentos, usos reales y auditoría.
- **Transición:** dato cargado → corrección compensatoria/versionada.
- **Versión/escenario:** no altera versiones históricas; nuevos escenarios leen el neto vigente.
- **Recursos:** personas y recursos reales.
- **Persistir:** original, corrección, autor y motivo.
- **No modificar:** registro original ni estimación utilizada históricamente.
- **Resultado:** apto; formalizar política append-only.

### CD-21 — Reloj y límites diarios — APTO

- **Entidades:** calendarios, intervalos, segmentos y zona horaria.
- **Transición:** agrupación de instantes en días locales.
- **Versión/escenario:** parámetros temporales del run.
- **Recursos:** cualquiera con calendario.
- **Persistir:** instantes con zona/UTC y zona del ámbito.
- **No modificar:** duración real al cambiar la visualización.
- **Resultado:** apto.

### CD-22 — Fallo durante publicación — APTO CON TRANSACCIÓN

- **Entidades:** versiones, escenario, auditoría y outbox.
- **Transición:** intento de publicación → rollback total.
- **Versión/escenario:** V5 sigue Current; escenario sigue Ready/Failed según política.
- **Recursos:** asignaciones no cambian.
- **Persistir:** nada parcial; opcionalmente log técnico fuera de la transacción de dominio.
- **No modificar:** versión vigente y proyección pública.
- **Resultado:** apto.

## 6. Auditoría de simulaciones y versiones

El modelo permite coexistencia de V5, S18, S19 y ejecución real, porque las simulaciones producen soluciones inmutables separadas y la ejecución utiliza entidades propias.

Flujo esperado al confirmar S18:

```text
V5 CURRENT
├── S18 READY -> confirmar -> V6 CURRENT / S18 CONFIRMED
├── S19 READY -> S19 STALE
└── ejecución real originada en V5 -> permanece inmutable

V5 -> SUPERSEDED, pero consultable
```

### Detección de obsolescencia

Se necesitan dos comprobaciones, no una:

1. **Obsolescencia de plan:** `scenario.base_plan_version_id != planning_plan.current_version_id`.
2. **Obsolescencia operativa:** la revisión de datos planificables vigente difiere de la revisión usada por el snapshot del run.

Cambios que incrementan la revisión operativa incluyen:

- inicio, pausa o finalización real;
- liberación/ocupación real de banco;
- ausencia;
- avería;
- recepción o devolución de material;
- liberación/revocación de planos;
- cambio efectivo de duración o prioridad;
- modificación de ventana del cliente;
- autorización/revocación de horas extra.

El hash del snapshot sirve para reproducir, pero no permite detectar eficientemente que apareció un dato nuevo. Se recomienda `PlanningDataRevision` monotónica por ámbito, incrementada transaccionalmente ante cambios relevantes. El escenario conserva `base_data_revision`. Antes de confirmar se validan ambas revisiones y, opcionalmente, se recalcula el hash.

La ejecución real debe conservar `origin_plan_version_id` y `origin_assignment_id` opcional. Así, reemplazar V5 no rompe la trazabilidad de lo efectivamente realizado bajo V5.

## 7. Auditoría de tiempo y calendarios

El modelo distingue calendarios, excepciones, indisponibilidades y autorizaciones, pero le falta el propietario del calendario general de planta.

Separación requerida:

| Concepto | Representación recomendada |
|---|---|
| Calendario general de planta | `Plant`/`PlanningScope` + `PlantCalendarAssignment` |
| Calendario individual | `EmployeeCalendarAssignment` |
| Calendario de máquina/banco | `PhysicalResourceCalendarAssignment` |
| Feriado/cierre general | `CalendarException` del calendario de planta |
| Ausencia personal | `EmployeeUnavailability` |
| Mantenimiento/avería | `PhysicalResourceUnavailability` |
| Horario ordinario | `CalendarWorkingInterval` |
| Capacidad extraordinaria | intervalo adicional + `OvertimeAuthorization` |
| Ocupación fuera de horario | `PhysicalOccupation`, sin generar trabajo ni capacidad |

La disponibilidad laboral efectiva será la intersección del calendario general con el calendario individual/físico, menos indisponibilidades, más capacidad extraordinaria autorizada. La ocupación física no pasa por esa intersección: puede cubrir desde viernes 16:00 hasta lunes 08:00 y bloquear el banco durante todo el rango sin sumar horas trabajadas.

Para “más de un día hábil” se necesita que `CommunicationPolicy` referencie explícitamente el calendario comercial aplicable y su zona horaria.

## 8. Estado público frente a estado interno

`PublicProjectProjection` evita consultar directamente el planificador, pero `PublicStageDefinition` solo define las etapas y no cómo se derivan.

Se recomienda agregar:

### `PublicStageMapping`

Regla versionada y ordenada que transforma hechos internos en una etapa pública. Puede evaluar únicamente un vocabulario permitido:

- hitos alcanzados;
- estados agregados del proyecto/lotes;
- recepción material suficiente;
- existencia de producción iniciada;
- porcentaje de instalación;
- cierre.

No debe ejecutar expresiones libres ni leer nombres de recursos. Cada mapping referencia una versión de configuración y prioridad de evaluación. El generador de proyección aplica estas reglas y guarda qué regla produjo el estado.

Esto permite cambiar en el futuro la correspondencia de las ocho etapas sin modificar el motor de scheduling. El portal solo consume la proyección publicada mediante allowlist.

## 9. Brechas encontradas y modificaciones recomendadas

### BM-1 — Calendario general de planta

Agregar `Plant` o formalizar `PlanningScope` como propietario de calendario, más `PlantCalendarAssignment`. La disponibilidad efectiva debe documentar su intersección con calendarios particulares.

### BM-2 — Versionado de lotes productivos

Agregar `ProductionBatchVersion` y asociar `ProductionBatchMember` a esa versión. Una solución referencia la versión de composición usada. Una composición ya publicada es inmutable.

### BM-3 — Cambios hipotéticos, overrides y fases de operación

Separar:

- `PlanningEvent`: hecho efectivo que ya afecta el estado real;
- `ScenarioChange`: cambio hipotético evaluado solo dentro de un escenario;
- `SchedulingOverride`: autorización explícita como fragmentación intradía.

Para herrajes, agregar `RequiredOperationPhase` o equivalente, con trabajo estimado y gates entre fases. Ejemplo:

```text
Armado físicamente posible
    -> gate herrajes
Terminación de armado
```

Ambas fases pertenecen a la misma operación comercial de armado, pero permiten planificar trabajo antes y después del insumo sin inventar una finalización.

### BM-4 — Revisión de datos planificables

Agregar `PlanningDataRevision` por ámbito y `base_data_revision` en escenario/run. Toda mutación relevante incrementa la revisión. La confirmación valida versión del plan y revisión operativa.

### BM-5 — Origen de la ejecución real

Agregar referencias inmutables opcionales desde `OperationExecution`/`ExecutionSegment` hacia `PlanVersion`, `PlannedOperationAssignment` y `AssignmentSegment` de origen. Debe permitirse ejecución no planificada, por eso las referencias no siempre son obligatorias.

### BM-6 — Derivación pública configurable

Agregar `PublicStageMapping` versionado y registrar en `PublicProjectProjection` la versión/regla aplicada. Vincular `CommunicationPolicy` con un calendario comercial.

### Ajustes menores no bloqueantes

- Agregar `PlanningLock` para documentar qué parte de una operación iniciada queda congelada.
- Formalizar política append-only para ejecución y recepciones.
- Normalizar los alcances de `OvertimeAuthorization` evitando una referencia polimórfica débil.
- Definir cómo se representa capacidad mayor que uno si aparece un recurso compartido no unitario.
- Definir si la corrección de una solución Ready crea otro run o una nueva revisión; no editarla.

## 10. Decisiones arquitectónicas antes del esquema físico

Estas decisiones no cambian reglas de negocio, pero conviene resolverlas al aplicar los ajustes:

1. Elegir `Plant` explícita o reutilizar `PlanningScope` como ámbito de calendario y revisión.
2. Elegir fases de operación frente a dos operaciones enlazadas para el armado antes/después de herrajes. Se recomienda fases para conservar una única operación comercial.
3. Definir el alcance inicial de `PlanningLock`: segmentos ejecutados, inicio, equipo, recurso físico y ocupación.
4. Definir si `PlanningDataRevision` es una secuencia global por planta o revisiones separadas por dominio. Para V1 se recomienda una secuencia por planta.
5. Definir la granularidad de reglas de `PublicStageMapping`: predicados tipados y versionados, no expresiones arbitrarias.
6. Definir el calendario comercial usado en comunicaciones: normalmente calendario de planta, pero con referencia explícita.
7. Elegir una estrategia SQL de rangos temporales y exclusión para recursos unitarios, manteniendo validación de dominio.
8. Decidir cómo almacenar snapshots reproducibles: documento canónico completo, referencia a revisiones o ambos. Se recomienda ambos.

## 11. Conclusión

El modelo lógico cubre la mayor parte del dominio y sus separaciones centrales son correctas. Sin embargo, las brechas BM-1 a BM-6 afectan trazabilidad temporal, versionado histórico, simulaciones hipotéticas, detección de obsolescencia y desacoplamiento del portal. Crear el esquema físico sin resolverlas obligaría a migraciones tempranas o validaciones frágiles.

**`MODELO_REQUIERE_AJUSTES`**

No debe comenzar la Etapa 2 hasta revisar esta auditoría y actualizar explícitamente el modelo lógico con las modificaciones aceptadas.
