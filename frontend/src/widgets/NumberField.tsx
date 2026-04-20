import type React from 'react'

interface NumberFieldProps {
  label: string
  min: number
  max: number
  value: number | null
  onChange: (v: number | null) => void
}

/**
 * Числовой input с лейблом сверху, диапазоном [min, max] и поддержкой пустого состояния.
 * При пустой строке `value` становится `null` (пока пользователь набирает).
 * На onBlur значение зажимается в [min, max], если оно не null.
 */
export function NumberField({ label, min, max, value, onChange }: NumberFieldProps) {
  return (
    <label style={labelStyle}>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        value={value ?? ''}
        onChange={(e) => {
          const raw = e.target.value
          if (raw === '') {
            onChange(null)
            return
          }
          const n = Number(raw)
          if (!isNaN(n)) onChange(n)
        }}
        onBlur={() => {
          if (value !== null) onChange(Math.max(min, Math.min(max, value)))
        }}
        style={numberInputStyle}
      />
    </label>
  )
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: 12,
  color: '#555',
}

const numberInputStyle: React.CSSProperties = {
  padding: '6px 8px',
  fontSize: 13,
  border: '1px solid #ccc',
  borderRadius: 4,
  width: 70,
}
