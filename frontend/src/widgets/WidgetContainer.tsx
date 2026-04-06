import { useState } from 'react'
import { PriceChartWidget } from './PriceChartWidget'
import { Widget } from './Widget'

type WidgetType = 'price-chart' | 'event-study'

interface WidgetInstance {
  id: string
  type: WidgetType
  x: number
  y: number
}

const WIDGET_TITLES: Record<WidgetType, string> = {
  'price-chart': 'Price chart',
  'event-study': 'Event study',
}

const DEFAULT_WIDTH = 640
const DEFAULT_HEIGHT = 480
const TOOLBAR_OFFSET_Y = 80 // toolbar + padding

export function WidgetContainer() {
  const [widgets, setWidgets] = useState<WidgetInstance[]>([])
  const [menuOpen, setMenuOpen] = useState(false)

  const addWidget = (type: WidgetType) => {
    // Центр экрана с небольшим случайным смещением, чтобы виджеты не накладывались один в один
    const centerX = window.innerWidth / 2 - DEFAULT_WIDTH / 2
    const centerY =
      TOOLBAR_OFFSET_Y + (window.innerHeight - TOOLBAR_OFFSET_Y) / 2 - DEFAULT_HEIGHT / 2
    const offset = widgets.length * 30

    setWidgets((prev) => [
      ...prev,
      {
        id: `${type}-${Date.now()}`,
        type,
        x: Math.max(20, centerX + offset),
        y: Math.max(TOOLBAR_OFFSET_Y, centerY + offset),
      },
    ])
    setMenuOpen(false)
  }

  const removeWidget = (id: string) => {
    setWidgets((prev) => prev.filter((w) => w.id !== id))
  }

  return (
    <>
      <div
        style={{
          display: 'flex',
          gap: 8,
          padding: '12px 20px',
          borderBottom: '1px solid #eee',
          position: 'relative',
          backgroundColor: 'white',
          zIndex: 100,
        }}
      >
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          style={{
            padding: '8px 16px',
            fontSize: 14,
            backgroundColor: '#4CAF50',
            color: 'white',
            border: 'none',
            borderRadius: 6,
            cursor: 'pointer',
          }}
        >
          + Добавить виджет
        </button>
        {menuOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 20,
              marginTop: 4,
              backgroundColor: 'white',
              border: '1px solid #ddd',
              borderRadius: 6,
              boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
              minWidth: 200,
              zIndex: 110,
            }}
          >
            <button onClick={() => addWidget('price-chart')} style={menuItemStyle}>
              Price chart
            </button>
            <button onClick={() => addWidget('event-study')} style={menuItemStyle}>
              Event study
            </button>
          </div>
        )}
      </div>

      {widgets.map((w) => (
        <Widget
          key={w.id}
          title={WIDGET_TITLES[w.type]}
          initialX={w.x}
          initialY={w.y}
          initialWidth={DEFAULT_WIDTH}
          initialHeight={DEFAULT_HEIGHT}
          onClose={() => removeWidget(w.id)}
        >
          {w.type === 'price-chart' ? (
            <PriceChartWidget />
          ) : (
            <div style={{ color: '#888', padding: '20px 0' }}>
              {WIDGET_TITLES[w.type]} (placeholder)
            </div>
          )}
        </Widget>
      ))}
    </>
  )
}

const menuItemStyle: React.CSSProperties = {
  display: 'block',
  width: '100%',
  padding: '10px 16px',
  textAlign: 'left',
  background: 'none',
  border: 'none',
  cursor: 'pointer',
  fontSize: 14,
}
