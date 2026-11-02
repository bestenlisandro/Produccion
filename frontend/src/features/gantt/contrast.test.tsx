import {render,screen} from '@testing-library/react'
import {expect,test,vi} from 'vitest'
import tokens from './ganttTokens.css?raw'
import {GanttTimeline} from './GanttTimeline'
import {ganttV2Fixture,initialV2Fixture} from '../../test/ganttV2Fixture'

const palette=Object.fromEntries([...tokens.matchAll(/(--gantt-[\w-]+):\s*(#[\da-f]{6});/gi)].map(m=>[m[1],m[2]]))
function luminance(hex:string){
 const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(n=>n<=.04045?n/12.92:((n+.055)/1.055)**2.4)
 return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722
}
const ratio=(a:string,b:string)=>{const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}

test('texto de cada estado cumple contraste AA de 4.5:1',()=>{
 for(const state of ['executed','in-progress','planned','blocked','delayed'])expect(ratio(palette['--gantt-on-dark'],palette[`--gantt-${state}`]),state).toBeGreaterThanOrEqual(4.5)
 for(const background of ['simulation-bg','simulation-pattern'])expect(ratio(palette['--gantt-simulation-text'],palette[`--gantt-${background}`])).toBeGreaterThanOrEqual(4.5)
 expect(ratio(palette['--gantt-blocked-text'],palette['--gantt-simulation-bg'])).toBeGreaterThanOrEqual(4.5)
 for(const background of ['working-bg','offshift-bg','weekend-bg']){
  expect(ratio(palette['--gantt-simulation'],palette[`--gantt-${background}`])).toBeGreaterThanOrEqual(3)
  expect(ratio(palette['--gantt-selected-border'],palette[`--gantt-${background}`])).toBeGreaterThanOrEqual(3)
  expect(ratio(palette['--gantt-dependency'],palette[`--gantt-${background}`])).toBeGreaterThanOrEqual(3)
 }
})
test('selección persistente tiene estado accesible y contorno independiente del fill',()=>{
 const view=render(<GanttTimeline data={ganttV2Fixture} selectedId="op-2" onSelect={vi.fn()}/>)
 expect(screen.getAllByRole('button',{name:/Plan vigente.*Armado/}).every(b=>b.getAttribute('aria-pressed')==='true')).toBe(true)
 expect(view.container.querySelectorAll('[data-selected=true]')).toHaveLength(1)
 expect(view.container.querySelectorAll('rect[class*=selectedOutline]')).toHaveLength(2)
})
test('simulación usa trama SVG además de clase y etiqueta, incluso bloqueada',()=>{
 const view=render(<GanttTimeline data={initialV2Fixture} onSelect={vi.fn()}/>)
 const blocked=screen.getAllByRole('button',{name:/Simulación.*Armado.*BLOQUEADO/})
 expect(blocked).toHaveLength(2)
 expect(blocked.every(b=>b.getAttribute('style')?.includes('gantt-simulation-'))).toBe(true)
 expect(view.container.querySelector('pattern line')).toBeInTheDocument()
 expect(view.container.querySelector('[class*=statusIcon]')).toHaveTextContent('⚠')
})
test('Todas atenúa relaciones ajenas a selección sin alterar las precedencias',()=>{
 const view=render(<GanttTimeline data={ganttV2Fixture} selectedId="op-0" dependencies="all" onSelect={vi.fn()}/>)
 expect(view.container.querySelectorAll('[data-dependency]')).toHaveLength(3)
 expect(view.container.querySelectorAll('[data-related=true]')).toHaveLength(1)
 expect(view.container.querySelectorAll('path[class*=edgeMuted]')).toHaveLength(2)
})
