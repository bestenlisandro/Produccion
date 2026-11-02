from sqlalchemy import Connection, text

from production_besten.domain.scenario_expiry import PlannedOperationTiming


def solution_timings(conn: Connection, organization_id, solution_id):
    # Inspect the entire solution, independently of the visible Gantt range.
    rows = conn.execute(text("""
        SELECT opr.planned_start_at,opr.planned_end_at,
               EXISTS(SELECT 1 FROM execution.operation_executions oe
                       WHERE oe.organization_id=opr.organization_id
                         AND oe.required_operation_id=opr.required_operation_id
                         AND oe.started_at IS NOT NULL) AS execution_started
          FROM planning.operation_plan_results opr
         WHERE opr.organization_id=:org AND opr.schedule_solution_id=:solution
    """), {"org": organization_id, "solution": solution_id}).mappings()
    return tuple(PlannedOperationTiming(row["planned_start_at"], row["planned_end_at"],
                                        row["execution_started"]) for row in rows)
