import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  createEnvironment,
  createRule,
  createStrategy,
  deleteEnvironment,
  deleteRule,
  deleteStrategy,
  listEnvironments,
  listRules,
  listStrategies,
  renameEnvironment,
  renameRule,
  renameStrategy,
  updateEnvironmentDescription,
  updateRuleDescription,
  updateStrategyDescription,
} from '../api/client'
import type { ActionType, Environment, Rule, Strategy } from '../api/types'
import { useRequiredResearchId } from '../contexts/ActiveResearch'
import { SearchablePicker } from './SearchablePicker'
import { SqlEditor } from './SqlEditor'

type Tab = 'strategies' | 'rules' | 'environments'

const TAB_LABELS: Record<Tab, string> = {
  strategies: 'Стратегии',
  rules: 'Правила',
  environments: 'Окружения',
}

export function EntityEditorWidget() {
  const [tab, setTab] = useState<Tab>('strategies')
  return (
    <div style={rootStyle}>
      <div style={tabsStyle}>
        {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            style={t === tab ? tabActiveStyle : tabInactiveStyle}
          >
            {TAB_LABELS[t]}
          </button>
        ))}
      </div>
      {tab === 'strategies' && <StrategiesTab />}
      {tab === 'rules' && <RulesTab />}
      {tab === 'environments' && <EnvironmentsTab />}
    </div>
  )
}

// ── Универсальный layout с левой панелью и детальной справа ────────────────

interface ListLayoutProps<T> {
  items: T[]
  selectedId: string | 'new' | null
  onSelect: (id: string | 'new' | null) => void
  getKey: (x: T) => string
  getLabel: (x: T) => string
  newButtonLabel: string
  detail: React.ReactNode
}

function ListLayout<T>(props: ListLayoutProps<T>) {
  return (
    <div style={layoutStyle}>
      <div style={leftPanelStyle}>
        <button
          style={newButtonStyle}
          onClick={() => props.onSelect('new')}
          disabled={props.selectedId === 'new'}
        >
          {props.newButtonLabel}
        </button>
        <div style={listStyle}>
          {props.items.length === 0 ? (
            <div style={emptyHintStyle}>Пока нет записей</div>
          ) : (
            props.items.map((it) => {
              const id = props.getKey(it)
              return (
                <div
                  key={id}
                  onClick={() => props.onSelect(id)}
                  style={id === props.selectedId ? listItemActiveStyle : listItemStyle}
                >
                  {props.getLabel(it)}
                </div>
              )
            })
          )}
        </div>
      </div>
      <div style={rightPanelStyle}>
        {props.detail}
      </div>
    </div>
  )
}

// ── Универсальный заголовок detail-панели с rename + delete иконками ──────

interface EntityHeaderProps {
  name: string
  metaLine?: string
  onRename: (next: string) => Promise<void>
  onDelete: () => void
}

function EntityHeader(props: EntityHeaderProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(props.name)
  useEffect(() => { setDraft(props.name); setEditing(false) }, [props.name])
  const submit = async () => {
    const next = draft.trim()
    if (next && next !== props.name) {
      try { await props.onRename(next) } catch { /* error выводится в текущей карточке */ }
    }
    setEditing(false)
  }
  return (
    <div style={detailHeaderStyle}>
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') void submit()
            if (e.key === 'Escape') { setDraft(props.name); setEditing(false) }
          }}
          onBlur={submit}
          style={nameInputStyle}
        />
      ) : (
        <h3 style={detailTitleStyle}>{props.name}</h3>
      )}
      <div style={detailActionsStyle}>
        <IconButton title="Переименовать" onClick={() => setEditing(true)}>
          <PencilIcon />
        </IconButton>
        <IconButton title="Удалить" onClick={props.onDelete} hoverColor="#a01919">
          <TrashIcon />
        </IconButton>
      </div>
    </div>
  )
}

// ── Универсальный редактор описания ────────────────────────────────────────

interface DescriptionEditorProps {
  value: string | null | undefined
  onSave: (text: string) => Promise<unknown>
  placeholder?: string
}

