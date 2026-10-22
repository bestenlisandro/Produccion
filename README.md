# Producción Besten

Sistema web de planificación y programación de producción de muebles de melamina a medida.

El producto se diseña como un APS de capacidad finita: considera simultáneamente operaciones, precedencias, materiales, planos, personas, habilidades, máquinas, bancos, calendarios, instalaciones y restricciones del cliente.

## Principios no negociables

- Los recursos, habilidades, operaciones, rutas y calendarios son datos configurables.
- El planificador debe producir programas factibles, explicables y reproducibles.
- Una simulación nunca modifica el programa vigente.
- Toda reprogramación sigue el flujo: evento, impacto, escenario, comparación, confirmación y publicación.
- El portal del cliente usa una proyección pública separada de los datos internos.
- La futura integración con la aplicación de Compras se realizará mediante contratos versionados, nunca compartiendo tablas.

## Documentación funcional inicial

- [Decisiones funcionales V1](docs/00-decisiones-funcionales-v1.md)
- [Límites de módulos e integración con Compras](docs/01-modulos-e-integracion-compras.md)
- [Casos de aceptación del planificador](docs/02-casos-aceptacion-planificador.md)
- [Modelo lógico de datos V1](docs/03-modelo-logico-v1.md)
- [Casos difíciles del modelo](docs/04-casos-dificiles-modelo.md)
- [Auditoría formal del modelo lógico V1](docs/05-auditoria-modelo-logico-v1.md)
- [Cierre definitivo del modelo lógico V1](docs/06-cierre-modelo-logico-v1.md)
- [Ajuste de estimación restante durante ejecución](docs/07-ajuste-estimacion-restante-v1.md)
- [Esquema físico PostgreSQL V1](docs/07-esquema-fisico-postgresql-v1.md)
- [Diccionario de datos V1](docs/08-diccionario-datos-v1.md)
- [Validación UX de reprogramación V1](docs/09-validacion-ux-reprogramacion-v1.md)
- [Auditoría de simplificación del esquema V1](docs/10-auditoria-simplificacion-esquema-v1.md)
- [Cierre del esquema físico PostgreSQL V1](docs/11-cierre-esquema-fisico-v1.md)
- [Plan de migraciones PostgreSQL V1](docs/12-plan-migraciones-postgresql-v1.md)
- [Seguridad y estrategia RLS V1](docs/13-seguridad-rls-v1.md)
- [Validación de migraciones PostgreSQL V1](docs/14-validacion-migraciones-v1.md)
- [Entorno de validación PostgreSQL V1](docs/15-entorno-validacion-postgresql-v1.md)
- [Cierre de migraciones PostgreSQL V1](docs/16-cierre-migraciones-postgresql-v1.md)
- [Arquitectura backend V1](docs/17-arquitectura-backend-v1.md)
- [Validación del primer incremento backend V1](docs/18-validacion-backend-base-v1.md)
- [Plan RLS V1](docs/19-plan-rls-v1.md)
- [Contrato de API interna V1](docs/20-contrato-api-interna-v1.md)
- [Motor de planificación factible V1](docs/21-motor-planificacion-v1.md)
- [Capacidad acumulativa V1](docs/22-capacidad-acumulativa-v1.md)
- [Reprogramación ante desvíos V1](docs/23-reprogramacion-desvios-v1.md)
- [Promoción atómica del programa V1](docs/24-promocion-programa-v1.md)
- [Frontend operativo y tablero diario V1](docs/25-frontend-operativo-v1.md)
- [Gantt operativo, timezone y comparación V1](docs/26-gantt-operativo-v1.md)
- [Gantt asistido: mover y redimensionar como hipótesis](docs/27-gantt-ajustes-asistidos-v1.md)

## Entorno backend reproducible

La configuración no contiene credenciales. Copiar `.env.example` sólo como referencia local y proporcionar `DATABASE_URL` o `TEST_DATABASE_URL` mediante variables de entorno.

