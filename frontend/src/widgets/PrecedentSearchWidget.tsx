import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { sql, PostgreSQL } from '@codemirror/lang-sql'
import { Prec } from '@codemirror/state'
import { keymap } from '@codemirror/view'
import {
  PrecedentApiError,
  getEventsInfo,
  searchPrecedents,
  searchPrecedentsFuzzy,
} from '../api/client'
import type { WidgetGroup } from './chartSync'
import {
  selectPrecedentSet,
  useGroupStore,
} from './groupStore'

interface PrecedentSearchWidgetProps {
  group: WidgetGroup
}

type SearchMode = 'fuzzy' | 'pql'
type ViewMode = 'found' | 'selected'
type Status = 'idle' | 'loading' | 'success' | 'error'

interface EventRow {
  eventId: string
  event: string
  dateStart: string
  tags: string[]
}

interface ErrorState {
  message: string
  line: number | null
  column: number | null
}

const DEFAULT_PQL = `SELECT id, event
FROM events
WHERE date_start > DATE '2020-01-01'
ORDER BY date_start DESC
LIMIT 50`

const ID_COLUMN_NAMES = new Set(['id', 'event_id'])
const EVENT_COLUMN_NAME = 'event'

export function PrecedentSearchWidget({ group }: PrecedentSearchWidgetProps) {
  const [mode, setMode] = useState<SearchMode>('fuzzy')
  const [fuzzyQuery, setFuzzyQuery] = useState('')
  const [pqlSource, setPqlSource] = useState(DEFAULT_PQL)
  const [viewMode, setViewMode] = useState<ViewMode>('found')

  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<ErrorState | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [foundRows, setFoundRows] = useState<EventRow[]>([])

  // Кэш всех событий, виденных в любом поиске за время жизни виджета —
  // нужен для отображения данных в режиме «Выбранные» после смены режима/запроса.
  const [eventCache, setEventCache] = useState<Map<string, EventRow>>(() => new Map())

  // Локальный набор для группы `none` — в groupStore группа `none` не пишется,
  // потому что несколько виджетов в `none` не должны делиться состоянием.
  const [localSet, setLocalSet] = useState<string[]>([])

  const groupSet = useGroupStore(selectPrecedentSet(group))
  const togglePrecedentInSet = useGroupStore((s) => s.togglePrecedentInSet)
  const addPrecedentsToSet = useGroupStore((s) => s.addPrecedentsToSet)
  const removePrecedentsFromSet = useGroupStore((s) => s.removePrecedentsFromSet)
  const clearPrecedentSet = useGroupStore((s) => s.clearPrecedentSet)

  const selectedIds = group === 'none' ? localSet : groupSet
  const selectedCount = selectedIds.length

  const toggleSelected = useCallback((eventId: string) => {
    if (group === 'none') {
      setLocalSet((prev) =>
        prev.includes(eventId) ? prev.filter((id) => id !== eventId) : [...prev, eventId],
      )
    } else {
      togglePrecedentInSet(group, eventId)
    }
  }, [group, togglePrecedentInSet])

  const clearSelected = useCallback(() => {
    if (group === 'none') setLocalSet([])
    else clearPrecedentSet(group)
  }, [group, clearPrecedentSet])

  const addManyToSelected = useCallback((eventIds: string[]) => {
    if (eventIds.length === 0) return
    if (group === 'none') {
      setLocalSet((prev) => {
        const known = new Set(prev)
        const added = eventIds.filter((id) => !known.has(id))
        return added.length === 0 ? prev : [...prev, ...added]
      })
    } else {
      addPrecedentsToSet(group, eventIds)
    }
  }, [group, addPrecedentsToSet])

  const removeManyFromSelected = useCallback((eventIds: string[]) => {
    if (eventIds.length === 0) return
    if (group === 'none') {
      setLocalSet((prev) => {
        const remove = new Set(eventIds)
        return prev.filter((id) => !remove.has(id))
      })
    } else {
      removePrecedentsFromSet(group, eventIds)
    }
  }, [group, removePrecedentsFromSet])

  const abortRef = useRef<AbortController | null>(null)

  // ── Поиск ──

  const runSearch = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setStatus('loading')
    setError(null)
    setTruncated(false)
    setFoundRows([])

    try {
      const hits = mode === 'fuzzy'
        ? await runFuzzy(fuzzyQuery, ctrl.signal)
        : await runPql(pqlSource, ctrl.signal)
      if (ctrl.signal.aborted) return

      // Дотянуть дату и теги одним батчем (events-info).
      const eventIds = hits.hits.map((h) => h.eventId)
      const infoResp = eventIds.length > 0
        ? await getEventsInfo(eventIds)
        : { rows: [] }
      if (ctrl.signal.aborted) return

      const infoMap = new Map<string, { dateStart: string; tags: string[] }>()
      for (const r of infoResp.rows) infoMap.set(r.eventId, { dateStart: r.dateStart, tags: r.tags })

      const rows: EventRow[] = hits.hits.map((h) => {
        const info = infoMap.get(h.eventId)
        return {
          eventId: h.eventId,
          event: h.event,
          dateStart: info?.dateStart ?? '',
          tags: info?.tags ?? [],
        }
      })

      setFoundRows(rows)
      setTruncated(hits.truncated)
      setStatus('success')

      // обновить кэш
      setEventCache((prev) => {
        const next = new Map(prev)
        for (const r of rows) next.set(r.eventId, r)
        return next
      })
    } catch (e) {
      if (ctrl.signal.aborted) return
      if (e instanceof PrecedentApiError) {
        setError({ message: e.message, line: e.line, column: e.column })
      } else if (e instanceof ContractError) {
        setError({ message: e.message, line: null, column: null })
      } else if (e instanceof Error) {
        setError({ message: e.message, line: null, column: null })
      } else {
        setError({ message: String(e), line: null, column: null })
      }
      setStatus('error')
    }
  }, [mode, fuzzyQuery, pqlSource])

  useEffect(() => () => { if (abortRef.current) abortRef.current.abort() }, [])

  // При смене режима — очистить найденные и поле запроса (драфт §«Смена режима»).
  const setModeAndReset = (next: SearchMode) => {
    if (next === mode) return
    setMode(next)
    setFoundRows([])
    setStatus('idle')
    setError(null)
    setTruncated(false)
    if (next === 'fuzzy') setFuzzyQuery('')
    else setPqlSource(DEFAULT_PQL)
  }

  // CodeMirror extensions для PQL: Ctrl+Enter — выполнить.
  const pqlExtensions = useMemo(
    () => [
      sql({ dialect: PostgreSQL, upperCaseKeywords: false }),
      Prec.highest(
        keymap.of([
          {
            key: 'Mod-Enter',
            run: () => { void runSearch(); return true },
          },
        ]),
      ),
    ],
    [runSearch],
  )

  // ── Список к отображению ──

  const displayedRows: EventRow[] = useMemo(() => {
    if (viewMode === 'found') return foundRows
    // selected: вытаскиваем из кэша; если события нет в кэше — показываем плейсхолдер.
    return selectedIds.map((id) => eventCache.get(id) ?? {
      eventId: id,
      event: '(событие не загружено в этой сессии)',
      dateStart: '',
      tags: [],
    })
  }, [viewMode, foundRows, selectedIds, eventCache])

  // ── Bulk-выделение в режиме «Найденные» ──

  const foundIds = useMemo(() => foundRows.map((r) => r.eventId), [foundRows])
  const allFoundSelected = useMemo(() => {
    if (foundIds.length === 0) return false
    const known = new Set(selectedIds)
    return foundIds.every((id) => known.has(id))
  }, [foundIds, selectedIds])

  const toggleAllFound = useCallback(() => {
    if (foundIds.length === 0) return
    if (allFoundSelected) removeManyFromSelected(foundIds)
    else addManyToSelected(foundIds)
  }, [foundIds, allFoundSelected, addManyToSelected, removeManyFromSelected])

  // ── Статус-строка ──

  const statusLine = useMemo(() => {
    if (status === 'loading') return 'Поиск…'
    if (status === 'success') {
      const tail = truncated ? ` (усечено до ${foundRows.length})` : ''
      return `Найдено: ${foundRows.length}${tail}`
    }
    return ''
  }, [status, foundRows.length, truncated])

  // ── Render ──

  return (
    <div style={rootStyle}>
      {/* Шапка: режим + поле запроса + кнопка */}
      <div style={searchBarStyle}>
        <select
          value={mode}
          onChange={(e) => setModeAndReset(e.target.value as SearchMode)}
          style={modeSelectStyle}
        >
          <option value="fuzzy">Fuzzy</option>
          <option value="pql">PQL</option>
        </select>

        {mode === 'fuzzy' ? (
          <input
            type="text"
            value={fuzzyQuery}
            onChange={(e) => setFuzzyQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') void runSearch() }}
            placeholder="Текст для подстрочного поиска"
            style={fuzzyInputStyle}
          />
        ) : (
          <div style={pqlEditorWrapperStyle}>
            <CodeMirror
              value={pqlSource}
              onChange={setPqlSource}
              extensions={pqlExtensions}
              basicSetup={{
                lineNumbers: false,
                highlightActiveLine: false,
                foldGutter: false,
                bracketMatching: true,
                autocompletion: false,
              }}
              style={pqlEditorStyle}
            />
          </div>
        )}

        <button
          style={runButtonStyle}
          onClick={() => void runSearch()}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? 'Выполнение…' : 'Выполнить'}
        </button>
      </div>

      {/* Переключатель Найденные | Выбранные + Очистить набор */}
      <div style={viewSwitcherStyle}>
        <button
          style={viewMode === 'found' ? viewTabActiveStyle : viewTabStyle}
          onClick={() => setViewMode('found')}
        >
          Найденные
        </button>
        <button
          style={viewMode === 'selected' ? viewTabActiveStyle : viewTabStyle}
          onClick={() => setViewMode('selected')}
        >
          Выбранные ({selectedCount})
        </button>
        {viewMode === 'selected' && selectedCount > 0 && (
          <button onClick={clearSelected} style={clearSetButtonStyle}>
            Очистить набор
          </button>
        )}
        <span style={statusLineStyle}>{statusLine}</span>
      </div>

      {/* Ошибка PQL/контракта */}
      {error && (
        <div style={errorBannerStyle}>
          {error.line != null && (
            <span style={errorPositionStyle}>
              Строка {error.line}{error.column != null ? `, колонка ${error.column}` : ''}:&nbsp;
            </span>
          )}
          {error.message}
        </div>
      )}

      {/* Таблица результатов */}
      <div style={tableWrapperStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              <th style={thCheckboxStyle}>
                {viewMode === 'found' && foundRows.length > 0 && (
                  <SelectAllCheckbox
                    checked={allFoundSelected}
                    indeterminate={!allFoundSelected && foundIds.some((id) => selectedIds.includes(id))}
                    onChange={toggleAllFound}
                    title={allFoundSelected ? 'Снять выделение со всех найденных' : 'Выделить все найденные'}
                  />
                )}
              </th>
              <th style={thDateStyle}>дата</th>
              <th style={thStyle}>event</th>
              <th style={thStyle}>теги</th>
            </tr>
          </thead>
          <tbody>
            {displayedRows.length === 0 ? (
              <tr>
                <td style={emptyCellStyle} colSpan={4}>
                  {viewMode === 'found'
                    ? (status === 'success' ? 'Ничего не найдено' : 'Введите запрос и нажмите «Выполнить»')
                    : 'Набор пуст. Поставьте галочки в режиме «Найденные».'}
                </td>
              </tr>
            ) : (
              displayedRows.map((row) => {
                const checked = selectedIds.includes(row.eventId)
                return (
                  <tr key={row.eventId}>
                    <td style={tdCheckboxStyle}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSelected(row.eventId)}
                      />
                    </td>
                    <td style={tdDateStyle}>{row.dateStart}</td>
                    <td style={tdEventStyle}>{row.event}</td>
                    <td style={tdTagsStyle}>{row.tags.join(', ')}</td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Внутренние хелперы поиска
// ────────────────────────────────────────────────────────────────────────────

interface SelectAllCheckboxProps {
  checked: boolean
  indeterminate: boolean
  onChange: () => void
  title: string
}

function SelectAllCheckbox({ checked, indeterminate, onChange, title }: SelectAllCheckboxProps) {
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate
  }, [indeterminate])
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      title={title}
    />
  )
}

class ContractError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ContractError'
  }
}

async function runFuzzy(
  query: string,
  signal: AbortSignal,
): Promise<{ hits: { eventId: string; event: string }[]; truncated: boolean }> {
  const r = await searchPrecedentsFuzzy(query, signal)
  return { hits: r.hits, truncated: r.truncated }
}

async function runPql(
  source: string,
  signal: AbortSignal,
): Promise<{ hits: { eventId: string; event: string }[]; truncated: boolean }> {
  const r = await searchPrecedents({ source }, signal)
  // Контракт виджета: ровно две колонки — (id|event_id) + event.
  if (r.columns.length !== 2) {
    throw new ContractError(
      `Ожидалось ровно две колонки (id|event_id и event), получено ${r.columns.length}: ` +
      r.columns.map((c) => c.name).join(', '),
    )
  }
  const [first, second] = r.columns
  if (!ID_COLUMN_NAMES.has(first.name) || second.name !== EVENT_COLUMN_NAME) {
    throw new ContractError(
      `Имена колонок должны быть «id» или «event_id» и «event». Получено: ` +
      `«${first.name}», «${second.name}».`,
    )
  }
  const hits = r.rows.map((row) => ({
    eventId: String(row[0]),
    event: row[1] == null ? '' : String(row[1]),
  }))
  return { hits, truncated: r.stats.truncated }
}

// ────────────────────────────────────────────────────────────────────────────
// Стили
// ────────────────────────────────────────────────────────────────────────────

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  gap: 8,
  padding: 8,
}

const searchBarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 8,
  flexShrink: 0,
}

const modeSelectStyle: React.CSSProperties = {
  fontSize: 13,
  padding: '6px 8px',
  border: '1px solid #ccc',
  borderRadius: 4,
  background: '#fff',
  height: 32,
}

const fuzzyInputStyle: React.CSSProperties = {
  flex: 1,
  fontSize: 13,
  padding: '6px 10px',
  border: '1px solid #ccc',
  borderRadius: 4,
  outline: 'none',
  height: 32,
  boxSizing: 'border-box',
}

const pqlEditorWrapperStyle: React.CSSProperties = {
  flex: 1,
  border: '1px solid #ccc',
  borderRadius: 4,
  overflow: 'hidden',
  maxHeight: 140,
}

const pqlEditorStyle: React.CSSProperties = {
  fontSize: 13,
  fontFamily: 'Consolas, Menlo, monospace',
}

const runButtonStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  background: '#2962FF',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
  height: 32,
}

const viewSwitcherStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  flexShrink: 0,
}

const viewTabStyle: React.CSSProperties = {
  padding: '4px 12px',
  fontSize: 12,
  background: '#f5f5f5',
  border: '1px solid #ddd',
  borderRadius: 4,
  cursor: 'pointer',
  color: '#555',
}

