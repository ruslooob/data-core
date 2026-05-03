import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  cancelBacktestRun,
  createEnvironment,
  createRule,
  createStrategy,
  deleteBacktestResult,
  deleteStrategy,
  getBacktestResult,
  getBacktestRunLog,
  getBacktestRunProgress,
  listBacktestResults,
  listEnvironments,
  listRules,
  listStrategies,
  renameStrategy,
  startBacktestRun,
  updateEnvironmentDescription,
  updateRuleDescription,
  updateStrategyDescription,
} from '../api/client'
import type {
  ActionType,
  BacktestResultDetail,
  BacktestResultMeta,
  BacktestRunProgress,
  Environment,
  Rule,
  Strategy,
} from '../api/types'
import { EquityCurveChart } from './EquityCurveChart'
import { SearchablePicker } from './SearchablePicker'
import { SqlEditor } from './SqlEditor'

// ── Типы черновика формы создания ──────────────────────────────────────────

type EnvDraft =
  | { kind: 'none' }
  | { kind: 'inline'; name: string; dateStart: string; dateEnd: string; startingCapital: string; description: string }
  | { kind: 'imported'; envId: string }

interface InlineRuleDraft {
  name: string
  triggerSql: string
  actionType: ActionType
  actionQuantitySql: string
  priority: string
  description: string
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
  description: string
  env: EnvDraft
  rules: RuleDraft[]
  envExpanded: boolean
}

