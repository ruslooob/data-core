import { useEffect, useMemo, useRef, useState } from 'react'
import { getTickers, runEventStudy } from '../api/client'
import type {
  EventStudyResult,
  ExpectedReturnModel,
  PrecedentEvent,
} from '../api/types'
import type { WidgetGroup } from './chartSync'
import { CarChart } from './CarChart'
import { EventStudySensitivitySection } from './EventStudySensitivitySection'
import { FactVsForecastChart } from './FactVsForecastChart'
import { NumberField } from './NumberField'
import {
  groupEventBus,
  selectEventStudyRequest,
  selectLeaderTicker,
  selectPrecedentSet,
  selectShowEvents,
  useGroupStore,
} from './groupStore'

function shiftDate(iso: string, deltaDays: number): string {
  const d = new Date(iso)
  d.setUTCDate(d.getUTCDate() + deltaDays)
  return d.toISOString().slice(0, 10)
}

/** Подпись события в дропдауне: дата и описание. */
function formatEventLabel(e: PrecedentEvent): string {
  return e.event ? `${e.dateStart} · ${e.event}` : e.dateStart
}

const MODELS: { value: ExpectedReturnModel; label: string }[] = [
  { value: 'mean_adjusted', label: 'Mean adjusted' },
  { value: 'market_model', label: 'Market model' },
  { value: 'capm', label: 'CAPM' },
]

const OUTLIER_PRESETS = [
  { value: 0, label: 'Выкл' },
  { value: 3, label: 'Мягкий (3σ)' },
  { value: 2.5, label: 'Средний (2.5σ)' },
  { value: 2, label: 'Жёсткий (2σ)' },
]

/** При зуме на event window показываем в N раз больший контекст вокруг. */
const ZOOM_CONTEXT_FACTOR = 3

interface EventStudyWidgetProps {
  group: WidgetGroup
}

