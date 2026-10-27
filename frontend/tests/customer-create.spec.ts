import { test,expect,type Page } from '@playwright/test'
import { projectOptions,projectIds } from '../src/test/projectIntakeFixture'

const customer={id:'aabbccdd-1111-4111-8111-112233445566',display_name:'Nico del Castillo',phone:null,email:null}
async function setup(page:Page,{existing=false,failFirst=false}={}){
  const options={...structuredClone(projectOptions),customers:existing?[{id:customer.id,name:customer.display_name,code:null}]:[]}
  const calls:{body:unknown;key:string|undefined}[]=[]
  let reads=0
  await page.route('**/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname
    if(path==='/api/project-intake/options'){reads++;return route.fulfill({json:options})}
    if(path==='/api/customers'&&request.method()==='POST'){
      calls.push({body:request.postDataJSON(),key:request.headers()['idempotency-key']})
      if(failFirst&&calls.length===1)return route.fulfill({status:500,json:{}})
      options.customers=[{id:customer.id,name:customer.display_name,code:null}]
      return route.fulfill({status:201,json:{customer,idempotent_replay:failFirst}})
    }
    throw new Error(`Unexpected request: ${request.method()} ${path}`)
  })
  await page.goto('/projects/new')
  await expect(page.getByRole('button',{name:'+ NUEVO CLIENTE'})).toBeVisible()
  return {calls,getReads:()=>reads}
}

test('alta con nombre selecciona cliente y preserva todo el proyecto',async({page})=>{
  const {calls,getReads}=await setup(page)
  await expect(page.getByLabel('Cliente',{exact:true}).locator('option')).toHaveCount(1)
  await page.getByLabel('Código del proyecto').fill('P-REAL')
  await page.getByLabel('Nombre / referencia').fill('Cocina real')
  await page.getByLabel('Prioridad del proyecto').selectOption(projectIds.high)
  await page.getByLabel('Fecha comprometida').fill('2026-12-24')
  await page.getByLabel('Notas').fill('Conservar notas')
  await page.getByRole('button',{name:'+ NUEVO CLIENTE'}).click()
  const dialog=page.getByRole('dialog',{name:'Nuevo cliente'})
  await expect(dialog).toBeVisible()
  await expect(page.getByLabel('Nombre / razón social')).toBeFocused()
  await page.getByLabel('Nombre / razón social').fill('Nico del Castillo')
  await expect(page.getByLabel('Teléfono (opcional)')).toBeEmpty()
  await expect(page.getByLabel('Email (opcional)')).toBeEmpty()
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()
  await page.getByRole('button',{name:'CREAR CLIENTE',exact:true}).click()
  await expect(dialog).toHaveCount(0)
  await expect(page.getByRole('region',{name:'Notificaciones'})).toContainText('Cliente creado correctamente.')
  expect(calls).toHaveLength(1)
  expect(calls[0].body).toEqual({display_name:'Nico del Castillo',phone:null,email:null})
  expect(calls[0].key).toBeTruthy()
  await expect.poll(getReads).toBeGreaterThan(1)
  await expect(page.getByLabel('Cliente',{exact:true})).toHaveValue(customer.id)
  await expect(page.getByLabel('Código del proyecto')).toHaveValue('P-REAL')
  await expect(page.getByLabel('Nombre / referencia')).toHaveValue('Cocina real')
  await expect(page.getByLabel('Prioridad del proyecto')).toHaveValue(projectIds.high)
  await expect(page.getByLabel('Fecha comprometida')).toHaveValue('2026-12-24')
  await expect(page.getByLabel('Notas')).toHaveValue('Conservar notas')
  await expect(page.getByRole('button',{name:'GUARDAR',exact:true})).toBeEnabled()
})

test('error conserva modal y retry reutiliza intención y clave',async({page})=>{
  const {calls}=await setup(page,{failFirst:true})
  await page.getByRole('button',{name:'+ NUEVO CLIENTE'}).click()
  await page.getByLabel('Nombre / razón social').fill('Nico del Castillo')
  await page.getByLabel('Teléfono (opcional)').fill('12345')
  await page.getByLabel('Email (opcional)').fill('nico@example.test')
  await page.getByRole('button',{name:'CREAR CLIENTE',exact:true}).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await expect(page.getByLabel('Nombre / razón social')).toHaveValue('Nico del Castillo')
  await expect(page.getByLabel('Teléfono (opcional)')).toHaveValue('12345')
  await expect(page.getByLabel('Email (opcional)')).toHaveValue('nico@example.test')
  await expect(page.getByRole('alert').last()).toContainText('Reintentá el mismo envío')
  await page.getByRole('button',{name:'REINTENTAR CREACIÓN'}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  expect(calls).toHaveLength(2);expect(calls[1]).toEqual(calls[0])
  await expect(page.getByLabel('Cliente',{exact:true})).toHaveValue(customer.id)
})

test('cliente existente puede seleccionarse sin crear duplicado',async({page})=>{
  const {calls}=await setup(page,{existing:true})
  await page.getByRole('button',{name:'+ NUEVO CLIENTE'}).click()
  await page.getByLabel('Nombre / razón social').fill('nico del')
  await page.getByRole('button',{name:'USAR CLIENTE EXISTENTE: Nico del Castillo'}).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByLabel('Cliente',{exact:true})).toHaveValue(customer.id)
  expect(calls).toHaveLength(0)
})
