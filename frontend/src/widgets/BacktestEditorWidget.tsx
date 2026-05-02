import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createEnvironment,
  createRule,
  createStrategy,
  deleteStrategy,
  listEnvironments,
  listRules,
  listStrategies,
  renameStrategy,
} from '../api/client'
import type { ActionType, Environment, Rule, Strategy } from '../api/types'
import { SearchablePicker } from './SearchablePicker'
import { SqlEditor } from './SqlEditor'

// ── Типы черновика формы создания ──────────────────────────────────────────

type EnvDraft =
  | { kind: 'none' }
  | { kind: 'inline'; name: string; dateStart: string; dateEnd: string; startingCapital: string }
  | { kind: 'imported'; envId: string }

interface InlineRuleDraft {
  name: string
  triggerSql: string
  actionType: ActionType
  actionQuantitySql: string
  priority: string
}

type RuleDraft = {
  localId: string
  expanded: boolean
} & (
  | { source: 'inline'; data: InlineRuleDraft }
  | { source: 'imported'; ruleId: string }
)

interface FormState {
  name: string
  env: EnvDraft
  rules: RuleDraft[]
  envExpanded: boolean
}

const EMPTY_FORM: FormState = {
  name: '',
  env: { kind: 'none' },
  rules: [],
  envExpanded: true,
}

const EMPTY_INLINE_RULE: InlineRuleDraft = {
  name: '',
  triggerSql: '',
  actionType: 'buy',
  actionQuantitySql: '',
  priority: '100',
}

// ── Auto-name ──────────────────────────────────────────────────────────────

