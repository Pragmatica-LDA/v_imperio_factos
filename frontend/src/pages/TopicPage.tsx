import { useApi } from '../api'
import { ArticleRow, DayBars, Empty, ErrorBox, Kicker, Loading, SiteTag, Spark } from '../components/ui'
import { num } from '../format'
import { href } from '../router'
import type { TopicDetail } from '../types'

export default function TopicPage({ id }: { id: number }) {
  const { data: t, error, reload } = useApi<TopicDetail>(`/api/front/topics/${id}/`)
  if (!t || t.id !== id) return error ? <ErrorBox error={error} retry={reload} /> : <Loading />
  return (
    <div className="detail">
      <header className="detail-head">
        <div className="detail-crumbs">
          {t.path.map((p) => <span key={p.id}><a href={href.topic(p.id)}>{p.name}</a> › </span>)}
          {t.kind !== 'tema' && <span className="badge">{t.kind}</span>}
          {t.status === 'por_rever' && <span className="badge">por rever</span>}
        </div>
        <h1 className="detail-title">{t.name}</h1>
        {t.description && <p className="detail-lead">{t.description}</p>}
      </header>

      <div className="stat-row">
        <div className={`stat ${t.hot ? 'stat-hot' : ''}`}>
          <span className="stat-n">{t.temperature.toFixed(1)}°</span><span>{t.hot ? 'tema quente' : 'temperatura'}</span>
        </div>
        <div className="stat stat-wide">
          <span>Temperatura ao longo do tempo</span>
          <Spark values={t.history.map((h) => h.value)} w={260} h={48} className="spark-hot" />
        </div>
        <div className="stat"><span className="stat-n">{num(t.n_articles)}</span><span>notícias</span></div>
        <div className="stat">
          <span>Por meio</span>
          <span className="site-counts">
            {Object.entries(t.sites).map(([k, v]) => <span key={k}><SiteTag site={k} /> {v}</span>)}
          </span>
        </div>
        <div className="stat stat-wide"><span>Notícias por dia</span><DayBars days={t.series} h={50} /></div>
      </div>

      <div className="detail-grid">
        <div className="detail-main">
          <Kicker>Notícias</Kicker>
          {t.articles.length === 0 ? <Empty>Sem notícias.</Empty> : (
            <ul className="article-list">{t.articles.map((a) => <ArticleRow key={a.id} a={a} />)}</ul>
          )}
          <p><a href={href.archive({ topic: t.id, label: t.name })}>Ver tudo no arquivo →</a></p>
        </div>
        <aside className="detail-side">
          <section>
            <Kicker>Quem aparece</Kicker>
            <ul className="kv">
              {t.entities.map((e) => <li key={e.id}><a href={href.entity(e.id)}>{e.name}</a><span className="mono">{e.n}</span></li>)}
            </ul>
          </section>
          {t.children.length > 0 && (
            <section>
              <Kicker>Subtemas</Kicker>
              <ul className="kv">
                {t.children.map((c) => <li key={c.id}><a href={href.topic(c.id)}>{c.name}</a><span className="mono">{c.temperature.toFixed(1)}°</span></li>)}
              </ul>
            </section>
          )}
          {t.editions.length > 0 && (
            <section>
              <Kicker>Edições</Kicker>
              <ul className="kv">{t.editions.map((e) => <li key={e.id}><span>{e.label}</span><span className="mono">{e.temperature.toFixed(1)}°</span></li>)}</ul>
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}
