# Decisiones funcionales V1

Estado: baseline funcional V1 validado por el negocio.

Este documento convierte la especificación funcional en reglas que puedan implementarse y probarse. Si una regla cambia, deberá registrarse explícitamente; no se modificará de forma implícita dentro del algoritmo.

## 1. Unidad de planificación

- La unidad comercial es el **proyecto**.
- Un proyecto contiene uno o más **lotes de proyecto**.
- La unidad mínima que programa el motor es una **operación de lote**.
- Una operación puede pertenecer a un **lote productivo compartido** con operaciones de otros proyectos.
- No se realiza seguimiento por módulo de mueble en V1.

## 2. Tiempo y calendarios

- Las fechas se almacenan como instantes con zona horaria; la operación inicial utiliza `America/Buenos_Aires`.
- Las duraciones se expresan internamente en minutos enteros.
- La interfaz puede redondear o agrupar visualmente, pero el motor no pierde precisión por usar bloques fijos.
- Cada persona y recurso físico tiene calendario propio.
- La capacidad normal y extraordinaria se mantienen separadas.
- La capacidad extraordinaria solo puede utilizarse si el escenario la autoriza expresamente.
- La fecha comprometible normal se calcula sin horas extraordinarias.

## 3. Divisibilidad de operaciones — VALIDADA

Las operaciones se programan a nivel de lote, no pieza por pieza ni módulo por módulo.

- Un lote completo puede avanzar aunque otro lote del mismo proyecto esté pendiente.
- Un lote entra en perforado cuando todo ese lote está cortado y canteado.
- Un lote entra en armado cuando todo ese lote está perforado.
- Una operación puede dividirse entre jornadas cuando sea necesario.
- No se fragmenta arbitrariamente dentro del mismo día, salvo interrupción real o decisión explícita del usuario.
- Los segmentos realmente ejecutados de una operación iniciada se conservan como hechos.

El modelo mantendrá una política de división configurable para permitir futuras excepciones sin cambiar el motor, pero la regla anterior es el comportamiento inicial de V1.

## 4. Precedencias y habilitaciones

Las precedencias productivas son de tipo fin-a-inicio en V1.

Flujo previo adoptado:

```text
Medición final -> Replanteo
Replanteo -> Pedido de materiales
Replanteo -> Preparación de planos
Material disponible + Planos disponibles -> Primera operación productiva del lote
```

Rutas iniciales:

- Placa entera: Corte -> Pegado -> Perforado -> Armado.
- Material cortado: Pegado -> Perforado -> Armado.
- Material cortado y canteado: Perforado -> Armado.

El perforado de un lote solo se habilita cuando el corte y pegado requeridos para ese lote están completamente terminados. Otros lotes del mismo proyecto no lo bloquean.

El armado de un lote puede comenzar al terminar completamente su perforado, aunque otros lotes del proyecto sigan pendientes.

## 5. Materiales y planos

- La disponibilidad se controla por lote, no solamente por proyecto.
- Un lote puede tener varios requerimientos de material.
- Un requerimiento indica cantidad requerida y cantidad cubierta.
- El lote queda materialmente habilitado cuando todos los requerimientos obligatorios para su próxima operación están cubiertos.
- Las recepciones parciales pueden habilitar un lote y mantener bloqueado otro.
- En V1 no se administra inventario contable completo ni valorización.
- Los planos también se liberan por lote, permitiendo preparación parcial del proyecto.

## 6. Herrajes — VALIDADA

Estados simplificados: Disponible, Pendiente, Recibido y No aplica.

- Los herrajes no bloquean el comienzo general de producción.
- Pueden realizarse corte, pegado, perforado y las tareas de armado físicamente posibles.
- Si faltan herrajes imprescindibles, el armado puede quedar iniciado o parcial, pero no puede considerarse terminado.
- La espera de herrajes debe ser visible y explicable.
- No se implementa inventario detallado de herrajes en V1.

El modelo distinguirá condiciones necesarias para iniciar de condiciones necesarias para completar una operación.

## 7. Recursos y habilidades

