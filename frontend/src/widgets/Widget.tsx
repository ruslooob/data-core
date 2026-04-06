import { useRef, useState, type ReactNode } from 'react'

interface WidgetProps {
  title: string
  initialX: number
  initialY: number
  initialWidth: number
  initialHeight: number
  zIndex: number
  onClose: () => void
  onFocus: () => void
  headerLeft?: ReactNode
  children: ReactNode
}

export function Widget({
  title,
  initialX,
  initialY,
  initialWidth,
  initialHeight,
  zIndex,
  onClose,
  onFocus,
  headerLeft,
  children,
}: WidgetProps) {
  const [position, setPosition] = useState({ x: initialX, y: initialY })
  const dragOffsetRef = useRef<{ dx: number; dy: number } | null>(null)

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).tagName === 'BUTTON') return
    onFocus()
    dragOffsetRef.current = {
      dx: e.clientX - position.x,
      dy: e.clientY - position.y,
    }

    const handleMouseMove = (ev: MouseEvent) => {
      if (!dragOffsetRef.current) return
      setPosition({
        x: ev.clientX - dragOffsetRef.current.dx,
        y: ev.clientY - dragOffsetRef.current.dy,
      })
    }
    const handleMouseUp = () => {
      dragOffsetRef.current = null
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
  }

  return (
    <div
      onMouseDownCapture={onFocus}
      style={{
        position: 'absolute',
        left: position.x,
        top: position.y,
        width: initialWidth,
        height: initialHeight,
        zIndex,
        border: '1px solid #ddd',
        borderRadius: 8,
        backgroundColor: 'white',
        boxShadow: '0 2px 6px rgba(0,0,0,0.12)',
        display: 'flex',
        flexDirection: 'column',
        resize: 'both',
        overflow: 'hidden',
        minWidth: 320,
        minHeight: 260,
      }}
    >
      <div
        onMouseDown={handleMouseDown}
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '12px 16px',
          borderBottom: '1px solid #eee',
          backgroundColor: '#f9f9f9',
          borderRadius: '8px 8px 0 0',
          flexShrink: 0,
          cursor: 'move',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {headerLeft}
          <h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>
        </div>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            fontSize: 20,
            cursor: 'pointer',
            color: '#888',
            padding: '0 8px',
          }}
          title="Закрыть"
        >
          ×
        </button>
      </div>
      <div
        style={{
          padding: 16,
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          overflow: 'hidden',
        }}
      >
        {children}
      </div>
      <div
        onMouseDown={handleMouseDown}
        title="Перетащить"
        style={{
          height: 10,
          flexShrink: 0,
          marginRight: 16, // оставляем угол для resize grabber
          borderTop: '1px solid #eee',
          backgroundColor: '#f9f9f9',
          cursor: 'move',
          userSelect: 'none',
        }}
      />
    </div>
  )
}
