import { useState } from 'react'
import type { WidgetGroup } from './chartSync'
import { EventEffectAnalysisWidget } from './EventEffectAnalysisWidget'
import { EventStudyWidget } from './EventStudyWidget'
import { IndexChartWidget } from './IndexChartWidget'
import { PqlEditorWidget } from './PqlEditorWidget'
import { PrecedentSearchWidget } from './PrecedentSearchWidget'
import { PriceChartWidget } from './PriceChartWidget'
import { BacktestEditorWidget } from './BacktestEditorWidget'
import { EntityEditorWidget } from './EntityEditorWidget'
import { ResearchReportWidget } from './research/ResearchReportWidget'
import { ResearchSelector } from './research/ResearchSelector'
import { WidgetGroupPicker } from './WidgetGroupPicker'
import { WidgetWindow } from './WidgetWindow'

type WidgetType = 'price-chart' | 'event-study' | 'index-chart' | 'precedent-search' | 'event-effect-analysis' | 'pql-editor' | 'backtest-editor' | 'entity-editor' | 'research-report'

interface WidgetInstance {
  id: string
  type: WidgetType
  x: number
  y: number
  width: number
  height: number
  group: WidgetGroup
  zIndex: number
}

const CANVAS_WIDTH = 4000
const CANVAS_HEIGHT = 3000

const WIDGET_TITLES: Record<WidgetType, string> = {
  'price-chart': 'Price chart',
  'event-study': 'Event study',
  'index-chart': 'Index chart',
  'precedent-search': 'Поиск прецедентов',
  'event-effect-analysis': 'Анализ эффекта событий',
  'pql-editor': 'PQL Editor',
  'backtest-editor': 'BacktestEditor',
  'entity-editor': 'EntityEditor',
  'research-report': 'Research Journal',
}

const DEFAULT_WIDTH = 640
const DEFAULT_HEIGHT = 480
const TOOLBAR_OFFSET_Y = 80

// Виджеты с нестандартным дефолтным размером.
const WIDGET_SIZES: Partial<Record<WidgetType, { width: number; height: number }>> = {
  'backtest-editor': { width: 1280, height: 960 },
  'entity-editor': { width: 1280, height: 960 },
  'research-report': { width: 900, height: 700 },
  'event-effect-analysis': { width: 1100, height: 700 },
  'event-study': { width: 1280, height: 720 },
}

export function WidgetCanvas() {
  const [widgets, setWidgets] = useState<WidgetInstance[]>([])
  const [menuOpen, setMenuOpen] = useState(false)
  const [topZ, setTopZ] = useState(1)

  const addWidget = (type: WidgetType, group: WidgetGroup = 'none') => {
    const size = WIDGET_SIZES[type] ?? { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT }
    const scrollX = window.scrollX
    const scrollY = window.scrollY
    const centerX = scrollX + window.innerWidth / 2 - size.width / 2
    const centerY =
      scrollY + TOOLBAR_OFFSET_Y + (window.innerHeight - TOOLBAR_OFFSET_Y) / 2 - size.height / 2
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
        width: size.width,
        height: size.height,
        group,
        zIndex: newZ,
      },
    ])
    setMenuOpen(false)
  }

  const focusWidget = (id: string) => {
    setWidgets((prev) => {
      const w = prev.find((x) => x.id === id)
      if (!w) return prev
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

  // Двойной клик по событию в Event Effect: фокусируем Event Study этой группы,
  // если он уже открыт, иначе открываем новый в той же группе. Какое событие
  // считать — едет через стор (requestEventStudy), его читает сам виджет.
  const openOrFocusEventStudy = (group: WidgetGroup) => {
    const existing = widgets.find((w) => w.type === 'event-study' && w.group === group)
    if (existing) focusWidget(existing.id)
    else addWidget('event-study', group)
  }

  const setWidgetGroup = (id: string, group: WidgetGroup) => {
    setWidgets((prev) =>
      prev.map((w) => (w.id === id ? { ...w, group: group } : w)),
    )
  }

  return (
    <>
      <div style={toolbarStyle}>
        <ResearchSelector />
        <div style={addWidgetWrapStyle}>
          <button onClick={() => setMenuOpen(!menuOpen)} style={addWidgetButtonStyle}>
            + Добавить виджет
          </button>
          {menuOpen && (
            <div style={dropdownMenuStyle}>
            <button onClick={() => addWidget('price-chart')} style={menuItemStyle}>
              Price chart
            </button>
            <button onClick={() => addWidget('index-chart')} style={menuItemStyle}>
              Index chart
            </button>
            <button onClick={() => addWidget('event-study')} style={menuItemStyle}>
              Event study
            </button>
            <button onClick={() => addWidget('precedent-search')} style={menuItemStyle}>
              Поиск прецедентов
            </button>
            <button onClick={() => addWidget('event-effect-analysis')} style={menuItemStyle}>
              Анализ эффекта событий
            </button>
            <button onClick={() => addWidget('pql-editor')} style={menuItemStyle}>
              PQL Editor
            </button>
            <button onClick={() => addWidget('backtest-editor')} style={menuItemStyle}>
              BacktestEditor
            </button>
            <button onClick={() => addWidget('entity-editor')} style={menuItemStyle}>
              EntityEditor
            </button>
            <button onClick={() => addWidget('research-report')} style={menuItemStyle}>
              Research Journal
            </button>
            </div>
          )}
        </div>
      </div>

      <div style={canvasStyle}>
        {widgets.map((w) => (
          <WidgetWindow
            key={w.id}
            title={WIDGET_TITLES[w.type]}
            initialX={w.x}
            initialY={w.y}
            initialWidth={w.width}
            initialHeight={w.height}
            zIndex={w.zIndex}
            onClose={() => removeWidget(w.id)}
            onFocus={() => focusWidget(w.id)}
            headerLeft={
              <WidgetGroupPicker
                group={w.group}
                onChange={(g) => setWidgetGroup(w.id, g)}
              />
            }
          >
            {w.type === 'price-chart' ? (
              <PriceChartWidget group={w.group} />
            ) : w.type === 'index-chart' ? (
              <IndexChartWidget group={w.group} />
            ) : w.type === 'precedent-search' ? (
              <PrecedentSearchWidget group={w.group} />
            ) : w.type === 'event-effect-analysis' ? (
              <EventEffectAnalysisWidget group={w.group} onOpenEventStudy={openOrFocusEventStudy} />
            ) : w.type === 'pql-editor' ? (
              <PqlEditorWidget group={w.group} />
            ) : w.type === 'backtest-editor' ? (
              <BacktestEditorWidget />
            ) : w.type === 'entity-editor' ? (
              <EntityEditorWidget />
            ) : w.type === 'research-report' ? (
              <ResearchReportWidget />
            ) : (
              <EventStudyWidget group={w.group} />
            )}
          </WidgetWindow>
        ))}
      </div>
    </>
  )
}

const toolbarStyle: React.CSSProperties = {
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
}

const addWidgetButtonStyle: React.CSSProperties = {
  padding: '8px 16px',
  fontSize: 14,
  backgroundColor: '#4CAF50',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
}

const addWidgetWrapStyle: React.CSSProperties = {
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
  minWidth: 200,
  zIndex: 110,
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

const canvasStyle: React.CSSProperties = {
  position: 'relative',
  width: CANVAS_WIDTH,
  height: CANVAS_HEIGHT,
}
