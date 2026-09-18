# Etapa 2.1 — Validación de facilidad de reprogramación V1

## 1. Objetivo y conclusión ejecutiva

Esta auditoría valida si el esquema físico de 107 tablas permite implementar una experiencia cotidiana de reprogramación simple antes de crear migraciones.

La conclusión es positiva: el esquema ya separa correctamente el hecho operativo, la intención del usuario, la solución simulada y el plan publicado. No se requieren tablas ni columnas adicionales. La facilidad de uso deberá resolverse mediante comandos de aplicación; la interfaz no escribirá directamente revisiones, segmentos, reservas, soluciones ni punteros de versión.

El flujo obligatorio para cualquier cambio es:

> comando simple → validación inmediata → escenario aislado → cálculo de impactos → comparación → confirmación o rechazo

Para una operación en ejecución hay una precisión importante: el nuevo tiempo restante es un hecho operativo efectivo y se conserva aunque luego se rechace la propuesta de reprogramación. Lo que el rechazo conserva intacto es el **plan vigente**, no una estimación que el usuario ya declaró verdadera.

## 2. Frontera de comandos

Los siguientes nombres son contratos de la capa de aplicación, no tablas ni estados de interfaz. Cada comando recibe un identificador de idempotencia, actor, planta, fecha de solicitud y versión esperada del agregado que modifica.

| Comando | Uso permitido | Resultado de negocio |
|---|---|---|
| `UPDATE_REMAINING_ESTIMATE` | Operación en ejecución | Registra una nueva estimación restante efectiva, incrementa `PlanningStateRevision`, invalida escenarios incompatibles y genera una simulación de impacto |
| `RESIZE_SCHEDULED_ACTIVITY` | Actividad futura; si está en ejecución se deriva al comando anterior | Crea una hipótesis de cambio de duración o fin dentro de un escenario; no modifica el plan vigente |
| `MOVE_SCHEDULED_ACTIVITY` | Actividad futura no bloqueada | Crea una hipótesis de nueva ubicación temporal y evalúa factibilidad; no mueve reservas vigentes |
| `REPLAN_FROM_OPERATION` | Operación raíz existente | Recalcula el cierre transitivo afectado desde esa operación, preservando hechos y bloqueos anteriores |
| `REPLAN_PROJECT` | Proyecto existente | Recalcula el alcance del proyecto y las operaciones externas afectadas por recursos o dependencias |
| `ACCEPT_REPLAN` | Escenario `Ready`, vigente y factible | Promueve atómicamente la solución a una nueva versión del plan |
| `REJECT_REPLAN` | Escenario no confirmado | Rechaza la propuesta sin cambiar `planning_plans.current_version_id` |

### 2.1 Modos de entrada normalizados

Los atajos `+30 min`, `+1 h` y `+2 h`, el nuevo restante, la nueva hora de fin y el arrastre de Gantt son formas de entrada. La capa de aplicación los transforma en una intención canónica con:

- modo de entrada y valor bruto;
- instante de corte;
- objetivo temporal solicitado;
- dimensiones que cambian: trabajo humano, uso físico activo u ocupación física;
- alcance y motivo;
- versión base sobre la que actuó el usuario.

Una nueva hora de fin no se convierte restando horas de reloj sin más. Debe interpretarse con calendarios, pausas, continuidad, habilidad, equipo y recurso físico. La previsualización muestra el equivalente productivo calculado antes de confirmar la estimación efectiva.

## 3. Flujo de cada comando y entidades afectadas

### 3.1 `UPDATE_REMAINING_ESTIMATE`

