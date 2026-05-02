import { useMemo } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { sql, PostgreSQL } from '@codemirror/lang-sql'
import { Prec } from '@codemirror/state'
import { keymap } from '@codemirror/view'

interface SqlEditorProps {
  value: string
  onChange: (next: string) => void
  readOnly?: boolean
  onSubmit?: () => void
  minHeight?: number
  fontSize?: number
}

export function SqlEditor({
  value,
  onChange,
  readOnly = false,
  onSubmit,
  minHeight = 80,
  fontSize = 13,
}: SqlEditorProps) {
  const extensions = useMemo(() => {
    const list: any[] = [sql({ dialect: PostgreSQL, upperCaseKeywords: false })]
    if (onSubmit) {
      list.push(
        Prec.highest(
          keymap.of([
            { key: 'Mod-Enter', run: () => { onSubmit(); return true } },
          ]),
        ),
      )
    }
    return list
  }, [onSubmit])

  return (
    <div style={{ ...wrapperStyle, minHeight }}>
      <CodeMirror
        value={value}
        onChange={readOnly ? undefined : onChange}
        extensions={extensions}
        editable={!readOnly}
        basicSetup={{
          lineNumbers: false,
          highlightActiveLine: false,
          foldGutter: false,
          bracketMatching: true,
          autocompletion: false,
        }}
        style={{ fontSize, fontFamily: 'Consolas, Menlo, monospace' }}
      />
    </div>
  )
}

const wrapperStyle: React.CSSProperties = {
  border: '1px solid #ccc',
  borderRadius: 4,
  overflow: 'hidden',
}
