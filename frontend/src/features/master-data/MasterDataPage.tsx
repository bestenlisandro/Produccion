import { cloneElement,useEffect,useId,useMemo,useRef,useState,type FormEvent,type ReactElement,type ReactNode } from 'react'
import { useMutation,useQuery,useQueryClient } from '@tanstack/react-query'
import { api,ApiError,type MasterRecord,type MasterSnapshot } from '../../api/client'
import styles from './MasterDataPage.module.css'

type Section='people'|'skills'|'centers'|'resources'|'calendars'|'plant'|'stages'
type Commit={path:string;method:'POST'|'PATCH'|'PUT'|'DELETE';body?:unknown}
type CommitAction=(command:Commit,onSuccess?:()=>void)=>void
type Intent={command:Commit;key:string;onSuccess?:()=>void}
const sections:[Section,string][]=[['people','Personas'],['skills','Habilidades'],['centers','Centros de trabajo'],['resources','Recursos'],['calendars','Calendarios'],['plant','Planta'],['stages','Etapas productivas']]
const value=(record:MasterRecord|undefined,key:string)=>String(record?.[key]??'')
const numberValue=(record:MasterRecord|undefined,key:string)=>Number(record?.[key]??0)

export function MasterDataPage(){
  const [section,setSection]=useState<Section>('people')
  const [showInactive,setShowInactive]=useState(false)
  const [notice,setNotice]=useState('')
  const [uncertain,setUncertain]=useState(false)
  const intent=useRef<Intent|null>(null)
  const queryClient=useQueryClient()
  const query=useQuery({queryKey:['master-data'],queryFn:api.masterSnapshot})
  const mutation=useMutation({retry:false,mutationFn:(attempt:Intent)=>api.mutateMaster(attempt.command.path,attempt.command.method,attempt.command.body,attempt.key),onSuccess:(result,attempt)=>{
    intent.current=null
    setUncertain(false)
    attempt.onSuccess?.()
    setNotice(result.plan_requires_reconciliation?'Guardado. PLAN_REQUIRES_RECONCILIATION: el programa vigente no fue modificado.':'Cambios guardados.')
    void queryClient.invalidateQueries({queryKey:['master-data']})
    void queryClient.invalidateQueries({queryKey:['current-plan']})
  },onError:error=>{
    const unknownOutcome=!(error instanceof ApiError)||error.status>=500
    setUncertain(unknownOutcome)
    if(!unknownOutcome)intent.current=null
  }})
  const commit:CommitAction=(command,onSuccess)=>{
    if(intent.current)return
    setNotice('')
    // Keep an immutable copy of the submitted intention until its result is known.
    const attempt={command:structuredClone(command),key:crypto.randomUUID(),onSuccess}
    intent.current=attempt
    mutation.mutate(attempt)
  }
  if(query.isPending)return <main><Async title="Cargando configuración…"/></main>
  if(query.isError)return <main><Async title="No pudimos cargar la configuración" detail={query.error.message}><button onClick={()=>query.refetch()}>REINTENTAR</button></Async></main>
  const data=query.data
  return <main>
    <p className="eyebrow">CONFIGURACIÓN · DEV ONLY</p><h1>Maestros operativos</h1>
    <p className={styles.dev}>Contexto local de desarrollo. Autenticación y autorización productivas: BLOCKER FOR PRODUCTION.</p>
    <nav className={styles.tabs} aria-label="Secciones de configuración">{sections.map(([id,label])=><button key={id} className={section===id?styles.active:'secondary'} aria-pressed={section===id} onClick={()=>setSection(id)}>{label}</button>)}</nav>
    {section!=='plant'&&<label className={styles.filter}><input type="checkbox" checked={showInactive} onChange={event=>setShowInactive(event.target.checked)}/> Mostrar inactivos</label>}
    {notice&&<p className={notice.includes('RECONCILIATION')?'warning':'success'} role="status">{notice}</p>}
    {mutation.error&&<p className="warning" role="alert">{mutation.error instanceof ApiError?mutation.error.message:'No se pudo guardar el cambio.'}</p>}
    {uncertain&&<div role="status"><p>No pudimos confirmar el resultado. Reintentá el mismo guardado antes de iniciar otro.</p><button disabled={mutation.isPending} onClick={()=>{if(intent.current)mutation.mutate(intent.current)}}>REINTENTAR GUARDADO</button></div>}
    {section==='people'&&<People data={data} showInactive={showInactive} commit={commit} busy={mutation.isPending||uncertain}/>}
    {section==='skills'&&<Skills data={data} showInactive={showInactive} commit={commit} busy={mutation.isPending||uncertain}/>}
    {section==='centers'&&<Centers data={data} showInactive={showInactive} commit={commit} busy={mutation.isPending||uncertain}/>}
    {section==='resources'&&<Resources data={data} showInactive={showInactive} commit={commit} busy={mutation.isPending||uncertain}/>}
    {section==='calendars'&&<Calendars data={data} showInactive={showInactive} commit={commit} busy={mutation.isPending||uncertain}/>}
    {section==='stages'&&<Stages data={data} showInactive={showInactive} commit={commit} busy={mutation.isPending||uncertain}/>}
    {section==='plant'&&<Plant data={data} commit={commit} busy={mutation.isPending||uncertain}/>}
  </main>
}

