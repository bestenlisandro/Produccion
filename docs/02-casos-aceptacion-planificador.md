# Casos de aceptación del planificador

Estos casos forman el contrato funcional inicial. Cada uno deberá convertirse en pruebas automatizadas con fechas, calendarios y resultados exactos.

## CA-01 — Recurso humano y máquina simultáneos

**Dado** un lote listo para corte que necesita una escuadradora y dos personas con habilidad Corte,  
**y** la máquina está libre pero solo una persona habilitada está disponible,  
**entonces** la operación no se programa,  
**y** la explicación indica falta de la segunda persona.

## CA-02 — Planos disponibles pero material pendiente

**Dado** un lote con planos liberados y recursos disponibles,  
**pero** material obligatorio incompleto,  
**entonces** ninguna operación productiva del lote comienza,  
**y** el material aparece como restricción determinante.

## CA-03 — Recepción parcial habilita solo un lote

**Dado** un proyecto con Lote 1 y Lote 2,  
**y** la recepción cubre completamente el material del Lote 1 pero no el del Lote 2,  
**entonces** el Lote 1 puede programarse,  
**y** el Lote 2 permanece bloqueado.

## CA-04 — Precedencia completa para perforado

**Dado** un lote de placas enteras con corte terminado y pegado aún en ejecución,  
**entonces** perforado no puede comenzar, aunque la perforadora y Mariano estén libres.

## CA-05 — Otro lote del mismo proyecto no bloquea

**Dado** que el Lote 1 está completamente canteado,  
**y** el Lote 2 del mismo proyecto todavía no llegó,  
**entonces** el Lote 1 puede comenzar perforado.

## CA-06 — Horas-persona de armado

**Dado** un armado de 10 horas-persona, equipo mínimo uno y máximo dos,  
**cuando** se asignan dos personas con productividad lineal,  
**entonces** se reservan aproximadamente cinco horas coincidentes para ambas personas y un banco.

## CA-07 — Banco bloqueado durante la noche

**Dado** un armado que comienza en Banco 1 y continúa al día siguiente,  
**entonces** Banco 1 permanece físicamente ocupado durante la noche,  
**y** otra operación no puede utilizarlo aunque no haya personas trabajando.

## CA-08 — Segundo banco disponible

**Dado** Banco 1 ocupado físicamente y Banco 2 libre,  
**cuando** otra operación de armado encuentra personas habilitadas,  
**entonces** puede programarse en Banco 2.

## CA-09 — Descarga desplaza producción

**Dado** que Emiliano y Gonzalo están asignados a descarga de 09:00 a 11:00,  
**entonces** no pueden reservarse para corte, pegado, armado o instalación en ese intervalo.

## CA-10 — Perforadora unitaria

**Dadas** dos operaciones de perforado listas,  
**entonces** sus reservas sobre la única perforadora no se superponen, aunque existan dos operarios habilitados.

## CA-11 — Ventana obligatoria de instalación

**Dada** una instalación cuyos recursos están libres el lunes,  
**pero** el cliente solo admite el jueves de 08:00 a 12:00,  
**entonces** ningún segmento se programa fuera de esa ventana.

## CA-12 — Equipo variable en instalación

**Dada** una instalación de varios días con trabajo-persona pendiente,  
**cuando** trabajan tres personas el primer día y dos el segundo,  
**entonces** cada segmento reserva su propio equipo,  
**y** el trabajo-persona restante se conserva correctamente.

## CA-13 — Horas extra no automáticas

**Dado** que una fecha comprometida solo puede cumplirse usando sábado,  
**y** no existe autorización extraordinaria,  
**entonces** el plan normal informa atraso y no utiliza el sábado.

Al simular con autorización extraordinaria, debe mostrarse por separado el escenario que utiliza sábado y su cantidad de horas extra.

## CA-14 — Operación en ejecución congelada

**Dada** una operación en ejecución,  
**cuando** cambia la prioridad de otro proyecto,  
**entonces** la operación iniciada no cambia de comienzo, recursos ni banco automáticamente.

## CA-15 — Simulación no modifica el programa

**Dada** una versión vigente V10,  
**cuando** se calcula un escenario por demora de proveedor,  
**entonces** V10 conserva exactamente sus asignaciones,  
**y** la propuesta se almacena separadamente.

## CA-16 — Confirmación crea una versión

**Dado** un escenario calculado sobre V10,  
**cuando** un usuario autorizado lo confirma,  
**entonces** se crea V11 como nueva versión vigente,  
**y** V10 permanece consultable e inmutable.

## CA-17 — Escenario obsoleto

**Dado** un escenario calculado sobre V10,  
**y** V11 ya fue publicada por otro usuario,  
**cuando** se intenta confirmar el escenario anterior,  
**entonces** se rechaza la publicación y se solicita recalcular.

## CA-18 — Prioridad no cambia por atraso

**Dado** un proyecto Normal cuya fecha calculada supera el compromiso,  
**entonces** conserva prioridad Normal,  
**y** el sistema genera una advertencia de atraso.

