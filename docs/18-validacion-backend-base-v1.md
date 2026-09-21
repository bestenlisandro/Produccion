# Validación del primer incremento backend V1

Fecha de validación: 2026-09-04.

## 1. Alcance cerrado

Se implementó y probó exclusivamente el caso de uso `UPDATE_REMAINING_ESTIMATE`. No se implementaron proyectos, lotes, inicio/fin de ejecución, API FastAPI, scheduler, Gantt ni portal.

El incremento mantiene las capas separadas:

- `domain`: comando, resultado, dimensiones y errores de negocio;
- `application`: servicio y puerto de unidad de trabajo;
- `persistence`: transacción SQLAlchemy 2 Core contra PostgreSQL;
- `infrastructure`: configuración y creación del engine desde variables de entorno.

## 2. Entorno efectivo

- Python 3.11.5;
- FastAPI 0.141.1 instalado, todavía sin endpoints;
- SQLAlchemy 2.0.52;
- psycopg 3.3.5;
- Pydantic 2.13.5;
- pytest 8.4.2;
- PostgreSQL 18.6 local;
- entorno aislado `.venv`;
- dependencias instaladas con TLS verificado mediante `truststore`;
- conexión obtenida exclusivamente de `DATABASE_URL` o `TEST_DATABASE_URL`.

No se usó `--trusted-host`, no se desactivó TLS y no se modificó Python global.

## 3. Módulos implementados

- `src/production_besten/domain/errors.py`;
- `src/production_besten/domain/remaining_estimate.py`;
- `src/production_besten/application/ports.py`;
- `src/production_besten/application/update_remaining_estimate.py`;
- `src/production_besten/persistence/database.py`;
- `src/production_besten/persistence/remaining_estimate_uow.py`;
- `src/production_besten/infrastructure/settings.py`;
- pruebas unitarias en `tests/unit`;
- pruebas PostgreSQL reales en `tests/integration`.

No se generaron modelos ORM para las 87 tablas. El adaptador usa SQLAlchemy 2 Core y SQL explícito sobre el subconjunto requerido.

## 4. Transacción y locks

El comando completo ocurre en una sola transacción:

1. valida el comando y sus dimensiones;
2. busca por `organization_id + operation_execution_id` y bloquea `operation_executions` con `FOR UPDATE`;
3. valida que el estado sea `running` o `paused`;
4. valida que las fases declaradas pertenezcan a la operación;
5. bloquea la revisión restante vigente y verifica `expected_revision_no`;
6. deriva trabajo humano ejecutado desde `actual_resource_usages` vigentes al corte, sin aceptar ese valor desde la pantalla;
7. lee `labor_minutes` del snapshot original congelado;
8. bloquea `planning_state_heads` con `FOR UPDATE`;
9. crea una `PlanningStateRevision` y el evento `REMAINING_ESTIMATE_UPDATED`;
10. avanza el state head exactamente una vez;
11. marca la revisión anterior como sustituida apuntando al UUID ya reservado del sucesor;
12. inserta la nueva `RemainingEstimateRevision` y sus `RemainingResourceEstimate` explícitos;
13. fuerza las constraints diferidas y confirma.

Ante una excepción, la unidad de trabajo ejecuta rollback. El plan publicado y `core.plants.current_plan_version_id` no se modifican.

El orden estable de locks es ejecución → revisión vigente → state head. Dos comandos con la misma revisión esperada se serializan; el segundo observa la nueva revisión y recibe `RevisionConflict`.

## 5. Validaciones realizadas

La base descartable recibió M0–M10 sin modificaciones adicionales y pasó los verificadores existentes: 8 schemas, 87 tablas, 297 FK, 159 UNIQUE, 154 CHECK, 7 EXCLUDE y 290 índices.

Desde Python se comprobó realmente:

- apertura de conexión y `SELECT 1`;
- transacción explícita y rollback;
- lectura de 8 schemas y 87 tablas;
- caso 10 h original, 7 h ejecutadas, 5 h restantes y total actualizado 12 h;
- preservación del snapshot original;
- preservación de R1 y creación append-only de R2;
- segunda actualización con secuencia R1 → R2 → R3;
- coexistencia independiente de `LABOR_WORK=120`, `ACTIVE_PHYSICAL_USE=90` y `PHYSICAL_OCCUPATION=600` minutos;
- un único sucesor vigente;
- incremento exacto de `PlanningStateRevision`;
- creación de `EffectiveEvent`;
- plan publicado intacto;
- rechazo cross-organization aun usando un UUID real de otra organización;
- rollback inducido después de sustituir la revisión anterior: cero filas parciales y state head intacto;
- dos comandos concurrentes: un éxito, un `RevisionConflict`, un único evento y una única revisión vigente.

