import { describe,expect,test } from 'vitest'
import { formatRange,ganttRange,moveAnchor,plantDateTime } from './time'

describe('Gantt timezone range',()=>{
  test('day starts at plant midnight and not browser midnight',()=>{
    const range=ganttRange('2026-09-29','day','America/Argentina/Buenos_Aires')
    expect(range).toEqual({from:'2026-09-29T03:00:00.000Z',to:'2026-09-30T03:00:00.000Z'})
  })
  test('week and fortnight are deterministic in plant timezone',()=>{
    expect(ganttRange('2026-09-30','week','America/Argentina/Buenos_Aires').from).toBe('2026-09-28T03:00:00.000Z')
    expect(ganttRange('2026-09-30','fortnight','America/Argentina/Buenos_Aires').to).toBe('2026-10-12T03:00:00.000Z')
  })
  test('navigation and labels use the plant timezone',()=>{
    expect(moveAnchor('2026-09-29','week',1,'America/Argentina/Buenos_Aires')).toBe('2026-10-06')
    expect(plantDateTime('2026-09-29T03:30:00Z','America/Argentina/Buenos_Aires')).toContain('29')
    expect(formatRange('2026-09-29T03:00:00Z','2026-09-30T03:00:00Z','America/Argentina/Buenos_Aires')).toBeTruthy()
  })
})
