# Cierre definitivo del modelo lógico V1

Estado: cierre actualizado después de incorporar estimaciones restantes durante ejecución.  
Alcance: modelo lógico y pruebas conceptuales; no incluye esquema SQL, migraciones, API, frontend ni motor.

## 1. Resumen ejecutivo

Se corrigieron formalmente las seis brechas identificadas en la auditoría y se incorporó el concepto genérico de fases de operación. El modelo ahora permite reconstruir la definición productiva usada por cada cálculo, detectar escenarios obsoletos aunque no cambie el plan vigente, comparar planificación con ejecución real y transformar hechos internos en etapas públicas configurables.

La unidad planificable queda definida así:

```text
Proyecto
└── Lote
    └── Operación requerida
        └── Una o más fases requeridas
            └── Resultado y asignación dentro de cada solución
                └── Segmentos + personas + reservas físicas
```

Las fases no convierten el sistema en seguimiento por piezas o módulos. Solo permiten expresar trabajo productivo separado por una condición intermedia, como Prearmado y Terminación.

Después de reauditar decisiones funcionales, 44 casos de aceptación, 22 casos difíciles y 45 invariantes, no se detectaron brechas lógicas que impidan diseñar el esquema físico.

## 2. Resolución de las seis brechas

| Brecha | Solución adoptada | Justificación V1 |
|---|---|---|
| Calendario general ausente | `Plant`, `PlantCalendarAssignment` y `WorkCenterCalendarAssignment`; intersección con calendarios individuales/físicos | Hace explícito `CALENDARIO_PLANTA` sin fusionar capacidad, trabajo y ocupación |
| Lotes productivos mutables | `ProductionBatchVersion` con miembros inmutables | Mantiene composición histórica y una única reserva compartida |
| Eventos, hipótesis y excepciones mezclados | `EffectiveEvent`, `SimulationHypothesis`, `ManualException`, más `PlanningLock` | Una hipótesis no cambia realidad; una excepción tiene autorización y alcance |
| Escenario obsoleto no detectable | `PlanningStateRevision` monotónica y `PlanningStateChange` | Evita comparar decenas de timestamps; complementa versión base del plan |
| Ejecución sin origen planificado | Referencias opcionales desde ejecución/segmentos a versión, resultado y segmento previstos | Admite ejecución espontánea y comparación plan-real sin reescribir historia |
| Estado público sin derivación | `PublicStageMappingSet` y `PublicStageMappingRule` versionados | Desacopla completamente portal, motor y estados técnicos |

## 3. Versionado de la definición productiva

Se adoptó `ProductDefinitionRevision` como snapshot canónico inmutable por planta.

Incluye:

- proyectos y lotes;
- cantidades relevantes;
- rutas/versiones;
- operaciones y fases;
- precedencias y gates;
- requerimientos físicos, humanos y de habilidades;
- estimaciones y políticas de división.

Los datos corrientes continúan normalizados. El snapshot no se usa como base operativa editable, sino como evidencia reproducible del cálculo.

Una hipótesis que modifica definición genera una revisión derivada antes de ejecutar el escenario:

```text
D12 efectiva
└── D13 derivada para S18
    ├── S18 rechazada -> D13 queda histórica
    └── S18 confirmada -> D13 pasa a ser la revisión efectiva
```

El escenario conserva su revisión productiva base; cada run y solución conserva la revisión de entrada exacta, que puede ser una derivación hipotética. La versión publicada referencia la misma revisión exacta de la solución confirmada. El hash canónico permite verificar integridad.

Esta estrategia es más simple para V1 que versionar individualmente cada fila de todas las entidades, pero permite reconstrucción histórica completa.

## 4. Fases de operación y esperas

`RequiredOperation` contiene una o más `RequiredOperationPhase`. Cada fase define su propio trabajo, recursos, política de división y gates.

Ejemplo validado:

```text
Armado
├── Prearmado: 6 h-persona, personas + banco
├── Espera: 0 h-persona, banco opcionalmente ocupado
└── Terminación: 4 h-persona, gate herrajes + personas + banco
```

