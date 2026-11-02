import {render,screen,within,fireEvent} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {expect,test,vi} from 'vitest'
import {ganttV2Fixture} from '../../test/ganttV2Fixture'
import {dependencyEdges,hierarchy,visibleRows,temporalTicks} from './operationalModel'
import {GanttTimeline} from './GanttTimeline'
import {ganttScenarioFixture} from '../../test/fixtures'

test('initial histórico superpone propuesta sin reemplazar las barras CURRENT',()=>{
 const data={...ganttV2Fixture,scenario:{...ganttScenarioFixture.scenario!,scenario_kind:'initial',stale:true,expired:true,operations:[{operation_id:'op-0',planned_start:ganttV2Fixture.operations[0].planned_start,planned_finish:ganttV2Fixture.operations[0].planned_finish,difference:'UNCHANGED' as const}]}}
 const view=render(<GanttTimeline data={data} onSelect={vi.fn()}/> )
 expect(view.container.querySelectorAll('.gantt-plan').length).toBeGreaterThan(0)
 expect(view.container.querySelectorAll('.gantt-scenario')).toHaveLength(1)
})

test('ramas paralelas se derivan sólo de precedencias explícitas',()=>{
 const edges=dependencyEdges(ganttV2Fixture.operations,'all')
 expect(edges).toEqual([{from:'op-0',to:'op-2'},{from:'op-1',to:'op-2'},{from:'op-2',to:'op-3'}])
 expect(dependencyEdges(ganttV2Fixture.operations,'selected')).toEqual([])
 expect(dependencyEdges(ganttV2Fixture.operations,'hidden','op-2')).toEqual([])
 expect(dependencyEdges(ganttV2Fixture.operations,'selected','op-0')).toEqual([{from:'op-0',to:'op-2'}])
})
test('plegar proyecto y etapa conserva la jerarquía e IDs',()=>{
 const rows=hierarchy(ganttV2Fixture,new Set());expect(rows.filter(r=>r.kind==='stage')).toHaveLength(4)
 expect(hierarchy(ganttV2Fixture,new Set([rows[0].id])).map(r=>r.kind)).toEqual(['group'])
 const folded=hierarchy(ganttV2Fixture,new Set([rows[1].id]));expect(folded.some(r=>r.operation?.operation_id==='op-0')).toBe(false)
 expect(folded.filter(r=>r.operation)).toHaveLength(3)
})
test('filas virtualizadas acotan nodos para 50 proyectos',()=>{
 const rows=Array.from({length:1000},(_,i)=>({id:String(i),label:String(i),kind:'group' as const,depth:0}))
 const slice=visibleRows(rows,6800,560);expect(slice.rows.length).toBeLessThan(20);expect(slice.start).toBe(96)
})
test('calendario local conserva fecha y fines de semana',()=>{
 const ticks=temporalTicks(ganttV2Fixture.range_from,ganttV2Fixture.range_to,ganttV2Fixture.timezone)
 expect(ticks).toHaveLength(7);expect(ticks.filter(t=>t.weekend)).toHaveLength(2)
 expect(new Date(ticks[0].start).toISOString()).toBe('2026-10-26T03:00:00.000Z')
})
test('selección dibuja dos entradas y una salida, pausa real y compromiso',async()=>{
 const view=render(<GanttTimeline data={ganttV2Fixture} selectedId="op-2" onSelect={vi.fn()}/> )
 expect(view.container.querySelectorAll('[data-dependency]')).toHaveLength(3)
 expect(view.container.querySelectorAll('[data-working-window]')).toHaveLength(2)
 expect(view.container.querySelectorAll('[data-weekend]')).toHaveLength(2)
 expect(screen.getAllByText('◆ Comprometida').length).toBeGreaterThan(0)
 expect(screen.getAllByRole('button',{name:/Plan vigente, Alacenas.*Armado/})).toHaveLength(2)
 await userEvent.click(screen.getByRole('button',{name:/2. Corte/}));expect(screen.queryByRole('button',{name:/Plan vigente, Alacenas.*Corte Fondos/})).not.toBeInTheDocument()
 expect(view.container.querySelectorAll('[data-dependency]')).toHaveLength(2)
})
test('teclado selecciona y tooltip es accesible sin hover',async()=>{
 const select=vi.fn();render(<GanttTimeline data={ganttV2Fixture} onSelect={select}/> )
 const bar=screen.getByRole('button',{name:/Plan vigente, Alacenas.*Multiple/});bar.focus()
 expect(await screen.findByRole('tooltip')).toHaveTextContent('Multiple')
 await userEvent.keyboard('{Enter}');expect(select).toHaveBeenCalledWith(ganttV2Fixture.operations[1])
})
test('ocultar capas quita barras y ejecución, sin quitar nombres',()=>{
 const view=render(<GanttTimeline data={ganttV2Fixture} onSelect={vi.fn()} layers={{plan:false,execution:false,simulation:false}}/> )
 expect(view.container.querySelectorAll('.gantt-plan')).toHaveLength(0)
 expect(screen.getByRole('button',{name:/Inspeccionar Corte Fondos/})).toBeInTheDocument()
})
test('colapsar grupo con botón anuncia aria-expanded',async()=>{
 render(<GanttTimeline data={ganttV2Fixture} onSelect={vi.fn()}/> )
 const group=screen.getByRole('button',{name:/A685/});expect(group).toHaveAttribute('aria-expanded','true')
 await userEvent.click(group);expect(group).toHaveAttribute('aria-expanded','false');expect(screen.queryByRole('button',{name:/Inspeccionar Armado/})).not.toBeInTheDocument()
})
test('agrupaciones persona, recurso y centro usan IDs de asignación reales',()=>{
 for(const group_by of ['person','resource','center'] as const){const rows=hierarchy({...ganttV2Fixture,group_by,groups:[{id:'project-v2',label:'Asignación',kind:group_by}]},new Set());expect(rows.filter(r=>r.operation)).toHaveLength(4);expect(rows.some(r=>r.kind==='stage')).toBe(false)}
})
test('scroll virtual conserva filas visibles',()=>{
 const data={...ganttV2Fixture,operations:Array.from({length:250},(_,i)=>({...ganttV2Fixture.operations[0],operation_id:`scale-${i}`,operation_name:`Operación ${i}`}))}
 const view=render(<GanttTimeline data={data} onSelect={vi.fn()}/> )
 const viewport=screen.getByLabelText('Desplazar cronograma');fireEvent.scroll(viewport,{target:{scrollTop:4000}})
 expect(view.container.querySelectorAll('[data-row-kind]').length).toBeLessThan(25)
 expect(within(screen.getByRole('region',{name:/Cronograma/})).getByText(/Calendario de planta/)).toBeInTheDocument()
})
