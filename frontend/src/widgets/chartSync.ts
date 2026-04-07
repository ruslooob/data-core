import type {
  IChartApi,
  ISeriesApi,
  MouseEventParams,
  Range,
  Time,
} from 'lightweight-charts'
import { groupRegistry } from './groupRegistry'

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
  memberId: string
}

export interface RegisterOptions {
  memberId: string
}

/**
 * Шина синхронизации графиков по модели «ведущий → ведомые».
 * - Если график — ведущий своей группы, его изменения visible range / crosshair
 *   транслируются всем остальным членам группы.
 * - Если ведущего в группе нет (или график — ведомый), синхронизация не происходит.
 * - Group `none` — никогда не синхронизируется.
 * Никакого peer-to-peer.
 */
class ChartSyncBus {
  private entries = new Map<IChartApi, Entry>()
  private lastAppliedAt = new WeakMap<IChartApi, number>()
  private readonly IGNORE_WINDOW_MS = 150
  private syncingCrosshair = false

  /**
   * Помечает chart как «только что получивший внешний setVisibleRange».
   * Используется когда виджет программно меняет range (например, по zoom-команде
   * из Event Study), чтобы лидер не пропагировал получившееся range-change
   * событие соседним графикам как эхо.
   */
  markApplied(chart: IChartApi): void {
    this.lastAppliedAt.set(chart, performance.now())
  }

  register(
    chart: IChartApi,
    priceSeries: ISeriesApi<'Line'>,
    initialGroup: SyncGroup,
    options: RegisterOptions,
  ): { setGroup: (g: SyncGroup) => void; unregister: () => void } {
    const entry: Entry = {
      chart,
      priceSeries,
      group: initialGroup,
      memberId: options.memberId,
    }
    this.entries.set(chart, entry)

    const onRangeChange = (range: Range<Time> | null) => {
      if (range === null) return
      if (entry.group === 'none') return
      // Только лидер группы транслирует range
      if (groupRegistry.getLeader(entry.group) !== entry.memberId) return
      const lastApplied = this.lastAppliedAt.get(chart) ?? 0
      if (performance.now() - lastApplied < this.IGNORE_WINDOW_MS) return

      const now = performance.now()
      for (const other of this.entries.values()) {
        if (other.chart === chart) continue
        if (other.group !== entry.group) continue
        this.lastAppliedAt.set(other.chart, now)
        other.chart.timeScale().setVisibleRange(range)
      }
    }
    chart.timeScale().subscribeVisibleTimeRangeChange(onRangeChange)

    const onCrosshairMove = (param: MouseEventParams) => {
      if (this.syncingCrosshair) return
      if (entry.group === 'none') return
      // Только лидер группы транслирует crosshair
      if (groupRegistry.getLeader(entry.group) !== entry.memberId) return
      this.syncingCrosshair = true
      try {
        for (const other of this.entries.values()) {
          if (other.chart === chart) continue
          if (other.group !== entry.group) continue
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
    chart.subscribeCrosshairMove(onCrosshairMove)

    const setGroup = (g: SyncGroup) => {
      entry.group = g
    }

    const unregister = () => {
      chart.timeScale().unsubscribeVisibleTimeRangeChange(onRangeChange)
      chart.unsubscribeCrosshairMove(onCrosshairMove)
      this.entries.delete(chart)
    }

    return { setGroup, unregister }
  }
}

function findClosestPoint(
  data: ReadonlyArray<{ time: Time; value: number }>,
  target: Time,
): { time: Time; value: number } | null {
  if (data.length === 0) return null
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
