# Etapa 2.3 — Cierre del esquema físico PostgreSQL V1 simplificado

## 1. Situación inicial

La Etapa 2 produjo una arquitectura objetivo de 107 tablas en 8 schemas. Era correcta y cubría 45 invariantes, 44 casos de aceptación, 22 casos difíciles y reprogramación simple, pero incluía generalizaciones y cabeceras que no eran necesarias para la primera entrega.

La Etapa 2.2 recomendó formalmente `SIMPLIFICAR_ESQUEMA_ANTES_DE_MIGRACIONES` y propuso 87 tablas sin degradar capacidades.

## 2. Propuesta aprobada y aplicación

La propuesta pragmática fue aplicada a:

- `docs/07-esquema-fisico-postgresql-v1.md`;
- `docs/08-diccionario-datos-v1.md`;
- este documento de cierre y el índice del proyecto.

Los documentos 07 y 08 son ahora autoritativos y reflejan exclusivamente objetos activos del esquema V1 simplificado. `docs/10-auditoria-simplificacion-esquema-v1.md` se conserva como registro histórico.

## 3. Cantidad final

Cantidad final realmente aplicada: **87 tablas**.

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

`M` agrupa mutables, proyecciones y lifecycle técnico; `V`, versionadas/lifecycle de dominio; `A`, append-only o inmutables.

Además quedaron definidos:

- **68** familias de constraints relevantes, sin contar PK/FK/NOT NULL básicos;
- **28** familias de índices secundarios explícitos, además de índices automáticos de PK/UNIQUE/EXCLUDE.

## 4. Matriz de reducción

| Tabla original | Acción | Destino / situación | Motivo |
|---|---|---|---|
| D004 `core.roles` | FUSIONADA | D005 `user_roles.role_code` + allowlist de aplicación | Roles personalizables no requeridos V1 |
| D023 `plant_calendar_assignments` | FUSIONADA | D002 `plants.base_calendar_id` | Un calendario base por planta |
| D024 `work_center_calendar_assignments` | FUSIONADA | D012 `work_centers.base_calendar_id` | Un calendario base opcional por centro |
| D025 `employee_calendar_assignments` | FUSIONADA | D013 `employees.base_calendar_id` | Un calendario base por persona |
| D026 `physical_resource_calendar_assignments` | FUSIONADA | D017 `physical_resources.base_calendar_id` | Un calendario base por recurso |
| D055 `hardware_readiness` | FUSIONADA | D009 estado/disponibilidad de lote + gate D039 | Relación 1:1 y mismo ciclo del lote |
| D056 `installation_work_packages` | FUSIONADA | D036/D037/D040 y `operation_kind=installation` | Instalación ya es una operación planificable |
| D059 `installation_progress_entries` | FUSIONADA | D064 evento + ejecución D085/D086/D088 + proyección D095 | Evita historial paralelo; conserva porcentaje |
| D062 `planning_state_changes` | DIFERIDA | V2+; resumen D061 + eventos D064 + auditoría D104 | Tercer historial no necesario V1 |
| D063 `event_types` | FUSIONADA | D064 código/schema de payload + allowlist | Tipos administrables por tenant no requeridos |
| D065 `manual_exception_reasons` | FUSIONADA | D066 código/texto + regla de aprobación | Motivos V1 cerrados |
| D068 `planning_plans` | FUSIONADA | Current/lock D002/D060; versiones D069; escenarios D070; locks D067 | Un programa publicado por planta |
| D072 `scenario_effective_events` | DIFERIDA | V2+; trigger directo en D070/D071 y revisión base | N:M arbitraria no requerida V1 |
| D073 `impact_analyses` | FUSIONADA | Cabecera de comparación D076; detalles D074 | Relación 1:1 con solución V1 |
| D075 `scheduling_runs` | FUSIONADA | D076 contiene run, solución e impacto final | Una solución por run V1 |
| D087 `execution_pauses` | FUSIONADA | D086 segmento `PAUSE`, trabajo cero y motivo | Misma línea temporal de ejecución |
| D098 `communication_policies` | DIFERIDA | V2+; calendario/umbral tipados en D002 | Una política segura basta V1 |
| D099 `communication_recommendations` | DIFERIDA | V2+; impacto D074 y aprobación D097 | Recomendación derivada del escenario |
| D100 `public_publication_history` | DIFERIDA | V2+; D095/D096/D097 + auditoría D104 | Evita snapshot histórico duplicado |
| D103 `scenario_promotions` | FUSIONADA | D069 + acción `SCENARIO_PROMOTED` en D104 | Versión y auditoría ya contienen evidencia |

Resultado: **15 fusionadas + 5 diferidas = 20 tablas menos**.

Los IDs D se conservaron estables; los huecos permiten rastrear documentos históricos sin convertir IDs retirados en tablas activas.

