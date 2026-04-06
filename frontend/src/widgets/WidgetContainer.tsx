import { useState } from 'react'
import type { SyncGroup } from './chartSync'
import { EventStudyWidget } from './EventStudyWidget'
import { PriceChartWidget } from './PriceChartWidget'
import { SyncGroupPicker } from './SyncGroupPicker'
import { Widget } from './Widget'

type WidgetType = 'price-chart' | 'event-study'

interface WidgetInstance {
  id: string
  type: WidgetType
  x: number
  y: number
  syncGroup: SyncGroup
  zIndex: number
}

const CANVAS_WIDTH = 4000
const CANVAS_HEIGHT = 3000

const WIDGET_TITLES: Record<WidgetType, string> = {
  'price-chart': 'Price chart',
  'event-study': 'Event study',
}

const DEFAULT_WIDTH = 640
const DEFAULT_HEIGHT = 480
const TOOLBAR_OFFSET_Y = 80

export function WidgetContainer() {
  const [widgets, setWidgets] = useState<WidgetInstance[]>([])
  const [menuOpen, setMenuOpen] = useState(false)
  const [topZ, setTopZ] = useState(1)

  const addWidget = (type: WidgetType) => {
    // Появляемся в центре видимой области полотна (с учётом скролла)
    const scrollX = window.scrollX
    const scrollY = window.scrollY
    const centerX = scrollX + window.innerWidth / 2 - DEFAULT_WIDTH / 2
    const centerY =
      scrollY + TOOLBAR_OFFSET_Y + (window.innerHeight - TOOLBAR_OFFSET_Y) / 2 - DEFAULT_HEIGHT / 2
    const offset = widgets.length * 30
    const newZ = topZ + 1
    setTopZ(newZ)

    setWidgets((prev) => [
      ...prev,
      {
        id: `${type}-${Date.now()}`,
        type,
        x: Math.max(20, centerX + offset),
        y: Math.max(TOOLBAR_OFFSET_Y, centerY + offset),
        syncGroup: 'none',
        zIndex: newZ,
      },
    ])
    setMenuOpen(false)
  }

  const focusWidget = (id: string) => {
    setWidgets((prev) => {
      const w = prev.find((x) => x.id === id)
      if (!w) return prev
      // Если уже самый верхний — ничего не делаем (избегаем лишних рендеров)
      const maxZ = prev.reduce((m, x) => (x.zIndex > m ? x.zIndex : m), 0)
      if (w.zIndex === maxZ) return prev
      const newZ = topZ + 1
      setTopZ(newZ)
      return prev.map((x) => (x.id === id ? { ...x, zIndex: newZ } : x))
    })
  }

  const removeWidget = (id: string) => {
    setWidgets((prev) => prev.filter((w) => w.id !== id))
  }

  const setWidgetSyncGroup = (id: string, group: SyncGroup) => {
    setWidgets((prev) =>
      prev.map((w) => (w.id === id ? { ...w, syncGroup: group } : w)),
    )
  }

  return (
    <>
      <div
        style={{
          display: 'flex',
          gap: 8,
          padding: '12px 20px',
          borderBottom: '1px solid #eee',
          position: 'sticky',
          top: 0,
          left: 0,
          backgroundColor: 'white',
          zIndex: 1000000,
          width: '100vw',
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

      <div
        style={{
          position: 'relative',
          width: CANVAS_WIDTH,
          height: CANVAS_HEIGHT,
        }}
      >
        {widgets.map((w) => (
          <Widget
            key={w.id}
            title={WIDGET_TITLES[w.type]}
            initialX={w.x}
            initialY={w.y}
            initialWidth={DEFAULT_WIDTH}
            initialHeight={DEFAULT_HEIGHT}
            zIndex={w.zIndex}
            onClose={() => removeWidget(w.id)}
            onFocus={() => focusWidget(w.id)}
            headerLeft={
              <SyncGroupPicker
                group={w.syncGroup}
                onChange={(g) => setWidgetSyncGroup(w.id, g)}
              />
            }
          >
            {w.type === 'price-chart' ? (
              <PriceChartWidget syncGroup={w.syncGroup} />
            ) : (
              <EventStudyWidget syncGroup={w.syncGroup} />
            )}
          </Widget>
        ))}
      </div>
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