En esta PC, donde pip necesita integrar el almacén de certificados de Windows, el procedimiento validado es:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install truststore==0.10.4
.\.venv\Scripts\python.exe -m pip install --use-feature=truststore --no-build-isolation -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --use-feature=truststore --no-build-isolation -e .
```

No se usa `--trusted-host` ni se desactiva TLS.

Para iniciar el backend de desarrollo:

```powershell
.\.venv\Scripts\python.exe -m uvicorn production_besten.api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

## Estado

Etapa 3.1 cerrada: M0–M10 fueron validadas y reproducidas sobre PostgreSQL 18.6 real.

Etapa 5.1 cerrada: existe un scheduler greedy hacia adelante de capacidad finita,
determinista y explicable, validado sobre PostgreSQL real en el checkpoint
`BASIC_FINITE_CAPACITY_SCHEDULER_VALIDATED`.

Etapa 5.2 validada en `v1-greedy-2`: agrega capacidad acumulativa por eventos,
demanda por fase, convivencia con personas/skills y recursos exclusivos, usos reales
y blockers explicables. Sobre PostgreSQL 18.6 se recreó una base descartable, se
aplicaron M0–M10 y pasaron 172/172 pruebas en 12,40 s. Incluye benchmarks PostgreSQL
de 112,36 ms para 3 proyectos/12 operaciones y 898,40 ms para 20 proyectos/100
operaciones. No existen todavía frontend, portal, optimización global ni promoción
automática de escenarios.

Etapa 5.3 implementada como `v1-replan-1`: `REPLAN_FROM_OPERATION`,
`REPLAN_PROJECT` y `REJECT_REPLAN` producen escenarios incrementales aislados,
comparables e idempotentes desde realidad/estimación restante. No existe todavía
promoción automática y el plan publicado permanece inmutable.

Etapa 5.4 implementa `ACCEPT_REPLAN`: valida bases y locks, conserva la versión
anterior, publica una nueva `PlanVersion`, confirma el escenario y registra auditoría
y outbox en una sola transacción. No modifica ejecución ni fechas comunicadas.

Etapa 6.1 incorpora la SPA operativa React/TypeScript en `frontend/`: tablero diario,
detalle de operación, actualización de estimación restante y simulación con
aceptación/rechazo. Los tipos HTTP se generan desde el OpenAPI real de FastAPI.

Etapa 6.2 agrega `/planning/gantt`: cronograma de sólo lectura por centro, recurso,
persona o proyecto; calendario en zona IANA de planta; realidad ejecutada, plan
vigente, ocupaciones físicas y comparación semántica con simulaciones. No agrega
migraciones ni permite drag-and-drop.

Etapa 6.3 agrega un modo explícito de ajuste asistido. Mover o redimensionar una
actividad futura genera una hipótesis y un escenario: el plan vigente nunca cambia
por arrastre ni antes de una aceptación explícita. El motor `v1-greedy-3` prioriza
la intención manual, conserva todas las restricciones y explica cualquier diferencia
entre lo solicitado y lo propuesto.

Etapa 7.1 incorpora Configuración (`/settings`) para maestros operativos.
Validada con PostgreSQL 18: capacidad nominal de centros en scheduler, vigencias
históricas, excepciones, idempotencia contextual y reconciliation persistente sin
reescribir CURRENT. Autenticación productiva diferida. Resultados y límites en
[administración de maestros](docs/28-administracion-maestros-v1.md).

Etapa 7.2 agrega Proyectos / pedidos (`/projects`): alta administrativa reutilizando
Project, listado, detalle, edición, prioridad, compromisos e hitos realizados de
medición/replanteo. La definición industrial permanece separada para 7.3; los cambios
relevantes generan reconciliation sin reescribir CURRENT. No agrega migraciones.
Alcance acordado y resultados en [proyectos y pedidos](docs/29-proyectos-pedidos-v1.md).

```powershell
cd frontend
npm ci
npm run api:generate
npm run dev
npm run test
npm run build
```