function DescriptionEditor(props: DescriptionEditorProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(props.value ?? '')
  const [saving, setSaving] = useState(false)
  useEffect(() => { setDraft(props.value ?? ''); setEditing(false) }, [props.value])
  const onSave = async () => {
    setSaving(true)
    try { await props.onSave(draft); setEditing(false) }
    finally { setSaving(false) }
  }
  if (!editing) {
    return (
      <div style={descViewStyle} onClick={() => setEditing(true)} title="Кликни, чтобы изменить">
        {(props.value && props.value.trim())
          ? props.value
          : <span style={mutedStyle}>{props.placeholder ?? 'Кликни, чтобы добавить описание'}</span>}
      </div>
    )
  }
  return (
    <div style={descEditWrapStyle}>
      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={3}
        autoFocus
        style={textareaStyle}
        placeholder={props.placeholder}
      />
      <div style={formActionsStyle}>
        <button style={primaryButtonStyle} disabled={saving} onClick={onSave}>
          {saving ? 'Сохранение…' : 'Сохранить'}
        </button>
        <button style={secondaryButtonStyle} disabled={saving}
          onClick={() => { setDraft(props.value ?? ''); setEditing(false) }}>
          Отмена
        </button>
      </div>
    </div>
  )
}

// ── Strategies tab ────────────────────────────────────────────────────────

function StrategiesTab() {
  const researchId = useRequiredResearchId()
  const [items, setItems] = useState<Strategy[]>([])
  const [rules, setRules] = useState<Rule[]>([])
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        listStrategies(researchId, true),
        listRules(researchId, true),
      ])
      setItems(s); setRules(r)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [researchId])
  useEffect(() => { void refresh() }, [refresh])

  const ruleById = useMemo(() => {
    const m = new Map<string, Rule>()
    for (const r of rules) m.set(r.id, r)
    return m
  }, [rules])

  const current = selected && selected !== 'new'
    ? items.find((x) => x.id === selected) ?? null
    : null

  return (
    <ListLayout<Strategy>
      items={items}
      selectedId={selected}
      onSelect={(id) => { setError(null); setSelected(id) }}
      getKey={(x) => x.id}
      getLabel={(x) => x.name}
      newButtonLabel="+ Новая стратегия"
      detail={
        <div style={detailWrapStyle}>
          {error && <div style={errorBannerStyle}>{error}</div>}
          {selected === 'new' && (
            <NewStrategyForm
              rules={rules}
              ruleById={ruleById}
              onCancel={() => setSelected(null)}
              onCreated={async (id) => { await refresh(); setSelected(id) }}
              onError={setError}
            />
          )}
          {current && (
            <ExistingStrategyView
              strategy={current}
              ruleById={ruleById}
              onChanged={refresh}
              onDeleted={() => { setSelected(null); void refresh() }}
              onError={setError}
            />
          )}
          {!selected && (
            <div style={emptyHintStyle}>Выберите стратегию слева или создайте новую</div>
          )}
        </div>
      }
    />
  )
}

