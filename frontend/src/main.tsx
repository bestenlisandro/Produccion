import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { queryClient } from './app/queryClient'
import { DailyBoard } from './features/daily-board/DailyBoard'
import { OperationDetail } from './features/operations/OperationDetail'
import { GanttPage } from './features/gantt/GanttPage'
import { MasterDataPage } from './features/master-data/MasterDataPage'
import { ProjectsPage,NewProjectPage,ProjectDetailPage } from './features/projects/Projects'
import { Root, RouteError } from './routes/Root'
import './styles/global.css'

const router=createBrowserRouter([{path:'/',Component:Root,ErrorBoundary:RouteError,children:[{index:true,Component:DailyBoard},{path:'projects',Component:ProjectsPage},{path:'projects/new',Component:NewProjectPage},{path:'projects/:projectId',Component:ProjectDetailPage},{path:'operations/:operationId',Component:OperationDetail},{path:'planning/gantt',Component:GanttPage},{path:'settings',Component:MasterDataPage}]}])
createRoot(document.getElementById('root')!).render(<StrictMode><QueryClientProvider client={queryClient}><RouterProvider router={router}/></QueryClientProvider></StrictMode>)
