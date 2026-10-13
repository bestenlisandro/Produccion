import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach,expect,test,vi } from 'vitest'
import { ganttFixture,ganttScenarioFixture } from '../../test/fixtures'
import { http,HttpResponse,server } from '../../test/server'
import { GanttPage } from './GanttPage'

vi.mock('./GanttTimeline',()=>({GanttTimeline:({data,onSelect}:{data:typeof ganttFixture,onSelect:(value:typeof ganttFixture.operations[0])=>void})=><div role="region" aria-label={`Cronograma en zona horaria ${data.timezone}. Sólo lectura.`}><button onClick={()=>onSelect(data.operations[0])}>Seleccionar Armado</button></div>}))

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