const EMPTY_FORM: FormState = {
  name: '',
  description: '',
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
  description: '',
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
            description: env.description.trim() || null,
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
              description: inline.description.trim() || null,
            }),
          )
          ruleIds.push(created.id)
        }
      }

      // 3. Создать стратегию
      const created = await withCollisionRetry(form.name.trim(), (n) =>
        createStrategy({ name: n, ruleIds, description: form.description.trim() || null }),
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
              environments={environments}
              envById={envById}
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
      <textarea
        value={form.description}
        onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
        placeholder="Описание стратегии (опционально)"
        style={descriptionTextareaStyle}
        rows={2}
      />

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
                description: '',
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
        <DescriptionEditor
          initial={e.description}
          placeholder="Описание окружения"
          onSave={async (text) => { await updateEnvironmentDescription(e.id, text) }}
        />
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
      <textarea
        value={env.description}
        onChange={(e2) => setEnv({ ...env, description: e2.target.value })}
        placeholder="Описание окружения (опционально)"
        rows={2}
        style={descriptionTextareaStyle}
      />
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
      <label style={fieldLabelStyle}>
        Описание (опционально)
        <textarea
          value={data.description}
          onChange={(e) => onChange({ description: e.target.value })}
          rows={2}
          style={descriptionTextareaStyle}
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
      <div>
        <span style={fieldLabelStyle}>Описание (можно изменить)</span>
        <DescriptionEditor
          initial={rule.description}
          placeholder="Описание правила"
          onSave={async (text) => { await updateRuleDescription(rule.id, text) }}
        />
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
  environments: Environment[]
  envById: Map<string, Environment>
  onRename: (name: string) => void
  onDelete: () => void
}) {
  const [renaming, setRenaming] = useState(false)
  const [draftName, setDraftName] = useState(props.strategy.name)

  // Прогон
  const [selectedEnvId, setSelectedEnvId] = useState<string | null>(null)
  const [activeRun, setActiveRun] = useState<BacktestRunProgress | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [runs, setRuns] = useState<BacktestResultMeta[]>([])
  const [openRunDetail, setOpenRunDetail] = useState<BacktestResultDetail | null>(null)
  const [openRunLoading, setOpenRunLoading] = useState(false)
  const running = activeRun?.status === 'running'

  const refreshRuns = useCallback(async () => {
    try {
      const all = await listBacktestResults()
      setRuns(all.filter((r) => r.strategyId === props.strategy.id))
    } catch {
      // молча
    }
  }, [props.strategy.id])

  useEffect(() => {
    setRenaming(false)
    setDraftName(props.strategy.name)
    setSelectedEnvId(null)
    setRunError(null)
    setActiveRun(null)
    setOpenRunDetail(null)
    void refreshRuns()
  }, [props.strategy.id, props.strategy.name, refreshRuns])

  // Polling прогресса активного прогона раз в секунду.
  // Зависим только от runId, чтобы обновление полей activeRun (через setActiveRun
  // внутри tick'а) не cleanup'ило сам интервал и не отменяло pending getBacktestResult.
  const runId = activeRun?.runId ?? null
  useEffect(() => {
    if (!runId) return
    let stopped = false
    const tick = async () => {
      try {
        const p = await getBacktestRunProgress(runId)
        if (stopped) return
        setActiveRun(p)
        if (p.status === 'done' && p.resultId) {
          stopped = true
          clearInterval(handle)
          await refreshRuns()
          const detail = await getBacktestResult(p.resultId)
          setOpenRunDetail(detail)
        } else if (p.status === 'error') {
          stopped = true
          clearInterval(handle)
          setRunError(p.errorMessage ?? 'Ошибка прогона')
        } else if (p.status === 'cancelled') {
          stopped = true
          clearInterval(handle)
        }
      } catch (e) {
        setRunError(e instanceof Error ? e.message : String(e))
      }
    }
    const handle = setInterval(() => { void tick() }, 1000)
    void tick()  // первый poll сразу, без секундной задержки
    return () => { stopped = true; clearInterval(handle) }
  }, [runId, refreshRuns])

  const submitRename = () => {
    const next = draftName.trim()
    if (next && next !== props.strategy.name) {
      props.onRename(next)
    }
    setRenaming(false)
  }

  const onRun = async () => {
    if (!selectedEnvId) {
      setRunError('Выберите окружение')
      return
    }
    setRunError(null)
    setOpenRunDetail(null)
    try {
      const started = await startBacktestRun({
        strategyId: props.strategy.id,
        environmentId: selectedEnvId,
      })
      // ставим начальное состояние; useEffect выше начнёт polling.
      setActiveRun({
        runId: started.runId,
        strategyId: props.strategy.id,
        environmentId: selectedEnvId,
        status: 'running',
        progress: 0,
        currentDate: null,
        currentEquity: null,
        nTradesSoFar: 0,
        done: false,
        resultId: null,
        errorMessage: null,
      })
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e))
    }
  }

  const onCancelRun = async () => {
    if (!activeRun || activeRun.status !== 'running') return
    try {
      await cancelBacktestRun(activeRun.runId)
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e))
    }
  }

  const onOpenRun = async (id: string) => {
    setOpenRunLoading(true)
    try {
      const detail = await getBacktestResult(id)
      setOpenRunDetail(detail)
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e))
    } finally {
      setOpenRunLoading(false)
    }
  }

  const onDeleteRun = async (id: string) => {
    if (!confirm('Удалить прогон и его сделки?')) return
    try {
      await deleteBacktestResult(id)
      if (openRunDetail?.id === id) setOpenRunDetail(null)
      await refreshRuns()
    } catch (e) {
      setRunError(e instanceof Error ? e.message : String(e))
    }
  }

  const selectedEnv = selectedEnvId ? props.envById.get(selectedEnvId) : null

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
      <StrategyDescriptionEditor strategy={props.strategy} onSaved={refreshRuns} />

      {/* Запуск прогона */}
      <div style={viewSectionTitleStyle}>Запустить прогон</div>
      <div style={runRowStyle}>
        <span style={runLabelStyle}>Окружение:</span>
        <span>
          {selectedEnv
            ? <span>{selectedEnv.name} <span style={ruleMetaStyle}>{selectedEnv.dateStart}…{selectedEnv.dateEnd}</span></span>
            : <span style={mutedHintStyle}>не выбрано</span>}
        </span>
        <SearchablePicker<Environment>
          items={props.environments}
          getKey={(e) => e.id}
          getName={(e) => e.name}
          renderMeta={(e) => `${e.dateStart}…${e.dateEnd}`}
          onPick={(e) => setSelectedEnvId(e.id)}
          title="Выбрать окружение"
        />
        <button
          style={primaryButtonStyle}
          disabled={running}
          onClick={onRun}
          title={selectedEnvId ? 'Запустить прогон' : 'Сначала выберите окружение'}
        >
          {running ? 'Идёт прогон…' : 'Запустить прогон'}
        </button>
        {running && (
          <button style={dangerButtonStyle} onClick={onCancelRun}>
            Отменить
          </button>
        )}
        {!selectedEnvId && !running && (
          <span style={validationHintStyle}>Выберите окружение</span>
        )}
      </div>
      {activeRun && activeRun.status === 'running' && (
        <RunProgressBar progress={activeRun} />
      )}
      {activeRun && activeRun.status === 'cancelled' && (
        <div style={mutedHintStyle}>Прогон отменён</div>
      )}
      {runError && <div style={errorBannerStyle}>{runError}</div>}

      {/* История прогонов */}
      {runs.length > 0 && (
        <>
          <div style={viewSectionTitleStyle}>Прогоны этой стратегии ({runs.length})</div>
          <div style={runListStyle}>
            {runs.map((r) => {
              const env = props.envById.get(r.environmentId)
              return (
                <div
                  key={r.id}
                  style={openRunDetail?.id === r.id ? runListItemActiveStyle : runListItemStyle}
                  onClick={() => void onOpenRun(r.id)}
                >
                  <span style={runListNameStyle}>
                    {env?.name ?? '(окружение удалено)'} <span style={ruleMetaStyle}>{r.createdAt}</span>
                  </span>
                  <span style={runListMetricsStyle}>
                    return={r.totalReturnPct.toFixed(2)}% · trades={r.nTrades}
                  </span>
                  <button
                    style={iconBtnStyle}
                    title="Удалить прогон"
                    onClick={(ev) => { ev.stopPropagation(); void onDeleteRun(r.id) }}
                  >×</button>
                </div>
              )
            })}
          </div>
        </>
      )}

      {/* Карточка открытого результата */}
      {openRunLoading && <div style={mutedHintStyle}>Загрузка…</div>}
      {openRunDetail && <ResultCard result={openRunDetail} />}

      {/* Правила */}
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

