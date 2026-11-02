# Gantt operativo V2

## Diagnóstico y alcance

El Gantt V1 usa vis-timeline. Se conservan la consulta existente, contexto DEV,
agrupaciones, calendario, segmentos de ejecución, intents move/resize,
idempotencia, comparación y aceptación explícita. La presentación V2 usa filas
React, CSS Grid y SVG; no añade dependencias ni modifica el scheduler.

## Brecha de lectura identificada antes del cambio

`GET /planning/current/gantt` no expone etapas congeladas, fecha comprometida,
habilidades ni segmentos de asignación planificados. El intervalo global no
permite representar interrupciones reales. Se amplía sólo este contrato con
campos aditivos opcionales: metadatos de la revisión congelada utilizada por
la solución, segmentos persistidos y nombre de planta. No se infieren pausas
recortando barras según un calendario genérico. Ninguna migración requerida.

La comparación V1 expone intervalos/deltas, pero no asignaciones completas de
la propuesta. Se informa esta limitación en la inspección de propuestas; no
se atribuyen personas/recursos actuales a una propuesta como si fueran nuevos.

## Arquitectura final

- `GanttPage`: conserva React Query, URL `scenario_id`, comandos de aceptación,
  rechazo, move/resize, Idempotency-Key y notifications. Toolbar única, zoom
  día/semana/quincena/mes, fecha local, HOY y ajuste al contenido cargado.
- `operationalModel`: jerarquía proyecto → etapa → operación, agrupaciones por
  asignación, relaciones explícitas, marcas locales y ventana de filas.
- `GanttTimeline`: nombres sticky de 280 px, encabezado temporal sticky, SVG
  para barras, segmentos, compromisos, ejecución, ocupación, AHORA y flechas.
  Filas de 68 px; todos los elementos temporales comparten la misma escala.
- `OperationalTimeline.module.css`: tokens semánticos y focus. Se mantiene la
  identidad Besten y no se agrega ninguna librería. La dependencia existente
  vis-timeline permanece en package.json para no ampliar el alcance; el nuevo
  componente no la importa en runtime.

## Jerarquía y agrupaciones

Proyecto es la vista inicial. Etapas y orden proceden de la revisión congelada
utilizada por la solución, no del catálogo actual ni del borrador siguiente.
Versiones antiguas sin esos metadatos muestran un fallback explícito.
Agrupar por centro, persona o recurso usa IDs y nombres devueltos por la API,
con operaciones bajo cada asignación; una operación compartida aparece en las
personas asignadas. La capacidad del centro se informa sin fabricar puestos
paralelos. Cada operación tiene su propia fila, por lo que trabajos simultáneos
siguen visibles. No se calcula utilización agregada ficticia.

Plegar proyecto/etapa conserva los IDs y excluye sus barras y flechas. El orden
visual no crea ni modifica ninguna precedencia. El caso de prueba tiene Corte y
Múltiple sin predecesoras, dos entradas a Armado y una salida a Instalación.

## Estados y calendario

Planificado: azul sólido; en curso: turquesa con borde reforzado; ejecutado:
petróleo oscuro; simulación: lavanda suave, contorno discontinuo; bloqueado:
ocre y borde discontinuo; demorado: borde carmín discontinuo; ocupación física:
ocre diferenciado; AHORA: línea carmín rotulada. Nombre y estado textual
permanecen en el panel fijo, redundantes al color. Criticidad no disponible se
indica explícitamente: no se inventa ruta crítica ni un cuello por duración.

Ventanas productivas claras sobre fondo gris fuera de turno. Fines de semana
con sombreado adicional. Las ventanas se obtienen del calendario real,
incluidas sus excepciones. No se hardcodean 08:00, 12:00, 12:45 ni 17:00.
El fondo es de planta: no afirma disponibilidad individual de cada persona o
recurso. Las barras utilizan los segmentos persistidos del scheduler, sin
intersectarlos artificialmente con este fondo. Así se respeta trabajo dividido,
continuidad y bloque único cuando corresponden. Contratos anteriores sin
segmentos conservan el intervalo global como fallback.

