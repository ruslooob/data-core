import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Plotly from 'plotly.js-dist-min'
import { runEventStudySensitivity } from '../api/client'
import type { ExpectedReturnModel, SensitivityCell } from '../api/types'
import {
  DEFAULT_GRID_ESTIMATIONS,
  DEFAULT_GRID_MODELS,
  DEFAULT_GRID_WINDOWS,
  GridConfigForm,
  HEATMAP_CELL_HEIGHT,
  HEATMAP_CELL_WIDTH,
  HEATMAP_PADDING_X,
  HEATMAP_PADDING_Y,
  MODEL_LABELS,
  Plot,
  plotStyle,
  Section,
} from './sensitivityGrid'

type Status = 'idle' | 'loading' | 'success' | 'error'

interface EventStudySensitivitySectionProps {
  ticker: string
  eventDate: string  // YYYY-MM-DD выбранного события
  /** Счётчик от родителя: его рост («Рассчитать» / стрелки) запускает пересчёт heatmap. */
  runSignal: number
}

/** Подпись величины со знаком в процентах. */
function fmtSignedPct(x: number): string {
  const v = x * 100
  return `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`
}

/**
 * Sensitivity для одного события: heatmap CAR против нормы по сетке параметров.
 * Каждая ячейка — CAR и норма (вилка обычного движения) при своей комбинации
 * (окно × модель × оценочное окно); цвет — вышел ли CAR за норму. t-тест
 * неприменим (n=1): устойчивость читается по тому, держится ли картина по сетке.
 */
export function EventStudySensitivitySection({ ticker, eventDate, runSignal }: EventStudySensitivitySectionProps) {
  const [gridWindows, setGridWindows] = useState<number[]>(DEFAULT_GRID_WINDOWS)
  const [gridModels, setGridModels] = useState<ExpectedReturnModel[]>(DEFAULT_GRID_MODELS)
  const [gridEstimations, setGridEstimations] = useState<number[]>(DEFAULT_GRID_ESTIMATIONS)
  const [sliceEstimation, setSliceEstimation] = useState<number>(DEFAULT_GRID_ESTIMATIONS[0])

  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<string | null>(null)
  const [cells, setCells] = useState<SensitivityCell[] | null>(null)

  const abortRef = useRef<AbortController | null>(null)

  // Смена события обнуляет результат — heatmap всегда про текущее событие.
  useEffect(() => {
    setCells(null)
    setStatus('idle')
    setError(null)
  }, [eventDate, ticker])

  const runGrid = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setStatus('loading')
    setError(null)
    try {
      const r = await runEventStudySensitivity({
        ticker,
        eventDate,
        grid: { windows: gridWindows, models: gridModels, estimationWindows: gridEstimations },
      }, ctrl.signal)
      if (ctrl.signal.aborted) return
      setCells(r.cells)
      setStatus('success')
      if (!gridEstimations.includes(sliceEstimation)) {
        setSliceEstimation(gridEstimations[0])
      }
    } catch (e) {
      if (ctrl.signal.aborted) return
      setError(e instanceof Error ? e.message : String(e))
      setStatus('error')
    }
  }, [ticker, eventDate, gridWindows, gridModels, gridEstimations, sliceEstimation])

  useEffect(() => () => { if (abortRef.current) abortRef.current.abort() }, [])

  // Авторасчёт по сигналу родителя (нажатие «Рассчитать» / стрелки в Event Study).
  // Через ref, чтобы эффект зависел только от сигнала, а не пересоздавался при
  // каждом изменении сетки/события.
  const runGridRef = useRef(runGrid)
  useEffect(() => { runGridRef.current = runGrid })
  useEffect(() => {
    if (runSignal > 0) void runGridRef.current()
  }, [runSignal])

  const sliceCells = useMemo(
    () => cells?.filter((c) => c.estimation === sliceEstimation) ?? [],
    [cells, sliceEstimation],
  )

  return (
    <div style={rootStyle}>
      <div style={titleStyle}>Sensitivity: CAR против нормы по параметрам</div>

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
        <label style={sliceLabelStyle}>
          Срез: оценочное окно
          <select
            value={sliceEstimation}
            onChange={(e) => setSliceEstimation(parseInt(e.target.value, 10))}
            style={sliceSelectStyle}
          >
            {gridEstimations.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </label>
        {status === 'error' && <span style={errorTextStyle}>{error}</span>}
      </div>

      {cells != null && (
        <SensitivityHeatmap cells={sliceCells} windows={gridWindows} models={gridModels} />
      )}
    </div>
  )
}

