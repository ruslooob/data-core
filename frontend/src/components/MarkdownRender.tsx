import type { CSSProperties, ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'

/**
 * Общий рендер markdown-текста для виджетов помощника и документации.
 * Поддерживает GFM-таблицы и подсветку кода. Внутренние ссылки на .md
 * перехватываются — навигация делегируется родителю через onLinkClick.
 */
export interface MarkdownRenderProps {
  source: string
  onLinkClick?: (href: string) => void
}

export function MarkdownRender({ source, onLinkClick }: MarkdownRenderProps) {
  return (
    <div style={containerStyle}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ inline, className, children, ...props }: CodeProps) {
            const match = /language-(\w+)/.exec(className || '')
            if (!inline && match) {
              return (
                <SyntaxHighlighter
                  language={match[1]}
                  style={oneLight}
                  PreTag="div"
                  customStyle={syntaxBlockStyle}
                >
                  {String(children).replace(/\n$/, '')}
                </SyntaxHighlighter>
              )
            }
            return (
              <code className={className} style={inlineCodeStyle} {...props}>
                {children}
              </code>
            )
          },
          a({ href, children, ...props }) {
            const isInternalMd = href && !/^https?:\/\//.test(href) && /\.md(#.*)?$/.test(href)
            if (isInternalMd && onLinkClick) {
              return (
                <a
                  href={href}
                  onClick={(e) => { e.preventDefault(); onLinkClick(href) }}
                  style={linkStyle}
                >
                  {children}
                </a>
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" style={linkStyle} {...props}>
                {children}
              </a>
            )
          },
          table({ children }) { return <table style={tableStyle}>{children}</table> },
          th({ children }) { return <th style={thStyle}>{children}</th> },
          td({ children }) { return <td style={tdStyle}>{children}</td> },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  )
}

interface CodeProps {
  inline?: boolean
  className?: string
  children?: ReactNode
}

const containerStyle: CSSProperties = {
  fontFamily: 'system-ui, -apple-system, sans-serif',
  fontSize: 14,
  lineHeight: 1.55,
  color: '#222',
}

const inlineCodeStyle: CSSProperties = {
  background: '#f4f4f4',
  padding: '1px 5px',
  borderRadius: 3,
  fontSize: '0.92em',
  fontFamily: 'Consolas, Monaco, "Courier New", monospace',
}

const syntaxBlockStyle: CSSProperties = {
  borderRadius: 6,
  fontSize: 13,
  margin: '8px 0',
}

const linkStyle: CSSProperties = {
  color: '#1565c0',
  textDecoration: 'none',
  borderBottom: '1px solid #bbdefb',
}

const tableStyle: CSSProperties = {
  borderCollapse: 'collapse',
  margin: '8px 0',
  fontSize: 13,
}

const thStyle: CSSProperties = {
  border: '1px solid #ccc',
  padding: '6px 10px',
  background: '#f0f0f0',
  textAlign: 'left',
  fontWeight: 600,
}

const tdStyle: CSSProperties = {
  border: '1px solid #ddd',
  padding: '6px 10px',
  verticalAlign: 'top',
}
