"""Эндпоинты каталога документации: дерево + содержимое одного документа."""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from core.docs_provider import list_docs_tree, read_doc

router = APIRouter()


@router.get('/api/docs/tree')
def get_docs_tree() -> list[dict]:
    """Иерархический список документов каталога документации."""
    return list_docs_tree()


@router.get('/api/docs/content')
def get_doc_content(path: str = Query(..., description='Относительный путь от корня каталога документации')) -> Response:
    """Содержимое одного документа в формате `text/markdown; charset=utf-8`."""
    try:
        text = read_doc(path)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return Response(content=text, media_type='text/markdown; charset=utf-8')
