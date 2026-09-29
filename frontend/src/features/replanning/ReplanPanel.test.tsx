import { render,screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { http,HttpResponse,server } from '../../test/server'
import { ReplanPanel } from './ReplanPanel'

const scenarioId='66666666-6666-4666-8666-666666666666'
const scenario={id:scenarioId,status:'ready',base_plan_version_id:crypto.randomUUID(),base_state_revision_id:crypto.randomUUID(),base_product_definition_revision_id:crypto.randomUUID(),stale:false,rejected:false,promoted:false,promoted_plan_version_id:null,row_version:2,promotion_lock_version:1,changed_operations:3,affected_projects:2,customer_date_alerts:1,communication_recommended:true,impacts:[{kind:'SHIFTED',delta_minutes:120,reason:{code:'PHYSICAL_RESOURCE_OCCUPIED'}}]}
const renderPanel=()=>render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><ReplanPanel operationId="11111111-1111-4111-8111-111111111111" realitySaved/></QueryClientProvider>)

beforeEach(()=>server.use(
  http.post('/api/operations/:id/replan',()=>HttpResponse.json({scenario_id:scenarioId,status:'ready',complete:true,changed_operations:3,affected_projects:2,customer_date_alerts:1,communication_recommended:true,idempotent_replay:false},{status:201})),
  http.get('/api/scenarios/:id',()=>HttpResponse.json(scenario)),
  http.post('/api/scenarios/:id/accept',()=>HttpResponse.json({ok:true},{status:201})),
  http.post('/api/scenarios/:id/reject',()=>HttpResponse.json({scenario_id:scenarioId,status:'rejected',row_version:3,idempotent_replay:false})),
))

async function simulate(){renderPanel();await userEvent.click(screen.getByText('SIMULAR REPROGRAMACIÓN'));return screen.findByText('Reprogramación propuesta')}

test('simula y muestra impacto humano',async()=>{await simulate();expect(screen.getByText((_,element)=>element?.tagName==='P'&&element.textContent?.includes('3 operaciones afectadas')===true)).toBeInTheDocument();expect(screen.getByText(/120 min/)).toBeInTheDocument()})
test('muestra recomendación de comunicación',async()=>{await simulate();expect(screen.getByText(/necesario avisar al cliente/)).toBeInTheDocument()})
test('acepta, evita doble click y refresca el estado servido',async()=>{let calls=0;const refetch=vi.spyOn(QueryClient.prototype,'refetchQueries');server.use(http.post('/api/scenarios/:id/accept',async()=>{calls++;await new Promise(r=>setTimeout(r,30));return HttpResponse.json({ok:true},{status:201})}));await simulate();await userEvent.dblClick(screen.getByText('CONFIRMAR NUEVO PLAN'));expect(await screen.findByText('Nueva planificación confirmada.')).toBeInTheDocument();expect(calls).toBe(1);expect(refetch).toHaveBeenCalledWith({queryKey:['daily-board'],type:'all'});expect(refetch).toHaveBeenCalledWith({queryKey:['operation','11111111-1111-4111-8111-111111111111'],type:'all'});expect(refetch).toHaveBeenCalledWith({queryKey:['scenario',scenarioId],type:'all'});refetch.mockRestore()})
test('rechaza y conserva la realidad actualizada',async()=>{await simulate();await userEvent.click(screen.getByText('CANCELAR PROPUESTA'));expect(await screen.findByText(/estimación real actualizada se mantiene/)).toBeInTheDocument()})
test('stale 409 ofrece volver a simular',async()=>{server.use(http.post('/api/scenarios/:id/accept',()=>HttpResponse.json({error:{code:'SCHEDULING_BASE_STALE',message:'stale'}},{status:409})));await simulate();await userEvent.click(screen.getByText('CONFIRMAR NUEVO PLAN'));expect(await screen.findByText(/situación de producción cambió/)).toBeInTheDocument();expect(screen.getByText('VOLVER A SIMULAR')).toBeInTheDocument()})
test('error de simulación es comprensible',async()=>{server.use(http.post('/api/operations/:id/replan',()=>HttpResponse.json({error:{code:'OUT_OF_HORIZON'}},{status:409})));renderPanel();await userEvent.click(screen.getByText('SIMULAR REPROGRAMACIÓN'));expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo generar la propuesta.')})
