import { useState, useEffect, useCallback, useRef } from 'react'
import { supabase } from '../lib/supabase'

interface RpcState<T> {
  data: T | null
  loading: boolean
  error: string | null
}

export function useSupabaseRpc<T>(
  fnName: string,
  params?: Record<string, unknown>,
  deps?: unknown[]
): RpcState<T> & { refetch: () => void } {
  const [state, setState] = useState<RpcState<T>>({ data: null, loading: true, error: null })
  const paramsRef = useRef(params)
  paramsRef.current = params

  // Monotonic request id: only the newest in-flight request may commit state,
  // so a slow earlier response can't clobber a newer one.
  const requestIdRef = useRef(0)
  // Guard against setState after unmount.
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
    }
  }, [])

  const fetch = useCallback(async () => {
    const requestId = ++requestIdRef.current
    setState(s => ({ ...s, loading: true, error: null }))
    const { data, error } = await supabase.rpc(fnName, paramsRef.current ?? {})
    // Drop the response if a newer request has started or we've unmounted.
    if (!mountedRef.current || requestId !== requestIdRef.current) return
    if (error) setState({ data: null, loading: false, error: error.message })
    else setState({ data: data as T, loading: false, error: null })
  }, [fnName, ...(deps ?? [])]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { void fetch() }, [fetch])

  return { ...state, refetch: fetch }
}
