import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor,within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach,test,expect,vi } from 'vitest'
import { http,HttpResponse,server } from '../../test/server'
import { ganttFixture } from '../../test/fixtures'
import { initialGanttFixture,initialScenarioId } from '../../test/initialScenarioFixture'
import { GanttPage } from './GanttPage'

vi.mock('./GanttTimeline',()=>({GanttTimeline:()=> <div>Timeline de simulación</div>}))
let accepted:boolean,calls:number,selected:string[],data:typeof initialGanttFixture
const show=(path=`/planning/gantt?scenario_id=${initialScenarioId}`)=>render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={[path]}><GanttPage/></MemoryRouter></QueryClientProvider>)
beforeEach(()=>{
 accepted=false;calls=0;selected=[];data=structuredClone(initialGanttFixture)
 server.use(http.get('/api/planning/current/gantt',({request})=>{
  const id=new URL(request.url).searchParams.get('scenario_id');if(id)selected.push(id)
  return HttpResponse.json(accepted&&!id?{...ganttFixture,plan_version_number:1}:id?data:{...data,operations:[],scenario:null})
 }),http.post('/api/scenarios/:id/accept',()=>{calls++;accepted=true;return HttpResponse.json({plan_version_id:ganttFixture.plan_version_id},{status:201})}))
})

test('URL selecciona escenario sin CURRENT y aceptar es explícito',async()=>{
 show()
 const detail=await screen.findByRole('region',{name:'Detalle de simulación inicial'})
 expect(within(detail).getByText('Armado')).toBeInTheDocument()
 expect(within(detail).getByText('Operador Uno')).toBeInTheDocument()
 expect(within(detail).getByText('120 min')).toBeInTheDocument()
 expect(screen.getByText(/Fecha final estimada:/)).toBeInTheDocument()
 expect(calls).toBe(0);expect(accepted).toBe(false)
 expect(selected).toContain(initialScenarioId)
 expect(screen.getByRole('button',{name:'MODO AJUSTE'})).toBeDisabled()
 await userEvent.click(screen.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'}))
 await waitFor(()=>expect(calls).toBe(1))
 expect(await screen.findByText(/Plan vigente V1/)).toBeInTheDocument()
})

test('sin selección ofrece las simulaciones sin elegir ni aceptar una',async()=>{
 show('/planning/gantt')
 expect(await screen.findByText(/Elegí una simulación/)).toBeInTheDocument()
 expect(selected).toEqual([]);expect(calls).toBe(0)
 await userEvent.selectOptions(screen.getByLabelText('Comparar con'),initialScenarioId)
 expect(await screen.findByRole('region',{name:'Detalle de simulación inicial'})).toBeInTheDocument()
 expect(selected).toContain(initialScenarioId);expect(calls).toBe(0)
})

test('escenario incompleto expone bloqueos y no permite aceptar',async()=>{
 data.scenario!.complete=false
 data.operations=data.operations.map(o=>({...o,planned_start:null,planned_finish:null,people:[],resources:[],centers:[],operational_status:'BLOQUEADO',blocker_code:'REQUIRED_SKILL_UNAVAILABLE'}))
 show()
 expect(await screen.findByText(/Simulación incompleta/)).toBeInTheDocument()
 expect(screen.getByRole('button',{name:'CONFIRMAR NUEVO PLAN'})).toBeDisabled()
 expect(screen.getByRole('region',{name:'Detalle de simulación inicial'})).toHaveTextContent('Sin asignar')
 await userEvent.click(screen.getByRole('button',{name:'VOLVER SIN ACEPTAR'}))
 await waitFor(()=>expect(screen.queryByRole('region',{name:'Detalle de simulación inicial'})).not.toBeInTheDocument())
 expect(calls).toBe(0)
})