La espera no es una fase de trabajo ni una asignación. Surge por diferencia entre el final de una fase y la liberación de la siguiente. Puede coexistir con una `PhysicalOccupation` abierta.

Para operaciones simples se genera una única fase. V1 utiliza orden secuencial por `sequence_no`, evitando un grafo interno innecesario.

## 5. Cambios realizados en el modelo

### Nuevas entidades o conceptos

- `Plant`.
- `PlantCalendarAssignment`.
- `WorkCenterCalendarAssignment`.
- `RequiredOperationPhase`.
- `RouteStepPhaseTemplate`.
- `PhasePlanResult`.
- `PlannedPhaseAssignment`.
- `ProductDefinitionRevision`.
- `ProductionBatchVersion`.
- `EffectiveEvent`.
- `SimulationHypothesis`.
- `ManualException`.
- `PlanningLock`.
- `PlanningStateRevision`.
- `PlanningStateChange`.
- `PublicStageMappingSet`.
- `PublicStageMappingRule`.
- `RemainingEstimateRevision`.
- `RemainingResourceEstimate`.

### Relaciones modificadas

- Requerimientos humanos, físicos y gates pueden pertenecer a una fase.
- Cada paso de ruta define al menos una plantilla de fase que se instancia sin alterar la versión histórica.
- Las asignaciones concretas se realizan sobre fases o versiones de lote productivo.
- Escenarios referencian versión base, revisión operativa y revisión productiva.
- Soluciones y versiones publicadas conservan las revisiones exactas utilizadas.
- Ejecución y segmentos reales referencian opcionalmente planificación de origen.
- La proyección pública registra mapping set y regla aplicados.
- La política de comunicación referencia un calendario comercial.
- El resultado de fase referencia la revisión de estimación restante usada para calcular su trabajo futuro.

### Cardinalidades relevantes

- `RequiredOperation 1:N RequiredOperationPhase`, mínimo una.
- `OperationPlanResult 1:N PhasePlanResult`.
- `PhasePlanResult 0..1:1 PlannedPhaseAssignment`.
- `ProductionBatch 1:N ProductionBatchVersion`.
- `ProductionBatchVersion 1:N ProductionBatchMember`.
- `Plant 1:N ProductDefinitionRevision`.
- `Plant 1:N PlanningStateRevision`.
- `Scenario N:1 PlanVersion + PlanningStateRevision + ProductDefinitionRevision`.
- `PublicStageMappingSet 1:N PublicStageMappingRule`.
- `OperationExecution 1:N RemainingEstimateRevision`.
- `RemainingEstimateRevision 1:N RemainingResourceEstimate`.

## 6. Invariantes nuevas o modificadas

Las 25 invariantes originales se conservan, con estos ajustes:

- INV-5 aplica gates por fase.
- INV-9 usa intersección planta/centro/persona o recurso.
- INV-12 exige resultados de operación y fases.
- INV-16 valida versión vigente y revisión operativa.
- INV-18 conserva ejecución y referencias al plan de origen.

Se agregaron INV-26 a INV-37:

| Invariante | Garantía |
|---:|---|
| INV-26 | Toda operación tiene al menos una fase y el trabajo total es la suma de fases |
| INV-27 | Las fases respetan orden y gates |
| INV-28 | La espera no consume trabajo ni capacidad; puede mantener ocupación |
| INV-29 | La revisión productiva usada por una solución es inmutable e íntegra |
| INV-30 | Toda solución identifica revisiones productiva y operativa |
| INV-31 | Una hipótesis solo afecta su escenario |
| INV-32 | Toda excepción efectiva tiene alcance, vigencia, autorización y motivo |
| INV-33 | Cambio de versión o revisión vuelve Stale al escenario |
| INV-34 | Ejecución independiente o vinculada conserva historia del plan |
| INV-35 | Composición publicada de lote productivo es inmutable |
| INV-36 | El portal obtiene etapa mediante mapping versionado |
| INV-37 | Cada transacción relevante incrementa una única revisión y detalla cambios |

