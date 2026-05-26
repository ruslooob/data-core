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
} from '../api/client'
import type {
  PrecedentSearchResult,
  PrecedentValue,
  SavedQuery,
} from '../api/types'
import type { WidgetGroup } from './chartSync'
import { SearchablePicker } from './SearchablePicker'

interface PqlEditorWidgetProps {
  group: WidgetGroup
}

const DEFAULT_QUERY = `SELECT date_start, event
FROM tagged_events
WHERE tag = 'SANCTIONS'
ORDER BY date_start DESC
LIMIT 20`

type Status = 'idle' | 'loading' | 'success' | 'error'

interface ErrorState {
  message: string
  line: number | null
  column: number | null
}

export function PqlEditorWidget(_props: PqlEditorWidgetProps) {
  const [source, setSource] = useState<string>(DEFAULT_QUERY)
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<PrecedentSearchResult | null>(null)
  const [error, setError] = useState<ErrorState | null>(null)
  const [savedQueries, setSavedQueries] = useState<SavedQuery[]>([])
  const [savePromptOpen, setSavePromptOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const sourceRef = useRef(source)
  const savePromptRef = useRef<HTMLDivElement>(null)

  useEffect(() => { sourceRef.current = source }, [source])

  const run = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setStatus('loading')
    setError(null)

    try {
      const r = await searchPrecedents({ source: sourceRef.current }, ctrl.signal)
      if (ctrl.signal.aborted) return
      setResult(r)
      setStatus('success')
    } catch (e) {
      if (ctrl.signal.aborted) return
      if (e instanceof PrecedentApiError) {
        setError({ message: e.message, line: e.line, column: e.column })
      } else if (e instanceof Error) {
        setError({ message: e.message, line: null, column: null })
      } else {
        setError({ message: String(e), line: null, column: null })
      }
      setStatus('error')
    }
  }, [])

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  // CodeMirror extensions: SQL диалект (Postgres-совместимый, как мы и решили)
  // плюс высоко-приоритетный keymap, чтобы Ctrl+Enter не съедал стандартный insertNewline.
  const extensions = useMemo(
    () => [
      sql({ dialect: PostgreSQL, upperCaseKeywords: false }),
      Prec.highest(
        keymap.of([
          {
            key: 'Mod-Enter',
            run: () => {
              void run()
              return true
            },
          },
        ]),
      ),
    ],
    [run],
  )

  // ── Сохранённые запросы ──

  const refreshSavedQueries = useCallback(async () => {
    try {
      const list = await listSavedQueries('PQL')
      setSavedQueries(list)
    } catch {
      // молча — кнопки просто покажут пустой список
    }
  }, [])

  useEffect(() => { void refreshSavedQueries() }, [refreshSavedQueries])

  const onPickSavedQuery = (q: SavedQuery) => {
    setSource(q.source)
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
      const saved = await saveSavedQuery({ name, source, kind: 'PQL' })
      setSavedQueries((prev) => [saved, ...prev])
      setSavePromptOpen(false)
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div style={rootStyle}>
      <div style={editorWrapperStyle}>
        <CodeMirror
          value={source}
          onChange={setSource}
          extensions={extensions}
          basicSetup={{
            lineNumbers: false,
            highlightActiveLine: false,
            foldGutter: false,
            bracketMatching: true,
            autocompletion: false,
          }}
          style={editorStyle}
        />
      </div>

      <div style={toolbarStyle}>
        <button
          style={runButtonStyle}
          onClick={() => void run()}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? 'Выполнение…' : 'Выполнить'}
        </button>
        <span style={hintStyle}>Ctrl+Enter</span>

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
          title="Загрузить запрос"
          emptyText="Пока нет сохранённых запросов"
        />

        <span style={statusStyle}>{renderStatusLine(status, result)}</span>
      </div>

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

      {result && status === 'success' && (
        <div style={tableWrapperStyle}>
          <table style={tableStyle}>
            <thead>
              <tr>
                {result.columns.map((c) => (
                  <th key={c.name} style={thStyle} title={c.type}>
                    {c.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows.length === 0 ? (
                <tr>
                  <td style={emptyCellStyle} colSpan={result.columns.length || 1}>
                    Совпадений не найдено
                  </td>
                </tr>
              ) : (
                result.rows.map((row, i) => (
                  <tr key={i}>
                    {row.map((v, j) => (
                      <td key={j} style={v === null ? nullCellStyle : tdStyle}>
                        {formatValue(v)}
                      </td>
                    ))}
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function renderStatusLine(status: Status, result: PrecedentSearchResult | null): string {
  if (status === 'success' && result) {
    const truncated = result.stats.truncated ? ' (усечено)' : ''
    return `Строк: ${result.rows.length}${truncated} · ${result.stats.durationMs} мс`
  }
  return ''
}

function formatValue(v: PrecedentValue): string {
  if (v === null) return '—'
  if (typeof v === 'number') {
    if (Number.isInteger(v)) return String(v)
    return v.toFixed(6).replace(/\.?0+$/, '')
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
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

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  gap: 8,
  padding: 8,
}

const editorWrapperStyle: React.CSSProperties = {
  border: '1px solid #ccc',
  borderRadius: 4,
  overflow: 'hidden',
  flexShrink: 0,
}

const editorStyle: React.CSSProperties = {
  fontSize: 13,
  fontFamily: 'Consolas, Menlo, monospace',
}

const toolbarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  flexShrink: 0,
}

const runButtonStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  background: '#2962FF',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const hintStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#999',
  marginRight: 8,
}

const iconButtonContainerStyle: React.CSSProperties = {
  position: 'relative',
}

const iconButtonStyle: React.CSSProperties = {
  width: 28,
  height: 28,
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

const statusStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#555',
  marginLeft: 'auto',
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
  fontFamily: 'Consolas, Menlo, monospace',
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

const tdStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderBottom: '1px solid #f0f0f0',
  whiteSpace: 'nowrap',
}

const nullCellStyle: React.CSSProperties = {
  padding: '4px 10px',
  borderBottom: '1px solid #f0f0f0',
  whiteSpace: 'nowrap',
  color: '#bbb',
  fontStyle: 'italic',
}

const emptyCellStyle: React.CSSProperties = {
  padding: '12px',
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}