// ── Heatmap: CAR + норма, цвет по выходу за норму ───────────────────────────

function SensitivityHeatmap({
  cells,
  windows,
  models,
}: {
  cells: SensitivityCell[]
  windows: number[]
  models: ExpectedReturnModel[]
}) {
  const cellMap = useMemo(() => {
    const m = new Map<string, SensitivityCell>()
    for (const c of cells) m.set(`${c.model}|${c.window}`, c)
    return m
  }, [cells])

  // z кодирует три состояния: 0 — нет данных, 1 — CAR в норме, 2 — аномалия.
  const z: number[][] = models.map((m) =>
    windows.map((w) => {
      const c = cellMap.get(`${m}|${w}`)
      if (!c || !c.available) return 0
      return c.isAnomalySigned ? 2 : 1
    }),
  )

  const text: string[][] = models.map((m) =>
    windows.map((w) => {
      const c = cellMap.get(`${m}|${w}`)
      if (!c || !c.available) return '—'
      return `${fmtSignedPct(c.car)}\n[${fmtSignedPct(c.baselineDown)}, ${fmtSignedPct(c.baselineUp)}]`
    }),
  )

  // Дискретная шкала: серый (нет данных) → белый (в норме) → оранжевый (аномалия).
  const colorscale: Array<[number, string]> = [
    [0.0, '#f0f0f0'],
    [0.33, '#f0f0f0'],
    [0.33, '#ffffff'],
    [0.66, '#ffffff'],
    [0.66, '#ffe0b2'],
    [1.0, '#ffe0b2'],
  ]

  const data: Plotly.Data[] = [{
    type: 'heatmap',
    z,
    x: windows.map(String),
    y: models.map((m) => MODEL_LABELS[m]),
    text,
    texttemplate: '%{text}',
    textfont: { size: 12, color: '#000' },
    colorscale,
    zmin: 0, zmax: 2,
    showscale: false,
    xgap: 2,
    ygap: 2,
    hovertemplate: '%{text}<extra></extra>',
  } as unknown as Plotly.Data]

  const boxStyle: React.CSSProperties = {
    ...heatmapBlockStyle,
    width: HEATMAP_CELL_WIDTH * windows.length + HEATMAP_PADDING_X,
    height: HEATMAP_CELL_HEIGHT * models.length + HEATMAP_PADDING_Y,
  }

  return (
    <div style={boxStyle}>
      <Plot
        data={data}
        layout={{
          autosize: true,
          margin: { l: 110, r: 10, t: 25, b: 10 },
          xaxis: { type: 'category', side: 'top' },
          yaxis: { type: 'category', automargin: true, autorange: 'reversed' },
        }}
        useResizeHandler
        style={plotStyle}
        config={{ displayModeBar: false }}
      />
    </div>
  )
}

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  flexShrink: 0,
}

const titleStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: '#333',
  padding: '4px 0 2px',
  borderBottom: '1px solid #e0e0e0',
}

const paramsBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
  flexWrap: 'wrap',
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

const sliceLabelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
  fontSize: 12,
  color: '#555',
}

const sliceSelectStyle: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
}

const errorTextStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#c62828',
}

const heatmapBlockStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  overflow: 'hidden',
  flexShrink: 0,
  alignSelf: 'flex-start',
}