La regla adicional de estimación restante incorporó INV-38 a INV-45 para garantizar estimación original inmutable, ejecución append-only, total actualizado, revisiones históricas del restante, separación de demanda futura por tipo de recurso y reprogramación siempre confirmada.

Las excepciones manuales no pueden dispensar invariantes físicas no negociables, como doble reserva o habilidad inexistente.

## 7. Casos de aceptación incorporados

Se agregaron los ocho casos recomendados por la auditoría:

| Caso | Cobertura | Resultado conceptual |
|---|---|---|
| CA-25 | Armado en fases y herrajes | Aprobado: Prearmado trabaja; Terminación espera herrajes |
| CA-26 | Corte y pegado simultáneos | Aprobado con máquinas/personas distintas |
| CA-27 | Un proyecto en dos bancos | Aprobado; exclusividad solo por banco concreto |
| CA-28 | División entre jornadas | Aprobado; fragmentación intradía requiere excepción |
| CA-29 | `OUT_OF_HORIZON` | Aprobado; no equivale a imposible |
| CA-30 | Fechas de hitos por solución | Aprobado; las fechas coexisten sin sobrescritura |
| CA-31 | Recomendación de comunicación | Aprobado con calendario comercial y autorización humana |
| CA-32 | Ejecución vinculada al plan | Aprobado con referencias históricas opcionales |

Se agregaron además cuatro casos exigidos directamente por las correcciones:

- CA-33: obsolescencia por cambio de revisión operativa.
- CA-34: aislamiento de hipótesis.
- CA-35: reconstrucción mediante revisión productiva.
- CA-36: mapping público configurable.

La regla de actualización durante ejecución agregó:

- CA-37: demora superior a la estimación original.
- CA-38: finalización anticipada.
- CA-39: actualización simple del restante.
- CA-40: conflicto por extensión.
- CA-41: impacto en fecha estimada.
- CA-42: banco extendido durante la noche.
- CA-43: segmentos ejecutados inmutables.
- CA-44: rechazo de la reprogramación.

El conjunto queda en 44 casos de aceptación.

## 8. Revisión de los 22 casos difíciles

Los 22 casos fueron recorridos nuevamente. Resultado:

- 22 representables con el modelo corregido.
- 0 casos marcados `BRECHA_MODELO`.
- CD-1 utiliza fases y ocupación independiente.
- CD-9 utiliza versión de lote productivo.
- CD-11 utiliza revisión operativa.
- CD-13 utiliza `PlanningLock` y ejecución append-only.
- CD-16 utiliza excepción manual para fragmentación intradía.
- CD-17 utiliza calendario comercial explícito.
- CD-19 utiliza mapping público versionado.

La resolución completa quedó registrada también en `docs/04-casos-dificiles-modelo.md`.

## 9. Reauditoría de simulaciones y versiones

Pueden coexistir:

```text
V5 CURRENT / definición D12 / estado R120
├── S18 READY sobre V5-D12-R120
├── S19 READY sobre V5-D12-R120
└── ejecución real originada en V5
```

Si una ausencia efectiva crea R121, ambos escenarios pasan a Stale aunque V5 continúe Current.

Si no hubo otro cambio y se confirma S18:

1. se valida V5 y R120;
2. se materializan solamente hipótesis aprobadas;
3. se adopta la revisión productiva derivada si corresponde;
4. se crea la revisión operativa resultante;
5. V5 pasa a Superseded;
6. V6 se crea Current;
7. S18 pasa a Confirmed;
8. S19 pasa a Stale;
9. la ejecución real de V5 conserva su origen.

La publicación es atómica; un fallo revierte cambios de versión, revisiones, auditoría y outbox.

## 10. Reauditoría de tiempo y capacidad

La capacidad laboral efectiva se deriva de:

```text
planta ∩ centro ∩ persona/recurso
- indisponibilidades
+ capacidad extraordinaria autorizada
```

