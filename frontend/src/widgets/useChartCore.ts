import { useEffect, useRef, type RefObject } from 'react'
import {
  createChart,
  createSeriesMarkers,
  HistogramSeries,
  LineSeries,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts'
import { chartSyncBus, type WidgetGroup } from './chartSync'
import { groupEventBus, useGroupStore } from './groupStore'

/** Секунды Unix-эпохи для переданной даты (ISO-строка или YYYY-MM-DD). */
export function dateToTs(d: string): UTCTimestamp {
  return (new Date(d).getTime() / 1000) as UTCTimestamp
}

/**
 * Базовый хук для time-series виджета (price chart, index chart и т.п.).
 * Создаёт график, серию цены, опционально серию объёма, маркеры,
 * регистрирует в chartSync, обрабатывает resize и опциональный клик по бару.
 *
 * Возвращает refs для последующего setData / маркеров / clearCrosshair.
 */
export interface ChartCoreOptions {
  containerRef: RefObject<HTMLDivElement | null>
  group: WidgetGroup
  /** Идентификатор виджета (для leader-aware chartSync и регистрации в groupStore). */
  memberId: string
  /**
   * Тикер, публикуемый виджетом в groupStore. undefined/null значат
   * «виджет не про акцию» (например, IndexChartWidget). PriceChartWidget
   * передаёт выбранный тикер и меняет его при переключении.
   */
  ticker?: string | null
  withVolume?: boolean
  /** Кастомный priceFormat для серии цены (например, для процентов). */
  priceFormat?: Parameters<IChartApi['addSeries']>[1] extends infer O
    ? O extends { priceFormat?: infer P }
      ? P
      : never
    : never
  /** Колбэк на клик по бару (вызывается с timestamp клика). */
  onBarClick?: (timeSec: number) => void
}

export interface ChartCoreRefs {
  chartRef: RefObject<IChartApi | null>
  mainSeriesRef: RefObject<ISeriesApi<'Line'> | null>
  volumeSeriesRef: RefObject<ISeriesApi<'Histogram'> | null>
  markersRef: RefObject<ISeriesMarkersPluginApi<Time> | null>
}

export function useChartCore(opts: ChartCoreOptions): ChartCoreRefs {
  const {
    containerRef,
    group,
    memberId,
    ticker = null,
    withVolume = false,
    onBarClick,
  } = opts

  const chartRef = useRef<IChartApi | null>(null)
  const mainSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const setGroupRef = useRef<((g: WidgetGroup) => void) | null>(null)
  const onBarClickRef = useRef(onBarClick)

  useEffect(() => {
    onBarClickRef.current = onBarClick
  }, [onBarClick])

  // Создание графика — один раз
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { color: '#ffffff' },
        textColor: '#333',
        panes: { separatorColor: '#e0e0e0', separatorHoverColor: '#b0b0b0' },
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      rightPriceScale: { borderColor: '#e0e0e0' },
      timeScale: {
        borderColor: '#e0e0e0',
        fixLeftEdge: true,
        fixRightEdge: true,
      },
    })

    const mainSeries = chart.addSeries(
      LineSeries,
      {
        color: '#2962FF',
        lineWidth: 2,
        priceLineVisible: false,
        ...(opts.priceFormat ? { priceFormat: opts.priceFormat } : {}),
      },
      0,
    )

    let volumeSeries: ISeriesApi<'Histogram'> | null = null
    if (withVolume) {
      volumeSeries = chart.addSeries(
        HistogramSeries,
        {
          color: '#90a4ae',
          priceFormat: { type: 'volume' },
          priceLineVisible: false,
        },
        1,
      )
    }

    chartRef.current = chart
    mainSeriesRef.current = mainSeries
    volumeSeriesRef.current = volumeSeries
    markersRef.current = createSeriesMarkers(mainSeries, [])

    // Click → callback (через ref, чтобы не пере-инициализировать график)
    const onClick = (param: MouseEventParams) => {
      if (param.time === undefined) return
      const cb = onBarClickRef.current
      if (!cb) return
      const ts = typeof param.time === 'number' ? param.time : 0
      cb(ts)
    }
    chart.subscribeClick(onClick)

    // Resize
    const ro = new ResizeObserver(() => {
      chart.applyOptions({
        width: container.clientWidth,
        height: container.clientHeight,
      })
    })
    ro.observe(container)

    // Регистрация в chartSync (range/crosshair sync с другими графиками группы)
    const { setGroup, unregister: unregisterSync } = chartSyncBus.register(
      chart,
      mainSeries,
      group,
      { memberId },
    )
    setGroupRef.current = setGroup

    return () => {
      chart.unsubscribeClick(onClick)
      unregisterSync()
      setGroupRef.current = null
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      mainSeriesRef.current = null
      volumeSeriesRef.current = null
      markersRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Обновление группы при смене prop'а
  useEffect(() => {
    setGroupRef.current?.(group)
  }, [group])

  // Регистрация в groupStore (жизненный цикл участника группы)
  useEffect(() => {
    useGroupStore.getState().registerMember(memberId, group, ticker)
    return () => useGroupStore.getState().unregisterMember(memberId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    useGroupStore.getState().setMemberGroup(memberId, group)
  }, [group, memberId])

  useEffect(() => {
    useGroupStore.getState().setMemberTicker(memberId, ticker)
  }, [ticker, memberId])

  // Hover sync: внешний виджет (CarChart) публикует наведённую дату —
  // ставим crosshair на ближайшую точку своей серии.
  useEffect(() => {
    if (group === 'none') return
    return groupEventBus.subscribe(group, 'hoverDate', (date) => {
      const chart = chartRef.current
      const series = mainSeriesRef.current
      if (!chart || !series) return
      if (date === null) {
        chart.clearCrosshairPosition()
        return
      }
      const targetTs = dateToTs(date)
      const data = series.data() as ReadonlyArray<{ time: Time; value: number }>
      if (data.length === 0) return
      let best = data[0]
      let bestDiff = Math.abs((typeof best.time === 'number' ? best.time : 0) - targetTs)
      for (let i = 1; i < data.length; i++) {
        const t = typeof data[i].time === 'number' ? (data[i].time as number) : 0
        const diff = Math.abs(t - targetTs)
        if (diff < bestDiff) {
          best = data[i]
          bestDiff = diff
        }
      }
      chart.setCrosshairPosition(best.value, best.time, series)
    })
  }, [group])

  return { chartRef, mainSeriesRef, volumeSeriesRef, markersRef }
}
