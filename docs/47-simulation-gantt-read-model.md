# Gantt de simulación de una revisión nueva contra CURRENT

Diagnóstico y corrección sobre `master`, HEAD `1075636`, 2026-11-04.
No se modificó ningún dato real ni se generó otra simulación.

## Request que fallaba y causa demostrada

URL de entrada:
`http://127.0.0.1:5173/planning/gantt?scenario_id=00f1ae78-401d-4251-9413-4dd05cd0cc38`.

El navegador real reproducía este request:

```text
GET /api/planning/current/gantt
  ?from=2026-11-02T00:00:00.000Z
  &to=2026-11-09T00:00:00.000Z
  &group_by=project
  &scenario_id=00f1ae78-401d-4251-9413-4dd05cd0cc38
```

Vite elimina `/api` antes de enviarlo al backend. Resultado original: HTTP 404,
`{"error":{"code":"RESOURCE_NOT_FOUND","message":"resource not found"}}`.
No había X-Request-Id ni request_id en la respuesta. El access log registraba 404;
no existía stack trace de 500. La causa de dominio es
`EntityNotFound('scenario not found')` en el read model del Gantt.

Las pruebas directas con headers DEV dieron:

| Lectura | Antes del fix |
| --- | --- |
| `/health` | 200 |
| `/scenarios/{id}` | 200 |
| `/master-data/snapshot` | 200 |
| `/planning/current/gantt` con rango, sin scenario_id | 200 |
| Mismo Gantt con scenario_id de simulación 9 | 404 |

La DB identifica el escenario 9 como `scenario_kind='simulation'`, status ready,
completo, basado en REV 5 y CURRENT V1. El productor normal de escenarios utiliza
`simulation` cuando existe CURRENT. Las dos consultas del Gantt (selección y
listado de opciones) sólo admitían `initial` y `replan`, por lo que filtraban
silenciosamente este escenario válido antes de construir operaciones o comparación.
El endpoint genérico de detalle no aplicaba ese filtro y sí encontraba el registro.

No era una restricción por revision_id, DAG paralelo, nombres, material_arrival,
serialización de segmentos ni estado ready. La lectura de la misma simulación
responde 200 al admitir su tipo, sin cambiar su contenido.

## Corrección acotada

- `persistence/api_queries.py`: incluir `simulation` en ambos filtros de lectura
  del Gantt. Se reutilizan el read model y la comparación temporal contra CURRENT.
- `scenarioPresentation.ts`: mostrar **Simulación**, sin clasificarla como Replan.
- `GanttPage.tsx`: extender a toda comparación con CURRENT la aclaración ya existente
  de que personas/recursos y segmentos detallados corresponden al plan vigente;
  la superposición expone fechas propuestas. No se alteran las asignaciones.
- `api/errors.py`: respuestas de error con X-Request-Id y campo aditivo
  `error.request_id`; log correlacionado con método, path, status, error_code y
  detalle de dominio. Las excepciones inesperadas se registran en backend y mantienen
  respuesta segura. No se envían stacks al usuario.
- `frontend/src/api/client.ts`: conservar requestId en ApiError y registrarlo junto
  al código/status en consola. Se mantiene el mensaje genérico seguro de la UI.

El contrato exitoso del Gantt ya declaraba scenario_kind como string. Exportar
OpenAPI no produjo diff. No se modificaron scheduler, ACCEPT, fechas, precedencias,
revisiones, escenarios, CURRENT ni políticas de vencimiento.

Una consulta deliberada de un UUID inexistente verificó la nueva correlación:
HTTP 404, código RESOURCE_NOT_FOUND y request_id
`0947b778-6869-42f2-9ab3-95d11ecdf919`, presente también en el log backend.

## Regresión y validación

El test PostgreSQL nuevo construye en DB descartable CURRENT V1 desde una
definición anterior en cadena, crea REV 5 con material_arrival Caso 1 y ramas
Corte/Múltiple independientes, y genera una simulación mediante la API normal.
Comprueba tipo simulation, ready, no stale, comparación de cuatro operaciones,
etiquetas nuevas, dos predecesoras de Armado y plan CURRENT sin modificaciones.
No utiliza ACCEPT para construir la nueva propuesta. También prueba la correlación
de errores para un escenario inexistente.

