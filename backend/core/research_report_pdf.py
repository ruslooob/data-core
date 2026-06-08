"""PDF-отчёт по исследованию: имя, описание, стратегии, сводная таблица прогонов, выводы."""
from __future__ import annotations

import io
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


FONT_REGULAR = 'DejaVuSans'
FONT_BOLD = 'DejaVuSans-Bold'


def _register_fonts_once() -> None:
    if FONT_REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    import matplotlib  # шрифты DejaVu лежат в matplotlib-data, репо чистым остаётся
    ttf_dir = Path(matplotlib.__file__).parent / 'mpl-data' / 'fonts' / 'ttf'
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(ttf_dir / 'DejaVuSans.ttf')))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(ttf_dir / 'DejaVuSans-Bold.ttf')))


def render_research_report_pdf(con, research_id: str) -> bytes:
    """Собрать PDF-отчёт исследования. Возвращает байты готового файла."""
    _register_fonts_once()

    name, description, conclusion = _fetch_research_meta(con, research_id)
    strategies = _fetch_strategies_with_rules(con, research_id)
    runs = _fetch_runs_sorted_by_abs_annual_return(con, research_id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f'Отчёт исследования — {name}',
    )

    styles = _build_styles()
    story = []
    story.append(Paragraph(_escape(name), styles['title']))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph('Описание', styles['h2']))
    story.append(Paragraph(_escape(description) or _empty(), styles['body']))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph('Прогоны', styles['h2']))
    if not runs:
        story.append(Paragraph(_empty(), styles['body']))
    else:
        story.append(_runs_table(runs))
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph('Стратегии', styles['h2']))
    if not strategies:
        story.append(Paragraph(_empty(), styles['body']))
    else:
        for s in strategies:
            story.append(KeepTogether(_strategy_block(s, styles)))
            story.append(Spacer(1, 4 * mm))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph('Выводы', styles['h2']))
    story.append(Paragraph(_escape(conclusion) or _empty(), styles['body']))

    doc.build(story)
    return buf.getvalue()


def _fetch_research_meta(con, research_id: str) -> tuple[str, str | None, str | None]:
    row = con.execute(
        'SELECT name, description, conclusion FROM research WHERE id = %s',
        [research_id],
    ).fetchone()
    if row is None:
        raise ValueError(f'Исследование {research_id} не найдено')
    return row[0], row[1], row[2]


def _fetch_strategies_with_rules(con, research_id: str) -> list[dict]:
    strategies = con.execute(
        '''
        SELECT DISTINCT s.id, s.name, s.description, s.created_at
        FROM strategies s
        JOIN backtest_results br ON br.strategy_id = s.id
        WHERE br.research_id = %s
        ORDER BY s.created_at, s.name
        ''',
        [research_id],
    ).fetchall()
    out = []
    for sid, sname, sdesc, _ in strategies:
        rules = con.execute(
            '''
            SELECT r.name, r.action_type, r.description
            FROM strategy_rules sr
            JOIN rules r ON r.id = sr.rule_id
            WHERE sr.strategy_id = %s
            ORDER BY sr.position
            ''',
            [sid],
        ).fetchall()
        out.append({
            'id': sid,
            'name': sname,
            'description': sdesc,
            'rules': [{'name': r[0], 'action_type': r[1], 'description': r[2]} for r in rules],
        })
    return out


def _fetch_runs_sorted_by_abs_annual_return(con, research_id: str) -> list[tuple]:
    return con.execute(
        '''
        SELECT s.name, e.name, e.date_start, e.date_end,
               br.total_return_pct, br.annual_return_pct, br.max_drawdown_pct,
               br.sharpe, br.n_trades, br.win_rate_pct
        FROM backtest_results br
        LEFT JOIN strategies   s ON s.id = br.strategy_id
        LEFT JOIN environments e ON e.id = br.environment_id
        WHERE br.research_id = %s
        ORDER BY ABS(br.annual_return_pct) DESC NULLS LAST, br.created_at
        ''',
        [research_id],
    ).fetchall()


