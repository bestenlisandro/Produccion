import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router'
import { api } from '../../api/client'
import { ErrorState, Loading } from '../../components/AsyncState'
import { blockerMessage, minutes, time } from '../daily-board/presentation'
import { OperationExecution } from './OperationExecution'
import styles from './OperationDetail.module.css'

export function OperationDetail() {
  const { operationId = '' } = useParams(); const [savedReality, setSavedReality] = useState(false)
  const query = useQuery({ queryKey: ['operation', operationId], queryFn: () => api.operation(operationId) })
  if(query.isPending) return <Loading label="Cargando operación…"/>; if(query.isError) return <ErrorState retry={() => void query.refetch()}/>
  const op=query.data
  return <main><Link to="/">← Volver al tablero</Link><header><p className="eyebrow">{op.project_name} · {op.lot_name}</p><h1>{op.operation_name}</h1><span className={`status status-${op.operational_status.toLowerCase()}`}>{op.operational_status.replace('_',' ')}</span></header>
    <div className={styles.grid}><section><h2>Planificado</h2><dl><dt>Fase</dt><dd>{op.phase_name}</dd><dt>Inicio</dt><dd>{time(op.planned_start)}</dd><dt>Fin</dt><dd>{time(op.planned_finish)}</dd><dt>Prioridad</dt><dd>{op.priority}</dd><dt>Siguiente</dt><dd>{op.next_operation_name ?? 'Sin siguiente operación'}</dd></dl></section><section><h2>Recursos</h2><dl><dt>Personas</dt><dd>{(op.people ?? []).map(p=>p.name).join(', ')||'Sin asignar'}</dd><dt>Centro</dt><dd>{op.work_center??'Sin asignar'}</dd><dt>Máquina / banco</dt><dd>{op.physical_resource??'Sin asignar'}</dd></dl></section><section><h2>Real</h2><dl><dt>Estimación original</dt><dd>{minutes(op.original_estimate_minutes)}</dd><dt>Ejecutado</dt><dd>{minutes(op.executed_minutes)}</dd><dt>Restante actual</dt><dd>{minutes(op.remaining_minutes)}</dd><dt>Progreso</dt><dd>{op.progress_percent == null?'—':`${op.progress_percent}%`}</dd></dl></section></div>
    {blockerMessage(op.blocker_code)&&op.operational_status!=='FINALIZADO'&&<aside className="warning"><strong>Restricción informada por el plan</strong><p>{blockerMessage(op.blocker_code)}</p><p>La ejecución valida los requisitos actuales al guardar.</p></aside>}
    <OperationExecution operationId={operationId} onSaved={()=>setSavedReality(true)} needsReview={op.plan_requires_reconciliation} realitySaved={savedReality}/>
    </main>
}
