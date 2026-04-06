import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { getPrices, getTickers } from '../api/client'

export function PriceChartWidget() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const priceSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  const [tickers, setTickers] = useState<string[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string>('')

  // Initialize chart once
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#333',
        panes: { separatorColor: '#e0e0e0', separatorHoverColor: '#b0b0b0' },
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      rightPriceScale: { borderColor: '#e0e0e0' },
      timeScale: { borderColor: '#e0e0e0' },
    })

    const priceSeries = chart.addSeries(
      LineSeries,
      { color: '#2962FF', lineWidth: 2, priceLineVisible: false },
      0,
    )
    const volumeSeries = chart.addSeries(
      HistogramSeries,
      {
        color: '#90a4ae',
        priceFormat: { type: 'volume' },
        priceLineVisible: false,
      },
      1,
    )

    chartRef.current = chart
    priceSeriesRef.current = priceSeries
    volumeSeriesRef.current = volumeSeries

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    })
    resizeObserver.observe(container)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
      priceSeriesRef.current = null
      volumeSeriesRef.current = null
    }
  }, [])

  // Load tickers list
  useEffect(() => {
    getTickers().then((ts) => {
      setTickers(ts)
      if (ts.length > 0) setSelectedTicker(ts[0])
    })
  }, [])

  // Load prices when ticker changes
  useEffect(() => {
    if (!selectedTicker) return
    if (!priceSeriesRef.current || !volumeSeriesRef.current) return

    getPrices(selectedTicker).then((candles) => {
      const priceData = candles.map((c) => ({
        time: (new Date(c.date).getTime() / 1000) as UTCTimestamp,
        value: c.close,
      }))
      const volumeData = candles.map((c) => ({
        time: (new Date(c.date).getTime() / 1000) as UTCTimestamp,
        value: c.volume,
        color: '#90a4ae80',
      }))
      priceSeriesRef.current!.setData(priceData)
      volumeSeriesRef.current!.setData(volumeData)
      chartRef.current?.timeScale().fitContent()
    })
  }, [selectedTicker])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div style={{ marginBottom: 12, flexShrink: 0 }}>
        <label style={{ marginRight: 8, fontSize: 14 }}>Тикер:</label>
        <select
          value={selectedTicker}
          onChange={(e) => setSelectedTicker(e.target.value)}
          style={{ padding: '4px 8px', fontSize: 14 }}
        >
          {tickers.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, width: '100%' }} />
    </div>
  )
}
