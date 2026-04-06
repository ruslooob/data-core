export interface Candle {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface SeriesPoint {
  date: string
  value: number
}

export type SeriesName = 'IMOEX' | 'RUONIA'

export interface DividendEvent {
  id: string
  ticker: string
  event_date: string
  dividend: number
  year: number
}

export type ExpectedReturnModel = 'mean_adjusted' | 'market_model' | 'capm'

export interface EventStudyRequest {
  ticker: string
  event_date: string
  model: ExpectedReturnModel
  event_window: [number, number]
  estimation_window: number
}

export interface EventStudyResult {
  event_date: string
  ar: number[]
  car: number
  n_days: number
  estimation_std: number
}