1. Verifica que exista una `operation_execution` en ejecución y toma un lock de aplicación sobre ella y sobre `planning_state_heads`.
2. Calcula lo ejecutado hasta `cutoff_at` exclusivamente desde `execution_segments` y `actual_resource_usages`; nunca lo recibe como verdad editable desde la pantalla.
3. Interpreta `input_mode` (`delta`, `remaining_duration`, `expected_finish`) y conserva `raw_input`.
4. Exige declarar o derivar explícitamente qué dimensiones cambian. No extiende por defecto todos los recursos.
5. En una sola transacción crea `effective_event`, `planning_state_revision`, sus `planning_state_changes`, `remaining_estimate_revision` y sus `remaining_resource_estimates`; sustituye técnicamente la revisión restante anterior.
6. Marca como `Stale` los escenarios cuyas bases dejaron de coincidir.
7. Crea un escenario basado en el plan vigente y la nueva revisión operativa, incorpora el evento en `scenario_effective_events` y ejecuta el análisis.
8. Devuelve inmediatamente la revisión aceptada y un estado de simulación; cuando termina el cálculo devuelve comparación, conflictos y propuesta.

Entidades principales: D060–D064, D070, D072–D083 y D085–D090.

### 3.2 `RESIZE_SCHEDULED_ACTIVITY`

1. Lee la actividad desde la solución de la versión vigente y verifica que no esté ejecutada ni protegida por un `PlanningLock`.
2. Normaliza el nuevo fin o duración y crea un `scenario` con una `simulation_hypothesis` de tipo `RESIZE_ACTIVITY`.
3. Ejecuta una comprobación rápida de rango, calendarios, precedencias, gates, recurso concreto y bloqueos.
4. Si la posición pedida es imposible, puede calcular una propuesta asistida en el primer intervalo factible o declarar el bloqueo concreto.
5. Ejecuta el motor sobre el alcance afectado y produce una solución inmutable y una comparación.

No se actualizan `planned_phase_assignments`, `assignment_segments`, asignaciones humanas ni reservas del plan vigente. Todas las filas nuevas pertenecen a la solución propuesta.

Entidades principales: D068–D082; D073–D074 para el impacto. Una actividad en ejecución se redirige a `UPDATE_REMAINING_ESTIMATE`.

### 3.3 `MOVE_SCHEDULED_ACTIVITY`

1. Recibe la actividad y el rango objetivo del arrastre.
2. Valida base vigente, condición futura, restricciones duras y permisos.
3. Crea una hipótesis `MOVE_ACTIVITY` con el rango solicitado y la política de anclaje (`exact`, `earliest_at_or_after` o `suggest_nearest`).
4. El motor conserva duración productiva y requerimientos, intenta la posición solicitada y, según la política, ofrece una alternativa asistida.
5. Genera solución, impactos y explicación sin tocar la versión actual.

Entidades principales: D069–D082. Los hechos ejecutados D085–D088 y bloqueos son entradas inmutables.

### 3.4 `REPLAN_FROM_OPERATION`

1. Crea un escenario con alcance raíz `required_operation_id` en `scenarios.parameters` y una hipótesis `REPLAN_FROM_OPERATION`.
2. Construye el cierre transitivo por precedencias, lotes, gates, ocupaciones compartidas, hitos y competencia por recursos.
3. Congela hechos ya ejecutados y, según política, actividades anteriores no afectadas.
4. Recalcula el subconjunto necesario y registra en `impact_items` toda actividad o proyecto incorporado fuera de la raíz.

Entidades principales: D070–D082 más rutas, precedencias, fases, materiales, planos, hitos y calendarios usados como entrada.

### 3.5 `REPLAN_PROJECT`

Es equivalente al comando anterior con `project_id` como raíz. El límite inicial es el proyecto, pero no se presume aislamiento: el análisis debe incluir otros proyectos desplazados por recursos, lotes compartidos o dependencias. La comparación distingue impacto directo, propagado y externo.

### 3.6 `ACCEPT_REPLAN`

