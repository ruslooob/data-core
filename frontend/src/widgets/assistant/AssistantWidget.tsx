import { useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { useActiveResearch } from '../../contexts/ActiveResearch'
import { MarkdownRender } from '../../components/MarkdownRender'

/**
 * Виджет помощника. Эфемерный чат: история живёт только в state виджета.
 * При закрытии или перезагрузке страницы — теряется.
 */
type Block =
  | { type: 'text'; text: string }
  | { type: 'tool_use'; name: string; input: unknown }
  | { type: 'tool_result'; content: string }
  | { type: 'error'; message: string }

interface Message {
  role: 'user' | 'assistant'
  blocks: Block[]
}

interface AssistantEvent {
  type: 'text' | 'tool_use' | 'tool_result' | 'error' | 'done'
  text?: string
  name?: string
  input?: unknown
  content?: string
  message?: string
}

const MAX_MENTION_SUGGESTIONS = 8

interface MentionState {
  from: number   // позиция символа `@` в input
  query: string  // текст между `@` и курсором
  selected: number
}

export function AssistantWidget() {
  const { activeResearchId } = useActiveResearch()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [availableDocs, setAvailableDocs] = useState<string[]>([])
  const [mention, setMention] = useState<MentionState | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    let abort = false
    fetch('/api/docs/tree')
      .then((r) => r.ok ? r.json() : [])
      .then((tree) => { if (!abort) setAvailableDocs(flattenDocs(tree)) })
      .catch(() => { /* список приложений — не критично, оставим пустым */ })
    return () => { abort = true }
  }, [])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const suggestions = useMemo(() => {
    if (!mention) return []
    const q = mention.query.toLowerCase()
    return availableDocs
      .filter((p) => p.toLowerCase().includes(q))
      .slice(0, MAX_MENTION_SUGGESTIONS)
  }, [mention, availableDocs])

  if (!activeResearchId) {
    return <div style={blockedStyle}>Выберите активное исследование, чтобы говорить с помощником.</div>
  }

  const detectMention = (text: string, cursor: number): MentionState | null => {
    const before = text.slice(0, cursor)
    const m = before.match(/(?:^|\s)@([^\s@]*)$/)
    if (!m) return null
    const atIdx = before.length - m[1].length - 1
    return { from: atIdx, query: m[1], selected: 0 }
  }

  const onChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value
    setInput(next)
    setMention(detectMention(next, e.target.selectionStart))
  }

  const onSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget
    setMention(detectMention(el.value, el.selectionStart))
  }

  const insertSuggestion = (docPath: string) => {
    if (!mention || !textareaRef.current) return
    const ta = textareaRef.current
    const cursor = ta.selectionStart
    const after = input.slice(cursor)
    const before = input.slice(0, mention.from)
    const token = `@${docPath}`
    const next = before + token + (after.startsWith(' ') ? after : ' ' + after)
    setInput(next)
    setMention(null)
    const newCursor = before.length + token.length + 1
    requestAnimationFrame(() => {
      ta.focus()
      ta.setSelectionRange(newCursor, newCursor)
    })
  }

  const send = async () => {
    const text = input.trim()
    if (!text || streaming) return
    const attachedDocs = extractAttachedDocs(text, availableDocs)
    setInput('')
    setMention(null)

    const userMsg: Message = { role: 'user', blocks: [{ type: 'text', text }] }
    const placeholder: Message = { role: 'assistant', blocks: [] }
    const nextHistory = [...messages, userMsg]
    setMessages([...nextHistory, placeholder])
    setStreaming(true)

    const controller = new AbortController()
    abortRef.current = controller

    try {
      await streamFromBackend({
        history: nextHistory.map(toApiMessage),
        researchId: activeResearchId,
        attachedDocs,
        signal: controller.signal,
        onEvent: (evt) => {
          setMessages((prev) => applyEventToLast(prev, evt))
        },
      })
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setMessages((prev) => applyEventToLast(prev, { type: 'error', message: String(e) }))
      }
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  const stop = () => abortRef.current?.abort()

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention && suggestions.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setMention({ ...mention, selected: (mention.selected + 1) % suggestions.length })
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setMention({ ...mention, selected: (mention.selected - 1 + suggestions.length) % suggestions.length })
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        insertSuggestion(suggestions[mention.selected])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setMention(null)
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      void send()
    }
  }

  return (
    <div style={rootStyle}>
      <div ref={scrollRef} style={messagesPaneStyle}>
        {messages.length === 0 && (
          <div style={emptyStateStyle}>
            Спросите что-нибудь — например, «покажи мои стратегии» или «прогон такой-то стратегии на таком-то окружении».
            Чтобы приложить документ — напишите `@` и выберите файл.
          </div>
        )}
        {messages.map((m, i) => (
          <MessageView key={i} message={m} />
        ))}
      </div>
      <div style={composerStyle}>
        <div style={composerInputWrapStyle}>
          <textarea
            ref={textareaRef}
            value={input}
            onChange={onChange}
            onKeyDown={onKeyDown}
            onSelect={onSelect}
            placeholder="Сообщение помощнику. @ — приложить документ. Enter — отправить, Shift+Enter — перенос."
            style={textareaStyle}
            disabled={streaming}
            rows={3}
          />
          {mention && suggestions.length > 0 && (
            <ul style={mentionDropdownStyle} role="listbox">
              {suggestions.map((doc, i) => (
                <li
                  key={doc}
                  role="option"
                  aria-selected={i === mention.selected}
                  onMouseDown={(e) => { e.preventDefault(); insertSuggestion(doc) }}
                  onMouseEnter={() => setMention({ ...mention, selected: i })}
                  style={{ ...mentionItemStyle, ...(i === mention.selected ? mentionItemActiveStyle : null) }}
                >
                  {doc}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div style={composerActionsStyle}>
          {streaming ? (
            <button onClick={stop} style={stopButtonStyle}>Остановить</button>
          ) : (
            <button onClick={send} style={sendButtonStyle} disabled={!input.trim()}>Отправить</button>
          )}
        </div>
      </div>
    </div>
  )
}

interface DocNodeShape { name: string; path: string; type: 'file' | 'dir'; children?: DocNodeShape[] }

function flattenDocs(tree: DocNodeShape[]): string[] {
  const out: string[] = []
  const walk = (nodes: DocNodeShape[]) => {
    for (const n of nodes) {
      if (n.type === 'file') out.push(n.path)
      else if (n.children) walk(n.children)
    }
  }
  walk(tree)
  return out
}

function extractAttachedDocs(text: string, available: string[]): string[] {
  const pool = new Set(available)
  const found = new Set<string>()
  for (const m of text.matchAll(/(?:^|\s)@(\S+)/g)) {
    if (pool.has(m[1])) found.add(m[1])
  }
  return Array.from(found)
}

function MessageView({ message }: { message: Message }) {
  if (message.role === 'user') {
    const text = message.blocks.find((b): b is Extract<Block, { type: 'text' }> => b.type === 'text')?.text ?? ''
    return (
      <div style={userMessageStyle}>
        <div style={userBubbleStyle}>{text}</div>
      </div>
    )
  }
  return (
    <div style={assistantMessageStyle}>
      {message.blocks.length === 0 ? (
        <div style={typingDotsStyle}>помощник думает…</div>
      ) : (
        message.blocks.map((b, i) => <BlockView key={i} block={b} />)
      )}
    </div>
  )
}

function BlockView({ block }: { block: Block }) {
  if (block.type === 'text') return <MarkdownRender source={block.text} />
  if (block.type === 'error') {
    return <div style={errorBlockStyle}>Ошибка: {block.message}</div>
  }
  if (block.type === 'tool_use') {
    const inputText = formatToolInput(block.input)
    return (
      <details style={toolBlockStyle}>
        <summary style={toolSummaryStyle}>▸ вызов {block.name}</summary>
        <pre style={toolPreStyle}>{inputText}</pre>
      </details>
    )
  }
  return (
    <details style={toolBlockStyle}>
      <summary style={toolSummaryStyle}>◂ результат инструмента</summary>
      <pre style={toolPreStyle}>{block.content}</pre>
    </details>
  )
}

function formatToolInput(input: unknown): string {
  try { return JSON.stringify(input, null, 2) } catch { return String(input) }
}

function toApiMessage(m: Message): { role: string; text: string } {
  const text = m.blocks
    .map((b) => (b.type === 'text' ? b.text : ''))
    .filter(Boolean)
    .join('\n')
  return { role: m.role, text }
}

function applyEventToLast(prev: Message[], evt: AssistantEvent): Message[] {
  if (prev.length === 0) return prev
  const last = prev[prev.length - 1]
  if (last.role !== 'assistant') return prev
  const updated: Message = { ...last, blocks: [...last.blocks] }
  switch (evt.type) {
    case 'text': {
      const tail = updated.blocks[updated.blocks.length - 1]
      if (tail && tail.type === 'text') {
        updated.blocks[updated.blocks.length - 1] = { type: 'text', text: tail.text + (evt.text ?? '') }
      } else {
        updated.blocks.push({ type: 'text', text: evt.text ?? '' })
      }
      break
    }
    case 'tool_use':
      updated.blocks.push({ type: 'tool_use', name: evt.name ?? '', input: evt.input })
      break
    case 'tool_result':
      updated.blocks.push({ type: 'tool_result', content: evt.content ?? '' })
      break
    case 'error':
      updated.blocks.push({ type: 'error', message: evt.message ?? 'неизвестная ошибка' })
      break
    case 'done':
    default:
      return prev.map((m, i) => (i === prev.length - 1 ? updated : m))
  }
  return prev.map((m, i) => (i === prev.length - 1 ? updated : m))
}

interface StreamArgs {
  history: { role: string; text: string }[]
  researchId: string
  attachedDocs: string[]
  signal: AbortSignal
  onEvent: (evt: AssistantEvent) => void
}

async function streamFromBackend({ history, researchId, attachedDocs, signal, onEvent }: StreamArgs) {
  const response = await fetch('/api/assistant/messages', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ history, researchId, attachedDocs }),
    signal,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(`HTTP ${response.status}: ${text}`)
  }
  const reader = response.body?.getReader()
  if (!reader) return
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trimEnd()
      buf = buf.slice(nl + 1)
      if (line.startsWith('data:')) {
        const payload = line.slice(5).trim()
        if (!payload) continue
        try { onEvent(JSON.parse(payload) as AssistantEvent) } catch { /* ignore malformed event */ }
      }
    }
  }
}

const rootStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  height: '100%',
  fontFamily: 'system-ui, -apple-system, sans-serif',
  background: 'white',
}

const messagesPaneStyle: CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '14px 18px',
  display: 'flex',
  flexDirection: 'column',
  gap: 14,
}

const emptyStateStyle: CSSProperties = {
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
  padding: '40px 20px',
  fontSize: 14,
}

const userMessageStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
}

const userBubbleStyle: CSSProperties = {
  background: '#1976d2',
  color: 'white',
  padding: '8px 14px',
  borderRadius: 14,
  maxWidth: '75%',
  whiteSpace: 'pre-wrap',
  fontSize: 14,
}

const assistantMessageStyle: CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
  padding: '4px 0',
}

const typingDotsStyle: CSSProperties = {
  color: '#888',
  fontStyle: 'italic',
  fontSize: 13,
}

const toolBlockStyle: CSSProperties = {
  background: '#f7f7f7',
  border: '1px solid #e5e5e5',
  borderRadius: 6,
  padding: '4px 8px',
  fontSize: 12,
  color: '#555',
}

const toolSummaryStyle: CSSProperties = {
  cursor: 'pointer',
  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
  userSelect: 'none',
}

const toolPreStyle: CSSProperties = {
  margin: '6px 0 2px 0',
  padding: 6,
  background: 'white',
  borderRadius: 4,
  border: '1px solid #eaeaea',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  maxHeight: 240,
  overflowY: 'auto',
  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
  fontSize: 12,
}

