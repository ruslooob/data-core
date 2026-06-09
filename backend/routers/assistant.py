"""SSE-эндпоинт помощника: стримит события рантайма обратно в виджет."""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from core.assistant_runtime import run_assistant
from core.docs_provider import read_doc
from schemas.assistant import AssistantRequest

router = APIRouter()


@router.post('/api/assistant/messages')
async def post_message(req: AssistantRequest):
    """Принять реплику пользователя и стримить события помощника в SSE.

    Тело запроса включает всю историю текущего чата — рантайм эфемерный,
    сервер не помнит прошлых сообщений между запросами.
    """
    if not req.history:
        raise HTTPException(status_code=400, detail='Пустая история диалога')
    if req.history[-1].role != 'user':
        raise HTTPException(status_code=400, detail='Последняя реплика в истории должна быть от пользователя')

    attached = _load_attached_docs(req.attached_docs)

    async def event_stream():
        history_dicts = [{'role': m.role, 'text': m.text} for m in req.history]
        try:
            async for evt in run_assistant(history_dicts, attached, req.research_id):
                yield _sse_format(evt)
        except Exception as e:
            yield _sse_format({'type': 'error', 'message': str(e)})

    return StreamingResponse(
        event_stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        },
    )


def _load_attached_docs(paths: list[str]) -> dict[str, str]:
    """Подгрузить содержимое приложенных документов. Несуществующие — пропускаем."""
    out: dict[str, str] = {}
    for path in paths:
        try:
            out[path] = read_doc(path)
        except (FileNotFoundError, ValueError):
            continue
    return out


def _sse_format(event: dict) -> str:
    return f'data: {json.dumps(event, ensure_ascii=False)}\n\n'