1. Verifica que el escenario esté `Ready`, tenga una única solución factible seleccionada y que sus tres bases sigan vigentes.
2. Bloquea plan, estado de planificación y planta en el orden definido.
3. Revalida conflictos contra hechos reales ocurridos después del cálculo.
4. Materializa únicamente las hipótesis que deban convertirse en decisiones reales.
5. Cierra la vigencia de la versión anterior, crea una nueva `plan_version`, actualiza `current_version_id` y registra promoción, auditoría y outbox en un único commit.

Entidades principales: D060–D061, D068–D083, D103–D104. Un fallo revierte todo.

### 3.7 `REJECT_REPLAN`

1. Cambia el escenario a rechazado y registra actor, instante y motivo.
2. No crea versión, no cambia `current_version_id` y no materializa hipótesis.
3. Conserva soluciones e impactos para auditoría.
4. Si el escenario nació de `UPDATE_REMAINING_ESTIMATE`, la revisión restante efectiva permanece vigente porque representa la realidad operativa; la pantalla debe advertir que el plan publicado quedó pendiente de reconciliación.

## 4. Información visible para el usuario

La comparación debe presentar, en lenguaje operativo:

- valor anterior y valor solicitado;
- hora planificada anterior y propuesta;
- actividades que se desplazan y magnitud del cambio;
- personas, bancos, máquinas o centros críticos;
- precedencia, calendario, material, plano, gate o bloqueo que impide una posición;
- proyectos e hitos afectados;
- paquetes de instalación y ventanas del cliente afectados;
- cambio de fecha estimada de entrega y diferencia contra la fecha ya comunicada al cliente;
- ocupación física que continúa sin trabajo humano;
- alcance calculado y elementos que quedan fuera del horizonte;
- estado `calculando`, `factible`, `factible con desplazamientos`, `no factible` u `obsoleto`;
- acciones inequívocas: confirmar propuesta, rechazarla o editar la hipótesis.

Una demora efectiva rechazada no debe desaparecer visualmente: se muestra “estimación actualizada; programa vigente aún no reconciliado”.

## 5. Información interna que la interfaz debe ocultar

La pantalla no necesita exponer:

- UUID, números internos de revisión, hashes o claves transaccionales;
- filas de `assignment_segments`, reservas o ocupaciones técnicas;
- IDs de run, solución, versión productiva o evento efectivo;
- locks, exclusiones GiST, control optimista o estado de outbox;
- snapshots canónicos, payloads `jsonb` y diagnósticos crudos del algoritmo.

Estos datos permanecen disponibles para auditoría y soporte. La UI puede mostrar un código de escenario legible y un detalle técnico descargable solo a usuarios autorizados.

## 6. Detección de conflictos

La detección se divide en dos niveles sin comprometer la confirmación:

### 6.1 Validación inmediata

Debe responder con baja latencia y detectar:

- actividad inexistente, ya terminada, en ejecución o bloqueada;
- versión base obsoleta;
- rango inválido o fuera de horizonte;
- precedencias y gates evidentes;
- falta de calendario o habilidad vigente;
- solapamiento de persona o recurso exclusivo concreto;
- ocupación física real incompatible;
- indisponibilidad y autorización de horas extraordinarias;
- material, plano, paquete de instalación o ventana del cliente no disponibles.

### 6.2 Validación completa del planificador

Evalúa alternativas de recursos y equipo, capacidad acumulativa, propagación por el grafo, lotes, hitos, instalación, prioridad, pausas, ocupación continua, proyectos competidores y diferencia contra fechas comunicadas. Una respuesta rápida positiva significa “candidato válido para simular”, no autorización para escribir el plan.

La confirmación repite las validaciones críticas contra el estado vigente; una propuesta obsoleta nunca se promueve.

## 7. Simulación y reubicación asistida

Cada intento crea un escenario aislado con sus bases. `simulation_hypotheses.parameters` conserva la intención normalizada y `scenarios.parameters` el alcance, política de reubicación y origen del comando. Los contratos JSON se versionarán y validarán en la capa de dominio antes de persistirlos.

