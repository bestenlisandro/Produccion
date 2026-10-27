import { test,expect,type Page } from '@playwright/test'
import { projectFixture,projectOptions,projectIds } from '../src/test/projectIntakeFixture'

async function setup(page:Page){
  const rows=[structuredClone(projectFixture)]
  const calls:{path:string;body:any;key:string|undefined}[]=[]
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname.replace('/api','')
  if(path.endsWith('/installations'))return route.fulfill({json:{project_id:projectFixture.id,project_code:projectFixture.code,project_name:projectFixture.name,customer_name:projectFixture.customer_name,row_version:1,timezone:'America/Argentina/Buenos_Aires',required:false,can_complete:false,completed:false,installations:[]}})
    if(path==='/project-intake/options')return route.fulfill({json:projectOptions})
    if(path==='/projects'&&request.method()==='GET')return route.fulfill({json:rows})
    if(path.startsWith('/projects/')&&request.method()==='GET')return route.fulfill({json:rows.find(p=>path===`/projects/${p.id}`)})
    const body=request.postDataJSON();calls.push({path,body,key:request.headers()['idempotency-key']})
    if(path==='/projects'){
      const created={...structuredClone(projectFixture),...body,id:'77777777-7777-4777-8777-777777777777'}
      rows.push(created);return route.fulfill({status:201,json:created})
    }
    const p=rows.find(p=>path.startsWith(`/projects/${p.id}`))!
    if(path.endsWith('/measurement'))p.measurement={supported:true,occurred_at:body.occurred_at,notes:body.notes}
    else if(path.endsWith('/replanteo'))p.replanteo={supported:true,occurred_at:body.occurred_at,notes:body.notes}
    else{Object.assign(p,body);if(body.priority_id)p.priority_code=body.priority_id===projectIds.high?'HIGH':'NORMAL'}
    p.row_version++;return route.fulfill({json:{project:p,idempotent_replay:false}})
  })
  await page.goto('/projects');await expect(page.getByRole('heading',{name:'Proyectos / pedidos'})).toBeVisible()
  return {rows,calls}
}

test('A nuevo proyecto guarda y abre detalle',async({page})=>{
  const {calls}=await setup(page)
  await page.getByRole('link',{name:'NUEVO PROYECTO'}).click()
  await page.getByLabel('Código del proyecto').fill('P-NEW');await page.getByLabel('Nombre / referencia').fill('Pedido de prueba')
  await page.getByLabel('Cliente',{exact:true}).selectOption(projectIds.customer);await page.getByLabel('Fecha comprometida').fill('2026-12-24')
  await page.getByRole('button',{name:'GUARDAR',exact:true}).click()
  await expect(page.getByRole('heading',{name:'Pedido de prueba',exact:true})).toBeVisible()
  expect(calls[0].key).toBeTruthy();expect(calls[0].body.code).toBe('P-NEW')
})

test('B edita prioridad y fecha comprometida',async({page})=>{
  const {calls}=await setup(page);await page.getByRole('link',{name:'Cocina Central'}).click()
  await page.getByRole('button',{name:'EDITAR PROYECTO'}).click();await page.getByLabel('Prioridad del proyecto').selectOption(projectIds.high)
  await page.getByLabel('Fecha comprometida').fill('2026-12-20');await page.getByRole('button',{name:'GUARDAR',exact:true}).click()
  await expect(page.getByText('Cambios guardados.')).toBeVisible();expect(calls.at(-1)?.body.priority_id).toBe(projectIds.high)
  await page.reload();await expect(page.getByText('Prioridad: ALTA')).toBeVisible();await expect(page.getByText('Comprometida: 2026-12-20',{exact:true})).toBeVisible()
})

