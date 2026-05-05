import { useCallback, useEffect, useState } from 'react'
import { getResearchReport } from '../../api/client'
import { useActiveResearch } from '../../contexts/ActiveResearch'

/**
 * Виджет отчёта по активному исследованию.
 * Показывает markdown как preformatted-текст и кнопку «Скачать .md».
 */
export function ResearchReportWidget() {
  const { activeResearch, activeResearchId } = useActiveResearch()
  const [text, setText] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    if (!activeResearchId) return
    setLoading(true)
    setError(null)
    try {
      setText(await getResearchReport(activeResearchId))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [activeResearchId])

  useEffect(() => { void refresh() }, [refresh])

  const onDownload = () => {
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const safeName = (activeResearch?.name ?? 'research')
      .toLowerCase().replace(/[^a-z0-9_-]+/gi, '-')
    a.download = `${safeName || 'research'}.md`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div style={rootStyle}>
      <div style={toolbarStyle}>
        <button onClick={() => void refresh()} style={refreshButtonStyle} disabled={loading}>
          {loading ? 'Обновление…' : 'Обновить'}
        </button>
        <button onClick={onDownload} style={downloadButtonStyle} disabled={!text}>
          Скачать .md
        </button>
      </div>
      {error && <div style={errorStyle}>{error}</div>}
      <pre style={previewStyle}>{text}</pre>
    </div>
  )
}

const rootStyle: React.CSSProperties = {
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  padding: 12,
  gap: 8,
}

const toolbarStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
}

const refreshButtonStyle: React.CSSProperties = {
  padding: '6px 12px',
  fontSize: 13,
  background: '#fff',
  border: '1px solid #bbb',
  borderRadius: 4,
  cursor: 'pointer',
}

const downloadButtonStyle: React.CSSProperties = {
  padding: '6px 12px',
  fontSize: 13,
  background: '#4CAF50',
  color: 'white',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const errorStyle: React.CSSProperties = {
  color: '#c62828',
  fontSize: 13,
  padding: '6px 10px',
  background: '#fde6e6',
  borderRadius: 4,
}

const previewStyle: React.CSSProperties = {
  flex: 1,
  margin: 0,
  padding: 12,
  background: '#fafafa',
  border: '1px solid #eee',
  borderRadius: 4,
  fontFamily: '"Consolas", "Monaco", monospace',
  fontSize: 12,
  lineHeight: 1.5,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflow: 'auto',
}
