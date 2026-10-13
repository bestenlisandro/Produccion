import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import {
  ApiError, api, type GanttGrouping, type GanttOperation,
} from '../../api/client'
import { ErrorState, Loading } from '../../components/AsyncState'
import { blockerMessage, minutes } from '../daily-board/presentation'
import { GanttTimeline } from './GanttTimeline'
import { differenceLabel } from './timelineModel'
import {
  formatRange, ganttRange, localDate, moveAnchor, plantDateTime,
  type GanttView,
} from './time'
import styles from './GanttPage.module.css'

const groupLabels: Record<GanttGrouping, string> = {
  center: 'Centro de trabajo', resource: 'Recurso físico',
  person: 'Persona', project: 'Proyecto',
}

export function GanttPage() {
  const qc = useQueryClient()
  const [timezone, setTimezone] = useState('UTC')
  const [anchor, setAnchor] = useState(() => localDate('UTC'))
  const [anchorChanged, setAnchorChanged] = useState(false)
  const [view, setView] = useState<GanttView>('week')
  const [groupBy, setGroupBy] = useState<GanttGrouping>('center')
  const [scenarioId, setScenarioId] = useState('')
  const [selected, setSelected] = useState<GanttOperation>()
  const [message, setMessage] = useState('')
  const range = useMemo(() => ganttRange(anchor, view, timezone), [anchor, view, timezone])
  const query = useQuery({
    queryKey: ['current-plan', 'gantt', range.from, range.to, groupBy, scenarioId || null],
    queryFn: () => api.gantt(range.from, range.to, groupBy, scenarioId || undefined),
    placeholderData: previous => previous,
  })
  useEffect(() => {
    if (!query.data || query.data.timezone === timezone) return
    setTimezone(query.data.timezone)
    if (!anchorChanged) setAnchor(localDate(query.data.timezone))
  }, [query.data, timezone, anchorChanged])
  const selectOperation = useCallback((operation: GanttOperation) => setSelected(operation), [])
  const refreshCurrent = async () => {
    setScenarioId('')
    setSelected(undefined)
    await qc.refetchQueries({ queryKey: ['current-plan', 'gantt'], type: 'all' })
  }
  const accept = useMutation({
    mutationFn: () => api.accept(
      query.data!.scenario!.id, query.data!.scenario!.promotion_lock_version,
    ),
    onSuccess: async () => {
      await refreshCurrent()
      setMessage('Nueva planificación confirmada. El Gantt muestra el plan vigente.')
    },
    onError: error => setMessage(error instanceof ApiError && error.status === 409
      ? 'La simulación quedó obsoleta. Volvé a simular desde la operación.'
      : 'No se pudo confirmar la simulación.'),
  })
  const reject = useMutation({
    mutationFn: () => api.reject(
      query.data!.scenario!.id, query.data!.scenario!.row_version,
    ),
    onSuccess: async () => {
      await refreshCurrent()
      setMessage('La propuesta fue descartada. La realidad registrada se mantiene.')
    },
    onError: () => setMessage('No se pudo descartar la simulación.'),
  })

  if (query.isPending) return <Loading label="Cargando Gantt operativo…" />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  const data = query.data
  const changeAnchor = (value: string) => { setAnchorChanged(true); setAnchor(value) }
  const outside = (data.scenario?.operations ?? []).filter(
    item => item.difference === 'OUT_OF_HORIZON',
  ).length ?? 0

  return <main className={styles.page}>
    <header className={styles.heading}>
      <div><p className="eyebrow">PLANIFICACIÓN</p><h1>Gantt operativo</h1>
        <p>Plan vigente V{data.plan_version_number} · {data.timezone} · Sólo lectura</p></div>
      <Link to="/">TABLERO DIARIO</Link>
    </header>

    <section className={styles.toolbar} aria-label="Controles del Gantt">
      <div className={styles.navigation}>
        <button className="secondary" onClick={() => changeAnchor(localDate(data.timezone))}>HOY</button>
        <button className="secondary" aria-label="Período anterior" onClick={() => changeAnchor(moveAnchor(anchor, view, -1, data.timezone))}>←</button>
        <strong>{formatRange(data.range_from, data.range_to, data.timezone)}</strong>
        <button className="secondary" aria-label="Período siguiente" onClick={() => changeAnchor(moveAnchor(anchor, view, 1, data.timezone))}>→</button>
        <label>Fecha<input type="date" value={anchor} onChange={event => changeAnchor(event.target.value)} /></label>
      </div>
      <label>Agrupar por<select value={groupBy} onChange={event => setGroupBy(event.target.value as GanttGrouping)}>
        {Object.entries(groupLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <fieldset><legend>Vista</legend>{([
        ['day', 'Día'], ['week', 'Semana'], ['fortnight', '2 semanas'],
      ] as const).map(([value, label]) => <button key={value} className={view === value ? '' : 'secondary'} aria-pressed={view === value} onClick={() => setView(value)}>{label}</button>)}</fieldset>
      <label>Comparar con<select value={scenarioId} onChange={event => { setScenarioId(event.target.value); setMessage('') }}>
        <option value="">Ninguno</option>
        {data.available_scenarios.map(scenario => <option key={scenario.id} value={scenario.id}>{scenario.name}{scenario.stale ? ' · obsoleta' : ''}</option>)}
      </select></label>
    </section>

    <section className={styles.legend} aria-label="Leyenda">
      <span><i className={styles.real}/> Ejecutado real</span>
      <span><i className={styles.current}/> En curso / restante vigente</span>
      <span><i className={styles.future}/> Futuro planificado</span>
      <span><i className={styles.occupation}/> Ocupación física</span>
      <span><i className={styles.scenario}/> Simulación</span>
      <span>│ AHORA</span>
    </section>

    {data.scenario && <section className={styles.impact} aria-label="Impacto de simulación">
      <div><p className="eyebrow">COMPARACIÓN</p><h2>{data.scenario.name}</h2>
        {data.scenario.stale && <strong className="warning">SIMULACIÓN OBSOLETA</strong>}</div>
      <dl><dt>Operaciones afectadas</dt><dd>{data.scenario.changed_operations}</dd>
        <dt>Proyectos afectados</dt><dd>{data.scenario.affected_projects}</dd>
        <dt>Cambios de entrega</dt><dd>{data.scenario.project_finish_changes?.length ?? 0}</dd>
        <dt>Fuera de horizonte</dt><dd>{outside}</dd></dl>
      {data.scenario.communication_recommended && <p className="warning">Puede ser necesario avisar al cliente.</p>}
      <ul>{(data.scenario.operations ?? []).map(item => <li key={item.operation_id}>{differenceLabel(item.difference)}{item.delta_minutes ? ` · ${Math.abs(item.delta_minutes)} min` : ''}</li>)}</ul>
      {!data.scenario.stale && data.scenario.status === 'ready' && <div className="actions">
        <button disabled={accept.isPending || reject.isPending} onClick={() => accept.mutate()}>CONFIRMAR NUEVO PLAN</button>
        <button className="secondary" disabled={accept.isPending || reject.isPending} onClick={() => reject.mutate()}>CANCELAR PROPUESTA</button>
      </div>}
    </section>}
    {message && <p className={message.includes('No se pudo') || message.includes('obsoleta') ? 'warning' : 'success'} aria-live="polite">{message}</p>}

    {data.operations.length === 0
      ? <div className="state">No hay operaciones para este rango.</div>
      : <GanttTimeline data={data} onSelect={selectOperation} />}

    <section className={styles.mobileList} aria-label="Operaciones visibles">
      <h2>Operaciones visibles</h2>
      {data.operations.map(operation => <button className="secondary" key={operation.operation_id} onClick={() => setSelected(operation)}>
        {operation.project_name} · {operation.operation_name} · {operation.operational_status.replaceAll('_', ' ')}
      </button>)}
    </section>

    {selected && <aside className={styles.popover} role="dialog" aria-label="Detalle de operación">
      <button className={styles.close} aria-label="Cerrar detalle" onClick={() => setSelected(undefined)}>×</button>
      <p className="eyebrow">{selected.project_name} · {selected.lot_name}</p>
      <h2>{selected.operation_name}</h2>
      <dl><dt>Fase</dt><dd>{selected.phase_name ?? 'Sin fase'}</dd>
        <dt>Estado</dt><dd>{selected.operational_status.replaceAll('_', ' ')}</dd>
        <dt>Prioridad</dt><dd>{selected.priority}</dd>
        <dt>Inicio</dt><dd>{selected.planned_start ? plantDateTime(selected.planned_start, data.timezone) : 'Fuera de horizonte'}</dd>
        <dt>Fin</dt><dd>{selected.planned_finish ? plantDateTime(selected.planned_finish, data.timezone) : 'Fuera de horizonte'}</dd>
        <dt>Personas</dt><dd>{(selected.people ?? []).map(value => value.name).join(', ') || 'Sin asignar'}</dd>
        <dt>Recurso</dt><dd>{(selected.resources ?? []).map(value => value.name).join(', ') || 'Sin asignar'}</dd>
        <dt>Ejecutado</dt><dd>{minutes(selected.executed_minutes)}</dd>
        <dt>Restante vigente</dt><dd>{minutes(selected.remaining_minutes)}</dd></dl>
      {blockerMessage(selected.blocker_code) && <p className="warning"><strong>Bloqueo:</strong> {blockerMessage(selected.blocker_code)}</p>}
      <Link to={`/operations/${selected.operation_id}`}>VER DETALLE</Link>
    </aside>}
  </main>
}