Resultado final de pytest:

```text
10 passed in 2.98s
```

Son 2 pruebas unitarias y 8 pruebas de integración real, sin mocks para el núcleo crítico.

## 6. Errores encontrados y correcciones

1. La prueba inicial de conexión intentó abrir una transacción explícita después de un `SELECT`, que en SQLAlchemy 2 ya había iniciado `autobegin`. Se cerró esa transacción antes de la prueba de rollback.
2. El fixture embebía JSON con `:` dentro de `text()`, interpretado como bind parameter. Se parametrizó el JSON y se convirtió explícitamente a `jsonb`.
3. La consulta inicial leyó `current_plan_version_id` desde `core.projects`; el campo pertenece a `core.plants`. Se agregó el join tenant-safe a planta.
4. El cálculo de ejecutado se reforzó para excluir tanto segmentos como usos humanos reemplazados por sucesores históricos.

No se modificaron migraciones ni constraints durante este incremento.

## 7. Riesgos residuales y límites conscientes

- El snapshot V1 exige la clave canónica `labor_minutes`; la canonicalización completa se resolverá al implementar el inicio de ejecución.
- El corte suma usos humanos cerrados cuyo rango termina antes o en `cutoff_at`; no prorratea un uso todavía abierto. La futura captura en tiempo real deberá cerrar o segmentar el tramo al corte.
- Este incremento registra el hecho y avanza el estado, pero no crea todavía el escenario de simulación ni ejecuta scheduling.
- RLS sigue pendiente de identidad real; la barrera actual es filtro tenant explícito más FK compuestas.
- No existe todavía API pública o interna que exponga el servicio.

## 8. Conclusión

`UPDATE_REMAINING_ESTIMATE_VALIDADO_EN_POSTGRESQL`

---

# Etapa 4.2 — Validación de ejecución real

Fecha: 2026-09-04.

## 9. Servicios agregados

- `StartOperationService`;
- `RegisterExecutionSegmentService`;
- `FinishOperationService`;
- `PostgresExecutionUnitOfWork` y su factory;
- comandos, resultados y errores de ejecución en la capa de dominio.

No se agregaron endpoints ni se modificaron las 11 migraciones validadas.

## 10. Planificación versus ejecución

Las referencias planificadas permanecen inmutables: `origin_plan_version_id`, `origin_operation_plan_result_id`, `origin_assignment_segment_id`, asignaciones humanas y reservas físicas. Los hechos reales viven por separado en `operation_executions`, `execution_segments`, `actual_resource_usages` y `physical_occupations(source_kind='actual')`.

Se verificó un plan con persona y banco previstos distintos de los realmente utilizados. El puntero de plan, el segmento previsto, la persona prevista y la reserva prevista conservaron exactamente sus valores.

## 11. Transacciones y locks

Cada comando crea como máximo una `PlanningStateRevision` y un `EffectiveEvent` dentro de la misma transacción que sus hechos reales.

- `START_OPERATION`: lock sobre operación requerida; evita dos ejecuciones activas. Congela original, crea ejecución, R1, evento y revisión operativa.
- Inicio de fase posterior: conserva la ejecución y registra `PHASE_STARTED` después de validar fases anteriores.
- `REGISTER_EXECUTION_SEGMENT`: lock sobre ejecución; crea segmento, usos reales y ocupaciones atómicamente.
- `FINISH_OPERATION`: lock sobre ejecución; registra cierre de fase y sólo completa la operación al terminar la última fase.
- `UPDATE_REMAINING_ESTIMATE` y finish comparten el primer lock sobre ejecución y se serializan.

Los failpoints probaron rollback después de insertar ejecución, segmento y estado final. En todos los casos se restauraron filas, eventos y state head.

## 12. Gates y fases

El evaluador no contiene una regla hardcodeada para Armado. Evalúa targets tipados de `operation_gates`: `available_at`, herrajes del lote, material asignado, plano liberado e hito ocurrido.

Se validó que un gate `HARDWARE_READY` pendiente permita trabajo parcial pero rechace finish. También se validó Prearmado → espera sin trabajo → inicio de Terminación → cierre total.

Límite V1: `operation_gates` instanciada y `required_operation_phases` no contienen un flag de opcionalidad. Todo gate instanciado y toda fase no archivada se tratan como obligatorios. Una futura opcionalidad requiere evolución explícita del modelo.

