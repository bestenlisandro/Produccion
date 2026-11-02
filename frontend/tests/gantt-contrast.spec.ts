import {test,expect,type Page} from '@playwright/test'
import {ganttV2Fixture,initialV2Fixture} from '../src/test/ganttV2Fixture'
import {ganttScenarioFixture} from '../src/test/fixtures'

async function contrastViewport(page:Page,project:string){
 await page.setViewportSize({width:project==='desktop-1366'?1280:project==='desktop-1440'?1440:project==='tablet-1024'?1024:390,height:1100})
}
function grouped(source:typeof ganttV2Fixture,resource:boolean){
 if(!resource)return source
 const operations=source.operations.map((op,i)=>({...op,group_ids:[i===3?'unassigned-resource':`resource-${i}`]}))
 return {...source,group_by:'resource',operations,groups:operations.map((o,i)=>({id:o.group_ids[0],label:o.resources?.[0]?.name??'Sin recurso físico',kind:'resource'}))}
}
test('contraste: proyecto, simulación, Armado seleccionado, flechas y recursos',async({page},info)=>{
 await contrastViewport(page,info.project.name)
 await page.route('**/api/**',route=>{
  if(route.request().method()!=='GET')throw new Error('La validación visual no permite mutaciones')
  const params=new URL(route.request().url()).searchParams
  return route.fulfill({json:grouped({...initialV2Fixture,range_from:params.get('from')!,range_to:params.get('to')!},params.get('group_by')==='resource')})
 })
 await page.goto(`/planning/gantt?scenario_id=${ganttScenarioFixture.scenario!.id}`)
 const mobile=info.project.name==='smartphone-390'
 await page.getByRole('button',{name:'AJUSTAR AL PLAN'}).click()
 await expect(page.locator('svg[aria-label="Escala temporal"] > g')).toHaveCount(1)
 await expect(page.getByRole('region',{name:'Leyenda'})).toContainText('Bloqueado')
 const sample=page.getByRole('region',{name:'Leyenda'}).locator('i').first()
 const box=await sample.boundingBox();expect(box!.width).toBeGreaterThanOrEqual(14);expect(box!.height).toBeGreaterThanOrEqual(14)
 await page.screenshot({path:info.outputPath('A-project-simulation.png'),fullPage:true})
 if(!mobile)await page.getByLabel('Dependencias',{exact:true}).selectOption('hidden')
 await (mobile?page.getByRole('region',{name:'Operaciones visibles'}).getByRole('button',{name:/Alacenas \(fixture\) · Armado/}):page.getByRole('button',{name:/Inspeccionar Armado/})).click()
 await expect(page.getByRole('dialog',{name:'Detalle de operación'})).toContainText('BLOQUEADO')
 await page.screenshot({path:info.outputPath('B-Armado-selected.png'),fullPage:true})
 if(!mobile){
  await page.getByLabel('Dependencias',{exact:true}).selectOption('selected')
  await expect(page.locator('[data-dependency][data-related=true]')).toHaveCount(3)
  const bar=page.getByRole('button',{name:/Simulación.*Armado/}).first()
  await expect(bar).toHaveAttribute('aria-pressed','true')
  const visual=await bar.evaluate(el=>({stroke:getComputedStyle(el).stroke,width:getComputedStyle(el).strokeWidth,fill:getComputedStyle(el).fill}))
  expect(visual.stroke).toBe('rgb(124, 58, 237)');expect(Number.parseFloat(visual.width)).toBeGreaterThanOrEqual(3);expect(visual.fill).toContain('url(')
 }
 await page.screenshot({path:info.outputPath('C-selected-dependencies.png'),fullPage:true})
 await page.keyboard.press('Escape')
 await page.getByLabel('Agrupar por').selectOption('resource')
 await expect(page.getByLabel('Agrupar por')).toHaveValue('resource')
 await page.screenshot({path:info.outputPath('D-resources.png'),fullPage:true})
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true)
})

test('estados sólidos y simulación distinguibles con contraste medido y daltonismo',async({page},info)=>{
 await contrastViewport(page,info.project.name)
 const operations=['PENDIENTE','EN_CURSO','BLOQUEADO','DEMORADO','FINALIZADO'].map((status,i)=>({...ganttV2Fixture.operations[i%4],operation_id:`state-${i}`,operational_status:status}))
 await page.route('**/api/**',route=>{
  if(route.request().method()!=='GET')throw new Error('No se permiten writes')
  const params=new URL(route.request().url()).searchParams
  return route.fulfill({json:{...ganttV2Fixture,group_by:params.get('group_by')??'project',groups:[{id:'project-v2',label:'Estados operativos de referencia',kind:params.get('group_by')??'project'}],range_from:params.get('from')!,range_to:params.get('to')!,operations,scenario:{...ganttScenarioFixture.scenario!,operations:operations.map(o=>({operation_id:o.operation_id,planned_start:o.planned_start,planned_finish:o.planned_finish,difference:'UNCHANGED'}))}}})
 })
 await page.goto('/planning/gantt')
 await page.getByLabel('Agrupar por').selectOption('center')
 await page.getByRole('button',{name:'AJUSTAR AL PLAN'}).click()
 await expect(page.locator('svg[aria-label="Escala temporal"] > g')).toHaveCount(1)
 const palette=await page.locator('.ganttTheme').first().evaluate(el=>{
  const css=getComputedStyle(el);return Object.fromEntries(['working-bg','offshift-bg','weekend-bg','executed','in-progress','planned','simulation','blocked','delayed','now','on-dark','simulation-text','simulation-bg','simulation-pattern'].map(k=>[k,css.getPropertyValue(`--gantt-${k}`).trim()]))
 })
 function luminance(hex:string){hex=hex.replace(/^#(.)(.)(.)$/,'#$1$1$2$2$3$3');const v=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return v[0]*.2126+v[1]*.7152+v[2]*.0722}
 function contrast(a:string,b:string){const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
 for(const state of ['executed','in-progress','planned','blocked','delayed'])expect(contrast(palette['on-dark'],palette[state])).toBeGreaterThanOrEqual(4.5)
 for(const bg of ['simulation-bg','simulation-pattern'])expect(contrast(palette['simulation-text'],palette[bg])).toBeGreaterThanOrEqual(4.5)
 console.log('GANTT_CONTRAST',info.project.name,JSON.stringify(Object.fromEntries(['executed','in-progress','planned','blocked','delayed'].map(k=>[k,contrast(palette['on-dark'],palette[k]).toFixed(2)]))))
 await page.screenshot({path:info.outputPath('states-normal.png'),fullPage:true})
 if(info.project.name==='desktop-1440'){
  const cdp=await page.context().newCDPSession(page)
  for(const type of ['deuteranopia','protanopia','achromatopsia']){
   await cdp.send('Emulation.setEmulatedVisionDeficiency',{type})
   await page.screenshot({path:info.outputPath(`states-${type}.png`),fullPage:true})
  }
  await cdp.send('Emulation.setEmulatedVisionDeficiency',{type:'none'});await cdp.detach()
 }
})