La reubicación asistida sigue este orden:

1. intenta exactamente el rango pedido;
2. identifica la primera restricción dura;
3. busca el intervalo factible más cercano según la política elegida;
4. recalcula el efecto en cascada;
5. devuelve posición sugerida y diferencias respecto del plan actual.

`impact_analyses` contiene el resumen y la comparación; `impact_items` conserva cambios por operación, fase, proyecto, persona, recurso e hito. La solución propuesta usa sus propias asignaciones y reservas contextuales, por lo que puede solaparse con la solución vigente sin corromperla.

## 8. Confirmación

Solo `ACCEPT_REPLAN` puede cambiar la referencia autoritativa del programa. La confirmación requiere:

- escenario completo y solución factible;
- bases de plan, estado operativo y definición productiva aún vigentes;
- actor autorizado y motivo;
- revalidación de hechos reales y restricciones duras;
- promoción transaccional completa.

El resultado observable es una nueva versión numerada. Nunca se editan retrospectivamente la versión anterior ni la solución que la respaldaba.

## 9. Cancelación y rechazo

Cancelar antes de lanzar el comando no persiste nada. Rechazar un escenario ya creado solo actualiza su máquina de estados y mantiene sus resultados como evidencia.

En ambos casos, `planning_plans.current_version_id` y todas las filas pertenecientes a la solución vigente quedan exactamente iguales. Tampoco se copian reservas de la solución rechazada. Esta garantía se verifica comparando el puntero y el hash de la solución vigente antes y después.

La única excepción aparente es intencional: una revisión efectiva de tiempo restante ya declarada no se deshace al rechazar el plan propuesto. Deshacer ese hecho exigiría una nueva corrección superseding, nunca borrar historia.

## 10. Explicación de imposibilidad

Una propuesta imposible no debe responder solamente “sin capacidad”. `operation_plan_results.explanation`, `phase_plan_results.explanation`, `critical_resource_id`, `blocker_assignment_id`, `impact_items.reason` y los diagnósticos del run permiten construir una explicación con:

- restricción incumplida y tipo;
- recurso, persona, fase, operación o hito bloqueante;
- intervalo solicitado y primer intervalo disponible, si existe;
- relación causal: precedencia, falta de habilidad, calendario, ocupación, material, plano, gate o límite de horizonte;
- alternativa considerada y motivo de descarte;
- consecuencia de relajar una preferencia cuando sea permitido.

Formato funcional mínimo:

> No puede ubicarse el martes de 14:00 a 16:00 porque el Banco 2 está ocupado por Terminación del proyecto P-184 hasta las 17:30. Primera posición factible: miércoles 08:00. Moverla desplaza la entrega estimada un día hábil.

Si la causa es capacidad acumulativa, la explicación identifica demanda, capacidad y contribuyentes principales. La calidad del texto es responsabilidad del motor y del presentador, pero el esquema ya conserva los datos causales necesarios.

## 11. Validación de casos UX

