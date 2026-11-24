import { render,screen,fireEvent } from '@testing-library/react';import userEvent from '@testing-library/user-event';import { QueryClient,QueryClientProvider } from '@tanstack/react-query';import { MemoryRouter,Route,Routes } from 'react-router';import { http,HttpResponse,server } from '../../test/server';import { operation } from '../../test/fixtures';import { OperationDetail } from './OperationDetail'
const detail={...operation,phase_id:'55555555-5555-4555-8555-555555555555',original_estimate_minutes:600,plan_requires_reconciliation:false,next_operation_name:'Canteado'}
const execution={timezone:'America/Argentina/Buenos_Aires',execution_id:crypto.randomUUID(),execution_status:'running',started_at:'2026-11-24T11:30:00Z',completed_at:null,remaining_revision_no:1,remaining_minutes:180,can_execute:true,blockers:[],phases:[{id:detail.phase_id,name:'Armado',original_estimate_minutes:600,required_people:1,started:true,completed:false}],people:[{id:'person',name:'Mariano'}],resources:[{id:'bank',name:'Banco de armado 1'}],segments:[]}
const renderDetail=()=>render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter initialEntries={['/operations/'+operation.operation_id]}><Routes><Route path="/operations/:operationId" element={<OperationDetail/>}/><Route path="/" element={<div>tablero</div>}/></Routes></MemoryRouter></QueryClientProvider>)
beforeEach(()=>server.use(http.get('/api/operations/:id',()=>HttpResponse.json(detail)),http.get('/api/operations/:id/execution',()=>HttpResponse.json(execution)),http.post('/api/operations/:id/execution/remaining-estimate',()=>HttpResponse.json({revision_id:crypto.randomUUID(),revision_number:2,original_minutes:600,executed_minutes:420,remaining_minutes:240,updated_total_minutes:660,planning_state_revision_id:crypto.randomUUID(),planning_state_revision_number:2,effective_event_id:crypto.randomUUID(),current_plan_version_id:crypto.randomUUID()}))))
test('muestra detalle real',async()=>{renderDetail();expect(await screen.findByRole('heading',{name:'Armado'})).toBeInTheDocument();expect(screen.getByText('Canteado')).toBeInTheDocument()})
test.each([[30,'+30 min'],[60,'+1 h'],[120,'+2 h']])('atajo agrega %i minutos',async(delta,label)=>{renderDetail();await screen.findByText('Actualizar tiempo restante');const input=screen.getByLabelText(/Nueva estimación/);await userEvent.click(screen.getByText(label));expect(input).toHaveValue(180+delta)})
test('guardar muestra reconciliación sin optimistic update',async()=>{renderDetail();await screen.findByText('Actualizar tiempo restante');await userEvent.click(screen.getByText('GUARDAR ESTIMACIÓN'));expect(await screen.findByText(/planificación necesita revisión/i)).toBeInTheDocument()})

test('ofrece iniciar la primera fase pendiente sin mostrar registro antes del inicio',async()=>{
 server.use(http.get('/api/operations/:id/execution',()=>HttpResponse.json({...execution,execution_id:null,execution_status:null,phases:execution.phases.map(p=>({...p,started:false}))})))
 let body:unknown
 server.use(http.post('/api/operations/:id/start',async({request})=>{body=await request.json();return HttpResponse.json({})}))
 renderDetail();await userEvent.click(await screen.findByRole('button',{name:'INICIAR OPERACIÓN / FASE'}))
 expect(body).toEqual(expect.objectContaining({phase_id:detail.phase_id,started_at:expect.any(String)}))
 expect(screen.queryByRole('button',{name:'REGISTRAR TRAMO'})).not.toBeInTheDocument()
})

test('tramo envía personas recursos y horas; reintento incierto conserva intención y clave',async()=>{
 const bodies:unknown[]=[], keys:(string|null)[]=[]
 server.use(http.post('/api/executions/:id/segments',async({request})=>{bodies.push(await request.json());keys.push(request.headers.get('Idempotency-Key'));return bodies.length===1?HttpResponse.json({}, {status:503}):HttpResponse.json({})}))
 renderDetail();await screen.findByRole('button',{name:'REGISTRAR TRAMO'})
 fireEvent.change(screen.getByLabelText('Fin del tramo / finalización'),{target:{value:'2026-11-24T09:00'}})
 await userEvent.click(screen.getByRole('checkbox',{name:'Mariano'}));await userEvent.click(screen.getByRole('checkbox',{name:'Banco de armado 1'}))
 await userEvent.click(screen.getByRole('button',{name:'REGISTRAR TRAMO'}))
 await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR MISMA ACCIÓN'}))
 expect(bodies).toHaveLength(2);expect(bodies[1]).toEqual(bodies[0]);expect(keys[1]).toBe(keys[0]);expect(keys[0]).toBeTruthy()
 expect(bodies[0]).toEqual(expect.objectContaining({work_minutes:30,humans:[{employee_id:'person',work_minutes:30}],physical_usages:[{physical_resource_id:'bank',work_minutes:30,capacity_units:1}]}))
})

test('oculta acciones sin permiso y conserva el historial al finalizar',async()=>{
 server.use(http.get('/api/operations/:id/execution',()=>HttpResponse.json({...execution,can_execute:false,blockers:['Tu usuario no tiene permiso para registrar ejecución.']})))
 renderDetail();expect(await screen.findByText('Tu usuario no tiene permiso para registrar ejecución.')).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'REGISTRAR TRAMO'})).not.toBeInTheDocument()
})

test('finalizada muestra tramo y no ofrece acciones de escritura',async()=>{
 server.use(http.get('/api/operations/:id/execution',()=>HttpResponse.json({...execution,execution_status:'completed',phases:execution.phases.map(p=>({...p,completed:true})),segments:[{id:'segment',phase_id:detail.phase_id,phase_name:'Armado',started_at:execution.started_at,ended_at:'2026-11-24T12:00:00Z',work_minutes:30,people:[{id:'person',name:'Mariano',minutes:30}],resources:[{id:'bank',name:'Banco de armado 1',minutes:30}]}]})))
 renderDetail();expect(await screen.findByText(/Operación finalizada/)).toBeInTheDocument();expect(screen.getByText('Mariano (30 min)')).toBeInTheDocument()
 expect(screen.queryByRole('button',{name:'REGISTRAR TRAMO'})).not.toBeInTheDocument()
})
