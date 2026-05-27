import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { sql, PostgreSQL } from '@codemirror/lang-sql'
import { Prec } from '@codemirror/state'
import { keymap } from '@codemirror/view'
import {
  PrecedentApiError,
  listSavedQueries,
  saveSavedQuery,
  searchPrecedents,
  searchPrecedentsFuzzy,
} from '../api/client'
import type { PrecedentEvent, SavedQuery, SavedQueryKind } from '../api/types'
import type { WidgetGroup } from './chartSync'
import {
  selectPrecedentSet,
  useGroupStore,
} from './groupStore'
import { SearchablePicker } from './SearchablePicker'

interface PrecedentSearchWidgetProps {
  group: WidgetGroup
}

type SearchMode = 'fuzzy' | 'pql'
type ViewMode = 'found' | 'selected'
type Status = 'idle' | 'loading' | 'success' | 'error'

interface ErrorState {
  message: string
  line: number | null
  column: number | null
}

const DEFAULT_PQL = `SELECT id, event, date_start
FROM events
WHERE date_start > DATE '2020-01-01'
ORDER BY date_start DESC
LIMIT 50`

const ID_COLUMN_NAMES = new Set(['id', 'event_id'])
const EVENT_COLUMN_NAME = 'event'
const DATE_COLUMN_NAME = 'date_start'

