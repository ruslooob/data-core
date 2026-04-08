import { useEffect, useMemo, useRef, useState } from 'react'
import { getEvents, getTickers, runEventStudy } from '../api/client'
import type { DividendEvent, EventStudyResult, ExpectedReturnModel } from '../api/types'
import type { WidgetGroup } from './chartSync'
import { CarChart } from './CarChart'
import {
  groupEventBus,
  selectLeaderTicker,
  selectShowEvents,
  useGroupStore,
} from './groupStore'

function shiftDate(iso: string, deltaDays: number): string {
  const d = new Date(iso)
  d.setUTCDate(d.getUTCDate() + deltaDays)
  return d.toISOString().slice(0, 10)
}

const MODELS: { value: ExpectedReturnModel; label: string }[] = [
  { value: 'mean_adjusted', label: 'Mean adjusted' },
  { value: 'market_model', label: 'Market model' },
  { value: 'capm', label: 'CAPM' },
]

/** При зуме на event window показываем в N раз больший контекст вокруг. */
const ZOOM_CONTEXT_FACTOR = 3

interface EventStudyWidgetProps {
  group: WidgetGroup
}

export function EventStudyWidget({ group }: EventStudyWidgetProps) {
  const [allTickers, setAllTickers] = useState<string[]>([])
  const [allEvents, setAllEvents] = useState<DividendEvent[]>([])
  const [ticker, setTicker] = useState<string>('')
  const [eventId, setEventId] = useState<string>('')
  const [model, setModel] = useState<ExpectedReturnModel>('market_model')
  const [daysBefore, setDaysBefore] = useState(10)
  const [daysAfter, setDaysAfter] = useState(10)
  const [estimationWindow, setEstimationWindow] = useState(200)
  const [result, setResult] = useState<EventStudyResult | null>(null)
  const [resultWindow, setResultWindow] = useState<{ before: number; after: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Подписки на стор группы — авто-перерендер только на нужных изменениях
  const leaderTicker = useGroupStore(selectLeaderTicker(group))
  const showEvents = useGroupStore(selectShowEvents(group))
  const setActiveEventInStore = useGroupStore((s) => s.setActiveEvent)
  const toggleShowEventsInStore = useGroupStore((s) => s.toggleShowEvents)

  useEffect(() => {
    getTickers().then((ts) => {
      setAllTickers(ts)
      if (ts.length > 0 && !ticker) {
        setTicker(ts.includes('LKOH') ? 'LKOH' : ts[0])
      }
    })
    getEvents().then(setAllEvents)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Доступные тикеры:
  //  - none → все (автономный режим)
  //  - есть ведущий с тикером → только его тикер (forced)
  //  - нет ведущего / индекс-лидер → пусто (placeholder)
  const tickers = useMemo(() => {
    if (group === 'none') return allTickers
    if (leaderTicker) return [leaderTicker]
    return []
  }, [group, leaderTicker, allTickers])

  const isLockedToLeader = group !== 'none' && leaderTicker !== null
  const isBlockedNoLeader = group !== 'none' && leaderTicker === null

  // Синхронизация выбранного тикера с ведущим
  useEffect(() => {
    if (group === 'none') {
      if (tickers.length > 0 && !tickers.includes(ticker)) setTicker(tickers[0])
      return
    }
    if (leaderTicker) {
      if (ticker !== leaderTicker) setTicker(leaderTicker)
    } else {
      if (ticker !== '') setTicker('')
    }
  }, [group, leaderTicker, tickers, ticker])

  const tickerEvents = useMemo(
    () =>
      allEvents
        .filter((e) => e.ticker === ticker)
        .sort((a, b) => a.eventDate.localeCompare(b.eventDate)),
    [allEvents, ticker],
  )

  useEffect(() => {
    if (tickerEvents.length > 0) {
      setEventId(tickerEvents[0].id)
    } else {
      setEventId('')
    }
  }, [tickerEvents])

  const currentIdx = tickerEvents.findIndex((e) => e.id === eventId)
  const currentEvent = tickerEvents[currentIdx]

  // Публикация активного события в группу (для подсветки на price chart)
  useEffect(() => {
    if (group === 'none') return
    if (!currentEvent) {
      setActiveEventInStore(group, null)
      return
    }
    setActiveEventInStore(group, {
      ticker: currentEvent.ticker,
      eventDate: currentEvent.eventDate,
      daysBefore,
      daysAfter,
    })
  }, [group, currentEvent, daysBefore, daysAfter, setActiveEventInStore])

  // При размонтировании / смене группы — очистить старую
  useEffect(() => {
    return () => {
      if (group !== 'none') {
        setActiveEventInStore(group, null)
      }
    }
  }, [group, setActiveEventInStore])

  // Подписка на «выбрать событие» из price chart (клик по маркеру)
  // handleCalculateRef нужен, чтобы подписка не пере-создавалась на каждом изменении state
  const handleCalculateRef = useRef<() => void>(() => {})
  useEffect(() => {
    if (group === 'none') return
    return groupEventBus.subscribe(group, 'selectEvent', (req) => {
      // Если тикер другой — сначала переключаем тикер, затем событие
      if (req.ticker !== ticker) {
        setTicker(req.ticker)
      }
      const found = allEvents.find(
        (e) => e.ticker === req.ticker && e.eventDate === req.eventDate,
      )
      if (found) {
        setEventId(found.id)
        // Авторасчёт на следующем тике, когда state применится
        setTimeout(() => handleCalculateRef.current(), 0)
      }
    })
  }, [group, ticker, allEvents])

  const stepEvent = (delta: number) => {
    if (tickerEvents.length === 0) return
    const next = Math.max(0, Math.min(tickerEvents.length - 1, currentIdx + delta))
    const ev = tickerEvents[next]
    setEventId(ev.id)
    // Авто-зум на price chart этой группы
    if (group !== 'none') {
      groupEventBus.emit(group, 'zoom', {
        from: shiftDate(ev.eventDate, -daysBefore * ZOOM_CONTEXT_FACTOR),
        to: shiftDate(ev.eventDate, daysAfter * ZOOM_CONTEXT_FACTOR),
      })
    }
    // Авто-расчёт после применения нового eventId
    setTimeout(() => handleCalculateRef.current(), 0)
  }

  // Обновляем handleCalculateRef на каждом рендере, чтобы select-handler звал актуальную версию
  useEffect(() => {
    handleCalculateRef.current = () => {
      void handleCalculate()
    }
  })

  const handleCalculate = async () => {
    const ev = tickerEvents[currentIdx]
    if (!ev) return
    if (group !== 'none') {
      groupEventBus.emit(group, 'zoom', {
        from: shiftDate(ev.eventDate, -daysBefore * ZOOM_CONTEXT_FACTOR),
        to: shiftDate(ev.eventDate, daysAfter * ZOOM_CONTEXT_FACTOR),
      })
    }
    setLoading(true)
    setError(null)
    try {
      const r = await runEventStudy({
        ticker,
        eventDate: ev.eventDate,
        model,
        eventWindow: [-daysBefore, daysAfter],
        estimationWindow: estimationWindow,
      })
      setResult(r)
      setResultWindow({ before: daysBefore, after: daysAfter })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
        <label style={labelStyle}>
          Тикер{isLockedToLeader && ' (ведущий)'}
          <select
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            style={selectStyle}
            disabled={isLockedToLeader || isBlockedNoLeader}
          >
            {tickers.length === 0 && <option value="">—</option>}
            {tickers.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>

        <label style={labelStyle}>
          Событие
          <select
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
            style={selectStyle}
            disabled={tickerEvents.length === 0}
          >
            {tickerEvents.map((e) => (
              <option key={e.id} value={e.id}>
                {e.eventDate} — {e.dividend.toFixed(2)} ₽
              </option>
            ))}
          </select>
        </label>

        <ShowEventsToggleButton
          show={showEvents}
          disabled={isBlockedNoLeader || group === 'none'}
          group={group}
          onToggle={() => toggleShowEventsInStore(group)}
        />

        <label style={labelStyle}>
          Модель
          <select
            value={model}
            onChange={(e) => setModel(e.target.value as ExpectedReturnModel)}
            style={selectStyle}
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
        <SliderField
          label={`Дней до: ${daysBefore}`}
          min={1}
          max={60}
          value={daysBefore}
          onChange={setDaysBefore}
        />
        <SliderField
          label={`Дней после: ${daysAfter}`}
          min={1}
          max={60}
          value={daysAfter}
          onChange={setDaysAfter}
        />
        <SliderField
          label={`Оценочное окно: ${estimationWindow}`}
          min={30}
          max={500}
          value={estimationWindow}
          onChange={setEstimationWindow}
        />
      </div>

      <div style={{ display: 'flex', gap: 8 }}>
        <button
          onClick={handleCalculate}
          style={calcButtonStyle}
          disabled={!eventId || loading || isBlockedNoLeader}
        >
          {loading ? 'Считаем…' : 'Рассчитать'}
        </button>
        <button
          onClick={() => stepEvent(-1)}
          disabled={currentIdx <= 0}
          style={navButtonStyle}
          title="Предыдущее событие"
        >
          ←
        </button>
        <button
          onClick={() => stepEvent(1)}
          disabled={currentIdx < 0 || currentIdx >= tickerEvents.length - 1}
          style={navButtonStyle}
          title="Следующее событие"
        >
          →
        </button>
      </div>

      {error && <div style={{ color: '#c62828', fontSize: 13 }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
        {isBlockedNoLeader ? (
          <div
            style={{
              flex: 1,
              color: '#888',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              textAlign: 'center',
              padding: 16,
            }}
          >
            Выберите ведущий price chart в группе
            <br />
            (кнопка ⟳ на нужном графике)
          </div>
        ) : result && resultWindow ? (
          <CarChart
            result={result}
            daysBefore={resultWindow.before}
            daysAfter={resultWindow.after}
            group={group}
          />
        ) : (
          <div
            style={{
              flex: 1,
              color: '#888',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            Нажми «Рассчитать»
          </div>
        )}
      </div>
    </div>
  )
}

function ShowEventsToggleButton({
  show,
  disabled,
  group,
  onToggle,
}: {
  show: boolean
  disabled: boolean
  group: WidgetGroup
  onToggle: () => void
}) {
  let title: string
  if (group === 'none') {
    title = 'Выберите цветовую группу, чтобы показывать события на ведущем графике'
  } else if (disabled) {
    title = 'В группе нет ведущего price chart — некому показывать события'
  } else if (show) {
    title = 'Скрыть события на ведущем графике'
  } else {
    title = 'Показать все события тикера на ведущем графике'
  }
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      title={title}
      aria-label={title}
      style={{
        alignSelf: 'flex-end',
        marginBottom: 1,
        width: 32,
        height: 32,
        padding: 0,
        border: '1px solid #d0d0d0',
        borderRadius: 4,
        background: show ? '#2962FF' : 'transparent',
        color: show ? '#ffffff' : '#666',
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: disabled ? 0.45 : 1,
      }}
    >
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
        <circle cx="12" cy="12" r="3" />
      </svg>
    </button>
  )
}

function SliderField({
  label,
  min,
  max,
  value,
  onChange,
}: {
  label: string
  min: number
  max: number
  value: number
  onChange: (v: number) => void
}) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
      <span style={{ fontSize: 12, color: '#555' }}>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: 12,
  color: '#555',
}

const selectStyle: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
  minWidth: 140,
}

const navButtonStyle: React.CSSProperties = {
  padding: '8px 14px',
  fontSize: 14,
  border: '1px solid #ccc',
  borderRadius: 6,
  background: 'white',
  cursor: 'pointer',
}

const calcButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  backgroundColor: '#4CAF50',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
}

