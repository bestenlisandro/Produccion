import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { request } from '../../api/client'
import type { components } from '../../api/schema'
import styles from './ResourceOccupancyPage.module.css'

type Report = components['schemas']['ResourceOccupancyResponse']
type Resource = components['schemas']['ResourceOccupancyRow']
type Day = components['schemas']['ResourceOccupancyDay']
type Alert = components['schemas']['ResourceOccupancyBooking']['alerts'][number]

const dateFormat = new Intl.DateTimeFormat('es-AR', {
  weekday: 'short', day: '2-digit', month: '2-digit', timeZone: 'UTC',
})
const numberFormat = new Intl.NumberFormat('es-AR', { maximumFractionDigits: 1 })
const statuses = {
  no_shift: 'Sin turno',
  unavailable: 'No disponible',
  missing_calendar: 'Calendario sin configurar',
}
const alertLabels: Record<Alert, string> = {
  outside_availability: 'Fuera de disponibilidad',
  overlap: 'Solapamiento',
}
const bookingLabels = {
  work: 'Asignación',
  hold: 'Reserva continua planificada',
  actual_hold: 'Reserva continua registrada',
}
const dayLabel = (date: string) => dateFormat.format(new Date(date + 'T00:00:00Z'))
const duration = (minutes: number | null) => {
  if (minutes === null) return '—'
  const rounded = Math.round(minutes * 10) / 10
  const hours = Math.floor(rounded / 60)
  const remainder = rounded - hours * 60
  return hours ? `${hours} h ${numberFormat.format(remainder)} min` : `${numberFormat.format(remainder)} min`
}
const cellLabel = (day: Day) => day.status === 'available'
  ? `${numberFormat.format(day.percent ?? 0)} %` : statuses[day.status]
const tone = (day: Day) => {
  if (day.status !== 'available') return day.status
  const percent = day.percent ?? 0
  if (percent === 0) return 'free'
  if (percent < 50) return 'low'
  if (percent < 85) return 'medium'
  return 'high'
}