function autoName(): string {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `Untitled-${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}-${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// Если базовое имя уже занято (409) — добавляем числовой суффикс -2, -3 …
async function withCollisionRetry<T>(
  base: string,
  fn: (candidateName: string) => Promise<T>,
): Promise<T> {
  let attempt = 1
  while (true) {
    const candidate = attempt === 1 ? base : `${base}-${attempt}`
    try {
      return await fn(candidate)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      if (msg.includes('уже существует') && attempt < 99) {
        attempt += 1
        continue
      }
      throw e
    }
  }
}

// ── Mode ───────────────────────────────────────────────────────────────────

type Mode =
  | { kind: 'idle' }
  | { kind: 'view'; strategyId: string }
  | { kind: 'create' }

// ── Главный компонент ──────────────────────────────────────────────────────

export function BacktestEditorWidget() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [rules, setRules] = useState<Rule[]>([])
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [mode, setMode] = useState<Mode>({ kind: 'idle' })
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY_FORM)

  const refresh = useCallback(async () => {
    try {
      const [s, r, e] = await Promise.all([listStrategies(), listRules(), listEnvironments()])
      setStrategies(s)
      setRules(r)
      setEnvironments(e)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const ruleById = useMemo(() => {
    const m = new Map<string, Rule>()
    for (const r of rules) m.set(r.id, r)
    return m
  }, [rules])

  const envById = useMemo(() => {
    const m = new Map<string, Environment>()
    for (const e of environments) m.set(e.id, e)
    return m
  }, [environments])

  const selectedStrategy = mode.kind === 'view'
    ? strategies.find((s) => s.id === mode.strategyId) ?? null
    : null

  const startCreate = () => {
    setForm(EMPTY_FORM)
    setMode({ kind: 'create' })
    setError(null)
  }

  const cancelCreate = () => {
    setForm(EMPTY_FORM)
    setMode({ kind: 'idle' })
    setError(null)
  }

  const onSubmitCreate = async () => {
    if (!form.name.trim()) {
      setError('Имя стратегии не может быть пустым')
      return
    }
    if (form.rules.length === 0) {
      setError('Стратегия должна содержать минимум одно правило')
      return
    }
    setSaving(true)
    setError(null)
    try {
      // 1. Создать inline-environment если есть
      if (form.env.kind === 'inline') {
        const env = form.env
        const envName = env.name.trim() || autoName()
        const cap = parseFloat(env.startingCapital)
        if (!Number.isFinite(cap) || cap <= 0) {
          throw new Error('startingCapital должен быть положительным числом')
        }
        await withCollisionRetry(envName, (n) =>
          createEnvironment({
            name: n,
            dateStart: env.dateStart,
            dateEnd: env.dateEnd,
            startingCapital: cap,
          }),
        )
      }

      // 2. Для каждой inline-rule — POST /api/rules (с auto-name при пустом имени).
      //    Собираем итоговый список ruleIds в порядке формы.
      const ruleIds: string[] = []
      for (const draft of form.rules) {
        if (draft.source === 'imported') {
          ruleIds.push(draft.ruleId)
        } else {
          const inline = draft.data
          const baseName = inline.name.trim() || autoName()
          const priority = parseInt(inline.priority, 10)
          if (!Number.isFinite(priority)) {
            throw new Error(`Priority правила "${baseName}" должен быть целым числом`)
          }
          if (!inline.triggerSql.trim()) {
            throw new Error(`У правила "${baseName}" пустой триггер`)
          }
          if (!inline.actionQuantitySql.trim()) {
            throw new Error(`У правила "${baseName}" пустой actionQuantitySql`)
          }
          const created = await withCollisionRetry(baseName, (n) =>
            createRule({
              name: n,
              triggerSql: inline.triggerSql,
              actionType: inline.actionType,
              actionQuantitySql: inline.actionQuantitySql,
              priority,
            }),
          )
          ruleIds.push(created.id)
        }
      }

      // 3. Создать стратегию
      const created = await withCollisionRetry(form.name.trim(), (n) =>
        createStrategy({ name: n, ruleIds }),
      )

      await refresh()
      setForm(EMPTY_FORM)
      setMode({ kind: 'view', strategyId: created.id })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const onRenameStrategy = async (id: string, name: string) => {
    setError(null)
    try {
      await renameStrategy(id, name)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  const onDeleteStrategy = async (id: string) => {
    if (!confirm('Удалить стратегию? Прогоны и сделки этой стратегии будут удалены.')) return
    setError(null)
    try {
      await deleteStrategy(id)
      await refresh()
      setMode({ kind: 'idle' })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div style={rootStyle}>
      {error && <div style={errorBannerStyle}>{error}</div>}
      <div style={bodyStyle}>
        <div style={leftPanelStyle}>
          <button
            style={newButtonStyle}
            onClick={startCreate}
            disabled={mode.kind === 'create'}
          >
            + Новая стратегия
          </button>
          <div style={listStyle}>
            {strategies.length === 0 ? (
              <div style={emptyHintStyle}>Стратегий пока нет</div>
            ) : (
              strategies.map((s) => (
                <div
                  key={s.id}
                  onClick={() => setMode({ kind: 'view', strategyId: s.id })}
                  style={
                    mode.kind === 'view' && mode.strategyId === s.id
                      ? listItemActiveStyle
                      : listItemStyle
                  }
                >
                  {s.name}
                </div>
              ))
            )}
          </div>
        </div>
        <div style={rightPanelStyle}>
          {mode.kind === 'idle' && (
            <div style={emptyHintStyle}>Выберите стратегию слева или создайте новую</div>
          )}
          {mode.kind === 'create' && (
            <CreateForm
              form={form}
              setForm={setForm}
              rules={rules}
              ruleById={ruleById}
              environments={environments}
              envById={envById}
              saving={saving}
              onCancel={cancelCreate}
              onSubmit={onSubmitCreate}
            />
          )}
          {mode.kind === 'view' && selectedStrategy && (
            <ViewPanel
              strategy={selectedStrategy}
              ruleById={ruleById}
              onRename={(name) => onRenameStrategy(selectedStrategy.id, name)}
              onDelete={() => onDeleteStrategy(selectedStrategy.id)}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Форма создания ─────────────────────────────────────────────────────────

function CreateForm(props: {
  form: FormState
  setForm: React.Dispatch<React.SetStateAction<FormState>>
  rules: Rule[]
  ruleById: Map<string, Rule>
  environments: Environment[]
  envById: Map<string, Environment>
  saving: boolean
  onCancel: () => void
  onSubmit: () => void
}) {
  const { form, setForm } = props

  const setEnv = (env: EnvDraft) => setForm((f) => ({ ...f, env }))
  const toggleEnvSection = () => setForm((f) => ({ ...f, envExpanded: !f.envExpanded }))

  const addInlineRule = () => {
    const draft: RuleDraft = {
      localId: `local-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      expanded: true,
      source: 'inline',
      data: { ...EMPTY_INLINE_RULE },
    }
    setForm((f) => ({ ...f, rules: [...f.rules, draft] }))
  }

  const addImportedRule = (ruleId: string) => {
    if (form.rules.some((r) => r.source === 'imported' && r.ruleId === ruleId)) return
    const draft: RuleDraft = {
      localId: `import-${ruleId}`,
      expanded: false,
      source: 'imported',
      ruleId,
    }
    setForm((f) => ({ ...f, rules: [...f.rules, draft] }))
  }

  const removeRule = (localId: string) =>
    setForm((f) => ({ ...f, rules: f.rules.filter((r) => r.localId !== localId) }))

  const moveRule = (localId: string, delta: -1 | 1) => {
    setForm((f) => {
      const idx = f.rules.findIndex((r) => r.localId === localId)
      if (idx < 0) return f
      const target = idx + delta
      if (target < 0 || target >= f.rules.length) return f
      const next = [...f.rules]
      ;[next[idx], next[target]] = [next[target], next[idx]]
      return { ...f, rules: next }
    })
  }

  const toggleRuleExpanded = (localId: string) =>
    setForm((f) => ({
      ...f,
      rules: f.rules.map((r) => (r.localId === localId ? { ...r, expanded: !r.expanded } : r)),
    }))

  const updateInlineRule = (localId: string, patch: Partial<InlineRuleDraft>) =>
    setForm((f) => ({
      ...f,
      rules: f.rules.map((r) =>
        r.localId === localId && r.source === 'inline'
          ? { ...r, data: { ...r.data, ...patch } }
          : r,
      ),
    }))

  const importableRules = props.rules.filter(
    (r) => !form.rules.some((fr) => fr.source === 'imported' && fr.ruleId === r.id),
  )

  return (
    <div style={formStyle}>
      <div style={formHeaderStyle}>
        <input
          type="text"
          value={form.name}
          onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          placeholder="Имя стратегии"
          style={nameInputStyle}
        />
        <div style={formActionsStyle}>
          <button
            style={primaryButtonStyle}
            disabled={props.saving}
            onClick={props.onSubmit}
          >
            {props.saving ? 'Сохранение…' : 'Создать стратегию'}
          </button>
          <button style={secondaryButtonStyle} onClick={props.onCancel} disabled={props.saving}>
            Отмена
          </button>
        </div>
      </div>

      {/* Секция Environment */}
      <Section
        title="Окружение"
        expanded={form.envExpanded}
        onToggle={toggleEnvSection}
      >
        <EnvSection
          env={form.env}
          setEnv={setEnv}
          environments={props.environments}
          envById={props.envById}
        />
      </Section>

      {/* Секция Правила */}
      <Section
        title={`Правила (${form.rules.length})`}
        expanded
        onToggle={() => { /* всегда развёрнуто */ }}
        alwaysOpen
      >
        <div style={ruleListContainerStyle}>
          {form.rules.length === 0 && (
            <div style={emptyHintStyle}>Добавьте правило: новое или из общих</div>
          )}
          {form.rules.map((draft, i) => (
            <RuleAccordion
              key={draft.localId}
              draft={draft}
              ruleById={props.ruleById}
              index={i}
              total={form.rules.length}
              onToggle={() => toggleRuleExpanded(draft.localId)}
              onRemove={() => removeRule(draft.localId)}
              onMove={(delta) => moveRule(draft.localId, delta)}
              onChange={(patch) => updateInlineRule(draft.localId, patch)}
            />
          ))}
          <div style={ruleAddRowStyle}>
            <button style={secondaryButtonStyle} onClick={addInlineRule}>
              + Новое правило
            </button>
            <ImportRulePicker
              importable={importableRules}
              onPick={(ruleId) => addImportedRule(ruleId)}
            />
          </div>
        </div>
      </Section>
    </div>
  )
}