const viewTabActiveStyle: React.CSSProperties = {
  ...{
    padding: '4px 12px',
    fontSize: 12,
    borderRadius: 4,
    cursor: 'pointer',
  },
  background: '#2962FF',
  color: '#fff',
  border: '1px solid #2962FF',
}

const clearSetButtonStyle: React.CSSProperties = {
  marginLeft: 8,
  padding: '4px 10px',
  fontSize: 12,
  background: 'transparent',
  border: '1px solid #d33',
  color: '#d33',
  borderRadius: 4,
  cursor: 'pointer',
}

const statusLineStyle: React.CSSProperties = {
  marginLeft: 'auto',
  fontSize: 12,
  color: '#555',
}

const errorBannerStyle: React.CSSProperties = {
  padding: '8px 12px',
  background: '#fdecea',
  border: '1px solid #f5a8a3',
  borderRadius: 4,
  color: '#a01919',
  fontSize: 12,
  fontFamily: 'Consolas, Menlo, monospace',
  whiteSpace: 'pre-wrap',
  flexShrink: 0,
}

const errorPositionStyle: React.CSSProperties = {
  fontWeight: 600,
}

const tableWrapperStyle: React.CSSProperties = {
  flex: 1,
  minHeight: 0,
  overflow: 'auto',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
}

const tableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 12,
}

const thStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '6px 10px',
  background: '#f5f5f5',
  borderBottom: '1px solid #e0e0e0',
  position: 'sticky',
  top: 0,
  fontWeight: 600,
}

const thCheckboxStyle: React.CSSProperties = {
  ...{ background: '#f5f5f5', borderBottom: '1px solid #e0e0e0', position: 'sticky', top: 0 },
  width: 28,
  padding: '6px 6px',
}

const tdCheckboxStyle: React.CSSProperties = {
  padding: '4px 6px',
  borderBottom: '1px solid #f0f0f0',
  textAlign: 'center',
  width: 28,
}

const thDateStyle: React.CSSProperties = {
  ...thStyle,
  whiteSpace: 'nowrap',
  width: 96,
}

const tdDateStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderBottom: '1px solid #f0f0f0',
  whiteSpace: 'nowrap',
  color: '#444',
  fontVariantNumeric: 'tabular-nums',
  width: 96,
}

const tdEventStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderBottom: '1px solid #f0f0f0',
}

const tdTagsStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderBottom: '1px solid #f0f0f0',
  color: '#666',
  whiteSpace: 'nowrap',
}

const emptyCellStyle: React.CSSProperties = {
  padding: '12px',
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}
