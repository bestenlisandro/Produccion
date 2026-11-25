import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach,expect,test,vi } from 'vitest'
import { ganttFixture,ganttScenarioFixture } from '../../test/fixtures'
import { http,HttpResponse,server } from '../../test/server'
import { GanttPage } from './GanttPage'
import {revisionSimulationFixture,revisionSimulationId} from '../../test/ganttRevisionSimulationFixture'

vi.mock('./GanttTimeline',()=>({GanttTimeline:({data,onSelect,adjustmentMode,onIntent}:{data:typeof ganttFixture,onSelect:(value:typeof ganttFixture.operations[0])=>void,adjustmentMode?:boolean,onIntent?:(value:unknown)=>void})=><div role="region" aria-label={`Cronograma en zona horaria ${data.timezone}. ${adjustmentMode?'Modo ajuste.':'Sólo lectura.'}`}><button onClick={()=>onSelect(data.operations[0])}>Seleccionar Armado</button>{adjustmentMode&&<button onClick={()=>onIntent?.({kind:'move',operation:{...data.operations[0],operational_status:'PENDIENTE',executed_minutes:0},requestedStart:'2026-10-20T14:00:00Z',requestedFinish:'2026-10-20T18:00:00Z',requestedDurationMinutes:240})}>Simular drag</button>}</div>}))

const renderPage=()=>render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><GanttPage/></MemoryRouter></QueryClientProvider>)

test('conserva ejecución visible cuando una operación finalizada sale del trabajo futuro',async()=>{
 const operation={...ganttFixture.operations[0],planned_start:null,planned_finish:null,planned_segments:[],operational_status:'FINALIZADO',remaining_minutes:0,
 actual_segments:[{id:'actual-finished',started_at:'2026-11-25T11:30:00Z',ended_at:'2026-11-25T11:50:00Z',work_minutes:20}]}
 server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json({...ganttFixture,operations:[operation]})))
 renderPage();expect(await screen.findByText('Sin trabajo futuro planificado')).toBeInTheDocument()
 expect(screen.getByText(/Ejecutado:.*20 min/)).toBeInTheDocument()
 await userEvent.click(screen.getByRole('button',{name:'Seleccionar Armado'}))
 expect(screen.getByRole('link',{name:'VER DETALLE'})).toBeInTheDocument()
 expect(screen.getAllByText('Sin programación futura')).toHaveLength(2)
})

