import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor,within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach,expect,test,vi } from 'vitest'
import { http,HttpResponse,server } from '../../test/server'
import { MasterDataPage,localDate,windowsAt } from './MasterDataPage'

import {ids,snapshot} from '../../test/masterDataFixture'


const renderPage=()=>render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><MasterDataPage/></QueryClientProvider>)
beforeEach(()=>{server.use(http.get('/api/master-data/snapshot',()=>HttpResponse.json(snapshot)));vi.spyOn(window,'confirm').mockReturnValue(true)})

test('navega Configuración, lista personas y muestra matriz de skills',async()=>{
  renderPage();expect(screen.getByText('Cargando configuración…')).toBeInTheDocument()
  expect(await screen.findByRole('heading',{name:'Maestros operativos'})).toBeInTheDocument()
  expect(screen.getByText(/DEV ONLY/)).toBeInTheDocument();expect(screen.getByText('Operador Uno')).toBeInTheDocument()
  expect(screen.getByLabelText('Armado')).toBeChecked()
  for(const [button,heading] of [['Habilidades','Habilidades'],['Centros de trabajo','Centros de trabajo'],['Recursos','Recursos físicos'],['Calendarios','Calendarios'],['Planta','Planta']]){await userEvent.click(screen.getByRole('button',{name:button}));expect(screen.getByRole('heading',{name:heading})).toBeInTheDocument()}
})

