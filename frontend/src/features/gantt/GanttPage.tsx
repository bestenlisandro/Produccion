import { useCallback, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link,useSearchParams } from 'react-router'
import moment from 'moment-timezone'
import {
  ApiError, api, type GanttGrouping, type GanttOperation,
} from '../../api/client'
import { ErrorState, Loading } from '../../components/AsyncState'
import { blockerMessage, minutes } from '../daily-board/presentation'
import { GanttTimeline, type GanttIntent } from './GanttTimeline'
import { differenceLabel } from './timelineModel'
import type {DependencyMode,Layers} from './operationalModel'
import {
  formatRange, ganttRange, localDate, moveAnchor, plantDateTime,
  type GanttView,
} from './time'
import styles from './GanttPage.module.css'
import './ganttTokens.css'
import {confirmationBlocker,scenarioLabel} from './scenarioPresentation'

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
  const [groupBy, setGroupBy] = useState<GanttGrouping>('project')
  const [searchParams,setSearchParams]=useSearchParams()
  const scenarioId=searchParams.get('scenario_id')??''
  const setScenarioId=useCallback((id:string)=>{setSearchParams(id?{scenario_id:id}:{},{replace:true})},[setSearchParams])
  const [dependencies,setDependencies]=useState<DependencyMode>('selected')
  const [layers,setLayers]=useState<Layers>({plan:true,execution:true,simulation:true})
  const [changesOnly,setChangesOnly]=useState(false)
  const [fitRange,setFitRange]=useState<{from:string;to:string}>()
  const selectionTrigger=useState(()=>({element:null as Element|null}))[0]
  const [selected, setSelected] = useState<GanttOperation>()
  const [message, setMessage] = useState('')
  const [adjustmentMode, setAdjustmentMode] = useState(false)
  const [intent, setIntent] = useState<(GanttIntent & { commandId: string })>()
  const [formStart, setFormStart] = useState('')
  const [formDuration, setFormDuration] = useState('')
  const [compactInteraction,setCompactInteraction] = useState(
    () => typeof window.matchMedia === 'function'
      && window.matchMedia('(max-width: 700px)').matches,
  )
  useEffect(()=>{if(typeof window.matchMedia!=='function')return;const media=window.matchMedia('(max-width: 700px)');const update=()=>setCompactInteraction(media.matches);media.addEventListener('change',update);return()=>media.removeEventListener('change',update)},[])
  const range = useMemo(() => fitRange??ganttRange(anchor, view, timezone), [anchor, view, timezone,fitRange])
  const query = useQuery({
    queryKey: ['current-plan', 'gantt', range.from, range.to, groupBy, scenarioId || null],
    queryFn: () => api.gantt(range.from, range.to, groupBy, scenarioId || undefined),
    placeholderData: previous => previous,
    refetchInterval: scenarioId ? 30_000 : false,
  })
  useEffect(() => {
    if (!query.data) return
    if(query.data.timezone!==timezone)setTimezone(query.data.timezone)
    const first=query.data.scenario?.scenario_kind==='initial'&&!query.data.plan_version_id?query.data.operations.filter(o=>o.planned_start).map(o=>o.planned_start!).sort()[0]:undefined
    if (!anchorChanged&&first)setAnchor(moment.tz(first,query.data.timezone).format('YYYY-MM-DD'))
    else if(!anchorChanged&&query.data.timezone!==timezone)setAnchor(localDate(query.data.timezone))
  }, [query.data, timezone, anchorChanged])
  const selectOperation = useCallback((operation: GanttOperation) => {selectionTrigger.element=document.activeElement;setSelected(operation)}, [selectionTrigger])
  useEffect(()=>{if(!selected)return;document.getElementById('gantt-operation-detail')?.focus();const close=(event:KeyboardEvent)=>{if(event.key==='Escape'){setSelected(undefined);(selectionTrigger.element as HTMLElement|null)?.focus?.()}};document.addEventListener('keydown',close);return()=>document.removeEventListener('keydown',close)},[selected,selectionTrigger])
  useEffect(()=>{if(query.data)setSelected(previous=>previous?query.data.operations.find(o=>o.operation_id===previous.operation_id):undefined)},[query.data])
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
    onError: error => setMessage(error instanceof ApiError && error.code === 'SCENARIO_EXPIRED'
      ? 'Esta simulación quedó desactualizada porque contiene operaciones planificadas en el pasado. Generá una nueva simulación antes de confirmar el plan.'
      : error instanceof ApiError && error.status === 409
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
  const simulate = useMutation({
    mutationFn: async (value: GanttIntent & { commandId: string }) => {
      const cutoff = new Date().toISOString()
      const horizon = new Date(
        Math.max(Date.parse(value.requestedFinish), Date.now()) + 90 * 86400000,
      ).toISOString()
      if (value.kind === 'resize') {
        return api.resizeActivity(value.operation.operation_id, {
          base_plan_version_id: query.data!.plan_version_id!,
          requested_duration_minutes: value.requestedDurationMinutes,
          cutoff_at: cutoff, horizon_end: horizon,
          phase_id: value.operation.phase_id,
          resize_kind: 'PLANNED_DURATION_HYPOTHESIS',
        }, value.commandId)
      }
      return api.moveActivity(value.operation.operation_id, {
        base_plan_version_id: query.data!.plan_version_id!,
        requested_start: value.requestedStart,
        cutoff_at: cutoff, horizon_end: horizon,
        phase_id: value.operation.phase_id,
        requested_resource_id: value.requestedResourceId,
      }, value.commandId)
    },
    onSuccess: result => {
      setScenarioId(result.scenario_id)
      setIntent(undefined)
      setMessage(result.exact_request_satisfied
        ? 'La posición solicitada es factible. Revisá el impacto antes de confirmar.'
        : 'El motor propuso la primera alternativa factible. Revisá motivos e impacto.')
    },
    onError: error => setMessage(error instanceof ApiError && error.status === 409
      ? error.message
      : 'No se pudo simular el ajuste manual.'),
  })
  const captureIntent = useCallback((value: GanttIntent) => {
    setIntent({ ...value, commandId: crypto.randomUUID() })
    setMessage('')
  }, [])

  if (query.isPending) return <Loading label="Cargando Gantt operativo…" />
  if (query.isError) {
    if (!scenarioId && query.error instanceof ApiError && query.error.status === 404
      && query.error.code === 'RESOURCE_NOT_FOUND') {
      return <main><section className="state" role="status">
        <h1>Todavía no existe un plan vigente.</h1>
        <p>Cargá y liberá un proyecto y generá una simulación para comenzar.</p>
        <Link to="/projects">IR A PROYECTOS</Link>
      </section></main>
    }
    return <ErrorState retry={() => void query.refetch()} />
  }
  const data = query.data
  const initial=data.scenario?.scenario_kind==='initial'&&!data.plan_version_id
  const blocked=confirmationBlocker(data)
  const changeAnchor = (value: string) => { setFitRange(undefined);setAnchorChanged(true); setAnchor(value) }
  const zoom=(value:GanttView)=>{const center=moment.tz((Date.parse(range.from)+Date.parse(range.to))/2,data.timezone).format('YYYY-MM-DD');changeAnchor(center);setView(value)}
  const fit=()=>{const dates=data.operations.flatMap(o=>[o.planned_start,o.planned_finish]).concat((data.scenario?.operations??[]).flatMap(o=>[o.planned_start,o.planned_finish])).filter((v):v is string=>Boolean(v)).map(Date.parse);if(!dates.length)return;const start=moment.tz(Math.min(...dates),data.timezone).startOf('day'),end=moment.tz(Math.max(...dates),data.timezone).add(1,'day').startOf('day');if(end.diff(start,'days')>31){setMessage('El plan supera 31 días. Navegá por períodos para revisar el resto.');return}setAnchorChanged(true);setFitRange({from:start.toISOString(),to:end.toISOString()})}
  const visibleData=changesOnly&&data.scenario&&!initial?{...data,operations:data.operations.filter(o=>data.scenario!.operations?.some(c=>c.operation_id===o.operation_id&&c.difference!=='UNCHANGED'))}:data
  const outside = (data.scenario?.operations ?? []).filter(
    item => item.difference === 'OUT_OF_HORIZON',
  ).length ?? 0

  return <main className={`${styles.page} ganttTheme`}>
    <header className={styles.heading}>
      <div><p className="eyebrow">PLANIFICACIÓN</p><h1>Gantt operativo</h1>
        <p>{initial?'Simulación inicial · SIMULACIÓN · No aceptada':data.plan_version_id?`Plan vigente V${data.plan_version_number}`:'Todavía no existe un plan vigente.'} · {data.plant_name??'Planta'} · {data.timezone} · {adjustmentMode ? 'Modo ajuste DEV/interno' : 'Sólo lectura'}</p></div>
      <div><small>Actualizado: {plantDateTime(data.generated_at,data.timezone)}</small><br/><Link to="/">TABLERO DIARIO</Link></div>
    </header>

    <section className={styles.toolbar} aria-label="Controles del Gantt">
      <fieldset><legend>Interacción</legend>
        <button aria-pressed={!adjustmentMode} className={!adjustmentMode ? '' : 'secondary'} onClick={() => { setAdjustmentMode(false); setIntent(undefined) }}>MODO CONSULTA</button>
        <button disabled={!data.plan_version_id||Boolean(data.scenario)} aria-pressed={adjustmentMode} className={adjustmentMode ? '' : 'secondary'} onClick={() => setAdjustmentMode(true)}>MODO AJUSTE</button>
      </fieldset>
      <div className={styles.navigation}>
        <button className="secondary" onClick={() => changeAnchor(localDate(data.timezone))}>HOY</button>
        <button className="secondary" aria-label="Período anterior" onClick={() => changeAnchor(moveAnchor(anchor, view, -1, data.timezone))}>←</button>
        <strong>{formatRange(data.range_from, data.range_to, data.timezone)}</strong>
        <button className="secondary" aria-label="Período siguiente" onClick={() => changeAnchor(moveAnchor(anchor, view, 1, data.timezone))}>→</button>
        <button className="secondary" disabled={!data.operations.some(o=>o.planned_start)} onClick={fit}>AJUSTAR AL PLAN</button>
        <label>Fecha<input type="date" value={anchor} onChange={event => changeAnchor(event.target.value)} /></label>
      </div>
      <label>Agrupar por<select value={groupBy} onChange={event => setGroupBy(event.target.value as GanttGrouping)}>
        {Object.entries(groupLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </select></label>
      <fieldset><legend>Vista</legend>{([
        ['day', 'Día'], ['week', 'Semana'], ['fortnight', '2 semanas'], ['month','Mes'],
      ] as const).map(([value, label]) => <button key={value} className={view === value ? '' : 'secondary'} aria-pressed={view === value} onClick={() => zoom(value)}>{label}</button>)}</fieldset>
      <label>Comparar con<select value={scenarioId} onChange={event => { setScenarioId(event.target.value); setAdjustmentMode(false);setSelected(undefined);setChangesOnly(false);setMessage('') }}>
        <option value="">Ninguno</option>
        {[...data.available_scenarios].sort((a,b)=>Date.parse(b.created_at)-Date.parse(a.created_at)).map(scenario => <option key={scenario.id} value={scenario.id}>{scenarioLabel(scenario,data.timezone)}</option>)}
      </select></label>
      <label>Dependencias<select aria-label="Dependencias" value={dependencies} onChange={e=>setDependencies(e.target.value as DependencyMode)}><option value="hidden">Ocultas</option><option value="selected">Seleccionada</option><option value="all">Todas</option></select></label>
      <fieldset className={styles.layers}><legend>Mostrar</legend>{([['plan','Plan'],['execution','Ejecución'],['simulation','Simulación']] as const).map(([key,label])=><label key={key}><input type="checkbox" checked={layers[key]} onChange={e=>setLayers({...layers,[key]:e.target.checked})}/>{label}</label>)}</fieldset>
    </section>
    {adjustmentMode && <p className={styles.devNotice}>Modo ajuste DEV/interno: permite simular, no constituye autorización de seguridad. Arrastrá una operación futura o usá PROPONER HORARIO.</p>}

    {intent && <section className={styles.intentPanel} aria-label="Proponer cambio">
      <p className="eyebrow">PROPUESTA MANUAL</p>
      <h2>{intent.kind === 'resize' ? 'Proponer duración planificada' : 'Proponer horario'}</h2>
      <dl><dt>Proyecto</dt><dd>{intent.operation.project_name}</dd>
        <dt>Operación</dt><dd>{intent.operation.operation_name}</dd>
        <dt>Actual</dt><dd>{plantDateTime(intent.operation.planned_start!, data.timezone)}–{plantDateTime(intent.operation.planned_finish!, data.timezone)}</dd>
        <dt>Solicitado</dt><dd>{plantDateTime(intent.requestedStart, data.timezone)}–{plantDateTime(intent.requestedFinish, data.timezone)}</dd>
        {intent.kind === 'resize' && <><dt>Semántica</dt><dd>Estimación planificada hipotética; no modifica realidad ni estimación original.</dd></>}
        {intent.requestedResourceId && <><dt>Recurso solicitado</dt><dd>{data.groups.find(group => group.id === intent.requestedResourceId)?.label ?? intent.requestedResourceId}</dd></>}
      </dl>
      <div className="actions">
        <button disabled={simulate.isPending} onClick={() => simulate.mutate(intent)}>{simulate.isPending?'GENERANDO…':'SIMULAR CAMBIO'}</button>
        <button className="secondary" disabled={simulate.isPending} onClick={() => setIntent(undefined)}>CANCELAR</button>
      </div>
      {simulate.isPending && <p aria-live="polite">Validando disponibilidad y recalculando impacto…</p>}
    </section>}

    <section className={styles.legend} aria-label="Leyenda">
      <span><i aria-hidden="true" className={styles.real}/> Ejecutado real</span>
      <span><i aria-hidden="true" className={styles.current}/> En curso / restante vigente</span>
      <span><i aria-hidden="true" className={styles.future}/> Futuro planificado</span>
      <span><i aria-hidden="true" className={styles.occupation}/> Ocupación física</span>
      <span><i aria-hidden="true" className={styles.scenario}/> Simulación</span>
      <span><i aria-hidden="true" className={styles.blocked}>!</i> Bloqueado</span>
      <span><i aria-hidden="true" className={styles.delayed}>!</i> Retrasado</span>
      <span><i aria-hidden="true" className={styles.nowSwatch}/> AHORA</span>
    </section>

    {data.scenario && <section className={styles.impact} aria-label="Impacto de simulación">
      <div><p className="eyebrow">{initial?'SIMULACIÓN DE PROYECTO LIBERADO':`CURRENT V${data.plan_version_number} vs SIMULACIÓN SELECCIONADA · PLAN ACTUAL vs PROPUESTA`} · {data.scenario.complete?'Completa':'Incompleta'}</p><h2>{data.scenario.name}</h2>
        {data.scenario.origin_plan_version_number!=null&&<strong>ORIGEN DE CURRENT V{data.scenario.origin_plan_version_number} · CONFIRMADA</strong>}
        {data.scenario.stale && <strong className="warning">SIMULACIÓN OBSOLETA</strong>}</div>
      {data.scenario.expired && <p className="warning" role="status"><strong>SIMULACIÓN DESACTUALIZADA</strong> · Esta propuesta contiene operaciones planificadas en el pasado. Generá una nueva simulación para poder confirmarla.</p>}
      <dl><dt>Operaciones afectadas</dt><dd>{data.scenario.changed_operations}</dd>
        <dt>Proyectos afectados</dt><dd>{data.scenario.affected_projects}</dd>
        <dt>Cambios de entrega</dt><dd>{data.scenario.project_finish_changes?.length ?? 0}</dd>
        <dt>Fuera de horizonte</dt><dd>{outside}</dd><dt>Restricciones informadas</dt><dd>{data.operations.filter(o=>o.blocker_code).length}</dd><dt>Criticidad</dt><dd>No disponible</dd></dl>
      {data.scenario.communication_recommended && !blocked && <p className="warning">Puede ser necesario avisar al cliente.</p>}
      {data.scenario.manual_intent && <dl>
        <dt>Solicitaste</dt><dd>{plantDateTime(String(data.scenario.manual_intent.requested_start), data.timezone)}</dd>
        <dt>Primera posición factible</dt><dd>{data.scenario.manual_intent.proposed_start ? plantDateTime(String(data.scenario.manual_intent.proposed_start), data.timezone) : 'Sin posición factible'}</dd>
        <dt>Resultado</dt><dd>{data.scenario.manual_intent.exact_request_satisfied ? 'Solicitud exacta satisfecha' : 'Alternativa propuesta por restricciones'}</dd>
        <dt>Motivo</dt><dd>{Array.isArray(data.scenario.manual_intent.explanations) ? data.scenario.manual_intent.explanations.join(', ') : 'Sin bloqueos adicionales'}</dd>
      </dl>}
      <div className="actions"><button className="secondary" aria-pressed={changesOnly} onClick={()=>setChangesOnly(true)}>VER CAMBIOS</button><button className="secondary" aria-pressed={!changesOnly} onClick={()=>setChangesOnly(false)}>VER PLAN COMPLETO</button>{!initial&&<button className="secondary" onClick={()=>void refreshCurrent()}>VOLVER SIN ACEPTAR</button>}</div>
      <ul>{(data.scenario.operations ?? []).map(item => {
        const operation=data.operations.find(o=>o.operation_id===item.operation_id)
        return <li key={item.operation_id}><strong>{operation?.operation_name??'Operación histórica'}</strong> · <span>{differenceLabel(item.difference)}{item.delta_minutes ? ` · ${Math.abs(item.delta_minutes)} min` : ''}</span><br/>
          Vigente: {operation?.planned_start&&operation.planned_finish?`${plantDateTime(operation.planned_start,data.timezone)} → ${plantDateTime(operation.planned_finish,data.timezone)}`:'Sin programación'}<br/>
          Simulación: {item.planned_start&&item.planned_finish?`${plantDateTime(item.planned_start,data.timezone)} → ${plantDateTime(item.planned_finish,data.timezone)}`:'Sin programación'}</li>
      })}</ul>
      <div className="actions">
        <button aria-describedby={blocked?'scenario-confirmation-blocker':undefined} disabled={Boolean(blocked) || accept.isPending || reject.isPending} onClick={() => accept.mutate()}>{accept.isPending?'CONFIRMANDO…':'CONFIRMAR NUEVO PLAN'}</button>
        {initial?<button className="secondary" disabled={accept.isPending} onClick={()=>void refreshCurrent()}>VOLVER SIN ACEPTAR</button>:data.scenario.status==='ready'&&!data.scenario.stale&&<button className="secondary" disabled={accept.isPending || reject.isPending} onClick={() => reject.mutate()}>CANCELAR PROPUESTA</button>}
      </div>
      {blocked&&<p id="scenario-confirmation-blocker" className="warning">{blocked}</p>}
    </section>}
    {message && <p className={message.includes('No se pudo') || message.includes('obsoleta') || message.includes('desactualizada') ? 'warning' : 'success'} aria-live="polite">{message}</p>}

    {initial && <section className={styles.initialSummary} aria-label="Detalle de simulación inicial">
      <h2>Operaciones de la simulación</h2>
      <p>Sin aceptación automática. Revisá secuencia, fechas, personas y recursos antes de confirmar.</p>
      {data.scenario?.complete===false?<p className="warning">Simulación incompleta: no tiene fecha final estimada y no puede aceptarse. Revisá los bloqueos.</p>:<p>Fecha final estimada: {data.operations.filter(o=>o.planned_finish).map(o=>o.planned_finish!).sort().at(-1)?plantDateTime(data.operations.filter(o=>o.planned_finish).map(o=>o.planned_finish!).sort().at(-1)!,data.timezone):'Sin fecha'}</p>}
      <details><summary>Resumen de operaciones y asignaciones</summary><ul>{data.operations.map(op=><li key={op.operation_id}><strong>{op.operation_name}</strong> · <span>{op.duration_minutes??'—'} min</span> · <span>{(op.people??[]).map(p=>p.name).join(', ')||'Sin asignar'}</span> · {op.resources?.map(r=>r.name).join(', ')||'Sin recurso físico'} · {op.blocker_code?blockerMessage(op.blocker_code):op.operational_status} · {op.planned_start?plantDateTime(op.planned_start,data.timezone):'Sin inicio'}</li>)}</ul></details>
    </section>}
    {!data.plan_version_id&&!data.scenario&&<p className="state">Todavía no existe un plan vigente. Elegí una simulación en Comparar con para revisarla.</p>}

    {data.operations.length === 0
      ? <div className="state">No hay operaciones para este rango.</div>
      : <div className={styles.desktopTimeline}><GanttTimeline data={visibleData} onSelect={selectOperation}
          adjustmentMode={adjustmentMode && !compactInteraction && !data.scenario} onIntent={captureIntent} selectedId={selected?.operation_id} dependencies={dependencies} layers={layers}/></div>}

    <section className={styles.mobileList} aria-label="Operaciones visibles"><div role="region" aria-label={`Cronograma móvil en zona horaria ${data.timezone}. Sólo lectura.`}>
      <h2>Operaciones visibles</h2>
      {visibleData.operations.map(operation => <button className="secondary" data-status={operation.operational_status} data-simulation={Boolean(data.scenario)||undefined} data-selected={selected?.operation_id===operation.operation_id||undefined} key={operation.operation_id} onClick={() => selectOperation(operation)}>
        <strong>{['BLOQUEADO','DEMORADO'].includes(operation.operational_status)&&<span aria-hidden="true">⚠ </span>}{operation.project_name} · {operation.operation_name}</strong><span>{operation.operational_status.replaceAll('_', ' ')} · {operation.duration_minutes??'—'} min</span><span>{operation.planned_start?plantDateTime(operation.planned_start,data.timezone):'Sin inicio'} → {operation.planned_finish?plantDateTime(operation.planned_finish,data.timezone):'Sin fin'}</span><span>{operation.people?.map(p=>p.name).join(', ')||'Sin personas'} · {operation.resources?.map(r=>r.name).join(', ')||'Sin recurso físico'}</span><span>Predecesoras: {operation.predecessors?.map(p=>p.name).join(', ')||'Ninguna'}</span>
      </button>)}</div>
    </section>

    {selected && <aside id="gantt-operation-detail" tabIndex={-1} className={styles.popover} role="dialog" aria-label="Detalle de operación">
      <button className={styles.close} aria-label="Cerrar detalle" onClick={() => {setSelected(undefined);(selectionTrigger.element as HTMLElement|null)?.focus?.()}}>×</button>
      <p className="eyebrow">{selected.project_name} · {selected.lot_name}</p>
      <h2>{selected.operation_name}</h2>
      {data.scenario&&<p>SIMULACIÓN · No aceptada</p>}
      <dl><dt>Fase</dt><dd>{selected.phase_name ?? 'Sin fase'}</dd>
        <dt>Estado</dt><dd>{selected.operational_status.replaceAll('_', ' ')}</dd>
        <dt>Prioridad</dt><dd>{selected.priority}</dd>
        <dt>Inicio</dt><dd>{selected.planned_start ? plantDateTime(selected.planned_start, data.timezone) : 'Fuera de horizonte'}</dd>
        <dt>Fin</dt><dd>{selected.planned_finish ? plantDateTime(selected.planned_finish, data.timezone) : 'Fuera de horizonte'}</dd>
        <dt>Duración</dt><dd>{selected.duration_minutes??'No disponible'} min</dd>
        <dt>División</dt><dd>{({splittable:'Divisible',continuous:'Continua',non_splittable:'Sin interrupciones'} as Record<string,string>)[selected.split_policy??'']??'No disponible'}</dd>
        <dt>Habilidades</dt><dd>{selected.skill_codes?.join(', ')||'No expuestas en esta revisión'}</dd>
        <dt>Centro</dt><dd>{selected.centers?.map(c=>`${c.name}${c.aggregate_capacity?` · capacidad ${c.aggregate_capacity}`:''}`).join(', ')||'Sin centro de fábrica'}</dd>
        <dt>Predecesoras</dt><dd>{selected.predecessors?.map(p=>p.name).join(', ')||'Ninguna'}</dd>
        <dt>Sucesoras</dt><dd>{data.operations.filter(o=>o.predecessors?.some(p=>p.id===selected.operation_id)).map(o=>o.operation_name).join(', ')||'Ninguna en los datos cargados'}</dd>
        <dt>Personas</dt><dd>{(selected.people ?? []).map(value => value.name).join(', ') || 'Sin asignar'}</dd>
        <dt>Recurso</dt><dd>{(selected.resources ?? []).map(value => value.name).join(', ') || 'Sin asignar'}</dd>
        <dt>Ejecutado</dt><dd>{minutes(selected.executed_minutes)}</dd>
        <dt>Restante vigente</dt><dd>{minutes(selected.remaining_minutes)}</dd></dl>
      {!!selected.planned_segments?.length&&<section aria-label="Segmentos planificados"><h3>Segmentos de trabajo</h3><ul>{selected.planned_segments.map((s,i)=><li key={i}>{s.phase_name}: {plantDateTime(s.started_at,data.timezone)} → {plantDateTime(s.ended_at,data.timezone)}</li>)}</ul></section>}
      <h3>¿Por qué empieza a esta hora?</h3><p>El planificador no expone actualmente el motivo detallado.</p><p>Criticidad no disponible. Las dependencias lógicas no representan bloqueos por capacidad.</p>
      {data.scenario&&data.plan_version_id&&<p>Personas y recursos corresponden al plan actual. La comparación expone fechas propuestas, no las nuevas asignaciones ni sus interrupciones.</p>}
      {blockerMessage(selected.blocker_code) && <p className="warning"><strong>{selected.operational_status==='BLOQUEADO'?'Bloqueo:':'Restricción informada:'}</strong> {blockerMessage(selected.blocker_code)}</p>}
      {adjustmentMode && !['FINALIZADO', 'EN_CURSO'].includes(selected.operational_status)
        && selected.executed_minutes === 0 && <section>
        <h3>Alternativa accesible</h3>
        <label>Fecha y hora solicitada
          <input type="datetime-local" value={formStart} onChange={event => setFormStart(event.target.value)} />
        </label>
        <button disabled={!formStart} onClick={() => {
          const start = moment.tz(formStart, data.timezone)
          const currentMinutes = Math.max(1, Math.round(
            (Date.parse(selected.planned_finish!) - Date.parse(selected.planned_start!)) / 60000,
          ))
          captureIntent({
            kind: 'move', operation: selected,
            requestedStart: start.toISOString(),
            requestedFinish: start.clone().add(currentMinutes, 'minutes').toISOString(),
            requestedDurationMinutes: currentMinutes,
          })
          setSelected(undefined)
        }}>PROPONER HORARIO</button>
        <label>Duración planificada (minutos)
          <input type="number" min="1" value={formDuration}
            onChange={event => setFormDuration(event.target.value)} />
        </label>
        <button disabled={!Number(formDuration)} onClick={() => {
          const duration = Number(formDuration)
          const start = selected.planned_start!
          captureIntent({
            kind: 'resize', operation: selected,
            requestedStart: start,
            requestedFinish: new Date(Date.parse(start) + duration * 60000).toISOString(),
            requestedDurationMinutes: duration,
          })
          setSelected(undefined)
        }}>PROPONER DURACIÓN</button>
      </section>}
      {adjustmentMode && selected.operational_status === 'EN_CURSO' && <p className="warning">Una operación en curso no se mueve: actualizá el tiempo restante y luego simulá la reprogramación.</p>}
      <Link to={`/operations/${selected.operation_id}`}>VER DETALLE</Link>
    </aside>}
  </main>
}