function DescriptionEditor(props: {
  initial: string | null | undefined
  onSave: (text: string) => Promise<unknown>
  placeholder?: string
}) {
  const [draft, setDraft] = useState(props.initial ?? '')
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  useEffect(() => { setDraft(props.initial ?? '') }, [props.initial])
  const onSave = async () => {
    setSaving(true)
    try {
      await props.onSave(draft)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }
  if (!editing) {
    return (
      <div style={descViewStyle} onClick={() => setEditing(true)} title="Кликни чтобы изменить">
        {(props.initial && props.initial.trim())
          ? props.initial
          : <span style={mutedHintStyle}>{props.placeholder ?? 'Кликни, чтобы добавить описание'}</span>}
      </div>
    )
  }
  return (
    <div style={descEditWrapStyle}>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={props.placeholder}
        rows={3}
        style={descriptionTextareaStyle}
        autoFocus
      />
      <div style={formActionsStyle}>
        <button style={primaryButtonStyle} disabled={saving} onClick={onSave}>
          {saving ? 'Сохранение…' : 'Сохранить'}
        </button>
        <button style={secondaryButtonStyle} onClick={() => { setDraft(props.initial ?? ''); setEditing(false) }} disabled={saving}>
          Отмена
        </button>
      </div>
    </div>
  )
}

function StrategyDescriptionEditor(props: { strategy: Strategy; onSaved: () => void }) {
  return (
    <DescriptionEditor
      initial={props.strategy.description}
      placeholder="Описание стратегии"
      onSave={async (text) => {
        await updateStrategyDescription(props.strategy.id, text)
        props.onSaved()
      }}
    />
  )
}

function RunProgressBar(props: { progress: BacktestRunProgress }) {
  const p = props.progress
  const pct = Math.round(p.progress * 100)
  return (
    <div style={progressWrapStyle}>
      <div style={progressBarOuterStyle}>
        <div style={{ ...progressBarInnerStyle, width: `${pct}%` }} />
      </div>
      <div style={progressMetaStyle}>
        <span>{pct}%</span>
        {p.currentDate && <span>дата: {p.currentDate}</span>}
        {p.currentEquity != null && <span>equity: {p.currentEquity.toFixed(0)}</span>}
        <span>сделок: {p.nTradesSoFar}</span>
      </div>
      <RunLogTail runId={p.runId} active={p.status === 'running'} />
    </div>
  )
}

function RunLogTail(props: { runId: string; active: boolean }) {
  const [text, setText] = useState('')
  const [collapsed, setCollapsed] = useState(false)
  const cursorRef = useRef(0)
  const containerRef = useRef<HTMLPreElement>(null)

  useEffect(() => {
    if (!props.runId) return
    cursorRef.current = 0
    setText('')
    let stopped = false
    const tick = async () => {
      try {
        const chunk = await getBacktestRunLog(props.runId, cursorRef.current)
        if (stopped) return
        if (chunk.content) {
          setText((prev) => prev + chunk.content)
          // Прокручиваем в конец после следующего рендера.
          setTimeout(() => {
            const el = containerRef.current
            if (el) el.scrollTop = el.scrollHeight
          }, 0)
        }
        cursorRef.current = chunk.next_byte
      } catch {
        // лог-файла ещё нет / 404 — молча, попробуем в следующий тик
      }
    }
    void tick()
    if (!props.active) return
    const handle = setInterval(() => { void tick() }, 1000)
    return () => { stopped = true; clearInterval(handle) }
  }, [props.runId, props.active])

  return (
    <div style={logSectionStyle}>
      <div style={logHeaderStyle}>
        <span style={cardSubtitleStyle}>Лог прогона</span>
        <button style={iconBtnStyle} onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? '▸' : '▾'}
        </button>
      </div>
      {!collapsed && (
        <pre ref={containerRef} style={logBodyStyle}>{text || '(лог пуст)'}</pre>
      )}
    </div>
  )
}