## 13. Idempotencia y concurrencia

La estrategia V1 usa `command_id` UUID, persistido en la referencia externa única del evento:

- replay idéntico devuelve el resultado original;
- la misma clave con otro target se rechaza;
- claves distintas siguen sujetas a locks y reglas de negocio.

Resultados reales:

- doble start: un éxito y un `ExecutionAlreadyActive`;
- doble finish: un éxito y un `ExecutionAlreadyCompleted`;
- remaining estimate vs finish: serialización sin revisión perdida;
- ninguna prueba produjo dos ejecuciones activas, dos eventos finales o dos revisiones incompatibles.

## 14. Casos validados

Se agregaron 20 pruebas de integración real que cubren los 18 casos requeridos y además idempotencia y rollback separado:

1. start planificado y sin planificación;
2. replay idempotente;
3. segmento real y varias jornadas separadas;
4. persona y recurso reales distintos de los previstos;
5. ocupación nocturna sin horas-persona nocturnas;
6. finish normal e idempotente;
7. finish bloqueado por gate;
8. operación multifase y espera;
9. terminación anticipada y tardía;
10. cinco variantes cross-tenant;
11. doble start y doble finish concurrentes;
12. remaining estimate concurrente con finish;
13. rollback separado de start, segmento y finish;
14. historia planificada intacta.

Los 10 tests anteriores permanecen aprobados. Resultado final:

```text
30 passed in 4.43s
```

## 15. Errores encontrados y correcciones

1. La detección concurrente de fase iniciada sólo reconocía `PHASE_STARTED`; el segundo start de la primera fase podía interpretar que la ejecución activa correspondía a una fase no iniciada. Se incorporó `OPERATION_STARTED + phase_id`. La carrera pasó con un único inicio.
2. La idempotencia inicial devolvía cualquier evento con la misma clave sin verificar target. Se agregó validación de operación, ejecución y fase.
3. El soporte de fases se completó permitiendo `START_OPERATION` sobre una ejecución activa únicamente para una fase posterior válida, sin crear otra ejecución.

## 16. Riesgos residuales

- Disponibilidad estructural V1 valida estado activo, tenant, habilidades, cantidades mínimas y solapamientos reales. La evaluación completa de calendarios, excepciones y horas extra queda para un refinamiento posterior.
- El trabajo real al corte sólo suma usos humanos cerrados; un tramo abierto debe cerrarse o segmentarse.
- Las ocupaciones reales se registran con fin conocido. Una ocupación abierta y liberación posterior requerirá un comando compatible con la constraint de rango actual.
- No se genera todavía simulación de impacto ni se modifica el programa futuro.
- RLS continúa pendiente; hoy operan filtros tenant explícitos y FK compuestas.

## 17. Conclusión Etapa 4.2

`EXECUTION_COMMANDS_VALIDATED_IN_POSTGRESQL`

---

# Etapa 4.3 — Proyectos y definición productiva versionada

Fecha: 2026-09-07.

## 18. Alcance implementado

Se agregaron los servicios `CREATE_PROJECT`, `CREATE_PRODUCTION_BATCH`,
`DEFINE_BATCH_ROUTE`, `CREATE_REQUIRED_OPERATION`,
`CREATE_REQUIRED_OPERATION_PHASE` y `CREATE_PRODUCT_DEFINITION_REVISION` mediante
dominio, aplicación y un Unit of Work PostgreSQL específico. No se agregaron API,
frontend, Gantt, portal, integración con Compras ni motor de scheduling.

`CREATE_PRODUCTION_BATCH` crea el lote productivo perteneciente al proyecto en
`core.project_lots`. No usa el agregado diferente `production.production_batches`,
destinado a lotes operativos compartidos.

## 19. Lifecycle y límite transaccional

El proyecto nace en `draft` y no incrementa el estado mientras esté vacío. Lotes,
rutas activas, operaciones y fases forman el draft productivo normalizado editable.
Cada comando programable inserta su agregado completo, evento efectivo y una sola
`PlanningStateRevision`; un fallo revierte todo.

La revisión productiva congela el draft completo de la planta, enlaza a su padre y
mueve `current_product_definition_revision_id` atómicamente. Las revisiones previas
no se actualizan. El plan vigente, resultados y reservas programadas nunca se
reescriben por estos comandos; los escenarios con base anterior quedan detectables
como obsoletos comparando sus revisiones base con los punteros actuales.

