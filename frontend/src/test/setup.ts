import {clearNotices} from '../notifications/store'
import {act} from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { server } from './server'
beforeAll(()=>server.listen({onUnhandledRequest:'error'}));afterEach(()=>{act(clearNotices);server.resetHandlers()});afterAll(()=>server.close())
