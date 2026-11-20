BEGIN;

ALTER TABLE execution.remaining_resource_estimates
DROP CONSTRAINT ck_execution_remaining_resources_dimension;
ALTER TABLE execution.remaining_resource_estimates
ADD CONSTRAINT ck_execution_remaining_resources_dimension CHECK (
  (dimension='LABOR_WORK' AND min_people IS NOT NULL AND max_people IS NOT NULL
   AND min_people >= 1 AND max_people >= min_people AND physical_requirement_id IS NULL AND expected_release_at IS NULL)
  OR (dimension='ACTIVE_PHYSICAL_USE' AND physical_requirement_id IS NOT NULL AND remaining_minutes IS NOT NULL AND skill_id IS NULL AND expected_release_at IS NULL)
  OR (dimension='PHYSICAL_OCCUPATION' AND physical_resource_id IS NOT NULL AND (remaining_minutes IS NOT NULL OR expected_release_at IS NOT NULL) AND skill_id IS NULL)
);

COMMIT;