def _strategy_block(s: dict, styles: dict) -> list:
    block = [Paragraph(_escape(s['name']), styles['h3'])]
    if s['description']:
        block.append(Paragraph(_escape(s['description']), styles['body']))
    if s['rules']:
        block.append(Spacer(1, 2 * mm))
        block.append(Paragraph('Правила:', styles['body_bold']))
        for rule in s['rules']:
            line = f"• <b>{_escape(rule['name'])}</b> — {_escape(rule['action_type'])}"
            if rule['description']:
                line += f": {_escape(rule['description'])}"
            block.append(Paragraph(line, styles['bullet']))
    return block


def _runs_table(runs: list[tuple]) -> Table:
    header_labels = ['Стратегия', 'Окружение', 'Период', 'Доход., %', 'Годов., %',
                     'Просадка, %', 'Sharpe', 'Сделок', 'Win, %']
    header = [_wrap(label, bold=True) for label in header_labels]
    body = []
    for r in runs:
        strategy, env, dstart, dend, total, ann, mdd, sharpe, ntr, wr = r
        period_html = f'{_iso(dstart)}<br/>– {_iso(dend)}'
        body.append([
            _wrap(strategy or '—'),
            _wrap(env or '—'),
            _wrap(period_html, raw_html=True),
            _fmt_pct(total),
            _fmt_pct(ann),
            _fmt_pct(mdd),
            _fmt_num(sharpe, 2),
            str(int(ntr)) if ntr is not None else '—',
            _fmt_pct(wr),
        ])
    table = Table(
        [header] + body,
        repeatRows=1,
        hAlign='LEFT',
        colWidths=[m * mm for m in (26, 22, 22, 18, 16, 20, 16, 16, 18)],
    )
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E8E8E8')),
        ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#888888')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    return table


def _build_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        'title': ParagraphStyle(
            'TitleK', parent=base['Title'], fontName=FONT_BOLD, fontSize=20, leading=24,
        ),
        'h2': ParagraphStyle(
            'H2K', parent=base['Heading2'], fontName=FONT_BOLD, fontSize=13, leading=16,
            spaceBefore=6, spaceAfter=4,
        ),
        'h3': ParagraphStyle(
            'H3K', parent=base['Heading3'], fontName=FONT_BOLD, fontSize=11, leading=14,
            spaceBefore=2, spaceAfter=2,
        ),
        'body': ParagraphStyle(
            'BodyK', parent=base['BodyText'], fontName=FONT_REGULAR, fontSize=10, leading=13,
        ),
        'body_bold': ParagraphStyle(
            'BodyBoldK', parent=base['BodyText'], fontName=FONT_BOLD, fontSize=10, leading=13,
        ),
        'bullet': ParagraphStyle(
            'BulletK', parent=base['BodyText'], fontName=FONT_REGULAR, fontSize=10, leading=13,
            leftIndent=8,
        ),
    }


def _escape(s: str | None) -> str:
    if s is None:
        return ''
    return (
        s.replace('&', '&amp;')
         .replace('<', '&lt;')
         .replace('>', '&gt;')
    )


def _wrap(s: str, bold: bool = False, raw_html: bool = False) -> Paragraph:
    """Текст в ячейке таблицы — Paragraph, чтобы reportlab переносил длинные строки.
    `raw_html=True` оставляет разметку как есть (для собственных строк вроде period с <br/>)."""
    safe = s if raw_html else _escape(s)
    font = FONT_BOLD if bold else FONT_REGULAR
    return Paragraph(safe, ParagraphStyle('Cell', fontName=font, fontSize=8, leading=10))


def _empty() -> str:
    return '<i>не указано</i>'


def _iso(d) -> str:
    if d is None:
        return '—'
    return d.isoformat() if hasattr(d, 'isoformat') else str(d)


def _fmt_pct(v) -> str:
    if v is None:
        return '—'
    return f'{float(v):.2f}'


def _fmt_num(v, digits: int) -> str:
    if v is None:
        return '—'
    return f'{float(v):.{digits}f}'
