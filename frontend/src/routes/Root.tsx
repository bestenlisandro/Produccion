import { Outlet } from 'react-router'
export function Root(){return <><nav><strong>PRODUCCIÓN BESTEN</strong><span>Operaciones</span></nav><Outlet/></>}
export function RouteError(){return <main className="state" role="alert"><h1>No pudimos abrir esta pantalla</h1><a href="/">Volver al tablero</a></main>}