// ── Секция-обёртка ─────────────────────────────────────────────────────────

function Section(props: {
  title: string
  expanded: boolean
  onToggle: () => void
  alwaysOpen?: boolean
  children: React.ReactNode
}) {
  return (
    <div style={sectionStyle}>
      <div
        style={sectionHeaderStyle}
        onClick={props.alwaysOpen ? undefined : props.onToggle}
      >
        <span>
          {!props.alwaysOpen && (props.expanded ? '▾' : '▸')} {props.title}
        </span>
      </div>
      {(props.expanded || props.alwaysOpen) && (
        <div style={sectionBodyStyle}>{props.children}</div>
      )}
    </div>
  )
}

// ── Секция Environment ────────────────────────────────────────────────────

function EnvSection(props: {
  env: EnvDraft
  setEnv: (env: EnvDraft) => void
  environments: Environment[]
  envById: Map<string, Environment>
}) {
  const { env, setEnv } = props

  if (env.kind === 'none') {
    return (
      <div style={envEmptyStyle}>
        <div style={emptyHintStyle}>Окружение не задано</div>
        <div style={ruleAddRowStyle}>
          <button
            style={secondaryButtonStyle}
            onClick={() =>
              setEnv({
                kind: 'inline',
                name: '',
                dateStart: '2020-01-01',
                dateEnd: '2025-12-31',
                startingCapital: '1000000',
              })
            }
          >
            + Новое окружение
          </button>
          <ImportEnvPicker
            environments={props.environments}
            onPick={(envId) => setEnv({ kind: 'imported', envId })}
          />
        </div>
      </div>
    )
  }

  if (env.kind === 'imported') {
    const e = props.envById.get(env.envId)
    if (!e) {
      return <div style={emptyHintStyle}>Импортированное окружение не найдено (id={env.envId})</div>
    }
    return (
      <div style={envCardStyle}>
        <div style={envCardHeaderStyle}>
          <span style={envCardTitleStyle}>{e.name} <span style={readOnlyBadgeStyle}>импорт</span></span>
          <button style={iconBtnStyle} onClick={() => setEnv({ kind: 'none' })} title="Убрать">×</button>
        </div>
        <div style={envCardRowStyle}>период: {e.dateStart} — {e.dateEnd}</div>
        <div style={envCardRowStyle}>стартовый капитал: {e.startingCapital.toLocaleString('ru-RU')}</div>
      </div>
    )
  }

  // inline
  return (
    <div style={envCardStyle}>
      <div style={envCardHeaderStyle}>
        <input
          type="text"
          value={env.name}
          onChange={(e2) => setEnv({ ...env, name: e2.target.value })}
          placeholder="Имя (пусто → Untitled-…)"
          style={inputStyle}
        />
        <button style={iconBtnStyle} onClick={() => setEnv({ kind: 'none' })} title="Убрать">×</button>
      </div>
      <div style={envFieldsStyle}>
        <label style={fieldLabelStyle}>
          dateStart
          <input
            type="date"
            value={env.dateStart}
            onChange={(e2) => setEnv({ ...env, dateStart: e2.target.value })}
            style={inputStyle}
          />
        </label>
        <label style={fieldLabelStyle}>
          dateEnd
          <input
            type="date"
            value={env.dateEnd}
            onChange={(e2) => setEnv({ ...env, dateEnd: e2.target.value })}
            style={inputStyle}
          />
        </label>
        <label style={fieldLabelStyle}>
          startingCapital
          <input
            type="number"
            value={env.startingCapital}
            onChange={(e2) => setEnv({ ...env, startingCapital: e2.target.value })}
            style={inputStyle}
          />
        </label>
      </div>
    </div>
  )
}

