import {test,expect,type Page} from '@playwright/test'
import {editorFixture,editorOptions,editorIds,editorLot} from '../src/test/productEditorFixture'
import {projectFixture,projectOptions} from '../src/test/projectIntakeFixture'
async function setup(page:Page,empty=false){
 const data:any=structuredClone(editorFixture),project:any=structuredClone(projectFixture),calls:any[]=[];let conflict=false
 if(empty){data.lots=[];data.status='empty';data.errors=['Agregá al menos un lote productivo.']}
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname.replace('/api','')
  if(path.endsWith('/installations'))return route.fulfill({json:{project_id:projectFixture.id,project_code:projectFixture.code,project_name:projectFixture.name,customer_name:projectFixture.customer_name,row_version:1,timezone:'America/Argentina/Buenos_Aires',required:false,can_complete:false,completed:false,installations:[]}})
  if(path==='/product-definition/options')return route.fulfill({json:editorOptions})
  if(path==='/project-intake/options')return route.fulfill({json:projectOptions})
  if(path==='/projects'&&req.method()==='GET')return route.fulfill({json:[project]})
  if(path==='/projects'&&req.method()==='POST'){Object.assign(project,req.postDataJSON());return route.fulfill({status:201,json:project})}
  if(path===`/projects/${editorIds.project}`)return route.fulfill({json:project})
  if(!path.includes('/product-definition'))return route.fulfill({status:404,json:{}})
  if(req.method()==='GET')return route.fulfill({json:data})
  const body=req.postDataJSON(),action=path.split('/').at(-1);calls.push({action,body,key:req.headers()['idempotency-key']})
  if(conflict)return route.fulfill({status:409,json:{error:{code:'PRODUCT_EDITOR_VERSION_CONFLICT',message:'La definición productiva cambió desde que la abriste. Actualizá antes de guardar.'}}})
  if(req.method()==='PUT'){data.lots=body.lots;data.status='draft';data.errors=data.lots.length?data.lots.flatMap((l:any)=>l.operations.length?l.operations.filter((o:any)=>!o.phases.length).map(()=> 'Agregá al menos una fase con duración.'):['Agregá operaciones a la ruta.']):['Agregá al menos un lote productivo.']}
  if(action==='freeze'){data.status='frozen';project.plannable=true;project.definition_revision_no=data.revisions.length+1;data.revisions.unshift({id:crypto.randomUUID(),revision_no:data.revisions.length+1,created_at:new Date().toISOString(),lot_count:data.lots.length,operation_count:data.lots.reduce((n:number,l:any)=>n+l.operations.length,0),snapshot:{lots:structuredClone(data.lots)}})}
  if(action==='new-revision')data.status='draft'
  data.row_version++;return route.fulfill({json:data})
 })
 return {data,calls,setConflict:()=>{conflict=true}}
}
const url=`/projects/${editorIds.project}/product-definition`
async function open(page:Page){await page.goto(url);await expect(page.getByRole('heading',{name:'Definición productiva',exact:true})).toBeVisible()}
async function freeze(page:Page){page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'CONGELAR DEFINICIÓN',exact:true}).click();await expect(page.getByText('CONGELADA · Sólo lectura')).toBeVisible()}
test('A proyecto nuevo a lote ruta operaciones fases y guardado',async({page})=>{
 const {calls}=await setup(page,true);await page.goto('/projects/new');await page.getByLabel('Código del proyecto').fill('P-EDITOR');await page.getByLabel('Nombre / referencia').fill('Mueble a definir');await page.getByLabel('Cliente',{exact:true}).selectOption(projectOptions.customers[0].id);await page.getByRole('button',{name:'GUARDAR',exact:true}).click();await page.getByRole('button',{name:'DEFINIR PRODUCCIÓN'}).click()
 await page.getByRole('button',{name:'AGREGAR LOTE'}).click();await page.getByLabel('Nombre del lote').fill('Cocina');await page.getByRole('button',{name:'AGREGAR OPERACIÓN'}).click();await page.getByLabel('Nombre de operación').fill('Corte de fondos');await page.getByRole('button',{name:'AGREGAR FASE'}).click();await page.getByLabel('Duración estimada (minutos)').fill('45');await page.getByRole('button',{name:'AGREGAR HABILIDAD'}).click();await page.getByRole('button',{name:'AGREGAR RECURSO'}).click();await page.getByRole('button',{name:'GUARDAR BORRADOR'}).click();await expect(page.getByRole('button',{name:'CONGELAR DEFINICIÓN'})).toBeEnabled();expect(calls[0].key).toBeTruthy();expect(calls[0].body.lots[0].operations[0].phases[0].original_estimate_minutes).toBe(45)
})
test('B inválida informa errores y bloquea freeze',async({page})=>{await setup(page,true);await open(page);await page.getByRole('button',{name:'AGREGAR LOTE'}).click();await page.getByRole('button',{name:'GUARDAR BORRADOR'}).click();await expect(page.getByText('Agregá operaciones a la ruta.')).toBeVisible();await expect(page.getByRole('button',{name:'CONGELAR DEFINICIÓN'})).toBeDisabled()})
test('C confirmación freeze y read-only',async({page})=>{await setup(page);await open(page);await freeze(page);await expect(page.getByLabel('Nombre del lote')).toHaveCount(0);await expect(page.getByRole('button',{name:'CREAR NUEVA REVISIÓN'})).toBeEnabled()})
test('D nueva revisión conserva anterior',async({page})=>{const {data}=await setup(page);await open(page);await freeze(page);await page.getByRole('button',{name:'CREAR NUEVA REVISIÓN'}).click();await expect(page.getByLabel('Duración estimada (minutos)')).toBeEnabled();await page.getByLabel('Duración estimada (minutos)').fill('90');await page.getByRole('button',{name:'GUARDAR BORRADOR'}).click();await expect(page.getByRole('button',{name:'CONGELAR DEFINICIÓN'})).toBeEnabled();await freeze(page);expect(data.revisions).toHaveLength(2);expect(data.revisions[1].snapshot.lots[0].operations[0].phases[0].original_estimate_minutes).toBe(30);await page.getByText(/VER REVISIÓN 1/).click();await expect(page.getByText(/Trabajo: 30 minutos/)).toBeVisible()})
test('E congelada muestra elegibilidad',async({page})=>{await setup(page);await open(page);await freeze(page);await page.getByRole('link',{name:'← Volver al proyecto'}).click();await expect(page.getByText('Demanda con definición productiva disponible')).toBeVisible()})
test('F 409 conserva input',async({page})=>{const {setConflict}=await setup(page);await open(page);setConflict();await page.getByLabel('Nombre del lote').fill('Mi cocina');await page.getByRole('button',{name:'GUARDAR BORRADOR'}).click();await expect(page.getByRole('alert')).toContainText('La definición productiva cambió');await expect(page.getByLabel('Nombre del lote')).toHaveValue('Mi cocina')})
test('G benchmark responsive 5 lotes 50 operaciones 100 fases',async({page},info)=>{
 const {data}=await setup(page);data.lots=[]
 for(let li=0;li<5;li++){const l:any=structuredClone(editorLot);l.code=`L${li}`;l.name=`Lote ${li}`;l.operations=[];for(let oi=0;oi<10;oi++){const o=structuredClone(editorLot.operations[0]);o.code=`O${oi}`;o.name=`Operación ${oi}`;o.phases.push({...structuredClone(o.phases[0]),code:'FINISH'});l.operations.push(o)}data.lots.push(l)}
 const start=Date.now();await open(page);await expect(page.getByLabel('Nombre de fase')).toHaveCount(100);const elapsed=Date.now()-start;expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy();console.log(`PRODUCT_EDITOR_RENDER ${info.project.name}: ${elapsed}ms payload=${JSON.stringify(data).length}`);await page.screenshot({path:`test-results/product-editor-${info.project.name}.png`})
})