## CA-19 — Lote productivo compartido

**Dado** un lote de corte con operaciones de tres proyectos y duración manual,  
**entonces** se realiza una sola reserva de escuadradora y personas,  
**y** al terminar se liberan las sucesoras de los tres miembros.

## CA-20 — Explicación del recurso limitante

**Dado** que una operación podía liberarse el martes a las 08:30,  
**pero** su operario elegible estaba asignado hasta las 11:00,  
**entonces** el resultado indica inicio a las 11:00, persona limitante y asignación previa que causó la espera.

## CA-21 — Resultado reproducible

**Dado** el mismo snapshot, configuración y versión del algoritmo,  
**cuando** se ejecuta el planificador más de una vez,  
**entonces** produce las mismas asignaciones, segmentos, recursos y explicaciones.

## CA-22 — Portal sin información interna

**Dado** un enlace público válido,  
**entonces** la respuesta puede mostrar etapa, avance, fecha pública y novedades,  
**pero** no contiene nombres de operarios, utilización, otros proyectos, costos, prioridad ni simulaciones.

## CA-23 — Regeneración del enlace

**Dado** un enlace público activo,  
**cuando** se regenera,  
**entonces** el token anterior deja de funcionar y el nuevo solo permite consultar el mismo proyecto.

## CA-24 — Evento de Compras idempotente

**Dado** un evento `MaterialReceived` con la misma clave de idempotencia enviado dos veces,  
**entonces** la recepción se procesa una sola vez,  
**y** no duplica cantidades ni disponibilidad.

## CA-25 — Armado en fases y herrajes

**Dado** un armado con fase Prearmado de 6 horas-persona y fase Terminación de 4 horas-persona,  
**y** los herrajes están pendientes,  
**entonces** Prearmado puede planificarse y ejecutarse,  
**pero** Terminación no comienza ni Armado se considera terminado hasta que los herrajes estén disponibles.

La espera intermedia no consume horas-persona; el banco puede permanecer ocupado si la ocupación física continúa abierta.

## CA-26 — Corte y pegado simultáneos

**Dadas** operaciones listas de corte y pegado sin precedencia entre sí,  
**y** máquinas y personas concretas diferentes disponibles,  
**entonces** pueden programarse simultáneamente, aunque pertenezcan al mismo proyecto.

## CA-27 — Un proyecto ocupa dos bancos

**Dados** dos lotes del mismo proyecto listos para armado,  
**y** dos bancos y equipos humanos disponibles,  
**entonces** ambos lotes pueden ocupar Banco 1 y Banco 2 simultáneamente.

## CA-28 — División entre jornadas

**Dada** una fase de ocho horas que no cabe en la capacidad restante del día,  
**entonces** puede continuar en la jornada siguiente mediante segmentos,  
**pero** no se divide automáticamente en varios intervalos del mismo día para rodear otra asignación o indisponibilidad.

Una división intradía exige una excepción manual autorizada y auditada.

## CA-29 — Fuera de horizonte

**Dado** un horizonte parametrizado de 90 días,  
**cuando** una fase no encuentra ubicación dentro del horizonte,  
**entonces** su operación queda `OUT_OF_HORIZON`,  
**y** no se marca imposible, terminada ni cancelada.

La solución informa la última operación programable y las sucesoras pendientes.

## CA-30 — Fechas de hitos por solución

**Dado** un plan vigente con fabricación estimada el día 20,  
**cuando** un escenario calcula el mismo hito para el día 24,  
**entonces** ambas fechas coexisten en sus respectivas soluciones,  
**y** la fecha vigente o comunicada no se sobrescribe al simular.

## CA-31 — Recomendación de comunicación

**Dada** una fecha comunicada y una nueva fecha estimada,  
**cuando** la diferencia supera un día hábil según el calendario comercial configurado,  
**entonces** se genera `COMUNICACIÓN_RECOMENDADA`,  
**pero** no se cambia la fecha pública ni se envía un mensaje sin aprobación humana.

## CA-32 — Ejecución vinculada al plan de origen

**Dada** una ejecución iniciada desde una asignación publicada,  
**entonces** conserva referencias a la versión, operación y segmento previstos,  
**y** registra por separado personas, recursos y tiempos reales.

Reemplazar posteriormente la versión vigente no altera esas referencias históricas.

## CA-33 — Escenario obsoleto por estado operativo

**Dado** un escenario Ready calculado sobre V5 y revisión operativa R120,  
**cuando** una ausencia efectiva incrementa el estado a R121 sin reemplazar V5,  
**entonces** el escenario queda `STALE` y no puede confirmarse.

## CA-34 — Hipótesis aislada

**Dada** una hipótesis de demora de proveedor dentro de un escenario,  
**entonces** puede afectar la solución simulada,  
**pero** no modifica el pedido, entrega, disponibilidad real ni programa vigente.

## CA-35 — Definición productiva histórica

