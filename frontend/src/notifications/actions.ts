import {notify} from './store'

type Action={success:string;failure:string}
export function actionFor(path:string,method:string,body:Record<string,unknown>={}):Action{
  const p=path.split('?')[0]
  if(p.endsWith('/product-definition')&&method==='PUT')return {success:'Borrador guardado correctamente.',failure:'No se pudo guardar el borrador.'}
  if(p.endsWith('/product-definition/validate'))return {success:'Definición validada correctamente.',failure:'No se pudo validar la definición.'}
  if(p.endsWith('/product-definition/freeze'))return {success:'Revisión congelada correctamente.',failure:'No se pudo congelar la revisión.'}
  if(p.endsWith('/product-definition/new-revision'))return {success:'Nueva revisión creada correctamente.',failure:'No se pudo crear la nueva revisión.'}
  if(p.endsWith('/release'))return {success:'Proyecto liberado a planificación.',failure:'No se pudo liberar el proyecto.'}
  if(p.endsWith('/unrelease'))return {success:'Proyecto retirado de planificación.',failure:'No se pudo retirar el proyecto de planificación.'}
  if(/\/(simulations|replan|installation-plan)$/.test(p))return {success:'Simulación generada correctamente.',failure:'No se pudo generar la simulación.'}
  if(/\/planning\/activities\/.+\/(move|resize)$/.test(p))return {success:'Simulación del cambio generada correctamente.',failure:'No se pudo simular el cambio.'}
  if(p.endsWith('/accept'))return {success:'Nuevo plan confirmado.',failure:'No se pudo confirmar el nuevo plan.'}
  if(p.endsWith('/reject'))return {success:'Propuesta descartada correctamente.',failure:'No se pudo descartar la propuesta.'}
  if(p.endsWith('/measurement'))return {success:'Medición registrada correctamente.',failure:'No se pudo registrar la medición.'}
  if(p.endsWith('/replanteo'))return {success:'Replanteo registrado correctamente.',failure:'No se pudo registrar el replanteo.'}
  if(p.endsWith('/installation-location'))return {success:'Ubicación actualizada correctamente.',failure:'No se pudo actualizar la ubicación.'}
  if(p==='/customers'&&method==='POST')return {success:'Cliente creado correctamente.',failure:'No se pudo crear el cliente.'}
  if(p==='/projects'&&method==='POST')return {success:'Proyecto creado correctamente.',failure:'No se pudo crear el proyecto.'}
  if(/^\/projects\/[^/]+$/.test(p)&&method==='PATCH')return {success:'Proyecto actualizado correctamente.',failure:'No se pudo actualizar el proyecto.'}
  if(p.endsWith('/status'))return {success:body.status==='archived'?'Registro archivado correctamente.':'Estado actualizado correctamente.',failure:'No se pudo actualizar el estado.'}
  if(p.endsWith('/remaining-estimate'))return {success:'Estimación restante guardada correctamente.',failure:'No se pudo guardar la estimación restante.'}
  if(p.endsWith('/start'))return {success:'Operación iniciada correctamente.',failure:'No se pudo iniciar la operación.'}
  if(p.endsWith('/segments'))return {success:'Tramo de ejecución registrado correctamente.',failure:'No se pudo registrar el tramo de ejecución.'}
  if(p.endsWith('/finish'))return {success:'Fase finalizada correctamente.',failure:'No se pudo finalizar la fase.'}
  if(p.endsWith('/complete'))return {success:'Proyecto cerrado correctamente.',failure:'No se pudo cerrar el proyecto.'}
  if(p.startsWith('/master-data/'))return {success:'Cambios guardados correctamente.',failure:'No se pudieron guardar los cambios.'}
  return {success:'Acción completada correctamente.',failure:'No se pudo completar la acción.'}
}
export function completedAction(path:string,method:string,body:Record<string,unknown>,result:unknown){
  const scope=`${method} ${path}`,action=actionFor(path,method,body)
  const data=result&&typeof result==='object'?result as Record<string,unknown>:{}
  if(path.endsWith('/product-definition/validate')&&Array.isArray(data.errors)&&data.errors.length){
    notify('warning','Hay errores que deben corregirse antes de congelar.',scope)
  }else if(data.complete===false&&/\/(simulations|replan|installation-plan)$/.test(path)){
    notify('warning','Simulación generada con operaciones pendientes. Revisá los bloqueos antes de confirmar.',scope)
  }else if(data.plan_requires_reconciliation){
    notify('warning','Cambios guardados. El plan requiere reconciliación.',scope)
  }else notify('success',action.success,scope)
}
