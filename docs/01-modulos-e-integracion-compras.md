# Límites de módulos e integración con Compras

## 1. Objetivo

Producción Besten debe funcionar de manera autónoma en V1 y quedar preparada para relacionarse más adelante con la aplicación de Compras. La integración no debe fusionar ambos dominios ni obligar a desplegarlos juntos.

## 2. Propiedad de los datos

### Producción es fuente de verdad de

- proyecto y lote que necesitan el material;
- requerimiento productivo;
- cantidad requerida para habilitar la operación;
- fecha en la que se necesita;
- prioridad e impacto productivo;
- asignación de material recibido a lotes;
- condición de habilitación del planificador.

### Compras podrá ser fuente de verdad de

- proveedores;
- solicitud y orden de compra;
- precios, moneda y condiciones;
- seguimiento comercial de la orden;
- entrega prometida por el proveedor;
- recepción administrativa y documentación.

### Datos compartidos mediante contrato

- identificador del requerimiento productivo;
- identificador externo de solicitud u orden;
- material solicitado y cantidad;
- fecha requerida y prometida;
- estado resumido;
- cantidades recibidas;
- demoras y cancelaciones;
- referencia de origen y fecha del evento.

## 3. Flujo futuro

```text
Producción: necesidad de material
    -> evento MaterialRequirementCreated
Compras: solicitud/orden
    -> evento PurchaseOrderLinked
Compras: promesa o demora
    -> evento SupplierDeliveryChanged
Compras: recepción
    -> evento MaterialReceived
Producción: asignación al lote
    -> recalcular disponibilidad
    -> detectar impacto
    -> crear propuesta de escenario
```

Una demora o recepción puede disparar detección de impacto, pero nunca publicar automáticamente una reprogramación.

## 4. Patrón técnico

- API o eventos versionados; nunca consultas directas entre bases de datos.
- `source_system` y `external_reference` en entidades integrables.
- Outbox para publicar eventos después de una transacción confirmada.
- Inbox para registrar eventos recibidos.
- Clave de idempotencia para evitar procesar duplicados.
- Número de versión o fecha efectiva para ordenar cambios.
- Reintentos y bandeja de errores sin pérdida silenciosa.
- Registro del payload original y resultado de procesamiento para trazabilidad.

## 5. Consistencia

La integración será de consistencia eventual. El sistema deberá mostrar:

- última sincronización;
- estado de integración;
- dato pendiente de confirmar;
- errores que requieren intervención.

El motor solo utilizará como habilitación una disponibilidad confirmada en Producción. Recibir un evento de Compras no implica necesariamente que el material ya esté asignado físicamente a un lote.

## 6. Operación autónoma

Mientras Compras no esté integrada:

- pedidos y recepciones se registran manualmente en Producción;
- el mismo modelo conserva `source_system = production`;
- la futura vinculación no exige migrar la lógica del planificador;
- los datos manuales no se eliminan al activar la integración.

## 7. Conflictos y reconciliación

- Un dato proveniente de Compras no sobrescribe silenciosamente una corrección manual local.
- Los conflictos generan una tarea de reconciliación.
- La asignación de recepciones a lotes sigue siendo responsabilidad de Producción.
- Reversas, devoluciones o material dañado generan eventos compensatorios; no se borran recepciones históricas.

## 8. Aislamiento de proyectos técnicos

- Repositorios, bases de datos, secretos y despliegues separados.
- Nombres de servicios y contenedores con prefijo `produccion-besten`.
- Contratos compartidos publicados con versión propia, sin copiar tablas.
- Ninguna dependencia de código directa con la aplicación de Eficiencia Energética.
- Autenticación compartida podrá evaluarse después, sin mezclar dominios ni permisos.
