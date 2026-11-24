import {useState,type FormEvent} from 'react'
import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query'
import {Link} from 'react-router'
import moment from 'moment-timezone'
import {request,ApiError,api} from '../../api/client'
import type {components} from '../../api/schema'
import {ReplanPanel} from '../replanning/ReplanPanel'
import {useCommand} from '../../api/useCommand'
import styles from './Projects.module.css'

type Project=components['schemas']['InstallationProject']
type Installation=components['schemas']['InstallationOperation']
export const installationStates:Record<string,string>={not_ready:'NO LISTA',ready:'LISTA',scheduled:'PROGRAMADA',running:'EN CURSO',finished:'FINALIZADA',blocked:'BLOQUEADA'}
export const siteFields=['installation_site_name','installation_address','installation_locality','installation_contact_name','installation_contact_phone','installation_access_notes'] as const
const labels=['Nombre del lugar','Dirección','Localidad','Contacto en obra','Teléfono de contacto','Indicaciones de acceso']
function date(value:string|null,zone:string){return value?moment(value).tz(zone).format('DD/MM/YYYY HH:mm'):'—'}

export function InstallationSection({projectId}:{projectId:string}){
 const qc=useQueryClient()
 const query=useQuery({queryKey:['installations',projectId],queryFn:()=>request<Project>(`/projects/${projectId}/installations`)})
 const refresh=()=>Promise.all([qc.invalidateQueries({queryKey:['installations']}),qc.invalidateQueries({queryKey:['projects']}),qc.invalidateQueries({queryKey:['daily-board']}),qc.invalidateQueries({queryKey:['operation']}),qc.invalidateQueries({queryKey:['current-plan']})])
 if(query.isPending)return <section role="status">Cargando instalación…</section>
 if(query.isError)return <section role="alert">No pudimos cargar la instalación.<button onClick={()=>void query.refetch()}>REINTENTAR INSTALACIÓN</button></section>
 return <InstallationCard key={query.data.row_version} project={query.data} refresh={refresh}/>
}

function InstallationCard({project:p,refresh}:{project:Project;refresh:()=>void}){
 const command=useCommand(refresh)
 const [site,setSite]=useState(Object.fromEntries(siteFields.map(k=>[k,p[k]??''])))
 const [editing,setEditing]=useState(false)
 const [scenarioId,setScenarioId]=useState<string>()
 const [cutoff,setCutoff]=useState(moment().tz(p.timezone).format('YYYY-MM-DDTHH:mm'))
 const simulation=useMutation({mutationFn:()=>request<components['schemas']['ReplanResponse']>(`/projects/${p.project_id}/installation-plan`,{method:'POST',body:JSON.stringify({cutoff_at:moment.tz(cutoff,p.timezone).toISOString(),horizon_end:moment.tz(cutoff,p.timezone).add(90,'days').toISOString(),reason:'Planificación de instalación'})},crypto.randomUUID()),onSuccess:r=>setScenarioId(r.scenario_id)})
 const scenario=useQuery({queryKey:['scenario',scenarioId],queryFn:()=>api.scenario(scenarioId!),enabled:!!scenarioId})
 const confirm=useMutation({mutationFn:()=>api.accept(scenarioId!,scenario.data!.promotion_lock_version),onSuccess:()=>{setScenarioId(undefined);refresh()}})
 const busy=command.isPending||command.uncertain
 const save=(e:FormEvent)=>{e.preventDefault();command.send(`/projects/${p.project_id}/installation-location`,{...site,expected_row_version:p.row_version},'PATCH')}
 return <section className={`${styles.card} ${styles.installation}`}><h2>Instalación</h2><p>{p.required?'Instalación requerida':'No requiere instalación en la definición congelada.'}</p>
 <p>{p.completed?'PROYECTO FINALIZADO':p.can_complete?'Todas las operaciones finalizaron. Puede cerrarse el proyecto.':'El cierre requiere finalizar todas las operaciones obligatorias.'}</p>
 <p>Compromiso del proyecto: {p.committed_date??'—'} · Inicio deseado del proyecto: {date(p.desired_start_at??null,p.timezone)}</p><h3>Ubicación de instalación</h3>{siteFields.map((k,i)=>p[k]&&<p key={k}>{labels[i]}: {p[k]}</p>)}
 {!editing?<button disabled={p.completed} onClick={()=>setEditing(true)}>EDITAR UBICACIÓN</button>:<form className={styles.form} onSubmit={save}><fieldset disabled={busy} style={{display:'contents'}}>{siteFields.map((k,i)=><label key={k}>{labels[i]}<input maxLength={k==='installation_access_notes'?2000:k==='installation_address'?500:k==='installation_contact_phone'?80:200} value={site[k]} onChange={e=>setSite({...site,[k]:e.target.value})}/></label>)}<button>{command.isPending?'GUARDANDO…':'GUARDAR UBICACIÓN'}</button></fieldset></form>}
 {command.error&&<p role="alert">{command.error instanceof ApiError&&command.error.status===409?'Los datos cambiaron. Actualizá antes de volver a guardar.':command.error.message}<button onClick={refresh}>ACTUALIZAR INSTALACIÓN</button></p>}
 {command.uncertain&&<button disabled={command.isPending} onClick={command.retry}>REINTENTAR MISMA ACCIÓN</button>}
 {p.installations.map(i=><InstallationWork key={`${i.operation_id}:${i.execution_id}:${i.remaining_revision_no}:${i.executed_minutes}:${i.state}`} item={i} zone={p.timezone} refresh={refresh}/>)}
 {p.installations.some(i=>i.state!=='finished')&&<><label>Inicio del horizonte ({p.timezone})<input type="datetime-local" value={cutoff} onChange={e=>setCutoff(e.target.value)}/></label><button disabled={simulation.isPending} onClick={()=>simulation.mutate()}>{simulation.isPending?'GENERANDO…':'SIMULAR PLAN DE INSTALACIÓN'}</button>{simulation.error&&<p role="alert">{simulation.error.message}</p>}{scenario.data&&<div><p>Propuesta: {scenario.data.changed_operations} operaciones afectadas. CURRENT permanece sin cambios.</p><button disabled={confirm.isPending||scenario.data.stale||scenario.data.status!=='ready'} onClick={()=>confirm.mutate()}>{confirm.isPending?'CONFIRMANDO…':'CONFIRMAR PLAN DE INSTALACIÓN'}</button></div>}{confirm.error&&<p role="alert">{confirm.error.message}</p>}</>}
 {p.can_complete&&<button disabled={busy} onClick={()=>{if(window.confirm('¿Cerrar el proyecto con todas sus operaciones finalizadas?'))command.send(`/projects/${p.project_id}/complete`,{expected_row_version:p.row_version})}}>CERRAR PROYECTO</button>}
 <p><Link to="/installations">AGENDA DE INSTALACIONES</Link> · {p.installations.some(i=>i.planned_start)&&<><Link to="/planning/gantt">ABRIR GANTT</Link> · <Link to="/">TABLERO DIARIO</Link></>}</p></section>
}