function ImportEnvPicker(props: {
  environments: Environment[]
  onPick: (envId: string) => void
}) {
  if (props.environments.length === 0) {
    return <span style={mutedHintStyle}>(общих окружений ещё нет)</span>
  }
  return (
    <SearchablePicker<Environment>
      items={props.environments}
      getKey={(e) => e.id}
      getName={(e) => e.name}
      renderMeta={(e) => `${e.dateStart}…${e.dateEnd}`}
      onPick={(e) => props.onPick(e.id)}
      title="Импортировать из общих"
    />
  )
}

// ── Гармошка одного правила ────────────────────────────────────────────────

function RuleAccordion(props: {
  draft: RuleDraft
  ruleById: Map<string, Rule>
  index: number
  total: number
  onToggle: () => void
  onRemove: () => void
  onMove: (delta: -1 | 1) => void
  onChange: (patch: Partial<InlineRuleDraft>) => void
}) {
  const { draft } = props
  const isImported = draft.source === 'imported'
  const importedRule = isImported ? props.ruleById.get(draft.ruleId) : null

  const headerLabel = isImported
    ? (importedRule ? importedRule.name : `(правило ${draft.ruleId} не найдено)`)
    : (draft.data.name.trim() || '(новое правило, имя не задано)')

  return (
    <div style={ruleAccordionStyle}>
      <div style={ruleAccordionHeaderStyle}>
        <span style={ruleAccordionTitleStyle} onClick={props.onToggle}>
          {draft.expanded ? '▾' : '▸'} {props.index + 1}. {headerLabel}
          {isImported && <span style={readOnlyBadgeStyle}>импорт</span>}
        </span>
        <span style={ruleControlsStyle}>
          <button style={iconBtnStyle} disabled={props.index === 0} onClick={() => props.onMove(-1)} title="Выше">↑</button>
          <button style={iconBtnStyle} disabled={props.index === props.total - 1} onClick={() => props.onMove(+1)} title="Ниже">↓</button>
          <button style={iconBtnStyle} onClick={props.onRemove} title="Убрать из стратегии">×</button>
        </span>
      </div>
      {draft.expanded && (
        <div style={ruleAccordionBodyStyle}>
          {isImported && importedRule ? (
            <ImportedRuleView rule={importedRule} />
          ) : draft.source === 'inline' ? (
            <InlineRuleEditor data={draft.data} onChange={props.onChange} />
          ) : null}
        </div>
      )}
    </div>
  )
}

