# Casos difíciles para validar el modelo lógico

Estos casos no modifican las reglas aprobadas. Sirven para comprobar que el modelo puede representarlas sin pérdida de integridad antes de diseñar migraciones.

## 1. Herrajes como condición de finalización

Un lote comienza armado, consume cuatro horas-persona y queda físicamente sobre Banco 1. Faltan herrajes imprescindibles.

Debe poder representarse simultáneamente:

- operación En ejecución o Esperando insumo;
- segmentos ya ejecutados inmutables;
- trabajo restante ajustable;
- gate `COMPLETE` incumplido;
- Banco 1 todavía ocupado;
- armado no terminado;
- sucesoras no liberadas.

Verificar especialmente que recibir herrajes no marque automáticamente el armado como terminado: todavía puede requerir trabajo final.

## 2. Banco ocupado sin mano de obra

Armado A utiliza Banco 1 el viernes hasta las 16:00 y continúa el lunes. No hay trabajo el fin de semana.

El modelo debe conservar una ocupación física continua, mientras las asignaciones humanas solo cubren segmentos laborales. Armado B no puede usar Banco 1 el sábado ni el lunes temprano, pero puede usar Banco 2.

## 3. Un proyecto ocupa ambos bancos

Dos lotes del mismo proyecto se arman simultáneamente en bancos distintos con equipos diferentes.

No debe existir una restricción artificial de exclusividad por proyecto. Las únicas exclusividades son los recursos físicos y personas concretas.

## 4. Cambio de equipo en instalación

Una instalación tiene tres personas el jueves y una persona diferente el viernes.

Debe existir una sola operación requerida, una asignación con varios segmentos y asignaciones humanas distintas por segmento. El total de trabajo-persona aportado debe ser consistente con el trabajo pendiente.

## 5. Ventanas del cliente discontinuas

El cliente habilita jueves 08:00–12:00 y viernes 14:00–17:00. La instalación requiere seis horas y admite división entre jornadas.

El modelo debe representar ambos segmentos sin crear disponibilidad durante el intervalo intermedio.

## 6. Recepción parcial compartida

Una entrega de veinte placas puede cubrir diez placas del Lote A y diez del Lote B. Posteriormente se registra una devolución de dos placas asignadas a B.

Debe conservarse la historia, recalcular la cobertura neta y volver a bloquear B si deja de cubrir su requerimiento. Esto genera impacto y simulación, no reprogramación automática.

## 7. Evento duplicado desde Compras

Compras reintenta el mismo evento de recepción por un timeout.

La clave idempotente debe producir un único movimiento y dejar registrado que el segundo mensaje ya había sido procesado.

## 8. Modificación de una ruta ya utilizada

Se agrega una nueva operación a la plantilla de placas enteras cuando existen lotes planificados con una versión anterior.

Los lotes existentes deben conservar pasos, precedencias y requerimientos originales. Los nuevos lotes pueden utilizar una versión nueva. No se edita una versión publicada en uso.

## 9. Lote productivo con miembros de varios proyectos

Un lote de corte agrupa tres operaciones. Una de ellas se cancela antes de ejecutar el lote productivo.

Debe verificarse cómo se crea una nueva composición versionada o se retira el miembro con auditoría, sin alterar programas publicados ni duplicar reservas.

## 10. Operación fuera del horizonte

En un horizonte de 90 días se programan Corte y Pegado, pero Perforado no encuentra intervalo.

Perforado debe quedar `OUT_OF_HORIZON`; sus sucesoras también permanecen pendientes con explicación. El proyecto no queda marcado como imposible. Al ampliar el horizonte, se genera una nueva solución sin modificar la anterior.

## 11. Ausencia posterior a una simulación

Un escenario Ready asigna a una persona que luego registra una ausencia en el plan vigente antes de que el escenario sea confirmado.

Si la ausencia produce una nueva versión vigente o cambia el snapshot aplicable, el escenario debe quedar Stale o fallar la validación de publicación. Nunca debe confirmarse una solución basada en capacidad obsoleta.

## 12. Dos confirmaciones concurrentes

Dos usuarios simulan sobre V5. Ambos intentan confirmar escenarios diferentes.

Solo una transacción puede crear V6. La otra detecta que V5 ya no es Current y marca su escenario Stale. En ningún momento hay dos versiones vigentes.

## 13. Operación iniciada frente a nueva prioridad

Perforado A tiene segmentos reales ejecutados y uno futuro planificado. Se eleva la prioridad del Proyecto B.

Los hechos ejecutados no cambian. El alcance exacto que se congela para el resto de A debe conservarse en el snapshot y en la explicación. B solo puede usar capacidad realmente libre.

## 14. Capacidad normal y extraordinaria en el mismo día

Una persona trabaja su jornada normal y dos horas autorizadas adicionales para un proyecto específico.

Los segmentos deben separar minutos normales y extraordinarios. Otro proyecto no puede consumir la autorización. La comparación de escenarios informa ambas capacidades por separado.

## 15. Habilidad con vigencia

Emiliano obtiene habilitación de Perforado a partir de una fecha futura.

