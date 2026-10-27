import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import {render,screen,waitFor,within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router'
import {beforeEach,test,expect,vi} from 'vitest'
import {http,HttpResponse,server} from '../../test/server'
import {ProductEditor} from './ProductEditor'
import {editorFixture,editorOptions,editorIds} from '../../test/productEditorFixture'
let data:any,calls:any[]
function show(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><MemoryRouter><ProductEditor projectId={editorIds.project}/></MemoryRouter></QueryClientProvider>)}
async function ready(){show();await screen.findByRole('heading',{name:'Definición productiva'})}
const click=async(name:string)=>userEvent.click(screen.getByRole('button',{name}))
beforeEach(()=>{
 data=structuredClone(editorFixture);calls=[];vi.spyOn(window,'confirm').mockReturnValue(true)
 server.use(http.get('/api/product-definition/options',()=>HttpResponse.json(editorOptions)),http.get('/api/projects/:id/product-definition',()=>HttpResponse.json(data)),http.put('/api/projects/:id/product-definition',async({request})=>{const body:any=await request.json();calls.push({body,key:request.headers.get('Idempotency-Key')});data={...data,lots:body.lots,row_version:data.row_version+1};return HttpResponse.json(data)}),http.post('/api/projects/:id/product-definition/:action',async({params,request})=>{calls.push({action:params.action,body:await request.json()});data.row_version++;if(params.action==='freeze')data.status='frozen';if(params.action==='new-revision')data.status='draft';return HttpResponse.json(data)}))
})
test('loading de definición',async()=>{show();expect(screen.getByRole('status')).toHaveTextContent('Cargando definición');await screen.findByRole('heading',{name:'Definición productiva'})})
test('definición vacía orienta a agregar lote',async()=>{data.lots=[];data.status='empty';await ready();expect(screen.getByText('Agregá un lote para comenzar.')).toBeInTheDocument()})
test('crear múltiples lotes',async()=>{await ready();await click('AGREGAR LOTE');expect(screen.getAllByLabelText('Nombre del lote')).toHaveLength(2)})
test('editar nombre de lote se guarda',async()=>{await ready();await userEvent.clear(screen.getByLabelText('Nombre del lote'));await userEvent.type(screen.getByLabelText('Nombre del lote'),'Armario');await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].name).toBe('Armario'))})
test('cantidad y unidad',async()=>{await ready();await userEvent.clear(screen.getByLabelText('Cantidad'));await userEvent.type(screen.getByLabelText('Cantidad'),'4');await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].quantity).toBe(4))})
test('ruta publicada usa maestros',async()=>{await ready();expect(screen.getByRole('option',{name:'Ruta de muebles'})).toBeInTheDocument();expect(screen.getByLabelText('Ruta publicada')).toHaveValue(editorIds.route)})
test('agregar operación no inventa nombres',async()=>{await ready();await click('AGREGAR OPERACIÓN');expect(screen.getAllByLabelText('Nombre de operación')[1]).toHaveValue('');expect(screen.queryByLabelText('Tipo de operación')).not.toBeInTheDocument()})
test('editar operación',async()=>{await ready();await userEvent.clear(screen.getByLabelText('Nombre de operación'));await userEvent.type(screen.getByLabelText('Nombre de operación'),'Corte especial');await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].operations[0].name).toBe('Corte especial'))})
test('duración canónica en minutos',async()=>{await ready();await userEvent.clear(screen.getByLabelText('Duración estimada (minutos)'));await userEvent.type(screen.getByLabelText('Duración estimada (minutos)'),'75');await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].operations[0].phases[0].original_estimate_minutes).toBe(75))})
test('centro requerido activo',async()=>{await ready();await click('AGREGAR RECURSO');expect(screen.getByLabelText('Centro de trabajo')).toHaveValue(editorIds.center)})
test('demanda de capacidad independiente',async()=>{await ready();await click('AGREGAR RECURSO');await userEvent.clear(screen.getByLabelText('Demanda de capacidad'));await userEvent.type(screen.getByLabelText('Demanda de capacidad'),'2');await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].operations[0].phases[0].physical_requirements[0].capacity_units).toBe(2))})
test('personas necesarias abstractas',async()=>{await ready();await click('AGREGAR HABILIDAD');await userEvent.clear(screen.getByLabelText('Personas necesarias'));await userEvent.type(screen.getByLabelText('Personas necesarias'),'2');await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].operations[0].phases[0].labor_requirements[0].min_people).toBe(2))})

