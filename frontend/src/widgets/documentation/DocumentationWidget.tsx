import { useEffect, useMemo, useState, type CSSProperties } from 'react'
import { MarkdownRender } from '../../components/MarkdownRender'

/**
 * Виджет просмотра документации проекта.
 * Слева — дерево документов, справа — markdown выбранного.
 * Внутренние ссылки между документами открываются внутри виджета.
 */
interface DocNode {
  name: string
  path: string
  type: 'file' | 'dir'
  children?: DocNode[]
}

export function DocumentationWidget() {
  const [tree, setTree] = useState<DocNode[] | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)
  const [activePath, setActivePath] = useState<string | null>(null)
  const [content, setContent] = useState<string>('')
  const [contentError, setContentError] = useState<string | null>(null)

  useEffect(() => {
    let abort = false
    fetch('/api/docs/tree')
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then((data) => { if (!abort) { setTree(data); setActivePath(firstFilePath(data)) } })
      .catch((e) => { if (!abort) setTreeError(String(e)) })
    return () => { abort = true }
  }, [])

  useEffect(() => {
    if (!activePath) return
    let abort = false
    setContentError(null)
    fetch(`/api/docs/content?path=${encodeURIComponent(activePath)}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.text() })
      .then((text) => { if (!abort) setContent(text) })
      .catch((e) => { if (!abort) setContentError(String(e)) })
    return () => { abort = true }
  }, [activePath])

  const onInternalLink = (href: string) => {
    if (!activePath) { setActivePath(stripAnchor(href)); return }
    const base = activePath.includes('/') ? activePath.slice(0, activePath.lastIndexOf('/') + 1) : ''
    const target = resolveRelativePath(base, stripAnchor(href))
    setActivePath(target)
  }

  return (
    <div style={rootStyle}>
      <aside style={treePaneStyle}>
        {treeError ? <div style={errorTextStyle}>{treeError}</div> :
          tree ? <DocTree nodes={tree} active={activePath} onSelect={setActivePath} level={0} /> :
          <div style={loadingTextStyle}>Загрузка дерева…</div>
        }
      </aside>
      <section style={contentPaneStyle}>
        {!activePath ? <div style={placeholderStyle}>Выберите документ слева</div> :
         contentError ? <div style={errorTextStyle}>{contentError}</div> :
         <MarkdownRender source={content} onLinkClick={onInternalLink} />
        }
      </section>
    </div>
  )
}

interface DocTreeProps {
  nodes: DocNode[]
  active: string | null
  onSelect: (path: string) => void
  level: number
}

function DocTree({ nodes, active, onSelect, level }: DocTreeProps) {
  const listStyle = level === 0 ? treeListRootStyle : treeListNestedStyle
  return (
    <ul style={listStyle}>
      {nodes.map((n) => <TreeItem key={n.path} node={n} active={active} onSelect={onSelect} level={level} />)}
    </ul>
  )
}

function TreeItem({ node, active, onSelect, level }: { node: DocNode; active: string | null; onSelect: (p: string) => void; level: number }) {
  const [open, setOpen] = useState(true)
  if (node.type === 'dir') {
    return (
      <li>
        <div style={dirRowStyle} onClick={() => setOpen((v) => !v)}>
          <span style={dirCaretStyle}>{open ? '▾' : '▸'}</span>{node.name}
        </div>
        {open && node.children && <DocTree nodes={node.children} active={active} onSelect={onSelect} level={level + 1} />}
      </li>
    )
  }
  const isActive = active === node.path
  return (
    <li>
      <div
        onClick={() => onSelect(node.path)}
        style={{ ...fileRowStyle, ...(isActive ? activeFileRowStyle : null) }}
      >
        {node.name}
      </div>
    </li>
  )
}

function firstFilePath(nodes: DocNode[]): string | null {
  for (const n of nodes) {
    if (n.type === 'file') return n.path
    if (n.children) { const inner = firstFilePath(n.children); if (inner) return inner }
  }
  return null
}

function stripAnchor(href: string): string {
  const i = href.indexOf('#')
  return i >= 0 ? href.slice(0, i) : href
}

function resolveRelativePath(baseDir: string, href: string): string {
  if (href.startsWith('/')) return href.slice(1)
  const parts = (baseDir + href).split('/')
  const stack: string[] = []
  for (const p of parts) {
    if (p === '' || p === '.') continue
    if (p === '..') { stack.pop(); continue }
    stack.push(p)
  }
  return stack.join('/')
}

const rootStyle: CSSProperties = {
  display: 'flex',
  height: '100%',
  fontFamily: 'system-ui, -apple-system, sans-serif',
}

const treePaneStyle: CSSProperties = {
  width: 260,
  borderRight: '1px solid #e0e0e0',
  overflowY: 'auto',
  padding: '10px 8px',
  background: '#fafafa',
  fontSize: 13,
}

const contentPaneStyle: CSSProperties = {
  flex: 1,
  overflowY: 'auto',
  padding: '14px 22px',
  background: 'white',
}

const treeListRootStyle: CSSProperties = {
  listStyle: 'none',
  padding: 0,
  margin: 0,
}

const treeListNestedStyle: CSSProperties = {
  listStyle: 'none',
  padding: 0,
  paddingLeft: 16,
  margin: 0,
}

const dirRowStyle: CSSProperties = {
  cursor: 'pointer',
  padding: '3px 4px',
  userSelect: 'none',
  fontWeight: 600,
  color: '#444',
}

const dirCaretStyle: CSSProperties = {
  display: 'inline-block',
  width: 14,
  color: '#888',
}

const fileRowStyle: CSSProperties = {
  cursor: 'pointer',
  padding: '3px 4px 3px 14px',
  borderRadius: 3,
  color: '#333',
}

const activeFileRowStyle: CSSProperties = {
  background: '#e3f2fd',
  color: '#0d47a1',
  fontWeight: 600,
}

const placeholderStyle: CSSProperties = {
  color: '#999',
  fontStyle: 'italic',
  padding: 20,
}

const errorTextStyle: CSSProperties = {
  color: '#c62828',
  padding: 10,
  fontSize: 13,
}

const loadingTextStyle: CSSProperties = {
  color: '#999',
  padding: 10,
  fontSize: 13,
}
