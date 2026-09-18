# Contrato de API interna V1

Fecha: 2026-09-07.

## 1. Alcance

Interfaz HTTP mínima para proyectos, definición productiva, ejecución real y ajuste
de tiempo restante. Es una capa de transporte sobre servicios existentes. No incluye
scheduler, Gantt, portal público, frontend, Compras ni autenticación productiva.

## 2. Contexto DEV ONLY

En desarrollo/testing cada endpoint protegido requiere:

```http
X-Dev-User-Id: <uuid>
X-Dev-Organization-Id: <uuid>
X-Dev-Plant-Id: <uuid>  # requerido al crear proyecto; opcional en otras lecturas
```

Estos headers se confían sin criptografía y no son autenticación. `organization_id`,
`user_id` y `plant_id` no forman parte de los bodies. En modo productivo el provider
DEV debe estar deshabilitado; será sustituido por un
`SupabaseRequestContextProvider` que validará JWT, memberships y capabilities. RLS
será la barrera adicional en PostgreSQL.

## 3. Idempotencia

Los POST que invocan comandos con `command_id` requieren:

```http
Idempotency-Key: <uuid>
```

Aplica a lotes, rutas, operaciones, fases, revisiones, start, segmentos y finish. Un
retry compatible devuelve el resultado existente, normalmente con HTTP 200 y
`idempotent_replay=true` cuando la respuesta lo expone. Reutilizar la clave con otro
target o payload devuelve 409. `POST /projects` no la usa porque `CREATE_PROJECT` no
posee `command_id`. La estimación restante usa la revisión optimista vigente derivada
por servidor.

## 4. Endpoints

| Método | Ruta | Resultado |
|---|---|---|
| GET | `/health` | Proceso vivo; no consulta DB |
| GET | `/ready` | Conectividad PostgreSQL |
| POST | `/projects` | Crea proyecto en la planta del contexto |
| GET | `/projects/{project_id}` | Obtiene proyecto tenant-safe |
| POST | `/projects/{project_id}/batches` | Crea lote productivo del proyecto |
| GET | `/projects/{project_id}/batches` | Lista lotes por orden |
| POST | `/batches/{batch_id}/route` | Asigna versión publicada de ruta |
| POST | `/batches/{batch_id}/operations` | Crea demanda de operación |
| POST | `/operations/{operation_id}/phases` | Crea fase, requisitos y gates |
| POST | `/projects/{project_id}/product-definition-revisions` | Congela la definición completa de la planta del proyecto |
| POST | `/operations/{operation_id}/start` | Inicia ejecución planificada o no planificada |
| POST | `/executions/{execution_id}/segments` | Registra segmento y usos reales |
| POST | `/operations/{operation_id}/finish` | Finaliza fase/operación |
| POST | `/operations/{operation_id}/remaining-estimate` | Actualiza estimación restante vigente |

Congelar desde la ruta de un proyecto identifica su planta, pero la revisión
resultante captura la definición productiva vigente completa de esa planta. La
respuesta contiene ID, número, hash, fecha y flags de reutilización; no devuelve el
snapshot canónico.

## 5. Estimación restante simplificada

Ejemplo con un único requisito laboral obligatorio en la fase actual:

```json
{
  "cutoff_at": "2026-09-07T14:00:00Z",
  "reason": "requiere una hora adicional",
  "remaining": [
    {"dimension": "LABOR_WORK", "minutes": 300}
  ]
}
```

La API deriva ejecución, fase, skill, dotación y revisión esperada. Si existen varios
requisitos, el request debe desambiguar `phase_id`, `skill_id`, `min_people` y
`max_people`. Para uso físico puede requerirse `physical_requirement_id`; para
ocupación de un recurso real se exige `physical_resource_id`. El cliente nunca envía
trabajo ejecutado, total actualizado ni `PlanningStateRevision`.

## 6. Errores

Los errores de dominio usan:

```json
{"error": {"code": "GATE_BLOCKED", "message": "..."}}
```

- 400: request estructuralmente válido pero semánticamente inválido;
- 404: recurso inexistente o inaccesible para el tenant, con el mismo cuerpo genérico;
- 409: estado, concurrencia, gate, disponibilidad o idempotencia;
- 422: validación de path/header/body por FastAPI/Pydantic;
- 500: error inesperado genérico, sin SQL ni stack;
- 503: provider productivo de identidad no configurado.

## 7. OpenAPI y seguridad futura

`/openapi.json` es generado por FastAPI con títulos, schemas y códigos declarados.
La transición futura reemplaza únicamente el provider de contexto y agrega políticas
RLS/privilegios mínimos; los DTO, comandos y servicios no deben recibir identidad del
body ni cambiar sus reglas productivas.
