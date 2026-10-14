import { useApi } from '../api'
import { ArticleRow, DayBars, Empty, ErrorBox, Kicker, Loading, Meta, SiteTag, Spark, StackBar, ToneDot } from '../components/ui'
import { ago, ENTITY_TYPE, num, PIECE, pct } from '../format'
import { href } from '../router'
import type { Bucket, HotTopic, Overview, Story, TrendingEntity } from '../types'

const SITE_ORDER = ['jn', 'publico', 'observador']

export default function Home() {
  const { data, error, loading, reload } = useApi<Overview>('/api/front/overview/', 120_000)
  if (!data) return error ? <ErrorBox error={error} retry={reload} /> : <Loading label="A ler a actualidade" />
  const { totals: t, window_h: w } = data
  return (
    <div className="home">
      <section className="pulse" aria-label="Resumo">
        <Pulse n={t.articles_window} label={`notícias nas últimas ${w}h`} />
        <Pulse n={data.stories.filter((s) => s.n_articles > 1).length} label="histórias com várias notícias" />
        <Pulse n={data.entities.length ? data.entities[0].n_articles : 0}
          label={data.entities[0] ? `notícias com ${data.entities[0].name}` : 'entidade mais citada'} />
        <Pulse n={t.articles_total} label="notícias no arquivo" />
        <Pulse n={t.entities_total} label="entidades conhecidas" />
        <span className="pulse-updated">
          {loading ? 'a actualizar…' : `actualizado ${ago(data.generated_at)}`}
        </span>
      </section>

      <div className="grid-main">
        <section className="col-stories" aria-labelledby="h-agora">
          <Kicker n="01">
            <span id="h-agora">Agora</span> — as histórias das últimas {w} horas, por cobertura, temperatura e actualidade
          </Kicker>
          {data.stories.length === 0 ? (
            <Empty>Sem notícias nesta janela.</Empty>
          ) : (
            <>
              <LeadStory s={data.stories[0]} />
              <div className="stories-grid">
                {data.stories.slice(1).map((s, i) => (
                  <StoryCard key={s.lead.id} s={s} rank={i + 2} />
                ))}
              </div>
            </>
          )}
        </section>

        <aside className="col-rail">
          <Kicker n="02">Quem está nas notícias</Kicker>
          <p className="rail-note">Nº de notícias nas últimas {w}h · variação face às {w}h anteriores</p>
          <EntityBoard rows={data.entities} />
          <Kicker n="03">Onde</Kicker>
          <div className="places">
            {data.places.map((p) => (
              <a key={p.id} href={href.entity(p.id)} className="place"
                style={{ fontSize: `${0.8 + Math.min(p.n_articles / (data.places[0]?.n_articles || 1), 1) * 0.7}rem` }}>
                {p.name}
                <sup>{p.n_articles}</sup>
              </a>
            ))}
          </div>
        </aside>
      </div>

      <section className="band" aria-labelledby="h-temp">
        <Kicker n="04">
          <span id="h-temp">Temperatura dos temas</span> — notícias recentes × meios distintos, com decaimento
        </Kicker>
        <div className="thermo-list">
          {data.hot_topics.map((t, i) => (
            <ThermoRow key={t.id} t={t} max={data.hot_topics[0].temperature} rank={i + 1} />
          ))}
        </div>
      </section>

      <section className="band" aria-labelledby="h-meios">
        <Kicker n="05">
          <span id="h-meios">Últimas por meio</span>
        </Kicker>
        <div className="by-site">
          {SITE_ORDER.map((slug) => data.latest_by_site.find((b) => b.site === slug))
            .concat(data.latest_by_site.filter((b) => !SITE_ORDER.includes(b.site)))
            .filter(Boolean)
            .map((b) => (
              <div key={b!.site} className={`site-col site-col-${b!.site}`}>
                <h3 className="site-col-head">
                  <SiteTag site={b!.site} /> {b!.name}
                  <a className="more" href={href.archive({ site: b!.site })}>arquivo →</a>
                </h3>
                <ul className="article-list">
                  {b!.articles.map((a) => (
                    <ArticleRow key={a.id} a={a} showSite={false} />
                  ))}
                </ul>
              </div>
            ))}
        </div>
      </section>

      <Numbers data={data} />
    </div>
  )
}

function Pulse({ n, label }: { n: number; label: string }) {
  return (
    <div className="pulse-item">
      <span className="pulse-n">{num(n)}</span>
      <span className="pulse-label">{label}</span>
    </div>
  )
}

