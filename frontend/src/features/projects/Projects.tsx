import { cloneElement,useId,useRef,useState,type FormEvent,type ReactElement } from 'react'
import { Link,useNavigate,useParams } from 'react-router'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import moment from 'moment-timezone'
import { ApiError } from '../../api/client'
import { projectApi,type Project,type ProjectOptions } from './projectApi'
import styles from './Projects.module.css'

const priorities:Record<string,string>={URGENT:'URGENTE',HIGH:'ALTA',NORMAL:'NORMAL'}
const statuses:Record<string,string>={draft:'Borrador',active:'Activo',inactive:'Suspendido',archived:'Archivado'}
const dateLabel=(value:string|null|undefined)=>value??'—'
type Command={path:string;method:'POST'|'PATCH';body:unknown;key:string}

function useSave(onSuccess:(project:Project)=>void){
  const intent=useRef<Command|null>(null)
  const [uncertain,setUncertain]=useState(false)
  const cache=useQueryClient()
  const mutation=useMutation({retry:false,mutationFn:(command:Command)=>projectApi.save(command.path,command.method,command.body,command.key),
    onSuccess:result=>{intent.current=null;setUncertain(false);void cache.invalidateQueries({queryKey:['projects']});void cache.invalidateQueries({queryKey:['current-plan']});onSuccess('project' in result?result.project:result)},
    onError:error=>{const unknown=!(error instanceof ApiError)||error.status>=500;setUncertain(unknown);if(!unknown)intent.current=null}})
  return {...mutation,uncertain,busy:mutation.isPending||uncertain,
    save:(path:string,method:'POST'|'PATCH',body:unknown)=>{if(intent.current)return;intent.current={path,method,body:structuredClone(body),key:crypto.randomUUID()};mutation.mutate(intent.current)},
    retry:()=>{if(intent.current)mutation.mutate(intent.current)}}
}

type Save=ReturnType<typeof useSave>
function SaveState({save,refresh}:{save:Save;refresh?:()=>void}){
  return <>{save.error&&<div className="warning" role="alert"><p>{save.error instanceof ApiError&&save.error.status===409&&save.error.code==='PROJECT_INTAKE_VERSION_CONFLICT'?'El proyecto cambió desde que lo abriste. Actualizá la información antes de guardar.':save.error.message}</p>{save.error instanceof ApiError&&save.error.status===409&&save.error.code==='PROJECT_INTAKE_VERSION_CONFLICT'&&refresh&&<button type="button" onClick={refresh}>ACTUALIZAR INFORMACIÓN</button>}</div>}
    {save.uncertain&&<div className="warning"><p>No pudimos confirmar el resultado. Reintentá el mismo guardado.</p><button type="button" disabled={save.isPending} onClick={save.retry}>REINTENTAR GUARDADO</button></div>}</>
}

function State({loading,error,retry}:{loading?:boolean;error?:Error|null;retry?:()=>void}){
  return <section className="state" role={error?'alert':'status'}><h1>{loading?'Cargando proyectos…':'No pudimos cargar los proyectos'}</h1>{error&&<><p>{error.message}</p><button onClick={retry}>REINTENTAR</button></>}</section>
}