test('instalación permite seis personas sin limitar otros procesos',async()=>{
 await ready();await click('AGREGAR HABILIDAD')
 const input=screen.getByLabelText('Personas necesarias')
 expect(input).not.toHaveAttribute('max')
 await userEvent.selectOptions(screen.getByLabelText('Clase de trabajo'),'installation')
 expect(input).toHaveAttribute('max','6')
 await userEvent.clear(input);await userEvent.type(input,'6');await click('GUARDAR BORRADOR')
 await waitFor(()=>expect(calls[0].body.lots[0].operations[0].phases[0].labor_requirements[0]).toMatchObject({min_people:6,max_people:6}))
})
test('skills se pueden agregar y quitar',async()=>{await ready();await click('AGREGAR HABILIDAD');expect(screen.getByLabelText('Habilidad requerida')).toHaveValue(editorIds.skill);await click('QUITAR HABILIDAD');expect(screen.queryByLabelText('Habilidad requerida')).not.toBeInTheDocument()})
test('recurso físico se selecciona por tipo',async()=>{await ready();await click('AGREGAR RECURSO');await userEvent.selectOptions(screen.getByLabelText('Recurso necesario (tipo)'),editorIds.resource);expect(screen.getByLabelText('Recurso necesario (tipo)')).toHaveValue(editorIds.resource)})
test('agregar múltiples fases',async()=>{await ready();await click('AGREGAR FASE');expect(screen.getAllByLabelText('Nombre de fase')).toHaveLength(2)})
test('editar nombre de fase',async()=>{await ready();await userEvent.clear(screen.getByLabelText('Nombre de fase'));await userEvent.type(screen.getByLabelText('Nombre de fase'),'Terminación');expect(screen.getByLabelText('Nombre de fase')).toHaveValue('Terminación')})
test('reordenar fases',async()=>{await ready();await click('AGREGAR FASE');await userEvent.type(screen.getAllByLabelText('Nombre de fase')[1],' segunda');await userEvent.click(screen.getAllByRole('button',{name:'SUBIR FASE'})[1]);expect(screen.getAllByLabelText('Nombre de fase')[0]).toHaveValue('Trabajo segunda')})
test('reordenar operaciones conserva independencia',async()=>{await ready();await click('AGREGAR OPERACIÓN');await userEvent.type(screen.getAllByLabelText('Nombre de operación')[1],' segunda');await userEvent.click(screen.getAllByRole('button',{name:'SUBIR OPERACIÓN'})[1]);await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls[0].body.lots[0].operations[0].name).toBe(' segunda'));expect(calls[0].body.lots[0].operations[1].predecessor_codes).toEqual([])})
test('eliminar operación de borrador',async()=>{await ready();await click('ELIMINAR OPERACIÓN');expect(screen.queryByLabelText('Nombre de operación')).not.toBeInTheDocument()})
test('eliminar fase de borrador',async()=>{await ready();await click('ELIMINAR FASE');expect(screen.queryByLabelText('Nombre de fase')).not.toBeInTheDocument()})
test('validar lista errores accionables',async()=>{data.errors=['Agregá al menos una fase con duración.'];await ready();expect(screen.getByRole('region',{name:'Errores de validación'})).toHaveTextContent('Agregá al menos una fase');expect(screen.getByRole('button',{name:'CONGELAR DEFINICIÓN'})).toBeDisabled();await click('VALIDAR');await waitFor(()=>expect(calls[0].action).toBe('validate'))})
test('freeze confirma y queda read-only',async()=>{await ready();await click('CONGELAR DEFINICIÓN');expect(window.confirm).toHaveBeenCalled();await screen.findByText('CONGELADA · Sólo lectura');expect(screen.queryByLabelText('Nombre del lote')).not.toBeInTheDocument()})
test('cancelar confirmación no congela',async()=>{vi.mocked(window.confirm).mockReturnValue(false);await ready();await click('CONGELAR DEFINICIÓN');expect(calls).toHaveLength(0)})
test('nueva revisión reabre borrador',async()=>{data.status='frozen';await ready();await click('CREAR NUEVA REVISIÓN');await screen.findByText('BORRADOR EDITABLE');expect(screen.getByLabelText('Nombre del lote')).toBeEnabled()})
test('409 visible conserva input y ofrece actualización',async()=>{server.use(http.put('/api/projects/:id/product-definition',()=>HttpResponse.json({error:{code:'PRODUCT_EDITOR_VERSION_CONFLICT',message:'La definición productiva cambió desde que la abriste. Actualizá antes de guardar.'}},{status:409})));await ready();await userEvent.type(screen.getByLabelText('Nombre del lote'),' nueva');await click('GUARDAR BORRADOR');await screen.findByRole('alert');expect(screen.getByLabelText('Nombre del lote')).toHaveValue('Cocina nueva');expect(screen.getByRole('button',{name:'ACTUALIZAR DEFINICIÓN'})).toBeInTheDocument()})
test('retry incierto conserva key y payload',async()=>{let attempts=0;const keys:string[]=[];server.use(http.put('/api/projects/:id/product-definition',async({request})=>{keys.push(request.headers.get('Idempotency-Key')!);return ++attempts===1?HttpResponse.json({error:{message:'Error temporal'}},{status:500}):HttpResponse.json(data)}));await ready();await click('GUARDAR BORRADOR');await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR GUARDADO'}));await waitFor(()=>expect(keys).toHaveLength(2));expect(keys[0]).toBe(keys[1])})
test('error de carga permite retry',async()=>{let count=0;server.use(http.get('/api/projects/:id/product-definition',()=>++count===1?HttpResponse.json({},{status:500}):HttpResponse.json(data)));show();await userEvent.click(await screen.findByRole('button',{name:'REINTENTAR'}));await screen.findByRole('heading',{name:'Definición productiva'})})
test('cambios sin guardar impiden freeze',async()=>{await ready();await click('AGREGAR FASE');expect(screen.getByRole('button',{name:'CONGELAR DEFINICIÓN'})).toBeDisabled();expect(screen.getByRole('button',{name:'VALIDAR'})).toBeDisabled()})


test('etapa fija y nombre libre; renumeración conserva IDs, fases y paralelismo',async()=>{
 const original=data.lots[0].operations[0];original.id='operation-funds';original.name='Corte de fondos'
 const second=structuredClone(original);second.id='operation-drawers';second.code='DRAWERS';second.name='Corte de cajones';data.lots[0].operations.push(second)
 const phase=structuredClone(original.phases)
 await ready()
 expect(screen.getByRole('heading',{name:'2. Corte'})).toBeInTheDocument()
 expect(screen.getByText('2.1 Corte de fondos')).toBeInTheDocument();expect(screen.getByText('2.2 Corte de cajones')).toBeInTheDocument()
 await userEvent.clear(screen.getAllByLabelText('Nombre de operación')[0]);await userEvent.type(screen.getAllByLabelText('Nombre de operación')[0],'Corte de fondos y laterales')
 expect(screen.getByRole('heading',{name:'2. Corte'})).toBeInTheDocument()
 await userEvent.click(screen.getAllByRole('button',{name:'SUBIR OPERACIÓN'})[1])
 expect(screen.getByText('2.1 Corte de cajones')).toBeInTheDocument();expect(screen.getByText('2.2 Corte de fondos y laterales')).toBeInTheDocument()
 await userEvent.click(screen.getAllByRole('button',{name:'ELIMINAR OPERACIÓN'})[0])
 expect(screen.getByText('2.1 Corte de fondos y laterales')).toBeInTheDocument()
 await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls).toHaveLength(1))
 const op=calls[0].body.lots[0].operations[0]
 expect(op.id).toBe('operation-funds');expect(op.name).toBe('Corte de fondos y laterales');expect(op.predecessor_codes).toEqual([]);expect(op.phases).toEqual(phase)
})