| Caso | Ejecución esperada | Evidencia física | Resultado |
|---|---|---|---|
| UX-01 — operación demora 2 h | `UPDATE_REMAINING_ESTIMATE` con delta +120; registra hecho y genera propuesta | D060–D064, D089–D090, D070–D082 | **SOPORTADO** |
| UX-02 — termina 2 h antes | Restante reducido o evento de finalización; libera capacidad futura y simula su aprovechamiento | D064, D085–D090, D073–D082 | **SOPORTADO** |
| UX-03 — arrastre futuro válido | `MOVE_SCHEDULED_ACTIVITY`; hipótesis exacta y solución factible aislada | D070–D082 | **SOPORTADO** |
| UX-04 — arrastre imposible | Validación rápida y/o run bloqueado devuelve recurso/asignación crítica y alternativa | D074, D077–D078, D082–D083 | **SOPORTADO** |
| UX-05 — extensión desplaza varias actividades | El motor propaga precedencias y capacidad; comparación emite múltiples impactos | D073–D082 | **SOPORTADO** |
| UX-06 — cancelar conserva plan | No promoción; mismo `current_version_id` y hash de solución | D068–D076, D103 | **SOPORTADO** |
| UX-07 — confirmar crea versión | Promoción atómica crea la siguiente `plan_version` y mueve el puntero | D060–D061, D068–D069, D103–D104 | **SOPORTADO** |
| UX-08 — preservar porción ejecutada | Hechos D086/D088 y locks no se reescriben; solo cambia la revisión restante y el futuro | D085–D090, D077–D083 | **SOPORTADO** |
| UX-09 — banco ocupado de noche sin personas | Dimensión `PHYSICAL_OCCUPATION` amplía ocupación; no crea `LABOR_WORK` nocturno | D083, D087–D090 | **SOPORTADO** |
| UX-10 — cambia fecha de entrega | Hitos de ambas soluciones e `impact_items` muestran el delta; D097 permite contrastarlo con la fecha comunicada y D099 registrar una recomendación sin enviarla | D073–D074, D084 y D097–D099 | **SOPORTADO** |

Cobertura: **10/10 casos UX soportados**.

## 12. Impacto sobre el esquema físico

### 12.1 Resultado

- Tablas nuevas: **0**.
- Columnas nuevas: **0**.
- Relaciones nuevas: **0**.
- Cambios a las 45 invariantes: **0**.
- Cambios a los 44 casos de aceptación anteriores: **0**.
- Total de tablas: **107**, sin variación.

Los comandos no requieren persistir una tabla genérica de “comandos”. La evidencia durable ya queda en eventos/revisiones para hechos efectivos, hipótesis/escenarios para propuestas, auditoría para acciones sensibles y `scenario_promotions` para confirmaciones.

### 12.2 Contratos que deberán fijarse antes de implementar servicios

No son cambios de esquema, pero sí reglas obligatorias de implementación:

1. catálogo cerrado y versionado de tipos de hipótesis y modos de entrada;
2. esquema JSON validado para cada tipo de hipótesis;
3. idempotencia por comando, utilizando la infraestructura de evento/auditoría correspondiente;
4. política explícita de anclaje y reubicación asistida;
5. códigos estructurados de causa y traducción a explicaciones humanas;
6. estrategia de cálculo rápido más ejecución asíncrona del planificador;
7. advertencia persistente cuando una estimación efectiva deja al plan vigente desactualizado;
8. control de concurrencia mediante versión base y promoción transaccional.

### 12.3 Riesgos de implementación, no brechas físicas

- Una hora de fin puede atravesar pausas o calendarios distintos; la conversión debe ser explicada y confirmada.
- Extender automáticamente todas las dimensiones produciría reservas falsas; la UI debe ofrecer una selección simple pero explícita.
- La respuesta “inmediata” requiere índices, validación rápida y worker; el esquema permite el flujo, pero no garantiza por sí solo la latencia.
- La capacidad acumulativa y la calidad de la explicación dependen del motor, aunque los resultados tengan dónde persistirse.
- Un escenario puede quedar obsoleto mientras el usuario compara; la confirmación debe rechazarlo y ofrecer recalcular.
- Un arrastre exacto puede funcionar localmente y ser inviable globalmente; solo una solución `Ready` puede confirmarse.

## 13. Dictamen formal

No se detectó `BRECHA_MODELO` ni necesidad de ajustar el esquema físico para habilitar los siete comandos y los diez casos UX. El diseño mantiene separados hechos ejecutados, estimación restante efectiva, hipótesis, solución simulada, plan vigente y nueva versión confirmada.

**`ESQUEMA_SOPORTA_REPROGRAMACION_SIMPLE`**

Este dictamen detiene el trabajo antes de SQL, migraciones, tablas PostgreSQL, API, frontend y motor completo de scheduling.