## 20. Canonicalización y hash

El contrato usa `snapshot_schema_version=1` y `canonicalization_version=1`. Captura
proyectos, lotes, materiales, planos, ruta activa y su configuración, operaciones,
fases, precedencias, estimaciones, requisitos humanos/físicos y gates. Excluye UUID,
timestamps técnicos, row versions y autores. Usa códigos semánticos y scope de lote,
orden explícito de colecciones, UTC ISO 8601, decimales normalizados, claves JSON
ordenadas, separadores compactos y UTF-8. SHA-256 se calcula sobre esa representación.

Un congelado idéntico devuelve la revisión vigente sin crear historia inútil ni
incrementar `PlanningStateRevision`. Un hash igual a una revisión histórica no
vigente se rechaza hasta contar con un caso de uso explícito de reactivación.

## 21. Concurrencia, multitenancy y rollback

Todas las mutaciones de definición bloquean primero la planta. Dos altas de lote se
serializan luego sobre el proyecto y reciben secuencias distintas. Dos congelados
simultáneos producen una sola revisión semántica. Una mutación concurrente con un
congelado queda totalmente antes o después: el snapshot nunca contiene un agregado
parcial.

Los UUID siempre se consultan con `organization_id`; además se validaron relaciones
privadas como cliente, prioridad, ruta, definición de operación, skills, centros y
targets de gates. Las FK compuestas siguen siendo la segunda barrera. La reutilización
de `command_id` con datos diferentes se rechaza.

Se inyectaron fallos después de insertar lote, asignación de ruta, operación, fase y
después de mover el puntero de revisión. No quedaron filas parciales, eventos ni bumps.

## 22. Validación real

Se reaplicaron M0–M10 sin modificaciones en una base descartable y pasaron
`verify_schema.sql` y `temporal_scenarios.sql`: 8 schemas, 87 tablas, 297 FK, 159
UNIQUE, 154 CHECK, 7 EXCLUDE, 290 índices, 5 triggers y 4 funciones mínimas.

Se agregaron 45 pruebas PostgreSQL reales, incluyendo:

- proyecto, duplicados y tenant incorrecto;
- uno, varios y dos lotes concurrentes;
- rutas distintas por lote, reemplazo con historia y rechazo de borrador;
- operación sin programación, una/múltiples fases, precedencias y rechazo de ciclo;
- requisitos humanos, uso físico, ocupación y gates de material, planos y herrajes;
- D1, D2, snapshot/hash determinista, D1 inmutable y no duplicación semántica;
- bump único, escenario obsoleto sin tocar el plan, idempotencia y rollback;
- dos congelados y mutación contra congelado concurrentes;
- cinco variantes cross-organization.

Resultado final junto con las 30 pruebas anteriores:

```text
75 passed
```

## 23. Errores encontrados y correcciones

1. La primera versión de la carrera de mutación/congelado sólo comprobaba que ambas
   operaciones terminaran. Se endureció para correlacionar contenido del snapshot con
   el orden real de `PlanningStateRevision`.
2. El snapshot inicial de ruta no incluía plantillas de requisitos/gates ni gates a
   nivel operación. Se completó el contrato canónico.
3. Materiales y paquetes de planos eran alcanzables desde gates pero no aparecían
   como definición propia del lote. Se incorporaron por código y scope semántico.
4. El replay de definición validaba sólo el tipo de entidad. Se agregó comparación
   de target/datos para impedir reutilización silenciosa de una clave.

No se modificaron migraciones.

## 24. Riesgos residuales

- Faltan comandos explícitos para editar/archivar campos ya creados en el draft;
  deberán usar el mismo lock raíz y bump único.
- La reactivación de un snapshot histórico idéntico requiere una decisión/caso de uso.
- La protección contra `UPDATE` directo de una revisión depende todavía de privilegios
  de base; RLS y rol de aplicación de mínimo privilegio no están desplegados.
- La validación de ciclos cubre el grafo local completo del proyecto en cada alta de
  aristas, pero futuras ediciones/bajas de precedencia deberán reutilizarla.
- No existe aún scheduling, simulación automática ni cálculo de huecos.

## 25. Conclusión Etapa 4.3

`PRODUCT_DEFINITION_COMMANDS_VALIDATED_IN_POSTGRESQL`

---

# Etapa 4.4 — API interna mínima

Fecha: 2026-09-07.

## 26. Implementación