La fecha comprometida es date-only en zona de planta, representada al final del
día local. Las etiquetas temporales usan es-AR y timezone de planta. Mes no
excede el límite de lectura de 31 días. Zoom conserva el centro temporal como
referencia antes de alinear al período; no convierte date-only a UTC para
mostrarlo. AHORA se actualiza cada minuto.

## Inspección y dependencias

Click/tap/Enter/Espacio mantienen selección. Panel lateral con duración,
división, habilidades congeladas (códigos), personas asignadas, centro/capacidad,
recursos, segmentos, ejecución/restante y precedencias textuales. Escape/cerrar
restauran foco al control que abrió el panel. No es un modal bloqueante.

Dependencias predeterminadas: Seleccionada. Antes de seleccionar no hay flechas.
Ocultas/Todas están disponibles. Se resaltan la operación y sus vecinas directas;
las flechas sólo provienen de `predecessors`. Un bloqueo por capacidad se presenta
como motivo textual, separado del grafo lógico. La razón `why_not_earlier` de una operación programada se rotula restricción,
no bloqueo activo. Razones conocidas se traducen
con el presentador existente. Si no hay explicación detallada, se dice:
«El planificador no expone actualmente el motivo detallado».

## CURRENT y simulación

Se conserva el primer escenario sin CURRENT. La pantalla distingue plan vigente,
simulación no aceptada y simulación obsoleta/incompleta. El resumen ofrece métricas
expuestas: operaciones/proyectos afectados, alertas de entrega, fuera de
horizonte, restricciones informadas y fecha final de simulación inicial. No presenta
alertas como un cálculo nuevo de conflictos.

VER CAMBIOS filtra diferencias informadas; VER PLAN COMPLETO recupera operaciones.
En escenario inicial todas las operaciones son nuevas respecto de CURRENT vacío.
VOLVER SIN ACEPTAR sólo cambia la vista. CANCELAR PROPUESTA mantiene el comando
existente de rechazo. CONFIRMAR NUEVO PLAN es la aceptación explícita existente,
con pending/disabled y feedback; incompletas no se aceptan y obsoletas no ofrecen
confirmación. Ninguna selección, agrupación, zoom o inspección envía comandos.

Modo ajuste sigue generando una intención move/resize con inicio/fin/delta
visibles durante el gesto. No mueve CURRENT. El usuario debe pulsar SIMULAR
CAMBIO; se conserva la alternativa por formulario y el retry con la misma clave.
Arrastrar entre recursos propone un recurso mediante el comando existente; el
backend decide factibilidad. Operaciones ejecutadas/en curso permanecen protegidas.
Al comparar una propuesta, se deshabilita el ajuste para evitar mezclar bases.

## Accesibilidad y responsive

Botones reales en jerarquía, aria-expanded, SVG seleccionable por teclado,
aria-label descriptivo, tooltip en focus con aria-describedby y versión textual
persistente de dependencias. Focus visible y mensajes aria-live. Los colores se
acompañan por texto, contorno y tramas de borde. No se declara certificación WCAG.

Desktop/laptop/tablet: panel fijo y scroll dentro del cronograma; nombres no se
pierden al desplazar fechas. En tablet los controles envuelven líneas sin ampliar
el viewport. Móvil ≤700 px: se oculta el lienzo desktop y aparecen tarjetas con
estado, fecha/hora, personas/recursos y predecesoras, con acceso al mismo panel.
No requiere scroll horizontal. El formulario sustituye drag en móvil. El cambio
de tamaño actualiza la disponibilidad de gestos.

## Performance

Ventana de filas a partir de 120 filas, con overscan de cuatro filas por lado.
No se dibujan flechas cuyo origen/destino no estén montados. Layout y relaciones
memoizados; hover no reconstruye jerarquía. El fixture de 50 proyectos/250
operaciones sólo vive en mocks; no hay carga masiva a la base real. Las tarjetas
móviles conservan todas las operaciones del rango; paginación móvil es futura.

## Limitaciones y futuras extensiones