Frontend: test de URL directa con scenario_id, etiquetas, comparación con CURRENT
V1, mensaje seguro y logging correlacionado. E2E en cuatro viewports comprueba la
carga, las barras propuestas y el DAG de dos ramas sin requests mutantes.
El fixture E2E devuelve el rango solicitado para que Ajustar al plan permita
inspeccionar conectores de la base anterior y la propuesta en una misma ventana.

Resultados finales:

- Backend relevante: **48 passed**, cero fallas; API, Gantt, revisión nueva,
  iniciales, históricos, aislamiento y reglas existentes de promoción/expiry.
  PostgreSQL descartable y rol eliminados.
- Vitest relevante: **65 passed**, ocho archivos; incluye Gantt y notificaciones.
  Tras ajustar la espera del test de URL directa se repitió GanttPage:
  **18 passed**, cero fallas. Subsisten avisos de MSW/act de tests anteriores.
- Playwright Gantt: **28 casos distintos aprobados**, cuatro viewports. La última
  ejecución conjunta pasó 26; dos navegaciones de tablet fallaron transitoriamente
  mientras Vite build reconstruía dist servido por preview. Se repitieron sólo
  esos dos después de terminar el build: ambos pasaron. La regresión nueva pasó
  en los cuatro viewports. No se modificó código para esos reintentos.
- TypeScript/Vite: aprobados; warning conocido de tamaño de bundle.
- OpenAPI exportado, sin cambios en el archivo generado.
- git diff --check y secret scan verificados al cierre.

## Verificación real y alcance

Después de reiniciar exclusivamente el backend de Producción, el navegador abrió
la URL original y recibió HTTP 200 en ambos rangos (UTC inicial y zona de planta).
Se renderizaron CURRENT V1, la simulación seleccionada y los nombres nuevos.
La inspección bloqueó todos los métodos mutantes y contó cero intentos de escritura.

El contenido de las **87 tablas coincide exactamente** por conteos y SHA-256 con
el baseline anterior al diagnóstico. REV 5 continúa released; escenario 9 ready,
complete=true, no aceptado; nueve escenarios totales, CURRENT V1 publicado y cero
ejecuciones. Sin CURRENT V2 ni modificación de maestros o revisiones.

Segmentos de simulación conservados, zona America/Argentina/Cordoba:

| Operación | Segmentos |
| --- | --- |
| Corte Fondos 3 mm | 04/11 12:45–13:05 |
| Procesado Múltiple 18 mm | 04/11 12:45–13:45 |
| Armado | 04/11 13:45–15:45 |
| Instalacion | 04/11 15:45–17:00 y 05/11 08:00–09:45 |

Precedencias: Corte → Armado, Múltiple → Armado, Armado → Instalacion.
La verificación contra el baseline incluye snapshots, precedencias y asignaciones.

Al finalizar el diagnóstico ya había pasado el inicio de 12:45. La lectura calcula
`expired=true` y la UI muestra **SIMULACIÓN DESACTUALIZADA**; esto es el vencimiento
normal por reloj, no una mutación del escenario ni el error de carga original.
El status persistido sigue ready. La confirmación se mantiene inhabilitada por
las reglas existentes; no se generó otra simulación para evitar el aviso.

Evidencia técnica ignorada por Git en `test-results/gantt-simulation9-fix/`:
baseline, respuestas HTTP, requests reales antes/después, capturas, logs y respuesta
Gantt completa. La captura final es `gantt-fixed.png`.

Cambios de código y tests sin commit ni push. App de Compras y backup no fueron accedidos.


## Archivos pendientes para revisión

Modificados:

- `src/production_besten/persistence/api_queries.py`
- `src/production_besten/api/errors.py`
- `frontend/src/api/client.ts`
- `frontend/src/features/gantt/GanttPage.tsx`
- `frontend/src/features/gantt/scenarioPresentation.ts`
- `frontend/src/features/gantt/GanttPage.test.tsx`
- `frontend/src/features/gantt/scenarioPresentation.test.ts`
- `tests/integration/test_api.py`

Nuevos:

- `tests/integration/test_gantt_new_revision_simulation.py`
- `frontend/src/test/ganttRevisionSimulationFixture.ts`
- `frontend/tests/gantt-revision-simulation.spec.ts`
- `docs/47-simulation-gantt-read-model.md`

Los archivos de evidencia de test-results quedan ignorados. Sin staging, commit ni push.