export function EventStudyWidget({ group }: EventStudyWidgetProps) {
  const [allTickers, setAllTickers] = useState<string[]>([])
  const [ticker, setTicker] = useState<string>('')
  const [eventId, setEventId] = useState<string>('')
  const [model, setModel] = useState<ExpectedReturnModel>('market_model')
  const [daysBefore, setDaysBefore] = useState<number | null>(10)
  const [daysAfter, setDaysAfter] = useState<number | null>(10)
  const [estimationWindow, setEstimationWindow] = useState<number | null>(200)
  const [outlierThreshold, setOutlierThreshold] = useState(0) // 0 = выкл, 2-5 = σ — пересчитывает модель
  const [highlightThreshold, setHighlightThreshold] = useState(0) // 0 = выкл, 2-5 = σ — только подсветка маркерами
  const [result, setResult] = useState<EventStudyResult | null>(null)
  const [resultWindow, setResultWindow] = useState<{ before: number; after: number } | null>(null)
  // Растёт при каждом расчёте (кнопка/стрелки) — триггерит пересчёт sensitivity-секции
  const [sensitivityRunSignal, setSensitivityRunSignal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Подписки на стор группы — авто-перерендер только на нужных изменениях
  const leaderTicker = useGroupStore(selectLeaderTicker(group))
  const showEvents = useGroupStore(selectShowEvents(group))
  const precedentSet = useGroupStore(selectPrecedentSet(group))
  const eventStudyRequest = useGroupStore(selectEventStudyRequest(group))
  const setActiveEventInStore = useGroupStore((s) => s.setActiveEvent)
  const toggleShowEventsInStore = useGroupStore((s) => s.toggleShowEvents)

  // Список тикеров нужен только для свободного выбора, когда лидер не назначен
  useEffect(() => {
    getTickers().then(setAllTickers)
  }, [])

  // События берём из набора группы целиком и сортируем по дате. По тикеру не
  // фильтруем: тикер — subject анализа, набор общий для группы (как в Event
  // Effect Analysis).
  const precedentEvents = useMemo(
    () => [...precedentSet].sort((a, b) => a.dateStart.localeCompare(b.dateStart)),
    [precedentSet],
  )

  // Тикер: залочен на ведущего, если он есть; иначе свободный выбор из всех
  const isLockedToLeader = leaderTicker !== null
  const tickerOptions = useMemo(
    () => (isLockedToLeader ? [leaderTicker as string] : allTickers),
    [isLockedToLeader, leaderTicker, allTickers],
  )

  useEffect(() => {
    if (leaderTicker) {
      if (ticker !== leaderTicker) setTicker(leaderTicker)
    } else if (allTickers.length > 0 && !allTickers.includes(ticker)) {
      setTicker(allTickers.includes('LKOH') ? 'LKOH' : allTickers[0])
    }
  }, [leaderTicker, allTickers, ticker])

  const paramsValid = daysBefore !== null && daysAfter !== null && estimationWindow !== null

  // Сброс выбранного события при смене набора — на первое, если текущего больше нет
  useEffect(() => {
    if (precedentEvents.length === 0) {
      setEventId('')
    } else if (!precedentEvents.some((e) => e.eventId === eventId)) {
      setEventId(precedentEvents[0].eventId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [precedentEvents])

  const currentIdx = precedentEvents.findIndex((e) => e.eventId === eventId)
  const currentEvent = precedentEvents[currentIdx]

  // Публикация активного события в группу (для подсветки на price chart)
  useEffect(() => {
    if (group === 'none') return
    if (!currentEvent) {
      setActiveEventInStore(group, null)
      return
    }
    if (daysBefore === null || daysAfter === null) return
    setActiveEventInStore(group, {
      ticker,
      eventDate: currentEvent.dateStart,
      daysBefore,
      daysAfter,
    })
  }, [group, currentEvent, ticker, daysBefore, daysAfter, setActiveEventInStore])

  // При размонтировании / смене группы — очистить старую
  useEffect(() => {
    return () => {
      if (group !== 'none') {
        setActiveEventInStore(group, null)
      }
    }
  }, [group, setActiveEventInStore])

  // Запрос «посчитать это событие» из стора группы — ставится двойным кликом по
  // строке Event Effect и кликом по маркеру на price chart. Событие набора
  // находим по дате (тикер ведёт лидер). nonce защищает от повторной обработки
  // одного запроса; свежесозданный виджет подхватывает запрос при появлении его
  // в наборе.
  // handleCalculateRef нужен, чтобы эффект не зависел от каждого изменения state.
  const handleCalculateRef = useRef<() => void>(() => {})
  const handledRequestNonceRef = useRef<number>(0)
  useEffect(() => {
    if (!eventStudyRequest) return
    if (eventStudyRequest.nonce === handledRequestNonceRef.current) return
    const found = precedentEvents.find((e) => e.dateStart === eventStudyRequest.eventDate)
    if (!found) return
    handledRequestNonceRef.current = eventStudyRequest.nonce
    setEventId(found.eventId)
    // Авторасчёт на следующем тике, когда применится новый eventId
    setTimeout(() => handleCalculateRef.current(), 0)
  }, [eventStudyRequest, precedentEvents])

  const stepEvent = (delta: number) => {
    if (precedentEvents.length === 0) return
    if (daysBefore === null || daysAfter === null) return
    const next = Math.max(0, Math.min(precedentEvents.length - 1, currentIdx + delta))
    const ev = precedentEvents[next]
    setEventId(ev.eventId)
    // Авто-зум на price chart этой группы
    if (group !== 'none') {
      groupEventBus.emit(group, 'zoom', {
        from: shiftDate(ev.dateStart, -daysBefore * ZOOM_CONTEXT_FACTOR),
        to: shiftDate(ev.dateStart, daysAfter * ZOOM_CONTEXT_FACTOR),
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
    const ev = precedentEvents[currentIdx]
    if (!ev) return
    if (daysBefore === null || daysAfter === null || estimationWindow === null) return
    // Тем же действием пересчитываем sensitivity-секцию (по её собственной сетке)
    setSensitivityRunSignal((n) => n + 1)
    if (group !== 'none') {
      groupEventBus.emit(group, 'zoom', {
        from: shiftDate(ev.dateStart, -daysBefore * ZOOM_CONTEXT_FACTOR),
        to: shiftDate(ev.dateStart, daysAfter * ZOOM_CONTEXT_FACTOR),
      })
    }
    setLoading(true)
    setError(null)
    try {
      const r = await runEventStudy({
        ticker,
        eventDate: ev.dateStart,
        model,
        eventWindow: [-daysBefore, daysAfter],
        estimationWindow: estimationWindow,
        outlierThreshold: outlierThreshold > 0 ? outlierThreshold : null,
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

  // Группа обязательна, источник событий — набор прецедентов
  if (group === 'none') {
    return (
      <div style={rootContainerStyle}>
        <div style={placeholderStyle}>
          Привяжите виджет к группе (выберите цвет рядом с заголовком),
          <br />
          затем выберите набор прецедентов.
        </div>
      </div>
    )
  }

  if (precedentSet.length === 0) {
    return (
      <div style={rootContainerStyle}>
        <div style={placeholderStyle}>
          Выберите события в виджете «Поиск прецедентов» этой же группы.
        </div>
      </div>
    )
  }

  return (
    <div style={rootContainerStyle}>
      <div style={sectionHeaderStyle}>CAR в окне события</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
        <label style={labelStyle}>
          Тикер{isLockedToLeader && ' (ведущий)'}
          <select
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            style={selectStyle}
            disabled={isLockedToLeader}
          >
            {tickerOptions.length === 0 && <option value="">—</option>}
            {tickerOptions.map((t) => (
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
            disabled={precedentEvents.length === 0}
          >
            {precedentEvents.length === 0 && <option value="">—</option>}
            {precedentEvents.map((e) => (
              <option key={e.eventId} value={e.eventId}>
                {formatEventLabel(e)}
              </option>
            ))}
          </select>
        </label>

        <ShowEventsToggleButton
          show={showEvents}
          disabled={leaderTicker === null}
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

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 24 }}>
        <fieldset style={fieldsetStyle}>
          <legend style={legendStyle}>Окно события</legend>
          <div style={{ display: 'flex', gap: 12 }}>
            <NumberField label="До" min={1} max={60} value={daysBefore} onChange={setDaysBefore} />
            <NumberField label="После" min={1} max={60} value={daysAfter} onChange={setDaysAfter} />
          </div>
        </fieldset>
        <fieldset style={fieldsetStyle}>
          <legend style={legendStyle}>Оценочное окно</legend>
          <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
            <NumberField label="Длина" min={30} max={500} value={estimationWindow} onChange={setEstimationWindow} />
            <label style={labelStyle}>
              Фильтр выбросов
              <select
                value={outlierThreshold}
                onChange={(e) => setOutlierThreshold(Number(e.target.value))}
                style={selectStyle}
              >
                {OUTLIER_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </label>
          </div>
        </fieldset>
      </div>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <button
          onClick={handleCalculate}
          style={calcButtonStyle}
          disabled={!eventId || loading || !paramsValid}
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
          disabled={currentIdx < 0 || currentIdx >= precedentEvents.length - 1}
          style={navButtonStyle}
          title="Следующее событие"
        >
          →
        </button>
      </div>

      {error && <div style={{ color: '#c62828', fontSize: 13 }}>{error}</div>}

      {result && resultWindow ? (
        <>
          <div style={carChartContainerStyle}>
            <CarChart
              result={result}
              daysBefore={resultWindow.before}
              daysAfter={resultWindow.after}
              group={group}
            />
          </div>
          <div style={sectionHeaderStyle}>Оценочное окно: факт vs прогноз</div>
          <div style={diagnosticControlsStyle}>
            <label style={labelStyle}>
              Подсветка выбросов
              <select
                value={highlightThreshold}
                onChange={(e) => setHighlightThreshold(Number(e.target.value))}
                style={selectStyle}
              >
                {OUTLIER_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </label>
            {result.outliersRemoved > 0 && (
              <div style={outliersHintStyle}>
                Фильтр модели уже убрал {result.outliersRemoved}{' '}
                {pluralizeDays(result.outliersRemoved)} — здесь видны выбросы
                из оставшегося оценочного окна.
              </div>
            )}
          </div>
          <div style={diagnosticsStripStyle}>
            <span style={metricStyle}>
              <span style={metricLabelStyle}>R²</span>
              <span style={metricValueStyle}>{result.rSquared.toFixed(2)}</span>
            </span>
            <span style={metricStyle}>
              <span style={metricLabelStyle}>σ_ε</span>
              <span style={metricValueStyle}>{(result.estimationStd * 100).toFixed(2)}%</span>
            </span>
          </div>
          <div style={factVsForecastContainerStyle}>
            <FactVsForecastChart
              dates={result.estimationDates}
              actual={result.estimationActual}
              predicted={result.estimationPredicted}
              residualSigmas={result.estimationResidualSigmas}
              highlightThreshold={highlightThreshold}
            />
          </div>
          {currentEvent && (
            <EventStudySensitivitySection
              ticker={ticker}
              eventDate={currentEvent.dateStart}
              runSignal={sensitivityRunSignal}
            />
          )}
        </>
      ) : (
        <div style={placeholderStyle}>Нажми «Рассчитать»</div>
      )}
    </div>
  )
}

function pluralizeDays(n: number): string {
  const lastTwo = n % 100
  if (lastTwo >= 11 && lastTwo <= 14) return 'дней'
  const last = n % 10
  if (last === 1) return 'день'
  if (last >= 2 && last <= 4) return 'дня'
  return 'дней'
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

const fieldsetStyle: React.CSSProperties = {
  border: '1px solid #e0e0e0',
  borderRadius: 6,
  padding: '8px 12px',
  margin: 0,
}

const legendStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#888',
  padding: '0 4px',
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

const CAR_CHART_HEIGHT = 380
const FACT_VS_FORECAST_HEIGHT = 280

const rootContainerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  height: '100%',
  overflowY: 'auto',
}

const carChartContainerStyle: React.CSSProperties = {
  height: CAR_CHART_HEIGHT,
  flexShrink: 0,
  display: 'flex',
  flexDirection: 'column',
}

const factVsForecastContainerStyle: React.CSSProperties = {
  height: FACT_VS_FORECAST_HEIGHT,
  flexShrink: 0,
  display: 'flex',
  flexDirection: 'column',
}

const sectionHeaderStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: '#333',
  padding: '4px 0 2px',
  borderBottom: '1px solid #e0e0e0',
  flexShrink: 0,
}

const diagnosticControlsStyle: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 16,
  alignItems: 'center',
  flexShrink: 0,
}

const outliersHintStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#e65100',
  flex: 1,
  minWidth: 220,
}

const diagnosticsStripStyle: React.CSSProperties = {
  display: 'flex',
  gap: 24,
  alignItems: 'baseline',
  padding: '4px 0',
  borderTop: '1px solid #e0e0e0',
  flexShrink: 0,
}

const metricStyle: React.CSSProperties = {
  display: 'inline-flex',
  gap: 6,
  alignItems: 'baseline',
}

const metricLabelStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#888',
}

const metricValueStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  color: '#333',
  fontVariantNumeric: 'tabular-nums',
}

const placeholderStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 200,
  color: '#888',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: 16,
}