function InlineRuleEditor(props: {
  data: InlineRuleDraft
  onChange: (patch: Partial<InlineRuleDraft>) => void
}) {
  const { data, onChange } = props
  return (
    <div style={ruleFormStyle}>
      <label style={fieldLabelStyle}>
        Имя (пусто → Untitled-…)
        <input
          type="text"
          value={data.name}
          onChange={(e) => onChange({ name: e.target.value })}
          style={inputStyle}
        />
      </label>
      <div style={ruleRowSplitStyle}>
        <label style={fieldLabelStyle}>
          Тип действия
          <select
            value={data.actionType}
            onChange={(e) => onChange({ actionType: e.target.value as ActionType })}
            style={inputStyle}
          >
            <option value="buy">buy</option>
            <option value="sell">sell</option>
          </select>
        </label>
        <label style={fieldLabelStyle}>
          Priority
          <input
            type="number"
            value={data.priority}
            onChange={(e) => onChange({ priority: e.target.value })}
            style={inputStyle}
          />
        </label>
      </div>
      <label style={fieldLabelStyle}>
        Trigger SQL
        <SqlEditor
          value={data.triggerSql}
          onChange={(v) => onChange({ triggerSql: v })}
          minHeight={80}
        />
      </label>
      <label style={fieldLabelStyle}>
        Action quantity SQL
        <SqlEditor
          value={data.actionQuantitySql}
          onChange={(v) => onChange({ actionQuantitySql: v })}
          minHeight={60}
        />
      </label>
    </div>
  )
}

function ImportedRuleView(props: { rule: Rule }) {
  const { rule } = props
  return (
    <div style={ruleFormStyle}>
      <div style={importedFieldStyle}>
        <span style={fieldLabelStyle}>Имя</span>
        <span>{rule.name}</span>
      </div>
      <div style={ruleRowSplitStyle}>
        <div style={importedFieldStyle}>
          <span style={fieldLabelStyle}>Тип действия</span>
          <span>{rule.actionType}</span>
        </div>
        <div style={importedFieldStyle}>
          <span style={fieldLabelStyle}>Priority</span>
          <span>{rule.priority}</span>
        </div>
      </div>
      <div>
        <span style={fieldLabelStyle}>Trigger SQL</span>
        <SqlEditor value={rule.triggerSql} onChange={() => { /* read-only */ }} readOnly minHeight={80} />
      </div>
      <div>
        <span style={fieldLabelStyle}>Action quantity SQL</span>
        <SqlEditor value={rule.actionQuantitySql} onChange={() => { /* read-only */ }} readOnly minHeight={60} />
      </div>
    </div>
  )
}

function ImportRulePicker(props: {
  importable: Rule[]
  onPick: (ruleId: string) => void
}) {
  if (props.importable.length === 0) {
    return <span style={mutedHintStyle}>(общих правил ещё нет)</span>
  }
  return (
    <SearchablePicker<Rule>
      items={props.importable}
      getKey={(r) => r.id}
      getName={(r) => r.name}
      renderMeta={(r) => `${r.actionType}, p=${r.priority}`}
      onPick={(r) => props.onPick(r.id)}
      title="Импортировать из общих"
    />
  )
}

// ── Просмотр существующей стратегии ────────────────────────────────────────

