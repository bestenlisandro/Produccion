import {actionFor,completedAction} from '../notifications/actions'
import {notify} from '../notifications/store'
import type { components } from './schema'

export type DailyBoard = components['schemas']['DailyBoardResponse']
export type DailyOperation = components['schemas']['DailyOperationResponse']
export type OperationDetail = components['schemas']['OperationDetailResponse']
export type Scenario = components['schemas']['ScenarioResponse']
export type ReplanResult = components['schemas']['ReplanResponse']
export type RemainingResult = components['schemas']['RemainingEstimateResponse']
export type GanttData = components['schemas']['GanttResponse']
export type GanttOperation = components['schemas']['GanttOperationResponse']
export type GanttScenario = components['schemas']['GanttScenarioResponse']
export type ManualScheduleResult = components['schemas']['ManualScheduleResponse']
export type GanttGrouping = 'center' | 'resource' | 'person' | 'project'
export type MasterRecord = Record<string, unknown> & { id: string; row_version: number; status?: string }
type SnapshotContract = components['schemas']['MasterDataSnapshotResponse']
// The HTTP schema exposes open records. This adapter adds the database identity
// used by editors without duplicating the generated collection contract.
export type MasterSnapshot = {
  [K in keyof SnapshotContract]: NonNullable<SnapshotContract[K]> extends unknown[] ? MasterRecord[]
    : K extends 'plant' ? MasterRecord : SnapshotContract[K]
}
export type MasterMutation = components['schemas']['MasterMutationResponse']

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public requestId?: string) { super(safeErrorMessage(status,message)) }
}

type DevContext = { userId: string; organizationId: string; plantId: string }

function context(): DevContext {
  return {
    userId: import.meta.env.VITE_DEV_USER_ID ?? localStorage.getItem('dev-user-id') ?? '',
    organizationId: import.meta.env.VITE_DEV_ORGANIZATION_ID ?? localStorage.getItem('dev-organization-id') ?? '',
    plantId: import.meta.env.VITE_DEV_PLANT_ID ?? localStorage.getItem('dev-plant-id') ?? '',
  }
}

export function safeErrorMessage(status:number,message:unknown):string {
  if(status>=500)return 'No pudimos confirmar el resultado. Reintentá el mismo envío.'
  const fallback='No se pudo completar la solicitud. Revisá los datos e intentá nuevamente.'
  if(typeof message!=='string'||!message.trim())return fallback
  const technical=/\b(?:traceback|sqlstate|sqlalchemy|psycopg|stack trace)\b|\b\w*(?:Error|Exception):|\bSELECT\s+.+\s+FROM\b|\bINSERT\s+INTO\b|\bUPDATE\s+\S+\s+SET\b|\bDELETE\s+FROM\b|[A-Z]:\\|node_modules[\\/]/i
  if(technical.test(message))return fallback
  return message.replace(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi,'referencia interna').slice(0,600)
}

export async function request<T>(path: string, init: RequestInit = {}, idempotencyKey?: string): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')
  if (import.meta.env.VITE_CLOUD_BUILD !== 'true') {
    const value = context()
    headers.set('X-Dev-User-Id', value.userId)
    headers.set('X-Dev-Organization-Id', value.organizationId)
    headers.set('X-Dev-Plant-Id', value.plantId)
  }
  if (idempotencyKey) headers.set('Idempotency-Key', idempotencyKey)
  const method=(init.method??'GET').toUpperCase(),mutating=!['GET','HEAD'].includes(method)
  let payload:Record<string,unknown>={}
  if(typeof init.body==='string'){try{payload=JSON.parse(init.body)}catch{/* Only used for human-readable feedback. */}}
  try{
    const response = await fetch(`/api${path}`, { ...init, headers })
    if (!response.ok) {
      if (response.status === 401 && import.meta.env.VITE_CLOUD_BUILD === 'true') {
        window.location.assign('/login')
      }
      const body = await response.json().catch(() => ({})) as { error?: { code?: string; message?: string; request_id?: string } }
      throw new ApiError(response.status, body.error?.code ?? 'HTTP_ERROR',body.error?.message ?? 'No se pudo completar la solicitud.',response.headers.get('X-Request-Id')??body.error?.request_id)
    }
    let result:T
    try{result=response.status===204?undefined as T:await response.json() as T}
    catch{throw new ApiError(502,'INVALID_RESPONSE','No se pudo interpretar la respuesta.')}
    if(mutating)completedAction(path,method,payload,result)
    return result
  }catch(error){
    // A transport/parse failure has an uncertain outcome: preserve existing retry/key handling.
    const safe=error instanceof ApiError?error:new ApiError(503,'NETWORK_ERROR','No se pudo conectar.')
    console.error('API request failed',{method,path,status:safe.status,code:safe.code,requestId:safe.requestId})
    if(mutating)notify('error',actionFor(path,method,payload).failure,`${method} ${path}`)
    throw safe
  }
}

