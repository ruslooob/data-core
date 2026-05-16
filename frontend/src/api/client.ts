import type {
  AggregateStudyRequest,
  AggregateStudyResult,
  BacktestResultDetail,
  BacktestResultMeta,
  BacktestRunProgress,
  BacktestRunRequest,
  BacktestRunStarted,
  Candle,
  DividendEvent,
  Environment,
  EnvironmentCreate,
  EventStudyRequest,
  EventStudyResult,
  EventTagsBulkResponse,
  PrecedentFuzzySearchResponse,
  PrecedentQueryRecord,
  PrecedentQuerySaveRequest,
  PrecedentSearchRequest,
  PrecedentSearchResult,
  Research,
  ResearchCreate,
  ResearchPatch,
  Rule,
  RuleCreate,
  SeriesName,
  SeriesPoint,
  Strategy,
  StrategyCreate,
} from './types'

export class PrecedentApiError extends Error {
  line: number | null
  column: number | null
  constructor(message: string, line: number | null, column: number | null) {
    super(message)
    this.name = 'PrecedentApiError'
    this.line = line
    this.column = column
  }
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body.detail) detail = body.detail
    } catch { /* не JSON */ }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export function getTickers(): Promise<string[]> {
  return fetchJson<string[]>('/api/tickers')
}

export function getPrices(
  ticker: string,
  startDate?: string,
  endDate?: string,
): Promise<Candle[]> {
  const params = new URLSearchParams()
  if (startDate) params.set('startDate', startDate)
  if (endDate) params.set('endDate', endDate)
  const query = params.toString()
  const url = `/api/prices/${ticker}${query ? `?${query}` : ''}`
  return fetchJson<Candle[]>(url)
}

export function getEvents(
  params: { ticker?: string; startDate?: string; endDate?: string } = {},
): Promise<DividendEvent[]> {
  const search = new URLSearchParams()
  if (params.ticker) search.set('ticker', params.ticker)
  if (params.startDate) search.set('startDate', params.startDate)
  if (params.endDate) search.set('endDate', params.endDate)
  const query = search.toString()
  const url = `/api/events${query ? `?${query}` : ''}`
  return fetchJson<DividendEvent[]>(url)
}

export function getSeries(name: SeriesName): Promise<SeriesPoint[]> {
  return fetchJson<SeriesPoint[]>(`/api/series/${name}`)
}

