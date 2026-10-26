# Piloto 1 — alta de cliente dentro de Nuevo proyecto

Base: `master`, `79331f00992e0a936a79c90c8e54d3a691470c59`.
Sin migraciones, commit ni push.

## Modelo y API

`core.customers` pertenece a una organización. Admite `display_name` obligatorio,
`phone` y `email` opcionales, y estado activo por defecto. No existe unicidad por
nombre: las restricciones únicas son ID, organización/ID y organización/código;
el código admite NULL. No se agregaron reglas de unicidad ni columnas.

La auditoría no encontró un comando o endpoint existente para crear clientes.
Se agregó `POST /customers`, integrado en `ProjectIntakeService` y su unidad de
trabajo transaccional, reutilizando contexto DEV, validación de actor/planta,
orden de locks, `Idempotency-Key`, detección de intención incompatible y auditoría.

Body mínimo: `{"display_name":"Nico del Castillo"}`. Teléfono y email vacíos
se normalizan a NULL. No se inventan código, CUIT, dirección ni contactos.
La respuesta HTTP 201 contiene `customer` e `idempotent_replay`.
El mismo key/contexto/payload devuelve el mismo cliente; cambiar la intención con
esa clave produce 409. El alta no modifica planning state ni CURRENT.

## UI y conservación del borrador

En `/projects/new`, junto al selector Cliente, aparece **+ NUEVO CLIENTE**.
Abre un diálogo modal con nombre/razón social obligatorio y teléfono/email
opcionales. El formulario de cliente es independiente del formulario de proyecto.

El éxito agrega el cliente al cache, refresca las opciones, lo selecciona y cierra
el diálogo. Conserva código, referencia, prioridad, fecha comprometida y notas.
Incluso si falla el refresco posterior de opciones, el borrador sigue montado y
mantiene la selección recién confirmada.

Un error mantiene abierto el diálogo y conserva los inputs. Una validación
rechazada permite corregirlos. Un fallo de resultado incierto conserva payload y
clave para **REINTENTAR CREACIÓN**, sin generar una intención distinta; durante
ese estado se bloquean modificaciones/cancelación para evitar duplicados por retry.
Cancelación normal y Escape cierran sin modificar los datos del proyecto.

Las coincidencias parciales de nombre, sin distinguir mayúsculas, ofrecen
**USAR CLIENTE EXISTENTE**. Es una ayuda de selección, no una regla de unicidad:
no fusiona clientes ni prohíbe crear homónimos con intenciones independientes.

## Verificación

Backend completo: **528 passed** (17 nuevos casos de clientes). Comprueba nombre
solo, contactos opcionales, validación, replay, conflicto por payload distinto,
concurrencia, aislamiento de contexto/tenant, opciones sin filtraciones y rollback.
Persisten los 2 warnings de dependencias conocidos.

Vitest completo: **164 passed**. Incluye selector vacío, apertura/cancelación,
campos opcionales, éxito, selección, conservación del borrador, error, retry,
selección de cliente existente y fallo de refresco posterior.

Playwright relevante: **40 passed**, en 1440, 1366, 1024 y 390 px, cubriendo los
flujos de proyectos y los nuevos casos de alta, error/retry y cliente existente.
Playwright completo: **202 passed, 14 skips preexistentes, 0 failed**.
Estas suites usan APIs simuladas; la persistencia real se probó además por el
siguiente smoke, sin simular la API.

### Navegador contra PostgreSQL descartable

Comando reproducible desde el repositorio:

```powershell
.\.venv\Scripts\python.exe scripts/test_postgres_disposable.py --customer-ui-smoke
```

Reutiliza el aislamiento del runner existente: base y rol aleatorios `besten_test_*`,
M0–M11 y limpieza al finalizar. El smoke rechaza cualquier URL que no corresponda
a ese esquema de base/rol local descartable. Utiliza puertos efímeros propios,
Vite, FastAPI real y Playwright con Edge; nunca apunta a la base del piloto.

El navegador completa **A685**, referencia, prioridad, fecha y notas. Crea
**Cliente E2E descartable** mediante el modal y verifica cierre, selección y
conservación de los cinco campos. Reenvía la misma petición con la misma clave:
el backend devuelve replay. SQL posterior confirma exactamente un cliente, con
teléfono/email NULL, una auditoría y ningún proyecto persistido. Resultado:
`REAL_CUSTOMER_UI_SMOKE passed`. Base/rol descartables eliminados.

OpenAPI se exportó desde FastAPI y los tipos se regeneraron mediante
`openapi-typescript`; no se editaron tipos generados manualmente. TypeScript y
Vite build aprobados; persiste el warning de bundle grande.

## Base del piloto

No se creó a Nico ni ningún otro cliente en `produccion_besten`. El usuario hará
el alta manual desde la UI. Clientes y proyectos permanecen en **0**. La
comparación SHA-256 de las 87 tablas confirmó que no cambiaron maestros, catálogo
de operaciones, planning state ni auditoría del piloto. Continúan 3 personas,
6 skills, 4 centros, 5 recursos y 6 tipos de operación.

El backend local se reinició con el endpoint actualizado. Health/ready responden
200 y su OpenAPI coincide con el archivo generado. La UI DEV mostró el nuevo
diálogo y permitió cancelarlo sin enviar ninguna petición de escritura al piloto.
Se verificaron los permisos INSERT necesarios del rol de aplicación.

`git diff --check` aprobado; sin secretos nuevos. Cambios locales sin staging,
commit ni push; sin migraciones nuevas. El estado previsto es código pendiente de
checkpoint, no working tree clean.

App de Compras y backup: no accedidos, inspeccionados ni modificados.

Conclusión: **PILOT_CUSTOMER_UI_READY**.