test('Armado conserva número 6 y cambiar etapa es explícito',async()=>{
 const options={...editorOptions,operations:[...editorOptions.operations,{id:'assembly-stage',code:'ARMADO',name:'Armado',display_order:6,status:'active'}]}
 server.use(http.get('/api/product-definition/options',()=>HttpResponse.json(options)))
 await ready();expect(screen.getByRole('heading',{name:'6. Armado'})).toBeInTheDocument()
 expect(screen.queryByLabelText('Tipo de operación')).not.toBeInTheDocument()
 await click('CAMBIAR ETAPA');await userEvent.selectOptions(screen.getByLabelText('Etapa de destino'),'assembly-stage')
 expect(screen.getByText('6.1 Corte')).toBeInTheDocument();expect(screen.queryByText('2.1 Corte')).not.toBeInTheDocument()
 await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls).toHaveLength(1));expect(calls[0].body.lots[0].operations[0].operation_definition_id).toBe('assembly-stage')
})

test('precedencias se eligen sin depender de la numeración',async()=>{
 const second=structuredClone(data.lots[0].operations[0]);second.code='NEXT';second.name='Corte siguiente';data.lots[0].operations.push(second)
 await ready();await userEvent.selectOptions(screen.getAllByLabelText('Operaciones precedentes')[1],'CUT')
 await userEvent.click(screen.getAllByRole('button',{name:'SUBIR OPERACIÓN'})[1]);await click('GUARDAR BORRADOR')
 await waitFor(()=>expect(calls).toHaveLength(1));expect(calls[0].body.lots[0].operations[0].predecessor_codes).toEqual(['CUT'])
})