function Async({title,detail,children}:{title:string;detail?:string;children?:ReactNode}){return <section className="state" role={detail?'alert':'status'}><h1>{title}</h1>{detail&&<p>{detail}</p>}{children}</section>}
function visible(records:MasterRecord[],showInactive:boolean){return records.filter(record=>showInactive||record.status!=='inactive')}
function statusAction(kind:string,record:MasterRecord,path:string,commit:CommitAction){
  const activating=record.status==='inactive'
  const usage=numberValue(record,'current_usage_count')
  if(!activating&&usage>0&&!window.confirm(`Este ${kind} participa en ${usage} operaciones del programa vigente. CURRENT no será modificado. ¿Desactivar de todas formas?`))return
  commit({path:`${path}/${record.id}/status`,method:'POST',body:{status:activating?'active':'inactive',expected_row_version:record.row_version}})
}
function Empty({label}:{label:string}){return <p className={styles.empty}>No hay {label} para mostrar.</p>}

function People({data,showInactive,commit,busy}:{data:MasterSnapshot;showInactive:boolean;commit:CommitAction;busy:boolean}){
  const [editing,setEditing]=useState<MasterRecord>()
  const people=visible(data.people,showInactive)
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);const body={code:form.get('code'),display_name:form.get('name'),base_calendar_id:form.get('calendar'),default_work_center_id:form.get('center')||null};commit({path:editing?`/people/${editing.id}`:'/people',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{if(element.isConnected){element.reset();setEditing(undefined)}})}
  return <Section title="Personas" intro="Una persona de producción no es una cuenta de usuario.">
    <MasterForm key={editing?.id??"new"} title={editing?'Editar persona':'Crear persona'} onSubmit={submit} busy={busy} onCancel={()=>setEditing(undefined)}>
      <Field label="Código"><input name="code" required defaultValue={value(editing,'code')}/></Field><Field label="Nombre visible"><input name="name" required defaultValue={value(editing,'display_name')}/></Field>
      <Field label="Calendario"><select name="calendar" required defaultValue={value(editing,'base_calendar_id')}><option value="">Seleccionar</option>{data.calendars.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field>
      <Field label="Centro habitual"><select name="center" defaultValue={value(editing,'default_work_center_id')}><option value="">Sin centro fijo</option>{data.work_centers.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field>
    </MasterForm>
    {people.length===0?<Empty label="personas"/>:<div className={styles.cards}>{people.map(person=><article className={styles.card} key={person.id}><header><h2>{value(person,'display_name')}</h2><span className="status">{value(person,'status')}</span></header><p>{value(person,'code')} · {value(person,'calendar_name')}</p><p>Centro: {value(person,'work_center_name')||'sin centro fijo'}</p><div className={styles.chips}>{data.skills.filter(skill=>skill.status==='active').map(skill=>{const assigned=(person.skills as MasterRecord[]??[]).some(item=>item.id===skill.id);return <label key={skill.id}><input type="checkbox" disabled={busy} checked={assigned} onChange={()=>commit({path:`/people/${person.id}/skills/${skill.id}`,method:assigned?'DELETE':'PUT',body:assigned?undefined:{}})}/>{value(skill,'name')}</label>})}</div><div className="actions"><button className="secondary" disabled={busy} onClick={()=>setEditing(person)}>EDITAR</button><button disabled={busy} onClick={()=>statusAction('persona',person,'/people',commit)}>{person.status==='inactive'?'REACTIVAR':'DESACTIVAR'}</button></div></article>)}</div>}
  </Section>
}

function Skills({data,showInactive,commit,busy}:{data:MasterSnapshot;showInactive:boolean;commit:CommitAction;busy:boolean}){
  const [editing,setEditing]=useState<MasterRecord>();const skills=visible(data.skills,showInactive)
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);const body={code:form.get('code'),name:form.get('name'),description:form.get('description')||null,category:form.get('category')||null};commit({path:editing?`/skills/${editing.id}`:'/skills',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{if(element.isConnected){element.reset();setEditing(undefined)}})}
  return <Section title="Habilidades" intro="Defina capacidades operativas y consulte rápidamente quién está habilitado."><MasterForm key={editing?.id??"new"} title={editing?'Editar habilidad':'Crear habilidad'} onSubmit={submit} busy={busy} onCancel={()=>setEditing(undefined)}><Field label="Código"><input name="code" required defaultValue={value(editing,'code')}/></Field><Field label="Nombre"><input name="name" required defaultValue={value(editing,'name')}/></Field><Field label="Categoría"><input name="category" defaultValue={value(editing,'category')}/></Field><Field label="Descripción"><input name="description" defaultValue={value(editing,'description')}/></Field></MasterForm>{skills.length===0?<Empty label="habilidades"/>:<div className={styles.cards}>{skills.map(skill=><article className={styles.card} key={skill.id}><header><h2>{value(skill,'name')}</h2><span className="status">{value(skill,'status')}</span></header><p>{value(skill,'code')} · {numberValue(skill,'people_count')} personas</p><p>{value(skill,'description')||'Sin descripción'}</p><div className="actions"><button className="secondary" disabled={busy} onClick={()=>setEditing(skill)}>EDITAR</button><button disabled={busy} onClick={()=>statusAction('skill',skill,'/skills',commit)}>{skill.status==='inactive'?'REACTIVAR':'DESACTIVAR'}</button></div></article>)}</div>}</Section>
}

