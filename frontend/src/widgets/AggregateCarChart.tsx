import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { AggregateStudyResult } from '../api/types'

interface AggregateCarChartProps {
  result: AggregateStudyResult
  daysBefore: number
  daysAfter: number
}

const BASE_TS = 946684800
const SECONDS_PER_DAY = 86400

function indexToTime(i: number): UTCTimestamp {
  return (BASE_TS + i * SECONDS_PER_DAY) as UTCTimestamp
}

type TrustLevel = 'reliable' | 'weak' | 'unreliable'

function getTrustLevel(pValue: number, nEvents: number): TrustLevel {
  if (nEvents < 3) return 'unreliable'
  if (pValue < 0.05) return 'reliable'
  if (pValue < 0.10) return 'weak'
  return 'unreliable'
}

const TRUST_CONFIG: Record<TrustLevel, { label: string; color: string; bg: string }> = {
  reliable:   { label: 'Надёжный',       color: '#2e7d32', bg: '#e8f5e9' },
  weak:       { label: 'Слабый сигнал',  color: '#e65100', bg: '#fff3e0' },
  unreliable: { label: 'Ненадёжный',     color: '#888',    bg: '#f5f5f5' },
}

export function AggregateCarChart({ result, daysBefore, daysAfter }: AggregateCarChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const meanRef = useRef<ISeriesApi<'Line'> | null>(null)
  const zeroRef = useRef<ISeriesApi<'Line'> | null>(null)

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
        fixLeftEdge: true,
        fixRightEdge: true,
        tickMarkFormatter: (time: number) => {
          const t = Math.round((time - BASE_TS) / SECONDS_PER_DAY)
          return t > 0 ? `+${t}` : `${t}`
        },
      },
      localization: {
        timeFormatter: (time: number) => {
          const t = Math.round((time - BASE_TS) / SECONDS_PER_DAY)
          return `t=${t > 0 ? '+' : ''}${t}`
        },
      },
      crosshair: { mode: 0 },
    })

    chartRef.current = chart

    const ignoreAutoscale = { autoscaleInfoProvider: () => null }

    zeroRef.current = chart.addSeries(LineSeries, {
      color: '#bbbbbb',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      ...ignoreAutoscale,
    })

    meanRef.current = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 3,
      priceLineVisible: false,
      priceFormat: {
        type: 'custom',
        formatter: (p: number) => `${p.toFixed(2)}%`,
        minMove: 0.01,
      },
    })

    const ro = new ResizeObserver(() => {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    })
    ro.observe(container)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      meanRef.current = null
      zeroRef.current = null
    }
  }, [])

  useEffect(() => {
    const chart = chartRef.current
    const mean = meanRef.current
    const zero = zeroRef.current
    if (!chart || !mean || !zero) return

    const n = result.meanCar.length
    if (n === 0) return

    const totalRequested = daysBefore + daysAfter + 1
    const tStart = n === totalRequested ? -daysBefore : -Math.floor(n / 2)

    const meanData = result.meanCar.map((v, i) => ({
      time: indexToTime(tStart + i),
      value: v * 100,
    }))

    mean.setData(meanData)

    zero.setData([
      { time: indexToTime(tStart), value: 0 },
      { time: indexToTime(tStart + n - 1), value: 0 },
    ])

    chart.timeScale().fitContent()
  }, [result, daysBefore, daysAfter])

  const trust = getTrustLevel(result.pValue, result.nEvents)
  const cfg = TRUST_CONFIG[trust]
  const carPct = (result.cumulativeMeanCar * 100).toFixed(2)

  return (
    <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div style={{
        display: 'flex',
        gap: 10,
        padding: '4px 8px',
        fontSize: 12,
        color: '#555',
        alignItems: 'center',
        flexWrap: 'wrap',
      }}>
        <span>
          Событий: <b>{result.nEvents}</b>
        </span>
        <span>
          Средний CAR:{' '}
          <b style={{ color: result.cumulativeMeanCar >= 0 ? '#2e7d32' : '#c62828' }}>
            {result.cumulativeMeanCar >= 0 ? '+' : ''}{carPct}%
          </b>
        </span>
        <TrustIndicator trust={trust} config={cfg} result={result} />
        <HelpBadge />
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, width: '100%' }} />
    </div>
  )
}

function TrustIndicator({
  trust,
  config,
  result,
}: {
  trust: TrustLevel
  config: { label: string; color: string; bg: string }
  result: AggregateStudyResult
}) {
  const [showTooltip, setShowTooltip] = useState(false)

  const pStr = result.pValue < 0.001 ? '<0.001' : result.pValue.toFixed(3)

  return (
    <span
      style={{ position: 'relative', display: 'inline-flex', alignItems: 'center' }}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <span style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 10,
        fontSize: 11,
        fontWeight: 600,
        background: config.bg,
        color: config.color,
        cursor: 'default',
      }}>
        {config.label}
      </span>

      {showTooltip && (
        <div style={{
          position: 'absolute',
          bottom: '100%',
          left: '50%',
          transform: 'translateX(-50%)',
          marginBottom: 6,
          background: '#333',
          color: '#fff',
          padding: '8px 12px',
          borderRadius: 6,
          fontSize: 12,
          lineHeight: 1.5,
          whiteSpace: 'nowrap',
          zIndex: 100,
          boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
        }}>
          <div>t-stat: <b>{result.tStat.toFixed(2)}</b></div>
          <div>p-value: <b>{pStr}</b></div>
          <div style={{ marginTop: 4, borderTop: '1px solid #555', paddingTop: 4, color: '#ccc' }}>
            p {'<'} 0.05 = надёжный{' '}
            {trust === 'reliable' && '\u2714'}
          </div>
          <div style={{ color: '#ccc' }}>
            p {'<'} 0.10 = слабый сигнал{' '}
            {trust === 'weak' && '\u2714'}
          </div>
          <div style={{ color: '#ccc' }}>
            p {'\u2265'} 0.10 = ненадёжный{' '}
            {trust === 'unreliable' && '\u2714'}
          </div>
        </div>
      )}
    </span>
  )
}

function HelpBadge() {
  const [show, setShow] = useState(false)
  return (
    <span
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <span style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 18,
        height: 18,
        borderRadius: '50%',
        border: '1px solid #ccc',
        fontSize: 11,
        color: '#999',
        cursor: 'default',
      }}>
        ?
      </span>
      {show && (
        <div style={{
          position: 'absolute',
          bottom: '100%',
          right: 0,
          marginBottom: 6,
          background: '#333',
          color: '#fff',
          padding: '8px 12px',
          borderRadius: 6,
          fontSize: 12,
          lineHeight: 1.5,
          width: 260,
          zIndex: 100,
          boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
        }}>
          <b>Агрегированный CAR</b> — средняя кумулятивная
          аномальная доходность по всем дивидендным событиям
          тикера. Показывает, реагирует ли акция на дивиденды
          в принципе. Индикатор доверия основан на
          статистическом тесте (t-test): чем больше событий
          и чем стабильнее эффект — тем надёжнее результат.
        </div>
      )}
    </span>
  )
}