test('crea persona con guardado explícito y calendario',async()=>{
  let request:Request|undefined;server.use(http.post('/api/master-data/people',async({request:r})=>{request=r;return HttpResponse.json({entity:{id:'new',row_version:1},current_usage_count:0,plan_requires_reconciliation:false,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno')
  const form=screen.getByRole('heading',{name:'Crear persona'}).closest('form')!
  await userEvent.type(within(form).getByLabelText('Código'),'EMP-2');await userEvent.type(within(form).getByLabelText('Nombre visible'),'Persona Dos');await userEvent.selectOptions(within(form).getByLabelText('Calendario'),ids.calendar);await userEvent.click(within(form).getByRole('button',{name:'GUARDAR'}))
  await waitFor(()=>expect(request).toBeDefined());expect(await request!.json()).toMatchObject({code:'EMP-2',display_name:'Persona Dos',base_calendar_id:ids.calendar})
})

test('edita y advierte antes de desactivar una persona usada por CURRENT',async()=>{
  let path='';server.use(http.post('/api/master-data/people/:id/status',({request})=>{path=new URL(request.url).pathname;return HttpResponse.json({entity:{id:ids.person,row_version:2,status:'inactive'},current_usage_count:4,plan_requires_reconciliation:true,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'DESACTIVAR'}))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('4 operaciones'));await waitFor(()=>expect(path).toContain(ids.person));expect(await screen.findByText(/PLAN_REQUIRES_RECONCILIATION/)).toBeInTheDocument()
})

test('crea y edita una habilidad',async()=>{
  let called=false;server.use(http.post('/api/master-data/skills',()=>{called=true;return HttpResponse.json({entity:{id:'new',row_version:1},current_usage_count:0,plan_requires_reconciliation:false,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Habilidades'}));expect(screen.getByText('Ensamble')).toBeInTheDocument()
  const form=screen.getByRole('heading',{name:'Crear habilidad'}).closest('form')!;await userEvent.type(within(form).getByLabelText('Código'),'CNC');await userEvent.type(within(form).getByLabelText('Nombre'),'CNC');await userEvent.click(within(form).getByRole('button',{name:'GUARDAR'}));await waitFor(()=>expect(called).toBe(true))
})

test('edita capacidad de centro sin confundirla con personas',async()=>{
  let body:any;server.use(http.patch('/api/master-data/work-centers/:id',async({request})=>{body=await request.json();return HttpResponse.json({entity:{id:ids.center,row_version:2},current_usage_count:4,plan_requires_reconciliation:true,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Centros de trabajo'}));expect(screen.getByText(/Capacidad 2/)).toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'EDITAR'}));const capacity=screen.getByLabelText('Capacidad nominal');await userEvent.clear(capacity);await userEvent.type(capacity,'3');await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}));await waitFor(()=>expect(body.aggregate_capacity).toBe(3))
})

test('muestra recurso, tipo y centro y permite desactivarlo',async()=>{
  let called=false;server.use(http.post('/api/master-data/resources/:id/status',()=>{called=true;return HttpResponse.json({entity:{id:ids.resource,row_version:2},current_usage_count:4,plan_requires_reconciliation:true,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Recursos'}));expect(screen.getByText('Banco 1')).toBeInTheDocument();expect(screen.getByText(/Banco · Armado/)).toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'DESACTIVAR'}));await waitFor(()=>expect(called).toBe(true))
})

test('edita jornada semanal, excepción y muestra timezone IANA',async()=>{
  const calls:string[]=[];server.use(http.put('/api/master-data/calendars/:id/windows',({request})=>{calls.push(new URL(request.url).pathname);return HttpResponse.json({entity:{id:ids.calendar,row_version:2},current_usage_count:3,plan_requires_reconciliation:true,idempotent_replay:false})}),http.post('/api/master-data/calendar-exceptions',({request})=>{calls.push(new URL(request.url).pathname);return HttpResponse.json({entity:{id:'new',row_version:1},current_usage_count:3,plan_requires_reconciliation:true,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Calendarios'}));expect(screen.getByDisplayValue('America/Argentina/Buenos_Aires')).toBeInTheDocument();expect(screen.getByText(/Feriado/)).toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'AGREGAR VENTANA'}));await userEvent.click(screen.getByRole('button',{name:'GUARDAR JORNADA'}));await waitFor(()=>expect(calls.some(item=>item.includes('/windows'))).toBe(true));await userEvent.type(screen.getByLabelText('Fecha'),'2026-12-24');await userEvent.type(screen.getByLabelText('Descripción de la excepción'),'Horario reducido');await userEvent.click(screen.getByRole('button',{name:'AGREGAR EXCEPCIÓN'}));await waitFor(()=>expect(calls.some(item=>item.endsWith('/calendar-exceptions'))).toBe(true))
})

test('configuración de planta no expone IDs ni revisiones',async()=>{
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Planta'}));expect(screen.getByDisplayValue('Planta Besten')).toBeInTheDocument();expect(screen.queryByLabelText(/UUID|revisión|organización/i)).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'GUARDAR'})).toBeInTheDocument()
})

test('muestra empty, error y retry',async()=>{
  server.use(http.get('/api/master-data/snapshot',()=>HttpResponse.json({...snapshot,people:[]})));const first=renderPage();expect(await screen.findByText('No hay personas para mostrar.')).toBeInTheDocument();first.unmount();let calls=0;server.use(http.get('/api/master-data/snapshot',()=>++calls===1?HttpResponse.json({}, {status:500}):HttpResponse.json(snapshot)));renderPage();await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR'}));expect(await screen.findByText('Operador Uno')).toBeInTheDocument()
})

test('presenta error de validación backend entendible',async()=>{
  server.use(http.post('/api/master-data/people',()=>HttpResponse.json({error:{code:'PERSISTENCE_CONFLICT',message:'El código ya existe.'}},{status:409})));renderPage();await screen.findByText('Operador Uno');const form=screen.getByRole('heading',{name:'Crear persona'}).closest('form')!;await userEvent.type(within(form).getByLabelText('Código'),'EMP-1');await userEvent.type(within(form).getByLabelText('Nombre visible'),'Duplicada');await userEvent.selectOptions(within(form).getByLabelText('Calendario'),ids.calendar);await userEvent.click(within(form).getByRole('button',{name:'GUARDAR'}));expect(await screen.findByRole('alert')).toHaveTextContent('El código ya existe.')
})

test.each([
  ['Personas','people','Nombre visible','display_name'],
  ['Habilidades','skills','Nombre','name'],
  ['Centros de trabajo','work_centers','Nombre','name'],
  ['Recursos','resources','Nombre','name'],
  ['Calendarios','calendars','Nombre','name'],
] as const)('cambiar registro en %s nunca mezcla identidad y controles',async(section,collection,label,name)=>{
  const original=snapshot[collection][0]
  const second={...original,id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',code:'SECOND',[name]:'Registro Segundo'}
  server.use(http.get('/api/master-data/snapshot',()=>HttpResponse.json({...snapshot,[collection]:[original,second]})))
  renderPage();await screen.findByText('Operador Uno')
  await userEvent.click(screen.getByRole('button',{name:section}))
  const edits=screen.getAllByRole('button',{name:'EDITAR'})
  await userEvent.click(edits[0]);await userEvent.click(edits[1])
  expect(screen.getByLabelText(label,{exact:true})).toHaveValue('Registro Segundo')
  expect(screen.getByLabelText('Código',{exact:true})).toHaveValue('SECOND')
})

test('error 409 conserva valores y edición; éxito posterior cierra el formulario',async()=>{
  let attempts=0
  server.use(http.patch('/api/master-data/people/:id',()=>++attempts===1
    ?HttpResponse.json({error:{message:'Conflicto de edición'}},{status:409})
    :HttpResponse.json({entity:{id:ids.person,row_version:2},current_usage_count:0,plan_requires_reconciliation:false,idempotent_replay:false})))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'EDITAR'}))
  const name=screen.getByLabelText('Nombre visible');await userEvent.clear(name);await userEvent.type(name,'Entrada conservada')
  await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Conflicto de edición')
  expect(name).toHaveValue('Entrada conservada');expect(screen.getByRole('heading',{name:'Editar persona'})).toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}))
  expect(await screen.findByRole('heading',{name:'Crear persona'})).toBeInTheDocument()
})

test('respuesta incierta reintenta misma intención y nueva intención obtiene otra key',async()=>{
  const keys:(string|null)[]=[],bodies:unknown[]=[]
  server.use(http.post('/api/master-data/people',async({request})=>{
    keys.push(request.headers.get('Idempotency-Key'));bodies.push(await request.json())
    return keys.length===1?HttpResponse.json({},{status:503}):HttpResponse.json({entity:{id:'new',row_version:1},current_usage_count:0,plan_requires_reconciliation:false,idempotent_replay:keys.length===2})
  }))
  renderPage();await screen.findByText('Operador Uno')
  const fill=async()=>{
    await userEvent.type(screen.getByLabelText('Código'),'NEW');await userEvent.type(screen.getByLabelText('Nombre visible'),'Persona Nueva')
    await userEvent.selectOptions(screen.getByLabelText('Calendario'),ids.calendar)
    await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}))
  }
  await fill();await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR GUARDADO'}))
  await screen.findByText('Cambios guardados.');await fill()
  await waitFor(()=>expect(keys).toHaveLength(3))
  expect(keys[0]).toBeTruthy();expect(keys[1]).toBe(keys[0]);expect(bodies[1]).toEqual(bodies[0]);expect(keys[2]).not.toBe(keys[0])
})

test('edita excepción existente con versión, rango y factor de capacidad',async()=>{
  let saved:any
  server.use(http.patch('/api/master-data/calendar-exceptions/:id',async({request})=>{
    saved=await request.json();return HttpResponse.json({entity:{id:'exception',row_version:2},current_usage_count:0,plan_requires_reconciliation:false,idempotent_replay:false})
  }))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Calendarios'}));await userEvent.click(screen.getByRole('button',{name:'EDITAR EXCEPCIÓN'}))
  expect(screen.getByLabelText('Descripción de la excepción')).toHaveValue('Feriado')
  await userEvent.selectOptions(screen.getByLabelText('Efecto'),'replace')
  await userEvent.type(screen.getByLabelText('Desde'),'08:00');await userEvent.type(screen.getByLabelText('Hasta'),'12:00')
  await userEvent.type(screen.getByLabelText('Factor de capacidad de la excepción'),'0.5')
  await userEvent.click(screen.getByRole('button',{name:'GUARDAR EXCEPCIÓN'}))
  await waitFor(()=>expect(saved).toMatchObject({calendar_id:ids.calendar,expected_row_version:1,effect:'replace',local_start:'08:00',local_end:'12:00',capacity_factor:0.5}))
})

test('rechaza rango incompleto de excepción sin enviar',async()=>{
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Calendarios'}))
  await userEvent.type(screen.getByLabelText('Fecha'),'2026-12-24');await userEvent.type(screen.getByLabelText('Desde'),'08:00')
  await userEvent.click(screen.getByRole('button',{name:'AGREGAR EXCEPCIÓN'}));expect(await screen.findByRole('alert')).toHaveTextContent('inicio y fin juntos')
})

test('permite mover una excepción a otro calendario explícito',async()=>{
  const target='dddddddd-dddd-4ddd-8ddd-dddddddddddd'
  let saved:any
  server.use(http.get('/api/master-data/snapshot',()=>HttpResponse.json({...snapshot,calendars:[...snapshot.calendars,{...snapshot.calendars[0],id:target,name:'Turno Tokio',timezone:'Asia/Tokyo'}]})),
    http.patch('/api/master-data/calendar-exceptions/:id',async({request})=>{saved=await request.json();return HttpResponse.json({entity:{id:'exception',row_version:2},current_usage_count:1,plan_requires_reconciliation:true,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Calendarios'}))
  await userEvent.click(screen.getByRole('button',{name:'EDITAR EXCEPCIÓN'}))
  await userEvent.selectOptions(screen.getByLabelText('Calendario de la excepción'),target)
  await userEvent.click(screen.getByRole('button',{name:'GUARDAR EXCEPCIÓN'}))
  await waitFor(()=>expect(saved?.calendar_id).toBe(target))
})

test('calendario utilizado permite desactivación con warning CURRENT',async()=>{
  let called=false
  server.use(http.get('/api/master-data/snapshot',()=>HttpResponse.json({...snapshot,calendars:snapshot.calendars.map(c=>({...c,current_usage_count:1}))})),
    http.post('/api/master-data/calendars/:id/status',()=>{called=true;return HttpResponse.json({entity:{id:ids.calendar,row_version:2,status:'inactive'},current_usage_count:1,plan_requires_reconciliation:true,idempotent_replay:false})}))
  renderPage();await screen.findByText('Operador Uno');await userEvent.click(screen.getByRole('button',{name:'Calendarios'}))
  await userEvent.click(screen.getByRole('button',{name:'DESACTIVAR'}))
  expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('1 operaciones'))
  await waitFor(()=>expect(called).toBe(true))
})

test('fecha efectiva usa zona IANA cerca del cambio de día',()=>{
  const instant=new Date('2026-10-22T01:30:00Z')
  expect(localDate('America/Argentina/Buenos_Aires',instant)).toBe('2026-10-21')
  expect(localDate('Asia/Tokyo',instant)).toBe('2026-10-22')
})

test('ventanas de distintas vigencias no se mezclan y el límite final es exclusivo',()=>{
  const records=[
    {id:'old',row_version:1,calendar_id:ids.calendar,valid_from:'2026-01-01',valid_to:'2026-10-21'},
    {id:'current',row_version:1,calendar_id:ids.calendar,valid_from:'2026-10-21',valid_to:'2026-11-01'},
    {id:'future',row_version:1,calendar_id:ids.calendar,valid_from:'2026-11-01',valid_to:null},
  ]
  expect(windowsAt(records,ids.calendar,'2026-10-21').map(r=>r.id)).toEqual(['current'])
  expect(windowsAt(records,ids.calendar,'2026-11-01').map(r=>r.id)).toEqual(['future'])
})