function NewStrategyForm(props: {
  rules: Rule[]
  ruleById: Map<string, Rule>
  onCancel: () => void
  onCreated: (id: string) => void | Promise<void>
  onError: (msg: string) => void
}) {
  const researchId = useRequiredResearchId()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [ruleIds, setRuleIds] = useState<string[]>([])
  const [saving, setSaving] = useState(false)

  const importable = props.rules.filter((r) => !ruleIds.includes(r.id))
  const move = (id: string, delta: -1 | 1) => {
    setRuleIds((prev) => {
      const idx = prev.indexOf(id); if (idx < 0) return prev
      const t = idx + delta; if (t < 0 || t >= prev.length) return prev
      const next = [...prev]; [next[idx], next[t]] = [next[t], next[idx]]; return next
    })
  }
  const remove = (id: string) => setRuleIds((prev) => prev.filter((x) => x !== id))

  const onSubmit = async () => {
    if (!name.trim()) { props.onError('Имя не может быть пустым'); return }
    setSaving(true)
    try {
      const created = await createStrategy({
        name: name.trim(), ruleIds, description: description.trim() || null,
        researchId,
      })
      await props.onCreated(created.id)
    } catch (e) {
      props.onError(e instanceof Error ? e.message : String(e))
    } finally { setSaving(false) }
  }

  return (
    <div style={formStyle}>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Имя стратегии"
        style={nameInputStyle}
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Описание (опционально)"
        rows={2}
        style={textareaStyle}
      />
      <div style={fieldLabelStyle}>Правила в порядке исполнения</div>
      <div style={ruleListStyle}>
        {ruleIds.length === 0 && <div style={emptyHintStyle}>Добавьте правила из существующих</div>}
        {ruleIds.map((id, i) => {
          const r = props.ruleById.get(id)
          if (!r) return null
          return (
            <div key={id} style={ruleListItemStyle}>
              <span>{i + 1}. {r.name} <span style={mutedStyle}>{r.actionType}, p={r.priority}</span></span>
              <span style={iconRowStyle}>
                <IconButton title="Выше" disabled={i === 0} onClick={() => move(id, -1)}>↑</IconButton>
                <IconButton title="Ниже" disabled={i === ruleIds.length - 1} onClick={() => move(id, +1)}>↓</IconButton>
                <IconButton title="Убрать" onClick={() => remove(id)}>×</IconButton>
              </span>
            </div>
          )
        })}
      </div>
      {importable.length > 0 ? (
        <div style={iconRowStyle}>
          <span style={mutedStyle}>Добавить правило из общих:</span>
          <SearchablePicker<Rule>
            items={importable}
            getKey={(r) => r.id}
            getName={(r) => r.name}
            renderMeta={(r) => `${r.actionType}, p=${r.priority}`}
            onPick={(r) => setRuleIds((prev) => [...prev, r.id])}
            title="Добавить правило"
          />
        </div>
      ) : (
        <div style={mutedStyle}>Все имеющиеся правила уже добавлены</div>
      )}
      <div style={formActionsStyle}>
        <button style={primaryButtonStyle} disabled={saving} onClick={onSubmit}>
          {saving ? 'Сохранение…' : 'Создать'}
        </button>
        <button style={secondaryButtonStyle} disabled={saving} onClick={props.onCancel}>
          Отмена
        </button>
      </div>
    </div>
  )
}

