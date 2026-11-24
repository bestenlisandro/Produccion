import {useState} from 'react'
import {useQuery, useQueryClient} from '@tanstack/react-query'
import moment from 'moment-timezone'
import {Link} from 'react-router'
import {request} from '../../api/client'
import type {components} from '../../api/schema'
import {useCommand} from '../../api/useCommand'
import styles from './OperationDetail.module.css'
import {ReplanPanel} from '../replanning/ReplanPanel'

type Detail = components['schemas']['OperationExecutionResponse']

export function OperationExecution({operationId, onSaved, needsReview, realitySaved}:{operationId:string; onSaved:()=>void; needsReview:boolean; realitySaved:boolean}) {
  const qc = useQueryClient()
  const query = useQuery({queryKey:['operation-execution', operationId], queryFn:()=>request<Detail>(`/operations/${operationId}/execution`)})
  const refresh = async () => {
    onSaved()
    await Promise.all(['operation-execution', 'operation', 'daily-board', 'current-plan', 'resource-occupancy', 'installations'].map(key=>qc.invalidateQueries({queryKey:[key]})))
  }
  if (query.isPending) return <section role="status">Cargando ejecución…</section>
  if (query.isError) return <section role="alert">No pudimos cargar la ejecución.<button onClick={()=>void query.refetch()}>REINTENTAR EJECUCIÓN</button></section>
  const d = query.data
  const phase = d.phases.find(p=>!p.completed)
  const version = `${d.execution_id}:${phase?.id}:${phase?.started}:${d.segments.map(s=>s.id).join(',')}:${d.remaining_revision_no}:${d.execution_status}`
  return <section className={styles.update}><h2>Ejecución de producción</h2>
    <p>Horarios de {d.timezone}. Registrá cada tramo continuo por separado, sin incluir pausas.</p>
    {d.blockers.map(message=><p role="alert" key={message}>{message}</p>)}
    <ExecutionForm key={version} detail={d} operationId={operationId} refresh={refresh}/>
    <h3>Tramos registrados</h3>
    {!d.segments.length ? <p>Todavía no hay tramos registrados.</p> : <div className={styles.history}><table><thead><tr><th>Fase</th><th>Inicio</th><th>Fin</th><th>Trabajo</th><th>Personas</th><th>Recursos</th></tr></thead><tbody>{d.segments.map(s=><tr key={s.id}>
      <td>{s.phase_name}</td><td>{moment(s.started_at).tz(d.timezone).format('DD/MM/YYYY HH:mm')}</td><td>{moment(s.ended_at).tz(d.timezone).format('DD/MM/YYYY HH:mm')}</td><td>{s.work_minutes} min</td>
      <td>{s.people.map(p=>`${p.name} (${p.minutes} min)`).join(', ')||'—'}</td><td>{s.resources.map(r=>`${r.name} (${r.minutes} min)`).join(', ')||'—'}</td>
    </tr>)}</tbody></table></div>}
    <p><Link to="/planning/gantt">VER GANTT</Link> · <Link to="/planning/resource-occupancy">VER OCUPACIÓN</Link></p>
    {d.can_execute&&needsReview&&<ReplanPanel operationId={operationId} realitySaved={realitySaved} zone={d.timezone} notBefore={d.segments.at(-1)?.ended_at??d.started_at??undefined}/>}
  </section>
}

