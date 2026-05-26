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

export interface PrecedentFuzzyHit {
  eventId: string
  event: string
  dateStart: string
}

export interface PrecedentFuzzySearchResponse {
  hits: PrecedentFuzzyHit[]
  truncated: boolean
}

export interface PrecedentEvent {
  eventId: string
  event: string
  dateStart: string
}

// ── Event Effect Analysis ───────────────────────────────────────────────────

export interface EventEffectParams {
  window: number
  model: ExpectedReturnModel
  estimationWindow: number
}

export type CentralStatistic = 'median' | 'mean'

export interface EventEffectIndividualRequest {
  ticker: string
  eventIds: string[]
  params: EventEffectParams
  centralStatistic: CentralStatistic
}

export interface IndividualCarRow {
  eventId: string
  date: string
  car: number
  rank: number
  isAnomaly: boolean
  baselineBand: number
  signedRank: number
  isAnomalySigned: boolean
  baselineUp: number
  baselineDown: number
}

export interface ExcludedEventRow {
  eventId: string
  reason: string
}

export interface IndividualForecast {
  central: number
  piLower: number
  piUpper: number
  n: number
  shapiroPValue: number | null
}

export interface EventEffectIndividualResponse {
  individualCars: IndividualCarRow[]
  excludedEvents: ExcludedEventRow[]
  forecast: IndividualForecast | null
}

export interface SensitivityGrid {
  windows: number[]
  models: ExpectedReturnModel[]
  estimationWindows: number[]
}

export interface EventEffectSensitivityRequest {
  ticker: string
  eventIds: string[]
  grid: SensitivityGrid
}

export interface SensitivityCell {
  window: number
  model: ExpectedReturnModel
  estimation: number
  car: number
  pValue: number
  n: number
  meanRank: number
  rankPValue: number
}

export interface EventEffectSensitivityResponse {
  cells: SensitivityCell[]
  excludedEventsByEstimation: Record<string, string[]>
}

// ── Исследование (Research) ─────────────────────────────────────────────────

export interface Research {
  id: string
  name: string
  description: string | null
  conclusion: string | null
  createdAt: string
  isDefault: boolean
}

export interface ResearchCreate {
  name: string
  description?: string | null
}

export interface ResearchPatch {
  name?: string | null
  description?: string | null
  conclusion?: string | null
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
  description?: string | null
  researchId?: string | null
}

export interface RuleCreate {
  name: string
  triggerSql: string
  actionType: ActionType
  actionQuantitySql: string
  priority: number
  description?: string | null
  researchId?: string | null
}

export interface Strategy {
  id: string
  name: string
  ruleIds: string[]
  createdAt: string
  description?: string | null
  researchId?: string | null
}

export interface StrategyCreate {
  name: string
  ruleIds: string[]
  description?: string | null
  researchId?: string | null
}

export interface Environment {
  id: string
  name: string
  dateStart: string
  dateEnd: string
  startingCapital: number
  createdAt: string
  description?: string | null
  researchId?: string | null
}

export interface EnvironmentCreate {
  name: string
  dateStart: string
  dateEnd: string
  startingCapital: number
  description?: string | null
  researchId?: string | null
}

export interface BacktestResultMeta {
  id: string
  strategyId: string
  environmentId: string
  createdAt: string
  totalReturnPct: number
  annualReturnPct: number
  maxDrawdownPct: number
  sharpe: number
  nTrades: number
  profitFactor: number | null
  winRatePct: number | null
}

export type TradeType = 'buy' | 'sell' | 'dividend'

export interface BacktestTrade {
  tradeDate: string
  ticker: string
  type: TradeType
  quantity: number
  price: number
  ruleName: string
  pnlRealized: number | null
}

export interface BacktestResultDetail extends BacktestResultMeta {
  trades: BacktestTrade[]
  equityCurve: { date: string; equity: number }[]
  strategy: Strategy | null
  environment: Environment | null
}

export interface BacktestRunRequest {
  strategyId: string
  environmentId: string
  researchId: string
}

export interface BacktestRunStarted {
  runId: string
  status: 'running'
}

export interface BacktestRunProgress {
  runId: string
  strategyId: string
  environmentId: string
  status: 'running' | 'done' | 'error' | 'cancelled'
  progress: number  // 0..1
  currentDate: string | null
  currentEquity: number | null
  nTradesSoFar: number
  done: boolean
  resultId: string | null
  errorMessage: string | null
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
  estimationDates: string[]
  estimationActual: number[]
  estimationPredicted: number[]
  rSquared: number
  estimationResidualSigmas: number[]
  carCumulative: number[]
  ciBand: number[]
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

