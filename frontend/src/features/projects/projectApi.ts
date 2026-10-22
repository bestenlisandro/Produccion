import type { components } from '../../api/schema'
import { request } from '../../api/client'

export type Project = components['schemas']['IntakeProject']
export type ProjectOptions = components['schemas']['IntakeOptions']
export const projectApi = {
  list: () => request<Project[]>('/projects'),
  detail: (id: string) => request<Project>(`/projects/${id}`),
  options: () => request<ProjectOptions>('/project-intake/options'),
  save: (path: string, method: 'POST'|'PATCH', body: unknown, key: string) =>
    request<Project|components['schemas']['IntakeMutation']>(path, {method, body: JSON.stringify(body)}, key),
}
