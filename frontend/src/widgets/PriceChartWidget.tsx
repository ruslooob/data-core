import { useEffect, useId, useRef, useState } from 'react'
import type { MouseEventParams, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts'
import { getEvents, getPrices, getTickers } from '../api/client'
import type { DividendEvent } from '../api/types'
import { chartSyncBus, type WidgetGroup } from './chartSync'
import { groupRegistry, type ActiveEvent } from './groupRegistry'
import { SyncLeaderButton } from './SyncLeaderButton'
import { useChartCore } from './useChartCore'

interface PriceChartWidgetProps {
  group: WidgetGroup
}

function dateToTs(d: string): UTCTimestamp {
  return (new Date(d).getTime() / 1000) as UTCTimestamp
}

export function PriceChartWidget({ group }: PriceChartWidgetProps) {
  const widgetId = useId()
  const containerRef = useRef<HTMLDivElement>(null)

  const [tickers, setTickers] = useState<string[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string>('')
  const [events, setEvents] = useState<DividendEvent[]>([])
  const [activeEvent, setActiveEvent] = useState<ActiveEvent | null>(null)
  const [isLeader, setIsLeader] = useState<boolean>(
    () => groupRegistry.getLeader(group) === widgetId,
  )
  const [showEvents, setShowEvents] = useState<boolean>(() =>
    groupRegistry.getShowEvents(group),
  )
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)

  // refs для click-handler'а из useChartCore (без пере-подписки)
  const eventsRef = useRef<DividendEvent[]>([])
  const groupRef = useRef<WidgetGroup>(group)
  useEffect(() => {
    eventsRef.current = events
  }, [events])
  useEffect(() => {
    groupRef.current = group
  }, [group])

  // Клик по бару → ищем ближайшее событие в ±2 дня → publish select
  const handleBarClick = (clickedTs: number) => {
    const currentGroup = groupRef.current
    if (currentGroup === 'none') return
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
      groupRegistry.requestSelectEvent(currentGroup, {
        ticker: best.ticker,
        eventDate: best.eventDate,
      })
    }
  }

  const { chartRef, mainSeriesRef, volumeSeriesRef, markersRef } = useChartCore({
    containerRef,
    group,
    memberId: widgetId,
    withVolume: true,
    onBarClick: handleBarClick,
  })

  // ── Регистрация в groupRegistry как член группы ──
  useEffect(() => {
    groupRegistry.register(widgetId, group, null)
    return () => groupRegistry.unregister(widgetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    groupRegistry.setGroup(widgetId, group)
  }, [group, widgetId])

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
    if (!mainSeriesRef.current || !volumeSeriesRef.current) return

    getPrices(selectedTicker).then((candles) => {
      const priceData = candles.map((c) => ({ time: dateToTs(c.date), value: c.close }))
      const volumeData = candles.map((c) => ({
        time: dateToTs(c.date),
        value: c.volume,
        color: '#90a4ae80',
      }))
      mainSeriesRef.current!.setData(priceData)
      volumeSeriesRef.current!.setData(volumeData)
      chartRef.current?.timeScale().fitContent()
    })
  }, [selectedTicker, chartRef, mainSeriesRef, volumeSeriesRef])

  // ── Подписка на состояние лидера группы ──
  useEffect(() => {
    setIsLeader(groupRegistry.getLeader(group) === widgetId)
    if (group === 'none') {
      setIsLeader(false)
      return
    }
    return groupRegistry.subscribeLeader(group, (leaderId) => {
      setIsLeader(leaderId === widgetId)
    })
  }, [group, widgetId])

  // ── Подписка на group-level «показывать события» ──
  useEffect(() => {
    setShowEvents(groupRegistry.getShowEvents(group))
    if (group === 'none') {
      setShowEvents(false)
      return
    }
    return groupRegistry.subscribeShowEvents(group, setShowEvents)
  }, [group])

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
    setActiveEvent(groupRegistry.getActiveEvent(group))
    if (group === 'none') {
      setActiveEvent(null)
      return
    }
    return groupRegistry.subscribeActiveEvent(group, setActiveEvent)
  }, [group])

  useEffect(() => {
    if (group === 'none') return
    return groupRegistry.subscribeHoverDate(group, (date) => {
      const chart = chartRef.current
      const series = mainSeriesRef.current
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
  }, [group, chartRef, mainSeriesRef])

  useEffect(() => {
    if (group === 'none') return
    return groupRegistry.subscribeZoom(group, (req) => {
      const chart = chartRef.current
      if (!chart) return
      // Помечаем chart, чтобы chartSync не пропагировал получившееся range-change
      // событие соседним price chart'ам как эхо (и не «затёр» их свежий зум).
      chartSyncBus.markApplied(chart)
      chart.timeScale().setVisibleRange({
        from: dateToTs(req.from),
        to: dateToTs(req.to),
      })
    })
  }, [group, chartRef])

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
      const SECONDS_PER_DAY = 86400
      markers.push({
        time: t0,
        position: 'aboveBar',
        color: '#e53935',
        shape: 'circle',
        text: 't=0',
      })
      const tFrom = (t0 - activeEvent.daysBefore * SECONDS_PER_DAY) as UTCTimestamp
      const tTo = (t0 + activeEvent.daysAfter * SECONDS_PER_DAY) as UTCTimestamp
      markers.push({
        time: tFrom,
        position: 'belowBar',
        color: '#e53935',
        shape: 'square',
        text: `−${activeEvent.daysBefore}`,
      })
      markers.push({
        time: tTo,
        position: 'belowBar',
        color: '#e53935',
        shape: 'square',
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
        <SyncLeaderButton group={group} memberId={widgetId} />
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
