import { useCallback, useEffect, useRef, useState } from 'react'
import { StudioError, api } from '../api/client'

interface State<T> {
  data: T | null
  loading: boolean
  error: StudioError | null
}

/** GET with a manual refresh and an optional poll, used for job states. */
export function useResource<T>(path: string | null, pollMs = 0) {
  const [state, setState] = useState<State<T>>({ data: null, loading: !!path, error: null })
  const alive = useRef(true)

  const load = useCallback(async () => {
    if (!path) return
    try {
      const data = await api.get<T>(path)
      if (alive.current) setState({ data, loading: false, error: null })
    } catch (error) {
      if (alive.current) {
        setState((prev) => ({ ...prev, loading: false, error: error as StudioError }))
      }
    }
  }, [path])

  useEffect(() => {
    alive.current = true
    setState((prev) => ({ ...prev, loading: !!path }))
    void load()
    return () => {
      alive.current = false
    }
  }, [load, path])

  useEffect(() => {
    if (!pollMs || !path) return
    const timer = window.setInterval(() => void load(), pollMs)
    return () => window.clearInterval(timer)
  }, [load, pollMs, path])

  return { ...state, reload: load, setData: (data: T) => setState({ data, loading: false, error: null }) }
}

/** A mutation that reports its own progress and error, for one button. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<StudioError | null>(null)

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setBusy(true)
    setError(null)
    try {
      return await fn()
    } catch (caught) {
      setError(caught as StudioError)
      return null
    } finally {
      setBusy(false)
    }
  }, [])

  return { busy, error, run, clearError: () => setError(null) }
}
