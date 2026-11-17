import { Link, Outlet } from 'react-router'
import {Notifications} from '../notifications/Notifications'
export function Root() {
  return <>
    <Notifications/>
    <nav>
      <strong>PRODUCCIÓN BESTEN</strong>
      <span>
        <Link to="/">Operaciones</Link>
        <Link to="/projects">Proyectos</Link>
        <Link to="/installations">Instalaciones</Link>
        <Link to="/planning/gantt">Gantt</Link>
        <Link to="/settings">Configuración</Link>
        {import.meta.env.VITE_CLOUD_BUILD === 'true' &&
          <form action="/logout" method="post"><button type="submit">Cerrar sesión</button></form>}
      </span>
    </nav>
    <Outlet/>
  </>
}
export function RouteError(){return <main className="state" role="alert"><h1>No pudimos abrir esta pantalla</h1><a href="/">Volver al tablero</a></main>}