function ViewPanel(props: {
  strategy: Strategy
  ruleById: Map<string, Rule>
  onRename: (name: string) => void
  onDelete: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [draftName, setDraftName] = useState(props.strategy.name)

  useEffect(() => {
    setRenaming(false)
    setDraftName(props.strategy.name)
  }, [props.strategy.id, props.strategy.name])

  const submitRename = () => {
    const next = draftName.trim()
    if (next && next !== props.strategy.name) {
      props.onRename(next)
    }
    setRenaming(false)
  }

  return (
    <div style={viewStyle}>
      <div style={viewHeaderStyle}>
        {renaming ? (
          <input
            type="text"
            value={draftName}
            onChange={(e) => setDraftName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') submitRename()
              if (e.key === 'Escape') { setDraftName(props.strategy.name); setRenaming(false) }
            }}
            onBlur={submitRename}
            autoFocus
            style={inputStyle}
          />
        ) : (
          <h3 style={viewTitleStyle} onDoubleClick={() => setRenaming(true)}>
            {props.strategy.name}
          </h3>
        )}
        <div style={viewActionsStyle}>
          <button style={secondaryButtonStyle} onClick={() => setRenaming(true)}>
            Переименовать
          </button>
          <button style={dangerButtonStyle} onClick={props.onDelete}>
            Удалить
          </button>
        </div>
      </div>
      <div style={viewMetaStyle}>Создана: {props.strategy.createdAt}</div>
      <div style={viewSectionTitleStyle}>Правила в порядке исполнения</div>
      <div style={ruleListReadOnlyStyle}>
        {props.strategy.ruleIds.map((rid, i) => {
          const r = props.ruleById.get(rid)
          if (!r) {
            return <div key={rid} style={ruleListItemMissingStyle}>{i + 1}. (правило {rid} не найдено)</div>
          }
          return (
            <details key={rid} style={ruleListReadOnlyItemStyle}>
              <summary style={ruleListReadOnlySummaryStyle}>
                {i + 1}. {r.name} <span style={ruleMetaStyle}>{r.actionType}, p={r.priority}</span>
              </summary>
              <div style={ruleFormStyle}>
                <div>
                  <span style={fieldLabelStyle}>Trigger SQL</span>
                  <SqlEditor value={r.triggerSql} onChange={() => { /* read-only */ }} readOnly minHeight={80} />
                </div>
                <div>
                  <span style={fieldLabelStyle}>Action quantity SQL</span>
                  <SqlEditor value={r.actionQuantitySql} onChange={() => { /* read-only */ }} readOnly minHeight={60} />
                </div>
              </div>
            </details>
          )
        })}
      </div>
    </div>
  )
}

// ── Стили ───────────────────────────────────────────────────────────────────

const rootStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  flex: 1,
  minHeight: 0,
  padding: 8,
  gap: 8,
}

const errorBannerStyle: React.CSSProperties = {
  padding: '8px 12px',
  background: '#fdecea',
  border: '1px solid #f5a8a3',
  borderRadius: 4,
  color: '#a01919',
  fontSize: 12,
}

const bodyStyle: React.CSSProperties = {
  display: 'flex',
  flex: 1,
  minHeight: 0,
  gap: 8,
}

const leftPanelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  width: 240,
  flexShrink: 0,
  gap: 8,
  borderRight: '1px solid #eee',
  paddingRight: 8,
}

const rightPanelStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflow: 'auto',
}

const newButtonStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  background: '#2962FF',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const listStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  overflow: 'auto',
  flex: 1,
}

const listItemStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  cursor: 'pointer',
  borderBottom: '1px solid #f5f5f5',
}

const listItemActiveStyle: React.CSSProperties = {
  ...listItemStyle,
  background: '#eaf2ff',
  fontWeight: 600,
}

const emptyHintStyle: React.CSSProperties = {
  padding: 12,
  fontSize: 12,
  color: '#999',
  fontStyle: 'italic',
  textAlign: 'center',
}

const mutedHintStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#999',
}

const formStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 12,
  padding: 8,
}

const formHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
}

const nameInputStyle: React.CSSProperties = {
  flex: 1,
  fontSize: 16,
  fontWeight: 600,
  padding: '6px 10px',
  border: '1px solid #ccc',
  borderRadius: 4,
  outline: 'none',
}

const formActionsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
}

