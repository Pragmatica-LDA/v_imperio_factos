export type Tone = 'positivo' | 'neutro' | 'negativo'

export type TopicRef = { id: number; name: string; weight?: number }
export type EntityRef = { id: number; name: string; type?: string; sentiment?: string }

export type Card = {
  id: number
  title: string
  site: string
  site_name: string
  url: string
  published_at: string
  section: string
  piece_type: string
  summary: string
  analysed: boolean
  tone: Tone | null
  tone_avg: number | null
  ai_score: number | null
  ai: boolean | null
  topics: TopicRef[]
  version_count: number
  cluster: { id: number; size: number; is_original: boolean } | null
  entities?: EntityRef[]
}

export type StoryOther = Pick<Card, 'id' | 'title' | 'site' | 'site_name' | 'published_at' | 'url' | 'tone' | 'ai'>

export type Story = {
  score: number
  lead: Card
  others: StoryOther[]
  n_articles: number
  sites: string[]
  shared_entities: EntityRef[]
  on_homepage: boolean
}

export type HotTopic = {
  id: number
  name: string
  kind: string
  parent: { id: number; name: string } | null
  temperature: number
  hot: boolean
  n_articles: number
  n_articles_now: number
  sites: string[]
  history: { at: string; value: number }[]
  articles: Card[]
}

export type TrendingEntity = {
  id: number
  name: string
  type: string
  n_articles: number
  n_sites: number
  sites: string[]
  prev_articles: number
  delta: number
  sentiment: Record<Tone, number>
}

export type Bucket = {
  n: number
  analysed: number
  tone: Partial<Record<Tone | 'sem_entidades', number>>
  ai: Partial<Record<'com_ia' | 'sem_ia' | 'sem_dados', number>>
  piece_type: Record<string, number>
}

export type Overview = {
  generated_at: string
  window_h: number
  totals: {
    articles_window: number
    sites_window: number
    articles_total: number
    analysed_total: number
    entities_total: number
    topics_active: number
    versions_window: number
  }
  stories: Story[]
  hot_topics: HotTopic[]
  entities: TrendingEntity[]
  places: TrendingEntity[]
  latest_by_site: { site: string; name: string; articles: Card[] }[]
  stats: {
    total: Bucket
    by_site: Record<string, Bucket>
    daily: { date: string; total: number; by_site: Record<string, number> }[]
    thresholds: { tone: number; ai: number }
  }
}

export type Related = Card & { similarity: number; shared_entities: EntityRef[] }

export type ArticleDetail = Omit<Card, 'entities'> & {
  lead: string
  authors: (string | { name?: string })[]
  text: string
  word_count: number
  analysis: {
    id: number
    model: string
    prompt_version: string
    version_number: number
    piece_type_reasoning: string
    ai_indicator: { score?: number; signals?: string[] } | null
  } | null
  entities: {
    id: number
    name: string
    type: string
    name_in_text: string
    roles: string[]
    position: string
    sentiment: string
    sentiment_score: number | null
    evidence: string
    is_location: boolean
  }[]
  topics_full: { id: number; name: string; weight: number; parent: string | null; edition: string | null; temperature: number }[]
  sources: { type: string; name: string; partial_attribute: string; excerpt: string; entity_id: number | null }[]
  versions: { number: number; created_at: string; change_ratio: number; word_count: number }[]
  duplicates: (Card & { similarity: number; is_original: boolean })[]
  related: { same_topic: Related[]; other_topics: Related[] }
}

export type Counted = { id: number; name: string; type?: string; n: number }

export type EntityDetail = {
  id: number
  name: string
  type: string
  status: string
  is_public: boolean | null
  external_id: string
  description: string
  merged_into: number | null
  aliases: string[]
  n_articles: number
  sites: Record<string, number>
  sentiment: Record<Tone, number>
  roles: Record<string, number>
  positions: string[]
  series: { date: string; n: number }[]
  co_entities: Counted[]
  topics: Counted[]
  articles: (Card & { entity_sentiment: string | null })[]
}

export type TopicDetail = {
  id: number
  name: string
  kind: string
  status: string
  description: string
  recurrence: string
  temperature: number
  hot: boolean
  path: { id: number; name: string }[]
  children: { id: number; name: string; temperature: number }[]
  editions: { id: number; label: string; temperature: number }[]
  n_articles: number
  sites: Record<string, number>
  history: { at: string; value: number; articles: number; sites: number }[]
  series: { date: string; n: number }[]
  entities: Counted[]
  articles: Card[]
}

export type Page<T> = { count: number; next: string | null; previous: string | null; results: T[] }

export type SearchResult = {
  entities: Counted[]
  topics: { id: number; name: string; temperature: number }[]
  articles: Card[]
}