function Coverage({ s }: { s: Story }) {
  return (
    <div className="coverage" title={`${s.n_articles} notícias em ${s.sites.length} meios`}>
      {s.sites.map((x) => (
        <SiteTag key={x} site={x} />
      ))}
      {s.n_articles > 1 && <span className="coverage-n">{s.n_articles} notícias</span>}
    </div>
  )
}

function LeadStory({ s }: { s: Story }) {
  const a = s.lead
  return (
    <article className="lead-story">
      <div className="lead-top">
        <Coverage s={s} />
        {a.topics[0] && (
          <a className="chip chip-hot" href={href.topic(a.topics[0].id)}>
            {a.topics[0].name}
          </a>
        )}
      </div>
      <h2 className="lead-title">
        <a href={href.article(a.id)}>{a.title}</a>
      </h2>
      {a.summary && <p className="lead-summary">{a.summary}</p>}
      <Meta a={a} />
      {s.shared_entities.length > 0 && (
        <div className="chips">
          {s.shared_entities.map((e) => (
            <a key={e.id} className="chip chip-entity" href={href.entity(e.id)}>
              {e.name}
            </a>
          ))}
        </div>
      )}
      {s.others.length > 0 && (
        <div className="also">
          <span className="also-label">Também</span>
          <ul>
            {s.others.slice(0, 6).map((o) => (
              <li key={o.id}>
                <SiteTag site={o.site} />
                <a href={href.article(o.id)}>{o.title}</a>
                <ToneDot tone={o.tone} />
              </li>
            ))}
            {s.others.length > 6 && <li className="also-more">+ {s.others.length - 6} notícias</li>}
          </ul>
        </div>
      )}
    </article>
  )
}

