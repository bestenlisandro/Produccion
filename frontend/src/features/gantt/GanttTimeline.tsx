import { useEffect, useMemo, useRef } from 'react'
import moment, { type MomentInput } from 'moment-timezone'
import { Timeline, type DataItem, type TimelineOptions } from 'vis-timeline'
import 'vis-timeline/styles/vis-timeline-graph2d.css'
import type { GanttData, GanttOperation } from '../../api/client'
import { timelineGroups, timelineItems, type OperationalTimelineItem } from './timelineModel'

export function GanttTimeline({
  data, onSelect,
}: {
  data: GanttData
  onSelect: (operation: GanttOperation) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const groups = useMemo(() => timelineGroups(data), [data])
  const items = useMemo(() => timelineItems(data), [data])

  useEffect(() => {
    if (!container.current) return
    const byId = new Map(data.operations.map(value => [value.operation_id, value]))
    let timeline: Timeline
    const options: TimelineOptions = {
      start: data.range_from, end: data.range_to,
      min: data.range_from, max: data.range_to,
      height: '580px', orientation: 'top',
      editable: false, groupEditable: false, itemsAlwaysDraggable: false,
      selectable: true, moveable: true, zoomable: true,
      horizontalScroll: true, verticalScroll: true, zoomKey: 'ctrlKey',
      stack: true, stackSubgroups: true, groupHeightMode: 'fitItems',
      showCurrentTime: true, locale: 'es',
      zoomMin: 60 * 60 * 1000, zoomMax: 31 * 24 * 60 * 60 * 1000,
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
    aria-label={`Cronograma en zona horaria ${data.timezone}. Sólo lectura.`}
  />
}
