import type {
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
    throw new Error(`${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export function getTickers(): Promise<string[]> {
  return fetchJson<string[]>('/api/tickers')
}

export function getPrices(
  ticker: string,
  start?: string,
  end?: string,
): Promise<Candle[]> {
  const params = new URLSearchParams()
  if (start) params.set('start', start)
  if (end) params.set('end', end)
  const query = params.toString()
  const url = `/api/prices/${ticker}${query ? `?${query}` : ''}`
  return fetchJson<Candle[]>(url)
}

export function getEvents(
  params: { ticker?: string; start?: string; end?: string } = {},
): Promise<DividendEvent[]> {
  const search = new URLSearchParams()
  if (params.ticker) search.set('ticker', params.ticker)
  if (params.start) search.set('start', params.start)
  if (params.end) search.set('end', params.end)
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