function Centers({data,showInactive,commit,busy}:{data:MasterSnapshot;showInactive:boolean;commit:CommitAction;busy:boolean}){
  const [editing,setEditing]=useState<MasterRecord>();const centers=visible(data.work_centers,showInactive)
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);const mode=String(form.get('mode'));const body={code:form.get('code'),name:form.get('name'),capacity_mode:mode,aggregate_capacity:mode==='cumulative'?Number(form.get('capacity')):null,capacity_unit:form.get('unit')||null,base_calendar_id:form.get('calendar')||null};commit({path:editing?`/work-centers/${editing.id}`:'/work-centers',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{if(element.isConnected){element.reset();setEditing(undefined)}})}
  return <Section title="Centros de trabajo" intro="La capacidad nominal del centro es independiente de la cantidad de personas."><MasterForm key={editing?.id??"new"} title={editing?'Editar centro':'Crear centro'} onSubmit={submit} busy={busy} onCancel={()=>setEditing(undefined)}><Field label="Código"><input name="code" required defaultValue={value(editing,'code')}/></Field><Field label="Nombre"><input name="name" required defaultValue={value(editing,'name')}/></Field><Field label="Modo"><select name="mode" defaultValue={value(editing,'capacity_mode')||'cumulative'}><option value="cumulative">Acumulativo</option><option value="exclusive">Exclusivo</option></select></Field><Field label="Capacidad nominal"><input name="capacity" type="number" min="0.0001" step="any" defaultValue={value(editing,'aggregate_capacity')||'1'}/></Field><Field label="Unidad"><input name="unit" defaultValue={value(editing,'capacity_unit')||'unidad'}/></Field><Field label="Calendario"><select name="calendar" defaultValue={value(editing,'base_calendar_id')}><option value="">Heredar planta</option>{data.calendars.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field></MasterForm>{centers.length===0?<Empty label="centros"/>:<div className={styles.cards}>{centers.map(center=><article className={styles.card} key={center.id}><header><h2>{value(center,'name')}</h2><span className="status">{value(center,'status')}</span></header><p>{value(center,'code')} · Capacidad {value(center,'aggregate_capacity')||'exclusiva'} {value(center,'capacity_unit')}</p><p>{numberValue(center,'resource_count')} recursos · {value(center,'calendar_name')||'calendario de planta'}</p><div className="actions"><button className="secondary" disabled={busy} onClick={()=>setEditing(center)}>EDITAR</button><button disabled={busy} onClick={()=>statusAction('centro',center,'/work-centers',commit)}>{center.status==='inactive'?'REACTIVAR':'DESACTIVAR'}</button></div></article>)}</div>}</Section>
}

