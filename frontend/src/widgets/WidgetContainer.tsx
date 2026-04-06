import { useState } from 'react'
import { PriceChartWidget } from './PriceChartWidget'
import { Widget } from './Widget'

type WidgetType = 'price-chart' | 'event-study'

interface WidgetInstance {
  id: string
  type: WidgetType
}

const WIDGET_TITLES: Record<WidgetType, string> = {
  'price-chart': 'Price chart',
  'event-study': 'Event study',
}

export function WidgetContainer() {
  const [widgets, setWidgets] = useState<WidgetInstance[]>([])
  const [menuOpen, setMenuOpen] = useState(false)

  const addWidget = (type: WidgetType) => {
    setWidgets((prev) => [
      ...prev,
      { id: `${type}-${Date.now()}`, type },
    ])
    setMenuOpen(false)
  }

  const removeWidget = (id: string) => {
    setWidgets((prev) => prev.filter((w) => w.id !== id))
  }

  return (
    <div>
      {widgets.map((w) => (
        <Widget
          key={w.id}
          title={WIDGET_TITLES[w.type]}
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

      <div style={{ position: 'relative', marginTop: 16 }}>
        <button
          onClick={() => setMenuOpen(!menuOpen)}
          style={{
            padding: '10px 20px',
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
              left: 0,
              marginTop: 4,
              backgroundColor: 'white',
              border: '1px solid #ddd',
              borderRadius: 6,
              boxShadow: '0 2px 8px rgba(0,0,0,0.12)',
              minWidth: 200,
              zIndex: 10,
            }}
          >
            <button
              onClick={() => addWidget('price-chart')}
              style={menuItemStyle}
            >
              Price chart
            </button>
            <button
              onClick={() => addWidget('event-study')}
              style={menuItemStyle}
            >
              Event study
            </button>
          </div>
        )}
      </div>
    </div>
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
