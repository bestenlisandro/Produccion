import { useEffect, useMemo, useRef } from 'react'
import moment, { type MomentInput } from 'moment-timezone'
import { Timeline, type DataItem, type TimelineOptions } from 'vis-timeline'
import 'vis-timeline/styles/vis-timeline-graph2d.css'
import type { GanttData, GanttOperation } from '../../api/client'
import {
  isAdjustable, timelineGroups, timelineItems, type OperationalTimelineItem,
} from './timelineModel'

export type GanttIntent = {
  kind: 'move' | 'resize'
  operation: GanttOperation
  requestedStart: string
  requestedFinish: string
  requestedDurationMinutes: number
  requestedResourceId?: string
}

export function GanttTimeline({
  data, onSelect, adjustmentMode = false, onIntent,
}: {
  data: GanttData
  onSelect: (operation: GanttOperation) => void
  adjustmentMode?: boolean
  onIntent?: (intent: GanttIntent) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const groups = useMemo(() => timelineGroups(data), [data])
  const items = useMemo(() => timelineItems(data, adjustmentMode), [data, adjustmentMode])

  useEffect(() => {
    if (!container.current) return
    const byId = new Map(data.operations.map(value => [value.operation_id, value]))
    let timeline: Timeline
    const options: TimelineOptions = {
      start: data.range_from, end: data.range_to,
      min: data.range_from, max: data.range_to,
      height: '580px', orientation: 'top',
      editable: adjustmentMode, groupEditable: false, itemsAlwaysDraggable: false,
      selectable: true, moveable: true, zoomable: true,
      horizontalScroll: true, verticalScroll: true, zoomKey: 'ctrlKey',
      stack: true, stackSubgroups: true, groupHeightMode: 'fitItems',
      showCurrentTime: true, locale: 'es',
      zoomMin: 60 * 60 * 1000, zoomMax: 31 * 24 * 60 * 60 * 1000,
      snap: date => new Date(Math.round(date.valueOf() / 900000) * 900000),
      onMove: (raw, callback) => {
        const item = raw as OperationalTimelineItem
        const original = items.find(value => value.id === item.id)
        const operation = item.operationId ? byId.get(item.operationId) : undefined
        if (!operation || !original || !isAdjustable(operation) || !onIntent) {
          callback(null)
          return
        }
        const requestedStart = new Date(item.start as Date | string | number)
        const requestedFinish = new Date(item.end as Date | string | number)
        const originalStart = new Date(original.start as Date | string | number)
        const originalFinish = new Date(original.end as Date | string | number)
        const resized = requestedStart.valueOf() === originalStart.valueOf()
          && requestedFinish.valueOf() !== originalFinish.valueOf()
        onIntent({
          kind: resized ? 'resize' : 'move',
          operation,
          requestedStart: requestedStart.toISOString(),
          requestedFinish: requestedFinish.toISOString(),
          requestedDurationMinutes: Math.max(
            1, Math.round((requestedFinish.valueOf() - requestedStart.valueOf()) / 60000),
          ),
          requestedResourceId: data.group_by === 'resource'
            && typeof item.group === 'string' && item.group !== original.group
            ? item.group : undefined,
        })
        callback(null)
      },
      moment: ((value?: MomentInput) => moment(value).tz(data.timezone)) as NonNullable<TimelineOptions['moment']>,
      template: (raw: OperationalTimelineItem | undefined) => {
        const target = document.createElement('span')
        if (!raw) return target
        target.textContent = raw.content ?? ''
        if (raw.operationId) {
          target.tabIndex = 0
          target.setAttribute('role', 'button')
          target.setAttribute('aria-label', raw.ariaLabel ?? raw.content ?? 'Operación')
          target.onkeydown = event => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              const operation = byId.get(raw.operationId!)
              if (operation) onSelect(operation)
            }
          }
        }
        return target
      },
    }
    timeline = new Timeline(
      container.current,
      items as DataItem[],
      groups,
      options,
    )
    timeline.on('select', properties => {
      const identifier = properties.items[0]
      const selected = items.find(item => item.id === identifier)
      if (!selected?.operationId) return
      const operation = byId.get(selected.operationId)
      if (operation) onSelect(operation)
    })
    return () => timeline.destroy()
  }, [data, groups, items, onSelect])

  return <div
    ref={container}
    className="ganttTimeline"
    role="region"
    aria-label={`Cronograma en zona horaria ${data.timezone}. ${adjustmentMode ? 'Modo ajuste.' : 'Sólo lectura.'}`}
  />
}
