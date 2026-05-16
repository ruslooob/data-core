import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

interface SearchablePickerProps<T> {
  items: T[]
  getKey: (item: T) => string
  getName: (item: T) => string
  renderMeta?: (item: T) => React.ReactNode
  onPick: (item: T) => void
  title?: string
  emptyText?: string
  noMatchesText?: string
  width?: number
}

/**
 * Кнопка с иконкой поиска, раскрывающая выпадающий список с фильтром по имени.
 * Используется для импорта прецедентов в PQL Editor и для импорта правил/окружений в BacktestEditor.
 */
export function SearchablePicker<T>({
  items,
  getKey,
  getName,
  renderMeta,
  onPick,
  title = 'Загрузить',
  emptyText = 'Список пуст',
  noMatchesText = 'Нет совпадений',
  width = 280,
}: SearchablePickerProps<T>) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const buttonRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        buttonRef.current && !buttonRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((x) => getName(x).toLowerCase().includes(q))
  }, [items, search, getName])

  const openDropdown = () => {
    if (buttonRef.current) {
      const rect = buttonRef.current.getBoundingClientRect()
      setPos({ top: rect.bottom + 4, left: rect.left })
    }
    setSearch('')
    setOpen(true)
  }

  return (
    <>
      <button
        ref={buttonRef}
        style={iconButtonStyle}
        title={title}
        onClick={openDropdown}
        aria-label={title}
      >
        <SearchIcon />
      </button>
      {open && createPortal(
        <div
          ref={dropdownRef}
          style={{ ...dropdownStyle, top: pos.top, left: pos.left, width }}
        >
          <input
            type="text"
            placeholder="Поиск по имени"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
            style={searchInputStyle}
          />
          <div style={listStyle}>
            {filtered.length === 0 ? (
              <div style={emptyStyle}>
                {items.length === 0 ? emptyText : noMatchesText}
              </div>
            ) : (
              filtered.map((item) => (
                <div
                  key={getKey(item)}
                  onClick={() => { onPick(item); setOpen(false) }}
                  style={itemStyle}
                >
                  <span style={itemNameStyle}>{getName(item)}</span>
                  {renderMeta && <span style={itemMetaStyle}>{renderMeta(item)}</span>}
                </div>
              ))
            )}
          </div>
        </div>,
        document.body,
      )}
    </>
  )
}

function SearchIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="11" cy="11" r="8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  )
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

const dropdownStyle: React.CSSProperties = {
  position: 'fixed',
  background: '#fff',
  border: '1px solid #ccc',
  borderRadius: 4,
  boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
  display: 'flex',
  flexDirection: 'column',
  maxHeight: 280,
  zIndex: 10000,
  overflow: 'hidden',
}

const searchInputStyle: React.CSSProperties = {
  fontSize: 13,
  padding: '8px 10px',
  border: 'none',
  borderBottom: '1px solid #eee',
  outline: 'none',
}

const listStyle: React.CSSProperties = {
  overflowY: 'auto',
  maxHeight: 220,
}

const itemStyle: React.CSSProperties = {
  padding: '6px 12px',
  fontSize: 13,
  cursor: 'pointer',
  borderBottom: '1px solid #f5f5f5',
  display: 'flex',
  justifyContent: 'space-between',
  gap: 8,
  alignItems: 'center',
}

const itemNameStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}

const itemMetaStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#888',
  flexShrink: 0,
}

const emptyStyle: React.CSSProperties = {
  padding: 12,
  fontSize: 12,
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}
