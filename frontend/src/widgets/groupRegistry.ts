import type { WidgetGroup } from './chartSync'

/**
 * Реестр участников логических групп и шина каналов контекста исследования.
 * Не пересекается с chartSync (он отвечает за leader-driven навигацию). Здесь:
 *  - состав группы: кто в какой группе и с каким тикером
 *  - ведущий график группы (leader / followers)
 *  - флаг «показывать события на ведущем» (toggle от Event Study)
 *  - активное событие группы (Event Study → подсветка на графиках)
 *  - запрос выбора события (клик по маркеру на price chart → Event Study)
 *  - запрос зума на event window (Event Study → графики группы)
 *  - hover-дата (CarChart → crosshair на price/index chart)
 */

interface Member {
  id: string
  group: WidgetGroup
  ticker: string | null
}

export interface ActiveEvent {
  ticker: string
  eventDate: string // YYYY-MM-DD
  daysBefore: number
  daysAfter: number
}

export interface ZoomRequest {
  from: string // YYYY-MM-DD
  to: string
}

export interface SelectEventRequest {
  ticker: string
  eventDate: string
}

type TickersListener = (tickers: string[]) => void
type ActiveEventListener = (ev: ActiveEvent | null) => void
type ZoomListener = (req: ZoomRequest) => void
type SelectListener = (req: SelectEventRequest) => void
type HoverDateListener = (date: string | null) => void
type LeaderListener = (leaderId: string | null) => void
type ShowEventsListener = (show: boolean) => void

class GroupRegistry {
  private members = new Map<string, Member>()
  private tickersListeners = new Map<WidgetGroup, Set<TickersListener>>()

  private activeEvents = new Map<WidgetGroup, ActiveEvent | null>()
  private activeListeners = new Map<WidgetGroup, Set<ActiveEventListener>>()

  private zoomListeners = new Map<WidgetGroup, Set<ZoomListener>>()
  private selectListeners = new Map<WidgetGroup, Set<SelectListener>>()
  private hoverDateListeners = new Map<WidgetGroup, Set<HoverDateListener>>()

  private leaders = new Map<WidgetGroup, string | null>()
  private leaderListeners = new Map<WidgetGroup, Set<LeaderListener>>()

  private showEventsByGroup = new Map<WidgetGroup, boolean>()
  private showEventsListeners = new Map<WidgetGroup, Set<ShowEventsListener>>()

  // ───── члены группы ─────

  register(id: string, group: WidgetGroup, ticker: string | null = null): void {
    this.members.set(id, { id, group, ticker })
    this.notifyTickers(group)
  }

  unregister(id: string): void {
    const m = this.members.get(id)
    if (!m) return
    this.members.delete(id)
    if (this.leaders.get(m.group) === id) {
      this.setLeader(m.group, null)
    }
    this.notifyTickers(m.group)
  }

  setGroup(id: string, group: WidgetGroup): void {
    const m = this.members.get(id)
    if (!m) return
    const oldGroup = m.group
    m.group = group
    if (oldGroup !== group) {
      // Если переезжающий участник был лидером старой группы — снять лидерство
      if (this.leaders.get(oldGroup) === id) {
        this.setLeader(oldGroup, null)
      }
      this.notifyTickers(oldGroup)
      this.notifyTickers(group)
    }
  }

  // ───── ведущий график группы ─────

  getLeader(group: WidgetGroup): string | null {
    return this.leaders.get(group) ?? null
  }

  setLeader(group: WidgetGroup, id: string | null): void {
    if (group === 'none') return
    const cur = this.leaders.get(group) ?? null
    if (cur === id) return
    this.leaders.set(group, id)
    const set = this.leaderListeners.get(group)
    if (set) for (const l of set) l(id)
  }

  toggleLeader(group: WidgetGroup, id: string): void {
    if (group === 'none') return
    const cur = this.leaders.get(group) ?? null
    this.setLeader(group, cur === id ? null : id)
  }

