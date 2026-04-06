import { useEffect, useMemo, useState } from 'react'
import { getEvents, getTickers } from '../api/client'
import type { DividendEvent, ExpectedReturnModel } from '../api/types'
import type { SyncGroup } from './chartSync'
import { groupRegistry } from './groupRegistry'

const MODELS: { value: ExpectedReturnModel; label: string }[] = [
  { value: 'mean_adjusted', label: 'Mean adjusted' },
  { value: 'market_model', label: 'Market model' },
  { value: 'capm', label: 'CAPM' },
]

interface EventStudyWidgetProps {
  syncGroup: SyncGroup
}

export function EventStudyWidget({ syncGroup }: EventStudyWidgetProps) {
  const [allTickers, setAllTickers] = useState<string[]>([])
  const [groupTickers, setGroupTickers] = useState<string[]>(() =>
    groupRegistry.getGroupTickers(syncGroup),
  )
  const [allEvents, setAllEvents] = useState<DividendEvent[]>([])
  const [ticker, setTicker] = useState<string>('')
  const [eventId, setEventId] = useState<string>('')
  const [model, setModel] = useState<ExpectedReturnModel>('market_model')
  const [daysBefore, setDaysBefore] = useState(10)
  const [daysAfter, setDaysAfter] = useState(10)
  const [estimationWindow, setEstimationWindow] = useState(200)

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

  // Подписка на изменения тикеров в текущей sync-группе
  useEffect(() => {
    setGroupTickers(groupRegistry.getGroupTickers(syncGroup))
    if (syncGroup === 'none') return
    return groupRegistry.subscribe(syncGroup, setGroupTickers)
  }, [syncGroup])

  // Доступные тикеры: фильтр по группе если есть participants, иначе все
  const tickers = useMemo(() => {
    if (syncGroup === 'none') return allTickers
    if (groupTickers.length === 0) return allTickers
    return groupTickers
  }, [syncGroup, groupTickers, allTickers])

  // Если текущий тикер выпал из доступных — переключиться на первый
  useEffect(() => {
    if (tickers.length === 0) return
    if (!tickers.includes(ticker)) {
      setTicker(tickers[0])
    }
  }, [tickers, ticker])

  const tickerEvents = useMemo(
    () =>
      allEvents
        .filter((e) => e.ticker === ticker)
        .sort((a, b) => a.event_date.localeCompare(b.event_date)),
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

  const stepEvent = (delta: number) => {
    if (tickerEvents.length === 0) return
    const next = Math.max(0, Math.min(tickerEvents.length - 1, currentIdx + delta))
    setEventId(tickerEvents[next].id)
  }

  const handleCalculate = () => {
    // Шаг 4.2 — здесь будет вызов runEventStudy и отрисовка
    console.log('calculate', {
      ticker,
      event_date: tickerEvents[currentIdx]?.event_date,
      model,
      event_window: [-daysBefore, daysAfter],
      estimation_window: estimationWindow,
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
        <label style={labelStyle}>
          Тикер
          <select
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            style={selectStyle}
          >
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
                {e.event_date} — {e.dividend.toFixed(2)} ₽
              </option>
            ))}
          </select>
        </label>

        <button
          onClick={() => stepEvent(-1)}
          disabled={currentIdx <= 0}
          style={navButtonStyle}
        >
          ←
        </button>
        <button
          onClick={() => stepEvent(1)}
          disabled={currentIdx < 0 || currentIdx >= tickerEvents.length - 1}
          style={navButtonStyle}
        >
          →
        </button>

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

      <button onClick={handleCalculate} style={calcButtonStyle} disabled={!eventId}>
        Рассчитать
      </button>

      <div style={{ flex: 1, color: '#888', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        График CAR появится после Шага 4.2
      </div>
    </div>
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
  padding: '6px 12px',
  fontSize: 14,
  border: '1px solid #ccc',
  borderRadius: 4,
  background: 'white',
  cursor: 'pointer',
  alignSelf: 'flex-end',
}

const calcButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  backgroundColor: '#4CAF50',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  alignSelf: 'flex-start',
}