- La comparación replan ofrece intervalos/deltas, no segmentos ni nuevas
  asignaciones de la propuesta. Se advierte en el panel que las personas/recursos
  son los del plan actual. Su contorno representa extensión temporal, no trabajo
  continuo confirmado. Ampliar este contrato sería una iteración independiente.
- No hay critical path, holguras ni cálculo de cuello de botella; no se infieren.
- AJUSTAR AL PLAN usa el contenido recibido, hasta 31 días. CURRENT se consulta
  por rango y no permite descubrir de una vez todo un horizonte mayor.
- Las sucesoras textuales se limitan a operaciones cargadas. Las flechas respetan
  plegado y virtualización; el panel mantiene las predecesoras textuales.
- No se calcula una nueva agenda, elegibilidad, solapamientos o disponibilidad.
  El scheduler y los comandos existentes siguen siendo fuente de verdad.
- Autenticación productiva sigue diferida. No se modifican migraciones ni datos.
- Persisten el warning de bundle de Vite y dos warnings de dependencias backend.

## Datos reales y Git

Trabajo exclusivo en Producción Besten, branch master, base
`df97bebe61a772ec79717b4b52c07cdd6f24e815`. No se accede a App de Compras ni al
backup. Baseline SHA-256 por tabla capturado en transacción read-only antes del
trabajo; se compara nuevamente al cierre. Todas las pruebas mutantes usan
fixtures/mocks o PostgreSQL descartable. La consulta de comprobación real usa
GET sobre la simulación ya existente; no genera otra ni acepta planes.

Sin commit ni push. Archivos de capturas/test-results/dist están ignorados y no
se incorporan a Git. OpenAPI y tipos se regeneran por la ampliación aditiva.

## Validación final

| Verificación | Resultado |
| --- | --- |
| Backend relevante: operational API, initial review, assisted Gantt, instalaciones | 63 aprobadas, DB descartable |
| Vitest completo | 204 aprobadas |
| Playwright completo | 250 aprobadas, 14 skips preexistentes, 0 fallas |
| Gantt V2 E2E | 12/12, incluido en el total completo |
| TypeScript / Vite | Aprobados |
| OpenAPI / schema.d.ts | Regenerados y sincronizados |
| git diff --check | Aprobado |
| Secret scan | 248 archivos, 0 candidatos nuevos; 2 placeholders preexistentes |
| Integridad real | SHA-256 y conteos de las 87 tablas idénticos antes/después |

Tras el cambio final de rótulo de restricción/bloqueo se repitieron TypeScript,
build y las 33 pruebas unitarias del Gantt; el E2E V2 pasó nuevamente 12/12.
No se suman subconjuntos ni repeticiones al total.

Benchmark PostgreSQL descartable: 10 proyectos/50 operaciones = 106,96 ms,
37,7 KiB; 50/250 = 341,38 ms, 188,1 KiB. Consulta CURRENT mantiene seis
sentencias SQL, sin N+1 de viajes a la base. Render E2E final 50/250:
833–1053 ms; overlay: 460–566 ms en desktop/tablet, bajo el umbral de 5 s.
La primera pasada también midió 556–589 ms y 358–447 ms respectivamente;
son mediciones de fixtures y entorno local, no una garantía de producción.

Capturas generadas e inspeccionadas en 1440, 1366, 1280×800, 1024 y 390 px.
`frontend/test-results/gantt-v2-*/gantt-v2-overview.png`,
`gantt-v2-comparison.png` y `gantt-v2-laptop-1280.png`. Se verificó ausencia de
scroll horizontal global y la alternativa móvil. Los archivos se regeneran
con Playwright y están ignorados en Git.

Comprobación real adicional por GET: Vera Mujica, America/Argentina/Cordoba,
cuatro etapas 2/4/6/9, segmentos planificados 1/1/2/2 y skills congeladas.
A685 activo, row_version 37; REV 1–4 preservadas, REV 4
`cab80c24-46b3-48a5-8bd1-ef3ec102eab8`; release intacto; ocho escenarios;
CURRENT NULL. No se creó ningún escenario, plan ni revisión. PostgreSQL 18.6
operativo. Backend DEV reiniciado sólo para cargar el contrato de lectura;
frontend sigue en 5173 y backend en 8000.

