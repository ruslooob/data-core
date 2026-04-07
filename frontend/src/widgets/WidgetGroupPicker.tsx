import { useEffect, useRef, useState } from 'react'
import { WIDGET_GROUPS, WIDGET_GROUP_COLORS, type WidgetGroup } from './chartSync'

interface WidgetGroupPickerProps {
  group: WidgetGroup
  onChange: (group: WidgetGroup) => void
}

export function WidgetGroupPicker({ group, onChange }: WidgetGroupPickerProps) {
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClickOutside = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', onClickOutside)
    return () => window.removeEventListener('mousedown', onClickOutside)
  }, [open])

  return (
    <div ref={rootRef} style={{ position: 'relative' }}>
      <button
        onClick={(e) => {
          e.stopPropagation()
          setOpen(!open)
        }}
        onMouseDown={(e) => e.stopPropagation()}
        title="Группа синхронизации"
        style={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          backgroundColor: WIDGET_GROUP_COLORS[group],
          border: group === 'none' ? '1px solid #999' : '1px solid rgba(0,0,0,0.2)',
          cursor: 'pointer',
          padding: 0,
        }}
      />
      {open && (
        <div
          onMouseDown={(e) => e.stopPropagation()}
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            backgroundColor: 'white',
            border: '1px solid #ddd',
            borderRadius: 6,
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            padding: 6,
            display: 'flex',
            gap: 4,
            zIndex: 200,
          }}
        >
          {WIDGET_GROUPS.map((g) => (
            <button
              key={g}
              onClick={(e) => {
                e.stopPropagation()
                onChange(g)
                setOpen(false)
              }}
              title={g}
              style={{
                width: 18,
                height: 18,
                borderRadius: '50%',
                backgroundColor: WIDGET_GROUP_COLORS[g],
                border:
                  g === group
                    ? '2px solid #333'
                    : g === 'none'
                      ? '1px solid #999'
                      : '1px solid rgba(0,0,0,0.2)',
                cursor: 'pointer',
                padding: 0,
              }}
            />
          ))}
        </div>
      )}
    </div>
  )
}
