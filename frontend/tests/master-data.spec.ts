import {test,expect,type Page} from '@playwright/test'
import {ids,snapshot} from '../src/test/masterDataFixture'

async function setup(page:Page){
  const data=structuredClone(snapshot)
  const calls:{path:string;body:any;key:string|undefined}[]=[]
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname.replace('/api/master-data','')
    if(path==='/snapshot')return route.fulfill({json:data})
    const body=request.postDataJSON()??{}
    calls.push({path,body,key:request.headers()['idempotency-key']})
    let entity:any={id:'new',row_version:1},usage=0
    if(path==='/people'){
      entity={...data.people[0],...body,id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',skills:[]}
      data.people.push(entity)
    }else if(path.includes('/skills/')){
      const person=data.people.find(p=>path.includes(p.id))!
      person.skills=request.method()==='DELETE'?[]:[{id:ids.skill,code:'ARM',name:'Armado'}]
      entity=person
    }else if(path===`/work-centers/${ids.center}`){
      Object.assign(data.work_centers[0],body,{row_version:2});entity=data.work_centers[0]
    }else if(path.endsWith('/status')){
      Object.assign(data.resources[0],body,{row_version:2});entity=data.resources[0];usage=4
    }else if(path.endsWith('/windows')){
      data.calendar_windows=body.windows.map((w:any,i:number)=>({...w,id:`window-${i}`,calendar_id:ids.calendar,row_version:1,valid_from:body.effective_from,valid_to:null}))
      data.calendars[0].row_version++;entity=data.calendars[0]
    }else if(path==='/calendar-exceptions'){
      entity={...body,id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',row_version:1};data.calendar_exceptions.push(entity)
    }else if(path.startsWith('/people/')){
      entity=data.people.find(p=>path.endsWith(p.id))!;Object.assign(entity,body,{row_version:2})
    }
    return route.fulfill({json:{entity,current_usage_count:usage,plan_requires_reconciliation:usage>0,idempotent_replay:false}})
  })
  await page.goto('/settings');await expect(page.getByRole('heading',{name:'Maestros operativos'})).toBeVisible()
  return {data,calls}
}

test('A crea persona y asigna skill',async({page})=>{
  const {calls}=await setup(page)
  const form=page.getByRole('heading',{name:'Crear persona'}).locator('..')
  await form.getByLabel('Código',{exact:true}).fill('EMP-2');await form.getByLabel('Nombre visible').fill('Persona Dos')
  await form.getByLabel('Calendario',{exact:true}).selectOption(ids.calendar);await form.getByRole('button',{name:'GUARDAR',exact:true}).click()
  const card=page.locator('article').filter({has:page.getByRole('heading',{name:'Persona Dos',exact:true})})
  await card.getByLabel('Armado',{exact:true}).click()
  await expect.poll(()=>calls.some(c=>c.path.includes('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/skills/'))).toBe(true)
  await expect(card.getByLabel('Armado',{exact:true})).toBeChecked()
})

test('B capacidad 2 persiste al volver a abrir',async({page})=>{
  const {calls}=await setup(page);await page.getByRole('button',{name:'Centros de trabajo',exact:true}).click()
  await page.getByRole('button',{name:'EDITAR',exact:true}).click();await page.getByLabel('Capacidad nominal').fill('2')
  await page.getByRole('button',{name:'GUARDAR',exact:true}).click();await expect.poll(()=>calls[0]?.body.aggregate_capacity).toBe(2)
  await page.reload();await page.getByRole('button',{name:'Centros de trabajo',exact:true}).click();await expect(page.getByText(/Capacidad 2/)).toBeVisible()
})

test('C recurso usado exige confirmación y muestra reconciliation',async({page})=>{
  await setup(page);await page.getByRole('button',{name:'Recursos',exact:true}).click()
  page.once('dialog',async dialog=>{expect(dialog.message()).toContain('4 operaciones');await dialog.accept()})
  await page.getByRole('button',{name:'DESACTIVAR',exact:true}).click()
  await expect(page.getByRole('status')).toContainText('PLAN_REQUIRES_RECONCILIATION')
})

