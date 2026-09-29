import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
  use: { baseURL: 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  webServer: { command: 'npm run preview -- --host 127.0.0.1 --port 4173', url: 'http://127.0.0.1:4173', reuseExistingServer: true },
  projects: [
    { name: 'desktop-1440', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'desktop-1366', use: { viewport: { width: 1366, height: 768 } } },
    { name: 'tablet-1024', use: { viewport: { width: 1024, height: 768 } } },
    { name: 'smartphone-390', use: { viewport: { width: 390, height: 844 } } }
  ]
})
