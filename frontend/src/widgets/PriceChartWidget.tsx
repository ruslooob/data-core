import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { MouseEventParams, SeriesMarker, Time, UTCTimestamp } from 'lightweight-charts'
import { getEvents, getPrices, getTickers } from '../api/client'
import { chartSyncBus, type WidgetGroup } from './chartSync'
import type { DividendEvent } from '../api/types'
import {
  groupEventBus,
  selectActiveEvent,
  selectIsLeader,
  selectShowEvents,
  useGroupStore,
} from './groupStore'
import { SyncLeaderButton } from './SyncLeaderButton'
import { dateToTs, useChartCore } from './useChartCore'

interface PriceChartWidgetProps {
  group: WidgetGroup
}

export function PriceChartWidget({ group }: PriceChartWidgetProps) {
  const widgetId = useId()
  const containerRef = useRef<HTMLDivElement>(null)

  const [tickers, setTickers] = useState<string[]>([])
  const [selectedTicker, setSelectedTicker] = useState<string>('')
  const [events, setEvents] = useState<DividendEvent[]>([])
  const [tooltip, setTooltip] = useState<{ x: number; y: number; text: string } | null>(null)

  // Подписки на стор группы — авто-перерендер только на изменения нужных значений
  const isLeader = useGroupStore(selectIsLeader(group, widgetId))
  const showEvents = useGroupStore(selectShowEvents(group))
  const activeEvent = useGroupStore(selectActiveEvent(group))

  // refs для click-handler'а из useChartCore (без пере-подписки)
  const eventsRef = useRef<DividendEvent[]>([])
  const groupRef = useRef<WidgetGroup>(group)
  const showEventsRef = useRef<boolean>(showEvents)
  const isLeaderRef = useRef<boolean>(isLeader)
  useEffect(() => {
    eventsRef.current = events
  }, [events])
  useEffect(() => {
    groupRef.current = group
  }, [group])
  useEffect(() => {
    showEventsRef.current = showEvents
  }, [showEvents])
  useEffect(() => {
    isLeaderRef.current = isLeader
  }, [isLeader])

  // Клик по бару → ищем ближайшее событие в ±2 дня → publish select.
  // Срабатывает только когда маркеры отображаются (showEvents && isLeader).
  const handleBarClick = (clickedTs: number) => {
    const currentGroup = groupRef.current
    if (currentGroup === 'none') return
    if (!showEventsRef.current || !isLeaderRef.current) return
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
      groupEventBus.emit(currentGroup, 'selectEvent', {
        ticker: best.ticker,
        eventDate: best.eventDate,
      })
    }
  }

  const { chartRef, mainSeriesRef, volumeSeriesRef, markersRef } = useChartCore({
    containerRef,
    group,
    memberId: widgetId,
    ticker: selectedTicker || null,
    withVolume: true,
    onBarClick: handleBarClick,
  })

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

  // ── Дивидендные события: грузим всегда при смене тикера ──
  // Видимость маркеров и срабатывание клика контролируются отдельно.
  useEffect(() => {
    if (!selectedTicker) {
      setEvents([])
      return
    }
    getEvents({ ticker: selectedTicker }).then(setEvents)
  }, [selectedTicker])

  useEffect(() => {
    if (group === 'none') return
    return groupEventBus.subscribe(group, 'zoom', (req) => {
      const chart = chartRef.current
      if (!chart) return
      chartSyncBus.markApplied(chart)
      try {
        chart.timeScale().setVisibleRange({
          from: dateToTs(req.from),
          to: dateToTs(req.to),
        })
      } catch { /* серия пуста или range вне данных */ }
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
    if (showEvents && isLeader) {
      for (const ev of events) {
        markers.push({
          time: dateToTs(ev.eventDate),
          position: 'belowBar',
          color: '#9e9e9e',
          shape: 'arrowUp',
        })
      }
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
  }, [events, activeEvent, selectedTicker, markersRef, isLeader, showEvents])

  const [tickerSearch, setTickerSearch] = useState('')
  const [tickerDropdownOpen, setTickerDropdownOpen] = useState(false)
  const tickerDropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (tickerDropdownRef.current && !tickerDropdownRef.current.contains(e.target as Node)) {
        setTickerDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const filteredTickers = useMemo(() => {
    if (!tickerSearch) return tickers
    const q = tickerSearch.toUpperCase()
    return tickers.filter((t) => t.includes(q))
  }, [tickers, tickerSearch])

  return (
    <div style={rootStyle}>
      <div style={toolbarStyle}>
        <label style={labelStyle}>Тикер:</label>
        <div ref={tickerDropdownRef} style={tickerDropdownContainerStyle}>
          <div onClick={() => setTickerDropdownOpen((v) => !v)} style={tickerTriggerStyle}>
            <span>{selectedTicker || '—'}</span>
            <span style={arrowStyle}>{tickerDropdownOpen ? '\u25B2' : '\u25BC'}</span>
          </div>
          {tickerDropdownOpen && (
            <div style={tickerDropdownPanelStyle}>
              <input
                type="text"
                value={tickerSearch}
                onChange={(e) => setTickerSearch(e.target.value)}
                placeholder="Поиск..."
                style={searchInputStyle}
                autoFocus
              />
              <div style={optionsListStyle}>
                {filteredTickers.map((t) => (
                  <div
                    key={t}
                    onClick={() => {
                      setSelectedTicker(t)
                      setTickerDropdownOpen(false)
                      setTickerSearch('')
                    }}
                    style={{
                      ...optionItemBaseStyle,
                      background: t === selectedTicker ? OPTION_BG_SELECTED : OPTION_BG_DEFAULT,
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = OPTION_BG_HOVER)}
                    onMouseLeave={(e) => (
                      e.currentTarget.style.background =
                        t === selectedTicker ? OPTION_BG_SELECTED : OPTION_BG_DEFAULT
                    )}
                  >
                    {t}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
        <SyncLeaderButton group={group} memberId={widgetId} />
      </div>
      <div style={chartOuterStyle}>
        <div
          ref={containerRef}
          style={{
            ...chartInnerBaseStyle,
            cursor: tooltip ? 'pointer' : 'crosshair',
          }}
        />
        {tooltip && (
          <div
            style={{
              ...tooltipBaseStyle,
              left: tooltip.x + 14,
              top: tooltip.y + 14,
            }}
          >
            {tooltip.text}
          </div>
        )}
      </div>
    </div>
  )
}

const OPTION_BG_SELECTED = '#e3f2fd'
const OPTION_BG_HOVER = '#f5f5f5'
const OPTION_BG_DEFAULT = 'transparent'

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
}

const toolbarStyle: React.CSSProperties = {
  marginBottom: 12,
  flexShrink: 0,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}

const labelStyle: React.CSSProperties = {
  fontSize: 14,
}

const tickerDropdownContainerStyle: React.CSSProperties = {
  position: 'relative',
}

const tickerTriggerStyle: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 14,
  border: '1px solid #ccc',
  borderRadius: 4,
  cursor: 'pointer',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 4,
  minWidth: 80,
}

const arrowStyle: React.CSSProperties = {
  fontSize: 10,
  color: '#999',
}

const tickerDropdownPanelStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  marginTop: 2,
  background: 'white',
  border: '1px solid #ccc',
  borderRadius: 6,
  boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
  zIndex: 50,
  minWidth: 120,
  padding: 4,
}

const searchInputStyle: React.CSSProperties = {
  width: '100%',
  padding: '4px 8px',
  fontSize: 13,
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  marginBottom: 4,
  boxSizing: 'border-box',
}

const optionsListStyle: React.CSSProperties = {
  maxHeight: 200,
  overflow: 'auto',
}

const optionItemBaseStyle: React.CSSProperties = {
  padding: '4px 8px',
  fontSize: 13,
  cursor: 'pointer',
  borderRadius: 3,
}

const chartOuterStyle: React.CSSProperties = {
  position: 'relative',
  flex: 1,
  minHeight: 0,
  width: '100%',
}

const chartInnerBaseStyle: React.CSSProperties = {
  width: '100%',
  height: '100%',
}

const tooltipBaseStyle: React.CSSProperties = {
  position: 'absolute',
  padding: '4px 8px',
  background: 'rgba(33, 33, 33, 0.92)',
  color: '#fff',
  fontSize: 12,
  borderRadius: 4,
  pointerEvents: 'none',
  whiteSpace: 'nowrap',
  zIndex: 5,
  boxShadow: '0 2px 6px rgba(0,0,0,0.25)',
}
