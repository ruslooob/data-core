import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { listResearch } from '../api/client'
import type { Research } from '../api/types'

const STORAGE_KEY = 'activeResearchId'
export const DEFAULT_RESEARCH_ID = '00000000-0000-0000-0000-000000000001'

export interface ActiveResearchValue {
  activeResearchId: string | null
  activeResearch: Research | null
  allResearch: Research[]
  isLoading: boolean
  setActiveResearchId: (id: string) => void
  reload: () => Promise<void>
}

const ActiveResearchContext = createContext<ActiveResearchValue | null>(null)

export function ActiveResearchProvider({ children }: { children: ReactNode }) {
  const [activeResearchId, setActiveResearchIdState] = useState<string | null>(() => {
    return localStorage.getItem(STORAGE_KEY)
  })
  const [allResearch, setAllResearch] = useState<Research[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const reload = useCallback(async () => {
    setIsLoading(true)
    try {
      const items = await listResearch()
      setAllResearch(items)
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const setActiveResearchId = useCallback((id: string) => {
    localStorage.setItem(STORAGE_KEY, id)
    setActiveResearchIdState(id)
  }, [])

  const activeResearch = useMemo(() => {
    if (!activeResearchId) return null
    return allResearch.find((r) => r.id === activeResearchId) ?? null
  }, [activeResearchId, allResearch])

  // Если активное id указывает на удалённое исследование — сбрасываем.
  useEffect(() => {
    if (!isLoading && activeResearchId && allResearch.length > 0) {
      const exists = allResearch.some((r) => r.id === activeResearchId)
      if (!exists) {
        localStorage.removeItem(STORAGE_KEY)
        setActiveResearchIdState(null)
      }
    }
  }, [activeResearchId, allResearch, isLoading])

  const value: ActiveResearchValue = {
    activeResearchId,
    activeResearch,
    allResearch,
    isLoading,
    setActiveResearchId,
    reload,
  }

  return (
    <ActiveResearchContext.Provider value={value}>
      {children}
    </ActiveResearchContext.Provider>
  )
}

export function useActiveResearch(): ActiveResearchValue {
  const ctx = useContext(ActiveResearchContext)
  if (!ctx) {
    throw new Error('useActiveResearch требует ActiveResearchProvider в дереве')
  }
  return ctx
}

/**
 * Возвращает researchId, гарантированно непустой. Бросает, если активное
 * исследование не выбрано — использовать в виджетах, которые рендерятся
 * только при выбранном контексте (защищены ResearchPicker'ом).
 */
export function useRequiredResearchId(): string {
  const { activeResearchId } = useActiveResearch()
  if (!activeResearchId) {
    throw new Error('Виджет требует активное исследование, но контекст пуст')
  }
  return activeResearchId
}