test('C registra medición y replanteo realizados',async({page})=>{
  await setup(page);await page.getByRole('link',{name:'Cocina Central'}).click()
  for(const label of ['Medición','Replanteo']){
    const form=page.getByRole('form',{name:label,exact:true})
    await form.getByLabel(`Fecha realizada de ${label.toLowerCase()}`,{exact:true}).fill('2026-09-01T10:00')
    await form.getByLabel(`Observación de ${label.toLowerCase()}`).fill('Conforme')
    await form.getByRole('button').click();await expect(page.getByRole('heading',{name:`${label}: ${label==='Medición'?'REALIZADA':'COMPLETADO'}`,exact:true})).toBeVisible()
  }
  await page.reload();await expect(page.getByRole('heading',{name:'Replanteo: COMPLETADO',exact:true})).toBeVisible()
})

test('D proyecto sin definición no ofrece planificación liberada',async({page})=>{
  await setup(page);await page.getByRole('link',{name:'Cocina Central'}).click()
  await expect(page.getByText('Todavía no definida',{exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'DEFINIR PRODUCCIÓN'})).toBeEnabled()
  await expect(page.getByText('Sin trabajo planificable liberado.')).toBeVisible();await expect(page.getByRole('link',{name:'ABRIR GANTT'})).toHaveCount(0)
})

test('E conflicto 409 conserva input y permite recuperar versión',async({page})=>{
  const {rows}=await setup(page);await page.getByRole('link',{name:'Cocina Central'}).click()
  let conflict=true
  await page.route(`**/api/projects/${projectIds.project}`,async route=>{
    if(route.request().method()!=='PATCH')return route.fallback()
    if(conflict){conflict=false;rows[0].row_version=2;return route.fulfill({status:409,json:{error:{code:'PROJECT_INTAKE_VERSION_CONFLICT',message:'Conflicto de versión'}}})}
    return route.fallback()
  })
  await page.getByRole('button',{name:'EDITAR PROYECTO'}).click();await page.getByLabel('Nombre / referencia').fill('Conservar entrada')
  await page.getByRole('button',{name:'GUARDAR',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'El proyecto cambió desde que lo abriste'})).toContainText('El proyecto cambió desde que lo abriste')
  await expect(page.getByLabel('Nombre / referencia')).toHaveValue('Conservar entrada')
  await page.getByRole('button',{name:'ACTUALIZAR INFORMACIÓN'}).click();await page.getByRole('button',{name:'EDITAR PROYECTO'}).click()
  await page.getByLabel('Nombre / referencia').fill('Recuperado');await page.getByRole('button',{name:'GUARDAR',exact:true}).click()
  await expect(page.getByText('Cambios guardados.')).toBeVisible()
})

test('F archivar conserva detalle e historia',async({page})=>{
  const {rows}=await setup(page);await page.getByRole('link',{name:'Cocina Central'}).click()
  page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'ARCHIVAR PROYECTO'}).click()
  await expect(page.getByText('Cambios guardados.')).toBeVisible();await page.reload()
  await expect(page.getByRole('heading',{name:'Cocina Central',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'EDITAR PROYECTO'})).toHaveCount(0)
  expect(rows).toHaveLength(1);expect(rows[0].status).toBe('archived')
})

test('benchmark 100 proyectos render búsqueda y responsive',async({page},testInfo)=>{
  const {rows}=await setup(page)
  rows.splice(0,rows.length,...Array.from({length:100},(_,i)=>({...structuredClone(projectFixture),id:`project-${i}`,code:`P-${i}`,name:`Proyecto ${i}`})))
  const start=Date.now();await page.reload();await expect(page.locator('article')).toHaveCount(100);const elapsed=Date.now()-start
  const filterStart=Date.now();await page.getByLabel('Buscar proyecto, código o cliente').fill('Proyecto 99');await expect(page.locator('article')).toHaveCount(1)
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);expect(overflow).toBe(false)
  const result={projects:100,render_ms:elapsed,filter_ms:Date.now()-filterStart,payload_bytes:Buffer.byteLength(JSON.stringify(rows)),backend:'mock'}
  await testInfo.attach('project-intake-benchmark',{body:JSON.stringify(result),contentType:'application/json'})
  console.log(`PROJECT_INTAKE_UI_BENCHMARK ${testInfo.project.name} ${JSON.stringify(result)}`)
})
