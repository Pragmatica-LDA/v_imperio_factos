import { useEffect, useRef, useState } from 'react'
import { auth, login, useApi } from './api'
import { SiteTag } from './components/ui'
import { dateLong } from './format'
import Archive from './pages/Archive'
import ArticlePage from './pages/ArticlePage'
import EntityPage from './pages/EntityPage'
import Home from './pages/Home'
import TopicPage from './pages/TopicPage'
import { href, useRoute } from './router'
import type { SearchResult } from './types'

export default function App() {
  const [logged, setLogged] = useState(() => Boolean(auth.get()))
  useEffect(() => {
    const out = () => setLogged(false)
    window.addEventListener('factos:logout', out)
    return () => window.removeEventListener('factos:logout', out)
  }, [])
  if (!logged) return <Login onDone={() => setLogged(true)} />
  return <Shell onLogout={() => { auth.clear(); setLogged(false) }} />
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const route = useRoute()
  return (
    <div className="paper">
      <header className="masthead">
        <div className="mast-top">
          <span className="mast-date">{dateLong()}</span>
          <nav className="mast-nav">
            <a href={href.home()} className={route.name === 'home' ? 'on' : ''}>Agora</a>
            <a href={href.archive()} className={route.name === 'archive' ? 'on' : ''}>Arquivo</a>
            <button type="button" className="link-btn" onClick={onLogout}>Sair</button>
          </nav>
        </div>
        <div className="mast-main">
          <a href={href.home()} className="wordmark" aria-label="Factos — início">
            Factos<span className="wordmark-dot">.</span>
          </a>
          <p className="mast-tag">
            O que está a ser notícia, lido em <SiteTag site="jn" /> <SiteTag site="publico" /> <SiteTag site="observador" />
          </p>
          <SearchBox />
        </div>
      </header>
      <main className="content" key={route.name + ('id' in route ? route.id : '')}>
        {route.name === 'home' && <Home />}
        {route.name === 'article' && <ArticlePage id={route.id} />}
        {route.name === 'entity' && <EntityPage id={route.id} />}
        {route.name === 'topic' && <TopicPage id={route.id} />}
        {route.name === 'archive' && <Archive params={route.params} />}
      </main>
      <footer className="colophon">
        Factos · arquivo interno de notícias portuguesas · os indicadores (tom, IA, temperatura) são derivados por modelos e configuráveis
      </footer>
    </div>
  )
}

function SearchBox() {
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 250)
    return () => clearTimeout(id)
  }, [q])
  useEffect(() => {
    const close = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false) }
    const hash = () => { setOpen(false); setQ('') }
    document.addEventListener('mousedown', close)
    window.addEventListener('hashchange', hash)
    return () => { document.removeEventListener('mousedown', close); window.removeEventListener('hashchange', hash) }
  }, [])
  const { data } = useApi<SearchResult>(debounced.length >= 2 ? `/api/front/search/?q=${encodeURIComponent(debounced)}` : null)
  const has = data && debounced.length >= 2 && (data.entities.length || data.topics.length || data.articles.length)
  return (
    <div className="search" ref={box}>
      <form onSubmit={(e) => { e.preventDefault(); window.location.hash = href.archive({ q }) }}>
        <input type="search" placeholder="Pessoa, partido, tema, título…" value={q} aria-label="Pesquisar"
          onChange={(e) => { setQ(e.target.value); setOpen(true) }} onFocus={() => setOpen(true)} />
      </form>
      {open && has ? (
        <div className="search-pop">
          {data.entities.length > 0 && <h5>Entidades</h5>}
          {data.entities.map((e) => <a key={`e${e.id}`} href={href.entity(e.id)}>{e.name} <small>{e.n} menções</small></a>)}
          {data.topics.length > 0 && <h5>Temas</h5>}
          {data.topics.map((t) => <a key={`t${t.id}`} href={href.topic(t.id)}>{t.name} <small>{t.temperature.toFixed(1)}°</small></a>)}
          {data.articles.length > 0 && <h5>Notícias</h5>}
          {data.articles.map((a) => <a key={`a${a.id}`} href={href.article(a.id)}><SiteTag site={a.site} /> {a.title}</a>)}
          <a className="search-all" href={href.archive({ q })}>Procurar "{q}" no arquivo →</a>
        </div>
      ) : null}
    </div>
  )
}

function Login({ onDone }: { onDone: () => void }) {
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <div className="login-wrap">
      <form className="login" onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setErr(null)
        try { await login(u, p); onDone() } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
      }}>
        <div className="wordmark">Factos<span className="wordmark-dot">.</span></div>
        <p className="muted">Acesso interno</p>
        <label>Utilizador<input autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required /></label>
        <label>Password<input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required /></label>
        {err && <p className="login-err" role="alert">{err}</p>}
        <button type="submit" disabled={busy}>{busy ? 'A entrar…' : 'Entrar'}</button>
      </form>
    </div>
  )
}
