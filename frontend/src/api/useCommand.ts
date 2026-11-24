import {useRef} from 'react'
import {useMutation} from '@tanstack/react-query'
import {ApiError, request} from './client'

// Keep the exact payload and key after an uncertain response, including network errors.
export function useCommand(refresh: () => void | Promise<unknown>) {
  const intent = useRef<{path:string; body:unknown; method:'POST'|'PATCH'; key:string} | null>(null)
  const mutation = useMutation({
    mutationFn: () => {
      const command = intent.current!
      return request(command.path, {method: command.method, body: JSON.stringify(command.body)}, command.key)
    },
    retry: false,
    onSuccess: async () => { intent.current = null; await refresh() },
    onError: error => { if (error instanceof ApiError && error.status < 500) intent.current = null },
  })
  return {...mutation, uncertain: !!intent.current && !mutation.isPending,
    send: (path:string, body:unknown, method:'POST'|'PATCH' = 'POST') => {
      if (intent.current) return
      intent.current = {path, body: structuredClone(body), method, key: crypto.randomUUID()}
      mutation.mutate()
    },
    retry: () => mutation.mutate(),
  }
}
