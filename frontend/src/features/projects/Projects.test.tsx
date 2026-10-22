import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { render,screen,waitFor,within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter,RouterProvider } from 'react-router'
import { beforeEach,test,expect,vi } from 'vitest'
import { http,HttpResponse,server } from '../../test/server'
import { ProjectsPage,NewProjectPage,ProjectDetailPage } from './Projects'
import { projectFixture as fixture,projectOptions,projectIds } from '../../test/projectIntakeFixture'

function renderPage(path='/projects'){
  const router=createMemoryRouter([{path:'/projects',Component:ProjectsPage},{path:'/projects/new',Component:NewProjectPage},{path:'/projects/:projectId',Component:ProjectDetailPage}],{initialEntries:[path]})
  return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><RouterProvider router={router}/></QueryClientProvider>)
}
beforeEach(()=>{
  vi.spyOn(window,'confirm').mockReturnValue(true)
  server.use(http.get('/api/projects',()=>HttpResponse.json([fixture])),http.get('/api/project-intake/options',()=>HttpResponse.json(projectOptions)),http.get('/api/projects/:id',()=>HttpResponse.json(fixture)))
})

test('lista proyectos con cliente, prioridad y fechas separadas',async()=>{
  renderPage();expect(screen.getByRole('status')).toHaveTextContent('Cargando proyectos')
  expect(await screen.findByRole('link',{name:'Cocina Central'})).toBeInTheDocument()
  expect(within(screen.getByRole('article')).getByText('Cliente Uno')).toBeInTheDocument();expect(screen.getByText('Estimada por planificación: —')).toBeInTheDocument()
})
test('empty invita a crear sin simular datos',async()=>{
  server.use(http.get('/api/projects',()=>HttpResponse.json([])));renderPage()
  expect(await screen.findByText('No hay proyectos cargados.')).toBeInTheDocument()
  expect(screen.getByRole('link',{name:'NUEVO PROYECTO'})).toBeInTheDocument()
})
test('error y retry recuperan listado',async()=>{
  let count=0;server.use(http.get('/api/projects',()=>++count===1?HttpResponse.json({},{status:500}):HttpResponse.json([fixture])))
  renderPage();await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR'}));expect(await screen.findByRole('link',{name:'Cocina Central'})).toBeInTheDocument()
})
test.each(['sin coincidencia','P-NONE','Cliente inexistente'])('búsqueda por referencia código y cliente filtra %s',async(search)=>{
  renderPage();await screen.findByRole('link',{name:'Cocina Central'});await userEvent.type(screen.getByLabelText('Buscar proyecto, código o cliente'),search)
  expect(screen.queryByRole('link',{name:'Cocina Central'})).not.toBeInTheDocument();expect(screen.getByText('No hay proyectos que coincidan con los filtros.')).toBeInTheDocument()
})
test.each([['Estado','archived'],['Prioridad','HIGH'],['Comprometida desde','2027-01-01'],['Comprometida hasta','2026-01-01']])('filtro %s se aplica',async(label,value)=>{
  renderPage();await screen.findByRole('link',{name:'Cocina Central'});const field=screen.getByLabelText(label,{exact:true})
  if(field.tagName==='SELECT')await userEvent.selectOptions(field,value);else await userEvent.type(field,value)
  expect(screen.queryByRole('link',{name:'Cocina Central'})).not.toBeInTheDocument()
})