## Archivos de esta entrega

Modificados (9):

- `frontend/openapi.json`
- `frontend/src/api/schema.d.ts`
- `frontend/src/features/gantt/GanttPage.module.css`
- `frontend/src/features/gantt/GanttPage.tsx`
- `frontend/src/features/gantt/GanttTimeline.tsx`
- `frontend/src/features/gantt/time.ts`
- `src/production_besten/api/schemas.py`
- `src/production_besten/persistence/api_queries.py`
- `tests/integration/test_initial_simulation_review.py`

Nuevos (6):

- `docs/41-gantt-operativo-v2.md`
- `frontend/src/features/gantt/OperationalTimeline.module.css`
- `frontend/src/features/gantt/OperationalTimeline.test.tsx`
- `frontend/src/features/gantt/operationalModel.ts`
- `frontend/src/test/ganttV2Fixture.ts`
- `frontend/tests/gantt-v2.spec.ts`

Nada staged. Sin commit ni push. M0–M13 intactas, cero migraciones nuevas.
App de Compras y backup no accedidos ni modificados.


## Ajuste posterior: contraste y colorimetría

Alcance exclusivo de presentación, selección y accesibilidad visual. No cambia
backend, scheduler, API, fechas, precedencias, agrupaciones, intents ni ACCEPT.
El V2 anterior sigue pendiente de commit; este ajuste se incorpora sobre ese
working tree sin descartar ni reimplementar su avance.

### Diagnóstico y corrección

Los colores anteriores eran apagados; además, el selector CSS de estado tenía
mayor especificidad que el de simulación. Una simulación bloqueada podía tomar
el relleno ámbar del estado y perder su identidad de propuesta. Ahora los fills
de estado sólo se aplican a barras sólidas; simulación mantiene violeta y trama,
mientras el estado sigue explícito en texto/icono y panel.

`ganttTokens.css` centraliza paleta semántica para timeline, leyenda y tarjetas.
No hay colores hexadecimales en la lógica TSX del timeline. Tokens principales:

| Token --gantt-… | Valor | Uso |
| --- | --- | --- |
| working-bg | #FFFFFF | Productivo |
| offshift-bg | #EEF2F6 | Fuera de turno / pausa |
| weekend-bg | #DDE3EA | Fin de semana |
| grid | #CBD5E1 | Grilla subordinada |
| executed | #334155 | Ejecutado |
| in-progress | #0F766E | En curso |
| planned | #2563EB | Futuro planificado |
| simulation | #7C3AED | Borde violeta de 3 px |
| simulation-bg | #EDE9FE | Fondo de simulación |
| simulation-pattern | #C4B5FD | Rayado diagonal SVG |
| simulation-text | #3B0764 | Texto sobre trama clara |
| blocked | #B45309 | Ámbar sólido |
| blocked-text | #78350F | Título móvil, sobre fondo claro |
| delayed | #B91C1C | Retraso + alerta |
| critical | #9F1239 | Reservado; no inventa criticidad |
| now | #111827 | AHORA |
| selected-border | #111827 | Contorno persistente de 3 px |
| dependency | #334155 | Relaciones seleccionadas, 2,5 px |
| dependency-muted | #8492A6 | Otras relaciones, 1,25 px discontinuas |

Otros tokens centralizan texto, foco, fondos de jerarquía, ocupación y halo de
flechas. En Todas, las relaciones ajenas a la selección se atenúan; sin selección
todas se muestran atenuadas. Seleccionada mantiene el comportamiento anterior:
sólo vecinas directas y ninguna flecha antes de seleccionar.

### Formas, selección y leyenda

- Plan sólido; simulación con borde discontinuo de 3 px y diagonal SVG. La trama
  es la misma semántica reproducida por la muestra de la leyenda.
