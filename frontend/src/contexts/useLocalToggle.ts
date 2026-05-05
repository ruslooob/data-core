import { useEffect, useState } from 'react'

/** Boolean-флаг с persist в localStorage. Используется для тогглов UI типа
 * «Показать общие», которые должны помниться между сессиями. */
export function useLocalToggle(key: string, defaultValue = false): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    const stored = localStorage.getItem(key)
    if (stored === null) return defaultValue
    return stored === '1'
  })

  useEffect(() => {
    localStorage.setItem(key, value ? '1' : '0')
  }, [key, value])

  return [value, setValue]
}
