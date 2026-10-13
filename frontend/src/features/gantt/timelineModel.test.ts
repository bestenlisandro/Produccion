import { describe,expect,test } from 'vitest'
import { ganttFixture,ganttScenarioFixture } from '../../test/fixtures'
import { differenceLabel,timelineGroups,timelineItems } from './timelineModel'

describe('Gantt timeline model',()=>{
  test('shows cumulative center capacity',()=>expect(timelineGroups(ganttFixture)[0].content).toContain('capacidad 3'))
  test('separates working time, current plan and real execution',()=>{
    const classes=timelineItems(ganttFixture).map(item=>item.className)
    expect(classes).toEqual(expect.arrayContaining(['gantt-working regular','gantt-plan gantt-status-en_curso','gantt-actual']))
  })
  test('shows physical occupations only in resource grouping',()=>{
    expect(timelineItems(ganttFixture).some(item=>String(item.className).includes('occupation'))).toBe(false)
    const resource={...ganttFixture,group_by:'resource' as const,groups:[{id:'center-1',label:'Banco 1',kind:'resource' as const}]}
    expect(timelineItems(resource).some(item=>String(item.className).includes('occupation'))).toBe(true)
  })
  test('adds semantic scenario overlay and readable difference',()=>{
    expect(timelineItems(ganttScenarioFixture).some(item=>String(item.className).includes('difference-delayed'))).toBe(true)
    expect(differenceLabel('OUT_OF_HORIZON')).toContain('fuera de horizonte')
  })
  test('keeps delayed and blocked status explicit',()=>{
    const delayed={...ganttFixture,operations:[{...ganttFixture.operations[0],operational_status:'DEMORADO',blocker_code:'GATE_BLOCKED'}]}
    const item=timelineItems(delayed).find(value=>String(value.id).startsWith('plan-'))!
    expect(item.content).toContain('DEMORADA')
    expect(item.className).toContain('demorado')
  })
})
