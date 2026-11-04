import type {GanttData} from '../../api/client'

type Option=GanttData['available_scenarios'][number]

export function scenarioLabel(option:Option,timezone:string):string {
 const date=new Intl.DateTimeFormat('es-AR',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(option.created_at))
 const states=[]
 if(option.status==='confirmed')states.push('Confirmada')
 if(option.expired)states.push('Desactualizada')
 if(option.stale&&option.status!=='confirmed')states.push('Histórica')
 if(!states.length)states.push('Vigente / revisable')
 if(option.origin_plan_version_number!=null)states.push(`ORIGEN DE CURRENT V${option.origin_plan_version_number}`)
 return `${date} · ${option.scenario_kind==='initial'?'Inicial':option.scenario_kind==='simulation'?'Simulación':'Replan'} · ${states.join(' · ')}`
}

export function confirmationBlocker(data:GanttData):string|null {
 const scenario=data.scenario
 if(!scenario)return 'Elegí una simulación para revisarla.'
 if(scenario.status==='confirmed')return 'Esta simulación ya fue confirmada y es histórica; no puede volver a promoverse.'
 if(scenario.expired)return 'Esta simulación está desactualizada. Generá una nueva simulación para poder confirmarla.'
 if(scenario.stale)return 'Esta simulación es histórica y ya no puede promoverse porque su base cambió.'
 if(scenario.status!=='ready')return 'Esta simulación no está lista para confirmar.'
 if(scenario.complete===false)return 'Esta simulación está incompleta. Revisá sus bloqueos antes de confirmar.'
 if(scenario.scenario_kind==='initial'&&data.plan_version_id)return 'Esta simulación inicial es histórica: ya existe un plan vigente.'
 return null
}
