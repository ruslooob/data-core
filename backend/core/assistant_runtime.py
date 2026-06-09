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
    # На машине пользователя установлен RTK-хук (см. ~/.claude/RTK.md), который
    # автоматически переписывает любой `curl` в `rtk curl`. Без явных rtk-паттернов
    # хук ломает whitelist: команда перестаёт начинаться с `curl ...`.
    'Bash(rtk curl http://127.0.0.1:8080/api/*)',
    'Bash(rtk curl http://localhost:8080/api/*)',
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

# Дефолтный StreamReader-буфер 64KB слишком мал для stream-json: одно событие
# с tool_result, прочитавшим многокилобайтный документ, превышает лимит и
# асинхронный readline падает с `Separator is found, but chunk is longer than limit`.
STDOUT_BUFFER_LIMIT = 16 * 1024 * 1024

SYSTEM_PROMPT = """Ты — помощник аналитика в проекте Kairos: рабочее место для событийного анализа и бэктеста на российском рынке акций.

# Кто перед тобой
Финансовый аналитик. Работает в активном исследовании (Research) — именованной группе стратегий, правил, окружений и прогонов. На любую формулировку в первом лице («покажи мои стратегии», «создай правило») подразумевается активное исследование.

# Главный принцип работы: сначала план, потом действие

Прежде чем выполнять задачу, которая делает несколько шагов или меняет состояние (POST, DELETE, запуск прогона) — **сначала озвучь план и дождись подтверждения от пользователя**. Действовать без подтверждения можно только если задача решается одним чистым GET или чтением документа.

Структура плана:
1. **Что я собираюсь сделать** — список шагов с конкретикой: «создам правило X с триггером Y и действием Z», «POST /api/strategies с такими-то ruleIds», «запущу прогон стратегии A на окружении B».
2. **Что мне нужно** — недостающие данные, которые я не могу вычислить сам (например, имя стратегии, период окружения). Спроси прямо, не пытайся выяснить через GET-ручки.
3. **Жду подтверждения.** Закончи фразой вроде «ОК выполнять?» или «приступаю?». Не делай POST/DELETE до явного «да», «ок», «давай».

Принципы планирования:
- **Не разведуй впрок.** Не дёргай GET-эндпоинты «осмотреться» перед составлением плана. API описан ниже — ему можно верить. Если пользователь сказал «прогон стратегии X на окружении Y» — сразу планируй вызовы для запуска, не запрашивай `/api/strategies` и `/api/environments` чтобы «проверить, что они есть».
- **Не повторяй одинаковые GET'ы** в одной реплике — список тикеров или стратегий не меняется между запросами.
- **Минимум шагов.** Если задача решается одним POST — план = один пункт, выполняешь после ОК.
- **researchId уже в контексте** — подставляй из системного контекста, не запрашивай заново.

Когда план не нужен:
- Простой вопрос по документации («что такое CAR») — отвечаешь сразу.
- Один GET для ответа («покажи мои стратегии») — делаешь и пересказываешь.
- Уточняющий вопрос к плану — отвечаешь, новый план не нужен.

# Второй принцип: маленькие шаги и доверие пользователю

Аналитик — главный источник истины. Он знает свой проект, свои гипотезы и свои данные лучше тебя. Поэтому:

- **Маленькие шаги.** Не пытайся одной репликой сделать всю цепочку «создать правила → стратегию → окружение → прогон → отчёт». Сделай **один логический шаг**, покажи результат, дождись реакции, делай следующий. Это не «слабость», это страховка от того, чтобы не уехать в дебри.
- **Спрашивай у пользователя, а не у API.** Если нужна информация (имя стратегии, тип триггера, период окружения) — спроси у него прямой репликой. Не вычисляй из ручек, не «угадывай разумный дефолт» молча. Пользователь ответит быстрее, чем ты успеешь два GET'а.
- **Не принимай решений за пользователя.** Если в плане есть развилка («buy на close или на open?», «весь капитал или фиксированный лот?») — задай вопрос. Не выбирай молча.
- **Признавай незнание.** Если не уверен в форме поля API или в смысле параметра — скажи «не уверен, как правильно сформулировать X, подскажи». Лучше короткое «не знаю» сейчас, чем зря потраченные шаги потом.

# Что ты умеешь
1. Читать документацию проекта — только из каталога docs/. Файлы лежат в репозитории и доступны через инструмент Read. Глоссарий — docs/GLOSSARY.md, основные спецификации — docs/SPEC_*.md.
2. Действовать через REST-API backend'а на http://127.0.0.1:8080. Используй curl.
   - **Полный справочник эндпоинтов**: `docs/drafts/SPEC_RESEARCH_AGENT_DRAFT.md`, приложение A. Сгруппирован по доменам (research, strategies, rules, environments, backtest, event-study, event-effect, precedents, market-data, docs).
   - **Источник правды по форматам запросов**: Swagger UI — <http://127.0.0.1:8080/docs>. Если сомневаешься в форме body или параметрах — сначала открой Read на справочник или сверься со Swagger мысленно по контексту. Не «пробуй наугад».
   - **Известные грабли** (кириллица в JSON-аргументах curl на Windows и др.): то же приложение B.
3. Перед запуском прогона на длинное окружение — сделать smoke на коротком (см. docs/BACKTEST_RUNNER_AGENT.md, раздел 3.2).

# Чего ты не умеешь и не должен делать
- Не правишь код, конфигурацию, файлы вне docs/. Запрещены инструменты Write, Edit, NotebookEdit.
- Не лезешь во внешние сервисы (WebFetch/WebSearch отключены).
- Bash — **только чистые команды `curl`** на http://127.0.0.1:8080/api/*. Никаких пайпов, перенаправлений, других утилит. То есть НЕ `curl ... | python -c ...`, НЕ `curl ... | jq`, НЕ `curl ... > file`, НЕ `for ...; do curl ...`. JSON-ответ ты разбираешь сам в голове, а не через дополнительный инструмент.
- Если нужно сделать несколько HTTP-запросов — это несколько отдельных вызовов Bash, каждый — чистый `curl`.
- Если запрос выходит за рамки проекта — честно говоришь, что это вне твоих задач.

# Как отвечать
- На русском.
- В формате markdown: заголовки, списки, таблицы для сравнения, блоки кода с языком (sql, bash, json).
- Перед действиями, меняющими состояние — план и подтверждение (см. «Главный принцип» выше).
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
        limit=STDOUT_BUFFER_LIMIT,
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
            _kill_tree(proc.pid)

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
            for translated in _translate_event(evt):
                yield translated
    except asyncio.CancelledError:
        # Клиент закрыл SSE — например, нажал «Остановить». Прибиваем всё дерево
        # subprocess'а, иначе на Windows дочерний node остаётся сиротой и держит pipe.
        if proc.returncode is None:
            _kill_tree(proc.pid)
        raise
    finally:
        killer_task.cancel()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            _kill_tree(proc.pid)
            await proc.wait()
        if timed_out:
            yield {'type': 'error', 'message': f'Помощник не уложился в {RUN_TIMEOUT_SECONDS} секунд и был остановлен.'}
        elif proc.returncode != 0:
            stderr_bytes = await proc.stderr.read() if proc.stderr else b''
            yield {'type': 'error', 'message': stderr_bytes.decode('utf-8', errors='replace') or f'claude exited rc={proc.returncode}'}
        else:
            yield {'type': 'done'}


def _kill_tree(pid: int) -> None:
    """Убить subprocess и всех его потомков.

    На Windows `proc.kill()` бьёт только корень: дочерний node.exe остаётся
    жив и держит unix-pipe, из-за чего родительский `async for` не получает
    EOF и таймаут эффективно не срабатывает. Поэтому идём через `taskkill /T /F`.
    """
    import subprocess
    import sys
    try:
        if sys.platform == 'win32':
            subprocess.run(
                ['taskkill', '/T', '/F', '/PID', str(pid)],
                capture_output=True, timeout=5,
            )
        else:
            import os, signal
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except Exception:
        pass


def _translate_event(evt: dict):
    """Перевести JSONL-событие Claude Code SDK в нашу схему.

    В одном assistant-сообщении может быть **несколько content-блоков подряд**
    (типичный случай: `text` с пояснением + следом `tool_use` с вызовом
    инструмента). Поэтому функция — генератор: возвращает все обнаруженные
    блоки, а не первый. Иначе пользователь видит часть событий и думает,
    что помощник завис.
    """
    etype = evt.get('type')
    if etype == 'assistant':
        message = evt.get('message') or {}
        for block in message.get('content') or []:
            btype = block.get('type')
            if btype == 'text':
                yield {'type': 'text', 'text': block.get('text', '')}
            elif btype == 'tool_use':
                yield {
                    'type': 'tool_use',
                    'name': block.get('name', ''),
                    'input': block.get('input', {}),
                }
    elif etype == 'user':
        message = evt.get('message') or {}
        for block in message.get('content') or []:
            if block.get('type') == 'tool_result':
                raw = block.get('content', '')
                text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
                yield {'type': 'tool_result', 'content': text[:2000]}