**Dada** una solución calculada con revisión productiva D12,  
**cuando** se modifica una ruta o estimación y se crea D13,  
**entonces** la solución anterior continúa reconstruyéndose exactamente con D12.

## CA-36 — Mapping público configurable

**Dado** un conjunto versionado de reglas de mapeo público,  
**cuando** cambian las reglas comerciales de presentación,  
**entonces** puede generarse una nueva proyección pública sin modificar operaciones, rutas ni el motor de scheduling.

## CA-37 — Operación demora más que la estimación original

**Dada** una operación en ejecución estimada originalmente en 10 horas-persona,  
**y** 7 horas-persona realmente ejecutadas,  
**cuando** el usuario informa 5 horas-persona restantes,  
**entonces** se conservan la estimación original de 10, el ejecutado de 7 y el restante de 5,  
**y** la estimación total actualizada resulta 12 horas-persona.

El cambio genera un evento efectivo y una nueva revisión operativa, pero no modifica el plan vigente.

## CA-38 — Operación termina antes de lo estimado

**Dada** una fase con estimación original de 10 horas-persona,  
**cuando** termina realmente después de 8 horas-persona,  
**entonces** conserva estimación original 10, ejecutado 8 y restante 0,  
**y** una simulación puede liberar las reservas futuras que ya no serían necesarias.

## CA-39 — Actualización simple del restante

**Dada** una operación en ejecución,  
**cuando** el usuario agrega 30 minutos, una hora, dos horas, ingresa un restante o una nueva finalización estimada,  
**entonces** la acción se normaliza en una nueva `RemainingEstimateRevision`,  
**y** conserva modo de ingreso, autor, momento, valor anterior y valor nuevo.

## CA-40 — Extensión genera conflicto

**Dada** una máquina asignada a Operación A y posteriormente reservada para Operación B,  
**cuando** el uso activo restante de A se extiende sobre B,  
**entonces** se detecta el conflicto y se crea una simulación con sus consecuencias,  
**pero** B y el plan vigente no se mueven hasta la confirmación.

## CA-41 — Extensión afecta una fecha estimada

**Dada** una extensión que retrasa una sucesora y el hito de fabricación,  
**entonces** la comparación muestra fecha estimada anterior, nueva fecha, desviación respecto de compromiso y proyectos dependientes afectados.

La fecha comunicada al cliente no se modifica automáticamente.

## CA-42 — Banco extendido durante la noche

**Dado** un armado que finalizaba el viernes pero necesita continuar el lunes,  
**cuando** se extiende la ocupación física del banco durante la noche y el fin de semana,  
**entonces** el banco permanece bloqueado de forma continua,  
**pero** ese intervalo no genera horas-persona ni uso activo de máquina.

## CA-43 — Segmentos ejecutados inmutables

**Dada** una operación con segmentos ya ejecutados y trabajo restante actualizado,  
**cuando** se calcula una reprogramación,  
**entonces** ningún segmento ejecutado cambia de horario, personas ni recursos reales,  
**y** solo se proponen asignaciones futuras nuevas o modificadas.

## CA-44 — Rechazo de la reprogramación

**Dada** una actualización de restante que generó un escenario,  
**cuando** el usuario rechaza la propuesta,  
**entonces** la versión anterior continúa Current y conserva sus asignaciones,  
**mientras** la estimación restante efectiva y su advertencia permanecen registradas para una nueva decisión.

## Invariantes globales

Toda propuesta considerada factible debe cumplir:

1. Ningún recurso unitario tiene reservas superpuestas.
2. Ninguna persona trabaja en dos operaciones simultáneas.
3. Toda persona satisface las habilidades requeridas.
4. Se respeta la cantidad mínima de recursos simultáneos.
5. Toda precedencia termina antes del inicio de su sucesora.
6. Materiales, planos y herrajes cumplen las reglas del lote.
7. Cada segmento está dentro de los calendarios aplicables.
8. Las horas extraordinarias tienen autorización explícita.
9. Las instalaciones respetan las ventanas obligatorias.
10. Las operaciones en ejecución no se desplazan automáticamente.
11. El programa vigente no cambia al simular.
12. El mismo snapshot produce el mismo resultado.
13. Cada fase respeta su orden, gates y requerimientos propios.
14. Las esperas sin segmentos no consumen capacidad ni trabajo-persona.
15. Una hipótesis no modifica el estado operativo real.
16. Una solución conserva revisión productiva y revisión operativa.
17. Un escenario obsoleto permanece auditable pero no publicable.
18. La ejecución real nunca reescribe el plan de origen.
19. El portal deriva su etapa mediante mapping versionado.
20. Estimación original, ejecutado y restante nunca se sobrescriben entre sí.
21. El total actualizado usa magnitudes compatibles, una fecha de corte explícita y el restante de todas las fases incompletas.
22. Cambiar trabajo humano, uso activo u ocupación física no modifica implícitamente las otras dimensiones.
23. Toda actualización de restante incrementa la revisión operativa sin publicar un plan.
24. Una simulación de extensión conserva hechos ejecutados y el plan vigente hasta confirmación.
