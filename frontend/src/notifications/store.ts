export type NoticeKind = 'success' | 'error' | 'warning' | 'info'
export type Notice = {id:number;kind:NoticeKind;message:string;scope:string}
let notices:Notice[]=[]
let nextId=0
const listeners=new Set<()=>void>()
const timers=new Map<number,ReturnType<typeof setTimeout>>()
const emit=()=>listeners.forEach(listener=>listener())
export const subscribe=(listener:()=>void)=>{listeners.add(listener);return ()=>{listeners.delete(listener)}}
export const getNotices=()=>notices
export function dismissNotice(id:number){
  clearTimeout(timers.get(id));timers.delete(id)
  notices=notices.filter(notice=>notice.id!==id);emit()
}
export function notify(kind:NoticeKind,message:string,scope='manual'){
  for(const previous of notices.filter(notice=>notice.scope===scope))dismissNotice(previous.id)
  while(notices.length>=3)dismissNotice(notices[0].id)
  const notice={id:++nextId,kind,message,scope}
  notices=[...notices,notice];emit()
  // Errors remain until dismissed or superseded by the result of the same action.
  if(kind!=='error')timers.set(notice.id,setTimeout(()=>dismissNotice(notice.id),kind==='warning'?9000:6000))
}
export function clearNotices(){
  for(const timer of timers.values())clearTimeout(timer)
  timers.clear();notices=[];emit()
}
