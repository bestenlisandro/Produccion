import moment from 'moment-timezone'
import type {GanttData,GanttOperation} from '../../api/client'
export type DependencyMode='hidden'|'selected'|'all'
export type Layers={plan:boolean;execution:boolean;simulation:boolean}
export type GanttRow={id:string;label:string;depth:number;kind:'group'|'stage'|'operation';operation?:GanttOperation;expanded?:boolean;capacity?:number|null}
export const ROW_HEIGHT=68
export function hierarchy(data:GanttData,collapsed:Set<string>):GanttRow[]{
 const rows:GanttRow[]=[]
 const groups=data.group_by==='project'?[...new Map(data.operations.map(o=>[o.project_id,{id:o.project_id,label:`${o.project_code} · ${o.project_name}`,capacity:null}])).values()]:data.groups
 for(const group of groups){
  const id=`group:${group.id}`,expanded=!collapsed.has(id)
  rows.push({id,label:group.label,kind:'group',depth:0,expanded,capacity:group.capacity})
  if(!expanded)continue
  const operations=data.operations.filter(o=>data.group_by==='project'?o.project_id===group.id:o.group_ids.includes(group.id))
  if(data.group_by!=='project'){operations.forEach(o=>rows.push({id:`${id}:${o.operation_id}`,label:o.operation_name,kind:'operation',depth:1,operation:o}));continue}
  const stages=new Map<string,GanttOperation[]>()
  for(const op of operations){const key=`${op.stage_order??1000}:${op.stage_name??'Etapa no disponible'}`;stages.set(key,[...(stages.get(key)??[]),op])}
  for(const [key,ops] of [...stages].sort(([a],[b])=>Number(a.split(':')[0])-Number(b.split(':')[0]))){
   const sid=`${id}:stage:${key}`,open=!collapsed.has(sid),first=ops[0]
   rows.push({id:sid,label:`${first.stage_order?`${first.stage_order}. `:''}${first.stage_name??'Etapa no disponible'}`,kind:'stage',depth:1,expanded:open})
   if(open)ops.sort((a,b)=>(a.operation_order??0)-(b.operation_order??0)).forEach(o=>rows.push({id:`${sid}:${o.operation_id}`,label:o.operation_name,kind:'operation',depth:2,operation:o}))
  }
 }
 return rows
}
export function relatedOperations(operations:GanttOperation[],selected?:string){
 const ids=new Set<string>();if(!selected)return ids;ids.add(selected)
 operations.find(o=>o.operation_id===selected)?.predecessors?.forEach(p=>ids.add(p.id))
 operations.filter(o=>o.predecessors?.some(p=>p.id===selected)).forEach(o=>ids.add(o.operation_id));return ids
}
export function dependencyEdges(operations:GanttOperation[],mode:DependencyMode,selected?:string){
 if(mode==='hidden'||mode==='selected'&&!selected)return []
 return operations.flatMap(o=>(o.predecessors??[]).filter(p=>mode==='all'||o.operation_id===selected||p.id===selected).map(p=>({from:p.id,to:o.operation_id})))
}
export function temporalTicks(from:string,to:string,timezone:string){
 const ticks=[];const end=Date.parse(to)
 for(const day=moment.tz(from,timezone).startOf('day');day.valueOf()<end;day.add(1,'day'))ticks.push({start:day.valueOf(),end:day.clone().add(1,'day').valueOf(),label:new Intl.DateTimeFormat('es-AR',{timeZone:timezone,weekday:'short',day:'2-digit',month:'2-digit'}).format(day.toDate()),weekend:day.isoWeekday()>5})
 return ticks
}
export function visibleRows(rows:GanttRow[],scrollTop:number,height:number){
 const start=rows.length>120?Math.max(0,Math.floor(scrollTop/ROW_HEIGHT)-4):0
 const end=rows.length>120?Math.min(rows.length,Math.ceil((scrollTop+height)/ROW_HEIGHT)+4):rows.length
 return {start,end,rows:rows.slice(start,end)}
}
