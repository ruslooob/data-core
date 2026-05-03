import { useEffect, useRef } from 'react'
import { createChart, LineSeries, type UTCTimestamp } from 'lightweight-charts'

interface EquityCurveChartProps {
  data: { date: string; equity: number }[]
  height?: number
}

/** Простой график equity-кривой для карточки результата прогона. */
export function EquityCurveChart({ data, height = 240 }: EquityCurveChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = containerRef.current
    if (!el || data.length === 0) return

    const chart = createChart(el, {
      width: el.clientWidth,
      height,
      layout: { textColor: '#333', background: { color: '#fff' } },
      grid: { vertLines: { color: '#eee' }, horzLines: { color: '#eee' } },
      timeScale: { timeVisible: false, secondsVisible: false },
    })
    const series = chart.addSeries(LineSeries, { color: '#2962FF', lineWidth: 2 })
    series.setData(
      data.map((p) => ({
        time: (new Date(p.date).getTime() / 1000) as UTCTimestamp,
        value: p.equity,
      })),
    )
    chart.timeScale().fitContent()

    const onResize = () => {
      chart.applyOptions({ width: el.clientWidth })
    }
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
    }
  }, [data, height])

  if (data.length === 0) {
    return <div style={emptyStyle}>Нет точек для отображения</div>
  }

  return <div ref={containerRef} style={{ width: '100%', height }} />
}

const emptyStyle: React.CSSProperties = {
  padding: 12,
  fontSize: 12,
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}
