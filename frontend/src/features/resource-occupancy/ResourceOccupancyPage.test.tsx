import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import type { components } from '../../api/schema'
import { http, HttpResponse, server } from '../../test/server'
import { ResourceOccupancyPage } from './ResourceOccupancyPage'

test('muestra el mismo tramo de dos horas en cada recurso de CURRENT', async () => {
  const date = '2026-11-16'
  const names = ['Emiliano', 'Gonzalo', 'Escuadradora 1']
  const day: components['schemas']['ResourceOccupancyDay'] = {
    date, status: 'available', percent: 100 * 120 / 495,
    available_minutes: 495, occupied_minutes: 120, free_minutes: 375,
    bookings: [{
      id: 'booking', project_code: 'ORD-PRUEBA', project_name: 'Alacenas', operation_name: 'Corte',
      start_at: `${date}T11:00:00Z`, end_at: `${date}T13:00:00Z`, kind: 'work',
      minutes_in_day: 120, occupied_minutes: 120, alerts: [],
    }],
  }
  server.use(http.get('/api/planning/current/resource-occupancy', () => HttpResponse.json({
    plant_name: 'Vera Mujica', timezone: 'America/Argentina/Cordoba', plan_version_number: 1,
    dates: [date],
    resources: names.map((name, index) => ({
      id: String(index), name, days: [day], group_key: index < 2 ? 'people' : 'machine',
      group_name: index < 2 ? 'Personas' : 'Escuadradora',
    })),
  })))
  const user = userEvent.setup()
  render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>
    <ResourceOccupancyPage/>
  </MemoryRouter></QueryClientProvider>)
  for (const name of names) {
    const cell = await screen.findByRole('button', {name: new RegExp(`^${name}, .*24,2 %$`)})
    expect(cell).toHaveTextContent('24,2 %')
    await user.click(cell)
    const detail = within(screen.getByRole('region', {name: 'Detalle de ocupación'}))
    expect(detail.getByRole('heading', {name})).toBeVisible()
    expect(detail.getByText('8 h 15 min')).toBeVisible()
    expect(detail.getByText('2 h 0 min')).toBeVisible()
    expect(detail.getByText('6 h 15 min')).toBeVisible()
    expect(detail.getByText('ORD-PRUEBA · Alacenas · Corte')).toBeVisible()
    expect(detail.getByText(/08:00.*→.*10:00/)).toBeVisible()
  }
})
