import type { DailyOperation } from '../../api/client'

export const statusOrder: Record<string, number> = { EN_CURSO: 0, DEMORADO: 1, BLOQUEADO: 2, LISTO: 3, PENDIENTE: 4, FINALIZADO: 5 }

export function sortOperations(values: DailyOperation[]) {
  return [...values].sort((a, b) => (statusOrder[a.operational_status] ?? 9) - (statusOrder[b.operational_status] ?? 9)
    || a.planned_start.localeCompare(b.planned_start) || a.priority_rank - b.priority_rank || a.operation_id.localeCompare(b.operation_id))
}

export const blockerMessages: Record<string, string> = {
  PERSON_UNAVAILABLE: 'No hay personal disponible con la habilidad requerida.',
  REQUIRED_SKILL_UNAVAILABLE: 'No hay personal disponible con la habilidad requerida.',
  PHYSICAL_RESOURCE_OCCUPIED: 'El recurso necesario está ocupado.',
  CUMULATIVE_CAPACITY_EXHAUSTED: 'El centro de trabajo no tiene capacidad disponible en ese horario.',
  MATERIAL_NOT_AVAILABLE: 'El material todavía no está disponible.',
  DRAWINGS_NOT_AVAILABLE: 'Los planos todavía no están liberados.',
  HARDWARE_NOT_AVAILABLE: 'Faltan herrajes para completar esta etapa.',
  OUTSIDE_WORKING_CALENDAR: 'Está fuera del horario de trabajo disponible.',
  OUT_OF_HORIZON: 'No se pudo programar dentro del horizonte actual.',
}

export const blockerMessage = (code?: string | null) => code ? blockerMessages[code] ?? `Bloqueo informado: ${code.replaceAll('_', ' ').toLowerCase()}.` : null
export const minutes = (value?: number | null) => value == null ? '—' : `${Math.floor(value / 60)} h ${value % 60} min`
export const time = (value: string) => new Intl.DateTimeFormat('es-AR', { hour: '2-digit', minute: '2-digit' }).format(new Date(value))
