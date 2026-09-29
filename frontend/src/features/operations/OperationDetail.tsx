import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { ApiError, api } from '../../api/client'
import { ErrorState, Loading } from '../../components/AsyncState'
import { blockerMessage, minutes, time } from '../daily-board/presentation'
import { ReplanPanel } from '../replanning/ReplanPanel'
import styles from './OperationDetail.module.css'

export function OperationDetail() {
  const { operationId = '' } = useParams(); const qc = useQueryClient(); const [proposed, setProposed] = useState<number | null>(null); const [savedReality, setSavedReality] = useState(false)
  const query = useQuery({ queryKey: ['operation', operationId], queryFn: () => api.operation(operationId) })
  const mutation = useMutation({ mutationFn: (value:number) => api.updateRemaining(operationId, query.data!.phase_id!, value), onSuccess: async () => { setSavedReality(true); await qc.invalidateQueries({ queryKey:['operation',operationId] }); await qc.invalidateQueries({ queryKey:['daily-board'] }) } })
  if(query.isPending) return <Loading label="Cargando operación…"/>; if(query.isError) return <ErrorState retry={() => void query.refetch()}/>
  const op=query.data; const value=proposed ?? op.remaining_minutes ?? 0; const active=op.operational_status==='EN_CURSO'
  return <main><Link to="/">← Volver al tablero</Link><header><p className="eyebrow">{op.project_name} · {op.lot_name}</p><h1>{op.operation_name}</h1><span className={`status status-${op.operational_status.toLowerCase()}`}>{op.operational_status.replace('_',' ')}</span></header>
    <div className={styles.grid}><section><h2>Planificado</h2><dl><dt>Fase</dt><dd>{op.phase_name}</dd><dt>Inicio</dt><dd>{time(op.planned_start)}</dd><dt>Fin</dt><dd>{time(op.planned_finish)}</dd><dt>Prioridad</dt><dd>{op.priority}</dd><dt>Siguiente</dt><dd>{op.next_operation_name ?? 'Sin siguiente operación'}</dd></dl></section><section><h2>Recursos</h2><dl><dt>Personas</dt><dd>{(op.people ?? []).map(p=>p.name).join(', ')||'Sin asignar'}</dd><dt>Centro</dt><dd>{op.work_center??'Sin asignar'}</dd><dt>Máquina / banco</dt><dd>{op.physical_resource??'Sin asignar'}</dd></dl></section><section><h2>Real</h2><dl><dt>Estimación original</dt><dd>{minutes(op.original_estimate_minutes)}</dd><dt>Ejecutado</dt><dd>{minutes(op.executed_minutes)}</dd><dt>Restante actual</dt><dd>{minutes(op.remaining_minutes)}</dd><dt>Progreso</dt><dd>{op.progress_percent == null?'—':`${op.progress_percent}%`}</dd></dl></section></div>
    {blockerMessage(op.blocker_code)&&<aside className="warning" role="alert"><strong>Bloqueo</strong><p>{blockerMessage(op.blocker_code)}</p></aside>}
    {active&&op.phase_id&&<section className={styles.update}><h2>Actualizar tiempo restante</h2><label>Nueva estimación restante (minutos)<input type="number" min="0" value={value} onChange={e=>setProposed(Number(e.target.value))}/></label><div className={styles.shortcuts}>{[30,60,120].map(x=><button type="button" key={x} onClick={()=>setProposed(value+x)}>+{x<60?`${x} min`:`${x/60} h`}</button>)}</div><button disabled={mutation.isPending} onClick={()=>mutation.mutate(value)}>{mutation.isPending?'GUARDANDO…':'GUARDAR ESTIMACIÓN'}</button>{mutation.isError&&<p role="alert">{mutation.error instanceof ApiError?mutation.error.message:'No se pudo guardar.'}</p>}</section>}
    {(savedReality||op.plan_requires_reconciliation)&&<ReplanPanel operationId={operationId} realitySaved={savedReality}/>} </main>
}