function ResultCard(props: { result: BacktestResultDetail }) {
  const r = props.result
  const fmtPct = (v: number) => `${v.toFixed(2)}%`
  const fmtNum = (v: number | null) => v == null ? '—' : v.toFixed(2)
  return (
    <div style={resultCardStyle}>
      <div style={resultHeaderStyle}>Результат прогона <span style={ruleMetaStyle}>{r.createdAt}</span></div>
      {(r.strategy || r.environment) && (
        <div style={metricsGridStyle}>
          {r.strategy && (
            <div style={cardSubsectionStyle}>
              <div style={cardSubtitleStyle}>Стратегия</div>
              <div>{r.strategy.name}</div>
              {r.strategy.description && (
                <div style={mutedHintStyle}>{r.strategy.description}</div>
              )}
            </div>
          )}
          {r.environment && (
            <div style={cardSubsectionStyle}>
              <div style={cardSubtitleStyle}>Окружение</div>
              <div>{r.environment.name}</div>
              <div style={mutedHintStyle}>
                {r.environment.dateStart} — {r.environment.dateEnd},{' '}
                {r.environment.startingCapital.toLocaleString('ru-RU')}
              </div>
              {r.environment.description && (
                <div style={mutedHintStyle}>{r.environment.description}</div>
              )}
            </div>
          )}
        </div>
      )}
      <div style={metricsGridStyle}>
        <Metric label="Σ доходность" value={fmtPct(r.totalReturnPct)} />
        <Metric label="Год. доходность" value={fmtPct(r.annualReturnPct)} />
        <Metric label="Макс. просадка" value={fmtPct(r.maxDrawdownPct)} />
        <Metric label="Sharpe" value={r.sharpe.toFixed(2)} />
        <Metric label="Сделок" value={String(r.nTrades)} />
        <Metric label="Profit factor" value={fmtNum(r.profitFactor)} />
        <Metric label="Win rate" value={r.winRatePct == null ? '—' : fmtPct(r.winRatePct)} />
      </div>
      <div style={tradesSectionTitleStyle}>Equity-кривая ({r.equityCurve.length} точек)</div>
      <EquityCurveChart data={r.equityCurve} height={260} />
      <div style={tradesSectionTitleStyle}>Журнал сделок ({r.trades.length})</div>
      <div style={tradesTableWrapperStyle}>
        <table style={tradesTableStyle}>
          <thead>
            <tr>
              <th style={tradesThStyle}>Дата</th>
              <th style={tradesThStyle}>Тикер</th>
              <th style={tradesThStyle}>Тип</th>
              <th style={tradesThStyle}>Кол-во</th>
              <th style={tradesThStyle}>Цена</th>
              <th style={tradesThStyle}>PnL</th>
              <th style={tradesThStyle}>Правило</th>
            </tr>
          </thead>
          <tbody>
            {r.trades.map((t, i) => (
              <tr key={i}>
                <td style={tradesTdStyle}>{t.tradeDate}</td>
                <td style={tradesTdStyle}>{t.ticker}</td>
                <td style={tradesTdStyle}>{t.type}</td>
                <td style={tradesTdStyle}>{t.quantity}</td>
                <td style={tradesTdStyle}>{t.price.toFixed(2)}</td>
                <td style={tradesTdStyle}>{t.pnlRealized == null ? '—' : t.pnlRealized.toFixed(2)}</td>
                <td style={tradesTdStyle}>{t.ruleName}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Metric(props: { label: string; value: string }) {
  return (
    <div style={metricCellStyle}>
      <div style={metricLabelStyle}>{props.label}</div>
      <div style={metricValueStyle}>{props.value}</div>
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

const runRowStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  flexWrap: 'wrap',
}

const runLabelStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#555',
  fontWeight: 600,
}

const runListStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 2,
  border: '1px solid #eee',
  borderRadius: 4,
}

const runListItemStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  padding: '6px 10px',
  fontSize: 12,
  cursor: 'pointer',
  borderBottom: '1px solid #f5f5f5',
  gap: 8,
}

const runListItemActiveStyle: React.CSSProperties = {
  ...runListItemStyle,
  background: '#eaf2ff',
  fontWeight: 600,
}

const runListNameStyle: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
}

const runListMetricsStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#666',
  fontFamily: 'Consolas, Menlo, monospace',
}

const resultCardStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 8,
  padding: 10,
  border: '1px solid #cdd9f0',
  borderRadius: 6,
  background: '#f7faff',
}

