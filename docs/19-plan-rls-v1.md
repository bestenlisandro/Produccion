# Plan de implementación RLS V1

## 1. Estado

RLS no se activa en esta etapa. La base backend usa contexto tenant explícito y FK compuestas, pero no existe todavía un proveedor de identidad integrado ni una suite de políticas con usuarios reales.

Activar RLS parcialmente produciría una falsa garantía y podría romper migraciones, workers o transacciones de promoción.

## 2. Identidad futura

La opción prevista es Supabase Auth o un proveedor JWT equivalente:

1. el token autenticado aporta `sub` verificable;
2. `core.user_profiles.auth_subject` enlaza ese `sub` con el perfil interno;
3. `core.user_roles` determina organización, rol, planta y vigencia;
4. la aplicación establece claims/contexto de sesión sólo después de validar el token;
5. PostgreSQL aplica políticas como última barrera.

No se almacenan passwords en la aplicación de producción.

## 3. Roles funcionales

Los códigos V1 permanecen cerrados:

- `admin`;
- `planner`;
- `supervisor`;
- `operator`;
- `portal-service`.

Permisos sensibles se separan conceptualmente:

- planificar/simular;
- confirmar programa;
- publicar al cliente.

El rol PostgreSQL técnico no reemplaza estos permisos funcionales.

## 4. Políticas por grupo

### Datos internos tenant-owned

`USING` y `WITH CHECK` exigirán que `organization_id` pertenezca a una membership vigente derivada del usuario autenticado.

### Planificación y confirmación

- lectura: miembros autorizados de la organización/planta;
- simulación: `admin` o `planner`;
- confirmación/promoción: permiso específico y función transaccional controlada;
- soluciones/versiones finales: sin `UPDATE` directo para roles normales.

### Ejecución

`operator`, `supervisor`, `planner` o `admin` según comando y planta. Inserciones de hechos se realizarán mediante servicios/funciones autorizadas, no CRUD abierto.

### Publicación y portal

- publicación: permiso `CLIENT_PUBLISH`;
- cliente público: nunca consulta tablas internas;
- `portal-service` accede sólo a función/vista allowlist que valida hash de token y devuelve `portal.public_project_projections`/timeline autorizado.

### Auditoría e integración

- auditoría: insert mediante servicio, lectura restringida;
- inbox/outbox: roles técnicos separados;
- payloads no quedan visibles al portal ni a operadores sin permiso.

## 5. Contexto de sesión

La API futura no confiará en `organization_id` enviado por el body o por headers arbitrarios. Derivará:

- `auth_subject` desde JWT verificado;
- organizaciones/plantas permitidas desde memberships/roles;
- actor interno desde `core.user_profiles`.

Las variables de sesión o claims usados por políticas deberán establecerse dentro de la misma conexión/transacción y limpiarse al devolverla al pool.

## 6. Plan incremental

1. integrar Supabase Auth en ambiente de prueba;
2. fijar contrato JWT y rotación de claves;
3. crear roles PostgreSQL runtime/migrator/worker/portal;
4. implementar helpers de contexto tenant;
5. activar RLS tabla por tabla, comenzando por `core` y `capacity`;
6. continuar con producción, planificación y ejecución;
7. aislar portal mediante funciones/vistas security-definer auditadas;
8. agregar pruebas positivas/negativas por rol, organización y planta;
9. probar pool de conexiones para evitar fuga de contexto;
10. recién entonces habilitar RLS en despliegue productivo.

## 7. Casos obligatorios

- usuario de organización A no lee/escribe B;
- UUID válido de otro tenant no elude la política;
- planner simula pero no publica si no tiene permiso;
- confirmador no promueve escenario stale;
- operator registra ejecución sólo en su planta autorizada;
- portal no obtiene personas, recursos, costos, prioridades o escenarios;
- worker/inbox/outbox conservan separación técnica;
- una conexión reutilizada no conserva claims del request anterior.

## 8. Criterio de activación

RLS sólo se considera lista cuando existan usuarios autenticados reales de prueba, políticas completas para el conjunto en alcance y una suite automatizada que pruebe explícitamente accesos permitidos y denegados.

