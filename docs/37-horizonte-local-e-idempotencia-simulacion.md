# Piloto 1 — horizonte local e idempotencia de simulación

Fecha: 2026-10-27. Base Git: `master`,
`286fe01db3da92883294e4279ba5365c7aad8a45`. Se preserva todo el trabajo pendiente
de permisos de auditoría y revisión del escenario inicial. Sin commit ni push.

## Causa exacta del desplazamiento

El date input contenía `2026-10-26`. `ProductionReadinessCard.send` construía
`horizon_start: start + 'T00:00:00Z'`. Ese sufijo convertía una fecha local elegida
por el usuario en un instante UTC antes de enviar la petición.

Pydantic recibía un datetime consciente de zona; el servicio y el escenario
conservaban ese instante, y PostgreSQL lo guardaba en el `tstzrange` del horizonte.
Al cargar capacidad, `ZoneInfo(plant.timezone)` lo convertía a
**25/10/2026 21:00 America/Argentina/Cordoba**. La comparación de vigencias
date-based se hacía contra ese día local anterior. No fue un cambio de zona
introducido por PostgreSQL ni una falta real de skills en los maestros.

## Contrato corregido

La UI obtiene la timezone real desde el contrato de preparación productiva.
Las fechas iniciales se calculan con esa zona, no con `toISOString().slice(0,10)`.
Los inputs se identifican como fechas locales de planta y envían date-only:

```json
{"horizon_start":"2026-10-26","horizon_end":"2026-11-03"}
```

FastAPI acepta fecha local o, por compatibilidad, timestamp explícito con timezone.
Un datetime sin zona se rechaza. La normalización usa `ZoneInfo` en backend:

- Date-only: comienzo del día en la zona real de planta, convertido a UTC.
- Timestamp consciente: conserva el instante indicado; no se reinterpreta.
- Inicio efectivo: `max(inicio seleccionado, reloj actual UTC)`.
- Fin: límite exclusivo; si es date-only, comienzo de ese día local. Debe ser
  posterior al inicio efectivo, o se devuelve un error de dominio comprensible.

Así, 26/10 local corresponde a **26/10 03:00Z**, no a 25/10 21:00 local. El motor
encuentra la próxima ventana del calendario; no se fija artificialmente 08:00.
Si la fecha es futura, empieza en su primera ventana. Si es hoy a las 15:00,
no programa antes de las 15:00; si hay almuerzo o fin de jornada, espera la
próxima ventana. Una fecha pasada también se limita al instante actual.

El reloj se inyecta por `create_app(clock=...)`, el contenedor y la unidad de
trabajo de liberación. En producción usa `datetime.now(timezone.utc)`; las pruebas
históricas declaran explícitamente su reloj fijo. No se congeló el reloj real.

## Vigencias

No se modificaron skills, fechas de vigencia ni calendarios reales. La carga de
employee_skills y membresías de recursos ya convierte el principio/fin del
horizonte a fechas de la planta; conserva el contrato conservador de cobertura
durante todo el horizonte. Las ventanas semanales se evalúan por fecha local en
la timezone de su calendario, con vigencias `[desde,hasta)`. Centros y recursos
usan su estado/calendario; asignaciones y segmentos usan instantes conscientes.

Corregir el instante de entrada hace que las habilidades vigentes desde 26/10
estén disponibles durante el 26/10 local. No se amplió su vigencia como workaround.

## Dos escenarios del piloto

La auditoría real muestra dos claves diferentes con el **mismo release_hash**:

| Hora local del 26/10 | Idempotency-Key | Scenario |
| --- | --- | --- |
| 13:31:41.849185 | cb641312-68bd-45d2-8a07-ace6d0532a2d | f0a46d2f-1eb9-45d1-80d6-5eab94805784 |
| 13:31:46.112380 | 7c8fba2a-c745-482d-95fa-a9f42bcc9422 | 16b169b0-8512-4b5d-a7ee-7420d60733f8 |

