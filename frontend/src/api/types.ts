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

// ── Precedent Query Language (PQL) ──────────────────────────────────────────

export interface PrecedentSearchRequest {
  source: string
}

export interface PrecedentColumn {
  name: string
  type: string
}

export interface PrecedentSearchStats {
  truncated: boolean
  durationMs: number
}

export type PrecedentValue = string | number | boolean | null

export interface PrecedentSearchResult {
  columns: PrecedentColumn[]
  rows: PrecedentValue[][]
  stats: PrecedentSearchStats
}

export interface PrecedentApiErrorDetail {
  message: string
  line: number | null
  column: number | null
}

export interface PrecedentQueryRecord {
  id: string
  name: string
  source: string
  createdAt: string
}

export interface PrecedentQuerySaveRequest {
  name: string
  source: string
}

// ── Бэктест: стратегии, правила, окружения ──────────────────────────────────

export type ActionType = 'buy' | 'sell'

export interface Rule {
  id: string
  name: string
  triggerSql: string
  actionType: ActionType
  actionQuantitySql: string
  priority: number
  createdAt: string
}

export interface RuleCreate {
  name: string
  triggerSql: string
  actionType: ActionType
  actionQuantitySql: string
  priority: number
}

export interface Strategy {
  id: string
  name: string
  ruleIds: string[]
  createdAt: string
}

export interface StrategyCreate {
  name: string
  ruleIds: string[]
}

export interface Environment {
  id: string
  name: string
  dateStart: string
  dateEnd: string
  startingCapital: number
  createdAt: string
}

export interface EnvironmentCreate {
  name: string
  dateStart: string
  dateEnd: string
  startingCapital: number
}

export interface EventStudyRequest {
  ticker: string
  eventDate: string
  model: ExpectedReturnModel
  eventWindow: [number, number]
  estimationWindow: number
  outlierThreshold?: number | null
}

export interface EventStudyResult {
  eventDate: string
  ar: number[]
  car: number
  nDays: number
  estimationStd: number
  outliersRemoved: number
}

// ── Агрегированный event study ──────────────────────────────────────────────

export interface AggregateStudyRequest {
  ticker: string
  model: ExpectedReturnModel
  eventWindow: [number, number]
  estimationWindow: number
  outlierThreshold?: number | null
}

export interface AggregateStudyResult {
  nEvents: number
  meanCar: number[]
  cumulativeMeanCar: number
  tStat: number
  pValue: number
  individualCars: number[]
  eventDates: string[]
}

