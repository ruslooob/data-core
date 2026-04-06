import type { SyncGroup } from './chartSync'

/**
 * Реестр участников sync-групп для целей фильтрации и связи между виджетами.
 * Не пересекается с chartSync (range/crosshair) — здесь:
 *  - кто в какой группе и с каким тикером (фильтр тикеров в Event Study)
 *  - «активное событие» группы (Event Study публикует, Price chart рисует подсветку)
 *  - «выбрать событие» (клик по маркеру на Price chart → Event Study выбирает)
 *  - «зум на диапазон» (Event Study кнопка «Показать на графике»)
 */

interface Member {
  id: string
  group: SyncGroup
  ticker: string | null
}

export interface ActiveEvent {
  ticker: string
  event_date: string // YYYY-MM-DD
  daysBefore: number
  daysAfter: number
}

export interface ZoomRequest {
  from: string // YYYY-MM-DD
  to: string
}

export interface SelectEventRequest {
  ticker: string
  event_date: string
}

type TickersListener = (tickers: string[]) => void
type ActiveEventListener = (ev: ActiveEvent | null) => void
type ZoomListener = (req: ZoomRequest) => void
type SelectListener = (req: SelectEventRequest) => void
type HoverDateListener = (date: string | null) => void

class GroupRegistry {
  private members = new Map<string, Member>()
  private tickersListeners = new Map<SyncGroup, Set<TickersListener>>()

  private activeEvents = new Map<SyncGroup, ActiveEvent | null>()
  private activeListeners = new Map<SyncGroup, Set<ActiveEventListener>>()

  private zoomListeners = new Map<SyncGroup, Set<ZoomListener>>()
  private selectListeners = new Map<SyncGroup, Set<SelectListener>>()
  private hoverDateListeners = new Map<SyncGroup, Set<HoverDateListener>>()

  // ───── члены группы ─────

  register(id: string, group: SyncGroup, ticker: string | null = null): void {
    this.members.set(id, { id, group, ticker })
    this.notifyTickers(group)
  }

  unregister(id: string): void {
    const m = this.members.get(id)
    if (!m) return
    this.members.delete(id)
    this.notifyTickers(m.group)
  }

  setGroup(id: string, group: SyncGroup): void {
    const m = this.members.get(id)
    if (!m) return
    const oldGroup = m.group
    m.group = group
    if (oldGroup !== group) {
      this.notifyTickers(oldGroup)
      this.notifyTickers(group)
    }
  }

  setTicker(id: string, ticker: string | null): void {
    const m = this.members.get(id)
    if (!m) return
    if (m.ticker === ticker) return
    m.ticker = ticker
    this.notifyTickers(m.group)
  }

  getGroupTickers(group: SyncGroup): string[] {
    const set = new Set<string>()
    for (const m of this.members.values()) {
      if (m.group !== group) continue
      if (m.ticker) set.add(m.ticker)
    }
    return Array.from(set).sort()
  }

  subscribe(group: SyncGroup, listener: TickersListener): () => void {
    let set = this.tickersListeners.get(group)
    if (!set) {
      set = new Set()
      this.tickersListeners.set(group, set)
    }
    set.add(listener)
    return () => set!.delete(listener)
  }

  private notifyTickers(group: SyncGroup): void {
    const set = this.tickersListeners.get(group)
    if (!set || set.size === 0) return
    const tickers = this.getGroupTickers(group)
    for (const l of set) l(tickers)
  }

  // ───── активное событие группы ─────

  setActiveEvent(group: SyncGroup, ev: ActiveEvent | null): void {
    if (group === 'none') return
    this.activeEvents.set(group, ev)
    const set = this.activeListeners.get(group)
    if (!set) return
    for (const l of set) l(ev)
  }

  getActiveEvent(group: SyncGroup): ActiveEvent | null {
    return this.activeEvents.get(group) ?? null
  }

  subscribeActiveEvent(group: SyncGroup, l: ActiveEventListener): () => void {
    let set = this.activeListeners.get(group)
    if (!set) {
      set = new Set()
      this.activeListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  // ───── команды: zoom и select event ─────

  requestZoom(group: SyncGroup, req: ZoomRequest): void {
    if (group === 'none') return
    const set = this.zoomListeners.get(group)
    if (!set) return
    for (const l of set) l(req)
  }

  subscribeZoom(group: SyncGroup, l: ZoomListener): () => void {
    let set = this.zoomListeners.get(group)
    if (!set) {
      set = new Set()
      this.zoomListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  requestSelectEvent(group: SyncGroup, req: SelectEventRequest): void {
    if (group === 'none') return
    const set = this.selectListeners.get(group)
    if (!set) return
    for (const l of set) l(req)
  }

  subscribeSelectEvent(group: SyncGroup, l: SelectListener): () => void {
    let set = this.selectListeners.get(group)
    if (!set) {
      set = new Set()
      this.selectListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  // ───── hover date (CarChart → PriceChart crosshair) ─────

  broadcastHoverDate(group: SyncGroup, date: string | null): void {
    if (group === 'none') return
    const set = this.hoverDateListeners.get(group)
    if (!set) return
    for (const l of set) l(date)
  }

  subscribeHoverDate(group: SyncGroup, l: HoverDateListener): () => void {
    let set = this.hoverDateListeners.get(group)
    if (!set) {
      set = new Set()
      this.hoverDateListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }
}

export const groupRegistry = new GroupRegistry()