function Resources({data,showInactive,commit,busy}:{data:MasterSnapshot;showInactive:boolean;commit:CommitAction;busy:boolean}){
  const [editing,setEditing]=useState<MasterRecord>();const resources=visible(data.resources,showInactive)
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);const body={code:form.get('code'),name:form.get('name'),work_center_id:form.get('center'),resource_type_id:form.get('type'),scheduling_mode:form.get('mode'),capacity_units:Number(form.get('capacity')),capacity_unit:form.get('unit')||null,is_mobile:form.get('mobile')==='on',base_calendar_id:form.get('calendar')};commit({path:editing?`/resources/${editing.id}`:'/resources',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{if(element.isConnected){element.reset();setEditing(undefined)}})}
  return <Section title="Recursos físicos" intro="Máquinas, bancos y equipos conservan su historia al desactivarse."><MasterForm key={editing?.id??"new"} title={editing?'Editar recurso':'Crear recurso'} onSubmit={submit} busy={busy} onCancel={()=>setEditing(undefined)}><Field label="Código"><input name="code" required defaultValue={value(editing,'code')}/></Field><Field label="Nombre"><input name="name" required defaultValue={value(editing,'name')}/></Field><Field label="Centro"><select name="center" required defaultValue={value(editing,'work_center_id')}><option value="">Seleccionar</option>{data.work_centers.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field><Field label="Tipo"><select name="type" required defaultValue={value(editing,'resource_type_id')}><option value="">Seleccionar</option>{data.resource_types.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field><Field label="Modo"><select name="mode" defaultValue={value(editing,'scheduling_mode')||'exclusive'}><option value="exclusive">Exclusivo</option><option value="cumulative">Acumulativo</option></select></Field><Field label="Capacidad"><input name="capacity" type="number" min="0.0001" step="0.1" required defaultValue={value(editing,'capacity_units')||'1'}/></Field><Field label="Unidad"><input name="unit" defaultValue={value(editing,'capacity_unit')||'unidad'}/></Field><Field label="Calendario"><select name="calendar" required defaultValue={value(editing,'base_calendar_id')}><option value="">Seleccionar</option>{data.calendars.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field><Field label="Recurso móvil"><input name="mobile" type="checkbox" defaultChecked={Boolean(editing?.is_mobile)}/></Field></MasterForm>{resources.length===0?<Empty label="recursos"/>:<div className={styles.cards}>{resources.map(resource=><article className={styles.card} key={resource.id}><header><h2>{value(resource,'name')}</h2><span className="status">{value(resource,'status')}</span></header><p>{value(resource,'resource_type_name')} · {value(resource,'work_center_name')}</p><p>{value(resource,'scheduling_mode')} · capacidad {value(resource,'capacity_units')} {value(resource,'capacity_unit')}</p><div className="actions"><button className="secondary" disabled={busy} onClick={()=>setEditing(resource)}>EDITAR</button><button disabled={busy} onClick={()=>statusAction('recurso',resource,'/resources',commit)}>{resource.status==='inactive'?'REACTIVAR':'DESACTIVAR'}</button></div></article>)}</div>}</Section>
}

type WindowDraft={weekday:number;local_start:string;local_end:string;capacity_factor:number}
export function localDate(timezone:string,instant=new Date()):string {
  const parts=new Intl.DateTimeFormat('en-US',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(instant)
  const part=(kind:string)=>parts.find(item=>item.type===kind)!.value
  return `${part('year')}-${part('month')}-${part('day')}`
}
export function windowsAt(records:MasterRecord[],calendarId:string,date:string){
  return records.filter(item=>item.calendar_id===calendarId&&(!item.valid_from||String(item.valid_from)<=date)&&(!item.valid_to||date<String(item.valid_to)))
}
function Calendars({data,showInactive,commit,busy}:{data:MasterSnapshot;showInactive:boolean;commit:CommitAction;busy:boolean}){
  const calendars=visible(data.calendars,showInactive);const [editing,setEditing]=useState<MasterRecord>()
  const [selected,setSelected]=useState(calendars[0]?.id??'');const calendar=data.calendars.find(item=>item.id===selected)
  const [effectiveFrom,setEffectiveFrom]=useState(()=>localDate(value(calendar,'timezone')||value(data.plant,'timezone')))
  const sourceWindows=useMemo(()=>windowsAt(data.calendar_windows,selected,effectiveFrom).map(item=>({weekday:Number(item.weekday),local_start:String(item.local_start).slice(0,5),local_end:String(item.local_end).slice(0,5),capacity_factor:Number(item.capacity_factor)})),[data.calendar_windows,selected,effectiveFrom])
  const [windows,setWindows]=useState<WindowDraft[]>(sourceWindows)
  useEffect(()=>setWindows(sourceWindows),[sourceWindows])
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);const body={code:form.get('code'),name:form.get('name'),timezone:form.get('timezone'),calendar_kind:form.get('kind'),description:form.get('description')||null};commit({path:editing?`/calendars/${editing.id}`:'/calendars',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{if(element.isConnected){element.reset();setEditing(undefined)}})}
  return <Section title="Calendarios" intro="Horarios locales interpretados con timezone IANA; no se convierten timestamps históricos."><MasterForm key={editing?.id??"new"} title={editing?'Editar calendario':'Crear calendario'} onSubmit={submit} busy={busy} onCancel={()=>setEditing(undefined)}><Field label="Código"><input name="code" required defaultValue={value(editing,'code')}/></Field><Field label="Nombre"><input name="name" required defaultValue={value(editing,'name')}/></Field><Field label="Timezone IANA"><input name="timezone" required placeholder="America/Argentina/Buenos_Aires" defaultValue={value(editing,'timezone')||'America/Argentina/Buenos_Aires'}/></Field><Field label="Tipo"><input name="kind" required defaultValue={value(editing,'calendar_kind')||'production'}/></Field><Field label="Descripción del calendario"><input name="description" defaultValue={value(editing,'description')}/></Field></MasterForm>
    {calendars.length===0?<Empty label="calendarios"/>:<div className={styles.cards}>{calendars.map(item=><article className={styles.card} key={item.id}><header><h2>{value(item,'name')}</h2><span className="status">{value(item,'status')}</span></header><p>{value(item,'timezone')} · {value(item,'calendar_kind')}</p><div className="actions"><button className="secondary" disabled={busy} onClick={()=>{setEditing(item);setSelected(item.id);setEffectiveFrom(localDate(value(item,'timezone')))}}>EDITAR</button><button className="secondary" disabled={busy} onClick={()=>statusAction('calendario',item,'/calendars',commit)}>{item.status==='inactive'?'REACTIVAR':'DESACTIVAR'}</button></div></article>)}</div>}
    {calendar&&<section className={styles.editor} aria-label="Editor semanal"><h2>Editor semanal · {value(calendar,'name')}</h2><label>Calendario<select value={selected} disabled={busy} onChange={event=>{setSelected(event.target.value);const next=data.calendars.find(item=>item.id===event.target.value);setEffectiveFrom(localDate(value(next,'timezone')||value(data.plant,'timezone')))}}>{calendars.map(item=><option key={item.id} value={item.id}>{value(item,'name')}</option>)}</select></label><label>Vigente desde<input type="date" required value={effectiveFrom} disabled={busy} onChange={event=>setEffectiveFrom(event.target.value)}/></label><div className={styles.windows}>{windows.map((window,index)=><div key={`${window.weekday}-${index}`}><select aria-label={`Día ${index+1}`} value={window.weekday} onChange={event=>setWindows(current=>current.map((item,i)=>i===index?{...item,weekday:Number(event.target.value)}:item))}>{['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'].map((day,i)=><option key={day} value={i+1}>{day}</option>)}</select><input aria-label={`Inicio ${index+1}`} type="time" value={window.local_start} onChange={event=>setWindows(current=>current.map((item,i)=>i===index?{...item,local_start:event.target.value}:item))}/><span>→</span><input aria-label={`Fin ${index+1}`} type="time" value={window.local_end} onChange={event=>setWindows(current=>current.map((item,i)=>i===index?{...item,local_end:event.target.value}:item))}/><button className="secondary" onClick={()=>setWindows(current=>current.filter((_,i)=>i!==index))}>QUITAR</button></div>)}</div><div className="actions"><button className="secondary" onClick={()=>setWindows(current=>[...current,{weekday:1,local_start:'08:30',local_end:'16:00',capacity_factor:1}])}>AGREGAR VENTANA</button><button disabled={busy||!effectiveFrom} onClick={()=>commit({path:`/calendars/${calendar.id}/windows`,method:'PUT',body:{expected_row_version:calendar.row_version,effective_from:effectiveFrom,windows}})}>GUARDAR JORNADA</button></div>
      <ExceptionEditor key={selected} calendar={calendar} calendars={data.calendars} records={data.calendar_exceptions.filter(item=>item.calendar_id===selected)} commit={commit} busy={busy}/>

    </section>}
  </Section>
}

function exceptionTime(record:MasterRecord|undefined,key:string,timezone:string){
  const timestamp=value(record,key)
  return timestamp?new Intl.DateTimeFormat('en-GB',{timeZone:timezone,hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(timestamp)):''
}

function ExceptionEditor({calendar,calendars,records,commit,busy}:{calendar:MasterRecord;calendars:MasterRecord[];records:MasterRecord[];commit:CommitAction;busy:boolean}){
  const [editing,setEditing]=useState<MasterRecord>()
  const [error,setError]=useState('')
  const submit=(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    const element=event.currentTarget,form=new FormData(element)
    const start=String(form.get('start')||''),end=String(form.get('end')||'')
    if(Boolean(start)!==Boolean(end)||(start&&start>=end)){
      setError('Indicá inicio y fin juntos, con inicio anterior al fin.');return
    }
    setError('')
    const body={calendar_id:form.get('calendar'),exception_date:form.get('date'),effect:form.get('effect'),local_start:start||null,local_end:end||null,capacity_factor:form.get('factor')?Number(form.get('factor')):null,reason:form.get('reason')||null}
    commit({path:editing?`/calendar-exceptions/${editing.id}`:'/calendar-exceptions',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{
      if(element.isConnected){element.reset();setEditing(undefined)}
    })
  }
  return <>
    <form key={editing?.id??'new'} className={styles.exception} onSubmit={submit} aria-label={editing?'Editar excepción':'Agregar excepción'}>
      <h2>{editing?'Editar excepción':'Agregar excepción'}</h2>
      <Field label="Calendario de la excepción"><select name="calendar" required defaultValue={calendar.id} disabled={busy}>{calendars.filter(item=>item.status==='active'||item.id===calendar.id).map(item=><option key={item.id} value={item.id}>{value(item,'name')} · {value(item,'timezone')}</option>)}</select></Field>
      <Field label="Fecha"><input name="date" type="date" required defaultValue={value(editing,'exception_date')}/></Field>
      <Field label="Efecto"><select name="effect" defaultValue={value(editing,'effect')||'remove'}><option value="remove">No laborable</option><option value="replace">Horario reducido</option><option value="add">Disponibilidad extraordinaria</option></select></Field>
      <Field label="Desde"><input name="start" type="time" defaultValue={exceptionTime(editing,'start_at',value(calendar,'timezone'))}/></Field>
      <Field label="Hasta"><input name="end" type="time" defaultValue={exceptionTime(editing,'end_at',value(calendar,'timezone'))}/></Field>
      <Field label="Factor de capacidad de la excepción"><input name="factor" type="number" min="0.000001" step="any" defaultValue={value(editing,'capacity_factor')}/></Field>
      <Field label="Descripción de la excepción"><input name="reason" defaultValue={value(editing,'reason')}/></Field>
      {error&&<p role="alert">{error}</p>}
      <button disabled={busy}>{editing?'GUARDAR EXCEPCIÓN':'AGREGAR EXCEPCIÓN'}</button>
      {editing&&<button type="button" className="secondary" disabled={busy} onClick={()=>{setEditing(undefined);setError('')}}>CANCELAR EXCEPCIÓN</button>}
    </form>
    <ul>{records.map(item=><li key={item.id}>{value(item,'exception_date')} · {exceptionLabel(value(item,'effect'))} · {value(item,'reason')||'Sin descripción'} <button className="secondary" disabled={busy} onClick={()=>{setEditing(item);setError('')}}>EDITAR EXCEPCIÓN</button></li>)}</ul>
  </>
}

function Plant({data,commit,busy}:{data:MasterSnapshot;commit:CommitAction;busy:boolean}){
  const plant=data.plant
  const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget;const form=new FormData(element);if(value(plant,'timezone')!==form.get('timezone')&&!window.confirm('Cambiar el timezone afecta la interpretación futura de calendarios. Los timestamps históricos no serán convertidos. ¿Continuar?'))return;commit({path:'/plant',method:'PATCH',body:{code:form.get('code'),name:form.get('name'),timezone:form.get('timezone'),base_calendar_id:form.get('calendar'),communication_threshold_business_days:Number(form.get('threshold')),expected_row_version:plant.row_version}})}
  return <Section title="Planta" intro="Sólo configuración operativa segura. IDs, organización y revisiones internas no son editables."><form className={styles.form} onSubmit={submit}><Field label="Código"><input name="code" required defaultValue={value(plant,'code')}/></Field><Field label="Nombre"><input name="name" required defaultValue={value(plant,'name')}/></Field><Field label="Timezone IANA"><input name="timezone" required defaultValue={value(plant,'timezone')}/></Field><Field label="Calendario base"><select name="calendar" required defaultValue={value(plant,'base_calendar_id')}>{data.calendars.filter(c=>c.status==='active').map(c=><option key={c.id} value={c.id}>{value(c,'name')}</option>)}</select></Field><Field label="Umbral de comunicación (días hábiles)"><input name="threshold" type="number" min="0" max="365" defaultValue={value(plant,'communication_threshold_business_days')}/></Field><div className="actions"><button disabled={busy}>GUARDAR</button></div></form></Section>
}

function Section({title,intro,children}:{title:string;intro:string;children:ReactNode}){return <section className={styles.section}><header><h2>{title}</h2><p>{intro}</p></header>{children}</section>}
function Field({label,children}:{label:string;children:ReactElement<{id?:string}>}){
  const id=useId()
  return <div className={styles.field}><label htmlFor={id}>{label}</label>{cloneElement(children,{id})}</div>
}
function MasterForm({title,onSubmit,busy,onCancel,children}:{title:string;onSubmit:(e:FormEvent<HTMLFormElement>)=>void;busy:boolean;onCancel:()=>void;children:ReactNode}){return <form key={title} className={styles.form} onSubmit={onSubmit}><h2>{title}</h2><fieldset disabled={busy} style={{display:'contents'}}>{children}<div className="actions"><button disabled={busy}>GUARDAR</button><button className="secondary" type="button" disabled={busy} onClick={onCancel}>CANCELAR</button></div></fieldset></form>}
function exceptionLabel(effect:string){return effect==='remove'?'No laborable':effect==='replace'?'Horario reemplazado':'Disponibilidad extraordinaria'}


function Stages({data,showInactive,commit,busy}:{data:MasterSnapshot;showInactive:boolean;commit:CommitAction;busy:boolean}){
 const [editing,setEditing]=useState<MasterRecord>()
 const submit=(event:FormEvent<HTMLFormElement>)=>{event.preventDefault();const element=event.currentTarget,form=new FormData(element);const body={code:form.get('code'),name:form.get('name'),display_order:Number(form.get('order'))};commit({path:editing?`/stages/${editing.id}`:'/stages',method:editing?'PATCH':'POST',body:editing?{...body,expected_row_version:editing.row_version}:body},()=>{if(element.isConnected){element.reset();setEditing(undefined)}})}
 return <Section title="Etapas productivas" intro="Clasificación estándar de operaciones. Los requerimientos se definen en las fases; editar el catálogo no modifica revisiones congeladas."><MasterForm key={editing?.id??'new'} title={editing?'Editar etapa':'Crear etapa'} onSubmit={submit} busy={busy} onCancel={()=>setEditing(undefined)}><Field label="Código"><input name="code" required readOnly={Boolean(editing)} defaultValue={value(editing,'code')}/></Field><Field label="Nombre"><input name="name" required defaultValue={value(editing,'name')}/></Field><Field label="Orden"><input name="order" type="number" min="1" max="32767" required defaultValue={value(editing,'display_order')||'10'}/></Field></MasterForm><div className={styles.cards}>{visible(data.stages??[],showInactive).sort((a,b)=>Number(a.display_order)-Number(b.display_order)||String(a.code).localeCompare(String(b.code))).map(stage=><article className={styles.card} key={stage.id}><header><h2>{value(stage,'display_order')}. {value(stage,'name')}</h2><span className="status">{value(stage,'status')}</span></header><p>{value(stage,'code')}</p><div className="actions"><button className="secondary" disabled={busy} onClick={()=>setEditing(stage)}>EDITAR</button><button disabled={busy} onClick={()=>statusAction('etapa',stage,'/stages',commit)}>{stage.status==='inactive'?'REACTIVAR':'DESACTIVAR'}</button></div></article>)}</div></Section>
}
