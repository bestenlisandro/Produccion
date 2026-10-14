import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach,expect,test,vi } from 'vitest'
import { ganttFixture,ganttScenarioFixture } from '../../test/fixtures'
import { http,HttpResponse,server } from '../../test/server'
import { GanttPage } from './GanttPage'

vi.mock('./GanttTimeline',()=>({GanttTimeline:({data,onSelect,adjustmentMode,onIntent}:{data:typeof ganttFixture,onSelect:(value:typeof ganttFixture.operations[0])=>void,adjustmentMode?:boolean,onIntent?:(value:unknown)=>void})=><div role="region" aria-label={`Cronograma en zona horaria ${data.timezone}. ${adjustmentMode?'Modo ajuste.':'Sólo lectura.'}`}><button onClick={()=>onSelect(data.operations[0])}>Seleccionar Armado</button>{adjustmentMode&&<button onClick={()=>onIntent?.({kind:'move',operation:{...data.operations[0],operational_status:'PENDIENTE',executed_minutes:0},requestedStart:'2026-10-20T14:00:00Z',requestedFinish:'2026-10-20T18:00:00Z',requestedDurationMinutes:240})}>Simular drag</button>}</div>}))

const renderPage=()=>render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><GanttPage/></MemoryRouter></QueryClientProvider>)
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
  renderPage();expect(await screen.findByText('SIMULACIÓN OBSOLETA')).toBeInTheDocument();expect(screen.queryByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).not.toBeInTheDocument()
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
