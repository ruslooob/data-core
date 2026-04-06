import { WidgetContainer } from './widgets/WidgetContainer'
import './App.css'

function App() {
  return (
    <div
      style={{
        padding: 20,
        maxWidth: 1200,
        margin: '0 auto',
        fontFamily: 'sans-serif',
      }}
    >
      <h1 style={{ fontSize: 24, marginBottom: 24 }}>data-core</h1>
      <WidgetContainer />
    </div>
  )
}

export default App