Se mantienen separados:

- capacidad potencial;
- asignación planificada;
- trabajo ejecutado;
- ocupación física.

Por lo tanto, un banco ocupado desde el viernes 16:00 hasta el lunes 08:00 bloquea el recurso sin producir horas-persona ni utilización laboral durante el fin de semana.

## 11. Reauditoría del portal público

El flujo corregido es:

```text
hechos internos aprobados
    -> PublicStageMappingRule versionada
    -> PublicProjectProjection con allowlist
    -> portal público de solo lectura
```

Cambiar reglas comerciales de presentación no cambia rutas, operaciones ni scheduling. La fecha comunicada solo cambia mediante publicación autorizada. Una recomendación nunca envía automáticamente.

## 12. Contradicciones buscadas

No se encontraron contradicciones nuevas bloqueantes.

Puntos revisados expresamente:

- Modelar herrajes como gate de inicio de Terminación respeta la regla “Armado no termina sin herrajes”, porque Prearmado continúa permitido y Armado solo termina al concluir todas sus fases.
- Una fase no equivale a lote, módulo ni pieza; no amplía indebidamente el alcance de V1.
- `PlanningStateRevision` no reemplaza `PlanVersion`: una representa realidad operativa y la otra programa publicado.
- `ProductDefinitionRevision` no reemplaza el modelo normalizado: congela la entrada histórica del cálculo.
- Una hipótesis de horas extra no constituye autorización efectiva hasta la confirmación.
- La ocupación física no se intersecta con calendarios laborales y no genera carga productiva.

## 13. Riesgos residuales

No bloquean el esquema físico, pero deberán tratarse en la Etapa 2:

- Elegir constraints temporales de PostgreSQL para reservas unitarias y ocupaciones abiertas.
- Evitar carreras al incrementar `PlanningStateRevision` y asignar materiales.
- Definir serialización canónica y tamaño máximo razonable del snapshot productivo.
- Diseñar el vocabulario seguro de predicados para mappings públicos.
- Diseñar referencias normalizadas para los distintos alcances de excepciones y horas extra.
- Garantizar inmutabilidad mediante permisos/constraints, además de disciplina de aplicación.
- Definir política de correcciones append-only para ejecución y eventos efectivos.
- Asegurar que una ejecución iniciada durante un escenario Ready lo vuelva obsoleto inmediatamente.

## 14. Decisiones diferidas a versiones futuras

- Múltiples plantas operativas simultáneas, aunque la entidad ya existe.
- Recursos con capacidad acumulada mayor a uno; V1 usa unidades concretas.
- Grafo interno de fases; V1 usa secuencia lineal.
- Inventario detallado y costos.
- Optimización matemática global.
- Setup automático y formación óptima de lotes productivos.
- Seguimiento por módulo o pieza.
- Productividad no lineal aprendida de históricos.
- Varios enlaces públicos activos por destinatario.
- Expresiones avanzadas de mapping público; V1 usa predicados tipados.

## 15. Archivos de la Etapa 1.6

Modificados:

- `docs/02-casos-aceptacion-planificador.md`.
- `docs/03-modelo-logico-v1.md`.
- `docs/04-casos-dificiles-modelo.md`.
- `README.md`.
- `docs/07-ajuste-estimacion-restante-v1.md`.

Creado:

- `docs/06-cierre-modelo-logico-v1.md`.

La auditoría original `docs/05-auditoria-modelo-logico-v1.md` se conserva sin reescribir su conclusión histórica.

## 16. Conclusión final

Las seis brechas fueron resueltas en el modelo, las fases permiten representar trabajo antes y después de insumos sin convertir esperas en carga, y la reauditoría no encontró inconsistencias bloqueantes.

**`MODELO_APTO_PARA_ESQUEMA_FISICO`**

El trabajo debe detenerse aquí. El siguiente incremento, sujeto a aprobación separada, es **Etapa 2 — Diseño del esquema físico PostgreSQL**.