function InstallationWork({item:i,zone,refresh}:{item:Installation;zone:string;refresh:()=>void}){
 const c=useCommand(refresh)
 const [start,setStart]=useState(moment(i.last_segment_end??i.started_at??undefined).tz(zone).format('YYYY-MM-DDTHH:mm'))
 const [end,setEnd]=useState(moment().tz(zone).format('YYYY-MM-DDTHH:mm'))
 const [remaining,setRemaining]=useState(i.remaining_minutes??i.duration_minutes)
 const [selected,setSelected]=useState<string[]>(i.people.map(p=>p.id))
 const [selectedResources,setSelectedResources]=useState<string[]>((i.resources??[]).map(p=>p.id))
 const iso=(v:string)=>moment.tz(v,zone).toISOString()
 const busy=c.isPending||c.uncertain
 const minutes=Math.max(0,moment(iso(end)).diff(moment(iso(start)),'minutes'))
 return <article aria-label={i.operation_name}><h3>{i.operation_name} · {installationStates[i.state]}</h3><p>Fase: {i.phase_name??'Finalizada'}</p>
 <p>Planificada: {date(i.planned_start,zone)} → {date(i.planned_finish,zone)}</p><p>Equipo requerido: {i.required_people} · Asignado: {i.people.map(p=>p.name).join(', ')||'Sin asignar'}</p><p>Recursos: {(i.resources??[]).map(r=>r.name).join(', ')||'Sin recursos físicos'}</p><p>Duración prevista: {i.duration_minutes} min · Ejecutado: {i.executed_minutes} min · Restante: {i.remaining_minutes??'—'} min</p><p>Inicio real: {date(i.started_at,zone)} · Final real: {date(i.completed_at,zone)}</p>{i.overdue&&<p className="warning">ATRASADA</p>}
 {i.blockers.map(b=><p className="warning" key={b}>{b}</p>)}
 {i.state!=='finished'&&<fieldset disabled={busy}><label>Inicio real / inicio de tramo ({zone})<input type="datetime-local" value={start} onChange={e=>setStart(e.target.value)}/></label>
 {!i.execution_id?<button disabled={!i.ready_to_start} onClick={()=>c.send(`/operations/${i.operation_id}/start`,{phase_id:i.phase_id,started_at:iso(start)})}>INICIAR INSTALACIÓN</button>:<><label>Fin de tramo / finalización ({zone})<input type="datetime-local" value={end} onChange={e=>setEnd(e.target.value)}/></label><p>Equipo que realizó este tramo</p>{i.people.map(p=><label key={p.id}><input type="checkbox" checked={selected.includes(p.id)} onChange={e=>setSelected(e.target.checked?[...selected,p.id]:selected.filter(id=>id!==p.id))}/>{p.name}</label>)}<p>Recursos utilizados</p>{(i.resources??[]).map(r=><label key={r.id}><input type="checkbox" checked={selectedResources.includes(r.id)} onChange={e=>setSelectedResources(e.target.checked?[...selectedResources,r.id]:selectedResources.filter(id=>id!==r.id))}/>{r.name}</label>)}<button disabled={minutes<=0||!selected.length} onClick={()=>c.send(`/executions/${i.execution_id}/segments`,{phase_id:i.phase_id,started_at:iso(start),ended_at:iso(end),work_minutes:minutes,humans:selected.map(id=>({employee_id:id,work_minutes:minutes})),physical_usages:selectedResources.map(id=>({physical_resource_id:id,work_minutes:minutes,capacity_units:1}))})}>REGISTRAR TRAMO / FIN DE JORNADA</button><p>Registrar un tramo conserva la instalación en curso para continuar otro día.</p><label>Tiempo restante (minutos-persona)<input type="number" min="0" value={remaining} onChange={e=>setRemaining(Number(e.target.value))}/></label><button onClick={()=>c.send(`/installations/${i.operation_id}/remaining-estimate`,{expected_revision_no:i.remaining_revision_no,cutoff_at:iso(end),input_mode:'remaining_duration',reason:'Avance de instalación',remaining:[{dimension:'LABOR_WORK',phase_id:i.phase_id,minutes:remaining}]})}>GUARDAR RESTANTE DE INSTALACIÓN</button><button onClick={()=>{if(window.confirm('¿Finalizar esta fase de instalación?'))c.send(`/operations/${i.operation_id}/finish`,{phase_id:i.phase_id,completed_at:iso(end)})}}>FINALIZAR FASE DE INSTALACIÓN</button></>}
 </fieldset>}{c.error&&<p role="alert">{c.error.message}<button onClick={refresh}>ACTUALIZAR INSTALACIÓN</button></p>}{c.uncertain&&<button onClick={c.retry}>REINTENTAR MISMA ACCIÓN</button>}{i.execution_id&&i.state!=='finished'&&<ReplanPanel operationId={i.operation_id} realitySaved={false}/>}</article>
}

