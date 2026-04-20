import { useEffect, useId, useRef, useState } from 'react'
import type { SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts'
import { getSeries } from '../api/client'
import type { SeriesName } from '../api/types'
import { type WidgetGroup } from './chartSync'
import { groupEventBus, selectActiveEvent, useGroupStore } from './groupStore'
import { SyncLeaderButton } from './SyncLeaderButton'
import { dateToTs, useChartCore } from './useChartCore'

interface IndexChartWidgetProps {
  group: WidgetGroup
}

const SERIES: { value: SeriesName; label: string }[] = [
  { value: 'IMOEX', label: 'IMOEX' },
  { value: 'RUONIA', label: 'RUONIA (% годовых)' },
]

export function IndexChartWidget({ group }: IndexChartWidgetProps) {
  const widgetId = useId()
  const containerRef = useRef<HTMLDivElement>(null)
  const [series, setSeries] = useState<SeriesName>('IMOEX')
  const activeEvent = useGroupStore(selectActiveEvent(group))

  const { chartRef, mainSeriesRef, markersRef } = useChartCore({
    containerRef,
    group,
    memberId: widgetId,
    withVolume: false,
  })

  // Загрузка ряда
  useEffect(() => {
    const ps = mainSeriesRef.current
    if (!ps) return
    getSeries(series).then((points) => {
      ps.setData(points.map((p) => ({ time: dateToTs(p.date), value: p.value })))
      chartRef.current?.timeScale().fitContent()
    })
  }, [series, chartRef, mainSeriesRef])

  // Зум по команде ES
  useEffect(() => {
    if (group === 'none') return
    return groupEventBus.subscribe(group, 'zoom', (req) => {
      const chart = chartRef.current
      const series = mainSeriesRef.current
      if (!chart || !series) return
      if ((series.data()?.length ?? 0) === 0) return
      try {
        chart.timeScale().setVisibleRange({
          from: dateToTs(req.from),
          to: dateToTs(req.to),
        })
      } catch { /* range вне данных */ }
    })
  }, [group, chartRef])

  // Подсветка активного события (без проверки тикера)
  useEffect(() => {
    const api = markersRef.current
    if (!api) return
    if (!activeEvent) {
      api.setMarkers([])
      return
    }
    const t0 = dateToTs(activeEvent.eventDate)
    const SECONDS_PER_DAY = 86400
    const markers: SeriesMarker<Time>[] = [
      {
        time: t0,
        position: 'aboveBar',
        color: '#e53935',
        shape: 'circle',
        text: `t=0 ${activeEvent.ticker}`,
      },
      {
        time: (t0 - activeEvent.daysBefore * SECONDS_PER_DAY) as UTCTimestamp,
        position: 'belowBar',
        color: '#e53935',
        shape: 'square',
        text: `−${activeEvent.daysBefore}`,
      },
      {
        time: (t0 + activeEvent.daysAfter * SECONDS_PER_DAY) as UTCTimestamp,
        position: 'belowBar',
        color: '#e53935',
        shape: 'square',
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
    <div style={rootStyle}>
      <div style={toolbarStyle}>
        <label style={labelStyle}>Ряд:</label>
        <select
          value={series}
          onChange={(e) => setSeries(e.target.value as SeriesName)}
          style={seriesSelectStyle}
        >
          {SERIES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        <SyncLeaderButton group={group} memberId={widgetId} />
      </div>
      <div ref={containerRef} style={chartContainerStyle} />
    </div>
  )
}

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
}

const toolbarStyle: React.CSSProperties = {
  marginBottom: 12,
  flexShrink: 0,
}

const labelStyle: React.CSSProperties = {
  marginRight: 8,
  fontSize: 14,
}

const seriesSelectStyle: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 14,
}

const chartContainerStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  width: '100%',
}
