import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor,within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { beforeEach,test,expect } from 'vitest'
import { http,HttpResponse,server } from '../../test/server'
import { NewProjectPage } from './Projects'
import { projectOptions,projectIds } from '../../test/projectIntakeFixture'

const customer={id:'aabbccdd-1111-4111-8111-112233445566',display_name:'Nico del Castillo',phone:null,email:null}
let options:typeof projectOptions
let calls:{body:any;key:string|null}[]
let optionReads:number
function show(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MemoryRouter><NewProjectPage/></MemoryRouter></QueryClientProvider>)}
async function open(){show();await userEvent.click(await screen.findByRole('button',{name:'+ NUEVO CLIENTE'}));return screen.getByRole('dialog',{name:'Nuevo cliente'})}
beforeEach(()=>{
 options={...structuredClone(projectOptions),customers:[]};calls=[];optionReads=0
 server.use(http.get('/api/project-intake/options',()=>{optionReads++;return HttpResponse.json(options)}),http.post('/api/customers',async({request})=>{
  calls.push({body:await request.json(),key:request.headers.get('Idempotency-Key')})
  options.customers=[{id:customer.id,name:customer.display_name,code:null}]
  return HttpResponse.json({customer,idempotent_replay:false},{status:201})
 }))
})

test('selector vacío permite abrir y cancelar el alta mínima',async()=>{
 const dialog=await open()
 expect(screen.getByLabelText('Cliente',{exact:true})).toHaveValue('')
 expect(within(dialog).getByLabelText('Nombre / razón social')).toBeRequired()
 expect(within(dialog).getByLabelText('Teléfono (opcional)')).not.toBeRequired()
 expect(within(dialog).getByLabelText('Email (opcional)')).not.toBeRequired()
 await userEvent.click(within(dialog).getByRole('button',{name:'CANCELAR CLIENTE'}))
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(calls).toHaveLength(0)
})

test('crea sólo con nombre, refresca y selecciona sin perder el proyecto',async()=>{
 show();await screen.findByRole('button',{name:'+ NUEVO CLIENTE'})
 await userEvent.type(screen.getByLabelText('Código del proyecto'),'P-REAL')
 await userEvent.type(screen.getByLabelText('Nombre / referencia'),'Cocina real')
 await userEvent.selectOptions(screen.getByLabelText('Prioridad del proyecto'),projectIds.high)
 await userEvent.type(screen.getByLabelText('Fecha comprometida'),'2026-12-24')
 await userEvent.type(screen.getByLabelText('Notas'),'Medidas confirmadas')
 await userEvent.click(screen.getByRole('button',{name:'+ NUEVO CLIENTE'}))
 await userEvent.type(screen.getByLabelText('Nombre / razón social'),'Nico del Castillo')
 await userEvent.click(screen.getByRole('button',{name:'CREAR CLIENTE'}))
 await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
 expect(calls[0].body).toEqual({display_name:'Nico del Castillo',phone:null,email:null})
 expect(calls[0].key).toBeTruthy()
 expect(screen.getByLabelText('Cliente',{exact:true})).toHaveValue(customer.id)
 expect(screen.getByLabelText('Código del proyecto')).toHaveValue('P-REAL')
 expect(screen.getByLabelText('Nombre / referencia')).toHaveValue('Cocina real')
 expect(screen.getByLabelText('Prioridad del proyecto')).toHaveValue(projectIds.high)
 expect(screen.getByLabelText('Fecha comprometida')).toHaveValue('2026-12-24')
 expect(screen.getByLabelText('Notas')).toHaveValue('Medidas confirmadas')
 await waitFor(()=>expect(optionReads).toBeGreaterThan(1))
})

test('teléfono y email suministrados se envían sin campos adicionales',async()=>{
 await open();await userEvent.type(screen.getByLabelText('Nombre / razón social'),'Nico del Castillo')
 await userEvent.type(screen.getByLabelText('Teléfono (opcional)'),'12345')
 await userEvent.type(screen.getByLabelText('Email (opcional)'),'nico@example.test')
 await userEvent.click(screen.getByRole('button',{name:'CREAR CLIENTE'}))
 await waitFor(()=>expect(calls[0].body).toEqual({display_name:'Nico del Castillo',phone:'12345',email:'nico@example.test'}))
})

test('error incierto conserva formulario e intención; retry no duplica',async()=>{
 server.use(http.post('/api/customers',async({request})=>{
  calls.push({body:await request.json(),key:request.headers.get('Idempotency-Key')})
  if(calls.length===1)return HttpResponse.json({},{status:500})
  options.customers=[{id:customer.id,name:customer.display_name,code:null}]
  return HttpResponse.json({customer,idempotent_replay:true},{status:201})
 }))
 await open();await userEvent.type(screen.getByLabelText('Nombre / razón social'),'Nico del Castillo')
 await userEvent.click(screen.getByRole('button',{name:'CREAR CLIENTE'}))
 const retry=await screen.findByRole('button',{name:'REINTENTAR CREACIÓN'})
 expect(screen.getByRole('dialog')).toBeInTheDocument()
 expect(screen.getByLabelText('Nombre / razón social')).toHaveValue('Nico del Castillo')
 expect(screen.getByLabelText('Nombre / razón social')).toBeDisabled()
 await userEvent.click(retry)
 await waitFor(()=>expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
 expect(calls).toHaveLength(2);expect(calls[1]).toEqual(calls[0])
 expect(screen.getByLabelText('Cliente',{exact:true})).toHaveValue(customer.id)
})

test('error de validación deja corregir sin cerrar ni perder los campos',async()=>{
 server.use(http.post('/api/customers',()=>HttpResponse.json({detail:[]},{status:422})))
 await open();await userEvent.type(screen.getByLabelText('Nombre / razón social'),'Nico del Castillo')
 await userEvent.click(screen.getByRole('button',{name:'CREAR CLIENTE'}))
 expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('Revisá el nombre')
 expect(screen.getByLabelText('Nombre / razón social')).toHaveValue('Nico del Castillo')
 expect(screen.getByLabelText('Nombre / razón social')).toBeEnabled()
})

test('permite usar el cliente coincidente sin enviar un alta duplicada',async()=>{
 options.customers=[{id:customer.id,name:customer.display_name,code:null}]
 await open();await userEvent.type(screen.getByLabelText('Nombre / razón social'),'nico del')
 await userEvent.click(screen.getByRole('button',{name:'USAR CLIENTE EXISTENTE: Nico del Castillo'}))
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(calls).toHaveLength(0)
 expect(screen.getByLabelText('Cliente',{exact:true})).toHaveValue(customer.id)
})

test('refresco fallido conserva selección y borrador después del alta exitosa',async()=>{
 server.use(http.get('/api/project-intake/options',()=>++optionReads===1?HttpResponse.json(options):HttpResponse.json({},{status:500})))
 show();await userEvent.type(await screen.findByLabelText('Código del proyecto'),'NO-PERDER')
 await userEvent.click(screen.getByRole('button',{name:'+ NUEVO CLIENTE'}))
 await userEvent.type(screen.getByLabelText('Nombre / razón social'),'Nico del Castillo')
 await userEvent.click(screen.getByRole('button',{name:'CREAR CLIENTE'}))
 await waitFor(()=>expect(optionReads).toBeGreaterThan(1))
 expect(screen.getByLabelText('Código del proyecto')).toHaveValue('NO-PERDER')
 expect(screen.getByLabelText('Cliente',{exact:true})).toHaveValue(customer.id)
})
