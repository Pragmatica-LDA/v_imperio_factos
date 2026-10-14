import type { ReactNode } from 'react'
import { ago, PIECE, siteShort, SITES } from '../format'
import { href } from '../router'
import type { Card, Tone } from '../types'

export function SiteTag({ site }: { site: string }) {
  return (
    <span className={`site-tag site-${site}`} title={SITES[site]?.name ?? site}>
      {siteShort(site)}
    </span>
  )
}

const TONE_LABEL: Record<string, string> = { positivo: 'Tom positivo', negativo: 'Tom negativo', neutro: 'Tom neutro' }

export function ToneDot({ tone }: { tone: Tone | string | null | undefined }) {
  if (!tone) return null
  return <span className={`tone-dot tone-${tone}`} title={TONE_LABEL[tone] ?? tone} aria-label={TONE_LABEL[tone]} />
}

export function AiTag({ ai, score }: { ai: boolean | null; score?: number | null }) {
  if (ai === null || ai === undefined) return null
  return ai ? (
    <span className="ai-tag" title={`Indicador de escrita por IA: ${score ?? '?'}%`}>
      IA {score}%
    </span>
  ) : null
}

export function Kicker({ children, n }: { children: ReactNode; n?: string }) {
  return (
    <div className="kicker">
      {n && <span className="kicker-n">{n}</span>}
      <span>{children}</span>
    </div>
  )
}

export function Meta({ a, showSite = true }: { a: Card; showSite?: boolean }) {
  return (
    <div className="meta">
      {showSite && <SiteTag site={a.site} />}
      <time dateTime={a.published_at} title={new Date(a.published_at).toLocaleString('pt-PT')}>
        {ago(a.published_at)}
      </time>
      {a.piece_type && a.piece_type !== 'noticia' && <span className="piece">{PIECE[a.piece_type] ?? a.piece_type}</span>}
      <ToneDot tone={a.tone} />
      <AiTag ai={a.ai} score={a.ai_score} />
      {a.version_count > 1 && <span className="versions" title="Versões registadas">v{a.version_count}</span>}
      {a.cluster && a.cluster.size > 1 && (
        <span className="dup" title="Notícias com o mesmo texto de origem">
          ×{a.cluster.size}
        </span>
      )}
    </div>
  )
}

export function ArticleRow({ a, showSite = true, extra }: { a: Card; showSite?: boolean; extra?: ReactNode }) {
  return (
    <li className="article-row">
      <Meta a={a} showSite={showSite} />
      <a className="article-title" href={href.article(a.id)}>
        {a.title}
      </a>
      {a.topics.length > 0 && (
        <div className="chips">
          {a.topics.slice(0, 2).map((t) => (
            <a key={t.id} className="chip" href={href.topic(t.id)}>
              {t.name}
            </a>
          ))}
        </div>
      )}
      {extra}
    </li>
  )
}

export function Spark({ values, w = 120, h = 28, className = '' }: { values: number[]; w?: number; h?: number; className?: string }) {
  if (values.length < 2) return <svg width={w} height={h} className={`spark ${className}`} aria-hidden />
  const max = Math.max(...values) || 1
  const min = Math.min(0, ...values)
  const x = (i: number) => (i / (values.length - 1)) * w
  const y = (v: number) => h - 2 - ((v - min) / (max - min || 1)) * (h - 4)
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  return (
    <svg width={w} height={h} className={`spark ${className}`} aria-hidden viewBox={`0 0 ${w} ${h}`}>
      <path d={`${d}L${w},${h}L0,${h}Z`} className="spark-area" />
      <path d={d} className="spark-line" />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r={2.5} className="spark-dot" />
    </svg>
  )
}

/** Barra proporcional segmentada (ex.: tom positivo/neutro/negativo). */
export function StackBar({ parts, height = 10 }: { parts: { key: string; value: number; label: string }[]; height?: number }) {
  const total = parts.reduce((s, p) => s + p.value, 0)
  return (
    <div className="stackbar" style={{ height }} role="img"
      aria-label={parts.map((p) => `${p.label}: ${p.value}`).join(', ')}>
      {parts.map((p) =>
        p.value > 0 ? (
          <span key={p.key} className={`seg seg-${p.key}`} style={{ flexGrow: p.value }}
            title={`${p.label}: ${p.value} (${total ? Math.round((100 * p.value) / total) : 0}%)`} />
        ) : null,
      )}
    </div>
  )
}

/** Série diária (barras), opcionalmente empilhada por meio. */
export function DayBars({ days, h = 90, stacked }: {
  days: { date: string; n: number; by_site?: Record<string, number> }[]
  h?: number
  stacked?: string[]
}) {
  const max = Math.max(1, ...days.map((d) => d.n))
  return (
    <div className="daybars" style={{ height: h }}>
      {days.map((d) => {
        const label = new Date(d.date).toLocaleDateString('pt-PT', { day: 'numeric', month: 'short' })
        return (
          <div key={d.date} className="daybar" title={`${label}: ${d.n}`}>
            <div className="daybar-col" style={{ height: `${(100 * d.n) / max}%` }}>
              {stacked
                ? stacked.map((s) =>
                    d.by_site?.[s] ? (
                      <span key={s} className={`seg site-bg-${s}`} style={{ flexGrow: d.by_site[s] }} />
                    ) : null,
                  )
                : <span className="seg seg-ink" style={{ flexGrow: 1 }} />}
            </div>
            <span className="daybar-label">{new Date(d.date).getDate()}</span>
          </div>
        )
      })}
    </div>
  )
}

export function Loading({ label = 'A carregar' }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <span className="loading-bar" />
      {label}…
    </div>
  )
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <strong>Não foi possível carregar.</strong> {error}
      {retry && (
        <button type="button" onClick={retry}>
          Tentar de novo
        </button>
      )}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>
}