  subscribeLeader(group: WidgetGroup, l: LeaderListener): () => void {
    let set = this.leaderListeners.get(group)
    if (!set) {
      set = new Set()
      this.leaderListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  /** Тикер ведущего графика группы (если лидер существует и это price chart с тикером). */
  getLeaderTicker(group: WidgetGroup): string | null {
    const leaderId = this.leaders.get(group)
    if (!leaderId) return null
    const m = this.members.get(leaderId)
    return m?.ticker ?? null
  }

  // ───── показ событий на ведущем графике (toggle от Event Study) ─────

  getShowEvents(group: WidgetGroup): boolean {
    return this.showEventsByGroup.get(group) ?? false
  }

  setShowEvents(group: WidgetGroup, show: boolean): void {
    if (group === 'none') return
    const cur = this.showEventsByGroup.get(group) ?? false
    if (cur === show) return
    this.showEventsByGroup.set(group, show)
    const set = this.showEventsListeners.get(group)
    if (set) for (const l of set) l(show)
  }

  toggleShowEvents(group: WidgetGroup): void {
    if (group === 'none') return
    this.setShowEvents(group, !this.getShowEvents(group))
  }

  subscribeShowEvents(group: WidgetGroup, l: ShowEventsListener): () => void {
    let set = this.showEventsListeners.get(group)
    if (!set) {
      set = new Set()
      this.showEventsListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  setTicker(id: string, ticker: string | null): void {
    const m = this.members.get(id)
    if (!m) return
    if (m.ticker === ticker) return
    m.ticker = ticker
    this.notifyTickers(m.group)
  }

  getGroupTickers(group: WidgetGroup): string[] {
    const set = new Set<string>()
    for (const m of this.members.values()) {
      if (m.group !== group) continue
      if (m.ticker) set.add(m.ticker)
    }
    return Array.from(set).sort()
  }

  subscribeTickers(group: WidgetGroup, listener: TickersListener): () => void {
    let set = this.tickersListeners.get(group)
    if (!set) {
      set = new Set()
      this.tickersListeners.set(group, set)
    }
    set.add(listener)
    return () => set!.delete(listener)
  }

  private notifyTickers(group: WidgetGroup): void {
    const set = this.tickersListeners.get(group)
    if (!set || set.size === 0) return
    const tickers = this.getGroupTickers(group)
    for (const l of set) l(tickers)
  }

  // ───── активное событие группы ─────

  setActiveEvent(group: WidgetGroup, ev: ActiveEvent | null): void {
    if (group === 'none') return
    this.activeEvents.set(group, ev)
    const set = this.activeListeners.get(group)
    if (!set) return
    for (const l of set) l(ev)
  }

  getActiveEvent(group: WidgetGroup): ActiveEvent | null {
    return this.activeEvents.get(group) ?? null
  }

  subscribeActiveEvent(group: WidgetGroup, l: ActiveEventListener): () => void {
    let set = this.activeListeners.get(group)
    if (!set) {
      set = new Set()
      this.activeListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  // ───── команды: zoom и select event ─────

  requestZoom(group: WidgetGroup, req: ZoomRequest): void {
    if (group === 'none') return
    const set = this.zoomListeners.get(group)
    if (!set) return
    for (const l of set) l(req)
  }

  subscribeZoom(group: WidgetGroup, l: ZoomListener): () => void {
    let set = this.zoomListeners.get(group)
    if (!set) {
      set = new Set()
      this.zoomListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  requestSelectEvent(group: WidgetGroup, req: SelectEventRequest): void {
    if (group === 'none') return
    const set = this.selectListeners.get(group)
    if (!set) return
    for (const l of set) l(req)
  }

  subscribeSelectEvent(group: WidgetGroup, l: SelectListener): () => void {
    let set = this.selectListeners.get(group)
    if (!set) {
      set = new Set()
      this.selectListeners.set(group, set)
    }
    set.add(l)
    return () => set!.delete(l)
  }

  // ───── hover date (CarChart → PriceChart crosshair) ─────

  broadcastHoverDate(group: WidgetGroup, date: string | null): void {
    if (group === 'none') return
    const set = this.hoverDateListeners.get(group)
    if (!set) return
    for (const l of set) l(date)
  }

  subscribeHoverDate(group: WidgetGroup, l: HoverDateListener): () => void {
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