function ExistingStrategyView(props: {
  strategy: Strategy
  ruleById: Map<string, Rule>
  onChanged: () => void | Promise<void>
  onDeleted: () => void
  onError: (msg: string) => void
}) {
  const onDelete = async () => {
    if (!confirm('Удалить стратегию? Прогоны и сделки этой стратегии тоже удалятся.')) return
    try { await deleteStrategy(props.strategy.id); props.onDeleted() }
    catch (e) { props.onError(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div style={formStyle}>
      <EntityHeader
        name={props.strategy.name}
        onRename={async (next) => { await renameStrategy(props.strategy.id, next); await props.onChanged() }}
        onDelete={onDelete}
      />
      <div style={mutedStyle}>Создана: {props.strategy.createdAt}</div>
      <DescriptionEditor
        value={props.strategy.description}
        placeholder="Описание стратегии"
        onSave={async (text) => { await updateStrategyDescription(props.strategy.id, text); await props.onChanged() }}
      />
      <div style={fieldLabelStyle}>Правила (иммутабельный набор)</div>
      <div style={ruleListStyle}>
        {props.strategy.ruleIds.map((rid, i) => {
          const r = props.ruleById.get(rid)
          if (!r) return <div key={rid} style={missingItemStyle}>{i + 1}. (правило {rid} удалено)</div>
          return (
            <details key={rid} style={ruleListAccordionStyle}>
              <summary style={ruleListSummaryStyle}>
                {i + 1}. {r.name} <span style={mutedStyle}>{r.actionType}, p={r.priority}</span>
              </summary>
              <div style={accordionBodyStyle}>
                <div style={fieldLabelStyle}>Trigger SQL</div>
                <SqlEditor value={r.triggerSql} onChange={() => {}} readOnly minHeight={80} />
                <div style={fieldLabelStyle}>Action quantity SQL</div>
                <SqlEditor value={r.actionQuantitySql} onChange={() => {}} readOnly minHeight={60} />
              </div>
            </details>
          )
        })}
      </div>
    </div>
  )
}

// ── Rules tab ────────────────────────────────────────────────────────────

function RulesTab() {
  const researchId = useRequiredResearchId()
  const [items, setItems] = useState<Rule[]>([])
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try { setItems(await listRules(researchId, true)) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [researchId])
  useEffect(() => { void refresh() }, [refresh])

  const current = selected && selected !== 'new'
    ? items.find((x) => x.id === selected) ?? null
    : null

  return (
    <ListLayout<Rule>
      items={items}
      selectedId={selected}
      onSelect={(id) => { setError(null); setSelected(id) }}
      getKey={(x) => x.id}
      getLabel={(x) => x.name}
      newButtonLabel="+ Новое правило"
      detail={
        <div style={detailWrapStyle}>
          {error && <div style={errorBannerStyle}>{error}</div>}
          {selected === 'new' && (
            <NewRuleForm
              onCancel={() => setSelected(null)}
              onCreated={async (id) => { await refresh(); setSelected(id) }}
              onError={setError}
            />
          )}
          {current && (
            <ExistingRuleView
              rule={current}
              onChanged={refresh}
              onDeleted={() => { setSelected(null); void refresh() }}
              onError={setError}
            />
          )}
          {!selected && (
            <div style={emptyHintStyle}>Выберите правило слева или создайте новое</div>
          )}
        </div>
      }
    />
  )
}

function NewRuleForm(props: {
  onCancel: () => void
  onCreated: (id: string) => void | Promise<void>
  onError: (msg: string) => void
}) {
  const researchId = useRequiredResearchId()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [actionType, setActionType] = useState<ActionType>('buy')
  const [priority, setPriority] = useState('100')
  const [triggerSql, setTriggerSql] = useState('')
  const [quantitySql, setQuantitySql] = useState('')
  const [saving, setSaving] = useState(false)

  const onSubmit = async () => {
    if (!name.trim()) { props.onError('Имя не может быть пустым'); return }
    if (!triggerSql.trim()) { props.onError('Trigger SQL не может быть пустым'); return }
    if (!quantitySql.trim()) { props.onError('Action quantity SQL не может быть пустым'); return }
    const p = parseInt(priority, 10)
    if (!Number.isFinite(p)) { props.onError('Priority должен быть целым числом'); return }
    setSaving(true)
    try {
      const created = await createRule({
        name: name.trim(),
        triggerSql, actionType, actionQuantitySql: quantitySql,
        priority: p,
        description: description.trim() || null,
        researchId,
      })
      await props.onCreated(created.id)
    } catch (e) {
      props.onError(e instanceof Error ? e.message : String(e))
    } finally { setSaving(false) }
  }

  return (
    <div style={formStyle}>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Имя правила"
        style={nameInputStyle}
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Описание (опционально)"
        rows={2}
        style={textareaStyle}
      />
      <div style={fieldRowStyle}>
        <label style={fieldLabelStyle}>
          Тип действия
          <select value={actionType} onChange={(e) => setActionType(e.target.value as ActionType)} style={inputStyle}>
            <option value="buy">buy</option>
            <option value="sell">sell</option>
          </select>
        </label>
        <label style={fieldLabelStyle}>
          Priority
          <input type="number" value={priority} onChange={(e) => setPriority(e.target.value)} style={inputStyle} />
        </label>
      </div>
      <label style={fieldLabelStyle}>Trigger SQL</label>
      <SqlEditor value={triggerSql} onChange={setTriggerSql} minHeight={100} />
      <label style={fieldLabelStyle}>Action quantity SQL</label>
      <SqlEditor value={quantitySql} onChange={setQuantitySql} minHeight={70} />
      <div style={formActionsStyle}>
        <button style={primaryButtonStyle} disabled={saving} onClick={onSubmit}>
          {saving ? 'Сохранение…' : 'Создать'}
        </button>
        <button style={secondaryButtonStyle} disabled={saving} onClick={props.onCancel}>
          Отмена
        </button>
      </div>
    </div>
  )
}

function ExistingRuleView(props: {
  rule: Rule
  onChanged: () => void | Promise<void>
  onDeleted: () => void
  onError: (msg: string) => void
}) {
  const onDelete = async () => {
    if (!confirm('Удалить правило? Стратегии, которые его используют, удалить не получится.')) return
    try { await deleteRule(props.rule.id); props.onDeleted() }
    catch (e) { props.onError(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div style={formStyle}>
      <EntityHeader
        name={props.rule.name}
        onRename={async (next) => { await renameRule(props.rule.id, next); await props.onChanged() }}
        onDelete={onDelete}
      />
      <div style={mutedStyle}>Создано: {props.rule.createdAt}</div>
      <DescriptionEditor
        value={props.rule.description}
        placeholder="Описание правила"
        onSave={async (text) => { await updateRuleDescription(props.rule.id, text); await props.onChanged() }}
      />
      <div style={fieldRowStyle}>
        <div style={readonlyFieldStyle}><span style={fieldLabelStyle}>Тип действия</span><span>{props.rule.actionType}</span></div>
        <div style={readonlyFieldStyle}><span style={fieldLabelStyle}>Priority</span><span>{props.rule.priority}</span></div>
      </div>
      <div style={fieldLabelStyle}>Trigger SQL</div>
      <SqlEditor value={props.rule.triggerSql} onChange={() => {}} readOnly minHeight={100} />
      <div style={fieldLabelStyle}>Action quantity SQL</div>
      <SqlEditor value={props.rule.actionQuantitySql} onChange={() => {}} readOnly minHeight={70} />
    </div>
  )
}

// ── Environments tab ────────────────────────────────────────────────────

function EnvironmentsTab() {
  const researchId = useRequiredResearchId()
  const [items, setItems] = useState<Environment[]>([])
  const [selected, setSelected] = useState<string | 'new' | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try { setItems(await listEnvironments(researchId, true)) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }, [researchId])
  useEffect(() => { void refresh() }, [refresh])

  const current = selected && selected !== 'new'
    ? items.find((x) => x.id === selected) ?? null
    : null

  return (
    <ListLayout<Environment>
      items={items}
      selectedId={selected}
      onSelect={(id) => { setError(null); setSelected(id) }}
      getKey={(x) => x.id}
      getLabel={(x) => x.name}
      newButtonLabel="+ Новое окружение"
      detail={
        <div style={detailWrapStyle}>
          {error && <div style={errorBannerStyle}>{error}</div>}
          {selected === 'new' && (
            <NewEnvironmentForm
              onCancel={() => setSelected(null)}
              onCreated={async (id) => { await refresh(); setSelected(id) }}
              onError={setError}
            />
          )}
          {current && (
            <ExistingEnvironmentView
              environment={current}
              onChanged={refresh}
              onDeleted={() => { setSelected(null); void refresh() }}
              onError={setError}
            />
          )}
          {!selected && (
            <div style={emptyHintStyle}>Выберите окружение слева или создайте новое</div>
          )}
        </div>
      }
    />
  )
}

function NewEnvironmentForm(props: {
  onCancel: () => void
  onCreated: (id: string) => void | Promise<void>
  onError: (msg: string) => void
}) {
  const researchId = useRequiredResearchId()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [dateStart, setDateStart] = useState('2020-01-01')
  const [dateEnd, setDateEnd] = useState('2025-12-31')
  const [capital, setCapital] = useState('1000000')
  const [saving, setSaving] = useState(false)

  const onSubmit = async () => {
    if (!name.trim()) { props.onError('Имя не может быть пустым'); return }
    const cap = parseFloat(capital)
    if (!Number.isFinite(cap) || cap <= 0) { props.onError('startingCapital должен быть положительным'); return }
    setSaving(true)
    try {
      const created = await createEnvironment({
        name: name.trim(), dateStart, dateEnd, startingCapital: cap,
        description: description.trim() || null,
        researchId,
      })
      await props.onCreated(created.id)
    } catch (e) { props.onError(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }

  return (
    <div style={formStyle}>
      <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Имя окружения" style={nameInputStyle} />
      <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Описание (опционально)" rows={2} style={textareaStyle} />
      <div style={fieldRowStyle}>
        <label style={fieldLabelStyle}>
          dateStart
          <input type="date" value={dateStart} onChange={(e) => setDateStart(e.target.value)} style={inputStyle} />
        </label>
        <label style={fieldLabelStyle}>
          dateEnd
          <input type="date" value={dateEnd} onChange={(e) => setDateEnd(e.target.value)} style={inputStyle} />
        </label>
        <label style={fieldLabelStyle}>
          startingCapital
          <input type="number" value={capital} onChange={(e) => setCapital(e.target.value)} style={inputStyle} />
        </label>
      </div>
      <div style={formActionsStyle}>
        <button style={primaryButtonStyle} disabled={saving} onClick={onSubmit}>
          {saving ? 'Сохранение…' : 'Создать'}
        </button>
        <button style={secondaryButtonStyle} disabled={saving} onClick={props.onCancel}>Отмена</button>
      </div>
    </div>
  )
}

function ExistingEnvironmentView(props: {
  environment: Environment
  onChanged: () => void | Promise<void>
  onDeleted: () => void
  onError: (msg: string) => void
}) {
  const onDelete = async () => {
    if (!confirm('Удалить окружение? Прогоны на его основе уже сохранены и не пострадают.')) return
    try { await deleteEnvironment(props.environment.id); props.onDeleted() }
    catch (e) { props.onError(e instanceof Error ? e.message : String(e)) }
  }
  return (
    <div style={formStyle}>
      <EntityHeader
        name={props.environment.name}
        onRename={async (next) => { await renameEnvironment(props.environment.id, next); await props.onChanged() }}
        onDelete={onDelete}
      />
      <div style={mutedStyle}>Создано: {props.environment.createdAt}</div>
      <DescriptionEditor
        value={props.environment.description}
        placeholder="Описание окружения"
        onSave={async (text) => { await updateEnvironmentDescription(props.environment.id, text); await props.onChanged() }}
      />
      <div style={fieldRowStyle}>
        <div style={readonlyFieldStyle}><span style={fieldLabelStyle}>dateStart</span><span>{props.environment.dateStart}</span></div>
        <div style={readonlyFieldStyle}><span style={fieldLabelStyle}>dateEnd</span><span>{props.environment.dateEnd}</span></div>
        <div style={readonlyFieldStyle}><span style={fieldLabelStyle}>startingCapital</span><span>{props.environment.startingCapital.toLocaleString('ru-RU')}</span></div>
      </div>
    </div>
  )
}

// ── IconButton + иконки ───────────────────────────────────────────────────

function IconButton(props: {
  children: React.ReactNode
  onClick?: () => void
  title?: string
  disabled?: boolean
  hoverColor?: string
}) {
  const [hover, setHover] = useState(false)
  const style: React.CSSProperties = {
    width: 26, height: 26, padding: 0,
    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    background: hover && !props.disabled ? '#f5f5f5' : 'transparent',
    border: '1px solid #ddd', borderRadius: 4,
    color: props.disabled ? '#bbb' : (hover && props.hoverColor ? props.hoverColor : '#555'),
    cursor: props.disabled ? 'default' : 'pointer',
    fontSize: 13, lineHeight: 1,
  }
  return (
    <button
      title={props.title}
      disabled={props.disabled}
      onClick={props.onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={style}
    >
      {props.children}
    </button>
  )
}

function PencilIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" />
    </svg>
  )
}

function TrashIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
      <path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2" />
    </svg>
  )
}

// ── Стили ────────────────────────────────────────────────────────────────

const rootStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, padding: 8, gap: 8 }
const tabsStyle: React.CSSProperties = { display: 'flex', gap: 4, borderBottom: '1px solid #eee', flexShrink: 0 }
const tabBaseStyle: React.CSSProperties = {
  padding: '6px 14px', fontSize: 13, background: 'transparent',
  border: 'none', borderBottom: '2px solid transparent', cursor: 'pointer',
  color: '#666',
}
const tabActiveStyle: React.CSSProperties = { ...tabBaseStyle, color: '#2962FF', borderBottomColor: '#2962FF', fontWeight: 600 }
const tabInactiveStyle: React.CSSProperties = { ...tabBaseStyle }

const layoutStyle: React.CSSProperties = { display: 'flex', flex: 1, minHeight: 0, gap: 8 }
const leftPanelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', width: 240, flexShrink: 0, gap: 8, borderRight: '1px solid #eee', paddingRight: 8 }
const rightPanelStyle: React.CSSProperties = { flex: 1, minWidth: 0, overflow: 'auto' }
const detailWrapStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 8, padding: 8 }

