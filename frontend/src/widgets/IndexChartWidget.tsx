import { useEffect, useId, useRef, useState } from 'react'
import type { SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts'
import { getSeries } from '../api/client'
import type { SeriesName } from '../api/types'
import { type WidgetGroup } from './chartSync'
import { groupRegistry, type ActiveEvent } from './groupRegistry'
import { SyncLeaderButton } from './SyncLeaderButton'
import { useChartCore } from './useChartCore'

interface IndexChartWidgetProps {
  syncGroup: WidgetGroup
}

const SERIES: { value: SeriesName; label: string }[] = [
  { value: 'IMOEX', label: 'IMOEX' },
  { value: 'RUONIA', label: 'RUONIA (% годовых)' },
]

function dateToTs(d: string): UTCTimestamp {
  return (new Date(d).getTime() / 1000) as UTCTimestamp
}

export function IndexChartWidget({ syncGroup }: IndexChartWidgetProps) {
  const widgetId = useId()
  const containerRef = useRef<HTMLDivElement>(null)
  const [series, setSeries] = useState<SeriesName>('IMOEX')
  const [activeEvent, setActiveEvent] = useState<ActiveEvent | null>(null)

  const { chartRef, priceSeriesRef, markersRef } = useChartCore({
    containerRef,
    syncGroup,
    memberId: widgetId,
    withVolume: false,
  })

  // Регистрация в groupRegistry (без тикера — индекс не публикует тикер)
  useEffect(() => {
    groupRegistry.register(widgetId, syncGroup, null)
    return () => groupRegistry.unregister(widgetId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    groupRegistry.setGroup(widgetId, syncGroup)
  }, [syncGroup, widgetId])

  // Загрузка ряда
  useEffect(() => {
    const ps = priceSeriesRef.current
    if (!ps) return
    getSeries(series).then((points) => {
      ps.setData(points.map((p) => ({ time: dateToTs(p.date), value: p.value })))
      chartRef.current?.timeScale().fitContent()
    })
  }, [series, chartRef, priceSeriesRef])

  // Подписка на активное событие группы (без фильтра по тикеру —
  // индекс глобален, нам важна только дата события на оси X)
  useEffect(() => {
    setActiveEvent(groupRegistry.getActiveEvent(syncGroup))
    if (syncGroup === 'none') {
      setActiveEvent(null)
      return
    }
    return groupRegistry.subscribeActiveEvent(syncGroup, setActiveEvent)
  }, [syncGroup])

  // Hover sync (CarChart → crosshair на индексе)
  useEffect(() => {
    if (syncGroup === 'none') return
    return groupRegistry.subscribeHoverDate(syncGroup, (date) => {
      const chart = chartRef.current
      const ps = priceSeriesRef.current
      if (!chart || !ps) return
      if (date === null) {
        chart.clearCrosshairPosition()
        return
      }
      const targetTs = dateToTs(date)
      const data = ps.data() as ReadonlyArray<{ time: Time; value: number }>
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
      chart.setCrosshairPosition(best.value, best.time, ps)
    })
  }, [syncGroup, chartRef, priceSeriesRef])

  // Зум по команде ES
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
  }, [syncGroup, chartRef])

  // Подсветка активного события (без проверки тикера)
  useEffect(() => {
    const api = markersRef.current
    if (!api) return
    if (!activeEvent) {
      api.setMarkers([])
      return
    }
    const t0 = dateToTs(activeEvent.eventDate)
    const dayMs = 86400
    const markers: SeriesMarker<Time>[] = [
      {
        time: t0,
        position: 'aboveBar',
        color: '#e53935',
        shape: 'circle',
        text: `t=0 ${activeEvent.ticker}`,
      },
      {
        time: (t0 - activeEvent.daysBefore * dayMs) as UTCTimestamp,
        position: 'belowBar',
        color: '#e53935',
        shape: 'arrowRight',
        text: `−${activeEvent.daysBefore}`,
      },
      {
        time: (t0 + activeEvent.daysAfter * dayMs) as UTCTimestamp,
        position: 'belowBar',
        color: '#e53935',
        shape: 'arrowLeft',
        text: `+${activeEvent.daysAfter}`,
      },
    ]
    markers.sort((a, b) => {
      const ta = typeof a.time === 'number' ? a.time : 0
      const tb = typeof b.time === 'number' ? b.time : 0
      return ta - tb
    })
    api.setMarkers(markers)
  }, [activeEvent, markersRef])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      <div style={{ marginBottom: 12, flexShrink: 0 }}>
        <label style={{ marginRight: 8, fontSize: 14 }}>Ряд:</label>
        <select
          value={series}
          onChange={(e) => setSeries(e.target.value as SeriesName)}
          style={{ padding: '4px 8px', fontSize: 14 }}
        >
          {SERIES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <SyncLeaderButton group={syncGroup} memberId={widgetId} />
      </div>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, width: '100%' }} />
    </div>
  )
}
