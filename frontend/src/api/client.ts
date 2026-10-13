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
export type GanttGrouping = 'center' | 'resource' | 'person' | 'project'

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message) }
}

type DevContext = { userId: string; organizationId: string; plantId: string }

function context(): DevContext {
  return {
    userId: import.meta.env.VITE_DEV_USER_ID ?? localStorage.getItem('dev-user-id') ?? '',
    organizationId: import.meta.env.VITE_DEV_ORGANIZATION_ID ?? localStorage.getItem('dev-organization-id') ?? '',
    plantId: import.meta.env.VITE_DEV_PLANT_ID ?? localStorage.getItem('dev-plant-id') ?? '',
  }
}

async function request<T>(path: string, init: RequestInit = {}, idempotent = false): Promise<T> {
  const value = context()
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body) headers.set('Content-Type', 'application/json')
  headers.set('X-Dev-User-Id', value.userId)
  headers.set('X-Dev-Organization-Id', value.organizationId)
  headers.set('X-Dev-Plant-Id', value.plantId)
  if (idempotent) headers.set('Idempotency-Key', crypto.randomUUID())
  const response = await fetch(`/api${path}`, { ...init, headers })
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { error?: { code?: string; message?: string }; detail?: unknown }
    throw new ApiError(response.status, body.error?.code ?? 'HTTP_ERROR', body.error?.message ?? 'No se pudo completar la solicitud.')
  }
  return response.json() as Promise<T>
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
  replan: (id: string) => request<ReplanResult>(`/operations/${id}/replan`, { method: 'POST', body: JSON.stringify({ cutoff_at: new Date().toISOString(), horizon_end: new Date(Date.now() + 90 * 86400000).toISOString(), reason: 'Desvío operativo' }) }, true),
  scenario: (id: string) => request<Scenario>(`/scenarios/${id}`),
  accept: (id: string, lock: number) => request(`/scenarios/${id}/accept`, { method: 'POST', body: JSON.stringify({ expected_promotion_lock_version: lock, reason: 'Confirmado desde tablero diario' }) }, true),
  reject: (id: string, row: number) => request(`/scenarios/${id}/reject`, { method: 'POST', body: JSON.stringify({ expected_row_version: row, reason: 'Propuesta descartada por el operador' }) }, true),
}
