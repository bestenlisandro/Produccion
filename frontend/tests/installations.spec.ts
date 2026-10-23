import {test,expect,type Page} from '@playwright/test'
import {installationFixture} from '../src/test/installationFixture'
import {projectFixture,projectOptions} from '../src/test/projectIntakeFixture'
import {readinessFixture} from '../src/test/productionReadinessFixture'
import {ganttFixture,operation} from '../src/test/fixtures'

async function setup(page:Page,required=true){
 const p:any=structuredClone(installationFixture),project:any=structuredClone(projectFixture);if(!required){p.required=false;p.installations=[];p.can_complete=true}
 const calls:any[]=[]
 await page.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname.replace('/api','')
  if(req.method()==='GET'){
   if(path==='/installations')return route.fulfill({json:p.required?[p]:[]})
   if(path.endsWith('/installations'))return route.fulfill({json:p})
   if(path.endsWith('/production-readiness'))return route.fulfill({json:readinessFixture})
   if(path==='/project-intake/options')return route.fulfill({json:projectOptions})
   if(path==='/projects')return route.fulfill({json:[project]})
   if(path===`/projects/${p.project_id}`)return route.fulfill({json:project})
   if(path.startsWith('/scenarios/'))return route.fulfill({json:{id:p.project_id,status:'ready',promotion_lock_version:1,row_version:1,stale:false,changed_operations:2,affected_projects:1,impacts:[]}})
   if(path==='/planning/current/gantt')return route.fulfill({json:{...ganttFixture,operations:[{...ganttFixture.operations[0],operation_name:'Instalación cocina'}]}})
   if(path==='/planning/current/day')return route.fulfill({json:{date:'2026-10-22',operations:[{...operation,operation_name:'Instalación cocina'}]}})
   return route.fulfill({json:{}})
  }
  const body=req.postDataJSON();calls.push({path,body,key:req.headers()['idempotency-key']})
  if(path.endsWith('/installation-location')){Object.assign(p,body);p.row_version++}
  if(path.endsWith('/installation-plan')||path.endsWith('/replan'))return route.fulfill({status:path.endsWith('/replan')?201:200,json:{scenario_id:p.project_id,status:'ready',complete:true}})
  if(path.endsWith('/start')){p.installations[0].execution_id=p.project_id;p.installations[0].state='running';p.installations[0].started_at=body.started_at;p.installations[0].remaining_revision_no=1}
  if(path.endsWith('/segments')){p.installations[0].executed_minutes+=body.work_minutes;p.installations[0].last_segment_end=body.ended_at}
  if(path.endsWith('/remaining-estimate')){p.installations[0].remaining_minutes=body.remaining[0].minutes;p.installations[0].remaining_revision_no++}
  if(path.endsWith('/finish')){p.installations[0].state='finished';p.installations[0].completed_at=body.completed_at;p.can_complete=true}
  if(path.endsWith('/complete')){if(!p.can_complete)return route.fulfill({status:409,json:{error:{message:'Operaciones pendientes'}}});p.can_complete=false;p.completed=true;p.row_version++}
  return route.fulfill({json:{}})
 })
 return {p,calls}
}
async function open(page:Page){await page.goto(`/projects/${installationFixture.project_id}`);await expect(page.getByRole('heading',{name:'Instalación',exact:true})).toBeVisible()}