async function fillNew(){
  await screen.findByLabelText('Código del proyecto');await userEvent.type(screen.getByLabelText('Código del proyecto'),'P-NEW')
  await userEvent.type(screen.getByLabelText('Nombre / referencia'),'Proyecto Nuevo');await userEvent.selectOptions(screen.getByLabelText('Cliente',{exact:true}),projectIds.customer)
  await userEvent.type(screen.getByLabelText('Fecha comprometida'),'2026-12-20')
}
test('alta simple valida campos sin pedir definición industrial',async()=>{
  renderPage('/projects/new');await screen.findByLabelText('Código del proyecto')
  expect(screen.getByRole('button',{name:'GUARDAR'})).toBeDisabled();expect(screen.queryByLabelText(/operación|duración|recurso/i)).not.toBeInTheDocument()
})
test('alta exitosa navega a detalle',async()=>{
  let body:any;server.use(http.post('/api/projects',async({request})=>{body=await request.json();return HttpResponse.json({...fixture,...body},{status:201})}))
  renderPage('/projects/new');await fillNew();await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}))
  expect(await screen.findByRole('heading',{name:'Resumen'})).toBeInTheDocument();expect(body).toMatchObject({code:'P-NEW',name:'Proyecto Nuevo',priority_id:projectIds.normal})
})
test('error backend conserva alta e inputs',async()=>{
  server.use(http.post('/api/projects',()=>HttpResponse.json({error:{message:'No se pudo validar el cliente'}},{status:400})))
  renderPage('/projects/new');await fillNew();await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo validar el cliente');expect(screen.getByLabelText('Nombre / referencia')).toHaveValue('Proyecto Nuevo')
})
test('reintento incierto conserva command key y cuerpo',async()=>{
  const keys:(string|null)[]=[],bodies:unknown[]=[]
  server.use(http.post('/api/projects',async({request})=>{keys.push(request.headers.get('Idempotency-Key'));bodies.push(await request.json());return keys.length===1?HttpResponse.json({},{status:503}):HttpResponse.json(fixture,{status:201})}))
  renderPage('/projects/new');await fillNew();await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}));await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR GUARDADO'}))
  await screen.findByRole('heading',{name:'Resumen'});expect(keys[1]).toBe(keys[0]);expect(bodies[1]).toEqual(bodies[0])
})
test('detalle separa fechas, medición, definición y planificación',async()=>{
  renderPage('/projects/'+fixture.id);await screen.findByRole('heading',{name:'Resumen'})
  for(const heading of ['Cliente / obra','Fechas','Medición / replanteo','Estado','Definición productiva','Planificación'])expect(screen.getByRole('heading',{name:heading})).toBeInTheDocument()
  expect(screen.getByText('Todavía no definida')).toBeInTheDocument();expect(screen.getByRole('button',{name:'DEFINIR PRODUCCIÓN'})).toBeEnabled()
  expect(screen.getByText('Sin trabajo planificable liberado.')).toBeInTheDocument()
})
test('edición guarda prioridad y fecha con row_version',async()=>{
  let body:any;server.use(http.patch('/api/projects/:id',async({request})=>{body=await request.json();return HttpResponse.json({project:{...fixture,priority_code:'HIGH'},idempotent_replay:false})}))
  renderPage('/projects/'+fixture.id);await userEvent.click(await screen.findByRole('button',{name:'EDITAR PROYECTO'}))
  await userEvent.selectOptions(screen.getByLabelText('Prioridad del proyecto'),projectIds.high)
  await userEvent.clear(screen.getByLabelText('Fecha comprometida'));await userEvent.type(screen.getByLabelText('Fecha comprometida'),'2026-12-24')
  await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}));await waitFor(()=>expect(body).toMatchObject({priority_id:projectIds.high,committed_date:'2026-12-24',expected_row_version:1}))
})
test('409 mantiene formulario y permite actualizar explícitamente',async()=>{
  server.use(http.patch('/api/projects/:id',()=>HttpResponse.json({error:{code:'PROJECT_INTAKE_VERSION_CONFLICT',message:'Conflicto'}},{status:409})))
  renderPage('/projects/'+fixture.id);await userEvent.click(await screen.findByRole('button',{name:'EDITAR PROYECTO'}));await userEvent.type(screen.getByLabelText('Nombre / referencia'),' Editado')
  await userEvent.click(screen.getByRole('button',{name:'GUARDAR'}));expect(await screen.findByRole('alert')).toHaveTextContent('El proyecto cambió desde que lo abriste')
  expect(screen.getByLabelText('Nombre / referencia')).toHaveValue('Cocina Central Editado')
  await userEvent.click(screen.getByRole('button',{name:'ACTUALIZAR INFORMACIÓN'}));expect(await screen.findByRole('heading',{name:'Resumen'})).toBeInTheDocument()
})
test.each([['Medición','measurement'],['Replanteo','replanteo']])('registra %s como hecho, sin fecha prevista',async(label,kind)=>{
  let body:any;server.use(http.post(`/api/projects/:id/${kind}`,async({request})=>{body=await request.json();return HttpResponse.json({project:fixture,idempotent_replay:false})}))
  renderPage('/projects/'+fixture.id);await screen.findByRole('heading',{name:'Resumen'})
  const form=screen.getByRole('form',{name:label})
  await userEvent.clear(within(form).getByLabelText(`Fecha realizada de ${label.toLowerCase()}`));await userEvent.type(within(form).getByLabelText(`Fecha realizada de ${label.toLowerCase()}`),'2026-09-01T10:00')
  await userEvent.type(within(form).getByLabelText(`Observación de ${label.toLowerCase()}`),'Conforme');await userEvent.click(within(form).getByRole('button'))
  await waitFor(()=>expect(body).toMatchObject({occurred_at:'2026-09-01T13:00:00.000Z',notes:'Conforme',expected_row_version:1}))
})
test('archiva sin borrar detalle y conserva historia',async()=>{
  let current={...fixture}
  server.use(http.get('/api/projects/:id',()=>HttpResponse.json(current)),http.post('/api/projects/:id/status',()=>{current={...fixture,status:'archived'};return HttpResponse.json({project:current,idempotent_replay:false})}))
  renderPage('/projects/'+fixture.id);await userEvent.click(await screen.findByRole('button',{name:'ARCHIVAR PROYECTO'}));expect(await screen.findByText('Cambios guardados.')).toBeInTheDocument()
  expect(screen.queryByRole('button',{name:'EDITAR PROYECTO'})).not.toBeInTheDocument();expect(screen.getByRole('heading',{name:'Cliente / obra'})).toBeInTheDocument()
})
test('proyecto planificado ofrece enlaces sin duplicar Gantt',async()=>{
  server.use(http.get('/api/projects/:id',()=>HttpResponse.json({...fixture,plannable:true,definition_revision_no:2,operation_ids:[projectIds.operation],planned_operation_ids:[projectIds.operation]})))
  renderPage('/projects/'+fixture.id);expect(await screen.findByRole('link',{name:'ABRIR GANTT'})).toHaveAttribute('href','/planning/gantt')
  expect(screen.getByRole('link',{name:'OPERACIÓN 1'})).toHaveAttribute('href',`/operations/${projectIds.operation}`)
})
