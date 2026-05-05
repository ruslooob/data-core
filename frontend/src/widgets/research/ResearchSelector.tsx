import { useState } from 'react'
import { createResearch } from '../../api/client'
import { useActiveResearch } from '../../contexts/ActiveResearch'

/**
 * Компактный селектор активного исследования для верхнего тулбара.
 * В выпадающем списке — все существующие исследования и пункт «+ Создать новое».
 */
export function ResearchSelector() {
  const { activeResearch, allResearch, setActiveResearchId, reload } = useActiveResearch()
  const [open, setOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!activeResearch) {
    return null
  }

  const closeDropdown = () => {
    setOpen(false)
    setCreating(false)
    setNewName('')
    setNewDescription('')
    setError(null)
  }

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) {
      setError('Введите имя исследования')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created = await createResearch({
        name,
        description: newDescription.trim() || null,
      })
      await reload()
      setActiveResearchId(created.id)
      closeDropdown()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось создать')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={containerStyle}>
      <button onClick={() => (open ? closeDropdown() : setOpen(true))} style={triggerStyle}>
        <span style={labelTextStyle}>Исследование:</span>
        <span style={nameTextStyle}>{activeResearch.name}</span>
        <span style={chevronStyle}>▾</span>
      </button>
      {open && (
        <div style={dropdownStyle}>
          {!creating && (
            <>
              {allResearch.map((r) => (
                <button
                  key={r.id}
                  onClick={() => {
                    setActiveResearchId(r.id)
                    closeDropdown()
                  }}
                  style={r.id === activeResearch.id ? itemActiveStyle : itemStyle}
                >
                  {r.name}
                </button>
              ))}
              <div style={dividerStyle} />
              <button onClick={() => setCreating(true)} style={itemActionStyle}>
                + Создать новое
              </button>
            </>
          )}
          {creating && (
            <div style={createFormStyle}>
              <label style={labelStyle}>
                Имя
                <input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="например: Защитные механики"
                  style={inputStyle}
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !busy) void handleCreate()
                    if (e.key === 'Escape') closeDropdown()
                  }}
                />
              </label>
              <label style={labelStyle}>
                Описание идеи (опционально)
                <textarea
                  value={newDescription}
                  onChange={(e) => setNewDescription(e.target.value)}
                  placeholder="Что хотим выяснить, какие гипотезы планируем"
                  style={textareaStyle}
                  rows={3}
                />
              </label>
              {error && <div style={errorStyle}>{error}</div>}
              <div style={createButtonsStyle}>
                <button onClick={() => setCreating(false)} style={secondaryButtonStyle} disabled={busy}>
                  Отмена
                </button>
                <button onClick={() => void handleCreate()} style={primaryButtonStyle} disabled={busy}>
                  {busy ? 'Создаём…' : 'Создать и открыть'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const containerStyle: React.CSSProperties = {
  position: 'relative',
}

const triggerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 6,
  padding: '8px 14px',
  fontSize: 13,
  backgroundColor: '#f5f5f5',
  border: '1px solid #ddd',
  borderRadius: 6,
  cursor: 'pointer',
}

const labelTextStyle: React.CSSProperties = {
  color: '#888',
}

const nameTextStyle: React.CSSProperties = {
  fontWeight: 500,
}

const chevronStyle: React.CSSProperties = {
  color: '#888',
  marginLeft: 2,
}

const dropdownStyle: React.CSSProperties = {
  position: 'absolute',
  top: '100%',
  left: 0,
  marginTop: 4,
  backgroundColor: 'white',
  border: '1px solid #ddd',
  borderRadius: 6,
  boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
  minWidth: 280,
  zIndex: 110,
}

const itemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '10px 14px',
  textAlign: 'left',
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  fontSize: 13,
}

const itemActiveStyle: React.CSSProperties = {
  ...itemStyle,
  backgroundColor: '#f0f9f0',
  fontWeight: 500,
}

const itemActionStyle: React.CSSProperties = {
  ...itemStyle,
  color: '#2962FF',
  fontWeight: 500,
}

const dividerStyle: React.CSSProperties = {
  height: 1,
  backgroundColor: '#eee',
  margin: '4px 0',
}

const createFormStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  padding: 12,
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: 12,
  color: '#444',
}

const inputStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
}

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  resize: 'vertical',
  fontFamily: 'inherit',
}

const errorStyle: React.CSSProperties = {
  color: '#c62828',
  fontSize: 12,
}

const createButtonsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 6,
  justifyContent: 'flex-end',
}

const primaryButtonStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  backgroundColor: '#4CAF50',
  color: 'white',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
  fontWeight: 500,
}

const secondaryButtonStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  backgroundColor: '#eee',
  color: '#333',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}
