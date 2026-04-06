import { useEffect, useRef } from 'react'
import {
  createChart,
  createSeriesMarkers,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import type { EventStudyResult } from '../api/types'

interface CarChartProps {
  result: EventStudyResult
  daysBefore: number
  daysAfter: number
}

// База для синтетических timestamp'ов: 2000-01-01. Каждый t = базе + i*86400.
// Lightweight Charts работает с временной шкалой, поэтому используем фиктивные
// даты, а формат тика переопределяем через localization.timeFormatter.
const BASE_TS = 946684800 // 2000-01-01 00:00:00 UTC

function indexToTime(i: number): UTCTimestamp {
  return (BASE_TS + i * 86400) as UTCTimestamp
}

export function CarChart({ result, daysBefore, daysAfter }: CarChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const carRef = useRef<ISeriesApi<'Line'> | null>(null)
  const upperRef = useRef<ISeriesApi<'Line'> | null>(null)
  const lowerRef = useRef<ISeriesApi<'Line'> | null>(null)
  const zeroRef = useRef<ISeriesApi<'Line'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)

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
        fixLeftEdge: true,
        fixRightEdge: true,
        tickMarkFormatter: (time: number) => {
          const t = Math.round((time - BASE_TS) / 86400)
          return t > 0 ? `+${t}` : `${t}`
        },
      },
      localization: {
        timeFormatter: (time: number) => {
          const t = Math.round((time - BASE_TS) / 86400)
          return `t=${t > 0 ? '+' : ''}${t}`
        },
      },
      crosshair: { mode: 0 },
    })

    // CI и нулевая линия не должны влиять на autoscale,
    // иначе CAR прижимается к нулю на фоне раздувшегося доверительного интервала
    const ignoreAutoscale = { autoscaleInfoProvider: () => null }

    upperRef.current = chart.addSeries(LineSeries, {
      color: '#90caf9',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      ...ignoreAutoscale,
    })
    lowerRef.current = chart.addSeries(LineSeries, {
      color: '#90caf9',
      lineWidth: 1,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: false,
      lastValueVisible: false,
      ...ignoreAutoscale,
    })
    zeroRef.current = chart.addSeries(LineSeries, {
      color: '#bbbbbb',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      ...ignoreAutoscale,
    })
    carRef.current = chart.addSeries(LineSeries, {
      color: '#2962FF',
      lineWidth: 2,
      priceLineVisible: false,
      priceFormat: {
        type: 'custom',
        formatter: (p: number) => `${p.toFixed(2)}%`,
        minMove: 0.01,
      },
    })

    chartRef.current = chart

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
      carRef.current = null
      upperRef.current = null
      lowerRef.current = null
      zeroRef.current = null
      markersRef.current = null
    }
  }, [])

  // Update data when result changes
  useEffect(() => {
    const car = carRef.current
    const upper = upperRef.current
    const lower = lowerRef.current
    const zero = zeroRef.current
    const chart = chartRef.current
    if (!car || !upper || !lower || !zero || !chart) return

    const ar = result.ar
    const n = ar.length
    if (n === 0) return

    // CAR[i] = sum(ar[0..i]), значения в процентах для удобства восприятия
    const carValues: number[] = []
    let acc = 0
    for (let i = 0; i < n; i++) {
      acc += ar[i]
      carValues.push(acc * 100)
    }

    // Ось t: -daysBefore..+daysAfter, длина n. Если n != daysBefore+daysAfter+1
    // (например, выходные/праздники в окне), всё равно центрируем по 0.
    const totalRequested = daysBefore + daysAfter + 1
    const tStart = n === totalRequested ? -daysBefore : -Math.floor(n / 2)

    // CI: ±2 * std * sqrt(k), в процентах
    const std = result.estimation_std * 100
    const carData = []
    const upperData = []
    const lowerData = []
    for (let i = 0; i < n; i++) {
      const time = indexToTime(tStart + i)
      const k = i + 1
      const band = 2 * std * Math.sqrt(k)
      carData.push({ time, value: carValues[i] })
      upperData.push({ time, value: band })
      lowerData.push({ time, value: -band })
    }

    car.setData(carData)
    upper.setData(upperData)
    lower.setData(lowerData)

    // Горизонтальная нулевая линия по всему окну
    zero.setData([
      { time: indexToTime(tStart), value: 0 },
      { time: indexToTime(tStart + n - 1), value: 0 },
    ])

    // Маркер t=0 на CAR серии
    const zeroIdx = -tStart
    if (zeroIdx >= 0 && zeroIdx < n) {
      if (!markersRef.current) {
        markersRef.current = createSeriesMarkers(car, [])
      }
      markersRef.current.setMarkers([
        {
          time: indexToTime(0),
          position: 'inBar',
          color: '#e53935',
          shape: 'circle',
          text: 't=0',
        },
      ])
    }

    chart.timeScale().fitContent()
  }, [result, daysBefore, daysAfter])

  return <div ref={containerRef} style={{ flex: 1, minHeight: 0, width: '100%' }} />
}
