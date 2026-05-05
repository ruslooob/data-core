import { ActiveResearchProvider, useActiveResearch } from './contexts/ActiveResearch'
import { ResearchPicker } from './widgets/research/ResearchPicker'
import { WidgetCanvas } from './widgets/WidgetCanvas'
import './App.css'

function AppShell() {
  const { activeResearchId } = useActiveResearch()
  if (!activeResearchId) {
    return <ResearchPicker />
  }
  return (
    <div style={{ fontFamily: 'sans-serif' }}>
      <WidgetCanvas />
    </div>
  )
}

function App() {
  return (
    <ActiveResearchProvider>
      <AppShell />
    </ActiveResearchProvider>
  )
}

export default App