const resultHeaderStyle: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
}

const metricsGridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
  gap: 8,
}

const metricCellStyle: React.CSSProperties = {
  background: '#fff',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  padding: '6px 10px',
}

const metricLabelStyle: React.CSSProperties = {
  fontSize: 11,
  color: '#888',
}

const metricValueStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 600,
  fontFamily: 'Consolas, Menlo, monospace',
}

const tradesSectionTitleStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#555',
  marginTop: 4,
}

const tradesTableWrapperStyle: React.CSSProperties = {
  maxHeight: 320,
  overflowY: 'auto',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  background: '#fff',
}

const tradesTableStyle: React.CSSProperties = {
  width: '100%',
  borderCollapse: 'collapse',
  fontSize: 12,
  fontFamily: 'Consolas, Menlo, monospace',
}

const tradesThStyle: React.CSSProperties = {
  textAlign: 'left',
  padding: '4px 8px',
  background: '#f5f5f5',
  borderBottom: '1px solid #e0e0e0',
  position: 'sticky',
  top: 0,
}

const tradesTdStyle: React.CSSProperties = {
  padding: '3px 8px',
  borderBottom: '1px solid #f0f0f0',
  whiteSpace: 'nowrap',
}

const progressWrapStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  padding: '6px 0',
}

const progressBarOuterStyle: React.CSSProperties = {
  width: '100%',
  height: 8,
  background: '#eee',
  borderRadius: 4,
  overflow: 'hidden',
}

const progressBarInnerStyle: React.CSSProperties = {
  height: '100%',
  background: '#2962FF',
  transition: 'width 0.3s',
}

const progressMetaStyle: React.CSSProperties = {
  display: 'flex',
  gap: 12,
  fontSize: 12,
  color: '#555',
  fontFamily: 'Consolas, Menlo, monospace',
}

const validationHintStyle: React.CSSProperties = {
  fontSize: 12,
  color: '#a01919',
  fontStyle: 'italic',
}

const descriptionTextareaStyle: React.CSSProperties = {
  fontSize: 13,
  padding: '6px 8px',
  border: '1px solid #ccc',
  borderRadius: 4,
  outline: 'none',
  fontFamily: 'inherit',
  resize: 'vertical',
}

const descViewStyle: React.CSSProperties = {
  padding: '6px 10px',
  fontSize: 13,
  background: '#fafafa',
  border: '1px dashed #ccc',
  borderRadius: 4,
  cursor: 'pointer',
  whiteSpace: 'pre-wrap',
  minHeight: 24,
}

const descEditWrapStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 6,
}

const cardSubsectionStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  padding: 8,
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  background: '#fff',
}

const cardSubtitleStyle: React.CSSProperties = {
  fontSize: 12,
  fontWeight: 600,
  color: '#555',
}

const logSectionStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  marginTop: 4,
}

const logHeaderStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
}

const logBodyStyle: React.CSSProperties = {
  fontFamily: 'Consolas, Menlo, monospace',
  fontSize: 11,
  color: '#333',
  background: '#fafafa',
  border: '1px solid #e0e0e0',
  borderRadius: 4,
  margin: 0,
  padding: 8,
  maxHeight: 220,
  overflowY: 'auto',
  whiteSpace: 'pre',
}