test('H etapas, nombres concretos, reordenamiento sin precedencias implícitas',async({page})=>{
 const {data,calls}=await setup(page)
 data.lots[0].operations[0].name='Corte de fondos'
 await open(page)
 const stage=page.getByRole('region',{name:'Etapa 2. Corte',exact:true})
 await expect(stage.getByRole('heading',{name:'2. Corte',exact:true})).toBeVisible()
 await page.getByLabel('Nombre de operación').fill('Corte de fondos y laterales')
 await expect(stage.getByRole('heading',{name:'2. Corte',exact:true})).toBeVisible()
 await stage.getByRole('button',{name:'AGREGAR OPERACIÓN',exact:true}).click()
 await page.getByLabel('Nombre de operación').nth(1).fill('Corte de cajones')
 await expect(page.getByText('2.2 Corte de cajones', {exact:true})).toBeVisible()
 await page.getByRole('button',{name:'SUBIR OPERACIÓN',exact:true}).nth(1).click()
 await expect(page.getByText('2.1 Corte de cajones',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'ELIMINAR OPERACIÓN',exact:true}).first().click()
 await expect(page.getByText('2.1 Corte de fondos y laterales',{exact:true})).toBeVisible()
 await page.getByRole('button',{name:'GUARDAR BORRADOR',exact:true}).click()
 expect(calls[0].body.lots[0].operations[0].predecessor_codes).toEqual([])
 expect(calls[0].body.lots[0].operations[0].name).toBe('Corte de fondos y laterales')
 expect(calls[0].body.lots[0].operations[0].phases[0].code).toBe('WORK')
})


test('I nueve etapas mantienen números y omitir etapas no renumera Armado',async({page},info)=>{
 const {data}=await setup(page)
 const names=['Preparación del Proyecto','Corte','Pegado de Cantos','Procesado con Múltiple','Procesado sin Múltiple','Armado','Control de Calidad','Embalaje','Instalación']
 const operations=names.map((name,i)=>({id:i===1?editorIds.operation:`stage-${i}`,code:i===1?'CORTE_ESCUADRADORA':`STAGE_${i}`,name,display_order:i+1,status:'active'}))
 await page.route('**/api/product-definition/options',route=>route.fulfill({json:{...editorOptions,operations}}))
 data.lots[0].operations[0].name='Corte de fondos'
 await open(page)
 for(let i=0;i<names.length;i++)await expect(page.getByRole('heading',{name:`${i+1}. ${names[i]}`,exact:true})).toHaveCount(1)
 const assembly=page.getByRole('region',{name:'Etapa 6. Armado',exact:true})
 await assembly.getByRole('button',{name:'AGREGAR OPERACIÓN',exact:true}).click()
 await assembly.getByLabel('Nombre de operación').fill('Armado de alacenas')
 await expect(assembly.getByText('6.1 Armado de alacenas',{exact:true})).toBeVisible()
 await expect(page.getByLabel('Tipo de operación')).toHaveCount(0)
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy()
 await page.getByRole('heading',{name:'2. Corte',exact:true}).scrollIntoViewIfNeeded()
 await page.screenshot({path:`test-results/standard-stages-${info.project.name}.png`})
})