test('URL directa carga simulation READY de REV5 y compara sus ramas contra CURRENT V1 sin aceptar',async()=>{
 const requests:string[]=[]
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 server.use(http.get('/api/planning/current/gantt',({request})=>{requests.push(request.url);return HttpResponse.json(revisionSimulationFixture)}))
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/planning/gantt?scenario_id=${revisionSimulationId}`]}><GanttPage/></MemoryRouter></QueryClientProvider>)
 await screen.findByText(/Plan vigente V1/)
 expect(screen.queryByText('No pudimos cargar la información.')).not.toBeInTheDocument()
 expect(screen.getByRole('region',{name:'Impacto de simulación'})).toHaveTextContent('A685 REV 5')
 expect(screen.getByRole('region',{name:'Impacto de simulación'})).toHaveTextContent('Corte Fondos 3 mm')
 expect(screen.getByRole('region',{name:'Impacto de simulación'})).toHaveTextContent('Procesado Múltiple 18 mm')
 expect(screen.getByLabelText('Comparar con')).toHaveValue(revisionSimulationId)
 expect(screen.getByRole('option',{name:/Simulación · Vigente \/ revisable/})).toBeInTheDocument()
 await waitFor(()=>expect(requests.length).toBeGreaterThan(1))
 await waitFor(()=>expect(client.isFetching()).toBe(0))
 expect(requests.every(url=>new URL(url).searchParams.get('scenario_id')===revisionSimulationId)).toBe(true)
})

test('error Gantt conserva mensaje seguro y registra código y requestId en consola',async()=>{
 const log=vi.spyOn(console,'error').mockImplementation(()=>{})
 server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json({error:{code:'RESOURCE_NOT_FOUND',message:'resource not found',request_id:'trace-gantt-9'}},{status:404,headers:{'X-Request-Id':'trace-gantt-9'}})))
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[`/planning/gantt?scenario_id=${revisionSimulationId}`]}><GanttPage/></MemoryRouter></QueryClientProvider>)
 await screen.findByText('No pudimos cargar la información.')
 expect(log).toHaveBeenCalledWith('API request failed',expect.objectContaining({status:404,code:'RESOURCE_NOT_FOUND',requestId:'trace-gantt-9'}))
 expect(screen.queryByText('trace-gantt-9')).not.toBeInTheDocument()
 log.mockRestore()
})

test('simulación vencida sigue visible y revisable pero no puede confirmarse',async()=>{
 let accepts=0
 server.use(http.get('/api/planning/current/gantt',({request})=>HttpResponse.json(new URL(request.url).searchParams.has('scenario_id')?{...ganttScenarioFixture,scenario:{...ganttScenarioFixture.scenario!,expired:true}}:ganttFixture)),http.post('/api/scenarios/:id/accept',()=>{accepts++;return HttpResponse.json({})}))
 renderPage();await screen.findByText(/Plan vigente V6/)
 await userEvent.selectOptions(screen.getByLabelText('Comparar con'),ganttScenarioFixture.scenario!.id)
 expect(await screen.findByText('SIMULACIÓN DESACTUALIZADA')).toBeVisible()
 const confirm=screen.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})
 expect(confirm).toBeDisabled();await userEvent.click(confirm);expect(accepts).toBe(0)
 expect(screen.getByText(/Esta propuesta contiene operaciones/)).toHaveTextContent('Generá una nueva simulación')
 await userEvent.click(screen.getByRole('button',{name:'Seleccionar Armado'}))
 expect(screen.getByRole('dialog',{name:'Detalle de operación'})).toBeVisible()
})

test('vencimiento entre lectura y ACCEPT muestra error y conserva CURRENT',async()=>{
 server.use(http.post('/api/scenarios/:id/accept',()=>HttpResponse.json({error:{code:'SCENARIO_EXPIRED',message:'Esta simulación quedó desactualizada. Generá una nueva simulación.'}},{status:409})))
 renderPage();await screen.findByText(/Plan vigente V6/)
 await userEvent.selectOptions(screen.getByLabelText('Comparar con'),ganttScenarioFixture.scenario!.id)
 await userEvent.click(await screen.findByRole('button',{name:'CONFIRMAR NUEVO PLAN'}))
 expect(await screen.findByText(/Esta simulación quedó desactualizada porque/)).toHaveClass('warning')
 expect(screen.getByText(/Plan vigente V6/)).toBeVisible()
 expect(screen.queryByText(/Nueva planificación confirmada/)).not.toBeInTheDocument()
})

test('leyenda distingue estados por texto, muestras e iconos',async()=>{
 renderPage();await screen.findByText(/Plan vigente V6/)
 const legend=screen.getByRole('region',{name:'Leyenda'})
 for(const name of ['Ejecutado real','En curso','Futuro planificado','Simulación','Bloqueado','Retrasado','Ocupación física','AHORA'])expect(legend).toHaveTextContent(name)
 expect(legend.querySelectorAll('i')).toHaveLength(8)
 expect([...legend.querySelectorAll('i')].every(i=>i.getAttribute('aria-hidden')==='true')).toBe(true)
})
beforeEach(()=>server.use(http.get('/api/planning/current/gantt',({request})=>HttpResponse.json(new URL(request.url).searchParams.has('scenario_id')?ganttScenarioFixture:ganttFixture))))

test('carga plan vigente, zona horaria, leyenda y controles',async()=>{
  renderPage();expect(screen.getByText('Cargando Gantt operativo…')).toBeInTheDocument()
  expect(await screen.findByText(/Plan vigente V6/)).toHaveTextContent('America/Argentina/Buenos_Aires')
  expect(screen.getByRole('region',{name:/zona horaria/})).toBeInTheDocument()
  expect(screen.getByText('Ejecutado real')).toBeInTheDocument();expect(screen.getByText(/AHORA/)).toBeInTheDocument()
  expect(screen.getByRole('button',{name:'Semana'})).toHaveAttribute('aria-pressed','true')
})

test('permite rango, fecha y las cuatro agrupaciones',async()=>{
  renderPage();await screen.findByText(/Plan vigente V6/)
  await userEvent.click(screen.getByRole('button',{name:'Día'}));expect(screen.getByRole('button',{name:'Día'})).toHaveAttribute('aria-pressed','true')
  await userEvent.click(screen.getByRole('button',{name:'2 semanas'}));expect(screen.getByRole('button',{name:'2 semanas'})).toHaveAttribute('aria-pressed','true')
  const group=screen.getByLabelText('Agrupar por');for(const value of ['center','resource','person','project']){await userEvent.selectOptions(group,value);expect(group).toHaveValue(value)}
  await userEvent.click(screen.getByRole('button',{name:'Período siguiente'}));await userEvent.click(screen.getByRole('button',{name:'Período anterior'}))
})

test('abre detalle operativo accesible y enlaza al detalle completo',async()=>{
  renderPage();await userEvent.click(await screen.findByRole('button',{name:'Seleccionar Armado'}))
  const dialog=screen.getByRole('dialog',{name:'Detalle de operación'});expect(dialog).toHaveTextContent('Operador Uno');expect(dialog).toHaveTextContent('Banco 1')
  expect(screen.getByRole('link',{name:'VER DETALLE'})).toHaveAttribute('href',`/operations/${ganttFixture.operations[0].operation_id}`)
  await userEvent.click(screen.getByRole('button',{name:'Cerrar detalle'}));expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
})

test('muestra empty, error y retry',async()=>{
  server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json({...ganttFixture,operations:[]})))
  const view=renderPage();expect(await screen.findByText('No hay operaciones para este rango.')).toBeInTheDocument();view.unmount()
  let calls=0;server.use(http.get('/api/planning/current/gantt',()=>++calls===1?HttpResponse.json({}, {status:500}):HttpResponse.json(ganttFixture)))
  renderPage();await userEvent.click(await screen.findByText('REINTENTAR'));expect(await screen.findByText(/Plan vigente V6/)).toBeInTheDocument()
})

test('sin CURRENT muestra orientación y enlace a proyectos',async()=>{
  server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json({error:{code:'RESOURCE_NOT_FOUND',message:'resource not found'}},{status:404})))
  renderPage()
  expect(await screen.findByRole('heading',{name:'Todavía no existe un plan vigente.'})).toBeInTheDocument()
  expect(screen.getByText('Cargá y liberá un proyecto y generá una simulación para comenzar.')).toBeInTheDocument()
  expect(screen.getByRole('link',{name:'IR A PROYECTOS'})).toHaveAttribute('href','/projects')
  expect(screen.queryByText('REINTENTAR')).not.toBeInTheDocument()
})

test('un 404 ajeno al contrato de CURRENT conserva el error',async()=>{
  server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json({error:{code:'OTHER_NOT_FOUND'}},{status:404})))
  renderPage()
  expect(await screen.findByText('REINTENTAR')).toBeInTheDocument()
  expect(screen.queryByText('Todavía no existe un plan vigente.')).not.toBeInTheDocument()
})

test('compara impacto semántico y confirma el nuevo plan',async()=>{
  let accepted=false;server.use(http.post('/api/scenarios/:id/accept',()=>{accepted=true;return HttpResponse.json({status:'promoted'})}))
  renderPage();await screen.findByText(/Plan vigente V6/);await userEvent.selectOptions(screen.getByLabelText('Comparar con'),'13131313-1313-4131-8131-131313131313')
  expect(await screen.findByText('Retrasada · 60 min')).toBeInTheDocument();expect(screen.getByText('Puede ser necesario avisar al cliente.')).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'}));await waitFor(()=>expect(accepted).toBe(true));expect(await screen.findByText(/Nueva planificación confirmada/)).toBeInTheDocument()
})

test('descarta la propuesta sin perder realidad',async()=>{
  let rejected=false;server.use(http.post('/api/scenarios/:id/reject',()=>{rejected=true;return HttpResponse.json({status:'rejected'})}))
  renderPage();await screen.findByText(/Plan vigente V6/);await userEvent.selectOptions(screen.getByLabelText('Comparar con'),'13131313-1313-4131-8131-131313131313');await screen.findByText('Retrasada · 60 min')
  await userEvent.click(screen.getByRole('button',{name:'CANCELAR PROPUESTA'}));await waitFor(()=>expect(rejected).toBe(true));expect(await screen.findByText(/realidad registrada se mantiene/)).toBeInTheDocument()
})

test('una simulación stale nunca permite confirmar',async()=>{
  const stale={...ganttScenarioFixture,available_scenarios:[{...ganttFixture.available_scenarios[0],stale:true}],scenario:{...ganttScenarioFixture.scenario!,stale:true}}
  server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json(stale)))
  renderPage();expect(await screen.findByText('SIMULACIÓN OBSOLETA')).toBeInTheDocument();expect(screen.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).toBeDisabled()
})

test('histórico initial compara con CURRENT, conserva botón y ordena etiquetas humanas',async()=>{
 const recent={...ganttFixture.available_scenarios[0],scenario_kind:'initial',status:'confirmed',origin_plan_version_number:6,created_at:'2026-10-28T17:55:00Z'}
 const older={...recent,id:'old-initial',status:'stale',stale:true,expired:true,origin_plan_version_number:null,created_at:'2026-10-27T18:08:00Z'}
 const base={...ganttFixture,available_scenarios:[older,recent]}
 server.use(http.get('/api/planning/current/gantt',({request})=>HttpResponse.json(new URL(request.url).searchParams.has('scenario_id')?{...base,scenario:{...ganttScenarioFixture.scenario!,id:older.id,scenario_kind:'initial',stale:true,expired:true}}:base)))
 renderPage();await screen.findByText(/Plan vigente V6/)
 const selector=screen.getByLabelText('Comparar con') as HTMLSelectElement
 expect([...selector.options].map(o=>o.value)).toEqual(['',recent.id,older.id])
 expect(selector.options[1].text).toContain('ORIGEN DE CURRENT V6')
 expect(selector.options[1].text).not.toContain(recent.id)
 await userEvent.selectOptions(selector,older.id)
 expect(await screen.findByText('SIMULACIÓN DESACTUALIZADA')).toBeVisible()
 expect(screen.getByText(/CURRENT V6 vs SIMULACIÓN SELECCIONADA/)).toBeVisible()
 expect(screen.getByText(/Plan vigente V6/)).toBeVisible()
 expect(screen.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).toBeDisabled()
 expect(screen.getByText(/Generá una nueva simulación para poder confirmarla\./,{selector:'#scenario-confirmation-blocker'})).toBeVisible()
 expect(screen.queryByRole('region',{name:'Detalle de simulación inicial'})).not.toBeInTheDocument()
 expect(screen.getByText('Armado',{selector:'li strong'})).toBeVisible()
})

test('inicia en consulta y captura una intención sin llamar al backend',async()=>{
  let calls=0;server.use(http.post('/api/planning/activities/:id/move',()=>{calls++;return HttpResponse.json({})}))
  renderPage();await screen.findByText(/Plan vigente V6/)
  expect(screen.getByRole('button',{name:'MODO CONSULTA'})).toHaveAttribute('aria-pressed','true')
  expect(screen.queryByRole('button',{name:'Simular drag'})).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'MODO AJUSTE'}))
  await userEvent.click(screen.getByRole('button',{name:'Simular drag'}))
  expect(screen.getByRole('region',{name:'Proponer cambio'})).toHaveTextContent('PROPUESTA MANUAL')
  expect(calls).toBe(0)
  await userEvent.click(screen.getByRole('button',{name:'CANCELAR'}))
  expect(screen.queryByRole('region',{name:'Proponer cambio'})).not.toBeInTheDocument()
  expect(calls).toBe(0)
})

test('simula explícitamente y muestra feedback contextual',async()=>{
  let calls=0;server.use(http.post('/api/planning/activities/:id/move',()=>{calls++;return HttpResponse.json({
    scenario_id:'13131313-1313-4131-8131-131313131313',
    schedule_solution_id:'14141414-1414-4141-8141-141414141414',status:'ready',
    requested_start:'2026-10-20T14:00:00Z',requested_finish:'2026-10-20T18:00:00Z',
    proposed_start:'2026-10-20T15:30:00Z',proposed_finish:'2026-10-20T19:30:00Z',
    exact_request_satisfied:false,changed_operations:2,affected_projects:1,
    customer_date_alerts:0,communication_recommended:false,explanations:['PHYSICAL_RESOURCE_OCCUPIED'],
    stale:false,idempotent_replay:false,
  })}))
  renderPage();await screen.findByText(/Plan vigente V6/)
  await userEvent.click(screen.getByRole('button',{name:'MODO AJUSTE'}))
  await userEvent.click(screen.getByRole('button',{name:'Simular drag'}))
  await userEvent.click(screen.getByRole('button',{name:'SIMULAR CAMBIO'}))
  expect(await screen.findByText(/primera alternativa factible/i)).toBeInTheDocument()
  expect(calls).toBe(1)
})

test('bloquea move en curso y ofrece formulario para trabajo futuro',async()=>{
  const future={...ganttFixture,operations:[{...ganttFixture.operations[0],operational_status:'PENDIENTE',executed_minutes:0}]}
  server.use(http.get('/api/planning/current/gantt',()=>HttpResponse.json(future)))
  renderPage();await screen.findByText(/Plan vigente V6/)
  await userEvent.click(screen.getByRole('button',{name:'MODO AJUSTE'}))
  await userEvent.click(screen.getByRole('button',{name:'Seleccionar Armado'}))
  expect(screen.getByRole('button',{name:'PROPONER HORARIO'})).toBeDisabled()
  await userEvent.type(screen.getByLabelText('Fecha y hora solicitada'),'2026-10-20T14:00')
  expect(screen.getByRole('button',{name:'PROPONER HORARIO'})).toBeEnabled()
})