function ExecutionForm({detail:d, operationId, refresh}:{detail:Detail; operationId:string; refresh:()=>Promise<void>}) {
  const phase = d.phases.find(p=>!p.completed)
  const latestEnd = d.segments.at(-1)?.ended_at
  const format = (value?:string|null)=>moment(value??undefined).tz(d.timezone).format('YYYY-MM-DDTHH:mm')
  const [start, setStart] = useState(()=>format(latestEnd??d.started_at))
  const [end, setEnd] = useState(()=>format(latestEnd??d.started_at))
  const [people, setPeople] = useState<string[]>([])
  const [resources, setResources] = useState<string[]>([])
  const [remaining, setRemaining] = useState(d.remaining_minutes??phase?.original_estimate_minutes??0)
  const [confirmFinish, setConfirmFinish] = useState(false)
  const c = useCommand(refresh)
  const iso = (value:string)=>moment.tz(value,d.timezone).toISOString()
  const duration = moment(iso(end)).diff(moment(iso(start)), 'minutes')
  const validTime = !!start && !!end && duration>0
  const validRemaining = Number.isInteger(remaining) && remaining>=0
  const busy = c.isPending || c.uncertain
  const toggle = (values:string[], id:string)=>values.includes(id)?values.filter(value=>value!==id):[...values,id]
  if (d.execution_status==='completed' || !phase) return <p className="success">Operación finalizada. Se conserva su historial de ejecución.</p>
  if (!d.can_execute) return null
  return <><p><strong>Fase actual: {phase.name}</strong> · Equipo mínimo: {phase.required_people} · Restante de la operación: {d.remaining_minutes??'—'} min-persona</p>
    <fieldset disabled={busy||d.blockers.length>0}><legend>Registrar avance</legend>
      <label>Inicio real / inicio de tramo<input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label>
      {!phase.started ? <button disabled={!start} onClick={()=>c.send(`/operations/${operationId}/start`,{phase_id:phase.id,started_at:iso(start)})}>INICIAR OPERACIÓN / FASE</button> : <>
        <label>Fin del tramo / finalización<input type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label>
        <fieldset><legend>Personas que trabajaron en este tramo</legend>{d.people.map(p=><label className={styles.choice} key={p.id}><input type="checkbox" checked={people.includes(p.id)} onChange={()=>setPeople(toggle(people,p.id))}/>{p.name}</label>)}</fieldset>
        <fieldset><legend>Máquinas y bancos utilizados</legend>{d.resources.map(r=><label className={styles.choice} key={r.id}><input type="checkbox" checked={resources.includes(r.id)} onChange={()=>setResources(toggle(resources,r.id))}/>{r.name}</label>)}</fieldset>
        <p>Se registran los minutos del tramo para cada persona y recurso seleccionado. Se verifican habilitaciones, equipo mínimo y conflictos de uso.</p>
        {!validTime&&<p>El fin del tramo debe ser posterior al inicio.</p>}
        {people.length<phase.required_people&&<p>Seleccioná al menos {phase.required_people} persona(s).</p>}
        {!people.length&&!resources.length&&<p>Seleccioná las personas y los recursos utilizados.</p>}
        <button disabled={!validTime||people.length<phase.required_people||(!people.length&&!resources.length)} onClick={()=>c.send(`/executions/${d.execution_id}/segments`,{phase_id:phase.id,started_at:iso(start),ended_at:iso(end),work_minutes:duration,humans:people.map(id=>({employee_id:id,work_minutes:duration})),physical_usages:resources.map(id=>({physical_resource_id:id,work_minutes:duration,capacity_units:1}))})}>REGISTRAR TRAMO</button>
        <h3>Actualizar tiempo restante</h3><label>Nueva estimación restante (minutos-persona)<input type="number" min="0" step="1" value={remaining} onChange={e=>setRemaining(Number(e.target.value))}/></label>
        <div className={styles.shortcuts}>{[30,60,120].map(value=><button key={value} onClick={()=>setRemaining(remaining+value)}>+{value<60?`${value} min`:`${value/60} h`}</button>)}</div>
        <p>El restante es trabajo pendiente, adicional a lo ya registrado. Se guarda con corte en el horario de fin indicado.</p>
        <button disabled={!validRemaining||!end||!d.remaining_revision_no} onClick={()=>c.send(`/operations/${operationId}/execution/remaining-estimate`,{expected_revision_no:d.remaining_revision_no,cutoff_at:iso(end),input_mode:'remaining_duration',reason:'Avance de producción desde detalle',remaining:[{dimension:'LABOR_WORK',phase_id:phase.id,minutes:remaining}]})}>GUARDAR ESTIMACIÓN</button>
        {!confirmFinish?<button onClick={()=>setConfirmFinish(true)}>FINALIZAR OPERACIÓN / FASE</button>:<div role="group" aria-label="Confirmar finalización"><p>¿Finalizar {phase.name} en el horario de fin indicado? La historia quedará conservada.</p><button disabled={!end} onClick={()=>c.send(`/operations/${operationId}/finish`,{phase_id:phase.id,completed_at:iso(end)})}>CONFIRMAR FINALIZACIÓN</button><button onClick={()=>setConfirmFinish(false)}>SEGUIR EN CURSO</button></div>}
      </>}
    </fieldset>
    {c.error&&<p role="alert">{c.error.message} <button onClick={()=>void refresh()}>ACTUALIZAR DATOS</button></p>}
    {c.uncertain&&<button disabled={c.isPending} onClick={c.retry}>REINTENTAR MISMA ACCIÓN</button>}
  </>
}
