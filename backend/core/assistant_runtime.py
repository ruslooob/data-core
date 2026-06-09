"""Рантайм помощника: обёртка над Claude Code CLI в headless-режиме.

Каждый запрос — это отдельный subprocess `claude --print --output-format=stream-json`,
с явным системным промптом и whitelist-инструментов (`Read` под docs/, `Bash` только
для curl на локальный backend). История диалога и приложенные документы склеиваются
в один входной prompt и подаются через stdin.

Используется OAuth-сессия пользователя (тот же логин, что и интерактивный claude).
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ALLOWED_TOOLS = [
    'Read(docs/**)',
    'Glob(docs/**)',
    'Grep(docs/**)',
    'Bash(curl http://127.0.0.1:8080/api/*)',
    'Bash(curl http://localhost:8080/api/*)',
]

DISALLOWED_TOOLS = [
    'Write',
    'Edit',
    'NotebookEdit',
    'WebFetch',
    'WebSearch',
    'Task',
]

RUN_TIMEOUT_SECONDS = 300

SYSTEM_PROMPT = """Ты — помощник аналитика в проекте Kairos: рабочее место для событийного анализа и бэктеста на российском рынке акций.

# Кто перед тобой
Финансовый аналитик. Работает в активном исследовании (Research) — именованной группе стратегий, правил, окружений и прогонов. На любую формулировку в первом лице («покажи мои стратегии», «создай правило») подразумевается активное исследование.

# Что ты умеешь
1. Читать документацию проекта — только из каталога docs/. Файлы лежат в репозитории и доступны через инструмент Read. Глоссарий — docs/GLOSSARY.md, основные спецификации — docs/SPEC_*.md.
2. Действовать через REST-API backend'а на http://127.0.0.1:8080. Используй curl. Базовые эндпоинты:
   - GET /api/research                              — список исследований
   - GET /api/strategies?researchId=X&includeCommon=true  — стратегии исследования
   - GET /api/rules?researchId=X&includeCommon=true       — правила исследования
   - GET /api/environments?researchId=X&includeCommon=true — окружения
   - POST /api/strategies, POST /api/rules, POST /api/environments — создание сущностей
   - POST /api/backtest/run (body со strategyId, environmentId, researchId) — запуск прогона
   - GET /api/backtest/runs/{runId}/progress         — прогресс прогона
   - GET /api/backtest/results/{resultId}            — финальные метрики
   - DELETE /api/backtest/results/{resultId}          — удалить прогон
   - GET /api/tickers, GET /api/candles?ticker=...   — котировки
3. Перед запуском прогона на длинное окружение — сделать smoke на коротком (см. docs/BACKTEST_RUNNER_AGENT.md, раздел 3.2).

# Чего ты не умеешь и не должен делать
- Не правишь код, конфигурацию, файлы вне docs/. Запрещены инструменты Write, Edit, NotebookEdit.
- Не лезешь во внешние сервисы (WebFetch/WebSearch отключены).
- Не делаешь bash-команд кроме curl на http://127.0.0.1:8080/api/*.
- Если запрос выходит за рамки проекта — честно говоришь, что это вне твоих задач.

