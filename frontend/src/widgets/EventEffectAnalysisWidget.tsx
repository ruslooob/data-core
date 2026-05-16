import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Plotly from 'plotly.js-dist-min'
import createPlotlyComponent from 'react-plotly.js/factory'
import { runEventEffectIndividual, runEventEffectSensitivity } from '../api/client'
import type {
  CentralStatistic,
  EventEffectIndividualResponse,
  EventEffectSensitivityResponse,
  ExpectedReturnModel,
  IndividualCarRow,
  SensitivityCell,
} from '../api/types'
import type { WidgetGroup } from './chartSync'
import { selectLeaderTicker, selectPrecedentSet, useGroupStore } from './groupStore'

const Plot = createPlotlyComponent(Plotly)

interface EventEffectAnalysisWidgetProps {
  group: WidgetGroup
}

type Tab = 'explorer' | 'sensitivity'
type FetchStatus = 'idle' | 'loading' | 'success' | 'error'

const DEFAULT_WINDOW = 5
const DEFAULT_MODEL: ExpectedReturnModel = 'market_model'
const DEFAULT_ESTIMATION = 200
const DEFAULT_CENTRAL: CentralStatistic = 'median'

const DEBOUNCE_MS = 350
const MODELS: ExpectedReturnModel[] = ['mean_adjusted', 'market_model', 'capm']
const MODEL_LABELS: Record<ExpectedReturnModel, string> = {
  mean_adjusted: 'Mean Adjusted',
  market_model: 'Market Model',
  capm: 'CAPM',
}

const WINDOW_PRESET = [3, 5, 10, 20]
const ESTIMATION_PRESET = [100, 150, 200, 250]
const DEFAULT_GRID_WINDOWS = [3, 5, 10]
const DEFAULT_GRID_MODELS: ExpectedReturnModel[] = ['market_model', 'capm']
const DEFAULT_GRID_ESTIMATIONS = [150, 200]

const SMALL_SAMPLE_THRESHOLD = 5
const SHAPIRO_ALPHA = 0.05

export function EventEffectAnalysisWidget({ group }: EventEffectAnalysisWidgetProps) {
  const eventIds = useGroupStore(selectPrecedentSet(group))
  const leaderTicker = useGroupStore(selectLeaderTicker(group))

  // ── Заглушки до того, как можно считать ──

  if (group === 'none') {
    return <PlaceholderMessage text="Привяжите виджет к группе (выберите цвет рядом с заголовком), затем выберите ведущий график и набор прецедентов." />
  }
  if (eventIds.length === 0) {
    return <PlaceholderMessage text="Выберите события в виджете «Поиск прецедентов» этой же группы." />
  }
  if (leaderTicker == null) {
    return <PlaceholderMessage text="Назначьте ведущий график цены в группе (через кнопку ведущего на графике)." />
  }

  return <Body ticker={leaderTicker} eventIds={eventIds} />
}

// ────────────────────────────────────────────────────────────────────────────
// Основное тело виджета
// ────────────────────────────────────────────────────────────────────────────

