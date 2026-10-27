-- Reproducible catalog upgrade for the existing Besten organization only.
-- Preserves IDs, referenced codes, status and all productive requirements.
BEGIN;
DO $$ BEGIN
    IF (SELECT count(*) FROM core.organizations WHERE id='cc1f3ea8-d31c-4a84-9c2b-0b207ba715f3') <> 1 THEN
        RAISE EXCEPTION 'Existing Besten organization is required';
    END IF;
END $$;
INSERT INTO production.operation_definitions(organization_id,code,name,category,display_order)
SELECT 'cc1f3ea8-d31c-4a84-9c2b-0b207ba715f3'::uuid,code,name,'production_stage',position
FROM (VALUES
    ('PREPARACION_PROYECTO','Preparación del Proyecto',1),
    ('CORTE_ESCUADRADORA','Corte',2),
    ('PEGADO','Pegado de Cantos',3),
    ('PERFORADORA_MULTIPLE','Procesado con Múltiple',4),
    ('PROCESADO_SIN_MULTIPLE','Procesado sin Múltiple',5),
    ('ARMADO','Armado',6),
    ('CONTROL_CALIDAD','Control de Calidad',7),
    ('EMBALAJE','Embalaje',8),
    ('INSTALACION','Instalación',9)
) AS stages(code,name,position)
ON CONFLICT (organization_id,code) DO UPDATE
SET name=EXCLUDED.name,display_order=EXCLUDED.display_order,
    updated_at=now(),row_version=production.operation_definitions.row_version+1
WHERE (production.operation_definitions.name,production.operation_definitions.display_order)
    IS DISTINCT FROM (EXCLUDED.name,EXCLUDED.display_order);
COMMIT;
