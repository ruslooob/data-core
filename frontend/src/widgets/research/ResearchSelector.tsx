import { useState } from 'react'
import { useActiveResearch } from '../../contexts/ActiveResearch'

/**
 * Компактный селектор активного исследования для верхнего тулбара.
 * Открывает выпадающий список всех исследований; внизу — пункт «Сменить».
 */
export function ResearchSelector() {
  const { activeResearch, allResearch, setActiveResearchId } = useActiveResearch()
  const [open, setOpen] = useState(false)

  if (!activeResearch) {
    return null
  }

  return (
    <div style={containerStyle}>
      <button onClick={() => setOpen(!open)} style={triggerStyle}>
        <span style={labelTextStyle}>Исследование:</span>
        <span style={nameTextStyle}>{activeResearch.name}</span>
        <span style={chevronStyle}>▾</span>
      </button>
      {open && (
        <div style={dropdownStyle}>
          {allResearch.map((r) => (
            <button
              key={r.id}
              onClick={() => {
                setActiveResearchId(r.id)
                setOpen(false)
              }}
              style={r.id === activeResearch.id ? itemActiveStyle : itemStyle}
            >
              {r.name}
            </button>
          ))}
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
  minWidth: 240,
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