Se agregó una app FastAPI creada por factory, schemas Pydantic 2 separados del
dominio, routers finos, consultas tenant-safe, traducción centralizada de errores,
health/readiness y `RequestContext` intercambiable. Los endpoints reutilizan los diez
comandos validados; no contienen inserts, commits ni reglas productivas.

La adaptación simplificada de tiempo restante consulta ejecución activa, fase y
revisión vigente. Cuando la fase posee un único requisito laboral obligatorio, la
API deriva skill y dotación; ejecutado, total y nuevas revisiones siguen calculándose
en el servicio de dominio/persistencia.

## 27. Contexto, seguridad e idempotencia

`DevRequestContextProvider` está marcado `DEV ONLY`. Lee UUID desde headers
`X-Dev-User-Id`, `X-Dev-Organization-Id` y el opcional `X-Dev-Plant-Id`. No existen
passwords propios ni se presenta esta cabecera como seguridad real. Deshabilitado,
responde 503 hasta instalar el futuro provider de Supabase Auth. Los queries filtran
organización y planta sin consultar globalmente para distinguir “ajeno” de “ausente”.

`Idempotency-Key` UUID es el único mecanismo para los comandos que tienen
`command_id`. Replay idéntico funciona y reutilización incompatible devuelve 409.
Se incorporó el error de dominio `IdempotencyConflict` para no clasificar ese caso
como request semántica 400.

## 28. Validación real

Sobre PostgreSQL 18.6 se reaplicaron M0–M10 sin cambios y volvieron a pasar los
verificadores de 8 schemas, 87 tablas y escenarios temporales/multitenancy.

Se agregaron 26 pruebas HTTP para:

- crear/obtener proyecto y ocultar recursos cross-tenant;
- crear/listar lote, asignar ruta, crear operación y fase;
- congelar/reutilizar revisión sin exponer el snapshot;
- inicio no planificado, segmento real, finish y estimación restante simplificada;
- 400, 404, 409 y 422;
- replay válido e incompatibilidad de idempotencia en definición y ejecución;
- gate bloqueado, concurrencia con un solo start y rollback desde HTTP;
- contexto DEV deshabilitado, health, ready y OpenAPI.

Resultado total:

```text
101 passed, 2 warnings
```

Las dos advertencias provienen de APIs de compatibilidad/deprecación de
`fastapi.testclient` y `starlette.testclient` con httpx/anyio; no indican fallos de
producto.

## 29. Errores encontrados y correcciones

1. El factory real de estimación restante tenía un nombre más corto que el asumido
   inicialmente; se corrigió el import y se reutilizó sin modificar el caso de uso.
2. La reutilización incompatible de claves de ejecución producía `InvalidEstimate`;
   se introdujo `IdempotencyConflict` y su traducción uniforme a 409.
3. El endpoint de segmentos filtraba organización mediante el servicio, pero no la
   planta opcional del contexto. Se agregó la lectura tenant/plant-safe antes de invocar.
4. Se agregó un handler 500 genérico para que un rollback inesperado no exponga SQL,
   nombres de tablas ni stack traces.

No se modificaron migraciones.

## 30. Riesgos residuales

- `DevRequestContextProvider` confía en headers: sólo es aceptable en desarrollo/tests.
- Supabase Auth, memberships, capabilities reales y RLS continúan pendientes.
- `/ready` valida conectividad, pero todavía no comprueba lag, permisos mínimos ni
  compatibilidad de versión de migraciones.
- No hay paginación porque los únicos listados V1 son mínimos.
- Las advertencias de TestClient requieren alinear dependencias en un incremento futuro.
- No se implementaron scheduler, Gantt, frontend, portal ni integración con Compras.

## 31. Conclusión Etapa 4.4

`MINIMAL_API_V1_VALIDATED`

---

# Etapa 5.1 — Validación del planificador factible

Fecha: 2026-09-07.

## 32. Implementación validada

Se agregó `v1-greedy-1`: planificación greedy hacia adelante, DAG, prioridad estable,
calendarios efectivos, personas/skills, dotación, proporcionalidad opt-in, recursos
exclusivos, fases, gates, horas extra, división en jornadas, ocupación física continua
y conservación parcial al agotar el horizonte.

El cálculo crea únicamente escenario y solución. Se comprobó que el plan vigente,
sus asignaciones y su puntero permanecen intactos. El input completo, sus revisiones,
algoritmo y hashes quedan persistidos.

## 33. Pruebas reales

M0–M10 permanecieron sin cambios. Los verificadores confirmaron 8 schemas, 87 tablas,
297 FK, 159 UNIQUE, 154 CHECK, 7 EXCLUDE y 290 índices.

