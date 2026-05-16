import { create } from 'zustand'
import type { WidgetGroup } from './chartSync'

/**
 * Глобальное состояние и шина каналов исследовательских групп.
 *
 * Состоит из двух частей:
 *  1. `useGroupStore` — Zustand-стор для durable-состояния группы:
 *     состав участников, лидер, флаг «показывать события», активное событие.
 *     Виджеты подписываются через селекторы — авто-перерендер только на нужных изменениях.
 *  2. `groupEventBus` — fire-and-forget шина для transient команд между виджетами:
 *     запрос зума, выбор события по клику, hover-дата от CarChart.
 *     Эти сигналы не хранят состояние (нет смысла «помнить» прошлый hover).
 */

// ───────────────────────────────────────────────────────────────────────────
// Типы
// ───────────────────────────────────────────────────────────────────────────

export interface ActiveEvent {
  ticker: string
  eventDate: string // YYYY-MM-DD
  daysBefore: number
  daysAfter: number
}

interface GroupedWidget {
  group: WidgetGroup
  ticker: string | null
}

// ───────────────────────────────────────────────────────────────────────────
// Zustand-стор: durable-состояние
// ───────────────────────────────────────────────────────────────────────────

interface GroupStoreState {
  /** Участники: id виджета → группа и тикер. */
  members: Record<string, GroupedWidget>
  /** Лидер каждой группы (или null). Группа `none` всегда null. */
  leaders: Record<WidgetGroup, string | null>
  /** Флаг «показывать события на ведущем» для каждой группы. */
  showEvents: Record<WidgetGroup, boolean>
  /** Активное событие исследования каждой группы (что сейчас в Event Study). */
  activeEvents: Record<WidgetGroup, ActiveEvent | null>
  /**
   * Набор прецедентов каждой группы — список event_id, выбранных в виджете
   * «Поиск прецедентов» и транслируемых потребителям (Event Effect Analysis,
   * Event Study, маркеры на графике). Для группы `none` сюда ничего не пишется
   * — автономный «Поиск прецедентов» хранит набор в локальном state.
   */
  precedentEventIds: Record<WidgetGroup, string[]>

  // Действия — состав группы
  registerMember: (id: string, group: WidgetGroup, ticker?: string | null) => void
  unregisterMember: (id: string) => void
  setMemberGroup: (id: string, group: WidgetGroup) => void
  setMemberTicker: (id: string, ticker: string | null) => void

  // Действия — лидер
  setLeader: (group: WidgetGroup, id: string | null) => void
  toggleLeader: (group: WidgetGroup, id: string) => void

  // Действия — показ событий
  setShowEvents: (group: WidgetGroup, show: boolean) => void
  toggleShowEvents: (group: WidgetGroup) => void

  // Действия — активное событие
  setActiveEvent: (group: WidgetGroup, ev: ActiveEvent | null) => void

  // Действия — набор прецедентов
  setPrecedentSet: (group: WidgetGroup, eventIds: string[]) => void
  togglePrecedentInSet: (group: WidgetGroup, eventId: string) => void
  addPrecedentsToSet: (group: WidgetGroup, eventIds: string[]) => void
  removePrecedentsFromSet: (group: WidgetGroup, eventIds: string[]) => void
  clearPrecedentSet: (group: WidgetGroup) => void
}

const emptyMap = <T,>(value: T): Record<WidgetGroup, T> => ({
  none: value,
  red: value,
  blue: value,
  green: value,
  yellow: value,
})

