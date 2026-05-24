import { useEffect, useMemo, useRef, useState } from 'react'
import {
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
} from 'lightweight-charts'

interface FactVsForecastChartProps {
  dates: string[]
  actual: number[]
  predicted: number[]
  /** Порог подсветки выбросов в σ остатков. 0 = выкл. */
  highlightThreshold: number
}

interface TooltipState {
  date: string
  actual: number
  predicted: number
  delta: number
  x: number
  y: number
}

/**
 * Визуальная диагностика подгонки модели на оценочном окне:
 * сравнение фактической лог-доходности и предсказания модели.
 *
 * Ось X — реальные торговые даты (YYYY-MM-DD). Горизонтальный скролл доступен.
 * Ось Y — в процентах (значение * 100).
 *
 * При hover курсора показывается тултип с фактом, прогнозом и их разницей
 * (остатком модели на этом дне).
 */
export function FactVsForecastChart({
  dates,
  actual,
  predicted,
  highlightThreshold,
}: FactVsForecastChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const actualRef = useRef<ISeriesApi<'Line'> | null>(null)
  const predictedRef = useRef<ISeriesApi<'Line'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const dataRef = useRef<{ dates: string[]; actual: number[]; predicted: number[] }>({
    dates: [],
    actual: [],
    predicted: [],
  })
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  const outlierDates = useMemo(() => {
    if (highlightThreshold <= 0) return new Set<string>()
    const n = Math.min(dates.length, actual.length, predicted.length)
    if (n < 2) return new Set<string>()
    const residuals: number[] = []
    for (let i = 0; i < n; i++) residuals.push(actual[i] - predicted[i])
    const mean = residuals.reduce((s, r) => s + r, 0) / n
    let sumSq = 0
    for (const r of residuals) sumSq += (r - mean) * (r - mean)
    const sigma = Math.sqrt(sumSq / (n - 1))
    if (sigma === 0) return new Set<string>()
    const limit = highlightThreshold * sigma
    const out = new Set<string>()
    for (let i = 0; i < n; i++) {
      if (Math.abs(residuals[i]) > limit) out.add(dates[i])
    }
    return out
  }, [dates, actual, predicted, highlightThreshold])

  // Init chart once
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: { background: { color: '#ffffff' }, textColor: '#333' },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      rightPriceScale: { borderColor: '#e0e0e0' },
      timeScale: {
        borderColor: '#e0e0e0',
        timeVisible: false,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Magnet },
    })

    const predictedSeries = chart.addSeries(LineSeries, {
      color: '#90A4AE',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: {
        type: 'custom',
        formatter: (p: number) => `${p.toFixed(2)}%`,
        minMove: 0.01,
      },
    })
    predictedRef.current = predictedSeries

    const actualSeries = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: {
        type: 'custom',
        formatter: (p: number) => `${p.toFixed(2)}%`,
        minMove: 0.01,
      },
    })
    actualRef.current = actualSeries

    chartRef.current = chart

    const onMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top
      const { dates: ds, actual: as_, predicted: ps } = dataRef.current
      if (ds.length === 0) {
        setTooltip(null)
        return
      }
      // Сначала пробуем точную координату через timeScale; если null — fallback на ratio.
      let idx = -1
      const time = chart.timeScale().coordinateToTime(x)
      if (time !== null) {
        const timeKey = timeToIsoDate(time)
        idx = ds.indexOf(timeKey)
        if (idx === -1) idx = nearestIndex(ds, timeKey)
      } else {
        const ratio = Math.max(0, Math.min(1, x / rect.width))
        idx = Math.round(ratio * (ds.length - 1))
      }
      if (idx < 0 || idx >= ds.length) {
        setTooltip(null)
        return
      }
      const a = as_[idx] * 100
      const p = ps[idx] * 100
      setTooltip({
        date: ds[idx],
        actual: a,
        predicted: p,
        delta: a - p,
        x,
        y,
      })
    }
    const onMouseLeave = () => setTooltip(null)
    container.addEventListener('mousemove', onMouseMove)
    container.addEventListener('mouseleave', onMouseLeave)

    const ro = new ResizeObserver(() => {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    })
    ro.observe(container)

    return () => {
      container.removeEventListener('mousemove', onMouseMove)
      container.removeEventListener('mouseleave', onMouseLeave)
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      actualRef.current = null
      predictedRef.current = null
      markersRef.current = null
    }
  }, [])

  // Update data
  useEffect(() => {
    const actualSeries = actualRef.current
    const predictedSeries = predictedRef.current
    const chart = chartRef.current
    if (!actualSeries || !predictedSeries || !chart) return

    const n = Math.min(dates.length, actual.length, predicted.length)
    dataRef.current = { dates, actual, predicted }
    if (n === 0) {
      actualSeries.setData([])
      predictedSeries.setData([])
      return
    }

    const actualData = []
    const predictedData = []
    for (let i = 0; i < n; i++) {
      actualData.push({ time: dates[i], value: actual[i] * 100 })
      predictedData.push({ time: dates[i], value: predicted[i] * 100 })
    }

    actualSeries.setData(actualData)
    predictedSeries.setData(predictedData)
    chart.timeScale().fitContent()
  }, [dates, actual, predicted])

  // Обновление маркеров-выбросов
  useEffect(() => {
    const actualSeries = actualRef.current
    if (!actualSeries) return
    if (!markersRef.current) markersRef.current = createSeriesMarkers(actualSeries, [])
    const markers = Array.from(outlierDates).map((d) => ({
      time: d as Time,
      position: 'inBar' as const,
      color: '#e53935',
      shape: 'circle' as const,
    }))
    markersRef.current.setMarkers(markers)
  }, [outlierDates])

  if (dates.length === 0) {
    return <div style={emptyStateStyle}>Нет данных</div>
  }

  return (
    <div style={wrapperStyle}>
      <div ref={containerRef} style={chartContainerStyle} />
      {tooltip && (
        <div style={tooltipPosition(tooltip, containerRef.current)}>
          <div style={tooltipDateStyle}>{tooltip.date}</div>
          <div style={tooltipRowStyle}>
            <span style={tooltipLabelActualStyle}>Факт</span>
            <span style={tooltipValueStyle}>{formatPercent(tooltip.actual)}</span>
          </div>
          <div style={tooltipRowStyle}>
            <span style={tooltipLabelPredictedStyle}>Прогноз</span>
            <span style={tooltipValueStyle}>{formatPercent(tooltip.predicted)}</span>
          </div>
          <div style={tooltipRowStyle}>
            <span style={tooltipLabelDeltaStyle}>Δ</span>
            <span style={tooltipValueStyle}>{formatPercent(tooltip.delta)}</span>
          </div>
        </div>
      )}
    </div>
  )
}

