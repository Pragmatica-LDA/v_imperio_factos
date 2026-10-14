import { useApi } from '../api'
import { ArticleRow, DayBars, Empty, ErrorBox, Kicker, Loading, SiteTag, StackBar, ToneDot } from '../components/ui'
import { ENTITY_TYPE, num } from '../format'
import { href } from '../router'
import type { EntityDetail } from '../types'

export default function EntityPage({ id }: { id: number }) {
  const { data: e, error, reload } = useApi<EntityDetail>(`/api/front/entities/${id}/`)
  if (!e || e.id !== id) return error ? <ErrorBox error={error} retry={reload} /> : <Loading />
  const s = e.sentiment
  const roles = Object.entries(e.roles)
  return (
    <div className="detail">
      <header className="detail-head">
        <div className="detail-crumbs">
          {ENTITY_TYPE[e.type] ?? e.type}
          {e.status === 'por_rever' && <span className="badge">por rever</span>}
          {e.is_public === true && <span className="badge">figura pública</span>}
          {e.merged_into && <a href={href.entity(e.merged_into)} className="badge">fundida → ver destino</a>}
        </div>
        <h1 className="detail-title">{e.name}</h1>
        {e.positions.length > 0 && <p className="detail-lead">{e.positions.join(' · ')}</p>}
        {e.aliases.length > 0 && <p className="muted">Também: {e.aliases.join(', ')}</p>}
      </header>

      <div className="stat-row">
        <div className="stat"><span className="stat-n">{num(e.n_articles)}</span><span>notícias</span></div>
        <div className="stat stat-wide">
          <span>Tom das menções</span>
          <StackBar height={12} parts={[
            { key: 'positivo', value: s.positivo, label: 'Positivo' },
            { key: 'neutro', value: s.neutro, label: 'Neutro' },
            { key: 'negativo', value: s.negativo, label: 'Negativo' },
          ]} />
          <small>
            <ToneDot tone="positivo" /> {s.positivo} · <ToneDot tone="neutro" /> {s.neutro} · <ToneDot tone="negativo" /> {s.negativo}
          </small>
        </div>
        <div className="stat">
          <span>Por meio</span>
          <span className="site-counts">
            {Object.entries(e.sites).map(([k, v]) => <span key={k}><SiteTag site={k} /> {v}</span>)}
          </span>
        </div>
        <div className="stat stat-wide">
          <span>Notícias por dia</span>
          <DayBars days={e.series} h={50} />
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Kicker>Notícias</Kicker>
          {e.articles.length === 0 ? <Empty>Sem notícias.</Empty> : (
            <ul className="article-list">
              {e.articles.map((a) => (
                <ArticleRow key={a.id} a={a} extra={a.entity_sentiment && (
                  <span className="muted small"><ToneDot tone={a.entity_sentiment} /> {a.entity_sentiment} para {e.name}</span>
                )} />
              ))}
            </ul>
          )}
          <p><a href={href.archive({ entity: e.id, label: e.name })}>Ver tudo no arquivo →</a></p>
        </div>
        <aside className="detail-side">
          {roles.length > 0 && (
            <section>
              <Kicker>Papéis</Kicker>
              <ul className="kv">{roles.map(([k, v]) => <li key={k}><span>{k}</span><span className="mono">{v}</span></li>)}</ul>
            </section>
          )}
          <section>
            <Kicker>Aparece com</Kicker>
            <ul className="kv">
              {e.co_entities.map((c) => (
                <li key={c.id}><a href={href.entity(c.id)}>{c.name}</a><span className="mono">{c.n}</span></li>
              ))}
            </ul>
          </section>
          <section>
            <Kicker>Temas</Kicker>
            <div className="chips">
              {e.topics.map((t) => <a key={t.id} className="chip" href={href.topic(t.id)}>{t.name} <sup>{t.n}</sup></a>)}
            </div>
          </section>
          <p className="footnote">
            Timeline e enriquecimento externo (Wikidata, fontes com URL) ainda por implementar.
          </p>
        </aside>
      </div>
    </div>
  )
}