# Как отвечать
- На русском.
- В формате markdown: заголовки, списки, таблицы для сравнения, блоки кода с языком (sql, bash, json).
- Перед действиями, которые меняют состояние (POST/DELETE), кратко поясни, что собираешься сделать.
- При ошибке передавай текст ошибки дословно, без догадок о причине.
- Не повторяй то, что аналитик и так знает: будь компактен.
"""


def build_prompt(history: Sequence[dict], attached_docs: dict[str, str], active_research_id: str | None) -> str:
    """Склеить системный контекст + приложенные документы + историю в один prompt.

    `history` — список словарей `{role: 'user'|'assistant', text: str}`. Последний элемент —
    свежая реплика пользователя; предыдущие — прошлые реплики обеих сторон.
    `attached_docs` — `{relative_path: content}` для документов, приложенных пользователем
    к свежей реплике через `@`.
    """
    parts: list[str] = []
    if active_research_id:
        parts.append(f'Активное исследование (researchId): {active_research_id}')
    if attached_docs:
        parts.append('Пользователь приложил следующие документы:')
        for path, content in attached_docs.items():
            parts.append(f'\n--- @{path} ---\n{content}\n--- /конец {path} ---')
    if len(history) > 1:
        parts.append('\nИстория диалога:')
        for msg in history[:-1]:
            role = 'Пользователь' if msg['role'] == 'user' else 'Помощник'
            parts.append(f'{role}: {msg["text"]}')
    parts.append('\nТекущая реплика пользователя:')
    parts.append(history[-1]['text'])
    return '\n'.join(parts)


async def run_assistant(
    history: Sequence[dict],
    attached_docs: dict[str, str] | None = None,
    active_research_id: str | None = None,
) -> AsyncIterator[dict]:
    """Запустить помощник и стримить события его работы.

    Возвращает события вида:
      - {type: 'text', text: str}        — фрагмент текстового ответа
      - {type: 'tool_use', name, input}  — помощник вызывает инструмент
      - {type: 'tool_result', content}   — результат инструмента
      - {type: 'done'}                   — успешное завершение
      - {type: 'error', message}         — ошибка рантайма

    Каждый вызов — отдельный subprocess. История передаётся текстом, без resume.
    """
    prompt = build_prompt(history, attached_docs or {}, active_research_id)

    cmd = [
        'claude', '--print',
        '--output-format', 'stream-json',
        '--verbose',
        '--system-prompt', SYSTEM_PROMPT,
        '--allowed-tools', ' '.join(ALLOWED_TOOLS),
        '--disallowed-tools', ' '.join(DISALLOWED_TOOLS),
        '--permission-mode', 'default',
        '--exclude-dynamic-system-prompt-sections',
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(REPO_ROOT),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(prompt.encode('utf-8'))
    await proc.stdin.drain()
    proc.stdin.close()

    timed_out = False

    async def _killer() -> None:
        nonlocal timed_out
        await asyncio.sleep(RUN_TIMEOUT_SECONDS)
        if proc.returncode is None:
            timed_out = True
            proc.kill()

    killer_task = asyncio.create_task(_killer())

    try:
        async for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            translated = _translate_event(evt)
            if translated is not None:
                yield translated
    finally:
        killer_task.cancel()
        await proc.wait()
        if timed_out:
            yield {'type': 'error', 'message': f'Помощник не уложился в {RUN_TIMEOUT_SECONDS} секунд и был остановлен.'}
        elif proc.returncode != 0:
            stderr_bytes = await proc.stderr.read() if proc.stderr else b''
            yield {'type': 'error', 'message': stderr_bytes.decode('utf-8', errors='replace') or f'claude exited rc={proc.returncode}'}
        else:
            yield {'type': 'done'}


def _translate_event(evt: dict) -> dict | None:
    """Перевести JSONL-событие Claude Code SDK в нашу схему.

    Формат stream-json: каждое событие имеет поле `type`. Для пользователя
    интересны три: assistant-сообщения с текстом, assistant-сообщения с
    `tool_use`, и user-сообщения с `tool_result`. Системные и итоговые события
    отбрасываются (рантайм сам генерирует `done`).
    """
    etype = evt.get('type')
    if etype == 'assistant':
        message = evt.get('message') or {}
        content = message.get('content') or []
        for block in content:
            btype = block.get('type')
            if btype == 'text':
                return {'type': 'text', 'text': block.get('text', '')}
            if btype == 'tool_use':
                return {
                    'type': 'tool_use',
                    'name': block.get('name', ''),
                    'input': block.get('input', {}),
                }
    elif etype == 'user':
        message = evt.get('message') or {}
        content = message.get('content') or []
        for block in content:
            if block.get('type') == 'tool_result':
                raw = block.get('content', '')
                text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
                return {'type': 'tool_result', 'content': text[:2000]}
    return None
