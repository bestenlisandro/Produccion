import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { api } from '../../api/client'
import { ErrorState, Loading } from '../../components/AsyncState'
import { blockerMessage, sortOperations, time } from './presentation'
import styles from './DailyBoard.module.css'

const today = () => new Date().toISOString().slice(0, 10)

export function DailyBoard() {
  const [date, setDate] = useState(today())
  const [project, setProject] = useState('')
  const [center, setCenter] = useState('')
  const [person, setPerson] = useState('')
  const [status, setStatus] = useState('')
  const query = useQuery({ queryKey: ['daily-board', date], queryFn: () => api.day(date) })
  const all = useMemo(() => sortOperations(query.data?.operations ?? []), [query.data])
  const filtered = all.filter(x => (!project || x.project_id === project) && (!center || x.work_center === center)
    && (!person || (x.people ?? []).some(p => p.id === person)) && (!status || x.operational_status === status))
  if (query.isPending) return <Loading label="Cargando producción…" />
  if (query.isError) return <ErrorState retry={() => void query.refetch()} />
  const count = (value: string) => all.filter(x => x.operational_status === value).length
  const projects = [...new Map(all.map(x => [x.project_id, x.project_name])).entries()]
  const centers = [...new Set(all.map(x => x.work_center).filter((x): x is string => Boolean(x)))]
  const people = [...new Map(all.flatMap(x => x.people ?? []).map(x => [x.id, x.name])).entries()]
  return <main>
    <header className={styles.header}><div><p className="eyebrow">TABLERO DIARIO</p><h1>Producción de hoy</h1><p>{new Intl.DateTimeFormat('es-AR', { dateStyle: 'full', timeZone: 'UTC' }).format(new Date(`${date}T12:00:00Z`))}</p></div><label>Fecha<input type="date" value={date} onChange={e => setDate(e.target.value)} /></label></header>
    <section className={styles.summary} aria-label="Resumen"><strong><span>{all.length}</span> Programadas</strong><strong><span>{count('EN_CURSO')}</span> En curso</strong><strong><span>{count('DEMORADO')}</span> Demoradas</strong><strong><span>{count('BLOQUEADO')}</span> Bloqueadas</strong><strong><span>{count('FINALIZADO')}</span> Finalizadas</strong></section>
    <section className={styles.filters} aria-label="Filtros">
      <label>Proyecto<select aria-label="Proyecto" value={project} onChange={e => setProject(e.target.value)}><option value="">Todos</option>{projects.map(([id,name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>Centro<select aria-label="Centro de trabajo" value={center} onChange={e => setCenter(e.target.value)}><option value="">Todos</option>{centers.map(x => <option key={x!}>{x}</option>)}</select></label>
      <label>Persona<select aria-label="Persona" value={person} onChange={e => setPerson(e.target.value)}><option value="">Todas</option>{people.map(([id,name]) => <option key={id} value={id}>{name}</option>)}</select></label>
      <label>Estado<select aria-label="Estado" value={status} onChange={e => setStatus(e.target.value)}><option value="">Todos</option>{Object.keys({ EN_CURSO:1,DEMORADO:1,BLOQUEADO:1,LISTO:1,PENDIENTE:1,FINALIZADO:1 }).map(x => <option key={x}>{x.replace('_',' ')}</option>)}</select></label>
    </section>
    {filtered.length === 0 ? <div className="state">No hay operaciones programadas para esta fecha.</div> : <div className={styles.tableWrap}><table><caption className="srOnly">Operaciones programadas</caption><thead><tr><th>Proyecto</th><th>Operación</th><th>Estado</th><th>Horario</th><th>Personas</th><th>Recurso</th><th>Prioridad</th></tr></thead><tbody>{filtered.map(op => <tr key={op.operation_id}><td data-label="Proyecto"><strong>{op.project_name}</strong><small>{op.lot_name}</small></td><td data-label="Operación"><Link to={`/operations/${op.operation_id}`}>{op.operation_name}</Link><small>{op.phase_name}</small>{blockerMessage(op.blocker_code) && <em>{blockerMessage(op.blocker_code)}</em>}</td><td data-label="Estado"><span className={`status status-${op.operational_status.toLowerCase()}`}>{op.operational_status.replace('_',' ')}</span></td><td data-label="Horario">{time(op.planned_start)}–{time(op.planned_finish)}</td><td data-label="Personas">{(op.people ?? []).map(p => p.name).join(', ') || 'Sin asignar'}</td><td data-label="Recurso">{op.physical_resource ?? op.work_center ?? 'Sin asignar'}</td><td data-label="Prioridad">{op.priority}</td></tr>)}</tbody></table></div>}
  </main>
}