function StoryCard({ s, rank }: { s: Story; rank: number }) {
  const a = s.lead
  return (
    <article className="story-card" style={{ animationDelay: `${rank * 40}ms` }}>
      <div className="story-rank">{String(rank).padStart(2, '0')}</div>
      <div>
        <Coverage s={s} />
        <h3 className="story-title">
          <a href={href.article(a.id)}>{a.title}</a>
        </h3>
        <Meta a={a} showSite={s.sites.length > 1 ? true : false} />
        {s.others.length > 0 && (
          <ul className="story-others">
            {s.others.slice(0, 3).map((o) => (
              <li key={o.id}>
                <SiteTag site={o.site} /> <a href={href.article(o.id)}>{o.title}</a>
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  )
}

function EntityBoard({ rows }: { rows: TrendingEntity[] }) {
  if (!rows.length) return <Empty>Sem entidades nesta janela.</Empty>
  const max = rows[0].n_articles || 1
  return (
    <ol className="entity-board">
      {rows.map((e, i) => {
        const s = e.sentiment
        return (
          <li key={e.id} className={i < 3 ? 'top' : ''}>
            <a href={href.entity(e.id)} className="eb-name">
              {e.name}
            </a>
            <span className="eb-type">{ENTITY_TYPE[e.type] ?? e.type}</span>
            <span className="eb-bar">
              <span style={{ width: `${(100 * e.n_articles) / max}%` }} />
            </span>
            <span className="eb-n">{e.n_articles}</span>
            <span className={`eb-delta ${e.delta > 0 ? 'up' : e.delta < 0 ? 'down' : ''}`}
              title={`${e.prev_articles} nas horas anteriores`}>
              {e.delta > 0 ? `▲${e.delta}` : e.delta < 0 ? `▼${-e.delta}` : '='}
            </span>
            <span className="eb-tone">
              <StackBar height={4} parts={[
                { key: 'positivo', value: s.positivo, label: 'Positivo' },
                { key: 'neutro', value: s.neutro, label: 'Neutro' },
                { key: 'negativo', value: s.negativo, label: 'Negativo' },
              ]} />
            </span>
          </li>
        )
      })}
    </ol>
  )
}

function ThermoRow({ t, max, rank }: { t: HotTopic; max: number; rank: number }) {
  const lead = t.articles[0]
  return (
    <div className={`thermo ${t.hot ? 'is-hot' : ''}`}>
      <span className="thermo-rank">{rank}</span>
      <div className="thermo-name">
        <a href={href.topic(t.id)}>{t.name}</a>
        {t.parent && <span className="thermo-parent">{t.parent.name}</span>}
      </div>
      <div className="thermo-gauge" title={`Temperatura ${t.temperature.toFixed(1)}`}>
        <span style={{ width: `${(100 * t.temperature) / (max || 1)}%` }} />
        <em>{t.temperature.toFixed(1)}°</em>
      </div>
      <Spark values={t.history.map((h) => h.value)} w={110} h={26} className="thermo-spark" />
      <div className="thermo-n">
        {t.n_articles_now} <small>/ {t.n_articles}</small>
        <span className="thermo-sites">
          {t.sites.map((s) => (
            <SiteTag key={s} site={s} />
          ))}
        </span>
      </div>
      <div className="thermo-lead">
        {lead ? (
          <a href={href.article(lead.id)}>
            <SiteTag site={lead.site} /> {lead.title}
          </a>
        ) : null}
      </div>
    </div>
  )
}

function toneParts(b: Bucket) {
  return [
    { key: 'positivo', value: b.tone.positivo ?? 0, label: 'Positivo' },
    { key: 'neutro', value: b.tone.neutro ?? 0, label: 'Neutro' },
    { key: 'negativo', value: b.tone.negativo ?? 0, label: 'Negativo' },
    { key: 'none', value: b.tone.sem_entidades ?? 0, label: 'Sem entidades' },
  ]
}

function aiParts(b: Bucket) {
  return [
    { key: 'ai', value: b.ai.com_ia ?? 0, label: 'Com IA' },
    { key: 'noai', value: b.ai.sem_ia ?? 0, label: 'Sem IA' },
    { key: 'none', value: b.ai.sem_dados ?? 0, label: 'Sem indicador' },
  ]
}

function Numbers({ data }: { data: Overview }) {
  const { total, by_site, daily, thresholds } = data.stats
  const sites = SITE_ORDER.filter((s) => by_site[s]).concat(Object.keys(by_site).filter((s) => !SITE_ORDER.includes(s)))
  const pieces = Object.entries(total.piece_type).sort((a, b) => b[1] - a[1])
  return (
    <section className="band numbers" aria-labelledby="h-num">
      <Kicker n="06">
        <span id="h-num">Os números do arquivo</span> — {num(total.analysed)} notícias analisadas de {num(total.n)}
      </Kicker>
      <div className="numbers-grid">
        <div className="num-block">
          <h4>Tom das notícias</h4>
          <div className="big-split">
            <BigPct label="positivas" value={pct(total.tone.positivo ?? 0, total.analysed)} cls="positivo" />
            <BigPct label="neutras" value={pct(total.tone.neutro ?? 0, total.analysed)} cls="neutro" />
            <BigPct label="negativas" value={pct(total.tone.negativo ?? 0, total.analysed)} cls="negativo" />
          </div>
          <table className="split-table">
            <tbody>
              {sites.map((s) => (
                <tr key={s}>
                  <th><SiteTag site={s} /></th>
                  <td><StackBar parts={toneParts(by_site[s])} /></td>
                  <td className="mono">{by_site[s].analysed}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="footnote">
            Derivado do sentimento por entidade (média; limiar ±{thresholds.tone}). A análise não dá um tom global.
          </p>
        </div>

        <div className="num-block">
          <h4>Escrita por IA</h4>
          <div className="big-split">
            <BigPct label="com indício de IA" value={pct(total.ai.com_ia ?? 0, total.analysed)} cls="ai" />
            <BigPct label="sem indício" value={pct(total.ai.sem_ia ?? 0, total.analysed)} cls="noai" />
          </div>
          <table className="split-table">
            <tbody>
              {sites.map((s) => (
                <tr key={s}>
                  <th><SiteTag site={s} /></th>
                  <td><StackBar parts={aiParts(by_site[s])} /></td>
                  <td className="mono">{by_site[s].ai.com_ia ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="footnote">
            Indicador do modelo de análise (≥ {thresholds.ai}%), não um veredicto. Detectores dedicados por implementar.
          </p>
        </div>

        <div className="num-block">
          <h4>Tipo de peça</h4>
          <ul className="piece-list">
            {pieces.map(([k, v]) => (
              <li key={k}>
                <span>{PIECE[k] ?? k}</span>
                <span className="piece-bar"><span style={{ width: `${pct(v, pieces[0][1])}%` }} /></span>
                <span className="mono">{v}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="num-block">
          <h4>Notícias por dia</h4>
          <DayBars days={daily.map((d) => ({ date: d.date, n: d.total, by_site: d.by_site }))} stacked={sites} h={110} />
          <div className="legend">
            {sites.map((s) => (
              <span key={s}><i className={`site-bg-${s}`} /> <SiteTag site={s} /></span>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

function BigPct({ label, value, cls }: { label: string; value: number; cls: string }) {
  return (
    <div className={`big-pct big-${cls}`}>
      <span className="big-n">{value}<small>%</small></span>
      <span className="big-label">{label}</span>
    </div>
  )
}