test('D jornada y excepción sobreviven recarga',async({page})=>{
  await setup(page);await page.getByRole('button',{name:'Calendarios',exact:true}).click()
  await page.getByRole('button',{name:'AGREGAR VENTANA'}).click();await page.getByLabel('Día 2').selectOption('2')
  await page.getByRole('button',{name:'GUARDAR JORNADA'}).click();await expect(page.getByText('Cambios guardados.')).toBeVisible()
  await page.getByLabel('Fecha',{exact:true}).fill('2026-12-24');await page.getByLabel('Descripción de la excepción').fill('Horario especial')
  await page.getByRole('button',{name:'AGREGAR EXCEPCIÓN',exact:true}).click();await expect(page.getByText(/Horario especial/)).toBeVisible()
  await page.reload();await page.getByRole('button',{name:'Calendarios',exact:true}).click()
  await expect(page.getByLabel('Día 2')).toHaveValue('2');await expect(page.getByText(/Horario especial/)).toBeVisible()
})

test('E error backend conserva input',async({page})=>{
  await setup(page)
  await page.route('**/api/master-data/people',route=>route.fulfill({status:409,json:{error:{message:'Código duplicado'}}}))
  await page.getByLabel('Código',{exact:true}).fill('DUP');await page.getByLabel('Nombre visible').fill('No perder')
  await page.getByLabel('Calendario',{exact:true}).selectOption(ids.calendar);await page.getByRole('button',{name:'GUARDAR',exact:true}).click()
  await expect(page.getByRole('alert')).toContainText('Código duplicado');await expect(page.getByLabel('Nombre visible')).toHaveValue('No perder')
})

test('F cambio rápido conserva ID y datos de persona B',async({page})=>{
  const {data,calls}=await setup(page)
  const secondId='cccccccc-cccc-4ccc-8ccc-cccccccccccc'
  data.people.push({...data.people[0],id:secondId,code:'EMP-B',display_name:'Persona B'})
  await page.reload();const edits=page.getByRole('button',{name:'EDITAR',exact:true})
  await edits.nth(0).click();await edits.nth(1).click()
  await expect(page.getByLabel('Nombre visible')).toHaveValue('Persona B');await page.getByRole('button',{name:'GUARDAR',exact:true}).click()
  await expect.poll(()=>calls.at(-1)?.path).toBe(`/people/${secondId}`)
  expect(calls.at(-1)?.body.display_name).toBe('Persona B')
})

test('benchmark render 50 personas 20 skills 20 recursos y responsive',async({page},testInfo)=>{
  const {data}=await setup(page)
  data.people=Array.from({length:50},(_,i)=>({...data.people[0],id:`person-${i}`,display_name:`Persona ${i}`}))
  data.skills=Array.from({length:20},(_,i)=>({...data.skills[0],id:`skill-${i}`,name:`Skill ${i}`}))
  data.resources=Array.from({length:20},(_,i)=>({...data.resources[0],id:`resource-${i}`,name:`Recurso ${i}`}))
  const start=Date.now();await page.reload();await expect(page.locator('article')).toHaveCount(50)
  const elapsed=Date.now()-start,payload=Buffer.byteLength(JSON.stringify(data))
  const overflow=await page.evaluate(()=>Array.from(document.querySelectorAll('body *')).filter(el=>el.getBoundingClientRect().right>window.innerWidth+1).slice(0,8).map(el=>({tag:el.tagName,class:el.className,right:el.getBoundingClientRect().right})))
  expect(overflow).toEqual([])
  await testInfo.attach('frontend-benchmark',{body:JSON.stringify({elapsed_ms:elapsed,payload_bytes:payload,people:50,skills:20,resources:20,backend:'mock'}),contentType:'application/json'})
  console.log(`MASTER_DATA_BENCHMARK ${testInfo.project.name}: render/navigation=${elapsed}ms payload=${payload} bytes (mock API)`)
})