## 5. Cambios relevantes

### 5.1 Calendarios

Planta, centro, persona y recurso físico poseen calendario base directo. Intervalos, feriados/cierres, excepciones, indisponibilidades y horas extra siguen en entidades normalizadas. Cambiar un calendario base incrementa `PlanningStateRevision`.

### 5.2 Herrajes

El lote conserva estado y disponibilidad. Un gate de fase permite Prearmado antes de herrajes y bloquea Terminación. Espera, trabajo y ocupación física siguen separados.

### 5.3 Instalación

Es una operación tipada que reutiliza fases, skills, requerimientos, asignaciones, calendarios y ejecución. Soporta equipos variables entre segmentos, varios días, ventanas del cliente, consumo de operarios y porcentaje público.

### 5.4 Run, solución e impacto

D076 conserva escenario, bases, algoritmo, input/hash, tiempos, estado, error, solución/hash, métricas, baseline y comparación. D074 conserva impactos detallados. Una fila final `ready/failed` es inmutable.

### 5.5 Programa vigente

Cada planta posee un único puntero `current_plan_version_id`. Las versiones tienen vigencia temporal no superpuesta; no existe `is_current`. Escenarios y soluciones no cambian el puntero.

### 5.6 Portal

Se mantiene proyección allowlist, mapping versionado, token hash/revocación, timeline, fecha comunicada e instalación. Una recomendación es un impacto y requiere aprobación antes de publicar o emitir outbox.

## 6. Capacidades críticas preservadas

Permanecen físicamente separadas:

- planificado y ejecutado;
- escenario y versión publicada;
- estimación original y restante;
- trabajo humano, uso activo y ocupación física;
- persona y recurso físico;
- evento efectivo e hipótesis;
- excepción manual e hipótesis;
- estado interno y etapa pública.

D089 y D090 no fueron simplificadas. Continúa siendo representable original 10 h, ejecutado 7 h, restante 5 h y total actualizado 12 h, con extensión independiente de personas, recurso activo y ocupación.

## 7. Revalidación de 45 invariantes

| Grupo | Cobertura | Mecanismos principales |
|---|---:|---|
| INV-01–05 | 5/5 | Proyecto/lote, rutas, DAG y gates tipados |
| INV-06–13 | 8/8 | EXCLUDE contextual, calendarios, skills, equipo y resultados |
| INV-14–17 | 4/4 | Solución inmutable, Current por planta y promoción |
| INV-18–22 | 5/5 | Ejecución/eventos/materiales/herrajes |
| INV-23–25 | 3/3 | Link, proyección y aprobación de comunicación |
| INV-26–32 | 7/7 | Fases, ocupación, snapshots, hipótesis y excepciones |
| INV-33–37 | 5/5 | Bases O(1), origen, batches, mapping y state head |
| INV-38–45 | 8/8 | Original/restante, dimensiones, locks y rechazo |

Resultado: **45/45 invariantes preservadas**.

## 8. Revalidación de 44 casos de aceptación

| Grupo | Cobertura |
|---|---:|
| CA-01–13 | 13/13 |
| CA-14–21 | 8/8 |
| CA-22–24 | 3/3 |
| CA-25–29 | 5/5 |
| CA-30–36 | 7/7 |
| CA-37–44 | 8/8 |

Resultado: **44/44 casos representables**. CA-31 usa impacto `COMMUNICATION_RECOMMENDED`, calendario/umbral de planta y aprobación D097; CA-24 conserva inbox idempotente.

## 9. Revalidación de 22 casos difíciles

| Grupo | Cobertura |
|---|---:|
| CD-01–05 | 5/5 |
| CD-06–10 | 5/5 |
| CD-11–15 | 5/5 |
| CD-16–18 | 3/3 |
| CD-19–22 | 4/4 |

Resultado: **22/22 preservados**, incluidos herrajes, banco nocturno, equipo variable, ventanas, recepción compartida, idempotencia, concurrencia, comunicación, token, corrección real y fallo de publicación.

## 10. UX-01 a UX-10

| UX | Estado |
|---|---|
| UX-01 — demora y nuevo fin | SOPORTADO |
| UX-02 — finalización anticipada | SOPORTADO |
| UX-03 — drag válido | SOPORTADO |
| UX-04 — drag imposible explicado | SOPORTADO |
| UX-05 — desplazamiento en cascada | SOPORTADO |
| UX-06 — cancelar conserva Current | SOPORTADO |
| UX-07 — confirmar crea versión | SOPORTADO |
| UX-08 — ejecutado inmutable | SOPORTADO |
| UX-09 — banco nocturno sin persona | SOPORTADO |
| UX-10 — cambio de fecha resaltado | SOPORTADO |

Resultado: **10/10 soportados**.

## 11. Siete comandos de reprogramación

