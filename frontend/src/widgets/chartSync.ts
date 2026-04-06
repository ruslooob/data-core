import type {
  IChartApi,
  ISeriesApi,
  MouseEventParams,
  Range,
  Time,
} from 'lightweight-charts'

export type SyncGroup = 'none' | 'red' | 'blue' | 'green' | 'yellow'

export const SYNC_GROUP_COLORS: Record<SyncGroup, string> = {
  none: '#cccccc',
  red: '#e53935',
  blue: '#1e88e5',
  green: '#43a047',
  yellow: '#fdd835',
}

export const SYNC_GROUPS: SyncGroup[] = ['none', 'red', 'blue', 'green', 'yellow']

interface Entry {
  chart: IChartApi
  priceSeries: ISeriesApi<'Line'>
  group: SyncGroup
  rangeSync: boolean
  crosshairSync: boolean
}

export interface RegisterOptions {
  /** Участвует в синхронизации visible range. По умолчанию true. */
  rangeSync?: boolean
  /** Участвует в синхронизации crosshair. По умолчанию true. */
  crosshairSync?: boolean
}

class ChartSyncBus {
  private entries = new Map<IChartApi, Entry>()
  private lastAppliedAt = new WeakMap<IChartApi, number>()
  private readonly IGNORE_WINDOW_MS = 150
  private syncingCrosshair = false

  /**
   * Помечает chart как «только что получивший внешний setVisibleRange».
   * Используется когда виджет программно меняет range (например, по zoom-команде
   * из Event Study), чтобы chartSync не пропагировал получившееся range-change
   * событие соседним графикам как эхо.
   */
  markApplied(chart: IChartApi): void {
    this.lastAppliedAt.set(chart, performance.now())
  }

  register(
    chart: IChartApi,
    priceSeries: ISeriesApi<'Line'>,
    initialGroup: SyncGroup,
    options: RegisterOptions = {},
  ): { setGroup: (g: SyncGroup) => void; unregister: () => void } {
    const rangeSync = options.rangeSync ?? true
    const crosshairSync = options.crosshairSync ?? true
    const entry: Entry = {
      chart,
      priceSeries,
      group: initialGroup,
      rangeSync,
      crosshairSync,
    }
    this.entries.set(chart, entry)

    const onRangeChange = (range: Range<Time> | null) => {
      if (range === null) return
      const lastApplied = this.lastAppliedAt.get(chart) ?? 0
      if (performance.now() - lastApplied < this.IGNORE_WINDOW_MS) return
      if (entry.group === 'none') return
      const now = performance.now()
      for (const other of this.entries.values()) {
        if (other.chart === chart) continue
        if (other.group !== entry.group) continue
        if (!other.rangeSync) continue

        // Синхронизируем только центр диапазона, сохраняя текущий масштаб slave.
        const newRange = shiftRangeToCenter(range, other.chart, other.priceSeries)
        if (newRange === null) continue

        this.lastAppliedAt.set(other.chart, now)
        other.chart.timeScale().setVisibleRange(newRange)
      }
    }
    if (rangeSync) {
      chart.timeScale().subscribeVisibleTimeRangeChange(onRangeChange)
    }

    const onCrosshairMove = (param: MouseEventParams) => {
      if (this.syncingCrosshair) return
      if (entry.group === 'none') return
      this.syncingCrosshair = true
      try {
        for (const other of this.entries.values()) {
          if (other.chart === chart) continue
          if (other.group !== entry.group) continue
          if (!other.crosshairSync) continue
          if (param.time === undefined) {
            other.chart.clearCrosshairPosition()
            continue
          }
          const data = other.priceSeries.data() as ReadonlyArray<{
            time: Time
            value: number
          }>
          const point = findClosestPoint(data, param.time)
          if (point) {
            other.chart.setCrosshairPosition(point.value, point.time, other.priceSeries)
          }
        }
      } finally {
        this.syncingCrosshair = false
      }
    }
    if (crosshairSync) {
      chart.subscribeCrosshairMove(onCrosshairMove)
    }

    const setGroup = (g: SyncGroup) => {
      entry.group = g
    }

    const unregister = () => {
      if (rangeSync) {
        chart.timeScale().unsubscribeVisibleTimeRangeChange(onRangeChange)
      }
      if (crosshairSync) {
        chart.unsubscribeCrosshairMove(onCrosshairMove)
      }
      this.entries.delete(chart)
    }

    return { setGroup, unregister }
  }
}

/**
 * Сдвигает текущий visibleRange slave-графика так, чтобы его центр совпал
 * с центром master-range, сохраняя длину диапазона (масштаб) slave.
 * Клампит к доступным данным slave, сохраняя длительность.
 */
function shiftRangeToCenter(
  masterRange: Range<Time>,
  slaveChart: IChartApi,
  slaveSeries: ISeriesApi<'Line'>,
): Range<Time> | null {
  const data = slaveSeries.data() as ReadonlyArray<{ time: Time; value: number }>
  if (data.length === 0) return null

  const slaveCurrent = slaveChart.timeScale().getVisibleRange()
  if (slaveCurrent === null) return null

  const slaveFromNum = timeToNumber(slaveCurrent.from)
  const slaveToNum = timeToNumber(slaveCurrent.to)
  const duration = slaveToNum - slaveFromNum
  if (duration <= 0) return null

  const masterCenter =
    (timeToNumber(masterRange.from) + timeToNumber(masterRange.to)) / 2

  let newFrom = masterCenter - duration / 2
  let newTo = masterCenter + duration / 2

  const dataMinNum = timeToNumber(data[0].time)
  const dataMaxNum = timeToNumber(data[data.length - 1].time)

  // Если диапазон slave длиннее всех его данных — просто показываем всё
  if (duration >= dataMaxNum - dataMinNum) {
    return { from: data[0].time, to: data[data.length - 1].time }
  }

  // Сдвигаем диапазон внутрь данных, сохраняя длительность
  if (newFrom < dataMinNum) {
    newTo += dataMinNum - newFrom
    newFrom = dataMinNum
  }
  if (newTo > dataMaxNum) {
    newFrom -= newTo - dataMaxNum
    newTo = dataMaxNum
  }

  return {
    from: newFrom as Time,
    to: newTo as Time,
  }
}

function findClosestPoint(
  data: ReadonlyArray<{ time: Time; value: number }>,
  target: Time,
): { time: Time; value: number } | null {
  if (data.length === 0) return null
  // time для daily series — UTCTimestamp (number seconds since epoch)
  const targetNum = timeToNumber(target)
  let best = data[0]
  let bestDiff = Math.abs(timeToNumber(best.time) - targetNum)
  for (let i = 1; i < data.length; i++) {
    const diff = Math.abs(timeToNumber(data[i].time) - targetNum)
    if (diff < bestDiff) {
      best = data[i]
      bestDiff = diff
    }
  }
  return best
}

function timeToNumber(t: Time): number {
  if (typeof t === 'number') return t
  if (typeof t === 'string') return new Date(t).getTime() / 1000
  return 0
}

export const priceChartSyncBus = new ChartSyncBus()
