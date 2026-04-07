import { useEffect, useState } from 'react'
import { groupRegistry } from './groupRegistry'
import type { SyncGroup } from './chartSync'

interface Props {
  group: SyncGroup
  memberId: string
}

/**
 * Минималистичная кнопка-иконка «синхронизация группы».
 * Состояния:
 *  - группа `none` → disabled, серая (sync невозможен в одиночной группе)
 *  - в группе нет ведущего → enabled, нейтральная (клик → стать ведущим)
 *  - этот виджет — ведущий → подсвечена акцентным цветом (клик → снять с роли)
 *  - ведущий есть, но это не я → disabled, бледная (нужно сначала снять текущего)
 */
export function SyncLeaderButton({ group, memberId }: Props) {
  const [leaderId, setLeaderId] = useState<string | null>(() => groupRegistry.getLeader(group))

  useEffect(() => {
    setLeaderId(groupRegistry.getLeader(group))
    if (group === 'none') return
    return groupRegistry.subscribeLeader(group, setLeaderId)
  }, [group])

  const isNone = group === 'none'
  const isLeader = !isNone && leaderId === memberId
  const isOtherLeader = !isNone && leaderId !== null && leaderId !== memberId
  const disabled = isNone || isOtherLeader

  let color = '#9e9e9e' // neutral
  let bg = 'transparent'
  let title = 'Синхронизировать графики группы'
  if (isNone) {
    title = 'Выберите цветовую группу, чтобы синхронизировать графики'
  } else if (isLeader) {
    color = '#ffffff'
    bg = '#2962FF'
    title = 'Этот график — ведущий. Клик: снять синхронизацию группы'
  } else if (isOtherLeader) {
    color = '#cfcfcf'
    title = 'В группе уже есть ведущий график. Снимите его, чтобы выбрать другой'
  } else {
    title = 'Клик: сделать этот график ведущим (синхронизировать группу)'
  }

  const onClick = () => {
    if (disabled) return
    groupRegistry.toggleLeader(group, memberId)
  }

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      style={{
        width: 26,
        height: 26,
        padding: 0,
        marginLeft: 8,
        border: '1px solid #d0d0d0',
        borderRadius: 4,
        background: bg,
        color,
        cursor: disabled ? 'not-allowed' : 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        opacity: isOtherLeader ? 0.55 : 1,
      }}
    >
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M21 12a9 9 0 0 1-15 6.7L3 16" />
        <path d="M3 12a9 9 0 0 1 15-6.7L21 8" />
        <polyline points="21 3 21 8 16 8" />
        <polyline points="3 21 3 16 8 16" />
      </svg>
    </button>
  )
}
