import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  cancelBacktestRun,
  deleteBacktestResult,
  getBacktestResult,
  getBacktestRunLog,
  getBacktestRunProgress,
  listBacktestResults,
  listEnvironments,
  listStrategies,
  startBacktestRun,
} from '../api/client'
import type {
  BacktestResultDetail,
  BacktestResultMeta,
  BacktestRunProgress,
  Environment,
  Strategy,
} from '../api/types'
import { EquityCurveChart } from './EquityCurveChart'
import { SearchablePicker } from './SearchablePicker'

type Tab = 'launch' | 'archive'

const TAB_LABELS: Record<Tab, string> = {
  launch: 'Запуск',
  archive: 'Архив',
}

export function BacktestEditorWidget() {
  const [tab, setTab] = useState<Tab>('launch')
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
      {tab === 'launch' && <LaunchTab />}
      {tab === 'archive' && <ArchiveTab />}
    </div>
  )
}

// ── Вкладка «Запуск» ─────────────────────────────────────────────────────

function LaunchTab() {
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<Strategy | null>(null)
  const [selectedEnv, setSelectedEnv] = useState<Environment | null>(null)
  const [activeRun, setActiveRun] = useState<BacktestRunProgress | null>(null)
  const [runError, setRunError] = useState<string | null>(null)
  const [resultDetail, setResultDetail] = useState<BacktestResultDetail | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const [s, e] = await Promise.all([listStrategies(), listEnvironments()])
        setStrategies(s); setEnvironments(e)
      } catch (err) {
        setRunError(err instanceof Error ? err.message : String(err))
      }
    })()
  }, [])

  const running = activeRun?.status === 'running'

  const onRun = async () => {
    if (!selectedStrategy || !selectedEnv) return
    setRunError(null)
    setResultDetail(null)
    try {
      const started = await startBacktestRun({
        strategyId: selectedStrategy.id,
        environmentId: selectedEnv.id,
      })
      setActiveRun({
        runId: started.runId,
        strategyId: selectedStrategy.id,
        environmentId: selectedEnv.id,
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

  const onCancel = async () => {
    if (!activeRun) return
    try { await cancelBacktestRun(activeRun.runId) }
    catch (e) { setRunError(e instanceof Error ? e.message : String(e)) }
  }

  // Polling прогресса; зависим только от runId, чтобы setActiveRun внутри
  // tick'а не cleanup'ил interval.
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
          stopped = true; clearInterval(handle)
          const detail = await getBacktestResult(p.resultId)
          setResultDetail(detail)
        } else if (p.status === 'error') {
          stopped = true; clearInterval(handle)
          setRunError(p.errorMessage ?? 'Ошибка прогона')
        } else if (p.status === 'cancelled') {
          stopped = true; clearInterval(handle)
        }
      } catch (e) {
        setRunError(e instanceof Error ? e.message : String(e))
      }
    }
    const handle = setInterval(() => { void tick() }, 1000)
    void tick()
    return () => { stopped = true; clearInterval(handle) }
  }, [runId])

  return (
    <div style={tabBodyStyle}>
      <Section title="Запуск прогона">
        <div style={launchRowStyle}>
          <SelectorRow
            label="Стратегия"
            current={selectedStrategy?.name ?? null}
            picker={
              <SearchablePicker<Strategy>
                items={strategies}
                getKey={(s) => s.id}
                getName={(s) => s.name}
                renderMeta={(s) => `${s.ruleIds.length} правил`}
                onPick={(s) => setSelectedStrategy(s)}
                title="Выбрать стратегию"
                emptyText="Стратегий пока нет — создайте в EntityEditor"
              />
            }
          />
          <SelectorRow
            label="Окружение"
            current={selectedEnv ? `${selectedEnv.name} (${selectedEnv.dateStart}…${selectedEnv.dateEnd})` : null}
            picker={
              <SearchablePicker<Environment>
                items={environments}
                getKey={(e) => e.id}
                getName={(e) => e.name}
                renderMeta={(e) => `${e.dateStart}…${e.dateEnd}`}
                onPick={(e) => setSelectedEnv(e)}
                title="Выбрать окружение"
                emptyText="Окружений нет — создайте в EntityEditor"
              />
            }
          />
          <div style={runActionRowStyle}>
            <RunButton
              disabled={running || !selectedStrategy || !selectedEnv}
              title={
                running ? 'Прогон идёт' :
                !selectedStrategy ? 'Выберите стратегию' :
                !selectedEnv ? 'Выберите окружение' : 'Запустить прогон'
              }
              onClick={onRun}
            />
            {running && <CancelButton onClick={onCancel} title="Отменить" />}
          </div>
        </div>
        {runError && <div style={errorBannerStyle}>{runError}</div>}
        {activeRun && activeRun.status === 'running' && (
          <RunProgressView progress={activeRun} />
        )}
        {activeRun && activeRun.status === 'cancelled' && (
          <div style={mutedStyle}>Прогон отменён</div>
        )}
      </Section>

      {resultDetail && (
        <Section title="Результат прогона">
          <ResultCard result={resultDetail} />
        </Section>
      )}
    </div>
  )
}