- Las personas, máquinas y bancos son recursos concretos configurables.
- Los centros de trabajo organizan recursos, pero no reemplazan sus reservas concretas.
- Una operación declara requerimientos genéricos: grupo de recursos, cantidad de personas, habilidades y cantidades mínimas/máximas.
- Una persona no puede participar simultáneamente en dos operaciones.
- Un recurso unitario no puede recibir reservas superpuestas.
- Incorporar personas, máquinas, bancos o turnos no requiere modificar la lógica central.

## 8. Horas-persona

- Armado e instalación conservan trabajo estimado en horas-persona.
- La duración de un segmento se obtiene del trabajo asignado, cantidad de personas y factor de productividad.
- En V1 se adopta productividad lineal cuando la operación no declare otra curva: dos personas realizan en aproximadamente la mitad de tiempo el mismo trabajo.
- Cada operación define equipo mínimo y máximo.
- El factor utilizado queda registrado en la explicación del escenario.

## 9. Ocupación física de bancos — VALIDADA

- La reserva de mano de obra y la ocupación física son conceptos separados.
- Desde que comienza el armado hasta que el lote/proyecto es retirado o una operación configurada determina explícitamente su liberación, el banco queda ocupado de forma continua, incluso durante noches, descansos o días no laborales.
- La liberación manual exige usuario, fecha, motivo y auditoría.
- La ocupación de un banco no implica que haya mano de obra asignada durante todo el intervalo.
- Un mismo proyecto puede ocupar simultáneamente ambos bancos.

## 10. Lotes productivos compartidos

- Un lote productivo compartido agrupa operaciones compatibles de uno o más proyectos.
- Su duración se ingresa manualmente en V1.
- La reserva de recursos se realiza una sola vez para todo el lote productivo.
- Su finalización libera las operaciones sucesoras de cada miembro.
- Los tiempos de preparación y la optimización automática de agrupamientos quedan fuera de V1.

## 11. Instalaciones

- La instalación usa los mismos recursos humanos que producción.
- Puede requerir entre una y tres personas según configuración.
- Puede dividirse en segmentos de varios días.
- El equipo puede cambiar entre segmentos, conservando el trabajo-persona restante.
- Todo segmento debe estar dentro de una ventana obligatoria del cliente.
- El porcentaje instalado se registra independientemente del trabajo-persona consumido.
- Fabricación e instalación de partes diferentes del proyecto pueden coexistir.

## 12. Prioridad y orden determinista — VALIDADA

Orden inicial adoptado para operaciones listas:

1. Operaciones iniciadas o congeladas conservan su posición.
2. Prioridad manual del proyecto: Urgente, Alta, Normal.
3. Fecha comprometida más próxima.
4. Fecha de aceptación más antigua.
5. Código estable del proyecto, lote y operación.

La prioridad de un proyecto atrasado no cambia automáticamente. El sistema genera una advertencia.

Los criterios serán configurables en una evolución posterior, pero la V1 conservará un orden total estable para garantizar reproducibilidad.

## 13. Estados

Los estados de operación son la fuente primaria:

- Pendiente.
- Bloqueada.
- Lista para programar.
- Programada.
- En ejecución.
- Pausada.
- Terminada.
- Cancelada.

El estado general del proyecto se deriva de operaciones, hitos y bloqueos. Una excepción manual debe quedar auditada y no altera silenciosamente estados de operaciones.

Se mantienen separados:

- fabricación terminada;
- instalación terminada;
- proyecto cerrado.

## 14. Programa y escenarios

- Existe una única versión publicada vigente por ámbito de planificación.
- Las versiones publicadas son inmutables.
- Toda simulación referencia una versión base.
- Confirmar un escenario crea una nueva versión; no edita la anterior.
- Si la versión base dejó de estar vigente, el escenario se marca obsoleto y debe recalcularse.
- Una operación en ejecución queda congelada.
- Las operaciones terminadas se preservan como hechos históricos.

## 15. Explicabilidad mínima

Por cada operación, el motor debe informar:

- fecha mínima por precedencias;
- fecha de disponibilidad de material y planos;
- recursos requeridos y elegidos;
- intervalos relevantes descartados;
- recurso o condición determinante del inicio;
- operación previa que ocupaba ese recurso;
- utilización o no de horas extraordinarias;
- regla de prioridad y desempate aplicada.

## 16. Avance del proyecto y portal público — VALIDADA

