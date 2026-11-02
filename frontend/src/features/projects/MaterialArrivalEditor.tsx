import {useState} from 'react'
import {useMutation,useQuery} from '@tanstack/react-query'
import {request} from '../../api/client'
import type {components} from '../../api/schema'
import type {Lot,Operation} from './ProductEditor'

type Selection=components['schemas']['MaterialArrivalSelection']
type Route=components['schemas']['MaterialArrivalRoute']
const materials=[['18','Melamina 18 mm'],['15','Melamina 15 mm'],['12','Melamina 12 mm'],['03','Fondo 3 mm'],['055','Fondo 5,5 mm']] as const

export function MaterialArrivalEditor({lot,change,onBusy}:{lot:Lot;change:(lot:Lot)=>void;onBusy:(busy:boolean)=>void}){
 const [expanded,setExpanded]=useState(false)
 const [selection,setSelection]=useState<Selection>(lot.material_arrival??{route_code:'MATERIAL_ROUTE_1',materials:materials.map(([m])=>m),optional_process_codes:[]})
 const catalog=useQuery({queryKey:['material-arrival-routes'],enabled:expanded||!!lot.material_arrival,queryFn:()=>request<Route[]>('/product-definition/material-arrival-routes')})
 const route=catalog.data?.find(r=>r.code===selection.route_code)
 const applied=catalog.data?.find(r=>r.code===lot.material_arrival?.route_code)
 const generate=useMutation({onMutate:()=>onBusy(true),onSettled:()=>onBusy(false),mutationFn:()=>request<Operation[]>('/product-definition/material-arrival-preview',{method:'POST',body:JSON.stringify(selection)}),onSuccess:operations=>{change({...lot,route_version_id:null,material_arrival:structuredClone(selection),operations});setExpanded(false)}})
 const update=(next:Selection)=>{setSelection(next);generate.reset()}
 const regenerate=()=>{
  if(lot.operations.length&&!window.confirm('¿Regenerar desde la ruta? Reemplazará TODAS las operaciones de este lote, sus nombres, fases, duraciones, personas, recursos y precedencias, incluidos los cambios manuales.'))return
  generate.mutate()
 }
 return <section aria-label="Llegada del material"><h3>Cómo llega el material</h3>
 <p>{applied?.name??(lot.material_arrival?'Ruta de llegada guardada':'Sin ruta de llegada seleccionada. La definición manual sigue disponible.')}</p>
 <button type="button" onClick={()=>setExpanded(v=>!v)}>{expanded?'CERRAR CONFIGURACIÓN DE LLEGADA':'CONFIGURAR LLEGADA DEL MATERIAL'}</button>
 {expanded&&<fieldset disabled={generate.isPending}><legend>Plantilla inicial por material</legend>
 {catalog.isPending&&<p role="status">Cargando rutas de llegada…</p>}
 {catalog.isError&&<p role="alert">No pudimos cargar las rutas. <button onClick={()=>void catalog.refetch()}>REINTENTAR RUTAS</button></p>}
 {route&&<><label>Cómo llega el material<select aria-label="Cómo llega el material" value={selection.route_code} onChange={e=>update({...selection,route_code:e.target.value as Selection['route_code'],optional_process_codes:[]})}>{catalog.data!.map(r=><option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
 <p><strong>{route.name}</strong></p><p>{route.summary}</p><p>La ruta sugiere operaciones y precedencias explícitas. Elegí los materiales presentes y los procesados según proyecto. Podés editar libremente la estructura generada.</p>
 {materials.map(([material,label])=>{
  const active=selection.materials.includes(material)
  const processors=route.processors.filter(p=>p.material===material&&p.applicability!=='no')
  return <fieldset key={material}><legend>{label}</legend><label><input type="checkbox" checked={active} onChange={e=>update({...selection,materials:e.target.checked?[...selection.materials,material]:selection.materials.filter(m=>m!==material),optional_process_codes:(selection.optional_process_codes??[]).filter(code=>!code.endsWith('-'+material))})}/>Incluir {label}</label>
  {active&&processors.map(p=>p.applicability==='yes'?<p key={p.reference}>{p.name}: sugerido por la ruta</p>:<label key={p.reference} style={{display:'block'}}><input type="checkbox" checked={(selection.optional_process_codes??[]).includes(p.reference)} onChange={e=>update({...selection,optional_process_codes:e.target.checked?[...(selection.optional_process_codes??[]),p.reference]:(selection.optional_process_codes??[]).filter(code=>code!==p.reference)})}/>{p.name} · {label} · según proyecto</label>)}
  {active&&(material==='03'||material==='055')&&<p>{selection.route_code==='MATERIAL_ROUTE_2'?'Fondo ya cortado: sin operación interna.':'Corte independiente antes de Armado. Sin Pegado ni Múltiple.'}</p>}
  </fieldset>
 })}
 <p>Armado esperará sólo las ramas terminales activas. La superposición real depende de personas, recursos y calendario.</p>
 <p>Regenerar reemplaza la estructura del lote. Cambiar esta selección conserva las operaciones hasta que confirmes la regeneración. Después agregá las fases y sus duraciones reales antes de congelar.</p>
 <button disabled={!selection.materials.length} onClick={regenerate}>{generate.isPending?'GENERANDO…':'REGENERAR DESDE RUTA'}</button></>}
 {generate.error&&<p role="alert">{generate.error.message}</p>}
 </fieldset>}
 {lot.material_arrival&&<p>Operaciones sugeridas desde la ruta de llegada; la estructura actual puede contener ajustes manuales.</p>}
 </section>
}
