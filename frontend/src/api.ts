// Cliente da API do front-office (/api/front/…). Autenticação por token DRF guardado no localStorage.
import { useCallback, useEffect, useState } from 'react'

const TOKEN_KEY = 'factos.token'

export class AuthError extends Error {}

export const auth = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (t: string) => localStorage.setItem(TOKEN_KEY, t),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

export async function apiGet<T>(path: string): Promise<T> {
  const token = auth.get()
  const r = await fetch(path, { headers: token ? { Authorization: `Token ${token}` } : {} })
  if (r.status === 401 || r.status === 403) {
    auth.clear()
    window.dispatchEvent(new Event('factos:logout'))
    throw new AuthError('Sessão expirada')
  }
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
  return r.json() as Promise<T>
}

export async function login(username: string, password: string): Promise<void> {
  const r = await fetch('/api/auth/token/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  if (r.status === 400) throw new Error('Utilizador ou password inválidos')
  if (!r.ok) throw new Error(`Erro do servidor (${r.status}). O backend e a base de dados estão a correr?`)
  const { token } = (await r.json()) as { token: string }
  auth.set(token)
}

export type Loaded<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void }

/** GET com recarregamento opcional (ms). Mantém os dados antigos enquanto recarrega. */
export function useApi<T>(path: string | null, refreshMs?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const reload = useCallback(() => setTick((t) => t + 1), [])

  useEffect(() => {
    if (!path) return
    let alive = true
    setLoading(true)
    apiGet<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [path, tick])

  useEffect(() => {
    if (!refreshMs) return
    const id = setInterval(reload, refreshMs)
    return () => clearInterval(id)
  }, [refreshMs, reload])

  return { data, error, loading, reload }
}