function formatPercent(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

function nearestIndex(dates: string[], target: string): number {
  if (dates.length === 0) return -1
  const targetTs = Date.parse(target)
  if (Number.isNaN(targetTs)) return -1
  let bestIdx = 0
  let bestDiff = Math.abs(Date.parse(dates[0]) - targetTs)
  for (let i = 1; i < dates.length; i++) {
    const diff = Math.abs(Date.parse(dates[i]) - targetTs)
    if (diff < bestDiff) {
      bestDiff = diff
      bestIdx = i
    }
  }
  return bestIdx
}

// lightweight-charts парсит time-строки 'YYYY-MM-DD' как BusinessDay {year, month, day}
// и возвращает их в callback в этом же виде. Приводим обратно к ISO-строке,
// чтобы матчить с массивом dates.
function timeToIsoDate(time: Time): string {
  if (typeof time === 'string') return time
  if (typeof time === 'number') {
    const d = new Date(time * 1000)
    return d.toISOString().slice(0, 10)
  }
  const bd = time as { year: number; month: number; day: number }
  const m = String(bd.month).padStart(2, '0')
  const d = String(bd.day).padStart(2, '0')
  return `${bd.year}-${m}-${d}`
}

const wrapperStyle: React.CSSProperties = {
  position: 'relative',
  width: '100%',
  height: '100%',
}

const chartContainerStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
}

const emptyStateStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#888',
  fontSize: 13,
}

const TOOLTIP_OFFSET = 14
const TOOLTIP_WIDTH = 150
const TOOLTIP_HEIGHT = 78

function tooltipPosition(
  tooltip: TooltipState,
  container: HTMLDivElement | null,
): React.CSSProperties {
  const containerWidth = container?.clientWidth ?? Number.POSITIVE_INFINITY
  const containerHeight = container?.clientHeight ?? Number.POSITIVE_INFINITY
  const placeLeft = tooltip.x + TOOLTIP_OFFSET + TOOLTIP_WIDTH > containerWidth
  const placeAbove = tooltip.y + TOOLTIP_OFFSET + TOOLTIP_HEIGHT > containerHeight
  const left = placeLeft ? tooltip.x - TOOLTIP_OFFSET - TOOLTIP_WIDTH : tooltip.x + TOOLTIP_OFFSET
  const top = placeAbove ? tooltip.y - TOOLTIP_OFFSET - TOOLTIP_HEIGHT : tooltip.y + TOOLTIP_OFFSET
  return { ...tooltipBaseStyle, left, top }
}

const tooltipBaseStyle: React.CSSProperties = {
  position: 'absolute',
  background: 'rgba(255, 255, 255, 0.97)',
  border: '1px solid #d0d0d0',
  borderRadius: 4,
  padding: '6px 10px',
  fontSize: 12,
  fontFamily: 'monospace',
  pointerEvents: 'none',
  boxShadow: '0 2px 6px rgba(0, 0, 0, 0.08)',
  width: TOOLTIP_WIDTH,
  zIndex: 50,
}

const tooltipDateStyle: React.CSSProperties = {
  color: '#888',
  marginBottom: 4,
  fontSize: 11,
}

const tooltipRowStyle: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 12,
  lineHeight: '16px',
}

const tooltipLabelActualStyle: React.CSSProperties = {
  color: '#2962FF',
  fontWeight: 600,
}

const tooltipLabelPredictedStyle: React.CSSProperties = {
  color: '#90A4AE',
}

const tooltipLabelDeltaStyle: React.CSSProperties = {
  color: '#444',
  fontWeight: 600,
}

const tooltipValueStyle: React.CSSProperties = {
  color: '#333',
  fontVariantNumeric: 'tabular-nums',
}