export function PrecedentSearchWidget({ group }: PrecedentSearchWidgetProps) {
  const [mode, setMode] = useState<SearchMode>('fuzzy')
  const [fuzzyQuery, setFuzzyQuery] = useState('')
  const [pqlSource, setPqlSource] = useState(DEFAULT_PQL)
  const [viewMode, setViewMode] = useState<ViewMode>('found')

  const [status, setStatus] = useState<Status>('idle')
  const [error, setError] = useState<ErrorState | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [foundRows, setFoundRows] = useState<PrecedentEvent[]>([])

  // Локальный набор для группы `none` — в groupStore группа `none` не пишется,
  // потому что несколько виджетов в `none` не должны делиться состоянием.
  const [localSet, setLocalSet] = useState<PrecedentEvent[]>([])

  // Сохранённые запросы текущего режима (FUZZY или PQL)
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>([])
  const [savePromptOpen, setSavePromptOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const savePromptRef = useRef<HTMLDivElement>(null)

  const savedKind: SavedQueryKind = mode === 'fuzzy' ? 'FUZZY' : 'PQL'
  const currentQueryText = mode === 'fuzzy' ? fuzzyQuery : pqlSource

  const groupSet = useGroupStore(selectPrecedentSet(group))
  const togglePrecedentInSet = useGroupStore((s) => s.togglePrecedentInSet)
  const addPrecedentsToSet = useGroupStore((s) => s.addPrecedentsToSet)
  const removePrecedentsFromSet = useGroupStore((s) => s.removePrecedentsFromSet)
  const clearPrecedentSet = useGroupStore((s) => s.clearPrecedentSet)

  const selectedEvents = group === 'none' ? localSet : groupSet
  const selectedCount = selectedEvents.length
  // Множество id выбранных — для отметки чекбоксов в режиме «Найденные»
  const selectedIds = useMemo(
    () => new Set(selectedEvents.map((e) => e.eventId)),
    [selectedEvents],
  )

  const toggleSelected = useCallback((event: PrecedentEvent) => {
    if (group === 'none') {
      setLocalSet((prev) =>
        prev.some((e) => e.eventId === event.eventId)
          ? prev.filter((e) => e.eventId !== event.eventId)
          : [...prev, event],
      )
    } else {
      togglePrecedentInSet(group, event)
    }
  }, [group, togglePrecedentInSet])

  const clearSelected = useCallback(() => {
    if (group === 'none') setLocalSet([])
    else clearPrecedentSet(group)
  }, [group, clearPrecedentSet])

  const addManyToSelected = useCallback((events: PrecedentEvent[]) => {
    if (events.length === 0) return
    if (group === 'none') {
      setLocalSet((prev) => {
        const known = new Set(prev.map((e) => e.eventId))
        const added = events.filter((e) => !known.has(e.eventId))
        return added.length === 0 ? prev : [...prev, ...added]
      })
    } else {
      addPrecedentsToSet(group, events)
    }
  }, [group, addPrecedentsToSet])

  const removeManyFromSelected = useCallback((eventIds: string[]) => {
    if (eventIds.length === 0) return
    if (group === 'none') {
      setLocalSet((prev) => {
        const remove = new Set(eventIds)
        return prev.filter((e) => !remove.has(e.eventId))
      })
    } else {
      removePrecedentsFromSet(group, eventIds)
    }
  }, [group, removePrecedentsFromSet])

  // Перенос выбора при смене группы: набор не сбрасывается, а переезжает в новую
  // группу (none → цвет, цвет → none, цвет → цвет). Слияние по eventId — ничего
  // не теряется, даже если в целевой группе уже что-то выбрано.
  const prevGroupRef = useRef(group)
  useEffect(() => {
    const prev = prevGroupRef.current
    if (prev === group) return
    prevGroupRef.current = group
    const prevSelection = prev === 'none'
      ? localSet
      : useGroupStore.getState().precedentEvents[prev]
    if (prevSelection.length === 0) return
    if (group === 'none') {
      setLocalSet((cur) => {
        const known = new Set(cur.map((e) => e.eventId))
        const added = prevSelection.filter((e) => !known.has(e.eventId))
        return added.length === 0 ? cur : [...cur, ...added]
      })
    } else {
      addPrecedentsToSet(group, prevSelection)
    }
  }, [group, localSet, addPrecedentsToSet])

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
      const result = mode === 'fuzzy'
        ? await runFuzzy(fuzzyQuery, ctrl.signal)
        : await runPql(pqlSource, ctrl.signal)
      if (ctrl.signal.aborted) return

      setFoundRows(result.rows)
      setTruncated(result.truncated)
      setStatus('success')
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

  // ── Сохранённые запросы (своя подборка на каждый режим) ──

  const refreshSavedQueries = useCallback(async () => {
    try {
      setSavedQueries(await listSavedQueries(savedKind))
    } catch {
      // молча — список просто будет пустым
    }
  }, [savedKind])

  useEffect(() => { void refreshSavedQueries() }, [refreshSavedQueries])

  const onPickSavedQuery = (q: SavedQuery) => {
    if (mode === 'fuzzy') setFuzzyQuery(q.source)
    else setPqlSource(q.source)
  }

  const openSavePrompt = () => {
    setSaveName('')
    setSaveError(null)
    setSavePromptOpen(true)
  }

  const submitSave = async () => {
    const name = saveName.trim()
    if (!name) {
      setSaveError('Введите имя')
      return
    }
    try {
      const saved = await saveSavedQuery({ name, source: currentQueryText, kind: savedKind })
      setSavedQueries((prev) => [saved, ...prev])
      setSavePromptOpen(false)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    }
  }

  // Click-outside для save-промпта
  useEffect(() => {
    if (!savePromptOpen) return
    const handler = (e: MouseEvent) => {
      if (savePromptRef.current && !savePromptRef.current.contains(e.target as Node)) {
        setSavePromptOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [savePromptOpen])

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

  const displayedRows = viewMode === 'found' ? foundRows : selectedEvents

  // ── Bulk-выделение в режиме «Найденные» ──

  const foundIds = useMemo(() => foundRows.map((r) => r.eventId), [foundRows])
  const allFoundSelected = useMemo(() => {
    if (foundIds.length === 0) return false
    return foundIds.every((id) => selectedIds.has(id))
  }, [foundIds, selectedIds])

  const toggleAllFound = useCallback(() => {
    if (foundRows.length === 0) return
    if (allFoundSelected) removeManyFromSelected(foundRows.map((r) => r.eventId))
    else addManyToSelected(foundRows)
  }, [foundRows, allFoundSelected, addManyToSelected, removeManyFromSelected])

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

        <div ref={savePromptRef} style={iconButtonContainerStyle}>
          <button
            style={iconButtonStyle}
            title="Сохранить запрос"
            onClick={openSavePrompt}
            aria-label="Сохранить запрос"
          >
            <FloppyIcon />
          </button>
          {savePromptOpen && (
            <div style={savePromptStyle}>
              <input
                type="text"
                placeholder="Имя запроса"
                value={saveName}
                onChange={(e) => { setSaveName(e.target.value); setSaveError(null) }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') void submitSave()
                  if (e.key === 'Escape') setSavePromptOpen(false)
                }}
                autoFocus
                style={savePromptInputStyle}
              />
              <button style={savePromptButtonStyle} onClick={() => void submitSave()}>Сохранить</button>
              {saveError && <div style={savePromptErrorStyle}>{saveError}</div>}
            </div>
          )}
        </div>

        <SearchablePicker<SavedQuery>
          items={savedQueries}
          getKey={(q) => q.id}
          getName={(q) => q.name}
          onPick={onPickSavedQuery}
          title="Загрузить сохранённый запрос"
          emptyText="Пока нет сохранённых запросов"
        />
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
                    indeterminate={!allFoundSelected && foundIds.some((id) => selectedIds.has(id))}
                    onChange={toggleAllFound}
                    title={allFoundSelected ? 'Снять выделение со всех найденных' : 'Выделить все найденные'}
                  />
                )}
              </th>
              <th style={thDateStyle}>дата</th>
              <th style={thStyle}>event</th>
            </tr>
          </thead>
          <tbody>
            {displayedRows.length === 0 ? (
              <tr>
                <td style={emptyCellStyle} colSpan={3}>
                  {viewMode === 'found'
                    ? (status === 'success' ? 'Ничего не найдено' : 'Введите запрос и нажмите «Выполнить»')
                    : 'Набор пуст. Поставьте галочки в режиме «Найденные».'}
                </td>
              </tr>
            ) : (
              displayedRows.map((row) => {
                const checked = selectedIds.has(row.eventId)
                return (
                  <tr key={row.eventId}>
                    <td style={tdCheckboxStyle}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleSelected(row)}
                      />
                    </td>
                    <td style={tdDateStyle}>{row.dateStart}</td>
                    <td style={tdEventStyle}>{row.event}</td>
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

function FloppyIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <polyline points="17 21 17 13 7 13 7 21" />
      <polyline points="7 3 7 8 15 8" />
    </svg>
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
): Promise<{ rows: PrecedentEvent[]; truncated: boolean }> {
  const r = await searchPrecedentsFuzzy(query, signal)
  const rows = r.hits.map((h) => ({
    eventId: h.eventId,
    event: h.event,
    dateStart: h.dateStart,
  }))
  return { rows, truncated: r.truncated }
}

async function runPql(
  source: string,
  signal: AbortSignal,
): Promise<{ rows: PrecedentEvent[]; truncated: boolean }> {
  const r = await searchPrecedents({ source }, signal)
  // Контракт виджета: ровно три колонки — (id|event_id), event, date_start.
  if (r.columns.length !== 3) {
    throw new ContractError(
      `Ожидалось ровно три колонки (id|event_id, event, date_start), получено ${r.columns.length}: ` +
      r.columns.map((c) => c.name).join(', '),
    )
  }
  const [first, second, third] = r.columns
  if (
    !ID_COLUMN_NAMES.has(first.name) ||
    second.name !== EVENT_COLUMN_NAME ||
    third.name !== DATE_COLUMN_NAME
  ) {
    throw new ContractError(
      `Имена колонок должны быть «id»/«event_id», «event», «date_start». Получено: ` +
      `«${first.name}», «${second.name}», «${third.name}».`,
    )
  }
  const rows = r.rows.map((row) => ({
    eventId: String(row[0]),
    event: row[1] == null ? '' : String(row[1]),
    dateStart: row[2] == null ? '' : String(row[2]),
  }))
  return { rows, truncated: r.stats.truncated }
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

const iconButtonContainerStyle: React.CSSProperties = {
  position: 'relative',
}

const iconButtonStyle: React.CSSProperties = {
  width: 32,
  height: 32,
  padding: 0,
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'transparent',
  border: '1px solid #ccc',
  borderRadius: 4,
  color: '#555',
  cursor: 'pointer',
}

const savePromptStyle: React.CSSProperties = {
  position: 'absolute',
  top: 'calc(100% + 4px)',
  left: 0,
  background: '#fff',
  border: '1px solid #ccc',
  borderRadius: 4,
  boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
  padding: 8,
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  minWidth: 220,
  zIndex: 100,
}

const savePromptInputStyle: React.CSSProperties = {
  fontSize: 13,
  padding: '6px 8px',
  border: '1px solid #ccc',
  borderRadius: 4,
  outline: 'none',
}

const savePromptButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  background: '#2962FF',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const savePromptErrorStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#a01919',
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

const emptyCellStyle: React.CSSProperties = {
  padding: '12px',
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}