export function ProjectsPage(){
  const query=useQuery({queryKey:['projects'],queryFn:projectApi.list})
  const [search,setSearch]=useState(''),[status,setStatus]=useState('open'),[priority,setPriority]=useState(''),[customer,setCustomer]=useState(''),[from,setFrom]=useState(''),[to,setTo]=useState('')
  if(query.isPending)return <main><State loading/></main>
  if(query.isError)return <main><State error={query.error} retry={()=>void query.refetch()}/></main>
  const rows=query.data.filter(p=>(status==='open'?['active','draft'].includes(p.status):!status||status===p.status)&&(!priority||p.priority_code===priority)&&(!customer||p.customer_id===customer)&&(!from||!!p.committed_date&&p.committed_date>=from)&&(!to||!!p.committed_date&&p.committed_date<=to)&&`${p.code} ${p.name} ${p.customer_name}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()))
  const customers=[...new Map(query.data.map(p=>[p.customer_id,p.customer_name])).entries()]
  return <main><p className="eyebrow">INGRESO DE TRABAJO</p><div className={styles.intro}><h1>Proyectos / pedidos</h1><Link to="/projects/new">NUEVO PROYECTO</Link></div>
    <p>Datos comerciales y administrativos. La definición productiva se prepara en un paso posterior.</p><p className={styles.dev}>DEV ONLY / BLOCKER FOR PRODUCTION · Autenticación productiva pendiente.</p>
    <section className={styles.filters} aria-label="Filtros de proyectos"><label>Buscar proyecto, código o cliente<input value={search} onChange={e=>setSearch(e.target.value)}/></label>
      <SelectField label="Estado"><select value={status} onChange={e=>setStatus(e.target.value)}><option value="open">Activos y borradores</option><option value="">Todos</option>{Object.entries(statuses).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></SelectField>
      <SelectField label="Prioridad"><select value={priority} onChange={e=>setPriority(e.target.value)}><option value="">Todas</option>{Object.entries(priorities).map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></SelectField>
      <SelectField label="Cliente"><select value={customer} onChange={e=>setCustomer(e.target.value)}><option value="">Todos</option>{customers.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></SelectField>
      <label>Comprometida desde<input type="date" value={from} onChange={e=>setFrom(e.target.value)}/></label><label>Comprometida hasta<input type="date" value={to} onChange={e=>setTo(e.target.value)}/></label></section>
    {rows.length===0?<section className="state">{query.data.length===0?'No hay proyectos cargados.':'No hay proyectos que coincidan con los filtros.'}</section>:<div className={styles.cards}>{rows.map(p=><article className={styles.card} key={p.id}><p className="eyebrow">{p.code}</p><h2><Link to={`/projects/${p.id}`}>{p.name}</Link></h2><p>{p.customer_name}</p><span className={styles.badge}>{priorities[p.priority_code]??p.priority_code}</span><span className={styles.badge}>{statuses[p.status]}</span><p>Comprometida: {dateLabel(p.committed_date)}</p><p>Estimada por planificación: {dateLabel(p.estimated_date)}</p>{p.overdue&&<p className="warning">Fecha comprometida atrasada. La prioridad no se cambia automáticamente.</p>}<p>{p.plannable?'Definición productiva disponible':p.ready_for_definition?'LISTO PARA DEFINIR PRODUCCIÓN':'Datos previos a producción pendientes'}</p></article>)}</div>}
  </main>
}

export function NewProjectPage(){
  const options=useQuery({queryKey:['project-options'],queryFn:projectApi.options})
  const navigate=useNavigate()
  const save=useSave(p=>navigate(`/projects/${p.id}`))
  return <main><Link to="/projects">← Proyectos</Link><h1>Nuevo proyecto</h1>{options.isPending?<State loading/>:options.isError?<State error={options.error} retry={()=>void options.refetch()}/>:<><SaveState save={save}/><ProjectForm options={options.data} busy={save.busy} submit={body=>save.save('/projects','POST',body)} cancel={()=>navigate('/projects')}/></>}</main>
}

function ProjectForm({project,options,busy,submit,cancel}:{project?:Project;options:ProjectOptions;busy:boolean;submit:(body:unknown)=>void;cancel:()=>void}){
  const [name,setName]=useState(project?.name??''),[code,setCode]=useState(project?.code??''),[customer,setCustomer]=useState(project?.customer_id??''),[priority,setPriority]=useState(project?.priority_id??options.priorities.find(p=>p.code==='NORMAL')?.id??''),[committed,setCommitted]=useState(project?.committed_date??''),[notes,setNotes]=useState(project?.description??'')
  const send=(e:FormEvent)=>{e.preventDefault();submit({name:name.trim(),customer_id:customer,priority_id:priority,committed_date:committed||null,description:notes||null,...(project?{expected_row_version:project.row_version}:{code:code.trim()})})}
  const available=options.customers.length>0&&options.priorities.length>0
  return <form className={styles.form} onSubmit={send} aria-label={project?'Editar proyecto':'Alta de proyecto'}><h2>{project?'Editar datos del proyecto':'Datos básicos'}</h2><p>Planta: {options.plant.name}</p>{!available&&<p role="alert">Se necesita un cliente activo y las prioridades configuradas para guardar el proyecto.</p>}<fieldset disabled={busy} style={{display:'contents'}}>
    {!project&&<label>Código del proyecto<input required name="code" value={code} onChange={e=>setCode(e.target.value)}/></label>}<label>Nombre / referencia<input required maxLength={200} name="name" value={name} onChange={e=>setName(e.target.value)}/></label>
    <SelectField label="Cliente"><select required value={customer} onChange={e=>setCustomer(e.target.value)}><option value="">Seleccionar cliente</option>{options.customers.map(c=><option key={c.id} value={c.id}>{c.name}</option>)}</select></SelectField>
    <SelectField label="Prioridad del proyecto"><select required value={priority} onChange={e=>setPriority(e.target.value)}><option value="">Seleccionar prioridad</option>{options.priorities.map(p=><option key={p.id} value={p.id}>{priorities[p.code??'']??p.name}</option>)}</select></SelectField>
    <label>Fecha comprometida<input type="date" value={committed} onChange={e=>setCommitted(e.target.value)}/></label><label className={styles.wide}>Notas<textarea maxLength={4000} value={notes} onChange={e=>setNotes(e.target.value)}/></label>
    <div className={`${styles.wide} actions`}><button disabled={busy||!available||!name.trim()||(!project&&!code.trim())}>GUARDAR</button><button type="button" className="secondary" onClick={cancel}>CANCELAR</button></div></fieldset></form>
}

export function ProjectDetailPage(){
  const {projectId=''}=useParams()
  return <ProjectDetail key={projectId} projectId={projectId}/>
}

function ProjectDetail({projectId}:{projectId:string}){
  const query=useQuery({queryKey:['projects',projectId],queryFn:()=>projectApi.detail(projectId)})
  const options=useQuery({queryKey:['project-options'],queryFn:projectApi.options})
  const [editing,setEditing]=useState(false),[notice,setNotice]=useState('')
  const cache=useQueryClient()
  const save=useSave(p=>{cache.setQueryData(['projects',projectId],p);setEditing(false);setNotice(p.plan_requires_reconciliation?'Guardado. PLAN_REQUIRES_RECONCILIATION: CURRENT permanece sin cambios.':'Cambios guardados.')})
  if(query.isPending)return <main><State loading/></main>
  if(query.isError)return <main><State error={query.error} retry={()=>void query.refetch()}/></main>
  const p=query.data
  const status=(next:string)=>{if(window.confirm(`¿${next==='archived'?'Archivar':'Cambiar el estado de'} ${p.code}? Se conservará su historia.`))save.save(`/projects/${p.id}/status`,'POST',{status:next,expected_row_version:p.row_version})}
  return <main><Link to="/projects">← Proyectos</Link><p className="eyebrow">{p.code}</p><div className={styles.intro}><h1>{p.name}</h1><span className={styles.badge}>{statuses[p.status]}</span></div><SaveState save={save} refresh={()=>{setEditing(false);save.reset();void query.refetch()}}/>{notice&&<p className="success" role="status">{notice}</p>}
    {editing?(options.isPending?<State loading/>:options.isError?<State error={options.error} retry={()=>void options.refetch()}/>:<ProjectForm key={p.id} project={p} options={options.data} busy={save.busy} cancel={()=>setEditing(false)} submit={body=>save.save(`/projects/${p.id}`,'PATCH',body)}/>):<div className={styles.grid}>
      <section className={styles.card}><h2>Resumen</h2><p>Prioridad: {priorities[p.priority_code]??p.priority_code}</p><p>{p.description||'Sin notas.'}</p><p>{p.ready_for_definition?'LISTO PARA DEFINIR PRODUCCIÓN':'Datos previos a producción pendientes'}</p>{p.status!=='archived'&&<button disabled={save.busy} onClick={()=>setEditing(true)}>EDITAR PROYECTO</button>}</section>
      <section className={styles.card}><h2>Cliente / obra</h2><p>{p.customer_name}</p><p>{p.customer_email||'Sin email'}</p><p>{p.customer_phone||'Sin teléfono'}</p><p className={styles.muted}>La ubicación de obra no está disponible en esta versión.</p></section>
      <section className={styles.card}><h2>Fechas</h2><p>Comprometida: {dateLabel(p.committed_date)}</p><p>Estimada por planificación: {dateLabel(p.estimated_date)}</p><p>Comunicada al cliente: {dateLabel(p.communicated_date)}</p>{p.overdue&&<p className="warning">Fecha comprometida atrasada</p>}{p.communication_recommended&&<p className="warning">Comunicación recomendada: desvío superior al umbral de días hábiles.</p>}</section>
      <section className={styles.card}><h2>Medición / replanteo</h2><p className={styles.muted}>Se registran trabajos realizados. La programación de una fecha prevista no está disponible en esta versión.</p>{options.isPending?<State loading/>:options.isError?<State error={options.error} retry={()=>void options.refetch()}/>:(['measurement','replanteo'] as const).map(kind=><MilestoneForm key={`${p.id}:${kind}:${p.row_version}`} project={p} kind={kind} timezone={options.data.timezone} save={save}/>)}</section>
      <section className={styles.card}><h2>Estado</h2><p>{statuses[p.status]}</p><div className="actions">{p.status==='draft'&&<button disabled={save.busy} onClick={()=>status('active')}>ACTIVAR</button>}{p.status==='active'&&<button disabled={save.busy} onClick={()=>status('inactive')}>SUSPENDER</button>}{p.status==='inactive'&&<button disabled={save.busy} onClick={()=>status('active')}>REACTIVAR</button>}{p.status!=='archived'&&<button className="secondary" disabled={save.busy} onClick={()=>status('archived')}>ARCHIVAR PROYECTO</button>}</div><p>Archivar conserva el detalle y la historia. Un proyecto con ejecución en curso no se puede archivar.</p></section>
      <section className={styles.card}><h2>Definición productiva</h2><p>{p.definition_revision_no?'Definición existente':'Todavía no definida'}</p><p>Lotes: {p.lot_count} · Revisión: {p.definition_revision_no??'—'}</p><button disabled>DEFINIR PRODUCCIÓN</button><p>Disponible en la siguiente etapa. Estar listo para definir producción no significa estar listo para planificar.</p></section>
      <section className={styles.card}><h2>Planificación</h2><p>{p.plannable?'Demanda con definición productiva disponible':'Sin trabajo planificable liberado.'}</p>{p.plan_requires_reconciliation&&<p className="warning">PLAN_REQUIRES_RECONCILIATION · El programa vigente no se modificó.</p>}{(p.planned_operation_ids??[]).length>0&&<div className="actions"><Link to="/">ABRIR TABLERO</Link><Link to="/planning/gantt">ABRIR GANTT</Link>{(p.planned_operation_ids??[]).map((id,index)=><Link key={id} to={`/operations/${id}`}>OPERACIÓN {index+1}</Link>)}</div>}</section>
    </div>}
  </main>
}

function MilestoneForm({project,kind,timezone,save}:{project:Project;kind:'measurement'|'replanteo';timezone:string;save:Save}){
  const label=kind==='measurement'?'Medición':'Replanteo',fact=project[kind]
  const [date,setDate]=useState(fact.occurred_at?moment(fact.occurred_at).tz(timezone).format('YYYY-MM-DDTHH:mm'):moment().tz(timezone).format('YYYY-MM-DDTHH:mm'))
  const [notes,setNotes]=useState(fact.notes??'')
  const submit=(e:FormEvent)=>{e.preventDefault();save.save(`/projects/${project.id}/${kind}`,'POST',{expected_row_version:project.row_version,occurred_at:moment.tz(date,timezone).toISOString(),notes:notes||null})}
  return <form onSubmit={submit} aria-label={label}><h3>{label}: {fact.occurred_at?(kind==='measurement'?'REALIZADA':'COMPLETADO'):'PENDIENTE'}</h3><fieldset disabled={save.busy||project.status==='archived'} className={styles.form}><label>Fecha realizada de {label.toLowerCase()}<input required type="datetime-local" value={date} onChange={e=>setDate(e.target.value)}/></label><label>Observación de {label.toLowerCase()}<textarea value={notes} onChange={e=>setNotes(e.target.value)}/></label><button>REGISTRAR {label.toUpperCase()}</button></fieldset></form>
}

function SelectField({label,children}:{label:string;children:ReactElement<{id?:string}>}){
  const id=useId()
  return <div className={styles.field}><label htmlFor={id}>{label}</label>{cloneElement(children,{id})}</div>
}
