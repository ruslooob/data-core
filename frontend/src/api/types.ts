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
  eventDate: string
  dividend: number
  year: number
}

export type ExpectedReturnModel = 'mean_adjusted' | 'market_model' | 'capm'

export interface EventStudyRequest {
  ticker: string
  eventDate: string
  model: ExpectedReturnModel
  eventWindow: [number, number]
  estimationWindow: number
}

export interface EventStudyResult {
  eventDate: string
  ar: number[]
  car: number
  nDays: number
  estimationStd: number
}
