import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach,test,expect,vi } from 'vitest'
import { http,HttpResponse,server } from '../../test/server'
import { projectFixture } from '../../test/projectIntakeFixture'
import { readinessFixture } from '../../test/productionReadinessFixture'
import { ProductionReadinessCard } from './ProductionReadiness'

let calls:{body:any;key:string|null}[]
const result={scenario_id:projectFixture.id,solution_id:projectFixture.id,status:'ready',complete:true,planned_phases:1,blocked_phases:0}
function show(){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><MemoryRouter><ProductionReadinessCard project={{...projectFixture,production_readiness:{...readinessFixture,released:true,eligible:true,state:'released'}}}/></MemoryRouter></QueryClientProvider>)}
const generate=()=>screen.getByRole('button',{name:/^(GENERAR SIMULACIÓN|GENERANDO…)$/})
beforeEach(()=>{
 vi.spyOn(Date,'now').mockReturnValue(Date.parse('2026-10-26T01:00:00Z'))
 calls=[]
 server.use(http.post('/api/projects/:id/simulations',async({request})=>{calls.push({body:await request.json(),key:request.headers.get('Idempotency-Key')});return HttpResponse.json(result)}))
})

test('fecha inicial es la fecha local de planta y payload conserva date-only',async()=>{
 show()
 expect(screen.getByLabelText('Inicio del horizonte (fecha local)')).toHaveValue('2026-10-25')
 expect(screen.getByText('Zona de planta: America/Argentina/Cordoba')).toBeInTheDocument()
 await userEvent.clear(screen.getByLabelText('Inicio del horizonte (fecha local)'))
 await userEvent.type(screen.getByLabelText('Inicio del horizonte (fecha local)'),'2026-10-26')
 await userEvent.click(generate())
 await screen.findByRole('link',{name:'ABRIR PLANIFICACIÓN'})
 expect(calls[0].body.horizon_start).toBe('2026-10-26')
 expect(calls[0].body.horizon_end).toMatch(/^\d{4}-\d{2}-\d{2}$/)
})

test('doble click produce una intención y el éxito bloquea repetición accidental',async()=>{
 server.use(http.post('/api/projects/:id/simulations',async({request})=>{calls.push({body:await request.json(),key:request.headers.get('Idempotency-Key')});await new Promise(r=>setTimeout(r,100));return HttpResponse.json(result)}))
 show();await userEvent.dblClick(generate())
 expect(generate()).toBeDisabled()
 await screen.findByRole('link',{name:'ABRIR PLANIFICACIÓN'})
 expect(calls).toHaveLength(1)
 expect(generate()).toBeDisabled()
})

test('retry técnico mantiene fecha y key de la intención original',async()=>{
 server.use(http.post('/api/projects/:id/simulations',async({request})=>{calls.push({body:await request.json(),key:request.headers.get('Idempotency-Key')});return calls.length===1?HttpResponse.json({},{status:500}):HttpResponse.json({...result,idempotent_replay:true})}))
 show();await userEvent.click(generate())
 const retry=await screen.findByRole('button',{name:'REINTENTAR MISMA ACCIÓN'})
 expect(screen.getByLabelText('Inicio del horizonte (fecha local)')).toBeDisabled()
 await userEvent.click(retry)
 await screen.findByRole('link',{name:'ABRIR PLANIFICACIÓN'})
 expect(calls).toHaveLength(2);expect(calls[1]).toEqual(calls[0])
})

test('preparar otra simulación permite nueva intención y nueva key',async()=>{
 show();await userEvent.click(generate());await screen.findByRole('link',{name:'ABRIR PLANIFICACIÓN'})
 expect(generate()).toBeDisabled()
 await userEvent.click(screen.getByRole('button',{name:'PREPARAR OTRA SIMULACIÓN'}))
 expect(calls).toHaveLength(1)
 await userEvent.clear(screen.getByLabelText('Inicio del horizonte (fecha local)'))
 await userEvent.type(screen.getByLabelText('Inicio del horizonte (fecha local)'),'2026-10-27')
 await userEvent.click(generate())
 await waitFor(()=>expect(calls).toHaveLength(2))
 expect(calls[1].key).not.toBe(calls[0].key)
 expect(calls[1].body.horizon_start).toBe('2026-10-27')
})