- El portal no utiliza directamente horas productivas para calcular el avance visible.
- Las etapas públicas iniciales son: Diseño y definición; Medición y replanteo; Preparación de planos y materiales; Materiales disponibles; En producción; Fabricación terminada; En instalación; Finalizado.
- El estado público se deriva de estados internos, pero no expone su detalle técnico.
- Si se muestra un porcentaje general, se obtiene de una configuración simple por etapas cuyos pesos quedan parametrizables.
- El porcentaje de instalación se conserva como dato separado.
- Una corrección manual del avance público requiere auditoría y no altera la ejecución productiva.
- La fecha interna calculada y la fecha comunicada al cliente son datos diferentes.

## 17. Cuellos de botella V1

Se señalarán usando indicadores explicables:

- porcentaje de utilización;
- horas pendientes;
- cantidad de operaciones esperando;
- tiempo de espera causado;
- cantidad de hitos cuya fecha depende del recurso.

No se afirmará que un único indicador constituye una optimización matemática global.

## 18. Simplificaciones expresas

- Una planta y una zona horaria inicial.
- Duraciones manuales.
- Sin inventario integral.
- Sin seguimiento por módulo.
- Sin optimización global.
- Sin cálculo automático de setup.
- Sin agrupamiento automático de lotes productivos.
- Productividad lineal inicial para equipos de personas.
- Forward finite-capacity scheduling determinista.
- Horas extra únicamente autorizadas.

## 19. Horizonte de planificación — VALIDADA

- El horizonte móvil inicial es de 90 días corridos hacia adelante.
- El valor es parametrizable y nunca queda hardcodeado en el motor.
- Una operación que no encuentra ubicación dentro del horizonte conserva su trabajo pendiente y queda con resultado `FUERA_DE_HORIZONTE`.
- El sistema informa la última operación programable y las operaciones pendientes.
- Ampliar el horizonte y recalcular no requiere cambiar la lógica.

## 20. Permisos para planificar, confirmar y publicar — VALIDADA

Se separan tres permisos:

- Planificar/simular: ejecutar simulaciones, modificar estimaciones, proponer asignaciones y analizar escenarios.
- Confirmar programa: convertir una simulación en una nueva versión vigente.
- Publicar al cliente: habilitar enlaces, modificar fechas comunicadas y aprobar comunicaciones.

Daniel, Maximiliano y Lisandro son datos iniciales de asignación de roles; sus nombres no forman parte de la lógica. V1 puede agrupar los permisos en un rol administrativo/planificador, manteniéndolos separados en el modelo.

Toda confirmación registra usuario, fecha y hora, escenario origen, versión anterior, versión nueva y motivo cuando corresponda.

## 21. Umbral de comunicación al cliente — VALIDADA

- Los cambios internos no envían comunicaciones automáticas.
- Si la nueva fecha difiere de la previamente comunicada en un día hábil o menos, se muestra una advertencia interna sin proponer comunicación automática.
- Si difiere en más de un día hábil, se genera `COMUNICACIÓN_RECOMENDADA` con fecha anterior, nueva fecha, diferencia y motivo.
- Toda comunicación requiere aprobación humana.
- El umbral es parametrizable.

## 22. Cierre de decisiones

Las ocho decisiones funcionales identificadas durante la revisión inicial quedaron resueltas y marcadas como `VALIDADA`. No quedan decisiones funcionales abiertas que impidan comenzar el modelo lógico de la Etapa 1.

## 23. Actualización del trabajo restante durante ejecución — VALIDADA

Una operación en ejecución conserva separadamente:

- estimación original inmutable;
- trabajo realmente ejecutado;
- estimación restante vigente;
- estimación total actualizada, calculada como ejecutado más restante.

Actualizar el restante es un evento efectivo y auditable que incrementa la revisión del estado de planificación. No modifica retrospectivamente la revisión productiva ni la versión publicada.

Flujo obligatorio:

```text
actualizar tiempo restante
-> detectar impacto
-> simular
-> comparar
-> usuario confirma
-> nueva versión
```

La estimación futura distingue trabajo humano, utilización activa de recursos físicos y ocupación física. Modificar una dimensión no extiende implícitamente las demás.

Los segmentos ejecutados son inmutables. Rechazar la propuesta de reprogramación mantiene el programa anterior vigente, aunque el sistema continúa advirtiendo que el nuevo pronóstico operativo puede volverlo conflictivo u obsoleto.