const primaryButtonStyle: React.CSSProperties = {
  padding: '6px 14px',
  fontSize: 13,
  background: '#2962FF',
  color: '#fff',
  border: 'none',
  borderRadius: 4,
  cursor: 'pointer',
}

const secondaryButtonStyle: React.CSSProperties = {
  padding: '6px 12px',
  fontSize: 13,
  background: '#fff',
  color: '#333',
  border: '1px solid #ccc',
  borderRadius: 4,
  cursor: 'pointer',
}

const dangerButtonStyle: React.CSSProperties = {
  padding: '6px 12px',
  fontSize: 13,
  background: '#fff',
  color: '#a01919',
  border: '1px solid #f5a8a3',
  borderRadius: 4,
  cursor: 'pointer',
}

const sectionStyle: React.CSSProperties = {
  border: '1px solid #e0e0e0',
  borderRadius: 6,
  background: '#fafafa',
}

const sectionHeaderStyle: React.CSSProperties = {
  padding: '8px 12px',
  fontSize: 13,
  fontWeight: 600,
  color: '#333',
  cursor: 'pointer',
  userSelect: 'none',
  borderBottom: '1px solid #eee',
}

const sectionBodyStyle: React.CSSProperties = {
  padding: 12,
  background: '#fff',
}

const inputStyle: React.CSSProperties = {
  fontSize: 13,
  padding: '6px 8px',
  border: '1px solid #ccc',
  borderRadius: 4,
  outline: 'none',
  fontFamily: 'inherit',
}

const fieldLabelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: 12,
  color: '#555',
  fontWeight: 600,
}

const envEmptyStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  gap: 8,
}

const envCardStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  padding: 8,
  border: '1px solid #eee',
  borderRadius: 4,
}

const envCardHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  justifyContent: 'space-between',
}

const envCardTitleStyle: React.CSSProperties = {
  fontWeight: 600,
  fontSize: 14,
}

const envCardRowStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#555',
}

const envFieldsStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr 1fr',
  gap: 8,
}

const ruleAddRowStyle: React.CSSProperties = {
  display: 'flex',
  gap: 8,
  alignItems: 'center',
  padding: '8px 0',
}

const ruleListContainerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
}

const ruleAccordionStyle: React.CSSProperties = {
  border: '1px solid #e0e0e0',
  borderRadius: 4,
}

const ruleAccordionHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '6px 10px',
  background: '#f7f7f7',
}

const ruleAccordionTitleStyle: React.CSSProperties = {
  flex: 1,
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: 600,
}

const ruleAccordionBodyStyle: React.CSSProperties = {
  padding: 10,
  background: '#fff',
}

const ruleControlsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 4,
}

const iconBtnStyle: React.CSSProperties = {
  width: 24,
  height: 24,
  padding: 0,
  border: '1px solid #ccc',
  background: '#fff',
  borderRadius: 4,
  cursor: 'pointer',
  fontSize: 12,
  lineHeight: 1,
}

const ruleFormStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
}

const ruleRowSplitStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: 8,
}

const importedFieldStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
  fontSize: 13,
}

const readOnlyBadgeStyle: React.CSSProperties = {
  marginLeft: 6,
  padding: '1px 6px',
  fontSize: 10,
  borderRadius: 4,
  background: '#eaeaea',
  color: '#555',
  fontWeight: 600,
}

const ruleMetaStyle: React.CSSProperties = {
  color: '#888',
  fontSize: 11,
  marginLeft: 6,
}

const viewStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  padding: 8,
  gap: 8,
}

const viewHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 8,
}

const viewTitleStyle: React.CSSProperties = {
  margin: 0,
  fontSize: 16,
  fontWeight: 600,
}

const viewActionsStyle: React.CSSProperties = {
  display: 'flex',
  gap: 6,
}

const viewMetaStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#888',
}

const viewSectionTitleStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#555',
  marginTop: 8,
}

const ruleListReadOnlyStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
}

const ruleListReadOnlyItemStyle: React.CSSProperties = {
  border: '1px solid #eee',
  borderRadius: 4,
  padding: 4,
}

const ruleListReadOnlySummaryStyle: React.CSSProperties = {
  fontSize: 13,
  cursor: 'pointer',
  padding: '4px 6px',
}

const ruleListItemMissingStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 12,
  color: '#a01919',
  fontStyle: 'italic',
  border: '1px solid #f5a8a3',
  borderRadius: 4,
}
