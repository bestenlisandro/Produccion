import { Link, Outlet } from 'react-router'
export function Root(){return <><nav><strong>PRODUCCIÓN BESTEN</strong><span><Link to="/">Operaciones</Link><Link to="/projects">Proyectos</Link><Link to="/planning/gantt">Gantt</Link><Link to="/settings">Configuración</Link></span></nav><Outlet/></>}
export function RouteError(){return <main className="state" role="alert"><h1>No pudimos abrir esta pantalla</h1><a href="/">Volver al tablero</a></main>}