- Selección: contorno negro independiente del fill original en cada segmento,
  banda lateral de 5 px, borde de fila y elevación. aria-pressed en barras y
  data-selected en fila/tarjeta, sin depender de hover.
- Bloqueado/retrasado: alerta visible y estado textual; ! adicional sobre barras
  cuando el ancho permite texto. Conserva etiquetas accesibles completas.
- Leyenda: ocho muestras de 24×16 px, labels explícitos e iconos de alerta.
  Ejecutado, en curso, futuro, ocupación, simulación, bloqueado, retrasado y AHORA.
- Las flechas tienen cabeza rellena y halo blanco para separarse de calendario y
  grilla. No se inventan relaciones.
- En móvil, propuesta usa borde violeta discontinuo y fondo claro; selección
  mantiene contorno oscuro. Bloqueo y demora conservan texto/iconos.

### Contraste medido

Se calcula luminancia relativa sRGB y razón (L1+0,05)/(L2+0,05), tanto sobre los
tokens fuente en Vitest como sobre CSS computado del build en Playwright.

| Texto blanco sobre estado | Razón |
| --- | --- |
| Ejecutado | 10,35:1 |
| En curso | 5,47:1 |
| Planificado | 5,17:1 |
| Bloqueado | 5,02:1 |
| Retrasado | 6,47:1 |

Texto oscuro de simulación: 12,63:1 sobre fondo y 8,12:1 sobre línea de trama.
Borde violeta contra fin de semana: 4,41:1. Tests exigen ≥4,5:1 para texto y
≥3:1 para borde/selección/dependencias frente a los tres fondos. El fondo de
calendario es decorativo; no se afirma que los grises entre sí alcancen 3:1.
Estas comprobaciones no constituyen una certificación WCAG completa.

### Capturas y pruebas

Se capturaron A proyecto + simulación, B Armado seleccionado, C dependencias
seleccionadas y D recursos, en 1440, 1280, 1024 y 390 px: 16 capturas. Todas usan
fixtures/mocks, con requests mutantes prohibidos. Los mock rangos reflejan el
rango solicitado para inspeccionar también las barras a escala diaria.

Además: estados sólidos juntos y comparación; emulación Chromium/Edge mediante
`Emulation.setEmulatedVisionDeficiency` para deuteranopia, protanopia y
achromatopsia (grises). Se restablece visión normal al finalizar. Se inspeccionan
las capturas: labels/iconos, sólido/trama y contorno siguen distinguibles cuando
los matices convergen.

Ubicación ignorada en Git: `frontend/test-results/gantt-contrast-*/`:
`A-project-simulation.png`, `B-Armado-selected.png`,
`C-selected-dependencies.png`, `D-resources.png`, `states-normal.png`,
`states-deuteranopia.png`, `states-protanopia.png`, `states-achromatopsia.png`.

Validación del ajuste:

- TypeScript y Vite build: aprobados; persiste warning de bundle preexistente.
- Vitest completo: 209 aprobadas; Gantt relevante: 38 aprobadas.
- Playwright relevante: 66 aprobadas, 14 skips preexistentes, cero fallas finales.
- Capturas de contraste finales: 8/8 pruebas; subconjunto del total relevante.
- No se repite backend: no hubo cambios backend en este ajuste.
- git diff --check: aprobado. Sin commit, push ni staging.

Archivos adicionales respecto de la entrega V2 anterior:
`frontend/src/features/gantt/ganttTokens.css`,
`frontend/src/features/gantt/contrast.test.tsx`,
`frontend/tests/gantt-contrast.spec.ts`; además se modifica el test existente
`GanttPage.test.tsx`. Se actualizan los estilos/componentes ya listados y este
informe. Estado acumulado esperado: 10 modificados y 9 nuevos.

La comprobación de cierre confirmó conteos y SHA-256 idénticos en las
87 tablas reales contra el baseline read-only de este ajuste.
Secret scan final: 251 archivos, cero candidatos nuevos y dos placeholders
preexistentes. No se envían
comandos contra la base real: A685, REV 4, release, simulaciones y CURRENT se
preservan. App de Compras y backup no se acceden ni modifican.