export const api = {
  day: (date: string) => request<DailyBoard>(`/planning/current/day?date=${encodeURIComponent(date)}`),
  gantt: (from: string, to: string, groupBy: GanttGrouping, scenarioId?: string) => {
    const params = new URLSearchParams({ from, to, group_by: groupBy })
    if (scenarioId) params.set('scenario_id', scenarioId)
    return request<GanttData>(`/planning/current/gantt?${params}`)
  },
  operation: (id: string) => request<OperationDetail>(`/operations/${id}`),
  updateRemaining: (id: string, phaseId: string, minutes: number) => request<RemainingResult>(`/operations/${id}/remaining-estimate`, { method: 'POST', body: JSON.stringify({ cutoff_at: new Date().toISOString(), reason: 'Actualización desde tablero diario', input_mode: 'remaining_duration', remaining: [{ dimension: 'LABOR_WORK', minutes, phase_id: phaseId }] }) }),
  replan: (id: string, cutoff = new Date().toISOString()) => request<ReplanResult>(`/operations/${id}/replan`, { method: 'POST', body: JSON.stringify({ cutoff_at: cutoff, horizon_end: new Date(Date.parse(cutoff) + 90 * 86400000).toISOString(), reason: 'Desvío operativo' }) }, crypto.randomUUID()),
  scenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  accept: (id: string, lock: number) => request(`/scenarios/${id}/accept`, { method: 'POST', body: JSON.stringify({ expected_promotion_lock_version: lock, reason: 'Confirmado desde tablero diario' }) }, crypto.randomUUID()),
  reject: (id: string, row: number) => request(`/scenarios/${id}/reject`, { method: 'POST', body: JSON.stringify({ expected_row_version: row, reason: 'Propuesta descartada por el operador' }) }, crypto.randomUUID()),
  moveActivity: (
    id: string, body: {
      base_plan_version_id: string; requested_start: string; cutoff_at: string;
      horizon_end: string; phase_id?: string | null; requested_resource_id?: string | null;
    }, commandId: string,
  ) => request<ManualScheduleResult>(`/planning/activities/${id}/move`, {
    method: 'POST', body: JSON.stringify(body),
  }, commandId),
  resizeActivity: (
    id: string, body: {
      base_plan_version_id: string; requested_duration_minutes: number;
      cutoff_at: string; horizon_end: string; phase_id?: string | null;
      resize_kind: 'PLANNED_DURATION_HYPOTHESIS';
    }, commandId: string,
  ) => request<ManualScheduleResult>(`/planning/activities/${id}/resize`, {
    method: 'POST', body: JSON.stringify(body),
  }, commandId),
  masterSnapshot: () => request<MasterSnapshot>('/master-data/snapshot'),
  mutateMaster: (path: string, method: 'POST'|'PATCH'|'PUT'|'DELETE', body: unknown, commandId: string) =>
    request<MasterMutation>(`/master-data${path}`, {
      method, body: body === undefined ? undefined : JSON.stringify(body),
    }, commandId),
}
