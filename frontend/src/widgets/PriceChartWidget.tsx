import { useEffect, useId, useRef, useState } from 'react'
import {
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { getEvents, getPrices, getTickers } from '../api/client'
import type { DividendEvent } from '../api/types'
import { priceChartSyncBus, type SyncGroup } from './chartSync'
import { groupRegistry, type ActiveEvent } from './groupRegistry'

function dateToTs(d: string): UTCTimestamp {
  return (new Date(d).getTime() / 1000) as UTCTimestamp
}

interface PriceChartWidgetProps {
  syncGroup: SyncGroup
}

export function PriceChartWidget({ syncGroup }: PriceChartWidgetProps) {
  const widgetId = useId()
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const priceSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const setGroupRef = useRef<((g: SyncGroup) => void) | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const eventsRef = useRef<DividendEvent[]>([])
  const activeEventRef = useRef<ActiveEvent | null>(null)
  const syncGroupRef = useRef<SyncGroup>(syncGroup)

  const [tickers, setTickers] = useState<string[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string>('')
  const [events, setEvents] = useState<DividendEvent[]>([])
  const [activeEvent, setActiveEvent] = useState<ActiveEvent | null>(null)

  // refs для использования внутри chart.subscribeClick (чтобы не пере-подписываться)
  useEffect(() => {
    eventsRef.current = events
  }, [events])
  useEffect(() => {
    activeEventRef.current = activeEvent
  }, [activeEvent])
  useEffect(() => {
    syncGroupRef.current = syncGroup
  }, [syncGroup])

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
      timeScale: {
        borderColor: '#e0e0e0',
        fixLeftEdge: true,
        fixRightEdge: true,
      },
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
    markersRef.current = createSeriesMarkers(priceSeries, [])

    // Клик по графику: если рядом с маркером события — публикуем выбор в группу
    const onClick = (param: MouseEventParams) => {
      if (param.time === undefined) return
      const group = syncGroupRef.current
      if (group === 'none') return
      const evs = eventsRef.current
      if (evs.length === 0) return
      const clickedTs = typeof param.time === 'number' ? param.time : 0
      // Ищем ближайшее событие в пределах 2 дней
      let best: DividendEvent | null = null
      let bestDiff = Infinity
      for (const ev of evs) {
        const diff = Math.abs(dateToTs(ev.event_date) - clickedTs)
        if (diff < bestDiff) {
          bestDiff = diff
          best = ev
        }
      }
      if (best && bestDiff <= 2 * 86400) {
        groupRegistry.requestSelectEvent(group, {
          ticker: best.ticker,
          event_date: best.event_date,
        })
      }
    }
    chart.subscribeClick(onClick)

    const resizeObserver = new ResizeObserver(() => {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    })
    resizeObserver.observe(container)

    const { setGroup, unregister } = priceChartSyncBus.register(
      chart,
      priceSeries,
      syncGroup,
    )
    setGroupRef.current = setGroup

    return () => {
      chart.unsubscribeClick(onClick)
      unregister()
      setGroupRef.current = null
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
      priceSeriesRef.current = null
      volumeSeriesRef.current = null
      markersRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Update group when prop changes
  useEffect(() => {
    setGroupRef.current?.(syncGroup)
    groupRegistry.setGroup(widgetId, syncGroup)
  }, [syncGroup, widgetId])

  // Register/unregister in groupRegistry (для фильтра тикеров в Event Study)
  useEffect(() => {
    groupRegistry.register(widgetId, syncGroup, null)
    return () => groupRegistry.unregister(widgetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Push current ticker into registry
  useEffect(() => {
    groupRegistry.setTicker(widgetId, selectedTicker || null)
  }, [selectedTicker, widgetId])

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
        time: dateToTs(c.date),
        value: c.close,
      }))
      const volumeData = candles.map((c) => ({
        time: dateToTs(c.date),
        value: c.volume,
        color: '#90a4ae80',
      }))
      priceSeriesRef.current!.setData(priceData)
      volumeSeriesRef.current!.setData(volumeData)
      chartRef.current?.timeScale().fitContent()
    })
  }, [selectedTicker])

  // Load dividend events for current ticker
  useEffect(() => {
    if (!selectedTicker) {
      setEvents([])
      return
    }
    getEvents({ ticker: selectedTicker }).then(setEvents)
  }, [selectedTicker])

  // Подписка на активное событие группы
  useEffect(() => {
    setActiveEvent(groupRegistry.getActiveEvent(syncGroup))
    if (syncGroup === 'none') {
      setActiveEvent(null)
      return
    }
    return groupRegistry.subscribeActiveEvent(syncGroup, setActiveEvent)
  }, [syncGroup])

  // Подписка на zoom-команды от Event Study
  useEffect(() => {
    if (syncGroup === 'none') return
    return groupRegistry.subscribeZoom(syncGroup, (req) => {
      const chart = chartRef.current
      if (!chart) return
      chart.timeScale().setVisibleRange({
        from: dateToTs(req.from),
        to: dateToTs(req.to),
      })
    })
  }, [syncGroup])

  // Перерисовка маркеров: все события + подсветка активного
  useEffect(() => {
    const markersApi = markersRef.current
    if (!markersApi) return

    const markers: SeriesMarker<Time>[] = []

    // Все дивидендные события — маленькие серые треугольники снизу
    for (const ev of events) {
      markers.push({
        time: dateToTs(ev.event_date),
        position: 'belowBar',
        color: '#9e9e9e',
        shape: 'arrowUp',
      })
    }

    // Подсветка активного события (если тикер совпадает с нашим)
    if (activeEvent && activeEvent.ticker === selectedTicker) {
      const t0 = dateToTs(activeEvent.event_date)
      const dayMs = 86400
      // Маркер t=0 (жирный красный)
      markers.push({
        time: t0,
        position: 'aboveBar',
        color: '#e53935',
        shape: 'circle',
        text: 't=0',
      })
      // Границы окна (приближённо в календарных днях; биржевых может быть меньше)
      const tFrom = (t0 - activeEvent.daysBefore * dayMs) as UTCTimestamp
      const tTo = (t0 + activeEvent.daysAfter * dayMs) as UTCTimestamp
      markers.push({
        time: tFrom,
        position: 'belowBar',
        color: '#e53935',
        shape: 'arrowRight',
        text: `−${activeEvent.daysBefore}`,
      })
      markers.push({
        time: tTo,
        position: 'belowBar',
        color: '#e53935',
        shape: 'arrowLeft',
        text: `+${activeEvent.daysAfter}`,
      })
    }

    // Сортировка по времени — обязательное требование плагина маркеров
    markers.sort((a, b) => {
      const ta = typeof a.time === 'number' ? a.time : 0
      const tb = typeof b.time === 'number' ? b.time : 0
      return ta - tb
    })

    markersApi.setMarkers(markers)
  }, [events, activeEvent, selectedTicker])

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
