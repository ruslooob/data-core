import { useState } from 'react'
import { useActiveResearch } from '../../contexts/ActiveResearch'

/**
 * Виджет отчёта по активному исследованию.
 * Сейчас — только дропдаун экспорта (CSV работает, PDF — заглушка).
 * Полноценный журнал исследования с заметками появится позже.
 */
export function ResearchReportWidget() {
  const { activeResearchId } = useActiveResearch()
  const [exportMenuOpen, setExportMenuOpen] = useState(false)

  const onExportCsv = () => {
    if (!activeResearchId) return
    setExportMenuOpen(false)
    window.location.href = `/api/research/${activeResearchId}/export?format=csv`
  }

  const onExportPdf = () => {
    setExportMenuOpen(false)
    alert('PDF-экспорт пока не реализован')
  }

  return (
    <div style={rootStyle}>
      <div style={toolbarStyle}>
        <div style={exportWrapStyle}>
          <button
            onClick={() => setExportMenuOpen((v) => !v)}
            style={downloadButtonStyle}
            disabled={!activeResearchId}
          >
            Скачать ▾
          </button>
          {exportMenuOpen && (
            <div style={dropdownMenuStyle}>
              <button onClick={onExportCsv} style={menuItemStyle}>CSV</button>
              <button onClick={onExportPdf} style={menuItemStyle}>PDF</button>
            </div>
          )}
        </div>
      </div>
      <div style={placeholderStyle}>
        Полноценный журнал исследования появится позже.
      </div>
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
  position: 'relative',
}

const exportWrapStyle: React.CSSProperties = {
  position: 'relative',
}

const dropdownMenuStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  marginTop: 4,
  backgroundColor: 'white',
  border: '1px solid #ddd',
  borderRadius: 6,
  boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
  minWidth: 140,
  zIndex: 100,
}

const menuItemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '8px 14px',
  textAlign: 'left',
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  fontSize: 13,
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

const placeholderStyle: React.CSSProperties = {
  flex: 1,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  color: '#999',
  fontSize: 13,
  fontStyle: 'italic',
}