function Body({
  ticker,
  eventIds,
}: {
  ticker: string
  eventIds: string[]
}) {
  const [tab, setTab] = useState<Tab>('explorer')

  return (
    <div style={rootStyle}>
      <div style={tabsBarStyle}>
        <button
          style={tab === 'explorer' ? tabActiveStyle : tabStyle}
          onClick={() => setTab('explorer')}
        >
          Events CAR Explorer
        </button>
        <button
          style={tab === 'sensitivity' ? tabActiveStyle : tabStyle}
          onClick={() => setTab('sensitivity')}
        >
          CAR Sensitivity Analysis
        </button>
        <span style={tabMetaStyle}>{ticker} · {eventIds.length} событий выбрано</span>
      </div>

      {/* Обе вкладки всегда смонтированы — переключение через видимость,
          чтобы при возврате не терять загруженные данные и параметры. */}
      <div style={tab === 'explorer' ? tabPaneVisibleStyle : tabPaneHiddenStyle}>
        <ExplorerTab ticker={ticker} eventIds={eventIds} />
      </div>
      <div style={tab === 'sensitivity' ? tabPaneVisibleStyle : tabPaneHiddenStyle}>
        <SensitivityTab ticker={ticker} eventIds={eventIds} />
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Вкладка 1: Events CAR Explorer
// ────────────────────────────────────────────────────────────────────────────

function ExplorerTab({ ticker, eventIds }: { ticker: string; eventIds: string[] }) {
  const [eventWindow, setEventWindow] = useState(DEFAULT_WINDOW)
  const [model, setModel] = useState<ExpectedReturnModel>(DEFAULT_MODEL)
  const [estimation, setEstimation] = useState(DEFAULT_ESTIMATION)
  const [central, setCentral] = useState<CentralStatistic>(DEFAULT_CENTRAL)

  const [status, setStatus] = useState<FetchStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [resp, setResp] = useState<EventEffectIndividualResponse | null>(null)

  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | null>(null)

  // Debounced fetch при изменении параметров
  useEffect(() => {
    if (timerRef.current != null) globalThis.clearTimeout(timerRef.current)
    timerRef.current = globalThis.setTimeout(() => {
      void fetchIndividual()
    }, DEBOUNCE_MS) as unknown as number
    return () => {
      if (timerRef.current != null) globalThis.clearTimeout(timerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker, eventIds, eventWindow, model, estimation, central])

  useEffect(() => () => { if (abortRef.current) abortRef.current.abort() }, [])

  const fetchIndividual = async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setStatus('loading')
    setError(null)
    try {
      const r = await runEventEffectIndividual({
        ticker,
        eventIds,
        params: { window: eventWindow, model, estimationWindow: estimation },
        centralStatistic: central,
      }, ctrl.signal)
      if (ctrl.signal.aborted) return
      setResp(r)
      setStatus('success')
    } catch (e) {
      if (ctrl.signal.aborted) return
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
    }
  }

  const n = resp?.forecast?.n ?? 0
  const excludedCount = resp?.excludedEvents.length ?? 0
  const totalRequested = eventIds.length
  const shapiroP = resp?.forecast?.shapiroPValue ?? null

  return (
    <div style={tabRootStyle}>
      {/* Параметры */}
      <div style={paramsBarStyle}>
        <label style={paramLabelStyle}>
          Окно (±)
          <input
            type="number"
            min={1} max={30}
            value={eventWindow}
            onChange={(e) => setEventWindow(Math.max(1, parseInt(e.target.value || '1', 10)))}
            style={paramInputStyle}
          />
        </label>
        <label style={paramLabelStyle}>
          Модель
          <select value={model} onChange={(e) => setModel(e.target.value as ExpectedReturnModel)} style={paramSelectStyle}>
            {MODELS.map((m) => <option key={m} value={m}>{MODEL_LABELS[m]}</option>)}
          </select>
        </label>
        <label style={paramLabelStyle}>
          Оценочное окно
          <input
            type="number"
            min={20} max={500}
            value={estimation}
            onChange={(e) => setEstimation(Math.max(20, parseInt(e.target.value || '200', 10)))}
            style={paramInputStyle}
          />
        </label>
        <label style={paramLabelStyle}>
          Прогноз вокруг
          <select value={central} onChange={(e) => setCentral(e.target.value as CentralStatistic)} style={paramSelectStyle}>
            <option value="median">медианы</option>
            <option value="mean">среднего</option>
          </select>
        </label>
        <span style={statusInlineStyle}>{statusInlineText(status)}</span>
      </div>

      {/* Диагностика */}
      <div style={warningsBlockStyle}>
        {excludedCount > 0 && (
          <Warning text={`${excludedCount} из ${totalRequested} событий исключено: недостаточно истории для оценочного окна.`} />
        )}
        {shapiroP != null && shapiroP < SHAPIRO_ALPHA && (
          <Warning text={`⚠ распределение CAR не нормально (Shapiro p = ${shapiroP.toFixed(3)}). Прогнозный интервал может быть неточным.`} />
        )}
        {n > 0 && n < SMALL_SAMPLE_THRESHOLD && (
          <Warning text={`Выборка мала (n = ${n}). Оценки прогнозного интервала могут быть ненадёжны.`} />
        )}
        {error && <Warning text={error} severity="error" />}
      </div>

      {/* Три представления */}
      {resp != null && (
        <div style={explorerGridStyle}>
          <CarTable rows={resp.individualCars} />
          <CarHistogram rows={resp.individualCars} forecast={resp.forecast} />
          <CarScatter rows={resp.individualCars} />
        </div>
      )}
    </div>
  )
}

// ── Таблица индивидуальных CAR ──

type SortKey = 'date' | 'car'
type SortDir = 'asc' | 'desc'

function CarTable({ rows }: { rows: IndividualCarRow[] }) {
  const [sortKey, setSortKey] = useState<SortKey>('date')
  const [sortDir, setSortDir] = useState<SortDir>('asc')

  const sorted = useMemo(() => {
    const copy = rows.slice()
    copy.sort((a, b) => {
      const va = sortKey === 'date' ? a.date : a.car
      const vb = sortKey === 'date' ? b.date : b.car
      const cmp = va < vb ? -1 : va > vb ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
    return copy
  }, [rows, sortKey, sortDir])

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir(key === 'date' ? 'asc' : 'desc') }
  }

  return (
    <div style={blockStyle}>
      <div style={blockTitleStyle}>Индивидуальные CAR</div>
      <div style={tableWrapperStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thClickableStyle} onClick={() => toggleSort('date')}>
                дата {sortKey === 'date' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
              <th style={thClickableStyle} onClick={() => toggleSort('car')}>
                CAR {sortKey === 'car' ? (sortDir === 'asc' ? '▲' : '▼') : ''}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr><td style={emptyCellStyle} colSpan={2}>Нет валидных событий</td></tr>
            ) : sorted.map((r) => (
              <tr key={r.eventId}>
                <td style={tdStyle}>{r.date}</td>
                <td style={{ ...tdStyle, color: r.car >= 0 ? '#1a7f37' : '#a01919' }}>
                  {(r.car * 100).toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ── Гистограмма с накладкой 95% PI ──

function CarHistogram({
  rows,
  forecast,
}: {
  rows: IndividualCarRow[]
  forecast: EventEffectIndividualResponse['forecast']
}) {
  const cars = rows.map((r) => r.car * 100)
  const bins = makeHistogramBins(cars)

  const shapes: Partial<Plotly.Shape>[] = forecast != null
    ? [{
        type: 'rect',
        xref: 'x', yref: 'paper',
        x0: forecast.piLower * 100, x1: forecast.piUpper * 100,
        y0: 0, y1: 1,
        fillcolor: 'rgba(41, 98, 255, 0.12)',
        line: { width: 0 },
        layer: 'below',
      } as Partial<Plotly.Shape>, {
        type: 'line',
        xref: 'x', yref: 'paper',
        x0: forecast.central * 100, x1: forecast.central * 100,
        y0: 0, y1: 1,
        line: { color: '#666', width: 2, dash: 'dash' },
      } as Partial<Plotly.Shape>]
    : []

  const data: Plotly.Data[] = [{
    type: 'bar',
    x: bins.map((b) => (b.start + b.end) / 2),
    y: bins.map((b) => b.count),
    width: bins.map((b) => b.end - b.start),
    customdata: bins.map((b) => [b.start, b.end]) as unknown as Plotly.Datum[],
    marker: {
      color: '#2962FF',
      line: { color: '#fff', width: 1 },
    },
    hovertemplate: '(%{customdata[0]:.2f}; %{customdata[1]:.2f}): %{y}<extra></extra>',
    name: 'CAR',
  }]

  return (
    <div style={blockStyle}>
      <div style={blockTitleStyle}>
        Распределение CAR
        {forecast != null && (
          <span style={blockSubtitleStyle}>
            &nbsp;· 95% PI: [{(forecast.piLower * 100).toFixed(2)}%, {(forecast.piUpper * 100).toFixed(2)}%]
          </span>
        )}
      </div>
      <Plot
        data={data}
        layout={{
          autosize: true,
          margin: { l: 40, r: 10, t: 10, b: 35 },
          xaxis: { title: { text: 'CAR, %' }, zeroline: true, zerolinecolor: '#999' },
          yaxis: { title: { text: 'события' } },
          shapes,
          showlegend: false,
        }}
        useResizeHandler
        style={plotStyle}
        config={{ displayModeBar: false }}
      />
    </div>
  )
}

// ── Scatter CAR по времени ──

function CarScatter({ rows }: { rows: IndividualCarRow[] }) {
  const data: Plotly.Data[] = [{
    x: rows.map((r) => r.date),
    y: rows.map((r) => r.car * 100),
    type: 'scatter',
    mode: 'markers',
    marker: { color: '#2962FF', size: 7 },
    name: 'CAR',
  }]

  return (
    <div style={blockStyle}>
      <div style={blockTitleStyle}>CAR во времени</div>
      <Plot
        data={data}
        layout={{
          autosize: true,
          margin: { l: 40, r: 10, t: 10, b: 35 },
          xaxis: { title: { text: 'дата события' }, type: 'date' },
          yaxis: { title: { text: 'CAR, %' }, zeroline: true, zerolinecolor: '#999' },
          showlegend: false,
        }}
        useResizeHandler
        style={plotStyle}
        config={{ displayModeBar: false }}
      />
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Вкладка 2: CAR Sensitivity Analysis
// ────────────────────────────────────────────────────────────────────────────

function SensitivityTab({ ticker, eventIds }: { ticker: string; eventIds: string[] }) {
  const [gridWindows, setGridWindows] = useState<number[]>(DEFAULT_GRID_WINDOWS)
  const [gridModels, setGridModels] = useState<ExpectedReturnModel[]>(DEFAULT_GRID_MODELS)
  const [gridEstimations, setGridEstimations] = useState<number[]>(DEFAULT_GRID_ESTIMATIONS)
  const [sliceEstimation, setSliceEstimation] = useState<number>(DEFAULT_GRID_ESTIMATIONS[0])

  const [status, setStatus] = useState<FetchStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [resp, setResp] = useState<EventEffectSensitivityResponse | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  const runGrid = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setStatus('loading')
    setError(null)
    try {
      const r = await runEventEffectSensitivity({
        ticker,
        eventIds,
        grid: { windows: gridWindows, models: gridModels, estimationWindows: gridEstimations },
      }, ctrl.signal)
      if (ctrl.signal.aborted) return
      setResp(r)
      setStatus('success')
      if (!gridEstimations.includes(sliceEstimation)) {
        setSliceEstimation(gridEstimations[0])
      }
    } catch (e) {
      if (ctrl.signal.aborted) return
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
    }
  }, [ticker, eventIds, gridWindows, gridModels, gridEstimations, sliceEstimation])

  useEffect(() => () => { if (abortRef.current) abortRef.current.abort() }, [])

  const sliceCells = useMemo(
    () => resp?.cells.filter((c) => c.estimation === sliceEstimation) ?? [],
    [resp, sliceEstimation],
  )

  return (
    <div style={tabRootStyle}>
      <Section title="Настроить сетку" initiallyOpen={false}>
        <GridConfigForm
          windows={gridWindows} setWindows={setGridWindows}
          models={gridModels} setModels={setGridModels}
          estimations={gridEstimations} setEstimations={setGridEstimations}
        />
      </Section>

      <div style={paramsBarStyle}>
        <button onClick={() => void runGrid()} disabled={status === 'loading'} style={runButtonStyle}>
          {status === 'loading' ? 'Расчёт…' : 'Рассчитать'}
        </button>
        <label style={paramLabelStyle}>
          Срез: оценочное окно
          <select
            value={sliceEstimation}
            onChange={(e) => setSliceEstimation(parseInt(e.target.value, 10))}
            style={paramSelectStyle}
          >
            {gridEstimations.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </label>
        <span style={statusInlineStyle}>{statusInlineText(status)}</span>
      </div>

      {error && <Warning text={error} severity="error" />}

      {resp != null && (
        <SensitivityHeatmap
          cells={sliceCells}
          windows={gridWindows}
          models={gridModels}
        />
      )}
    </div>
  )
}

// ── Section: сворачиваемая секция (стиль из BacktestEditor) ─────────────

function Section({ title, initiallyOpen, children }: { title: string; initiallyOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(initiallyOpen ?? true)
  return (
    <div style={sectionWrapStyle}>
      <div style={sectionHeaderStyle} onClick={() => setOpen(!open)}>
        <span>{open ? '▾' : '▸'} {title}</span>
      </div>
      {open && <div style={sectionBodyStyle}>{children}</div>}
    </div>
  )
}

// ── Форма настройки сетки (встраивается в гармошку) ──

function GridConfigForm({
  windows, setWindows,
  models, setModels,
  estimations, setEstimations,
}: {
  windows: number[]
  setWindows: (v: number[]) => void
  models: ExpectedReturnModel[]
  setModels: (v: ExpectedReturnModel[]) => void
  estimations: number[]
  setEstimations: (v: number[]) => void
}) {
  const toggleNum = (arr: number[], setArr: (v: number[]) => void, x: number) =>
    setArr(arr.includes(x) ? arr.filter((v) => v !== x) : [...arr, x].sort((a, b) => a - b))
  const toggleModel = (m: ExpectedReturnModel) =>
    setModels(models.includes(m) ? models.filter((v) => v !== m) : [...models, m])

  return (
    <>
      <div style={configRowStyle}>
        <span style={configLabelStyle}>Окна</span>
        {WINDOW_PRESET.map((w) => (
          <label key={w} style={configChipStyle}>
            <input type="checkbox" checked={windows.includes(w)} onChange={() => toggleNum(windows, setWindows, w)} />
            {w}
          </label>
        ))}
      </div>
      <div style={configRowStyle}>
        <span style={configLabelStyle}>Модели</span>
        {MODELS.map((m) => (
          <label key={m} style={configChipStyle}>
            <input type="checkbox" checked={models.includes(m)} onChange={() => toggleModel(m)} />
            {MODEL_LABELS[m]}
          </label>
        ))}
      </div>
      <div style={configRowStyle}>
        <span style={configLabelStyle}>Оценочные окна</span>
        {ESTIMATION_PRESET.map((e) => (
          <label key={e} style={configChipStyle}>
            <input type="checkbox" checked={estimations.includes(e)} onChange={() => toggleNum(estimations, setEstimations, e)} />
            {e}
          </label>
        ))}
      </div>
    </>
  )
}

// ── Heatmap ──

function SensitivityHeatmap({
  cells,
  windows,
  models,
}: {
  cells: SensitivityCell[]
  windows: number[]
  models: ExpectedReturnModel[]
}) {
  // Карта (model, window) → cell
  const cellMap = useMemo(() => {
    const m = new Map<string, SensitivityCell>()
    for (const c of cells) m.set(`${c.model}|${c.window}`, c)
    return m
  }, [cells])

  // z для цвета — по p_value (низкое p → насыщенный зелёный). Используем
  // дискретную шкалу через колеровку готовых значений ниже.
  const z: number[][] = models.map((m) =>
    windows.map((w) => {
      const c = cellMap.get(`${m}|${w}`)
      return c ? c.pValue : 1.0
    }),
  )

  const textMatrix: string[][] = models.map((m) =>
    windows.map((w) => {
      const c = cellMap.get(`${m}|${w}`)
      if (!c) return '—'
      return `${(c.car * 100).toFixed(2)}%\np=${c.pValue.toFixed(3)}\nn=${c.n}`
    }),
  )

  // colorscale: p<0.05 → насыщенный зелёный, p<0.10 → жёлтый, иначе серый.
  // Используем зонированную дискретную шкалу.
  const colorscale: Array<[number, string]> = [
    [0.0, '#2e7d32'],
    [0.05, '#a5d6a7'],
    [0.05, '#fff59d'],
    [0.10, '#fff59d'],
    [0.10, '#eeeeee'],
    [1.0, '#eeeeee'],
  ]

  const data: Plotly.Data[] = [{
    type: 'heatmap',
    z,
    x: windows.map(String),
    y: models.map((m) => MODEL_LABELS[m]),
    text: textMatrix,
    texttemplate: '%{text}',
    textfont: { size: 11 },
    colorscale,
    zmin: 0, zmax: 1,
    showscale: false,
    xgap: 2,
    ygap: 2,
    hovertemplate: '%{text}<extra></extra>',
  } as unknown as Plotly.Data]

  return (
    <div style={heatmapBlockStyle}>
      <Plot
        data={data}
        layout={{
          autosize: true,
          margin: { l: 90, r: 10, t: 10, b: 30 },
          xaxis: { type: 'category' },
          yaxis: { type: 'category', automargin: true },
        }}
        useResizeHandler
        style={plotStyle}
        config={{ displayModeBar: false }}
      />
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Хелперы
// ────────────────────────────────────────────────────────────────────────────

function PlaceholderMessage({ text }: { text: string }) {
  return <div style={placeholderStyle}>{text}</div>
}

function Warning({ text, severity = 'warn' }: { text: string; severity?: 'warn' | 'error' }) {
  return (
    <div style={severity === 'error' ? errorBannerStyle : warningBannerStyle}>
      {text}
    </div>
  )
}

function statusInlineText(s: FetchStatus): string {
  if (s === 'loading') return 'Расчёт…'
  if (s === 'error') return 'Ошибка'
  return ''
}

interface HistogramBin {
  start: number
  end: number
  count: number
}

/** Freedman-Diaconis: h = 2*IQR / n^(1/3). Возвращает готовые бины с count. */
function makeHistogramBins(values: number[]): HistogramBin[] {
  const n = values.length
  if (n === 0) return []
  const sorted = values.slice().sort((a, b) => a - b)
  const min = sorted[0]
  const max = sorted[n - 1]
  if (n < 2 || max === min) {
    return [{ start: min, end: max, count: n }]
  }
  const q = (p: number) => {
    const i = (n - 1) * p
    const lo = Math.floor(i), hi = Math.ceil(i)
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (i - lo)
  }
  const iqr = q(0.75) - q(0.25)
  // Если IQR вырожден — fallback на правило Стёрджеса.
  const h = iqr > 0 ? (2 * iqr) / Math.cbrt(n) : (max - min) / Math.ceil(Math.log2(n) + 1)
  if (h <= 0) return [{ start: min, end: max, count: n }]
  const binCount = Math.max(1, Math.ceil((max - min) / h))
  const bins: HistogramBin[] = []
  for (let i = 0; i < binCount; i++) {
    bins.push({ start: min + i * h, end: min + (i + 1) * h, count: 0 })
  }
  for (const v of values) {
    let idx = Math.floor((v - min) / h)
    if (idx >= binCount) idx = binCount - 1
    if (idx < 0) idx = 0
    bins[idx].count += 1
  }
  return bins
}

// ────────────────────────────────────────────────────────────────────────────
// Стили
// ────────────────────────────────────────────────────────────────────────────

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  gap: 8,
}

const tabsBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 4,
  flexShrink: 0,
  borderBottom: '1px solid #eee',
}

const tabBaseStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  background: 'transparent',
  border: 'none',
  borderBottom: '2px solid transparent',
  cursor: 'pointer',
  color: '#666',
}

const tabStyle: React.CSSProperties = tabBaseStyle

const tabActiveStyle: React.CSSProperties = {
  ...tabBaseStyle,
  color: '#2962FF',
  borderBottomColor: '#2962FF',
  fontWeight: 600,
}

const tabMetaStyle: React.CSSProperties = {
  marginLeft: 'auto',
  fontSize: 12,
  color: '#777',
}

const tabRootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  gap: 8,
  overflow: 'hidden',
}

const tabPaneVisibleStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  overflow: 'hidden',
}

const tabPaneHiddenStyle: React.CSSProperties = {
  display: 'none',
}

const paramsBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-end',
  gap: 12,
  flexShrink: 0,
}

const paramLabelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
  fontSize: 11,
  color: '#555',
}

const paramInputStyle: React.CSSProperties = {
  width: 64,
  padding: '4px 6px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
  outline: 'none',
}

const paramSelectStyle: React.CSSProperties = {
  padding: '4px 6px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
  background: '#fff',
}

const statusInlineStyle: React.CSSProperties = {
  marginLeft: 'auto',
  fontSize: 12,
  color: '#555',
}

const runButtonStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  background: '#2962FF',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const warningsBlockStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  flexShrink: 0,
}

const warningBannerStyle: React.CSSProperties = {
  padding: '6px 10px',
  background: '#fff8e1',
  border: '1px solid #ffd54f',
  borderRadius: 4,
  color: '#5d4037',
  fontSize: 12,
}

const errorBannerStyle: React.CSSProperties = {
  padding: '6px 10px',
  background: '#fdecea',
  border: '1px solid #f5a8a3',
  borderRadius: 4,
  color: '#a01919',
  fontSize: 12,
}

const explorerGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '260px 1fr 1fr',
  gap: 12,
  flex: 1,
  minHeight: 0,
}

const blockStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  overflow: 'hidden',
  minHeight: 0,
}

const heatmapBlockStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  overflow: 'hidden',
  height: 280,
  flexShrink: 0,
}

const blockTitleStyle: React.CSSProperties = {
  padding: '6px 10px',
  background: '#f5f5f5',
  borderBottom: '1px solid #e0e0e0',
  fontSize: 12,
  fontWeight: 600,
  color: '#444',
  flexShrink: 0,
}

const blockSubtitleStyle: React.CSSProperties = {
  fontWeight: 400,
  color: '#777',
}

const tableWrapperStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  overflow: 'auto',
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 12,
}

const thClickableStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  background: '#fafafa',
  borderBottom: '1px solid #e0e0e0',
  position: 'sticky',
  top: 0,
  cursor: 'pointer',
  userSelect: 'none',
  fontWeight: 600,
}

const tdStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderBottom: '1px solid #f0f0f0',
  whiteSpace: 'nowrap',
}

const emptyCellStyle: React.CSSProperties = {
  padding: '12px',
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}

const plotStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
}

const placeholderStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: 24,
  textAlign: 'center',
  color: '#888',
  fontSize: 13,
}

const sectionWrapStyle: React.CSSProperties = {
  border: '1px solid #e0e0e0',
  borderRadius: 6,
  background: '#fafafa',
  flexShrink: 0,
}

const sectionHeaderStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: '#333',
  cursor: 'pointer',
  userSelect: 'none',
}

const sectionBodyStyle: React.CSSProperties = {
  padding: 12,
  background: '#fff',
  borderTop: '1px solid #eee',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
}

const configRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  flexWrap: 'wrap',
}

const configLabelStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#555',
  fontWeight: 600,
  minWidth: 130,
}

const configChipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  fontSize: 12,
  color: '#444',
  cursor: 'pointer',
}

