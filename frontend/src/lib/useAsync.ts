/**
 * Loading one thing from the API, with the three states a screen actually has.
 *
 * Small on purpose: the UI has five read endpoints and no cache, no polling and no
 * optimistic updates, so a data-fetching library would be more machinery than the problem
 * has. What it does handle is what a hand-rolled `useEffect` usually gets wrong:
 *
 * - a response that arrives after the component unmounted, or after a newer request
 *   started, never overwrites fresher state;
 * - the in-flight request is aborted when the inputs change, so a slow first request
 *   cannot land on top of a fast second one;
 * - `reload()` is stable, so a refresh button does not re-render the tree.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { DependencyList } from 'react'

import { ApiError, asApiError } from '../api/client'

export interface AsyncState<T> {
  data: T | null
  error: ApiError | null
  loading: boolean
  reload: () => void
}

export function useAsync<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const loadRef = useRef(load)
  useEffect(() => {
    loadRef.current = load
  })

  useEffect(() => {
    const controller = new AbortController()
    let current = true
    setLoading(true)
    setError(null)

    loadRef.current(controller.signal).then(
      (result) => {
        if (!current) {
          return
        }
        setData(result)
        setLoading(false)
      },
      (thrown: unknown) => {
        if (!current || (thrown instanceof DOMException && thrown.name === 'AbortError')) {
          return
        }
        setError(asApiError(thrown))
        setLoading(false)
      },
    )

    return () => {
      current = false
      controller.abort()
    }
    // `deps` is the caller's dependency list, plus the reload counter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => {
    setNonce((value) => value + 1)
  }, [])

  return { data, error, loading, reload }
}
