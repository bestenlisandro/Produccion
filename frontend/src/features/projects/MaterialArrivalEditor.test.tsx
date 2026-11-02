import {QueryClient,QueryClientProvider} from '@tanstack/react-query'
import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router'
import {beforeEach,test,expect,vi} from 'vitest'
import {http,HttpResponse,server} from '../../test/server'
import {ProductEditor} from './ProductEditor'
import {editorFixture,editorOptions,editorIds} from '../../test/productEditorFixture'
import fixtures from '../../test/materialArrivalFixture.json'

let data:any,saves:any[],previews:any[]
beforeEach(()=>{
 data=structuredClone(editorFixture);saves=[];previews=[];vi.spyOn(window,'confirm').mockReturnValue(true)
 server.use(
  http.get('/api/product-definition/options',()=>HttpResponse.json({...editorOptions,operations:[...editorOptions.operations,...fixtures.stages]})),
  http.get('/api/product-definition/material-arrival-routes',()=>HttpResponse.json(fixtures.catalog)),
  http.get('/api/projects/:id/product-definition',()=>HttpResponse.json(data)),
  http.post('/api/product-definition/material-arrival-preview',async({request})=>{const body:any=await request.json();previews.push(body);return HttpResponse.json(fixtures.previews[body.route_code.slice(-1) as '1'|'3'|'5'])}),
  http.put('/api/projects/:id/product-definition',async({request})=>{const body:any=await request.json();saves.push(body);data={...data,lots:body.lots,row_version:data.row_version+1};return HttpResponse.json(data)})
 )
})
async function show(){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><MemoryRouter><ProductEditor projectId={editorIds.project}/></MemoryRouter></QueryClientProvider>);await screen.findByRole('heading',{name:'Definición productiva'})}
async function configure(){await userEvent.click(screen.getByRole('button',{name:'CONFIGURAR LLEGADA DEL MATERIAL'}));await screen.findByLabelText('Cómo llega el material')}

test('cinco rutas con nombres humanos y resumen; opciones según matriz reparada',async()=>{
 await show();await configure()
 const selector=screen.getByLabelText('Cómo llega el material')
 expect(selector.children).toHaveLength(5)
 await userEvent.selectOptions(selector,'MATERIAL_ROUTE_3')
 expect(screen.getByText('Melaminas: Corte → Pegado → procesados. Fondos: Corte independiente.')).toBeVisible()
 expect(screen.getByLabelText('Ranurado · Melamina 18 mm · según proyecto')).not.toBeChecked()
 expect(screen.queryByLabelText('Ranurado · Melamina 15 mm · según proyecto')).not.toBeInTheDocument()
 await userEvent.selectOptions(selector,'MATERIAL_ROUTE_2')
 expect(screen.queryByLabelText('Múltiple · Melamina 12 mm · según proyecto')).not.toBeInTheDocument()
})

test('materiales y opcionales sólo se aplican al regenerar con confirmación explícita',async()=>{
 await show();await configure()
 await userEvent.click(screen.getByLabelText('Múltiple · Melamina 15 mm · según proyecto'))
 await userEvent.click(screen.getByLabelText('Incluir Fondo 5,5 mm'))
 expect(screen.getByLabelText('Nombre de operación')).toHaveValue('Corte')
 vi.mocked(window.confirm).mockReturnValue(false)
 await userEvent.click(screen.getByRole('button',{name:'REGENERAR DESDE RUTA'}))
 expect(previews).toHaveLength(0)
 expect(screen.getByLabelText('Nombre de operación')).toHaveValue('Corte')
 vi.mocked(window.confirm).mockReturnValue(true)
 await userEvent.click(screen.getByRole('button',{name:'REGENERAR DESDE RUTA'}))
 await waitFor(()=>expect(previews).toHaveLength(1))
 expect(previews[0].optional_process_codes).toEqual(['MUL-15'])
 expect(previews[0].materials).not.toContain('055')
 expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('cambios manuales'))
})

test('Caso 3 sugiere operaciones, conserva edición manual y guarda selección del lote',async()=>{
 await show();await configure();await userEvent.selectOptions(screen.getByLabelText('Cómo llega el material'),'MATERIAL_ROUTE_3')
 await userEvent.click(screen.getByRole('button',{name:'REGENERAR DESDE RUTA'}))
 await waitFor(()=>expect(screen.getAllByLabelText('Nombre de operación').some(e=>(e as HTMLInputElement).value==='Pegado de cantos · 15 mm')).toBe(true))
 expect(screen.getAllByLabelText('Nombre de operación').find(e=>(e as HTMLInputElement).value==='Corte · Fondo 3 mm')!).toBeVisible()
 expect(screen.getByRole('button',{name:'CONGELAR DEFINICIÓN'})).toBeDisabled()
 const name=screen.getAllByLabelText('Nombre de operación').find(e=>(e as HTMLInputElement).value==='Múltiple · 18 mm')!;await userEvent.clear(name);await userEvent.type(name,'Múltiple manual')
 await userEvent.click(screen.getByRole('button',{name:'GUARDAR BORRADOR'}))
 await waitFor(()=>expect(saves).toHaveLength(1))
 expect(saves[0].lots[0].material_arrival.route_code).toBe('MATERIAL_ROUTE_3')
 expect(saves[0].lots[0].operations.some((o:any)=>o.name==='Múltiple manual')).toBe(true)
})

test('cambiar ruta no destruye operaciones ni guarda una ruta no aplicada',async()=>{
 await show();await configure();await userEvent.selectOptions(screen.getByLabelText('Cómo llega el material'),'MATERIAL_ROUTE_5')
 expect(screen.getByLabelText('Nombre de operación')).toHaveValue('Corte')
 await userEvent.click(screen.getByRole('button',{name:'GUARDAR BORRADOR'}));await waitFor(()=>expect(saves).toHaveLength(1))
 expect(saves[0].lots[0].material_arrival).toBeUndefined()
})

test('frozen no presenta selector ni regeneración',async()=>{
 data.status='frozen';await show()
 expect(screen.queryByRole('button',{name:'CONFIGURAR LLEGADA DEL MATERIAL'})).not.toBeInTheDocument()
 expect(screen.queryByLabelText('Cómo llega el material')).not.toBeInTheDocument()
})

test('error de generación conserva el trabajo manual',async()=>{
 server.use(http.post('/api/product-definition/material-arrival-preview',()=>HttpResponse.json({error:{code:'INVALID_PRODUCT_DEFINITION',message:'Falta la etapa activa ARMADO.'}},{status:400})))
 await show();await configure();await userEvent.click(screen.getByRole('button',{name:'REGENERAR DESDE RUTA'}))
 await screen.findByRole('alert');expect(screen.getByLabelText('Nombre de operación')).toHaveValue('Corte')
})
