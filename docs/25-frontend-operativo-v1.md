# Frontend operativo V1

Fecha: 2026-09-21

## Stack y estructura

La interfaz es una SPA en `frontend/` construida con React 19, TypeScript, Vite,
React Router y TanStack Query. Usa `fetch` nativo, CSS Modules y variables CSS. No
incorpora Redux, Axios, framework visual, SSR, service worker ni modo offline. El
Gantt se incorporó posteriormente en Etapa 6.2 y se documenta por separado.

- `src/api`: cliente HTTP único y tipos generados;
- `src/features/daily-board`: tablero, orden y traducciones industriales;
- `src/features/operations`: detalle y actualización de tiempo restante;
- `src/features/replanning`: simulación, impacto, aceptación y rechazo;
- `src/components`: estados remotos comunes;
- `src/test`: MSW y fixtures;
- `tests`: flujos Playwright de UI.

TanStack Query es la única fuente de server state. No se duplican respuestas en
loaders ni stores locales. Las mutaciones no son optimistas: al terminar invalidan y
recargan tablero, operación y escenario desde el servidor.

## Desarrollo y contrato

```powershell
cd frontend
npm ci
npm run api:generate
npm run dev
```

Vite publica `/api` mediante proxy a `http://127.0.0.1:8000`; no se abre CORS para
desarrollo. `scripts/export_openapi.py` obtiene el OpenAPI directamente de la app
FastAPI y `openapi-typescript` genera `src/api/schema.d.ts`. El archivo generado no se
edita manualmente.

Los headers `X-Dev-User-Id`, `X-Dev-Organization-Id` y `X-Dev-Plant-Id` están
encapsulados en `src/api/client.ts`. Los valores pueden configurarse localmente con
variables `VITE_DEV_*` o localStorage. Son identificadores públicos de desarrollo,
no credenciales ni autenticación. Todo `VITE_*` es visible en el navegador. El
provider DEV debe permanecer deshabilitado fuera de desarrollo/testing; Supabase
Auth continúa pendiente.

## Flujo operativo

El tablero muestra el plan vigente del día, resumen, fecha y filtros por proyecto,
centro, persona y estado. Ordena EN CURSO, DEMORADO, BLOQUEADO, LISTO, PENDIENTE y
FINALIZADO; dentro de cada grupo usa hora, prioridad e ID estable.

El detalle presenta planificación, recursos y realidad sin revisiones técnicas. Para
operaciones en curso permite proponer minutos manualmente o sumar 30/60/120 minutos
antes de guardar. La estimación original no cambia.

Cuando la realidad exige conciliación, el operador inicia explícitamente el replan.
La UI muestra cantidades e impactos, traduce blockers y advierte si corresponde
comunicación. Confirmar promociona mediante `/accept`; cancelar usa `/reject` y
explica que la estimación real se conserva. Un 409 stale no se reintenta: ofrece
volver a simular. Ningún flujo comunica automáticamente con clientes.

## API utilizada

- `GET /planning/current/day`;
- `GET /operations/{id}`;
- `POST /operations/{id}/remaining-estimate`;
- `POST /operations/{id}/replan`;
- `GET /scenarios/{id}`;
- `POST /scenarios/{id}/accept`;
- `POST /scenarios/{id}/reject`.

Las cuatro rutas de tablero, detalle, replan y reject se agregaron como adaptadores
finos. Las consultas residen en persistencia y los comandos reutilizan servicios de
aplicación y UOW existentes.

## Estados, accesibilidad y responsive

Tablero y detalle poseen loading, error, retry y empty state. Las tablas tienen
caption/headers; formularios, labels; resultados importantes, `aria-live`; y el
foco es visible. Los estados incluyen texto, no dependen sólo del color. La tabla se
convierte en filas etiquetadas bajo 700 px; resumen y filtros se adaptan a 1024 px.
La validación E2E recorre 1440×900, 1366×768, tablet horizontal 1024×768 y
smartphone 390×844.

## Pruebas y build

```powershell
npm run test
npm run test:e2e
npm run build
```

Vitest, Testing Library, user-event y MSW cubren carga, empty/error/retry, orden,
filtros, detalle, atajos, guardado, conciliación, impacto, comunicación, accept,
reject, stale, doble click y traducciones. Playwright usa networking determinista y
se clasifica como E2E de UI; cubre tablero→detalle, conservación de realidad tras
reject, promoción con refetch del plan vigente y recuperación ante stale. La
integración real permanece en pytest/PostgreSQL.

## Limitaciones

- No existe autenticación productiva ni autorización UI por capabilities.
- Playwright no sustituye las pruebas PostgreSQL.
- No hay polling en tiempo real, drag-and-drop, PWA u offline.
- Etapa 6.2 formalizó el rango y el eje temporal del Gantt en zona IANA de planta;
  el contrato diario continúa recibiendo una fecha civil.
