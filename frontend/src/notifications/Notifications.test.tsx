import {act,render,screen} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {afterEach,expect,test,vi} from 'vitest'
import {MemoryRouter,Routes,Route,Link} from 'react-router'
import {Notifications} from './Notifications'
import {notify,clearNotices,getNotices} from './store'
import {actionFor,completedAction} from './actions'
import {request,safeErrorMessage} from '../api/client'
import {http,HttpResponse,server} from '../test/server'

afterEach(()=>{clearNotices();vi.useRealTimers()})

test('success es accesible, no roba foco, se cierra y expira',async()=>{
  vi.useFakeTimers();render(<><input aria-label="Campo"/><Notifications/></>)
  screen.getByLabelText('Campo').focus()
  act(()=>notify('success','Guardado.','one'))
  expect(screen.getByRole('status')).toHaveTextContent('Guardado.')
  expect(screen.getByRole('status')).toHaveAttribute('aria-live','polite')
  expect(screen.getByLabelText('Campo')).toHaveFocus()
  act(()=>vi.advanceTimersByTime(6000));expect(screen.queryByRole('status')).not.toBeInTheDocument()
  act(()=>notify('error','No se pudo guardar.','two'))
  expect(screen.getByRole('alert')).toHaveAttribute('aria-live','assertive')
  act(()=>vi.advanceTimersByTime(20000));expect(screen.getByRole('alert')).toBeInTheDocument()
  act(()=>screen.getByRole('button',{name:'Cerrar notificación'}).click())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

test('no anuncia éxito mientras el backend no responde',async()=>{
  let finish!:()=>void
  const pending=new Promise<void>(resolve=>{finish=resolve})
  server.use(http.put('/api/projects/one/product-definition',async()=>{await pending;return HttpResponse.json({errors:[]})}))
  render(<Notifications/>)
  const response=request('/projects/one/product-definition',{method:'PUT',body:'{}'},'same-key')
  expect(screen.queryByText('Borrador guardado correctamente.')).not.toBeInTheDocument()
  await act(async()=>{finish();await response})
  expect(screen.getByRole('status')).toHaveTextContent('Borrador guardado correctamente.')
})

test('error técnico muestra error sin success, SQL, UUID ni stack trace',async()=>{
  server.use(http.put('/api/projects/one/product-definition',()=>HttpResponse.json({error:{message:'Traceback psycopg SELECT password FROM audit; 11111111-1111-4111-8111-111111111111'}},{status:500})))
  render(<Notifications/>)
  let caught:Error|undefined
  await act(async()=>{try{await request('/projects/one/product-definition',{method:'PUT'})}catch(error){caught=error as Error}})
  expect(screen.getByRole('alert')).toHaveTextContent('No se pudo guardar el borrador.')
  expect(screen.queryByRole('status')).not.toBeInTheDocument()
  expect(caught?.message).not.toMatch(/Traceback|psycopg|SELECT|11111111/)
  expect(document.body.textContent).not.toMatch(/Traceback|psycopg|SELECT|11111111/)
  expect(safeErrorMessage(409,'SQLSTATE 42501')).not.toContain('42501')
  expect(safeErrorMessage(409,'Proyecto 11111111-1111-4111-8111-111111111111 cambió.')).toBe('Proyecto referencia interna cambió.')
})

test('validación devuelve success o warning y freeze tiene confirmación propia',()=>{
  render(<Notifications/>)
  act(()=>completedAction('/projects/one/product-definition/validate','POST',{}, {errors:['Falta una fase.']}))
  expect(screen.getByRole('status')).toHaveTextContent('Hay errores que deben corregirse antes de congelar.')
  act(()=>completedAction('/projects/one/product-definition/validate','POST',{}, {errors:[]}))
  expect(screen.getAllByRole('status')).toHaveLength(1)
  expect(screen.getByRole('status')).toHaveTextContent('Definición validada correctamente.')
  act(()=>completedAction('/projects/one/product-definition/freeze','POST',{},{}))
  expect(screen.getByText('Revisión congelada correctamente.')).toBeInTheDocument()
})

test('feedback sobrevive a navegación al Gantt',async()=>{
  render(<MemoryRouter><Notifications/><Routes><Route path="/" element={<Link to="/planning/gantt">ABRIR PLANIFICACIÓN</Link>}/><Route path="/planning/gantt" element={<h1>Gantt</h1>}/></Routes></MemoryRouter>)
  act(()=>completedAction('/projects/one/simulations','POST',{}, {complete:true}))
  await userEvent.click(screen.getByRole('link',{name:'ABRIR PLANIFICACIÓN'}))
  expect(screen.getByRole('heading',{name:'Gantt'})).toBeInTheDocument()
  expect(screen.getByRole('status')).toHaveTextContent('Simulación generada correctamente.')
})

test('retry exitoso sustituye el error y conserva sólo tres avisos',()=>{
  act(()=>{notify('error','Error anterior.','save');notify('success','Guardado.','save')})
  expect(getNotices().map(n=>n.kind)).toEqual(['success'])
  act(()=>{notify('info','Uno.','1');notify('warning','Dos.','2');notify('success','Tres.','3')})
  expect(getNotices()).toHaveLength(3)
})

test.each([
  ['/customers','POST','Cliente creado correctamente.'],
  ['/projects/one/release','POST','Proyecto liberado a planificación.'],
  ['/projects/one/measurement','POST','Medición registrada correctamente.'],
  ['/projects/one/replanteo','POST','Replanteo registrado correctamente.'],
  ['/projects/one/installation-location','PATCH','Ubicación actualizada correctamente.'],
  ['/scenarios/one/accept','POST','Nuevo plan confirmado.'],
  ['/projects/one/product-definition/new-revision','POST','Nueva revisión creada correctamente.'],
])('mensaje de acción %s', (path,method,message)=>{expect(actionFor(path,method).success).toBe(message)})