test('fase nueva sin habilidad conserva personas al guardar, recargar y quitar la última skill',async()=>{
 data.lots[0].operations[0].phases=[]
 const first=show();await screen.findByRole('heading',{name:'Definición productiva'})
 await click('AGREGAR FASE')
 expect(screen.getByText(/Sin habilidad requerida/)).toBeInTheDocument()
 expect(screen.getByLabelText('Personas necesarias')).toHaveValue(1)
 await userEvent.clear(screen.getByLabelText('Personas necesarias'));await userEvent.type(screen.getByLabelText('Personas necesarias'),'2')
 await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls).toHaveLength(1))
 expect(calls[0].body.lots[0].operations[0].phases[0]).toMatchObject({required_people:2,labor_requirements:[]})
 first.unmount();await ready()
 expect(screen.getByLabelText('Personas necesarias')).toHaveValue(2)
 expect(screen.getByText(/Sin habilidad requerida/)).toBeInTheDocument()
 await click('AGREGAR HABILIDAD');expect(screen.getByLabelText('Habilidad requerida')).toHaveValue(editorIds.skill)
 expect(screen.queryByText(/Sin habilidad requerida/)).not.toBeInTheDocument()
 await click('QUITAR HABILIDAD')
 expect(screen.getByText(/Sin habilidad requerida/)).toBeInTheDocument();expect(screen.getByLabelText('Personas necesarias')).toHaveValue(2)
 await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls).toHaveLength(2))
 expect(calls[1].body.lots[0].operations[0].phases[0]).toMatchObject({required_people:2,labor_requirements:[]})
})

test('quitar última skill de fase antigua conserva su demanda humana',async()=>{
 data.lots[0].operations[0].phases[0].labor_requirements=[{skill_id:editorIds.skill,min_people:2,max_people:2,work_minutes:60,productivity_curve:{},is_mandatory:true}]
 await ready();expect(screen.getByLabelText('Personas necesarias')).toHaveValue(2)
 await click('QUITAR HABILIDAD');expect(screen.getByLabelText('Personas necesarias')).toHaveValue(2)
 await click('GUARDAR BORRADOR');await waitFor(()=>expect(calls).toHaveLength(1))
 expect(calls[0].body.lots[0].operations[0].phases[0]).toMatchObject({required_people:2,labor_requirements:[]})
})
