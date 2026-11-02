import moment from 'moment-timezone'

export type GanttView = 'day' | 'week' | 'fortnight' | 'month'

const spanDays: Record<GanttView, number> = { day: 1, week: 7, fortnight: 14, month: 31 }

export function localDate(timezone: string, now = new Date()) {
  return moment(now).tz(timezone).format('YYYY-MM-DD')
}

export function ganttRange(anchor: string, view: GanttView, timezone: string) {
  const value = moment.tz(anchor, 'YYYY-MM-DD', true, timezone)
  const start = view === 'month' ? value.startOf('month') : view === 'day' ? value.startOf('day') : value.startOf('isoWeek')
  const end = view === 'month' ? start.clone().add(1,'month') : start.clone().add(spanDays[view], 'days')
  return { from: start.toISOString(), to: end.toISOString() }
}

export function moveAnchor(anchor: string, view: GanttView, direction: -1 | 1, timezone: string) {
  return moment.tz(anchor, 'YYYY-MM-DD', true, timezone)
    .add(direction * (view==='month'?1:spanDays[view]), view==='month'?'months':'days').format('YYYY-MM-DD')
}

export function formatRange(from: string, to: string, timezone: string) {
  const formatter = new Intl.DateTimeFormat('es-AR', {
    timeZone: timezone, day: '2-digit', month: '2-digit', year: 'numeric',
  })
  return `${formatter.format(new Date(from))}–${formatter.format(new Date(new Date(to).getTime() - 1))}`
}

export function plantDateTime(value: string, timezone: string) {
  return new Intl.DateTimeFormat('es-AR', {
    timeZone: timezone, weekday: 'short', day: '2-digit', month: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}
