import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { findAnomalies, getTickers, scanAllAnomalies } from '../api/client'
import type { AnomalyResult, ExpectedReturnModel } from '../api/types'
import type { WidgetGroup } from './chartSync'
import {
  groupEventBus,
  selectLeaderTicker,
  useGroupStore,
} from './groupStore'

const MODELS: { value: ExpectedReturnModel; label: string }[] = [
  { value: 'mean_adjusted', label: 'Mean adjusted' },
  { value: 'market_model', label: 'Market model' },
  { value: 'capm', label: 'CAPM' },
]

interface AnomalyWidgetProps {
  group: WidgetGroup
}

const ALL_TICKERS_KEY = '__ALL__'

export function AnomalyWidget({ group }: AnomalyWidgetProps) {
  const [allTickers, setAllTickers] = useState<string[]>([])
  const [selectedTickers, setSelectedTickers] = useState<string[]>([ALL_TICKERS_KEY])
  const [tickerSearch, setTickerSearch] = useState('')
  const [tickerDropdownOpen, setTickerDropdownOpen] = useState(false)
  const [model, setModel] = useState<ExpectedReturnModel>('market_model')
  const [daysBefore, setDaysBefore] = useState(10)
  const [daysAfter, setDaysAfter] = useState(10)
  const [estimationWindow, setEstimationWindow] = useState(200)
  const [results, setResults] = useState<AnomalyResult[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scanProgress, setScanProgress] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const leaderTicker = useGroupStore(selectLeaderTicker(group))

  useEffect(() => {
    getTickers().then(setAllTickers)
  }, [])

  // Click outside → close dropdown
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setTickerDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const isAllSelected = selectedTickers.includes(ALL_TICKERS_KEY)
  const effectiveTickers = isAllSelected ? allTickers : selectedTickers

  const toggleTicker = (t: string) => {
    if (t === ALL_TICKERS_KEY) {
      // Если уже ALL → снять всё, если нет → выбрать ALL
      setSelectedTickers((prev) =>
        prev.includes(ALL_TICKERS_KEY) ? [] : [ALL_TICKERS_KEY],
      )
      return
    }
    setSelectedTickers((prev) => {
      const without = prev.filter((x) => x !== ALL_TICKERS_KEY)
      if (without.includes(t)) {
        return without.filter((x) => x !== t)
      }
      return [...without, t]
    })
  }

  const filteredTickers = useMemo(() => {
    if (!tickerSearch) return allTickers
    const q = tickerSearch.toUpperCase()
    return allTickers.filter((t) => t.includes(q))
  }, [allTickers, tickerSearch])

  const tickerLabel = isAllSelected
    ? 'Все тикеры'
    : selectedTickers.length <= 3
      ? selectedTickers.join(', ')
      : `${selectedTickers.length} тикеров`

  const handleScanSelected = async () => {
    if (effectiveTickers.length === 0) return
    setLoading(true)
    setError(null)
    setResults([])
    try {
      const all: AnomalyResult[] = []
      for (const t of effectiveTickers) {
        setScanProgress(t)
        const r = await findAnomalies({
          ticker: t,
          model,
          eventWindow: [-daysBefore, daysAfter],
          estimationWindow,
        })
        all.push(...r)
      }
      all.sort((a, b) => b.anomalyScore - a.anomalyScore)
      setResults(all)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setResults([])
    } finally {
      setLoading(false)
      setScanProgress('')
    }
  }

  const handleScanAllStreaming = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setLoading(true)
    setError(null)
    setResults([])
    setScanProgress('')

    const seen = new Set<string>()

    try {
      await scanAllAnomalies(
        {
          model,
          eventWindow: [-daysBefore, daysAfter],
          estimationWindow,
        },
        (r) => {
          const key = `${r.ticker}_${r.eventDate}`
          if (seen.has(key)) return
          seen.add(key)
          setScanProgress(r.ticker)
          setResults((prev) => {
            const next = [...prev, r]
            next.sort((a, b) => b.anomalyScore - a.anomalyScore)
            return next
          })
        },
        ctrl.signal,
      )
    } catch (e) {
      if (ctrl.signal.aborted) return
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
      setScanProgress('')
    }
  }, [model, daysBefore, daysAfter, estimationWindow])

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort()
      abortRef.current = null
      setLoading(false)
      setScanProgress('')
    }
  }

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  const handleEventClick = (r: AnomalyResult) => {
    if (group === 'none') return
    groupEventBus.emit(group, 'selectEvent', {
      ticker: r.ticker,
      eventDate: r.eventDate,
    })
  }

  const handleScan = isAllSelected ? handleScanAllStreaming : handleScanSelected

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'flex-end' }}>
        {/* Ticker multiselect combobox */}
        <label style={labelStyle}>
          Тикеры
          <div ref={dropdownRef} style={{ position: 'relative' }}>
            <div
              onClick={() => setTickerDropdownOpen((v) => !v)}
              style={{
                ...selectStyle,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 4,
                minWidth: 150,
              }}
            >
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {tickerLabel}
              </span>
              <span style={{ fontSize: 10, color: '#999' }}>{tickerDropdownOpen ? '\u25B2' : '\u25BC'}</span>
            </div>
            {tickerDropdownOpen && (
              <div style={dropdownStyle}>
                <input
                  type="text"
                  value={tickerSearch}
                  onChange={(e) => setTickerSearch(e.target.value)}
                  placeholder="Поиск..."
                  style={searchInputStyle}
                  autoFocus
                />
                <div style={{ maxHeight: 200, overflow: 'auto' }}>
                  <label style={checkboxRowStyle}>
                    <input
                      type="checkbox"
                      checked={isAllSelected}
                      onChange={() => toggleTicker(ALL_TICKERS_KEY)}
                    />
                    <b>Все тикеры</b>
                  </label>
                  {filteredTickers.map((t) => (
                    <label key={t} style={checkboxRowStyle}>
                      <input
                        type="checkbox"
                        checked={isAllSelected || selectedTickers.includes(t)}
                        onChange={() => toggleTicker(t)}
                      />
                      {t}
                    </label>
                  ))}
                </div>
              </div>
            )}
          </div>
        </label>

        <label style={labelStyle}>
          Модель
          <select
            value={model}
            onChange={(e) => setModel(e.target.value as ExpectedReturnModel)}
            style={selectStyle}
          >
            {MODELS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </label>

        <button
          onClick={() => setShowSettings((v) => !v)}
          style={{
            ...settingsButtonStyle,
            background: showSettings ? '#e0e0e0' : 'transparent',
          }}
          title="Настройки окон"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
        </button>

        {loading ? (
          <button onClick={handleStop} style={stopButtonStyle}>
            Стоп {scanProgress && `(${scanProgress}...)`}
          </button>
        ) : (
          <button
            onClick={handleScan}
            style={scanButtonStyle}
            disabled={effectiveTickers.length === 0 || loading}
          >
            Сканировать
          </button>
        )}
      </div>

      {/* Settings panel (collapsible) */}
      {showSettings && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16, padding: '4px 0' }}>
          <SliderField
            label={`Дней до: ${daysBefore}`}
            min={1} max={60}
            value={daysBefore}
            onChange={setDaysBefore}
          />
          <SliderField
            label={`Дней после: ${daysAfter}`}
            min={1} max={60}
            value={daysAfter}
            onChange={setDaysAfter}
          />
          <SliderField
            label={`Оценочное окно: ${estimationWindow}`}
            min={30} max={500}
            value={estimationWindow}
            onChange={setEstimationWindow}
          />
        </div>
      )}

      {error && <div style={{ color: '#c62828', fontSize: 13 }}>{error}</div>}

      {loading && results.length > 0 && (
        <div style={{ fontSize: 12, color: '#666' }}>
          Найдено: {results.length} событий, сканируем {scanProgress}...
        </div>
      )}

      {/* Results table */}
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
        {results.length === 0 && !loading ? (
          <div style={placeholderStyle}>
            Нажмите «Сканировать» для проверки событий
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: '2px solid #ddd', textAlign: 'left' }}>
                <th style={thStyle}>Тикер</th>
                <th style={thStyle}>Дата</th>
                <th style={thStyle}>CAR%</th>
                <th style={thStyle}>Vol</th>
                <th style={{ ...thStyle, whiteSpace: 'nowrap' }}>Объём</th>
                <th style={thStyle}>Аномалии</th>
                <th style={thStyle}>Балл</th>
              </tr>
            </thead>
            <tbody>
              {results.map((r) => (
                <tr
                  key={`${r.ticker}_${r.eventDate}`}
                  onClick={() => handleEventClick(r)}
                  style={{
                    borderBottom: '1px solid #eee',
                    cursor: group !== 'none' ? 'pointer' : 'default',
                    background: r.flags.length > 0 ? '#fff8e1' : 'transparent',
                  }}
                  title={
                    group === 'none'
                      ? 'Назначьте группу виджету, чтобы открывать события по клику'
                      : r.flags.map(f => f.detail).join('\n')
                  }
                >
                  <td style={{ ...tdStyle, fontWeight: 600 }}>{r.ticker}</td>
                  <td style={tdStyle}>{r.eventDate}</td>
                  <td style={{
                    ...tdStyle,
                    color: r.carPct >= 0 ? '#2e7d32' : '#c62828',
                    fontWeight: 600,
                  }}>
                    {r.carPct >= 0 ? '+' : ''}{r.carPct.toFixed(2)}
                  </td>
                  <td style={tdStyle}>{r.volRatio.toFixed(2)}</td>
                  <td style={tdStyle}>{r.volumeRatio.toFixed(2)}</td>
                  <td style={tdStyle}>
                    {r.flags.length === 0 ? (
                      <span style={{ color: '#aaa' }}>—</span>
                    ) : (
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {r.flags.map((f) => (
                          <span
                            key={f.code}
                            style={flagBadgeStyle(f.severity)}
                            title={f.detail}
                          >
                            {f.label}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <ScoreBar score={r.anomalyScore} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
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
    <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 160 }}>
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

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100)
  const color = score > 0.6 ? '#c62828' : score > 0.3 ? '#e65100' : score > 0 ? '#f9a825' : '#ccc'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <div style={{
        width: 40,
        height: 6,
        background: '#eee',
        borderRadius: 3,
        overflow: 'hidden',
      }}>
        <div style={{
          width: `${pct}%`,
          height: '100%',
          background: color,
          borderRadius: 3,
        }} />
      </div>
      <span style={{ fontSize: 11, color: '#888' }}>{pct > 0 ? pct : ''}</span>
    </div>
  )
}

function flagBadgeStyle(severity: number): React.CSSProperties {
  const bg = severity > 0.6 ? '#ffcdd2' : severity > 0.3 ? '#ffe0b2' : '#fff9c4'
  const color = severity > 0.6 ? '#b71c1c' : severity > 0.3 ? '#e65100' : '#f57f17'
  return {
    display: 'inline-block',
    padding: '1px 6px',
    borderRadius: 8,
    fontSize: 11,
    fontWeight: 500,
    background: bg,
    color: color,
    whiteSpace: 'nowrap',
  }
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
  minWidth: 120,
}

const scanButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  backgroundColor: '#e65100',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  alignSelf: 'flex-end',
}

const stopButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  backgroundColor: '#c62828',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  alignSelf: 'flex-end',
}

const settingsButtonStyle: React.CSSProperties = {
  width: 32,
  height: 32,
  padding: 0,
  border: '1px solid #d0d0d0',
  borderRadius: 4,
  cursor: 'pointer',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  alignSelf: 'flex-end',
  color: '#666',
}

const thStyle: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 12,
  fontWeight: 600,
  color: '#666',
}

const tdStyle: React.CSSProperties = {
  padding: '6px 8px',
}

const dropdownStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  marginTop: 2,
  background: 'white',
  border: '1px solid #ccc',
  borderRadius: 6,
  boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
  zIndex: 50,
  minWidth: 180,
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

const checkboxRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  padding: '3px 4px',
  fontSize: 13,
  cursor: 'pointer',
}

const placeholderStyle: React.CSSProperties = {
  flex: 1,
  color: '#888',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  textAlign: 'center',
  padding: 16,
}
