import { useEffect, useState } from 'react'
import { useApi } from '../api'
import { AiTag, Empty, ErrorBox, Loading, SiteTag, ToneDot } from '../components/ui'
import { dateTime, num, PIECE } from '../format'
import { href } from '../router'
import type { Card, Page } from '../types'

const PAGE = 50

export default function Archive({ params }: { params: URLSearchParams }) {
  const [q, setQ] = useState(params.get('q') ?? '')
  useEffect(() => setQ(params.get('q') ?? ''), [params])
  const offset = Number(params.get('offset') ?? 0)
  const api = new URLSearchParams()
  for (const k of ['q', 'site', 'topic', 'entity', 'piece_type', 'since', 'until']) {
    const v = params.get(k)
    if (v) api.set(k, v)
  }
  api.set('limit', String(PAGE))
  api.set('offset', String(offset))
  const { data, error, loading, reload } = useApi<Page<Card>>(`/api/front/articles/?${api}`)

  const current = Object.fromEntries(params.entries())
  const go = (patch: Record<string, string | undefined>) => {
    window.location.hash = href.archive({ ...current, offset: undefined, ...patch })
  }
  const label = params.get('label')

  return (
    <div className="archive">
      <header className="detail-head">
        <h1 className="detail-title">Arquivo</h1>
        <p className="detail-lead">Todas as notícias recolhidas, das mais recentes para as mais antigas.</p>
      </header>
      <form className="filters" onSubmit={(e) => { e.preventDefault(); go({ q }) }}>
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Palavras no título…" aria-label="Pesquisar no título" />
        <select value={params.get('site') ?? ''} onChange={(e) => go({ site: e.target.value })} aria-label="Meio">
          <option value="">Todos os meios</option>
          <option value="jn">JN</option>
          <option value="publico">Público</option>
          <option value="observador">Observador</option>
        </select>
        <select value={params.get('piece_type') ?? ''} onChange={(e) => go({ piece_type: e.target.value })} aria-label="Tipo de peça">
          <option value="">Todos os tipos</option>
          {Object.entries(PIECE).filter(([k]) => k !== 'desconhecido').map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <input type="date" value={params.get('since') ?? ''} onChange={(e) => go({ since: e.target.value })} aria-label="Desde" />
        <input type="date" value={params.get('until') ?? ''} onChange={(e) => go({ until: e.target.value })} aria-label="Até" />
        <button type="submit">Pesquisar</button>
        {(params.get('topic') || params.get('entity')) && (
          <button type="button" className="chip chip-x" onClick={() => go({ topic: undefined, entity: undefined, label: undefined })}>
            {label ?? 'filtro'} ✕
          </button>
        )}
      </form>
      {error && <ErrorBox error={error} retry={reload} />}
      {!data ? <Loading /> : data.results.length === 0 ? <Empty>Nenhuma notícia com estes filtros.</Empty> : (
        <>
          <p className="muted">{num(data.count)} notícias{loading ? ' · a carregar…' : ''}</p>
          <table className="archive-table">
            <thead>
              <tr><th>Data</th><th>Meio</th><th>Título</th><th>Temas</th><th>Entidades</th><th title="Tom">Tom</th><th>IA</th></tr>
            </thead>
            <tbody>
              {data.results.map((a) => (
                <tr key={a.id}>
                  <td className="mono nowrap">{dateTime(a.published_at)}</td>
                  <td><SiteTag site={a.site} /></td>
                  <td>
                    <a href={href.article(a.id)} className="archive-title">{a.title}</a>
                    {a.piece_type && a.piece_type !== 'noticia' && <span className="piece">{PIECE[a.piece_type] ?? a.piece_type}</span>}
                  </td>
                  <td>{a.topics.slice(0, 2).map((t) => <a key={t.id} className="chip" href={href.topic(t.id)}>{t.name}</a>)}</td>
                  <td className="ents">
                    {(a.entities ?? []).slice(0, 4).map((e, i) => (
                      <span key={e.id}>{i > 0 && ', '}<a href={href.entity(e.id)}>{e.name}</a></span>
                    ))}
                  </td>
                  <td><ToneDot tone={a.tone} /></td>
                  <td>{a.ai_score !== null && (a.ai ? <AiTag ai score={a.ai_score} /> : <span className="muted mono">{a.ai_score}</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <nav className="pager">
            <button type="button" disabled={offset === 0} onClick={() => go({ offset: String(Math.max(0, offset - PAGE)) })}>← Mais recentes</button>
            <span className="mono">{offset + 1}–{Math.min(offset + PAGE, data.count)} de {num(data.count)}</span>
            <button type="button" disabled={!data.next} onClick={() => go({ offset: String(offset + PAGE) })}>Mais antigas →</button>
          </nav>
        </>
      )}
    </div>
  )
}
