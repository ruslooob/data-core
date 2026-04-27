import { useCallback, useEffect, useRef, useState } from 'react'
import { PrecedentApiError, searchPrecedents } from '../api/client'
import type { PrecedentSearchResult, PrecedentValue } from '../api/types'
import type { WidgetGroup } from './chartSync'

interface PrecedentEditorWidgetProps {
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

export function PrecedentEditorWidget(_props: PrecedentEditorWidgetProps) {
  const [source, setSource] = useState<string>(DEFAULT_QUERY)
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<PrecedentSearchResult | null>(null)
  const [error, setError] = useState<ErrorState | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const run = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setStatus('loading')
    setError(null)

    try {
      const r = await searchPrecedents({ source }, ctrl.signal)
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
  }, [source])

  useEffect(() => {
    return () => {
      if (abortRef.current) abortRef.current.abort()
    }
  }, [])

  const onTextareaKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault()
      void run()
    }
  }

  return (
    <div style={rootStyle}>
      <textarea
        style={textareaStyle}
        value={source}
        onChange={(e) => setSource(e.target.value)}
        onKeyDown={onTextareaKeyDown}
        spellCheck={false}
        placeholder="SELECT ... FROM tagged_events WHERE tag = 'LKOH' LIMIT 20"
      />

      <div style={toolbarStyle}>
        <button
          style={runButtonStyle}
          onClick={() => void run()}
          disabled={status === 'loading'}
        >
          {status === 'loading' ? 'Выполнение…' : 'Выполнить'}
        </button>
        <span style={hintStyle}>Ctrl+Enter</span>
        <span style={statusStyle}>{renderStatusLine(status, result, error)}</span>
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

function renderStatusLine(
  status: Status,
  result: PrecedentSearchResult | null,
  error: ErrorState | null,
): string {
  if (status === 'loading') return ''
  if (status === 'error' && error) return ''
  if (status === 'success' && result) {
    const { rows, stats } = result
    const truncatedSuffix = stats.truncated ? ' (усечено)' : ''
    return `Строк: ${rows.length}${truncatedSuffix} · ${stats.durationMs} мс`
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

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  gap: 8,
  padding: 8,
}

const textareaStyle: React.CSSProperties = {
  fontFamily: 'Consolas, Menlo, monospace',
  fontSize: 13,
  padding: 8,
  border: '1px solid #ccc',
  borderRadius: 4,
  resize: 'vertical',
  minHeight: 120,
  outline: 'none',
}

const toolbarStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 12,
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
  ...{
    padding: '4px 10px',
    borderBottom: '1px solid #f0f0f0',
    whiteSpace: 'nowrap',
  },
  color: '#bbb',
  fontStyle: 'italic',
}

const emptyCellStyle: React.CSSProperties = {
  padding: '12px',
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}
