/**
 * Общие строительные блоки sensitivity-анализа для двух виджетов:
 *  - AggregateSensitivity (вкладка Event Effect Analysis, перебор по выборке),
 *  - Sensitivity (секция Event Study, перебор по одному событию).
 *
 * Сетка параметров (окна × модели × оценочные окна) и её UI едины: правка здесь
 * меняет оба места. Сам heatmap у виджетов разный (агрегат красит по p-value,
 * индивидуальный — по выходу CAR за норму) и живёт в своих файлах.
 */
import { useState, type ReactNode } from 'react'
import Plotly from 'plotly.js-dist-min'
import createPlotlyComponent from 'react-plotly.js/factory'
import type { ExpectedReturnModel } from '../api/types'

export const Plot = createPlotlyComponent(Plotly)

export const MODELS: ExpectedReturnModel[] = ['mean_adjusted', 'market_model', 'capm']
export const MODEL_LABELS: Record<ExpectedReturnModel, string> = {
  mean_adjusted: 'Mean Adjusted',
  market_model: 'Market Model',
  capm: 'CAPM',
}

export const WINDOW_PRESET = [3, 5, 10, 20]
export const ESTIMATION_PRESET = [100, 150, 200, 250]
export const DEFAULT_GRID_WINDOWS = [3, 5, 10]
export const DEFAULT_GRID_MODELS: ExpectedReturnModel[] = ['market_model', 'capm']
export const DEFAULT_GRID_ESTIMATIONS = [150, 200]

// Размеры heatmap зависят от размера сетки: ширина = ячейки × число окон,
// высота = ячейки × число моделей. Это избавляет от пустого серого поля при
// маленькой сетке и масштабирует контейнер под большую сетку.
//
// HEATMAP_CELL_TEXT_WIDTH — оценка ширины текста внутри ячейки в шрифте 13pt.
// HEATMAP_CELL_PADDING_X — желаемый горизонтальный воздух с каждой стороны.
const HEATMAP_CELL_TEXT_WIDTH = 90
const HEATMAP_CELL_PADDING_X = 30
export const HEATMAP_CELL_WIDTH = HEATMAP_CELL_TEXT_WIDTH + HEATMAP_CELL_PADDING_X * 2
export const HEATMAP_CELL_HEIGHT = 70
export const HEATMAP_PADDING_X = 124  // margin.l + margin.r + борды
export const HEATMAP_PADDING_Y = 40   // margin.t + margin.b + борды

export const plotStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
}

// ── Сворачиваемая секция (стиль из BacktestEditor) ──────────────────────────

export function Section({ title, initiallyOpen, children }: { title: string; initiallyOpen?: boolean; children: ReactNode }) {
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

// ── Форма настройки сетки (встраивается в гармошку) ─────────────────────────

export function GridConfigForm({
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
