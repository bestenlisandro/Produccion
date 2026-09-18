# Ajuste de estimación restante durante ejecución

Estado: regla funcional incorporada y reauditada antes del esquema físico.

## 1. Objetivo

Permitir actualizar con mínima fricción el trabajo o tiempo que resta de una operación en ejecución, medir el impacto y proponer una reprogramación sin alterar silenciosamente el plan vigente.

```text
actualizar restante
-> evento efectivo + nueva revisión operativa
-> detectar impacto
-> simular
-> comparar
-> confirmar o rechazar
```

## 2. Magnitudes separadas

Para cada operación/fase en ejecución se conservan:

| Magnitud | Fuente | Mutabilidad |
|---|---|---|
| Estimación original | `ProductDefinitionRevision` | Inmutable |
| Trabajo ejecutado | `ExecutionSegment` y `ActualResourceUsage` | Append-only/compensatorio |
| Restante informado | `RemainingEstimateRevision` | Inmutable; una corrección crea otra revisión |
| Total actualizado al corte | Ejecutado al corte + restante informado | Derivado y reproducible |

Ejemplo al momento de actualización:

```text
Original:              10 h-persona
Ejecutado al corte:     7 h-persona
Restante informado:     5 h-persona
Total actualizado:     12 h-persona
```

`RemainingEstimateRevision` guarda `cutoff_at` y el acumulado ejecutado usado. El restante operativo posterior puede derivarse restando el trabajo real compatible registrado desde el corte. Esa derivación no modifica la revisión original; una nueva evaluación humana crea otra revisión.

No se suman magnitudes incompatibles. Horas-persona, duración activa de máquina y ocupación física se presentan por separado.

## 3. Entidades incorporadas

### `RemainingEstimateRevision`

Pronóstico append-only vinculado a ejecución y operación, con identificación de la fase activa al corte. Conserva:

- revisión anterior;
- fecha de corte;
- estimación original referenciada;
- ejecutado acumulado al corte;
- restante informado;
- total actualizado al corte;
- modo y valor bruto de ingreso;
- autor y motivo;
- evento efectivo;
- `PlanningStateRevision` resultante.

Solo una revisión es vigente por ejecución/fase, sin eliminar las anteriores.

### `RemainingResourceEstimate`

Detalle de demanda futura que identifica la fase correspondiente. Distingue:

1. `LABOR_WORK`: horas-persona, habilidad y equipo previsto.
2. `ACTIVE_PHYSICAL_USE`: tiempo activo futuro de máquina, banco o recurso.
3. `PHYSICAL_OCCUPATION`: liberación prevista de un banco o recurso, aunque no exista trabajo.

Puede referenciar requerimientos genéricos o recursos concretos ya comprometidos. En operaciones multifase, la revisión reúne los detalles restantes de todas las fases incompletas; las fases no modificadas conservan su estimación vigente. Cambiar un detalle no altera implícitamente los otros.

### Relaciones con el planificador

- `PhasePlanResult.remaining_estimate_revision_id` identifica el pronóstico usado.
- `SchedulingRun` conserva el snapshot completo con esa revisión.
- `PlanningStateRevision` detecta cualquier escenario calculado con un pronóstico anterior.
- `PlanningLock` protege segmentos ya ejecutados y demás decisiones congeladas.

## 4. Formas de actualización futuras

El modelo soporta estas entradas sin imponer todavía una interfaz:

- extender 30 minutos;
- extender una, dos u otra cantidad de horas;
- reducir el restante;
- ingresar trabajo restante;
- ingresar hora estimada de finalización;
- fijar liberación estimada de banco;
- arrastrar el final en un Gantt.

Todas se normalizan a una revisión con unidad, dimensión, fecha de corte y valor bruto de origen. Si una hora final atraviesa pausas o períodos no laborales, la conversión debe usar calendarios y mostrar una previsualización; no se transforma silenciosamente en horas productivas.

## 5. Impacto sobre recursos

La actualización indica explícitamente qué dimensiones cambian.

Ejemplos:

| Situación | Trabajo humano | Uso activo | Ocupación física |
|---|---:|---:|---:|
| Trabajo adicional con misma máquina | Aumenta | Aumenta | Puede aumentar |
| Mueble esperando sobre banco | No aumenta | No aumenta | Aumenta |
| Retrabajo manual fuera del banco | Aumenta | Según recurso | No necesariamente |
| Finalización anticipada | Disminuye a cero | Puede liberarse | Puede liberarse por evento real |

El centro de trabajo condiciona calendarios y capacidad agregada, pero las reservas se prolongan sobre personas y recursos físicos concretos o requerimientos equivalentes. Una prolongación propuesta nunca crea una doble reserva válida: el conflicto debe aparecer en la simulación.

## 6. Flujo de reprogramación

