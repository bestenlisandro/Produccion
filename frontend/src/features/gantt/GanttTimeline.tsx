import {useEffect,useId,useMemo,useRef,useState,type PointerEvent} from 'react'
import moment from 'moment-timezone'
import type {GanttData,GanttOperation} from '../../api/client'
import {isAdjustable,operationLabel} from './timelineModel'
import {dependencyEdges,hierarchy,relatedOperations,ROW_HEIGHT,temporalTicks,visibleRows,type DependencyMode,type Layers} from './operationalModel'
import {plantDateTime} from './time'
import styles from './OperationalTimeline.module.css'
import './ganttTokens.css'

export type GanttIntent={kind:'move'|'resize';operation:GanttOperation;requestedStart:string;requestedFinish:string;requestedDurationMinutes:number;requestedResourceId?:string}
type Drag={operation:GanttOperation;startX:number;dx:number;kind:'move'|'resize'}
export function GanttTimeline({data,onSelect,adjustmentMode=false,onIntent,selectedId,dependencies='selected',layers={plan:true,execution:true,simulation:true}}:{data:GanttData;onSelect:(operation:GanttOperation)=>void;adjustmentMode?:boolean;onIntent?:(intent:GanttIntent)=>void;selectedId?:string;dependencies?:DependencyMode;layers?:Layers}){
 const patternId=`gantt-simulation-${useId().replace(/:/g,'')}`
 const [collapsed,setCollapsed]=useState<Set<string>>(new Set()),[scroll,setScroll]=useState(0),[drag,setDrag]=useState<Drag>(),[tip,setTip]=useState<string>(),[now,setNow]=useState(Date.now())
 const viewport=useRef<HTMLDivElement>(null)
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),60000);return()=>clearInterval(timer)},[])
 useEffect(()=>{if(viewport.current){viewport.current.scrollTop=0;setScroll(0)}},[data.group_by])
 const rows=useMemo(()=>hierarchy(data,collapsed),[data,collapsed]),slice=visibleRows(rows,scroll,560)
 const related=useMemo(()=>relatedOperations(data.operations,selectedId),[data.operations,selectedId])
 const edges=useMemo(()=>dependencyEdges(data.operations,dependencies,selectedId),[data.operations,dependencies,selectedId])
 const ticks=useMemo(()=>temporalTicks(data.range_from,data.range_to,data.timezone),[data.range_from,data.range_to,data.timezone])
 const from=Date.parse(data.range_from),to=Date.parse(data.range_to),span=to-from,width=Math.max(840,ticks.length*(ticks.length<=2?840:ticks.length<=7?190:105))
 const px=(date:string|number)=>((typeof date==='number'?date:Date.parse(date))-from)/span*width
 const toggle=(id:string)=>setCollapsed(previous=>{const next=new Set(previous);if(next.has(id))next.delete(id);else next.add(id);return next})
 const positions=new Map(slice.rows.flatMap((row,i)=>row.operation?[[row.operation.operation_id,{row:row.operation,y:(slice.start+i)*ROW_HEIGHT+31}] as const]:[]))
 const begin=(event:PointerEvent<SVGRectElement>,operation:GanttOperation)=>{
  if(!adjustmentMode||!isAdjustable(operation)||data.scenario)return
  event.currentTarget.setPointerCapture(event.pointerId)
  const box=event.currentTarget.getBoundingClientRect();setDrag({operation,startX:event.clientX,dx:0,kind:event.clientX>box.right-10?'resize':'move'})
 }
 const finish=(event:PointerEvent<SVGRectElement>)=>{
  if(!drag)return
  const target=document.elementFromPoint(event.clientX,event.clientY)?.closest('[data-group-id]')?.getAttribute('data-group-id')
  const requestedResourceId=data.group_by==='resource'&&target&&!drag.operation.group_ids.includes(target)&&data.groups.some(g=>g.id===target&&!g.id.startsWith('unassigned-'))?target:undefined
  if(Math.abs(drag.dx)>4||requestedResourceId){const delta=Math.round(drag.dx/width*span/900000)*900000,start=Date.parse(drag.operation.planned_start!)+(drag.kind==='move'?delta:0),end=Date.parse(drag.operation.planned_finish!)+delta
   if(end>start)onIntent?.({kind:drag.kind,operation:drag.operation,requestedResourceId,requestedStart:new Date(start).toISOString(),requestedFinish:new Date(end).toISOString(),requestedDurationMinutes:Math.max(1,Math.round((end-start)/60000))})
  };setDrag(undefined)
 }
 const summary=(op:GanttOperation)=>`${op.operation_name} · ${op.duration_minutes??'—'} min · ${(op.people??[]).map(p=>p.name).join(', ')||'Sin personas asignadas'} · ${(op.resources??[]).map(r=>r.name).join(', ')||'Sin recurso físico'}`
 return <div className={`${styles.root} ganttTheme`} role="region" aria-label={`Cronograma en zona horaria ${data.timezone}. ${adjustmentMode?'Modo ajuste.':'Sólo lectura.'}`}>
  <div ref={viewport} className={styles.viewport} onScroll={e=>setScroll(e.currentTarget.scrollTop)} tabIndex={0} aria-label="Desplazar cronograma">
   <div className={styles.canvas} style={{width:width+280}}>
    <div className={styles.header} style={{width:width+280}}><div className={styles.corner}>Operación / asignación<small>{rows.filter(r=>r.operation).length} filas · {data.group_by==='project'?'Proyecto / etapa':'Agrupación operativa'}</small></div>
     <svg width={width} height={58} aria-label="Escala temporal">{ticks.map(t=><g key={t.start}><rect x={px(t.start)} width={px(t.end)-px(t.start)} height={58} className={t.weekend?styles.headerWeekend:styles.headerDay}/><text x={px(t.start)+8} y={22}>{t.label}</text>{ticks.length<=7&&[0,6,12,18].map(h=><text key={h} x={px(moment.tz(t.start,data.timezone).add(h,'hours').valueOf())+3} y={45} className={styles.hour}>{String(h).padStart(2,'0')}:00</text>)}</g>)}</svg>
    </div>
    <div className={styles.body} style={{height:rows.length*ROW_HEIGHT}}>
     <svg className={styles.background} style={{left:280}} width={width} height={rows.length*ROW_HEIGHT} aria-label="Calendario productivo"><rect width={width} height="100%" className={styles.offshift}/>{ticks.map(t=><rect key={t.start} data-weekend={t.weekend||undefined} x={px(t.start)} width={px(t.end)-px(t.start)} height="100%" className={t.weekend?styles.weekend:undefined} fill="none"/>)}
      {data.working_windows.map((w,i)=><rect key={i} data-working-window={w.kind} x={Math.max(0,px(w.started_at))} width={Math.max(0,Math.min(width,px(w.ended_at))-Math.max(0,px(w.started_at)))} height="100%" className={styles.working}><title>{w.label??'Horario productivo'} · {plantDateTime(w.started_at,data.timezone)}–{plantDateTime(w.ended_at,data.timezone)}</title></rect>)}
     </svg>
     {slice.rows.map((row,index)=>{
      const op=row.operation,y=(slice.start+index)*ROW_HEIGHT,active=op&&related.has(op.operation_id),overlay=op&&!(data.scenario?.scenario_kind==='initial'&&!data.plan_version_id)?data.scenario?.operations?.find(o=>o.operation_id===op.operation_id):undefined
      const segments=op?.planned_segments?.length?op.planned_segments:op?.planned_start&&op.planned_finish?[{started_at:op.planned_start,ended_at:op.planned_finish}]:[]
      return <div key={row.id} className={`${styles.row} ${active?styles.related:''} ${op&&op.operation_id===selectedId?styles.selected:''}`} style={{top:y,width:width+280}} data-selected={op&&op.operation_id===selectedId||undefined} data-row-kind={row.kind} data-group-id={row.id.split(':')[1]}>
       <div className={`${styles.label} vis-label`} style={{paddingLeft:12+row.depth*12}}>{op?<button className={styles.operation} aria-label={`Inspeccionar ${summary(op)}`} onClick={()=>onSelect(op)}><strong>{['BLOQUEADO','DEMORADO'].includes(op.operational_status)&&<span className={styles.statusIcon} aria-hidden="true">⚠</span>}{row.label}</strong><small className={styles.stateLabel}>{op.operational_status.replaceAll('_',' ')} · {op.people?.length??0} personas asignadas</small><small>{op.resources?.map(r=>r.name).join(', ')||op.centers?.map(c=>c.name).join(', ')||'Sin centro de fábrica'}</small></button>:<button className={styles.group} aria-expanded={row.expanded} onClick={()=>toggle(row.id)}><span aria-hidden>{row.expanded?'▾':'▸'}</span> {row.label}{row.capacity&&row.capacity>1?<small>Capacidad {row.capacity}</small>:null}</button>}</div>
       {op&&<svg className={styles.bars} width={width} height={ROW_HEIGHT}>
        {((data.scenario?.scenario_kind==='initial'&&!data.plan_version_id)?layers.simulation:layers.plan)&&segments.map((segment,i)=>{
         const start=Math.max(0,px(segment.started_at)),end=Math.min(width,px(segment.ended_at));if(end<=start)return null;const simulation=(data.scenario?.scenario_kind==='initial'&&!data.plan_version_id)
         return <g key={`p${i}`} className={`vis-item ${simulation?'gantt-scenario':'gantt-plan'} gantt-status-${op.operational_status.toLowerCase()}`}><rect x={start} y={simulation?22:12} width={Math.max(4,end-start)} height={26} rx={4} className={`${styles.bar} ${simulation?styles.simulation:''}`} style={simulation?{fill:`url(#${patternId})`}:undefined} aria-pressed={op.operation_id===selectedId} role="button" tabIndex={0} aria-describedby={tip===row.id?`tooltip-${row.id}`:undefined} aria-label={operationLabel(op,simulation?'Simulación':'Plan vigente')} onClick={()=>{if(!drag||Math.abs(drag.dx)<4)onSelect(op)}} onFocus={()=>setTip(row.id)} onBlur={()=>setTip(undefined)} onMouseEnter={()=>setTip(row.id)} onMouseLeave={()=>setTip(undefined)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(op)}}} onPointerDown={e=>begin(e,op)} onPointerMove={e=>{if(drag)setDrag({...drag,dx:e.clientX-drag.startX})}} onPointerUp={finish} onPointerCancel={()=>setDrag(undefined)}><title>{summary(op)}</title></rect>{op.operation_id===selectedId&&<rect x={start-2} y={simulation?20:10} width={Math.max(4,end-start)+4} height={30} rx={5} className={styles.selectedOutline}/>}
          {end-start>45&&<text x={start+7} y={simulation?40:30} className={styles.barText}>{['BLOQUEADO','DEMORADO'].includes(op.operational_status)?'! ':''}{op.operation_name.length>(end-start)/7?`${op.operation_name.slice(0,Math.max(3,(end-start)/7-2))}…`:op.operation_name}</text>}</g>
        })}
        {layers.execution&&(op.actual_segments??[]).map(s=>{const start=Math.max(0,px(s.started_at)),end=Math.min(width,px(s.ended_at));return end>start?<rect key={s.id} x={start} y={43} width={end-start} height={10} className={styles.actual}><title>Ejecución real · {s.work_minutes} min</title></rect>:null})}
        {layers.simulation&&overlay?.planned_start&&overlay.planned_finish&&px(overlay.planned_finish)>0&&px(overlay.planned_start)<width&&<rect x={Math.max(0,px(overlay.planned_start))} y={42} width={Math.max(3,Math.min(width,px(overlay.planned_finish))-Math.max(0,px(overlay.planned_start)))} height={18} rx={3} style={{fill:`url(#${patternId})`}} className={`vis-item gantt-scenario ${styles.simulation} difference-${overlay.difference.toLowerCase()}`}><title>Propuesta · {op.operation_name} · {overlay.difference}</title></rect>}
        {op.committed_date&&(()=>{const due=px(moment.tz(op.committed_date,'YYYY-MM-DD',data.timezone).endOf('day').valueOf());return due>=0&&due<=width?<g><line x1={due} x2={due} y1={0} y2={68} className={styles.due}/><text x={due-5} y={62} textAnchor="end">◆ Comprometida</text></g>:null})()}
       </svg>}
       {tip===row.id&&op&&<div id={`tooltip-${row.id}`} className={styles.tooltip} role="tooltip">{summary(op)}</div>}
      </div>
     })}
     <svg className={styles.connectors} style={{left:280}} width={width} height={rows.length*ROW_HEIGHT} aria-label="Dependencias lógicas"><defs><pattern id={patternId} width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="8" height="8" className={styles.patternBase}/><line x1="0" x2="0" y1="0" y2="8" className={styles.patternStripe}/></pattern><marker id={`${patternId}-arrow`} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M0,0 L7,4 L0,8 Z" className={styles.marker}/></marker></defs>
      {edges.map(edge=>{const a=positions.get(edge.from),b=positions.get(edge.to);if(!a||!b||!a.row.planned_finish||!b.row.planned_start)return null;const ax=px(a.row.planned_finish),bx=px(b.row.planned_start);if(ax<0||bx>width)return null;const relevant=edge.from===selectedId||edge.to===selectedId;const d=`M${ax},${a.y} H${ax+12} V${b.y} H${bx}`;return <g key={`${edge.from}:${edge.to}`}><path d={d} className={styles.edgeHalo}/><path data-related={relevant||undefined} data-dependency={`${edge.from}:${edge.to}`} d={d} markerEnd={`url(#${patternId}-arrow)`} className={`${styles.edge} ${!relevant?styles.edgeMuted:''}`}><title>{a.row.operation_name} → {b.row.operation_name}</title></path></g>})}
      {now>=from&&now<=to&&<g><line x1={px(now)} x2={px(now)} y1={0} y2={rows.length*ROW_HEIGHT} className={styles.now}/><text x={px(now)+5} y={14}>AHORA</text></g>}
      {layers.execution&&data.group_by==='resource'&&data.occupations.map(o=>{const row=rows.findIndex(r=>r.id===`group:${o.group_id}`);return row>=slice.start&&row<slice.end?<rect key={o.id} x={Math.max(0,px(o.started_at))} y={row*ROW_HEIGHT+45} width={Math.max(0,Math.min(width,px(o.ended_at))-Math.max(0,px(o.started_at)))} height={9} className={styles.occupation}><title>Ocupación física · {o.resource_name} · {o.source_kind}</title></rect>:null})}
     </svg>
    </div>
   </div>
  </div>
  <p className={styles.calendarKey}>Fondo claro: horario productivo · Fondo gris: fuera de turno / pausa · Fin de semana sombreado. Calendario de planta; pueden existir excepciones por persona o recurso.</p>
  {drag&&<p role="status">{drag.kind==='move'?'Inicio propuesto':'Fin propuesto'}: {plantDateTime(new Date(Date.parse(drag.kind==='move'?drag.operation.planned_start!:drag.operation.planned_finish!)+Math.round(drag.dx/width*span/900000)*900000).toISOString(),data.timezone)} · Δ {Math.round(drag.dx/width*span/900000)*15} min · requiere simular</p>}
 </div>
}