Se agregaron 37 pruebas PostgreSQL reales, incluidos los 25 casos mínimos y casos
adicionales de snapshot/hash, ocupación nocturna, overtime y límite, calendario
individual, proporcionalidad opt-in, recurso concreto, cumulative diferido en 5.1, entrega
futura, solución parcial y ruta principal de muebles.

```text
138 passed, 2 warnings in 22.48s
```

Las dos advertencias son las mismas de compatibilidad/deprecación de TestClient de
Etapa 4.4 y no afectan al motor.

## 34. Errores encontrados y correcciones

1. Una fase divisible descartaba segmentos válidos al no completar dentro del
   horizonte. Ahora persiste el avance como `out_of_horizon` y el saldo separado.
2. El desempate para maximizar avance parcial también se aplicaba a soluciones
   completas y podía elegir la alternativa más lenta. Se limitó a incompletas.
3. Se corrigieron límite exclusivo del horizonte para vigencias, casts de
   `daterange`, orden estable de sets y asociación exacta de requerimientos físicos.
4. En 5.1 se hizo explícito el rechazo de cumulative y se incorporó `max_minutes` de
   horas extra. El rechazo fue reemplazado por soporte real en 5.2.

## 35. Riesgos residuales

Persisten las simplificaciones de `docs/21-motor-planificacion-v1.md`: capacidad
variable por franja, precedencias avanzadas, ejecución/remaining dentro del replanning, setups,
optimización, promoción y superficies de usuario. Ninguna se presenta como soportada.

## 36. Conclusión Etapa 5.1

`BASIC_FINITE_CAPACITY_SCHEDULER_VALIDATED`

## 37. Validación incremental Etapa 5.2

- versión del motor: `v1-greedy-2`;
- esquema estático: 87 tablas, 617 constraints, 297 FK, sin migraciones nuevas;
- PostgreSQL: 18.6, `127.0.0.1:5432`;
- `TEST_DATABASE_URL`: configurada sólo por proceso, sin persistir el secreto;
- pruebas recolectadas y aprobadas: 172/172;
- integración PostgreSQL: 160 pruebas;
- unitarias/benchmark puro: 12 pruebas;
- primera corrida completa previa a cobertura adicional: 169 passed en 36,68 s;
- corrida con uso real persistido: 170 passed en 11,42 s;
- recreación limpia final con M0–M10: 172 passed en 12,40 s;
- benchmark PostgreSQL pequeño: 3 proyectos, 12 operaciones, 2 reservas, 112,36 ms;
- benchmark PostgreSQL moderado: 20 proyectos, 100 operaciones, 20 reservas, 898,40 ms.

Conclusión reproducible de la sesión:

`CUMULATIVE_CAPACITY_SCHEDULER_VALIDATED`

## 38. Validación incremental Etapa 5.3

El 2026-09-18 se incorporó `v1-replan-1` sin migraciones. Una recreación descartable
de PostgreSQL 18.6 aprobó M0–M10 y los verificadores de 8 schemas/87 tablas. Antes de
agregar cobertura, las 172 pruebas históricas volvieron a pasar. La cobertura nueva
sumó 35 casos PostgreSQL e incluyó retry concurrente, escenarios paralelos,
rollback, multitenancy, cutoff, saldo de ejecución, comparación, rechazo e
inmutabilidad del plan vigente. La corrida final completa obtuvo 208/208 aprobadas.

El benchmark end-to-end PostgreSQL de 10 proyectos/50 operaciones registró 428,64
ms; el núcleo puro con 10 reservas, 36,63 ms. El detalle funcional y los límites están en
`docs/23-reprogramacion-desvios-v1.md`.

## 39. Validación incremental Etapa 5.4

El 2026-09-21 se implementó `ACCEPT_REPLAN` sin cambiar `v1-greedy-2` ni agregar
migraciones. La operación conserva V5 como `superseded`, crea V6 `published`, mueve
el único puntero vigente, confirma el escenario y registra auditoría/outbox en la
misma transacción. Se validaron idempotencia, un solo ganador concurrente, rechazo de
bases stale, multitenancy y rollback en seis puntos. La API mínima y su OpenAPI
quedaron cubiertos. Resultados finales y benchmark: `docs/24-promocion-programa-v1.md`.

La recreación final obtuvo `260 passed, 2 warnings in 24.45s`: 208 regresiones y 52
casos nuevos. Los warnings son deprecaciones externas ya conocidas; no hubo failed
ni skipped.
