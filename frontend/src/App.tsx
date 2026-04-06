import { useEffect, useState } from 'react'
import { getTickers } from './api/client'
import './App.css'

function App() {
  const [tickers, setTickers] = useState<string[]>([])

  useEffect(() => {
    getTickers().then(setTickers)
  }, [])

  return (
    <div style={{ padding: 20, fontFamily: 'sans-serif' }}>
      <h1>data-core</h1>
      <h2>Доступные тикеры ({tickers.length})</h2>
      <ul>
        {tickers.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  )
}

export default App