test('A agenda, programación explícita y Gantt',async({page})=>{const {calls}=await setup(page);await page.goto('/installations');await expect(page.getByText('Dirección: Calle 123')).toBeVisible();await page.getByRole('link',{name:'P-001 · Cocina Central'}).click();await page.getByRole('button',{name:'SIMULAR PLAN DE INSTALACIÓN'}).click();await page.getByRole('button',{name:'CONFIRMAR PLAN DE INSTALACIÓN'}).click();expect(calls.some(c=>c.path.endsWith('/accept'))).toBeTruthy();await page.getByRole('link',{name:'ABRIR GANTT'}).first().click();await expect(page.getByRole('heading',{name:'Gantt operativo'})).toBeVisible()})
test('B inicia, registra tramo y finaliza instalación',async({page})=>{await setup(page);await open(page);await page.getByRole('button',{name:'INICIAR INSTALACIÓN'}).click();await expect(page.getByRole('heading',{name:'Instalación cocina · EN CURSO'})).toBeVisible();await page.getByLabel(/Inicio real \/ inicio de tramo/).fill('2026-10-22T08:30');await page.getByLabel(/Fin de tramo \/ finalización/).fill('2026-10-22T10:30');await page.getByRole('button',{name:'REGISTRAR TRAMO / FIN DE JORNADA'}).click();await expect(page.getByText(/Ejecutado: 120 min/)).toBeVisible();page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'FINALIZAR FASE DE INSTALACIÓN'}).click();await expect(page.getByRole('heading',{name:'Instalación cocina · FINALIZADA'})).toBeVisible()})
test('C multidía conserva avance al fin de jornada',async({page})=>{await setup(page);await open(page);await expect(page.getByText(/Duración prevista: 780 min/)).toBeVisible();await page.getByRole('button',{name:'INICIAR INSTALACIÓN'}).click();await expect(page.getByRole('heading',{name:'Instalación cocina · EN CURSO'})).toBeVisible();await page.getByLabel(/Inicio real \/ inicio de tramo/).fill('2026-10-22T08:30');await page.getByLabel(/Fin de tramo \/ finalización/).fill('2026-10-22T15:00');await page.getByRole('button',{name:'REGISTRAR TRAMO / FIN DE JORNADA'}).click();await expect(page.getByText(/Ejecutado: 390 min/)).toBeVisible();await expect(page.getByRole('heading',{name:'Instalación cocina · EN CURSO'})).toBeVisible()})
test('D demora actualiza restante y simula replan',async({page})=>{const {calls}=await setup(page);await open(page);await page.getByRole('button',{name:'INICIAR INSTALACIÓN'}).click();await expect(page.getByRole('heading',{name:'Instalación cocina · EN CURSO'})).toBeVisible();await page.getByLabel('Tiempo restante (minutos-persona)').fill('360');await page.getByRole('button',{name:'GUARDAR RESTANTE DE INSTALACIÓN'}).click();await expect(page.getByText(/Restante: 360 min/)).toBeVisible();await page.getByRole('button',{name:'SIMULAR REPROGRAMACIÓN'}).click();await expect(page.getByRole('heading',{name:'Reprogramación propuesta'})).toBeVisible();expect(calls.find(c=>c.path.startsWith('/installations/')&&c.path.endsWith('/remaining-estimate')).key).toBeTruthy()})
test('E pendientes impiden cierre y sitio incompleto bloquea inicio',async({page})=>{const {p}=await setup(page);p.installations[0].ready_to_start=false;p.installations[0].blockers=['Producción precedente pendiente.'];await open(page);await expect(page.getByRole('button',{name:'CERRAR PROYECTO'})).toHaveCount(0);await expect(page.getByRole('button',{name:'INICIAR INSTALACIÓN'})).toBeDisabled();await page.getByRole('button',{name:'EDITAR UBICACIÓN'}).click();await page.getByLabel('Dirección',{exact:true}).fill('Calle nueva 456');await page.getByRole('button',{name:'GUARDAR UBICACIÓN'}).click();await expect(page.getByText('Dirección: Calle nueva 456')).toBeVisible()})
test('F cierra tras finalizar y responsive',async({page},testInfo)=>{const {p}=await setup(page);p.installations[0].state='finished';p.can_complete=true;await open(page);page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'CERRAR PROYECTO'}).click();await expect(page.getByText('PROYECTO FINALIZADO',{exact:true})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();if(testInfo.project.name==='smartphone-390')await page.screenshot({path:'test-results/installation-mobile.png',fullPage:true})})
test('G proyecto sin instalación cierra sin gate falso',async({page})=>{await setup(page,false);await open(page);await expect(page.getByText('No requiere instalación en la definición congelada.')).toBeVisible();page.once('dialog',d=>d.accept());await page.getByRole('button',{name:'CERRAR PROYECTO'}).click();await expect(page.getByText('PROYECTO FINALIZADO',{exact:true})).toBeVisible()})

test('H agenda representativa de 50 instalaciones',async({page},testInfo)=>{await setup(page);await page.route('**/api/installations',route=>route.fulfill({json:Array.from({length:50},(_,n)=>({...structuredClone(installationFixture),project_id:`00000000-0000-4000-8000-${String(n).padStart(12,'0')}`,project_code:`P-${n}`,project_name:`Obra ${n}`}))}));const start=performance.now();await page.goto('/installations');await expect(page.getByRole('heading',{name:'Instalación cocina · PROGRAMADA'})).toHaveCount(50);console.log(`INSTALLATION_RENDER_50 ${testInfo.project.name} ${(performance.now()-start).toFixed(2)} ms`);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy()})
