import { useState } from 'react'
import { useApi } from '../api'
import { AiTag, ArticleRow, Empty, ErrorBox, Kicker, Loading, SiteTag, ToneDot } from '../components/ui'
import { dateTime, ENTITY_TYPE, PIECE, SOURCE_TYPE } from '../format'
import { href } from '../router'
import type { ArticleDetail, Related } from '../types'

export default function ArticlePage({ id }: { id: number }) {
  const { data: a, error, reload } = useApi<ArticleDetail>(`/api/front/articles/${id}/`)
  const [showText, setShowText] = useState(false)
  if (!a || a.id !== id) return error ? <ErrorBox error={error} retry={reload} /> : <Loading />
  const people = a.entities.filter((e) => !e.is_location)
  const places = a.entities.filter((e) => e.is_location)
  const authors = a.authors.map((x) => (typeof x === 'string' ? x : x.name ?? '')).filter(Boolean)
  return (
    <article className="detail">
      <header className="detail-head">
        <div className="detail-crumbs">
          <SiteTag site={a.site} /> {a.site_name}
          {a.section && <span> · {a.section}</span>}
          <span> · {dateTime(a.published_at)}</span>
          {a.piece_type && <span className="piece">{PIECE[a.piece_type] ?? a.piece_type}</span>}
        </div>
        <h1 className="detail-title">{a.title}</h1>
        {a.lead && <p className="detail-lead">{a.lead}</p>}
        <div className="detail-meta">
          {authors.length > 0 && <span>Por {authors.join(', ')}</span>}
          <span className="tone-label"><ToneDot tone={a.tone} /> tom {a.tone ?? 'por analisar'}</span>
          <AiTag ai={a.ai} score={a.ai_score} />
          {a.ai === false && <span className="muted">IA {a.ai_score}%</span>}
          <a href={a.url} target="_blank" rel="noreferrer" className="ext">Ler no {a.site_name} ↗</a>
        </div>
        {a.topics_full.length > 0 && (
          <div className="chips">
            {a.topics_full.map((t) => (
              <a key={t.id} className="chip" href={href.topic(t.id)} title={`peso ${t.weight}`}>
                {t.parent && <span className="chip-parent">{t.parent} › </span>}
                {t.name}
                {t.edition && <span className="chip-ed"> · {t.edition}</span>}
              </a>
            ))}
          </div>
        )}
      </header>

      <div className="detail-grid">
        <div className="detail-main">
          {a.summary && (
            <section>
              <Kicker>Resumo da análise</Kicker>
              <p className="summary">{a.summary}</p>
            </section>
          )}

          <section>
            <Kicker>Quem aparece e como</Kicker>
            {people.length === 0 ? <Empty>Sem entidades.</Empty> : (
              <table className="entity-table">
                <thead>
                  <tr><th>Entidade</th><th>Papel</th><th>Tom</th><th>Porquê</th></tr>
                </thead>
                <tbody>
                  {people.map((e) => (
                    <tr key={`${e.id}-${e.name_in_text}`}>
                      <td>
                        <a href={href.entity(e.id)}>{e.name}</a>
                        <small>{ENTITY_TYPE[e.type] ?? e.type}{e.position ? ` · ${e.position}` : ''}</small>
                      </td>
                      <td>{e.roles.join(', ')}</td>
                      <td><ToneDot tone={e.sentiment} /> {e.sentiment}</td>
                      <td className="evidence">{e.evidence}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {places.length > 0 && (
              <p className="places-inline">
                <strong>Locais:</strong>{' '}
                {places.map((p, i) => (
                  <span key={p.id}>{i > 0 && ', '}<a href={href.entity(p.id)}>{p.name}</a></span>
                ))}
              </p>
            )}
          </section>

          {a.sources.length > 0 && (
            <section>
              <Kicker>Fontes citadas</Kicker>
              <ul className="sources">
                {a.sources.map((s, i) => (
                  <li key={i}>
                    <span className={`src-type src-${s.type}`}>{SOURCE_TYPE[s.type] ?? s.type}</span>
                    <span>
                      {s.entity_id ? <a href={href.entity(s.entity_id)}>{s.name}</a> : s.name}
                      {s.partial_attribute && <em> — {s.partial_attribute}</em>}
                    </span>
                    {s.excerpt && <q>{s.excerpt}</q>}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <Kicker>Texto</Kicker>
            <div className={`fulltext ${showText ? 'open' : ''}`}>
              {a.text.split(/\n+/).map((p, i) => <p key={i}>{p}</p>)}
            </div>
            <button type="button" className="link-btn" onClick={() => setShowText((v) => !v)}>
              {showText ? 'Recolher' : `Mostrar o texto todo (${a.word_count} palavras)`}
            </button>
          </section>
        </div>

        <aside className="detail-side">
          {a.duplicates.length > 0 && (
            <section>
              <Kicker>Mesmo texto de origem</Kicker>
              <ul className="article-list">
                {a.duplicates.map((d) => (
                  <ArticleRow key={d.id} a={d}
                    extra={<span className="sim">{Math.round(d.similarity * 100)}% igual{d.is_original ? ' · original' : ''}</span>} />
                ))}
              </ul>
            </section>
          )}
          <RelatedList title="Mesmo tema" items={a.related.same_topic} empty="Sem outras notícias do tema." />
          <RelatedList title="Outros temas, mesmas pessoas" items={a.related.other_topics}
            empty="Sem ligações por entidades fora do tema."
            note="Notícias de temas diferentes que partilham entidades pouco comuns." />

          <section>
            <Kicker>Versões</Kicker>
            <ol className="versions-list">
              {a.versions.map((v) => (
                <li key={v.number}>
                  <span className="mono">v{v.number}</span> {dateTime(v.created_at)}
                  {v.number > 1 && <span className="muted"> · {Math.round(v.change_ratio * 100)}% alterado</span>}
                </li>
              ))}
            </ol>
          </section>
          {a.analysis && (
            <p className="footnote">
              Análise da v{a.analysis.version_number} por {a.analysis.model} ({a.analysis.prompt_version}).
            </p>
          )}
        </aside>
      </div>
    </article>
  )
}

function RelatedList({ title, items, empty, note }: { title: string; items: Related[]; empty: string; note?: string }) {
  return (
    <section>
      <Kicker>{title}</Kicker>
      {note && <p className="rail-note">{note}</p>}
      {items.length === 0 ? <Empty>{empty}</Empty> : (
        <ul className="article-list">
          {items.map((r) => (
            <ArticleRow key={r.id} a={r} extra={r.shared_entities.length > 0 && (
              <div className="shared">
                via {r.shared_entities.slice(0, 3).map((e, i) => (
                  <span key={e.id}>{i > 0 && ', '}<a href={href.entity(e.id)}>{e.name}</a></span>
                ))}
              </div>
            )} />
          ))}
        </ul>
      )}
    </section>
  )
}