| Comando | Estado | Estructuras principales |
|---|---|---|
| `UPDATE_REMAINING_ESTIMATE` | SOPORTADO | D085–D090, D060/D061/D064, D070/D076 |
| `RESIZE_SCHEDULED_ACTIVITY` | SOPORTADO | D070/D071/D076–D084 |
| `MOVE_SCHEDULED_ACTIVITY` | SOPORTADO | D070/D071 y reservas contextuales |
| `REPLAN_FROM_OPERATION` | SOPORTADO | escenario, cierre de precedencias e impactos |
| `REPLAN_PROJECT` | SOPORTADO | escenario por planta e impactos interproyecto |
| `ACCEPT_REPLAN` | SOPORTADO | D002/D060/D069/D104/D102 en commit único |
| `REJECT_REPLAN` | SOPORTADO | estado D070; Current y restante intactos |

Resultado: **7/7 soportados**. La interfaz permanece aislada de segmentos, reservas, locks y revisiones.

## 12. Temporalidad

- Todos los instantes usan `timestamptz`.
- Disponibilidad semanal usa hora local más zona IANA.
- Rangos `[)` evitan doble consumo en límites contiguos.
- GiST/EXCLUDE protege personas y recursos exclusivos dentro de una solución.
- S18 y S19 pueden superponerse porque `schedule_solution_id` forma parte del contexto.
- Ocupación real efectiva se protege globalmente.
- Trabajo, reserva y ocupación tienen rangos separados.
- Capacidad acumulativa queda en motor y revalidación transaccional.

## 13. Concurrencia

La promoción conserva esta secuencia:

1. bloquear planta/contexto;
2. bloquear state head;
3. validar versión vigente y lock version;
4. validar `PlanningStateRevision`;
5. validar `ProductDefinitionRevision`;
6. validar escenario/solución y hechos reales;
7. crear nueva versión y cerrar la anterior;
8. actualizar puntero vigente;
9. auditar y emitir outbox;
10. commit único.

Orden de locks estable y optimistic locking para ediciones normales. Un escenario stale nunca se promueve.

## 14. Multitenancy y seguridad

- 8 schemas mantenidos por límites funcionales y permisos.
- `organization_id` directo o derivable con FK tenant-safe.
- No se permiten referencias cruzadas entre organizaciones.
- `auth_subject` externo compatible con Supabase Auth; sin passwords propios.
- Roles V1 cerrados y asignaciones con planta/vigencia.
- Portal accede exclusivamente a proyección allowlist.
- Soluciones/snapshots/versiones finales sin UPDATE para roles normales.
- Inbox, outbox y auditoría con permisos separados.

## 15. Auditoría e integración

La historia natural permanece en versiones, eventos, ejecución, restante y fechas comunicadas. D104 registra acciones sensibles. La promoción se evidencia por D069 y `SCENARIO_PROMOTED` dentro de la misma transacción.

Compras se integra por API + eventos versionados + idempotencia. D101 evita recepción duplicada; D102 publica después del commit. No comparte base ni tablas de negocio con Producción.

## 16. Riesgos residuales

- Capacidad acumulativa requiere validación del motor.
- Contratos de roles/eventos/excepciones deben versionarse en código.
- Un calendario base no soporta overlays múltiples V1.
- Una solución por run limita portfolios de alternativas internas.
- Una planta tiene un solo programa publicado.
- La auditoría pública no conserva un snapshot legal especializado.
- Explicaciones dependen de diagnósticos estructurados de calidad.
- Los 28 índices secundarios deberán verificarse con planes reales.

Ningún riesgo residual constituye una brecha para la V1 aprobada.

## 17. Decisiones diferidas

- Roles personalizados.
- Calendarios simultáneos/overlays.
- Herrajes por componente.
- Paquete especializado de instalación.
- Detalle indexable por entidad de state revision.
- Catálogos tenant de eventos/excepciones.
- Múltiples programas por planta.
- Escenario/evento N:M arbitrario.
- Varias soluciones por run.
- Workflow avanzado de comunicación y snapshot legal público.
- Tabla especializada de promociones.

Todas tienen camino de reincorporación documentado en la auditoría de simplificación.

## 18. Conclusión formal

La aplicación formal de la simplificación terminó con 87 tablas consistentes entre esquema y diccionario, 68 familias de constraints, 28 familias de índices secundarios, 45/45 invariantes, 44/44 casos de aceptación, 22/22 casos difíciles, UX-01 a UX-10 y 7/7 comandos. No se detectó `BRECHA_ESQUEMA_FISICO`.

**`ESQUEMA_SIMPLIFICADO_APTO_PARA_MIGRACIONES`**

Esta conclusión habilita diseñar migraciones en una etapa posterior; no crea ni ejecuta SQL por sí misma.
