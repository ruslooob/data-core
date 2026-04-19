import type {
  AggregateStudyRequest,
  AggregateStudyResult,
  AnomalyRequest,
  AnomalyResult,
  AnomalyScanAllRequest,
  Candle,
  DividendEvent,
  EventStudyRequest,
  EventStudyResult,
  SeriesName,
  SeriesPoint,
} from './types'

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

export function findAnomalies(
  request: AnomalyRequest,
): Promise<AnomalyResult[]> {
  return fetchJson<AnomalyResult[]>('/api/anomalies', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  })
}

export async function scanAllAnomalies(
  request: AnomalyScanAllRequest,
  onResult: (result: AnomalyResult) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch('/api/anomalies/scan-all', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
    signal,
  })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`)
  }
  const reader = response.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const payload = line.slice(6).trim()
      if (payload === '[DONE]') return
      try {
        onResult(JSON.parse(payload) as AnomalyResult)
      } catch {
        // skip malformed
      }
    }
  }
}