function SelectorRow(props: { label: string; current: string | null; picker: React.ReactNode }) {
  return (
    <div style={selectorRowStyle}>
      <span style={selectorLabelStyle}>{props.label}:</span>
      <span style={selectorValueStyle}>
        {props.current ?? <span style={mutedStyle}>не выбрано</span>}
      </span>
      {props.picker}
    </div>
  )
}

// ── Вкладка «Архив» ──────────────────────────────────────────────────────

function ArchiveTab() {
  const [results, setResults] = useState<BacktestResultMeta[]>([])
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [environments, setEnvironments] = useState<Environment[]>([])
  const [selectedDetail, setSelectedDetail] = useState<BacktestResultDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [r, s, e] = await Promise.all([
        listBacktestResults(), listStrategies(), listEnvironments(),
      ])
      setResults(r); setStrategies(s); setEnvironments(e)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const strategyById = useMemo(() => {
    const m = new Map<string, Strategy>()
    for (const s of strategies) m.set(s.id, s)
    return m
  }, [strategies])
  const envById = useMemo(() => {
    const m = new Map<string, Environment>()
    for (const e of environments) m.set(e.id, e)
    return m
  }, [environments])

  const onOpen = async (id: string) => {
    setLoadingDetail(true)
    try {
      setSelectedDetail(await getBacktestResult(id))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoadingDetail(false)
    }
  }

  const onDelete = async (id: string) => {
    if (!confirm('Удалить прогон и его сделки?')) return
    try {
      await deleteBacktestResult(id)
      if (selectedDetail?.id === id) setSelectedDetail(null)
      await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    }
  }

  return (
    <div style={tabBodyStyle}>
      {error && <div style={errorBannerStyle}>{error}</div>}
      <Section title={`Все прогоны (${results.length})`}>
        {results.length === 0 ? (
          <div style={emptyHintStyle}>Прогонов ещё нет</div>
        ) : (
          <div style={archiveTableWrapStyle}>
            <table style={archiveTableStyle}>
              <thead>
                <tr>
                  <th style={archiveThStyle}>Стратегия</th>
                  <th style={archiveThStyle}>Окружение</th>
                  <th style={archiveThStyle}>Период</th>
                  <th style={archiveThStyleNum}>Σ доход.</th>
                  <th style={archiveThStyleNum}>Год. доход.</th>
                  <th style={archiveThStyleNum}>Просадка</th>
                  <th style={archiveThStyleNum}>Sharpe</th>
                  <th style={archiveThStyleNum}>Сделок</th>
                  <th style={archiveThStyleNum}>Profit factor</th>
                  <th style={archiveThStyleNum}>Win rate</th>
                  <th style={archiveThStyle}>Создан</th>
                  <th style={archiveThStyle}></th>
                </tr>
              </thead>
              <tbody>
                {results.map((r) => {
                  const s = strategyById.get(r.strategyId)
                  const e = envById.get(r.environmentId)
                  const isSelected = selectedDetail?.id === r.id
                  return (
                    <tr
                      key={r.id}
                      onClick={() => void onOpen(r.id)}
                      style={isSelected ? archiveTrSelectedStyle : archiveTrStyle}
                    >
                      <td style={archiveTdStyle}>{s?.name ?? '(удалена)'}</td>
                      <td style={archiveTdStyle}>{e?.name ?? '(удалено)'}</td>
                      <td style={archiveTdStyle}>{e ? `${e.dateStart}…${e.dateEnd}` : '—'}</td>
                      <td style={archiveTdStyleNum}>{r.totalReturnPct.toFixed(2)}%</td>
                      <td style={archiveTdStyleNum}>{r.annualReturnPct.toFixed(2)}%</td>
                      <td style={archiveTdStyleNum}>{r.maxDrawdownPct.toFixed(2)}%</td>
                      <td style={archiveTdStyleNum}>{r.sharpe.toFixed(2)}</td>
                      <td style={archiveTdStyleNum}>{r.nTrades}</td>
                      <td style={archiveTdStyleNum}>{r.profitFactor == null ? '—' : r.profitFactor.toFixed(2)}</td>
                      <td style={archiveTdStyleNum}>{r.winRatePct == null ? '—' : `${r.winRatePct.toFixed(1)}%`}</td>
                      <td style={archiveTdStyle}>{r.createdAt}</td>
                      <td style={archiveTdStyle}>
                        <IconButton title="Удалить" hoverColor="#a01919"
                          onClick={(ev) => { ev?.stopPropagation(); void onDelete(r.id) }}>
                          <TrashIcon />
                        </IconButton>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>
      {loadingDetail && <div style={mutedStyle}>Загрузка карточки…</div>}
      {selectedDetail && (
        <Section title="Карточка прогона">
          <ResultCard result={selectedDetail} />
        </Section>
      )}
    </div>
  )
}

// ── ResultCard (общая для Launch и Archive) ──────────────────────────────

function ResultCard(props: { result: BacktestResultDetail }) {
  const r = props.result
  const fmtPct = (v: number) => `${v.toFixed(2)}%`
  const fmtNum = (v: number | null) => v == null ? '—' : v.toFixed(2)
  return (
    <div style={resultCardStyle}>
      {(r.strategy || r.environment) && (
        <div style={contextGridStyle}>
          {r.strategy && (
            <div style={contextCellStyle}>
              <div style={contextLabelStyle}>Стратегия</div>
              <div style={contextValueStyle}>{r.strategy.name}</div>
              {r.strategy.description && <div style={mutedStyle}>{r.strategy.description}</div>}
            </div>
          )}
          {r.environment && (
            <div style={contextCellStyle}>
              <div style={contextLabelStyle}>Окружение</div>
              <div style={contextValueStyle}>{r.environment.name}</div>
              <div style={mutedStyle}>
                {r.environment.dateStart} — {r.environment.dateEnd},{' '}
                {r.environment.startingCapital.toLocaleString('ru-RU')}
              </div>
              {r.environment.description && <div style={mutedStyle}>{r.environment.description}</div>}
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
      <Section title={`Equity-кривая (${r.equityCurve.length} точек)`} initiallyOpen>
        <EquityCurveChart data={r.equityCurve} height={280} />
      </Section>
      <Section title={`Журнал сделок (${r.trades.length})`} initiallyOpen={false}>
        <div style={tradesTableWrapStyle}>
          <table style={tradesTableStyle}>
            <thead>
              <tr>
                <th style={tradesThStyle}>Дата</th>
                <th style={tradesThStyle}>Тикер</th>
                <th style={tradesThStyle}>Тип</th>
                <th style={tradesThStyleNum}>Кол-во</th>
                <th style={tradesThStyleNum}>Цена</th>
                <th style={tradesThStyleNum}>PnL</th>
                <th style={tradesThStyle}>Правило</th>
              </tr>
            </thead>
            <tbody>
              {r.trades.map((t, i) => (
                <tr key={i}>
                  <td style={tradesTdStyle}>{t.tradeDate}</td>
                  <td style={tradesTdStyle}>{t.ticker}</td>
                  <td style={tradesTdStyle}>{t.type}</td>
                  <td style={tradesTdStyleNum}>{t.quantity}</td>
                  <td style={tradesTdStyleNum}>{t.price.toFixed(2)}</td>
                  <td style={tradesTdStyleNum}>{t.pnlRealized == null ? '—' : t.pnlRealized.toFixed(2)}</td>
                  <td style={tradesTdStyle}>{t.ruleName}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
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

// ── Прогресс + лог ───────────────────────────────────────────────────────

function RunProgressView(props: { progress: BacktestRunProgress }) {
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
          setTimeout(() => {
            const el = containerRef.current
            if (el) el.scrollTop = el.scrollHeight
          }, 0)
        }
        cursorRef.current = chunk.next_byte
      } catch { /* лог-файла ещё нет — попробуем в следующий тик */ }
    }
    void tick()
    if (!props.active) return
    const handle = setInterval(() => { void tick() }, 1000)
    return () => { stopped = true; clearInterval(handle) }
  }, [props.runId, props.active])

  return (
    <div style={logSectionStyle}>
      <div style={logHeaderStyle}>
        <span style={contextLabelStyle}>Лог прогона</span>
        <IconButton title={collapsed ? 'Развернуть' : 'Свернуть'} onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? '▸' : '▾'}
        </IconButton>
      </div>
      {!collapsed && (
        <pre ref={containerRef} style={logBodyStyle}>{text || '(лог пуст)'}</pre>
      )}
    </div>
  )
}

// ── Section: сворачиваемая секция-обёртка ───────────────────────────────

function Section(props: { title: string; initiallyOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(props.initiallyOpen ?? true)
  return (
    <div style={sectionWrapStyle}>
      <div style={sectionHeaderStyle} onClick={() => setOpen(!open)}>
        <span>{open ? '▾' : '▸'} {props.title}</span>
      </div>
      {open && <div style={sectionBodyStyle}>{props.children}</div>}
    </div>
  )
}

// ── Кнопки и иконки ─────────────────────────────────────────────────────

function RunButton(props: { onClick: () => void; disabled?: boolean; title?: string }) {
  return (
    <button
      style={props.disabled ? runButtonDisabledStyle : runButtonStyle}
      disabled={props.disabled}
      onClick={props.onClick}
      title={props.title}
    >
      <PlayIcon />
    </button>
  )
}

function CancelButton(props: { onClick: () => void; title?: string }) {
  return (
    <button style={cancelButtonStyle} onClick={props.onClick} title={props.title}>
      <StopIcon />
    </button>
  )
}

function IconButton(props: {
  children: React.ReactNode
  onClick?: (ev?: React.MouseEvent) => void
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
      onClick={(e) => props.onClick?.(e)}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={style}
    >
      {props.children}
    </button>
  )
}

function PlayIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <polygon points="5,3 19,12 5,21" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      <rect x="5" y="5" width="14" height="14" rx="1" />
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

const tabBodyStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0, overflow: 'auto' }

const sectionWrapStyle: React.CSSProperties = { border: '1px solid #e0e0e0', borderRadius: 6, background: '#fafafa' }
const sectionHeaderStyle: React.CSSProperties = { padding: '8px 12px', fontSize: 13, fontWeight: 600, color: '#333', cursor: 'pointer', userSelect: 'none', borderBottom: '1px solid #eee' }
const sectionBodyStyle: React.CSSProperties = { padding: 12, background: '#fff', display: 'flex', flexDirection: 'column', gap: 10 }

const launchRowStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 8 }
const selectorRowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8 }
const selectorLabelStyle: React.CSSProperties = { fontSize: 12, color: '#555', fontWeight: 600, minWidth: 88 }
const selectorValueStyle: React.CSSProperties = { flex: 1, fontSize: 13 }
const runActionRowStyle: React.CSSProperties = { display: 'flex', gap: 8, marginTop: 4 }

const runButtonStyle: React.CSSProperties = {
  width: 36, height: 36, padding: 0,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  background: '#3FB950', color: '#fff', border: 'none', borderRadius: 4,
  cursor: 'pointer',
}
const runButtonDisabledStyle: React.CSSProperties = { ...runButtonStyle, background: '#cfd8dc', cursor: 'not-allowed' }
const cancelButtonStyle: React.CSSProperties = {
  width: 36, height: 36, padding: 0,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
  background: '#fff', color: '#a01919', border: '1px solid #f5a8a3', borderRadius: 4,
  cursor: 'pointer',
}

const errorBannerStyle: React.CSSProperties = { padding: '8px 12px', background: '#fdecea', border: '1px solid #f5a8a3', borderRadius: 4, color: '#a01919', fontSize: 12 }
const emptyHintStyle: React.CSSProperties = { padding: 12, fontSize: 12, color: '#999', fontStyle: 'italic', textAlign: 'center' }
const mutedStyle: React.CSSProperties = { fontSize: 12, color: '#888' }

const archiveTableWrapStyle: React.CSSProperties = { overflowX: 'auto', maxHeight: 360, overflowY: 'auto', border: '1px solid #e0e0e0', borderRadius: 4 }
const archiveTableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 12 }
const archiveThStyle: React.CSSProperties = { textAlign: 'left', padding: '6px 10px', background: '#f5f5f5', borderBottom: '1px solid #e0e0e0', position: 'sticky', top: 0, fontWeight: 600 }
const archiveThStyleNum: React.CSSProperties = { ...archiveThStyle, textAlign: 'right' }
const archiveTrStyle: React.CSSProperties = { cursor: 'pointer' }
const archiveTrSelectedStyle: React.CSSProperties = { ...archiveTrStyle, background: '#eaf2ff' }
const archiveTdStyle: React.CSSProperties = { padding: '4px 10px', borderBottom: '1px solid #f0f0f0', whiteSpace: 'nowrap' }
const archiveTdStyleNum: React.CSSProperties = { ...archiveTdStyle, textAlign: 'right', fontFamily: 'Consolas, Menlo, monospace' }

const resultCardStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 10 }
const contextGridStyle: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 8 }
const contextCellStyle: React.CSSProperties = { padding: '6px 10px', border: '1px solid #e0e0e0', borderRadius: 4, background: '#fff' }
const contextLabelStyle: React.CSSProperties = { fontSize: 11, color: '#888' }
const contextValueStyle: React.CSSProperties = { fontSize: 14, fontWeight: 600 }

const metricsGridStyle: React.CSSProperties = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }
const metricCellStyle: React.CSSProperties = { background: '#fff', border: '1px solid #e0e0e0', borderRadius: 4, padding: '6px 10px' }
const metricLabelStyle: React.CSSProperties = { fontSize: 11, color: '#888' }
const metricValueStyle: React.CSSProperties = { fontSize: 16, fontWeight: 600, fontFamily: 'Consolas, Menlo, monospace' }

const tradesTableWrapStyle: React.CSSProperties = { maxHeight: 320, overflowY: 'auto', border: '1px solid #e0e0e0', borderRadius: 4, background: '#fff' }
const tradesTableStyle: React.CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'Consolas, Menlo, monospace' }
const tradesThStyle: React.CSSProperties = { textAlign: 'left', padding: '4px 8px', background: '#f5f5f5', borderBottom: '1px solid #e0e0e0', position: 'sticky', top: 0 }
const tradesThStyleNum: React.CSSProperties = { ...tradesThStyle, textAlign: 'right' }
const tradesTdStyle: React.CSSProperties = { padding: '3px 8px', borderBottom: '1px solid #f0f0f0', whiteSpace: 'nowrap' }
const tradesTdStyleNum: React.CSSProperties = { ...tradesTdStyle, textAlign: 'right' }

const progressWrapStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, padding: '6px 0' }
const progressBarOuterStyle: React.CSSProperties = { width: '100%', height: 8, background: '#eee', borderRadius: 4, overflow: 'hidden' }
const progressBarInnerStyle: React.CSSProperties = { height: '100%', background: '#2962FF', transition: 'width 0.3s' }
const progressMetaStyle: React.CSSProperties = { display: 'flex', gap: 12, fontSize: 12, color: '#555', fontFamily: 'Consolas, Menlo, monospace' }

const logSectionStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }
const logHeaderStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', justifyContent: 'space-between' }
const logBodyStyle: React.CSSProperties = {
  fontFamily: 'Consolas, Menlo, monospace', fontSize: 11, color: '#333',
  background: '#fafafa', border: '1px solid #e0e0e0', borderRadius: 4,
  margin: 0, padding: 8, maxHeight: 220, overflowY: 'auto', whiteSpace: 'pre',
}
