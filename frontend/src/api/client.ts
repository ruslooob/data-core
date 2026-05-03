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
  PrecedentQueryRecord,
  PrecedentQuerySaveRequest,
  PrecedentSearchRequest,
  PrecedentSearchResult,
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

export function listStrategies(): Promise<Strategy[]> {
  return fetchJson<Strategy[]>('/api/strategies')
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

export function listRules(): Promise<Rule[]> {
  return fetchJson<Rule[]>('/api/rules')
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

export function listEnvironments(): Promise<Environment[]> {
  return fetchJson<Environment[]>('/api/environments')
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

export function listBacktestResults(): Promise<BacktestResultMeta[]> {
  return fetchJson<BacktestResultMeta[]>('/api/backtest/results')
}

export function getBacktestResult(id: string): Promise<BacktestResultDetail> {
  return fetchJson<BacktestResultDetail>(`/api/backtest/results/${id}`)
}

export function deleteBacktestResult(id: string): Promise<void> {
  return deleteJson(`/api/backtest/results/${id}`)
}
