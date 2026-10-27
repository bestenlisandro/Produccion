import {useSyncExternalStore} from 'react'
import {dismissNotice,getNotices,subscribe} from './store'
import styles from './Notifications.module.css'

const labels={success:'Éxito',error:'Error',warning:'Atención',info:'Información'}
export function Notifications(){
  const notices=useSyncExternalStore(subscribe,getNotices,getNotices)
  return <section aria-label="Notificaciones" className={styles.viewport}>{notices.map(notice=><div key={notice.id} className={`${styles.notice} ${styles[notice.kind]}`} role={notice.kind==='error'?'alert':'status'} aria-live={notice.kind==='error'?'assertive':'polite'} aria-atomic="true"><div><strong>{labels[notice.kind]}</strong><p>{notice.message}</p></div><button type="button" className={styles.close} aria-label="Cerrar notificación" onClick={()=>dismissNotice(notice.id)}>×</button></div>)}</section>
}
