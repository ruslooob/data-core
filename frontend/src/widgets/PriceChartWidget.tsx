import { useEffect, useId, useRef, useState } from 'react'
import type { MouseEventParams, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts'
import { getEvents, getPrices, getTickers } from '../api/client'
import type { DividendEvent } from '../api/types'
import { priceChartSyncBus, type SyncGroup } from './chartSync'
import { groupRegistry, type ActiveEvent } from './groupRegistry'
import { SyncLeaderButton } from './SyncLeaderButton'
import { useChartCore } from './useChartCore'

interface PriceChartWidgetProps {
  syncGroup: SyncGroup
}

function dateToTs(d: string): UTCTimestamp {
  return (new Date(d).getTime() / 1000) as UTCTimestamp
}

export function PriceChartWidget({ syncGroup }: PriceChartWidgetProps) {
  const widgetId = useId()
  const containerRef = useRef<HTMLDivElement>(null)

  const [tickers, setTickers] = useState<string[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string>('')
  const [events, setEvents] = useState<DividendEvent[]>([])
  const [activeEvent, setActiveEvent] = useState<ActiveEvent | null>(null)
  const [isLeader, setIsLeader] = useState<boolean>(
    () => groupRegistry.getLeader(syncGroup) === widgetId,
  )
  const [showEvents, setShowEvents] = useState<boolean>(() =>
    groupRegistry.getShowEvents(syncGroup),
  )
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)

  // refs для click-handler'а из useChartCore (без пере-подписки)
  const eventsRef = useRef<DividendEvent[]>([])
  const syncGroupRef = useRef<SyncGroup>(syncGroup)
  useEffect(() => {
    eventsRef.current = events
  }, [events])
  useEffect(() => {
    syncGroupRef.current = syncGroup
  }, [syncGroup])

  // Клик по бару → ищем ближайшее событие в ±2 дня → publish select
  const handleBarClick = (clickedTs: number) => {
    const group = syncGroupRef.current
    if (group === 'none') return
    const evs = eventsRef.current
    if (evs.length === 0) return
    let best: DividendEvent | null = null
    let bestDiff = Infinity
    for (const ev of evs) {
      const diff = Math.abs(dateToTs(ev.eventDate) - clickedTs)
      if (diff < bestDiff) {
        bestDiff = diff
        best = ev
      }
    }
    if (best && bestDiff <= 2 * 86400) {
      groupRegistry.requestSelectEvent(group, {
        ticker: best.ticker,
        eventDate: best.eventDate,
      })
    }
  }

  const { chartRef, priceSeriesRef, volumeSeriesRef, markersRef } = useChartCore({
    containerRef,
    syncGroup,
    memberId: widgetId,
    withVolume: true,
    onBarClick: handleBarClick,
  })

  // ── groupRegistry: регистрация члена группы (тикер) ──
  useEffect(() => {
    groupRegistry.register(widgetId, syncGroup, null)
    return () => groupRegistry.unregister(widgetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    groupRegistry.setGroup(widgetId, syncGroup)
  }, [syncGroup, widgetId])

  useEffect(() => {
    groupRegistry.setTicker(widgetId, selectedTicker || null)
  }, [selectedTicker, widgetId])

  // ── Загрузка списка тикеров и котировок ──
  useEffect(() => {
    getTickers().then((ts) => {
      setTickers(ts)
      if (ts.length > 0) setSelectedTicker(ts[0])
    })
  }, [])

  useEffect(() => {
    if (!selectedTicker) return
    if (!priceSeriesRef.current || !volumeSeriesRef.current) return

    getPrices(selectedTicker).then((candles) => {
      const priceData = candles.map((c) => ({ time: dateToTs(c.date), value: c.close }))
      const volumeData = candles.map((c) => ({
        time: dateToTs(c.date),
        value: c.volume,
        color: '#90a4ae80',
      }))
      priceSeriesRef.current!.setData(priceData)
      volumeSeriesRef.current!.setData(volumeData)
      chartRef.current?.timeScale().fitContent()
    })
  }, [selectedTicker, chartRef, priceSeriesRef, volumeSeriesRef])

  // ── Подписка на состояние лидера группы ──
  useEffect(() => {
    setIsLeader(groupRegistry.getLeader(syncGroup) === widgetId)
    if (syncGroup === 'none') {
      setIsLeader(false)
      return
    }
    return groupRegistry.subscribeLeader(syncGroup, (leaderId) => {
      setIsLeader(leaderId === widgetId)
    })
  }, [syncGroup, widgetId])

  // ── Подписка на group-level «показывать события» ──
  useEffect(() => {
    setShowEvents(groupRegistry.getShowEvents(syncGroup))
    if (syncGroup === 'none') {
      setShowEvents(false)
      return
    }
    return groupRegistry.subscribeShowEvents(syncGroup, setShowEvents)
  }, [syncGroup])

  // ── Дивидендные события: только если этот график — ведущий И «глазик» включён ──
  useEffect(() => {
    if (!isLeader || !showEvents || !selectedTicker) {
      setEvents([])
      return
    }
    getEvents({ ticker: selectedTicker }).then(setEvents)
  }, [isLeader, showEvents, selectedTicker])

  // ── Подписки на канал группы ──
  useEffect(() => {
    setActiveEvent(groupRegistry.getActiveEvent(syncGroup))
    if (syncGroup === 'none') {
      setActiveEvent(null)
      return
    }
    return groupRegistry.subscribeActiveEvent(syncGroup, setActiveEvent)
  }, [syncGroup])

  useEffect(() => {
    if (syncGroup === 'none') return
    return groupRegistry.subscribeHoverDate(syncGroup, (date) => {
      const chart = chartRef.current
      const series = priceSeriesRef.current
      if (!chart || !series) return
      if (date === null) {
        chart.clearCrosshairPosition()
        return
      }
      const targetTs = dateToTs(date)
      const data = series.data() as ReadonlyArray<{ time: Time; value: number }>
      if (data.length === 0) return
      let best = data[0]
      let bestDiff = Math.abs((typeof best.time === 'number' ? best.time : 0) - targetTs)
      for (let i = 1; i < data.length; i++) {
        const t = typeof data[i].time === 'number' ? (data[i].time as number) : 0
        const diff = Math.abs(t - targetTs)
        if (diff < bestDiff) {
          best = data[i]
          bestDiff = diff
        }
      }
      chart.setCrosshairPosition(best.value, best.time, series)
    })
  }, [syncGroup, chartRef, priceSeriesRef])

  useEffect(() => {
    if (syncGroup === 'none') return
    return groupRegistry.subscribeZoom(syncGroup, (req) => {
      const chart = chartRef.current
      if (!chart) return
      // Помечаем chart, чтобы chartSync не пропагировал получившееся range-change
      // событие соседним price chart'ам как эхо (и не «затёр» их свежий зум).
      priceChartSyncBus.markApplied(chart)
      chart.timeScale().setVisibleRange({
        from: dateToTs(req.from),
        to: dateToTs(req.to),
      })
    })
  }, [syncGroup, chartRef])

  // ── Tooltip + cursor pointer на маркере события ──
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    const onMove = (param: MouseEventParams) => {
      if (param.time === undefined || !param.point) {
        setTooltip(null)
        return
      }
      const targetTs = typeof param.time === 'number' ? param.time : 0
      const evs = eventsRef.current
      let best: DividendEvent | null = null
      let bestDiff = Infinity
      for (const ev of evs) {
        const diff = Math.abs(dateToTs(ev.eventDate) - targetTs)
        if (diff < bestDiff) {
          bestDiff = diff
          best = ev
        }
      }
      if (best && bestDiff <= 2 * 86400) {
        setTooltip({
          x: param.point.x,
          y: param.point.y,
          text: `${best.eventDate} — ${best.dividend.toFixed(2)} ₽`,
        })
      } else {
        setTooltip(null)
      }
    }
    chart.subscribeCrosshairMove(onMove)
    return () => chart.unsubscribeCrosshairMove(onMove)
  }, [chartRef])

  // ── Маркеры: все дивиденды + подсветка активного события ──
  useEffect(() => {
    const markersApi = markersRef.current
    if (!markersApi) return

    const markers: SeriesMarker<Time>[] = []
    for (const ev of events) {
      markers.push({
        time: dateToTs(ev.eventDate),
        position: 'belowBar',
        color: '#9e9e9e',
        shape: 'arrowUp',
      })
    }

    if (activeEvent && isLeader && activeEvent.ticker === selectedTicker) {
      const t0 = dateToTs(activeEvent.eventDate)
      const dayMs = 86400
      markers.push({
        time: t0,
        position: 'aboveBar',
        color: '#e53935',
        shape: 'circle',
        text: 't=0',
      })
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

    markers.sort((a, b) => {
      const ta = typeof a.time === 'number' ? a.time : 0
      const tb = typeof b.time === 'number' ? b.time : 0
      return ta - tb
    })

    markersApi.setMarkers(markers)
  }, [events, activeEvent, selectedTicker, markersRef, isLeader])

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
        <SyncLeaderButton group={syncGroup} memberId={widgetId} />
      </div>
      <div style={{ position: 'relative', flex: 1, minHeight: 0, width: '100%' }}>
        <div
          ref={containerRef}
          style={{
            width: '100%',
            height: '100%',
            cursor: tooltip ? 'pointer' : 'crosshair',
          }}
        />
        {tooltip && (
          <div
            style={{
              position: 'absolute',
              left: tooltip.x + 14,
              top: tooltip.y + 14,
              padding: '4px 8px',
              background: 'rgba(33, 33, 33, 0.92)',
              color: '#fff',
              fontSize: 12,
              borderRadius: 4,
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
              zIndex: 5,
              boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
            }}
          >
            {tooltip.text}
          </div>
        )}
      </div>
    </div>
  )
}