const errorBlockStyle: CSSProperties = {
  background: '#fdecea',
  border: '1px solid #f5c6cb',
  color: '#a4262c',
  padding: '8px 12px',
  borderRadius: 6,
  fontSize: 13,
}

const composerStyle: CSSProperties = {
  borderTop: '1px solid #e0e0e0',
  padding: '10px 14px',
  background: '#fafafa',
}

const composerInputWrapStyle: CSSProperties = {
  position: 'relative',
}

const textareaStyle: CSSProperties = {
  width: '100%',
  boxSizing: 'border-box',
  resize: 'none',
  padding: 8,
  fontSize: 14,
  fontFamily: 'inherit',
  border: '1px solid #ccc',
  borderRadius: 6,
  outline: 'none',
}

const mentionDropdownStyle: CSSProperties = {
  position: 'absolute',
  bottom: '100%',
  left: 0,
  right: 0,
  marginBottom: 4,
  background: 'white',
  border: '1px solid #ccc',
  borderRadius: 6,
  listStyle: 'none',
  padding: 4,
  margin: 0,
  maxHeight: 220,
  overflowY: 'auto',
  boxShadow: '0 4px 10px rgba(0,0,0,0.12)',
  zIndex: 100,
  fontSize: 13,
}

const mentionItemStyle: CSSProperties = {
  padding: '5px 8px',
  cursor: 'pointer',
  borderRadius: 4,
  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
  color: '#333',
}

const mentionItemActiveStyle: CSSProperties = {
  background: '#e3f2fd',
  color: '#0d47a1',
}

const composerActionsStyle: CSSProperties = {
  display: 'flex',
  justifyContent: 'flex-end',
  marginTop: 8,
}

const sendButtonStyle: CSSProperties = {
  padding: '6px 16px',
  fontSize: 13,
  background: '#1976d2',
  color: 'white',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const stopButtonStyle: CSSProperties = {
  padding: '6px 16px',
  fontSize: 13,
  background: '#e53935',
  color: 'white',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const blockedStyle: CSSProperties = {
  padding: 24,
  color: '#888',
  textAlign: 'center',
  fontStyle: 'italic',
  fontSize: 14,
}
