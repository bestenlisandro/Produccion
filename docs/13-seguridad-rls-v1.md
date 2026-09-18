# Seguridad y estrategia RLS PostgreSQL V1

## 1. Estado

El repositorio no está conectado a Supabase ni dispone de un proveedor de claims verificable. Por ello las migraciones V1 **no habilitan RLS todavía** ni inventan objetos `auth.*`. Sí implementan aislamiento estructural tenant-safe, revocan privilegios a `PUBLIC` y dejan preparada la futura política.

## 2. Identidad

`core.user_profiles.auth_subject` es el identificador externo único. En Supabase almacenará `auth.users.id::text`; con otro proveedor almacenará su subject estable. No se guardan passwords, refresh tokens ni hashes de credenciales.

La aplicación resolverá:

> identidad autenticada → user_profile activo → organization_id → roles vigentes/planta

## 3. Ownership

Las 87 tablas tienen `organization_id`, excepto que `core.organizations` es la raíz tenant. Cada tabla hija tiene UNIQUE `(organization_id,id)` y las FK tenant-owned usan ambos campos. Esto impide cross-tenant incluso con RLS deshabilitada o ante un error del servicio.

Ownership adicional:

- planta: proyectos, capacidad, revisiones, escenarios y versiones;
- proyecto/lote: producción, material, instalación y portal;
- escenario/solución: resultados y reservas contextuales;
- ejecución: segmentos, usos y restante;
- organización: usuarios, catálogos, integration y audit.

## 4. Roles V1

| Rol | Lectura | Escritura prevista |
|---|---|---|
| `admin` | Todo el tenant | Configuración y administración, salvo historia inmutable |
| `planner` | Producción/capacidad/planning | Escenarios, hipótesis, excepciones autorizadas y promoción |
| `supervisor` | Plan y ejecución | Eventos, ejecución, restante e indisponibilidades según permiso |
| `operator` | Trabajo asignado | Inicio/pausa/fin y captura real acotada |
| `portal_service` | Solo proyección pública necesaria | Publicación controlada, nunca producción interna |

Los códigos son enum V1; los permisos concretos viven en una allowlist versionada de aplicación.

## 5. Estrategia futura de claims

Cuando exista Auth se implementará una función estable equivalente a `security.current_organization_id()` que lea un claim firmado o una variable de sesión establecida exclusivamente por un gateway confiable. No se aceptará un `organization_id` enviado libremente por el cliente.

Para Supabase se evaluará `auth.uid()` y claims JWT. Para PostgreSQL local/API propia, el pool establecerá contexto con `SET LOCAL` dentro de transacción y un rol sin permiso para alterar arbitrariamente esa configuración.

## 6. Políticas RLS futuras

Política base tenant-owned:

- `USING (organization_id = current_organization_id())` para SELECT/UPDATE/DELETE;
- `WITH CHECK (organization_id = current_organization_id())` para INSERT/UPDATE;
- filtros adicionales por planta y rol;
- service roles separados para integration, audit y portal.

No se concederá DELETE normal sobre historia. RLS complementa, no reemplaza, las FK compuestas.

## 7. Escritura por dominio

- `core/capacity/production`: escritura de configuración por admin/planner; cambios relevantes generan revisión/evento mediante servicio.
- `planning`: escenarios editables por planner; soluciones/resultados solo worker; plan versions solo servicio de promoción.
- `execution`: supervisor/operator mediante comandos; segmentos y eventos compensatorios, no update destructivo.
- `portal`: proyección únicamente por publicador interno; acceso anónimo por función que valida token hash.
- `integration`: inbox/outbox solo workers dedicados.
- `audit`: INSERT por servicios; sin UPDATE/DELETE para cuentas de aplicación.

## 8. Portal público

El token presentado se hashea y compara con `portal.public_tracking_links.token_hash`. Una función `SECURITY DEFINER` futura, con `search_path` fijo y permisos mínimos, devolverá exclusivamente columnas allowlist de D095/D096. El rol anónimo no recibe SELECT directo sobre tablas internas ni sobre la tabla completa de tokens.

Rotación revoca el enlace anterior. Un proyecto no puede tener más de un link activo V1.

## 9. Integration y audit

Workers de inbox/outbox usarán roles de DB separados. Payload e idempotency key no pueden alterarse; solo estado técnico. Auditoría acepta INSERT y consultas autorizadas, nunca modificación destructiva.

## 10. Seguridad base implementada ahora

- FK compuestas tenant-safe;
- `organization_id` obligatorio;
- privilegios `PUBLIC` revocados en los 8 schemas y sus tablas/secuencias;
- Auth externo mediante `auth_subject`;
- token público almacenado solo como hash;
- no existen passwords propias;
- ausencia de `ON DELETE CASCADE` en evidencia histórica;
- schemas separados para permisos futuros.

## 11. Validación antes de habilitar RLS

1. conectar proveedor Auth real;
2. probar claim válido, ausente y manipulado;
3. probar dos organizaciones y dos plantas;
4. verificar SELECT/INSERT/UPDATE cross-tenant;
5. probar service roles de portal/integration/audit;
6. confirmar que el owner de migraciones no sea el rol de runtime;
7. ejecutar tests con `FORCE ROW LEVEL SECURITY` donde corresponda;
8. documentar excepciones administrativas.

Hasta completar estas pruebas, activar RLS sería una falsa garantía. La integridad multitenant estructural ya queda aplicada en las migraciones.
