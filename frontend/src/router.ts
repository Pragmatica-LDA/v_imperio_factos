// Router mínimo por hash (#/noticia/12, #/arquivo?q=…). Sem dependências.
import { useEffect, useState } from 'react'

export type Route =
  | { name: 'home' }
  | { name: 'article'; id: number }
  | { name: 'entity'; id: number }
  | { name: 'topic'; id: number }
  | { name: 'archive'; params: URLSearchParams }

export function parse(hash: string): Route {
  const [path, query = ''] = hash.replace(/^#/, '').split('?')
  const parts = path.split('/').filter(Boolean)
  const id = Number(parts[1])
  switch (parts[0]) {
    case 'noticia':
      return { name: 'article', id }
    case 'entidade':
      return { name: 'entity', id }
    case 'tema':
      return { name: 'topic', id }
    case 'arquivo':
      return { name: 'archive', params: new URLSearchParams(query) }
    default:
      return { name: 'home' }
  }
}

export const href = {
  home: () => '#/',
  article: (id: number) => `#/noticia/${id}`,
  entity: (id: number) => `#/entidade/${id}`,
  topic: (id: number) => `#/tema/${id}`,
  archive: (p: Record<string, string | number | undefined> = {}) => {
    const q = new URLSearchParams()
    for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== '') q.set(k, String(v))
    const s = q.toString()
    return `#/arquivo${s ? `?${s}` : ''}`
  },
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const on = () => {
      setRoute(parse(window.location.hash))
      window.scrollTo({ top: 0 })
    }
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}
