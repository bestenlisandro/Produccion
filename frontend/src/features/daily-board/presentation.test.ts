import { describe,expect,test } from 'vitest'
import { blockerMessage,minutes,statusOrder } from './presentation'

describe('mensajes de blockers',()=>{
  test.each([
    ['PERSON_UNAVAILABLE','personal disponible'],
    ['REQUIRED_SKILL_UNAVAILABLE','habilidad requerida'],
    ['PHYSICAL_RESOURCE_OCCUPIED','recurso necesario'],
    ['CUMULATIVE_CAPACITY_EXHAUSTED','capacidad disponible'],
    ['MATERIAL_NOT_AVAILABLE','material todavía'],
    ['DRAWINGS_NOT_AVAILABLE','planos todavía'],
    ['HARDWARE_NOT_AVAILABLE','herrajes'],
    ['OUTSIDE_WORKING_CALENDAR','horario de trabajo'],
    ['OUT_OF_HORIZON','horizonte actual'],
  ])('%s se traduce', (code,text)=>expect(blockerMessage(code)).toContain(text))
})
test('duraciones no exponen revisiones técnicas',()=>expect(minutes(150)).toBe('2 h 30 min'))
test('orden visible mantiene finalizado al final',()=>expect(statusOrder.FINALIZADO).toBeGreaterThan(statusOrder.PENDIENTE))
