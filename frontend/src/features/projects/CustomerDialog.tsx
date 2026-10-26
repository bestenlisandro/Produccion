import { useEffect,useRef,useState,type FormEvent } from 'react'
import { useMutation,useQueryClient } from '@tanstack/react-query'
import { ApiError,request } from '../../api/client'
import type { components } from '../../api/schema'
import type { ProjectOptions } from './projectApi'
import styles from './Projects.module.css'

type Customer=components['schemas']['IntakeCustomer']
type Intent={body:components['schemas']['CustomerCreate'];key:string}

export function CustomerDialog({customers,onClose,onSelect}:{customers:ProjectOptions['customers'];onClose:()=>void;onSelect:(id:string)=>void}){
  const dialog=useRef<HTMLDialogElement>(null)
  const intent=useRef<Intent|null>(null)
  const [name,setName]=useState(''),[phone,setPhone]=useState(''),[email,setEmail]=useState('')
  const [uncertain,setUncertain]=useState(false)
  const cache=useQueryClient()
  useEffect(()=>{
    if(typeof dialog.current?.showModal==='function')dialog.current.showModal()
    else dialog.current?.setAttribute('open','')
  },[])
  const mutation=useMutation({retry:false,
    mutationFn:(attempt:Intent)=>request<components['schemas']['CustomerMutation']>('/customers',{method:'POST',body:JSON.stringify(attempt.body)},attempt.key),
    onSuccess:({customer}:{customer:Customer})=>{
      intent.current=null
      cache.setQueryData<ProjectOptions>(['project-options'],previous=>previous?{...previous,customers:[...previous.customers.filter(c=>c.id!==customer.id),{id:customer.id,name:customer.display_name}].sort((a,b)=>a.name.localeCompare(b.name))}:previous)
      void cache.invalidateQueries({queryKey:['project-options']})
      onSelect(customer.id)
    },
    onError:error=>{
      const unknown=!(error instanceof ApiError)||error.status>=500
      setUncertain(unknown)
      if(!unknown)intent.current=null
    },
  })
  const busy=mutation.isPending||uncertain
  const submit=(event:FormEvent)=>{
    event.preventDefault()
    if(intent.current||!name.trim())return
    intent.current={body:{display_name:name.trim(),phone:phone.trim()||null,email:email.trim()||null},key:crypto.randomUUID()}
    mutation.mutate(intent.current)
  }
  const search=name.trim().toLocaleLowerCase()
  const matches=search?customers.filter(c=>c.name.toLocaleLowerCase().includes(search)):[]
  return <dialog ref={dialog} className={styles.customerDialog} aria-labelledby="new-customer-title" onCancel={event=>{event.preventDefault();if(!busy)onClose()}}>
    <h2 id="new-customer-title">Nuevo cliente</h2>
    <form onSubmit={submit}>
      <fieldset disabled={busy}>
        <label>Nombre / razón social<input autoFocus required maxLength={200} value={name} onChange={e=>setName(e.target.value)}/></label>
        <label>Teléfono (opcional)<input type="tel" maxLength={80} value={phone} onChange={e=>setPhone(e.target.value)}/></label>
        <label>Email (opcional)<input type="email" maxLength={254} value={email} onChange={e=>setEmail(e.target.value)}/></label>
        {matches.length>0&&<div><p>Ya hay clientes con ese nombre. Podés seleccionar uno existente.</p>{matches.map(c=><button type="button" className="secondary" key={c.id} onClick={()=>onSelect(c.id)}>USAR CLIENTE EXISTENTE: {c.name}</button>)}</div>}
        <button type="submit" disabled={!name.trim()}>CREAR CLIENTE</button>
      </fieldset>
      {mutation.error&&<p role="alert">{mutation.error instanceof ApiError&&mutation.error.status===422?'Revisá el nombre, teléfono y email del cliente.':mutation.error instanceof ApiError&&mutation.error.status<500?mutation.error.message:'No pudimos confirmar la creación del cliente. Reintentá el mismo envío.'}</p>}
      {uncertain&&<button type="button" disabled={mutation.isPending} onClick={()=>{if(intent.current)mutation.mutate(intent.current)}}>REINTENTAR CREACIÓN</button>}
      <button type="button" className="secondary" disabled={busy} onClick={onClose}>CANCELAR CLIENTE</button>
    </form>
  </dialog>
}