export function InstallationsPage(){
 const query=useQuery({queryKey:['installations'],queryFn:()=>request<Project[]>('/installations')})
 const [filter,setFilter]=useState(''),[search,setSearch]=useState('')
 if(query.isPending)return <main role="status">Cargando agenda de instalaciones…</main>
 if(query.isError)return <main role="alert">No pudimos cargar la agenda.<button onClick={()=>void query.refetch()}>REINTENTAR</button></main>
 const rows=query.data.filter(p=>`${p.project_code} ${p.project_name} ${p.customer_name} ${p.installation_address??''}`.toLowerCase().includes(search.toLowerCase())&&(!filter||p.installations.some(i=>filter==='overdue'?i.overdue:filter==='today'?(i.scheduled_dates??[]).includes(moment().tz(p.timezone).format('YYYY-MM-DD')):i.state===filter)))
 return <main><h1>Agenda de instalaciones</h1><label>Buscar proyecto, cliente u obra<input value={search} onChange={e=>setSearch(e.target.value)}/></label><label>Estado de instalación<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="">Todas</option><option value="today">Hoy</option><option value="overdue">Atrasadas</option>{Object.entries(installationStates).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>{!rows.length&&<p>No hay instalaciones que coincidan.</p>}<div className={styles.cards}>{rows.map(p=><section className={styles.card} key={p.project_id}><h2><Link to={`/projects/${p.project_id}`}>{p.project_code} · {p.project_name}</Link></h2><p>{p.customer_name}</p>{siteFields.map((k,i)=>p[k]&&<p key={k}>{labels[i]}: {p[k]}</p>)}{p.installations.map(i=><div key={i.operation_id}><h3>{i.operation_name} · {installationStates[i.state]}</h3><p>{date(i.planned_start,p.timezone)} → {date(i.planned_finish,p.timezone)}</p><p>{i.required_people} persona(s) · {i.duration_minutes} min</p><p>{i.people.map(v=>v.name).join(', ')||'Sin equipo asignado'}</p>{i.overdue&&<p className="warning">ATRASADA</p>}</div>)}</section>)}</div></main>
}
