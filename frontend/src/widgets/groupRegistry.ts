import type { SyncGroup } from './chartSync'

/**
 * Реестр участников sync-групп для целей фильтрации и связи между виджетами.
 * Не пересекается с chartSync (range/crosshair) — здесь только «кто в какой
 * группе и с каким тикером», чтобы Event Study мог сузить dropdown тикеров
 * до price chart'ов своей группы.
 */

interface Member {
  id: string
  group: SyncGroup
  ticker: string | null
}

type Listener = (tickers: string[]) => void

class GroupRegistry {
  private members = new Map<string, Member>()
  private listeners = new Map<SyncGroup, Set<Listener>>()

  register(id: string, group: SyncGroup, ticker: string | null = null): void {
    this.members.set(id, { id, group, ticker })
    this.notify(group)
  }

  unregister(id: string): void {
    const m = this.members.get(id)
    if (!m) return
    this.members.delete(id)
    this.notify(m.group)
  }

  setGroup(id: string, group: SyncGroup): void {
    const m = this.members.get(id)
    if (!m) return
    const oldGroup = m.group
    m.group = group
    if (oldGroup !== group) {
      this.notify(oldGroup)
      this.notify(group)
    }
  }

  setTicker(id: string, ticker: string | null): void {
    const m = this.members.get(id)
    if (!m) return
    if (m.ticker === ticker) return
    m.ticker = ticker
    this.notify(m.group)
  }

  /** Уникальные тикеры всех price chart'ов в группе (отсортированы). */
  getGroupTickers(group: SyncGroup): string[] {
    const set = new Set<string>()
    for (const m of this.members.values()) {
      if (m.group !== group) continue
      if (m.ticker) set.add(m.ticker)
    }
    return Array.from(set).sort()
  }

  subscribe(group: SyncGroup, listener: Listener): () => void {
    let set = this.listeners.get(group)
    if (!set) {
      set = new Set()
      this.listeners.set(group, set)
    }
    set.add(listener)
    return () => {
      set!.delete(listener)
    }
  }

  private notify(group: SyncGroup): void {
    const set = this.listeners.get(group)
    if (!set || set.size === 0) return
    const tickers = this.getGroupTickers(group)
    for (const l of set) l(tickers)
  }
}

export const groupRegistry = new GroupRegistry()
