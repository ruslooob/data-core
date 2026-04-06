import type { ReactNode } from 'react'

interface WidgetProps {
  title: string
  onClose: () => void
  children: ReactNode
}

export function Widget({ title, onClose, children }: WidgetProps) {
  return (
    <div
      style={{
        border: '1px solid #ddd',
        borderRadius: 8,
        marginBottom: 16,
        backgroundColor: 'white',
        boxShadow: '0 1px 3px rgba(0,0,0,0.08)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '12px 16px',
          borderBottom: '1px solid #eee',
          backgroundColor: '#f9f9f9',
          borderRadius: '8px 8px 0 0',
        }}
      >
        <h3 style={{ margin: 0, fontSize: 16 }}>{title}</h3>
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
      <div style={{ padding: 16 }}>{children}</div>
    </div>
  )
}
