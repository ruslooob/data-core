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
} from 'lightweight-charts'
import { priceChartSyncBus, type SyncGroup } from './chartSync'

/**
 * Базовый хук для time-series виджета (price chart, index chart и т.п.).
 * Создаёт график, серию цены, опционально серию объёма, маркеры,
 * регистрирует в chartSync, обрабатывает resize и опциональный клик по бару.
 *
 * Возвращает refs для последующего setData / маркеров / clearCrosshair.
 */
export interface ChartCoreOptions {
  containerRef: RefObject<HTMLDivElement | null>
  syncGroup: SyncGroup
  /** Идентификатор виджета (для leader-aware chartSync). */
  memberId: string
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
  priceSeriesRef: RefObject<ISeriesApi<'Line'> | null>
  volumeSeriesRef: RefObject<ISeriesApi<'Histogram'> | null>
  markersRef: RefObject<ISeriesMarkersPluginApi<Time> | null>
}

export function useChartCore(opts: ChartCoreOptions): ChartCoreRefs {
  const {
    containerRef,
    syncGroup,
    memberId,
    withVolume = false,
    onBarClick,
  } = opts

  const chartRef = useRef<IChartApi | null>(null)
  const priceSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null)
  const setSyncGroupRef = useRef<((g: SyncGroup) => void) | null>(null)
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

    const priceSeries = chart.addSeries(
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
    priceSeriesRef.current = priceSeries
    volumeSeriesRef.current = volumeSeries
    markersRef.current = createSeriesMarkers(priceSeries, [])

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
    const { setGroup, unregister: unregisterSync } = priceChartSyncBus.register(
      chart,
      priceSeries,
      syncGroup,
      { memberId },
    )
    setSyncGroupRef.current = setGroup

    return () => {
      chart.unsubscribeClick(onClick)
      unregisterSync()
      setSyncGroupRef.current = null
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      priceSeriesRef.current = null
      volumeSeriesRef.current = null
      markersRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Обновление группы при смене prop'а
  useEffect(() => {
    setSyncGroupRef.current?.(syncGroup)
  }, [syncGroup])

  return { chartRef, priceSeriesRef, volumeSeriesRef, markersRef }
}