No puede ser asignado antes de esa fecha y sí después, sin modificar el catálogo de la operación ni hardcodear su nombre.

## 16. Recurso fuera de servicio parcialmente

La perforadora tiene mantenimiento de 10:00 a 13:00. Una operación divisible entre jornadas no debe fragmentarse arbitrariamente en dos tramos del mismo día para rodear el mantenimiento, salvo decisión explícita.

Debe verificarse que el calendario y la política de división se evalúen conjuntamente.

## 17. Cambio de fecha y comunicación

La fecha previamente comunicada es viernes. Un escenario calcula lunes siguiente y entre ambas existe un fin de semana.

La diferencia debe calcularse en días hábiles usando el calendario comercial definido. Si supera un día hábil, se crea `COMUNICACIÓN_RECOMENDADA`; no se envía ningún mensaje.

## 18. Regeneración del enlace público

Al regenerar el enlace, el token anterior queda revocado y el nuevo sigue mostrando la misma proyección pública. Ninguno permite inferir IDs internos ni consultar otros proyectos.

## 19. Proyección pública y plan interno

Una simulación modifica la fecha estimada, pero todavía no fue confirmada ni aprobada para publicación.

El portal debe seguir mostrando la fecha comunicada anterior. Confirmar el plan puede generar una recomendación, pero tampoco modifica automáticamente la fecha comunicada.

## 20. Corrección de ejecución real

Se cargan por error horas reales duplicadas y luego se corrigen.

La corrección debe ser auditada o compensatoria, preservar qué valor se usó originalmente y recalcular indicadores sin alterar asignaciones de versiones históricas.

## 21. Reloj y límites diarios

Una asignación cruza medianoche, un feriado o un cambio excepcional de calendario.

Los intervalos deben evaluarse como instantes con zona horaria; los informes diarios se agrupan en `America/Buenos_Aires` sin cambiar la duración real.

## 22. Fallo durante publicación

La actualización de la versión anterior se ejecuta, pero falla la escritura de auditoría o outbox.

La transacción completa debe revertirse. No puede quedar una versión sin auditoría, dos versiones vigentes ni una proyección pública parcialmente actualizada.

## Criterio para aprobar el modelo lógico

Antes de crear migraciones debemos poder responder para cada caso:

1. Qué entidad representa cada hecho.
2. Qué relación o restricción evita inconsistencias.
3. Qué dato es editable y cuál es inmutable.
4. Qué ocurre dentro de una simulación.
5. Qué cambia únicamente al confirmar.
6. Qué información, si alguna, puede llegar al portal público.

## Resolución después de la Etapa 1.6

| Caso | Resultado con el modelo corregido |
|---|---|
| CD-1 Herrajes | Resuelto mediante `RequiredOperationPhase`, gates por fase y trabajo estimado separado para Prearmado/Terminación. |
| CD-2 Banco sin personas | Resuelto mediante segmentos laborales y `PhysicalOccupation` continua. |
| CD-3 Dos bancos | Resuelto; no existe exclusión por proyecto, solo por recurso concreto. |
| CD-4 Equipo variable | Resuelto mediante asignaciones humanas por segmento. |
| CD-5 Ventanas discontinuas | Resuelto mediante ventanas y segmentos contenidos. |
| CD-6 Recepción parcial | Resuelto mediante asignaciones y movimientos compensatorios. |
| CD-7 Evento duplicado | Resuelto mediante inbox e idempotencia. |
| CD-8 Ruta utilizada | Resuelto mediante rutas versionadas y revisión productiva inmutable. |
| CD-9 Lote productivo | Resuelto mediante `ProductionBatchVersion` y miembros inmutables por versión. |
| CD-10 Fuera de horizonte | Resuelto mediante resultados `OUT_OF_HORIZON`. |
| CD-11 Ausencia posterior | Resuelto mediante `PlanningStateRevision` y estado `STALE`. |
| CD-12 Confirmaciones concurrentes | Representable mediante publicación transaccional y una sola versión Current. |
| CD-13 Operación iniciada | Resuelto mediante ejecución append-only y `PlanningLock` con alcance explícito. |
| CD-14 Horas extraordinarias | Resuelto mediante autorización y consumo separado por segmento. |
| CD-15 Habilidad vigente | Resuelto mediante vigencia de `EmployeeSkill`. |
| CD-16 División excepcional | Resuelto mediante `ManualException` de división intradía. |
| CD-17 Comunicación | Resuelto vinculando `CommunicationPolicy` con calendario comercial. |
| CD-18 Enlace público | Resuelto mediante revocación, hash y unicidad del enlace activo. |
| CD-19 Proyección pública | Resuelto mediante `PublicStageMappingSet` y reglas versionadas. |
| CD-20 Corrección real | Representable con política append-only/compensatoria. |
| CD-21 Zona horaria | Resuelto con instantes y zona de planta. |
| CD-22 Fallo de publicación | Representable mediante una única transacción con auditoría y outbox. |

No permanece ningún `BRECHA_MODELO` en estos 22 casos. Los detalles físicos de constraints y bloqueo se difieren a la Etapa 2.