const newButtonStyle: React.CSSProperties = { padding: '6px 10px', fontSize: 13, background: '#2962FF', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }
const listStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', overflow: 'auto', flex: 1 }
const listItemStyle: React.CSSProperties = { padding: '6px 10px', fontSize: 13, cursor: 'pointer', borderBottom: '1px solid #f5f5f5' }
const listItemActiveStyle: React.CSSProperties = { ...listItemStyle, background: '#eaf2ff', fontWeight: 600 }
const emptyHintStyle: React.CSSProperties = { padding: 12, fontSize: 12, color: '#999', fontStyle: 'italic', textAlign: 'center' }
const mutedStyle: React.CSSProperties = { fontSize: 12, color: '#888' }
const errorBannerStyle: React.CSSProperties = { padding: '8px 12px', background: '#fdecea', border: '1px solid #f5a8a3', borderRadius: 4, color: '#a01919', fontSize: 12 }

const detailHeaderStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }
const detailTitleStyle: React.CSSProperties = { margin: 0, fontSize: 16, fontWeight: 600 }
const detailActionsStyle: React.CSSProperties = { display: 'flex', gap: 4 }

const formStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 10 }
const nameInputStyle: React.CSSProperties = { fontSize: 16, fontWeight: 600, padding: '6px 10px', border: '1px solid #ccc', borderRadius: 4, outline: 'none' }
const inputStyle: React.CSSProperties = { fontSize: 13, padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, outline: 'none', fontFamily: 'inherit' }
const textareaStyle: React.CSSProperties = { fontSize: 13, padding: '6px 8px', border: '1px solid #ccc', borderRadius: 4, outline: 'none', fontFamily: 'inherit', resize: 'vertical' }
const fieldLabelStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, fontSize: 12, color: '#555', fontWeight: 600 }
const fieldRowStyle: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }
const readonlyFieldStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 2, fontSize: 13 }

const ruleListStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4 }
const ruleListItemStyle: React.CSSProperties = { padding: '6px 10px', fontSize: 13, border: '1px solid #eee', borderRadius: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }
const ruleListAccordionStyle: React.CSSProperties = { border: '1px solid #eee', borderRadius: 4, padding: 4 }
const ruleListSummaryStyle: React.CSSProperties = { fontSize: 13, cursor: 'pointer', padding: '4px 6px' }
const accordionBodyStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6, paddingTop: 6 }
const missingItemStyle: React.CSSProperties = { padding: '6px 10px', fontSize: 12, color: '#a01919', fontStyle: 'italic', border: '1px solid #f5a8a3', borderRadius: 4 }

const iconRowStyle: React.CSSProperties = { display: 'flex', gap: 4, alignItems: 'center' }
const formActionsStyle: React.CSSProperties = { display: 'flex', gap: 8 }
const primaryButtonStyle: React.CSSProperties = { padding: '6px 14px', fontSize: 13, background: '#2962FF', color: '#fff', border: 'none', borderRadius: 4, cursor: 'pointer' }
const secondaryButtonStyle: React.CSSProperties = { padding: '6px 12px', fontSize: 13, background: '#fff', color: '#333', border: '1px solid #ccc', borderRadius: 4, cursor: 'pointer' }

const descViewStyle: React.CSSProperties = { padding: '6px 10px', fontSize: 13, background: '#fafafa', border: '1px dashed #ccc', borderRadius: 4, cursor: 'pointer', whiteSpace: 'pre-wrap', minHeight: 24 }
const descEditWrapStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6 }
