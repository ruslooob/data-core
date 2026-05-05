import { useState } from 'react'
import { createResearch } from '../../api/client'
import {
  DEFAULT_RESEARCH_ID,
  useActiveResearch,
} from '../../contexts/ActiveResearch'

/**
 * Стартовый экран — показывается когда активное исследование не выбрано.
 * Пользователь видит список существующих и может либо выбрать одно, либо создать новое.
 */
export function ResearchPicker() {
  const { allResearch, isLoading, setActiveResearchId, reload } = useActiveResearch()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDescription, setNewDescription] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleCreate = async () => {
    const name = newName.trim()
    if (!name) {
      setError('Введите имя исследования')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const created = await createResearch({
        name,
        description: newDescription.trim() || null,
      })
      await reload()
      setActiveResearchId(created.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Не удалось создать')
    } finally {
      setBusy(false)
    }
  }

  if (isLoading) {
    return (
      <div style={containerStyle}>
        <p>Загрузка исследований…</p>
      </div>
    )
  }

  return (
    <div style={containerStyle}>
      <div style={cardStyle}>
        <h1 style={titleStyle}>Выбор исследования</h1>
        <p style={hintStyle}>
          Выберите существующее исследование или создайте новое. Все стратегии, правила,
          окружения и прогоны будут отображаться в его контексте.
        </p>

        <div style={listSectionStyle}>
          {allResearch.map((r) => (
            <button
              key={r.id}
              onClick={() => setActiveResearchId(r.id)}
              style={r.id === DEFAULT_RESEARCH_ID ? itemDefaultStyle : itemStyle}
            >
              <div style={itemNameStyle}>{r.name}</div>
              {r.description && <div style={itemDescStyle}>{r.description}</div>}
            </button>
          ))}
        </div>

        <div style={dividerStyle} />

        {creating ? (
          <div style={createFormStyle}>
            <label style={labelStyle}>
              Имя
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="например: Защитные механики"
                style={inputStyle}
                autoFocus
              />
            </label>
            <label style={labelStyle}>
              Описание идеи (опционально)
              <textarea
                value={newDescription}
                onChange={(e) => setNewDescription(e.target.value)}
                placeholder="Что хотим выяснить, какие гипотезы планируем"
                style={textareaStyle}
                rows={3}
              />
            </label>
            {error && <div style={errorStyle}>{error}</div>}
            <div style={createButtonsStyle}>
              <button
                onClick={() => {
                  setCreating(false)
                  setNewName('')
                  setNewDescription('')
                  setError(null)
                }}
                style={secondaryButtonStyle}
                disabled={busy}
              >
                Отмена
              </button>
              <button
                onClick={() => void handleCreate()}
                style={primaryButtonStyle}
                disabled={busy}
              >
                {busy ? 'Создаём…' : 'Создать и открыть'}
              </button>
            </div>
          </div>
        ) : (
          <button onClick={() => setCreating(true)} style={primaryButtonStyle}>
            + Создать новое исследование
          </button>
        )}
      </div>
    </div>
  )
}

const containerStyle: React.CSSProperties = {
  minHeight: '100vh',
  backgroundColor: '#f5f5f5',
  display: 'flex',
  alignItems: 'flex-start',
  justifyContent: 'center',
  padding: '60px 20px',
}

const cardStyle: React.CSSProperties = {
  width: '100%',
  maxWidth: 720,
  backgroundColor: 'white',
  borderRadius: 10,
  boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
  padding: 32,
}

const titleStyle: React.CSSProperties = {
  margin: '0 0 12px 0',
  fontSize: 24,
  fontWeight: 600,
}

const hintStyle: React.CSSProperties = {
  margin: '0 0 24px 0',
  color: '#666',
  fontSize: 14,
  lineHeight: 1.5,
}

const listSectionStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  marginBottom: 16,
}

const itemStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '14px 16px',
  border: '1px solid #ddd',
  borderRadius: 6,
  backgroundColor: 'white',
  cursor: 'pointer',
  display: 'block',
  width: '100%',
}

const itemDefaultStyle: React.CSSProperties = {
  ...itemStyle,
  borderColor: '#4CAF50',
  backgroundColor: '#f0f9f0',
}

const itemNameStyle: React.CSSProperties = {
  fontWeight: 500,
  fontSize: 15,
}

const itemDescStyle: React.CSSProperties = {
  marginTop: 4,
  fontSize: 13,
  color: '#666',
}

const dividerStyle: React.CSSProperties = {
  height: 1,
  backgroundColor: '#eee',
  margin: '20px 0',
}

const createFormStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: 13,
  color: '#444',
}

const inputStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 14,
  border: '1px solid #ccc',
  borderRadius: 4,
}

const textareaStyle: React.CSSProperties = {
  ...inputStyle,
  resize: 'vertical',
  fontFamily: 'inherit',
}

const errorStyle: React.CSSProperties = {
  color: '#c62828',
  fontSize: 13,
}

const createButtonsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  justifyContent: 'flex-end',
}

const primaryButtonStyle: React.CSSProperties = {
  padding: '10px 20px',
  fontSize: 14,
  backgroundColor: '#4CAF50',
  color: 'white',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
  fontWeight: 500,
}

const secondaryButtonStyle: React.CSSProperties = {
  padding: '10px 20px',
  fontSize: 14,
  backgroundColor: '#eee',
  color: '#333',
  border: 'none',
  borderRadius: 6,
  cursor: 'pointer',
}
