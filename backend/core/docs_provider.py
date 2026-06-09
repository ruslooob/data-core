"""Каталог документации проекта: листинг дерева и чтение одного документа.

Доступ ограничен каталогом `docs/` репозитория. Защита от path traversal: после
нормализации запрошенный путь обязан лежать внутри корня. Видны только `.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DOCS_ROOT = (Path(__file__).resolve().parent.parent.parent / 'docs').resolve()


@dataclass(frozen=True)
class DocNode:
    """Узел дерева документов. type — 'file' либо 'dir'.

    `path` — относительный путь от корня каталога документации, в POSIX-стиле
    (`drafts/SPEC_X.md`), чтобы фронт и помощник одинаково понимали его на любой ОС.
    """
    name: str
    path: str
    type: str
    children: tuple['DocNode', ...] = ()

    def to_dict(self) -> dict:
        d = {'name': self.name, 'path': self.path, 'type': self.type}
        if self.type == 'dir':
            d['children'] = [c.to_dict() for c in self.children]
        return d


def list_docs_tree() -> list[dict]:
    """Иерархический список документов под `docs/`. Только `.md`, dot-файлы скрыты."""
    return [n.to_dict() for n in _walk(DOCS_ROOT)]


def read_doc(rel_path: str) -> str:
    """Прочитать один документ по относительному пути от корня каталога.

    Бросает FileNotFoundError, если документа нет, и ValueError, если путь выходит
    за пределы каталога документации или ведёт не на `.md`.
    """
    candidate = (DOCS_ROOT / rel_path).resolve()
    try:
        candidate.relative_to(DOCS_ROOT)
    except ValueError as e:
        raise ValueError(f'Путь {rel_path!r} вне каталога документации') from e
    if candidate.suffix != '.md':
        raise ValueError(f'Документация состоит только из .md-файлов, путь {rel_path!r} неподходящий')
    if not candidate.is_file():
        raise FileNotFoundError(f'Документ {rel_path!r} не найден')
    return candidate.read_text(encoding='utf-8')


def _walk(directory: Path) -> list[DocNode]:
    dirs: list[DocNode] = []
    files: list[DocNode] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith('.'):
            continue
        rel = entry.relative_to(DOCS_ROOT).as_posix()
        if entry.is_dir():
            children = _walk(entry)
            if not children:
                continue
            dirs.append(DocNode(name=entry.name, path=rel, type='dir', children=tuple(children)))
        elif entry.is_file() and entry.suffix == '.md':
            files.append(DocNode(name=entry.name, path=rel, type='file'))
    return dirs + files
