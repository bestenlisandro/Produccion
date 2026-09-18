# Etapa 3.1 — Entorno de validación PostgreSQL V1

Fecha de comprobación: 2026-09-01  
Estado: **BLOQUEADA POR ENTORNO DE EJECUCIÓN**

## 1. Objetivo de la comprobación

Antes de modificar las migraciones M0–M10 se volvió a buscar un PostgreSQL 15+ ejecutable y descartable, tal como exige la Etapa 3.1.

La validación real requiere poder:

1. crear la base descartable `produccion_besten_test`;
2. habilitar las extensiones `pgcrypto` y `btree_gist`;
3. aplicar M0–M10 sin cambios preventivos;
4. ejecutar las pruebas de catálogo, temporales y funcionales;
5. eliminar y recrear la base;
6. repetir exitosamente la cadena completa una segunda vez.

## 2. Detección realizada

### 2.1 Cliente y servidor PostgreSQL local

| Comprobación | Resultado |
|---|---|
| `psql` en `PATH` | No encontrado |
| `pg_isready` en `PATH` | No encontrado |
| Instalación bajo `C:\Program Files\PostgreSQL` | No encontrada |
| Producto PostgreSQL registrado en Windows | No encontrado |
| Servicio Windows con nombre PostgreSQL | No encontrado |
| Proceso local `postgres` | No encontrado |
| Servidor escuchando en `127.0.0.1:5432` | No accesible |

Por lo tanto, no existe actualmente un cliente ni un servidor PostgreSQL local utilizable para la prueba.

### 2.2 Docker Desktop

| Comprobación | Resultado |
|---|---|
| Ejecutable Docker CLI | Encontrado en `C:\Program Files\Docker\Docker\resources\bin\docker.exe` |
| Docker Desktop instalado | Sí |
| `docker desktop status` | `stopped` |
| Servicio `com.docker.service` | `STOPPED` |
| Consulta al engine mediante `docker info` | No respondió; se interrumpió sin modificar el entorno |

Docker está instalado, pero no hay un engine operativo capaz de iniciar un contenedor PostgreSQL.

### 2.3 WSL

| Comprobación | Resultado |
|---|---|
| Versión predeterminada | WSL 2 |
| Distribuciones instaladas | Ninguna |

WSL está habilitado, pero no dispone de una distribución desde la cual ejecutar PostgreSQL ni sostener el backend Linux requerido por Docker.

### 2.4 Supabase CLI

| Comprobación | Resultado |
|---|---|
| `supabase` en `PATH` | No encontrado |
| Ejecutable local conocido | No encontrado |

No hay un runtime local de Supabase disponible como alternativa.

## 3. Condición faltante

Para continuar hace falta que el usuario deje disponible **una** de estas alternativas:

- PostgreSQL 15 o superior con servidor activo, `psql`, permiso para crear/eliminar `produccion_besten_test` y permiso para instalar `pgcrypto` y `btree_gist`;
- Docker Desktop con engine Linux operativo; o
- Supabase CLI con un proyecto local inicializado y PostgreSQL accesible.

La preparación de cualquiera de esas alternativas implica instalar, iniciar o configurar infraestructura y eventualmente aceptar licencias. Esa acción no se realizó automáticamente.

## 4. Cómo retomar la validación

Con PostgreSQL disponible, la primera aplicación puede iniciarse con:

```powershell
.\db\verify\apply_with_psql.ps1 -DatabaseUrl '<postgresql-connection-string>'
```

La conexión debe apuntar exclusivamente a la base descartable `produccion_besten_test` o permitir crearla. Antes de declarar el cierre deberán ejecutarse las dos recreaciones limpias y todas las pruebas previstas por la Etapa 3.1.

## 5. Archivos y estado preservados

- No se modificó ningún archivo de `db/migrations/`.
- No se ejecutó ninguna migración contra una base real.
- No se creó `docs/16-validacion-real-postgresql-v1.md`, porque no hubo validación real que registrar.
- No se actualizó `docs/14-validacion-migraciones-v1.md`: su resultado estático y su estado pendiente continúan vigentes.
- No se instaló ni reconfiguró PostgreSQL, Docker, WSL o Supabase.
- No se creó ningún commit.

## 6. Conclusión formal

La Etapa 3.1 no puede validar todavía la sintaxis, las restricciones ni los escenarios sobre un motor PostgreSQL real. El bloqueo es exclusivamente la ausencia de un runtime ejecutable; esta comprobación no detectó una nueva brecha del esquema.

**`MIGRACIONES_V1_REQUIEREN_AJUSTES`**

