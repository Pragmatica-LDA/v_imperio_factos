const rtf = new Intl.RelativeTimeFormat('pt-PT', { numeric: 'auto' })

export function ago(iso: string | null | undefined): string {
  if (!iso) return ''
  const s = (new Date(iso).getTime() - Date.now()) / 1000
  const abs = Math.abs(s)
  if (abs < 60) return 'agora'
  if (abs < 3600) return rtf.format(Math.round(s / 60), 'minute')
  if (abs < 86400) return rtf.format(Math.round(s / 3600), 'hour')
  if (abs < 86400 * 7) return rtf.format(Math.round(s / 86400), 'day')
  return dateShort(iso)
}

export const dateShort = (iso: string) =>
  new Date(iso).toLocaleDateString('pt-PT', { day: 'numeric', month: 'short' })

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('pt-PT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })

export const dateLong = (d = new Date()) =>
  d.toLocaleDateString('pt-PT', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })

export const num = (n: number) => n.toLocaleString('pt-PT')

export const pct = (a: number, b: number) => (b ? Math.round((100 * a) / b) : 0)

export const SITES: Record<string, { short: string; name: string }> = {
  jn: { short: 'JN', name: 'Jornal de Notícias' },
  publico: { short: 'PÚB', name: 'Público' },
  observador: { short: 'OBS', name: 'Observador' },
}

export const siteShort = (slug: string) => SITES[slug]?.short ?? slug.slice(0, 3).toUpperCase()

export const PIECE: Record<string, string> = {
  noticia: 'Notícia',
  opiniao: 'Opinião',
  analise: 'Análise',
  entrevista: 'Entrevista',
  reportagem: 'Reportagem',
  editorial: 'Editorial',
  outro: 'Outro',
  desconhecido: 'Sem análise',
}

export const ENTITY_TYPE: Record<string, string> = {
  pessoa: 'Pessoa',
  organizacao: 'Organização',
  partido: 'Partido',
  governo: 'Governo',
  instituicao: 'Instituição',
  empresa: 'Empresa',
  meio: 'Meio',
  local: 'Local',
  outro: 'Outro',
}

export const SOURCE_TYPE: Record<string, string> = {
  anonima: 'Anónima',
  oficial: 'Oficial',
  documento: 'Documento',
  agencia: 'Agência',
  redes_sociais: 'Redes sociais',
  especialista: 'Especialista',
  outro_meio: 'Outro meio',
  testemunha: 'Testemunha',
  outro: 'Outro',
}
