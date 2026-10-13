import type { DataGroup, DataItem } from 'vis-timeline'
import type { GanttData, GanttOperation } from '../../api/client'

export type OperationalTimelineItem = DataItem & {
  operationId?: string
  ariaLabel?: string
  content?: string
}

const statusClass = (status: string) => `gantt-status-${status.toLowerCase()}`

export function timelineGroups(data: GanttData): DataGroup[] {
  return data.groups.map(group => ({
    id: group.id,
    content: group.capacity && group.capacity > 1
      ? `${group.label} · capacidad ${group.capacity}`
      : group.label,
    title: group.capacity_mode
      ? `${group.label} · ${group.capacity_mode}`
      : group.label,
  }))
}

export function timelineItems(data: GanttData): OperationalTimelineItem[] {
  const items: OperationalTimelineItem[] = []
  for (const window of data.working_windows) {
    for (const group of data.groups) {
      items.push({
        id: `window-${group.id}-${window.started_at}`,
        group: group.id, start: window.started_at, end: window.ended_at,
        type: 'background', content: '', className: `gantt-working ${window.kind}`,
      })
    }
  }
  for (const operation of data.operations) {
    for (const group of operation.group_ids) {
      if (operation.planned_start && operation.planned_finish) {
        items.push({
          id: `plan-${operation.operation_id}-${group}`,
          group, start: operation.planned_start, end: operation.planned_finish,
          subgroup: 'plan', operationId: operation.operation_id,
          content: `${statusPrefix(operation.operational_status)}${operation.project_name} · ${operation.operation_name}`,
          className: `gantt-plan ${statusClass(operation.operational_status)}`,
          ariaLabel: operationLabel(operation, 'Plan vigente'),
        })
      }
      for (const segment of operation.actual_segments ?? []) {
        items.push({
          id: `actual-${segment.id}-${group}`,
          group, start: segment.started_at, end: segment.ended_at,
          subgroup: 'actual', operationId: operation.operation_id,
          content: 'REAL',
          className: 'gantt-actual',
          ariaLabel: operationLabel(operation, 'Segmento real ejecutado'),
        })
      }
    }
  }
  if (data.group_by === 'resource') {
    for (const occupation of data.occupations) {
      items.push({
        id: `occupation-${occupation.id}`, group: occupation.group_id,
        start: occupation.started_at, end: occupation.ended_at,
        subgroup: 'occupation', content: 'OCUPACIÓN',
        className: `gantt-occupation ${occupation.source_kind}`,
        ariaLabel: `Ocupación física ${occupation.resource_name}, ${occupation.project_name}`,
      })
    }
  }
  const byOperation = new Map(data.operations.map(item => [item.operation_id, item]))
  for (const overlay of data.scenario?.operations ?? []) {
    const operation = byOperation.get(overlay.operation_id)
    if (!operation || !overlay.planned_start || !overlay.planned_finish) continue
    for (const group of operation.group_ids) {
      items.push({
        id: `scenario-${overlay.operation_id}-${group}`,
        group, start: overlay.planned_start, end: overlay.planned_finish,
        subgroup: 'scenario', operationId: overlay.operation_id,
        content: overlay.difference.replaceAll('_', ' '),
        className: `gantt-scenario difference-${overlay.difference.toLowerCase()}`,
        ariaLabel: operationLabel(operation, `Simulación ${overlay.difference}`),
      })
    }
  }
  return items
}

export function operationLabel(operation: GanttOperation, prefix: string) {
  return [
    prefix, operation.project_name, operation.operation_name,
    operation.operational_status.replaceAll('_', ' '), operation.priority,
  ].join(', ')
}

export function differenceLabel(value: string) {
  return ({
    UNCHANGED: 'Sin cambio', SHIFTED: 'Desplazada', ADVANCED: 'Adelantada',
    DELAYED: 'Retrasada', OUT_OF_HORIZON: 'Nueva posición fuera de horizonte',
    NEWLY_PLANNED: 'Nueva en la simulación',
  } as Record<string, string>)[value] ?? value
}

function statusPrefix(status: string) {
  if (status === 'DEMORADO') return 'DEMORADA · '
  if (status === 'BLOQUEADO') return 'BLOQUEADA · '
  if (status === 'EN_CURSO') return 'EN CURSO · '
  return ''
}