export const useGroupStore = create<GroupStoreState>((set, get) => ({
  members: {},
  leaders: emptyMap<string | null>(null),
  showEvents: emptyMap<boolean>(false),
  activeEvents: emptyMap<ActiveEvent | null>(null),
  precedentEventIds: {
    none: [],
    red: [],
    blue: [],
    green: [],
    yellow: [],
  },

  registerMember: (id, group, ticker = null) =>
    set((state) => ({
      members: { ...state.members, [id]: { group, ticker } },
    })),

  unregisterMember: (id) =>
    set((state) => {
      const member = state.members[id]
      if (!member) return state
      const newMembers = { ...state.members }
      delete newMembers[id]
      const newLeaders = state.leaders
      const updates: Partial<GroupStoreState> = { members: newMembers }
      if (newLeaders[member.group] === id) {
        updates.leaders = { ...newLeaders, [member.group]: null }
      }
      return updates
    }),

  setMemberGroup: (id, group) =>
    set((state) => {
      const member = state.members[id]
      if (!member || member.group === group) return state
      const oldGroup = member.group
      const updates: Partial<GroupStoreState> = {
        members: { ...state.members, [id]: { ...member, group } },
      }
      // Если переезжающий участник был лидером старой группы — снять лидерство
      if (state.leaders[oldGroup] === id) {
        updates.leaders = { ...state.leaders, [oldGroup]: null }
      }
      return updates
    }),

  setMemberTicker: (id, ticker) =>
    set((state) => {
      const member = state.members[id]
      if (!member || member.ticker === ticker) return state
      return { members: { ...state.members, [id]: { ...member, ticker } } }
    }),

  setLeader: (group, id) =>
    set((state) => {
      if (group === 'none') return state
      if (state.leaders[group] === id) return state
      return { leaders: { ...state.leaders, [group]: id } }
    }),

  toggleLeader: (group, id) => {
    if (group === 'none') return
    const cur = get().leaders[group]
    get().setLeader(group, cur === id ? null : id)
  },

  setShowEvents: (group, show) =>
    set((state) => {
      if (group === 'none') return state
      if (state.showEvents[group] === show) return state
      return { showEvents: { ...state.showEvents, [group]: show } }
    }),

  toggleShowEvents: (group) => {
    if (group === 'none') return
    get().setShowEvents(group, !get().showEvents[group])
  },

  setActiveEvent: (group, ev) =>
    set((state) => {
      if (group === 'none') return state
      return { activeEvents: { ...state.activeEvents, [group]: ev } }
    }),

  setPrecedentSet: (group, eventIds) =>
    set((state) => {
      if (group === 'none') return state
      return { precedentEventIds: { ...state.precedentEventIds, [group]: eventIds } }
    }),

  togglePrecedentInSet: (group, eventId) =>
    set((state) => {
      if (group === 'none') return state
      const cur = state.precedentEventIds[group]
      const next = cur.includes(eventId)
        ? cur.filter((id) => id !== eventId)
        : [...cur, eventId]
      return { precedentEventIds: { ...state.precedentEventIds, [group]: next } }
    }),

  addPrecedentsToSet: (group, eventIds) =>
    set((state) => {
      if (group === 'none' || eventIds.length === 0) return state
      const cur = state.precedentEventIds[group]
      const known = new Set(cur)
      const added = eventIds.filter((id) => !known.has(id))
      if (added.length === 0) return state
      return { precedentEventIds: { ...state.precedentEventIds, [group]: [...cur, ...added] } }
    }),

  removePrecedentsFromSet: (group, eventIds) =>
    set((state) => {
      if (group === 'none' || eventIds.length === 0) return state
      const remove = new Set(eventIds)
      const cur = state.precedentEventIds[group]
      const next = cur.filter((id) => !remove.has(id))
      if (next.length === cur.length) return state
      return { precedentEventIds: { ...state.precedentEventIds, [group]: next } }
    }),

  clearPrecedentSet: (group) =>
    set((state) => {
      if (group === 'none') return state
      if (state.precedentEventIds[group].length === 0) return state
      return { precedentEventIds: { ...state.precedentEventIds, [group]: [] } }
    }),
}))

// ───────────────────────────────────────────────────────────────────────────
// Селекторы (для DRY и читаемости)
// ───────────────────────────────────────────────────────────────────────────

export const selectLeader = (group: WidgetGroup) => (s: GroupStoreState) =>
  s.leaders[group]

export const selectIsLeader = (group: WidgetGroup, id: string) => (s: GroupStoreState) =>
  s.leaders[group] === id

export const selectLeaderTicker = (group: WidgetGroup) => (s: GroupStoreState) => {
  const leaderId = s.leaders[group]
  if (!leaderId) return null
  return s.members[leaderId]?.ticker ?? null
}

export const selectShowEvents = (group: WidgetGroup) => (s: GroupStoreState) =>
  s.showEvents[group]

export const selectActiveEvent = (group: WidgetGroup) => (s: GroupStoreState) =>
  s.activeEvents[group]

export const selectPrecedentSet = (group: WidgetGroup) => (s: GroupStoreState) =>
  s.precedentEventIds[group]

// ───────────────────────────────────────────────────────────────────────────
// Event bus: transient команды (зум, выбор события, hover-дата)
// Не хранит состояние — fire-and-forget
// ───────────────────────────────────────────────────────────────────────────

export interface ZoomRequest {
  from: string // YYYY-MM-DD
  to: string
}

export interface SelectEventRequest {
  ticker: string
  eventDate: string
}

interface GroupEventMap {
  zoom: ZoomRequest
  selectEvent: SelectEventRequest
  hoverDate: string | null
}

type GroupEventType = keyof GroupEventMap
type GroupEventHandler<E extends GroupEventType> = (event: GroupEventMap[E]) => void

class GroupEventBus {
  private listeners = new Map<string, Set<(event: unknown) => void>>()

  emit<E extends GroupEventType>(group: WidgetGroup, type: E, event: GroupEventMap[E]): void {
    if (group === 'none') return
    const set = this.listeners.get(`${group}:${type}`)
    if (!set) return
    for (const handler of set) handler(event)
  }

  subscribe<E extends GroupEventType>(
    group: WidgetGroup,
    type: E,
    handler: GroupEventHandler<E>,
  ): () => void {
    const key = `${group}:${type}`
    let set = this.listeners.get(key)
    if (!set) {
      set = new Set()
      this.listeners.set(key, set)
    }
    set.add(handler as (event: unknown) => void)
    return () => set!.delete(handler as (event: unknown) => void)
  }
}

export const groupEventBus = new GroupEventBus()