Son dos envíos de la misma intención con claves distintas, separados por 4,263195
segundos. Los registros no permiten afirmar si el gesto físico fue otro clic,
navegación o reintento manual. El frontend ya deshabilitaba mientras estaba
pendiente y usaba `retry:false`; el retry técnico conservaba el ref de intención.
Pero tras éxito liberaba ese ref y permitía volver a generar con una clave nueva
sin distinguir una repetición accidental de una nueva simulación voluntaria.

Ahora GENERAR queda deshabilitado durante la petición, durante un resultado
incierto y después del éxito. El usuario debe pulsar **PREPARAR OTRA SIMULACIÓN**
para rearmar el formulario; esa acción no hace requests. El siguiente envío tiene
una clave nueva. No se introdujo unicidad global por payload: dos simulaciones
voluntarias siguen siendo válidas incluso con el mismo horizonte.

El retry técnico conserva payload/key y bloquea cambios del horizonte mientras
el resultado sea incierto. La búsqueda de replay del backend ocurre **antes** de
normalizar con el reloj: avanzar el tiempo no altera la intención ni crea otra
solución. Una clave reutilizada con payload distinto sigue produciendo 409.

## Pruebas

Backend completo: **546 passed**, con los dos warnings de dependencias conocidos.
Se agregaron 8 casos unitarios de fechas/instantes/reloj y 5 casos PostgreSQL de
horizonte local, además de conservar todas las regresiones previas.

La base descartable reproduce A685/Alacenas con timezone Córdoba, jornadas
08:00–12:00 / 12:45–17:00, Mariano/Emiliano/Gonzalo y skill de Corte vigente desde
26/10. Los snapshots contienen skills en las tres personas, Corte queda
planificable y se comprueban estos comienzos:

| Reloj fijo | Primera capacidad esperada |
| --- | --- |
| 25/10, fecha futura seleccionada 26/10 | 26/10 08:00 local |
| 26/10 15:00 local | 26/10 15:00 local |
| 26/10 12:15 local | 26/10 12:45 local |
| 26/10 18:00 local | 27/10 08:00 local |

También se verifica replay con reloj avanzado, rechazo de una intención distinta
con igual clave, y dos generaciones voluntarias con claves distintas. El escenario
inicial sigue visible sin CURRENT, y las regresiones de aceptación explícita siguen
verdes. Ninguna generación de test utiliza `produccion_besten`.

Vitest completo: **171 passed**. Incluye fecha local al cruzar medianoche UTC,
payload date-only, doble clic, bloqueo posterior al éxito, retry y rearme explícito.
TypeScript/Vite build y regeneración de OpenAPI/tipos aprobados. Persiste el warning
de bundle grande. No se editaron manualmente tipos generados.
Playwright completo: **218 passed, 14 skips preexistentes, 0 failed**, incluidas
las nuevas pruebas de fechas y reintentos en las cuatro resoluciones. Los casos
de escenario inicial sin CURRENT y aceptación explícita siguen aprobados.

## Datos reales y entrega

No se generó ni aceptó una simulación real. A685 sigue activo/liberado con REV 2
y CURRENT inexistente. Los dos escenarios incompletos y sus ScheduleSolution se
conservan como evidencia; tampoco se modificaron requisitos de centro/skill de
la definición productiva. El próximo envío real corresponde al usuario desde UI.

No se accedió, inspeccionó ni modificó App de Compras ni el backup.

La UI real se comprobó mediante lecturas, bloqueando cualquier request que no
fuera GET: timezone Córdoba, inicio local 27/10/2026 y fin exclusivo 26/11/2026.
No se pulsó GENERAR SIMULACIÓN ni ACCEPT. Backend/frontend quedaron operativos.
La comparación SHA-256 de las filas completas de las 87 tablas confirma que la
base real no cambió. `git diff --check` aprobado y sin secretos nuevos; no hay
migraciones nuevas ni archivos staged.

Conclusión: **PILOT_SCHEDULING_TIME_FIXED**.