export function runEventStudy(
  request: EventStudyRequest,
): Promise<EventStudyResult> {
  return fetchJson<EventStudyResult>('/api/event-study', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function runAggregateStudy(
  request: AggregateStudyRequest,
): Promise<AggregateStudyResult> {
  return fetchJson<AggregateStudyResult>('/api/event-study/aggregate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function searchPrecedents(
  request: PrecedentSearchRequest,
  signal?: AbortSignal,
): Promise<PrecedentSearchResult> {
  let response: Response
  try {
    response = await fetch('/api/precedents/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new PrecedentApiError('Сервер недоступен', null, null)
  }
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let line: number | null = null
    let column: number | null = null
    try {
      const body = await response.json()
      if (body.detail && typeof body.detail === 'object') {
        message = body.detail.message ?? message
        line = body.detail.line ?? null
        column = body.detail.column ?? null
      } else if (typeof body.detail === 'string') {
        message = body.detail
      }
    } catch { /* not JSON */ }
    throw new PrecedentApiError(message, line, column)
  }
  return response.json() as Promise<PrecedentSearchResult>
}

export function searchPrecedentsFuzzy(
  query: string,
  signal?: AbortSignal,
): Promise<PrecedentFuzzySearchResponse> {
  return fetchJson<PrecedentFuzzySearchResponse>('/api/precedents/search/fuzzy', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
    signal,
  })
}

export function getEventTagsBulk(eventIds: string[]): Promise<EventTagsBulkResponse> {
  return fetchJson<EventTagsBulkResponse>('/api/precedents/tags-bulk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ eventIds }),
  })
}

export function listPrecedentQueries(): Promise<PrecedentQueryRecord[]> {
  return fetchJson<PrecedentQueryRecord[]>('/api/precedents/queries')
}

export function savePrecedentQuery(
  request: PrecedentQuerySaveRequest,
): Promise<PrecedentQueryRecord> {
  return fetchJson<PrecedentQueryRecord>('/api/precedents/queries', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

// ── Исследования (Research) ─────────────────────────────────────────────────

export function listResearch(): Promise<Research[]> {
  return fetchJson<Research[]>('/api/research')
}

export function getResearch(id: string): Promise<Research> {
  return fetchJson<Research>(`/api/research/${id}`)
}

export function createResearch(request: ResearchCreate): Promise<Research> {
  return fetchJson<Research>('/api/research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function updateResearch(id: string, patch: ResearchPatch): Promise<Research> {
  return fetchJson<Research>(`/api/research/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  })
}

export function deleteResearch(id: string): Promise<void> {
  return deleteJson(`/api/research/${id}`)
}

// ── Бэктест: стратегии, правила, окружения ──────────────────────────────────

async function deleteJson(url: string): Promise<void> {
  const response = await fetch(url, { method: 'DELETE' })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body.detail) detail = body.detail
    } catch { /* not JSON */ }
    throw new Error(detail)
  }
}

export function listStrategies(researchId: string, includeCommon = false): Promise<Strategy[]> {
  const params = new URLSearchParams({ researchId })
  if (includeCommon) params.set('includeCommon', 'true')
  return fetchJson<Strategy[]>(`/api/strategies?${params.toString()}`)
}

export function createStrategy(request: StrategyCreate): Promise<Strategy> {
  return fetchJson<Strategy>('/api/strategies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function renameStrategy(id: string, name: string): Promise<Strategy> {
  return fetchJson<Strategy>(`/api/strategies/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export function deleteStrategy(id: string): Promise<void> {
  return deleteJson(`/api/strategies/${id}`)
}

export function updateStrategyResearch(id: string, researchId: string | null): Promise<Strategy> {
  return fetchJson<Strategy>(`/api/strategies/${id}/research`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ researchId }),
  })
}

export function listRules(researchId: string, includeCommon = false): Promise<Rule[]> {
  const params = new URLSearchParams({ researchId })
  if (includeCommon) params.set('includeCommon', 'true')
  return fetchJson<Rule[]>(`/api/rules?${params.toString()}`)
}

export function createRule(request: RuleCreate): Promise<Rule> {
  return fetchJson<Rule>('/api/rules', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function renameRule(id: string, name: string): Promise<Rule> {
  return fetchJson<Rule>(`/api/rules/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export function deleteRule(id: string): Promise<void> {
  return deleteJson(`/api/rules/${id}`)
}

export function updateRuleResearch(id: string, researchId: string | null): Promise<Rule> {
  return fetchJson<Rule>(`/api/rules/${id}/research`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ researchId }),
  })
}

export function listEnvironments(researchId: string, includeCommon = false): Promise<Environment[]> {
  const params = new URLSearchParams({ researchId })
  if (includeCommon) params.set('includeCommon', 'true')
  return fetchJson<Environment[]>(`/api/environments?${params.toString()}`)
}

export function createEnvironment(request: EnvironmentCreate): Promise<Environment> {
  return fetchJson<Environment>('/api/environments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function renameEnvironment(id: string, name: string): Promise<Environment> {
  return fetchJson<Environment>(`/api/environments/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
}

export function deleteEnvironment(id: string): Promise<void> {
  return deleteJson(`/api/environments/${id}`)
}

export function updateEnvironmentResearch(id: string, researchId: string | null): Promise<Environment> {
  return fetchJson<Environment>(`/api/environments/${id}/research`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ researchId }),
  })
}

export function updateStrategyDescription(id: string, description: string): Promise<Strategy> {
  return fetchJson<Strategy>(`/api/strategies/${id}/description`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  })
}

export function updateRuleDescription(id: string, description: string): Promise<Rule> {
  return fetchJson<Rule>(`/api/rules/${id}/description`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  })
}

export function updateEnvironmentDescription(id: string, description: string): Promise<Environment> {
  return fetchJson<Environment>(`/api/environments/${id}/description`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  })
}

export function startBacktestRun(request: BacktestRunRequest): Promise<BacktestRunStarted> {
  return fetchJson<BacktestRunStarted>('/api/backtest/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export function getBacktestRunProgress(runId: string): Promise<BacktestRunProgress> {
  return fetchJson<BacktestRunProgress>(`/api/backtest/runs/${runId}/progress`)
}

export async function cancelBacktestRun(runId: string): Promise<void> {
  const response = await fetch(`/api/backtest/runs/${runId}/cancel`, { method: 'POST' })
  if (!response.ok && response.status !== 404) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
}

export interface BacktestLogChunk {
  content: string
  next_byte: number
}

export function getBacktestRunLog(runId: string, afterByte: number): Promise<BacktestLogChunk> {
  return fetchJson<BacktestLogChunk>(
    `/api/backtest/runs/${runId}/log?after_byte=${afterByte}`,
  )
}

export function listBacktestResults(researchId: string): Promise<BacktestResultMeta[]> {
  const params = new URLSearchParams({ researchId })
  return fetchJson<BacktestResultMeta[]>(`/api/backtest/results?${params.toString()}`)
}

export function getBacktestResult(id: string): Promise<BacktestResultDetail> {
  return fetchJson<BacktestResultDetail>(`/api/backtest/results/${id}`)
}

export function deleteBacktestResult(id: string): Promise<void> {
  return deleteJson(`/api/backtest/results/${id}`)
}