export function ResourceOccupancyPage() {
  const report = useQuery({
    queryKey: ['resource-occupancy'],
    queryFn: ({signal}) => request<Report>('/planning/current/resource-occupancy', {signal}),
    refetchInterval: 60_000,
  })
  const [selection, setSelection] = useState<{resourceId: string, date: string}>()
  const data = report.data
  const groups = new Map<string, Resource[]>()
  for (const resource of data?.resources ?? []) {
    const group = groups.get(resource.group_key) ?? []
    group.push(resource)
    groups.set(resource.group_key, group)
  }
  const selectedResource = data?.resources.find(resource => resource.id === selection?.resourceId)
  const selectedDay = selectedResource?.days.find(day => day.date === selection?.date)

  return <main className={styles.page}>
    <header className={styles.header}>
      <div>
        <p className="eyebrow">PLANIFICACIÓN</p>
        <h1>Ocupación de recursos</h1>
        {data && <p className={styles.subtitle}>{data.plant_name} · {data.timezone}
          {data.plan_version_number !== null && <> · CURRENT V{data.plan_version_number}</>}
        </p>}
      </div>
      <Link to="/planning/gantt">Gantt operativo</Link>
    </header>

    {report.isPending && <p className="state" role="status">Cargando ocupación…</p>}
    {report.isError && <div className="state" role="alert">
      <p>No pudimos consultar la ocupación de recursos.</p>
      <button type="button" onClick={() => void report.refetch()}>Reintentar</button>
    </div>}
    {!report.isError && data && data.plan_version_number === null &&
      <p className="state" role="status">No hay un plan vigente (CURRENT) publicado.</p>}
    {!report.isError && data && data.plan_version_number !== null && <>
      {groups.size === 0 ? <p className="state">No hay recursos productivos activos.</p> : <>
        <div className={styles.toolbar}>
          <span>{dayLabel(data.dates[0])} – {dayLabel(data.dates.at(-1)!)} · 30 días corridos</span>
          <ul className={styles.legend} aria-label="Escala de ocupación">
            {[['free', '0 %'], ['low', 'Menos de 50 %'], ['medium', '50–<85 %'], ['high', '85–100 %']].map(([key, label]) =>
              <li key={key}><span data-tone={key} aria-hidden="true"/>{label}</li>)}
          </ul>
        </div>
        <div className={styles.scroll} tabIndex={0} role="region" aria-label="Matriz de ocupación de recursos">
          <table className={styles.matrix}>
            <thead><tr>
              <th scope="col">Recurso</th>
              {data.dates.map((date, index) => <th key={date} scope="col" data-today={index === 0}>
                <time dateTime={date}>{dayLabel(date)}</time>
                {index === 0 && <span className={styles.today}>Hoy</span>}
              </th>)}
            </tr></thead>
            {[...groups.entries()].map(([key, resources]) => <tbody key={key}>
              <tr className={styles.group}>
                <th scope="rowgroup">{resources[0].group_name}</th>
                <td colSpan={data.dates.length}/>
              </tr>
              {resources.map(resource => <tr key={resource.id}>
                <th scope="row">{resource.name}</th>
                {resource.days.map(day => {
                  const label = cellLabel(day)
                  const warnings = day.bookings.some(booking => booking.alerts.length > 0)
                  return <td key={day.date}><button type="button" data-tone={tone(day)}
                    className={styles.cell} aria-label={`${resource.name}, ${dayLabel(day.date)}, ${label}${warnings ? ', con alertas' : ''}`}
                    aria-pressed={resource.id === selection?.resourceId && day.date === selection?.date}
                    aria-controls="occupancy-detail"
                    onClick={() => setSelection({resourceId: resource.id, date: day.date})}>
                      {label}{warnings && <span className={styles.warningMark} aria-hidden="true">!</span>}
                  </button></td>
                })}
              </tr>)}
            </tbody>)}
          </table>
        </div>
        <section id="occupancy-detail" className={styles.detail} aria-label="Detalle de ocupación" aria-live="polite">
          {selectedResource && selectedDay
            ? <CellDetail resource={selectedResource} day={selectedDay} timezone={data.timezone}/>
            : <p>Seleccioná una celda para ver la disponibilidad y las reservas del día.</p>}
        </section>
      </>}
    </>}
  </main>
}

function CellDetail({resource, day, timezone}: {resource: Resource, day: Day, timezone: string}) {
  const timestamp = new Intl.DateTimeFormat('es-AR', {
    day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23', timeZone: timezone,
  })
  return <>
    <div className={styles.detailHeading}>
      <h2>{resource.name}</h2>
      <span>{dayLabel(day.date)} · {cellLabel(day)}</span>
    </div>
    <dl className={styles.totals}>
      <div><dt>Disponibles</dt><dd>{duration(day.available_minutes)}</dd></div>
      <div><dt>Ocupadas</dt><dd>{duration(day.occupied_minutes)}</dd></div>
      <div><dt>Libres</dt><dd>{duration(day.free_minutes)}</dd></div>
    </dl>
    {day.bookings.length === 0 ? <p>Sin asignaciones ni reservas.</p> :
      <ul className={styles.bookings}>{day.bookings.map(item => <li key={item.id}>
        <strong>{item.project_code} · {item.project_name} · {item.operation_name}</strong>
        <p>{bookingLabels[item.kind]} · {timestamp.format(new Date(item.start_at))}
          {item.end_at ? <> → {timestamp.format(new Date(item.end_at))}</> : ' · Liberación desconocida'}</p>
        <p>{item.minutes_in_day !== null && <>{duration(item.minutes_in_day)} en esta fecha · </>}
          {item.occupied_minutes === null ? 'Ocupación sin calcular'
            : <>{duration(item.occupied_minutes)} dentro de disponibilidad</>}</p>
        {item.alerts.length > 0 && <p className={styles.alert}>{item.alerts.map(alert => alertLabels[alert]).join(' · ')}</p>}
      </li>)}</ul>}
  </>
}