1. El usuario registra el nuevo restante.
2. Se crea `RemainingEstimateRevision` y `EffectiveEvent(REMAINING_ESTIMATE_UPDATED)`.
3. La transacción incrementa `PlanningStateRevision`.
4. Escenarios Ready basados en la revisión anterior quedan `STALE`.
5. El detector identifica futuras reservas insuficientes, conflictos, sucesoras, proyectos competidores e hitos.
6. Se crea una simulación sobre el plan Current y la nueva revisión operativa.
7. La solución conserva hechos ejecutados y recalcula únicamente demanda futura.
8. La comparación muestra recursos, operaciones, proyectos, hitos, compromiso y horas extra afectados.
9. Confirmar crea una nueva versión del plan.
10. Rechazar conserva la versión anterior Current.

Rechazar no borra el nuevo pronóstico, porque este representa conocimiento operativo real. El sistema mantiene una advertencia de plan desactualizado/conflictivo hasta que se confirme otra solución o cambie nuevamente la situación.

## 7. Finalización anticipada

Una finalización real crea su evento efectivo, registra el trabajo ejecutado final y deja restante cero. Las reservas futuras del plan anterior no se borran directamente: un escenario propone liberarlas y adelantar trabajo dependiente. De esta manera también una mejora respeta el flujo de confirmación.

## 8. Resultado de los ocho casos solicitados

| Caso | Entidades principales | Resultado conceptual |
|---|---|---|
| CA-37 Demora | Ejecución + revisión restante | Original 10, ejecutado 7, restante 5, total 12; plan sin cambios |
| CA-38 Termina antes | Ejecución + evento efectivo | Restante cero y liberación futura propuesta en escenario |
| CA-39 Actualización simple | Revisión restante + detalle de recursos | Modos de entrada normalizados y auditables |
| CA-40 Conflicto | Detalle físico + reservas + impacto | Conflicto visible; ninguna actividad se mueve sin confirmar |
| CA-41 Fecha estimada | Solución + hitos + comparación | Nueva fecha calculada; compromiso/comunicación sin sobrescribir |
| CA-42 Banco nocturno | Ocupación física | Bloqueo continuo sin horas-persona |
| CA-43 Segmentos ejecutados | Ejecución + lock | Hechos intactos; solo cambia futuro propuesto |
| CA-44 Rechazo | Escenario + PlanVersion | Plan anterior Current; pronóstico y advertencia permanecen |

Los ocho casos son representables sin cambiar las reglas de versiones, capacidad o ejecución aprobadas.

## 9. Invariantes agregadas

- INV-38: estimación original inmutable.
- INV-39: ejecutado derivado de hechos reales, no editable por pronóstico.
- INV-40: total actualizado calculado con unidad y fecha de corte compatibles.
- INV-41: una revisión vigente por ejecución y todas las anteriores auditables.
- INV-42: actualizar restante incrementa revisión operativa, no versión del plan.
- INV-43: trabajo humano, uso activo y ocupación cambian independientemente.
- INV-44: segmentos ejecutados se preservan en toda propuesta.
- INV-45: rechazar mantiene plan Current y conserva el pronóstico real.

## 10. Reauditoría breve

### Definición productiva

Consistente. La estimación original continúa dentro de la revisión productiva congelada. La actualización durante ejecución no genera una falsa modificación histórica.

### Ejecución real

Consistente. Los segmentos y usos reales son la única fuente de trabajo ejecutado. El pronóstico solo describe futuro.

### Scheduling

Consistente. La fase activa usa una revisión de restante concreta; los hechos están congelados y la solución propone nuevos segmentos futuros.

### Simulaciones y versiones

Consistente. El evento incrementa la revisión operativa y vuelve obsoletos escenarios anteriores. El plan vigente cambia únicamente al confirmar.

### Recursos y calendarios

Consistente. Cada dimensión de demanda futura se calcula por separado. La ocupación física puede atravesar períodos sin capacidad laboral.

### Portal público

Consistente. La actualización interna no se publica directamente. Solo un plan confirmado y una decisión de publicación pueden actualizar proyección o recomendar comunicación.

### Contradicciones

No se detectaron contradicciones con fases, gates, operaciones iniciadas, bancos, horas extraordinarias, fechas comunicadas ni definición productiva versionada.

## 11. Riesgos residuales para el esquema físico

- Garantizar de forma transaccional una única revisión restante vigente.
- Definir unidades y redondeos sin mezclar minutos-persona con duración transcurrida.
- Convertir hora de finalización a trabajo restante cuando existen pausas, calendarios o equipos variables.
- Definir constraints para ocupaciones físicas con final abierto.
- Marcar rápidamente escenarios obsoletos cuando se registra ejecución posterior al corte.
- Evitar que acciones rápidas oculten qué recursos se extienden; la previsualización deberá mostrarlo.

Estos riesgos requieren decisiones físicas y de aplicación, pero no una nueva entidad lógica bloqueante.

## 12. Conclusión

La nueva regla queda representada sin sobrescribir estimaciones originales, ejecución ni programa vigente. El modelo distingue correctamente trabajo futuro, uso activo y ocupación física, y conserva el flujo de simulación y confirmación.

**`MODELO_APTO_PARA_ESQUEMA_FISICO`**

No se inicia la Etapa 2 en este documento.
