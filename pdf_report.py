from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


PRIMARY_COLOR = colors.HexColor("#B83229")
GOLD_COLOR = colors.HexColor("#B8860B")
TEXT_COLOR = colors.HexColor("#333333")
MUTED_COLOR = colors.HexColor("#666666")
LIGHT_BG = colors.HexColor("#F8F6F0")


def _first_existing_font() -> str | None:
    candidates = [
        os.getenv("PDF_CHINESE_FONT"),
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\NotoSansSC-VF.ttf",
        r"C:\Windows\Fonts\simsun.ttc",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def register_chinese_fonts() -> Tuple[str, str]:
    """Return (regular_font, bold_font), registering local CJK fonts when possible."""
    font_path = _first_existing_font()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("BaziCN", font_path))
            pdfmetrics.registerFont(TTFont("BaziCN-Bold", font_path))
            return "BaziCN", "BaziCN-Bold"
        except Exception:
            pass

    # Built-in CID font keeps Chinese text vectorized even without a local TTF.
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light", "STSong-Light"


def _safe_text(value: Any, default: str = "未知") -> str:
    text = str(value if value not in (None, "") else default)
    text = html.unescape(text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    # Emoji glyph coverage varies by local font; remove non-BMP chars for stable PDF output.
    text = re.sub(r"[\U00010000-\U0010ffff]", "", text)
    return text.strip() or default


def _escape(value: Any) -> str:
    return html.escape(_safe_text(value, ""), quote=False)


def _strip_html_and_markdown(content: str) -> List[Tuple[str, str]]:
    """Convert HTML/Markdown-ish analysis text into typed text blocks."""
    text = _safe_text(content, "")
    if not text:
        return []

    replacements = [
        (r"<br\s*/?>", "\n"),
        (r"</p\s*>", "\n\n"),
        (r"<p[^>]*>", ""),
        (r"</div\s*>", "\n"),
        (r"<div[^>]*>", ""),
        (r"</h[1-6]\s*>", "\n\n"),
        (r"<h[1-6][^>]*>", "\n### "),
        (r"<li[^>]*>", "\n- "),
        (r"</li\s*>", ""),
        (r"</?[uo]l[^>]*>", "\n"),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)

    blocks: List[Tuple[str, str]] = []
    paragraph: List[str] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        joined = " ".join(part.strip() for part in paragraph if part.strip())
        if joined:
            blocks.append(("paragraph", joined))
        paragraph = []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            flush_paragraph()
            continue
        heading_match = re.match(r"^#{1,6}\s+(.+)$", line)
        bullet_match = re.match(r"^[-*+]\s+(.+)$", line)
        numbered_match = re.match(r"^(\d+[.)])\s+(.+)$", line)
        quote_match = re.match(r"^>\s+(.+)$", line)

        if heading_match:
            flush_paragraph()
            blocks.append(("heading", heading_match.group(1).strip()))
        elif bullet_match:
            flush_paragraph()
            blocks.append(("bullet", bullet_match.group(1).strip()))
        elif numbered_match:
            flush_paragraph()
            blocks.append(("bullet", f"{numbered_match.group(1)} {numbered_match.group(2).strip()}"))
        elif quote_match:
            flush_paragraph()
            blocks.append(("quote", quote_match.group(1).strip()))
        else:
            paragraph.append(line)
    flush_paragraph()
    return blocks


def _styles(font_name: str, bold_font: str) -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BaziTitle",
            parent=base["Title"],
            fontName=bold_font,
            fontSize=24,
            leading=32,
            textColor=PRIMARY_COLOR,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "BaziSubtitle",
            parent=base["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=16,
            textColor=GOLD_COLOR,
            alignment=TA_CENTER,
            spaceAfter=16,
        ),
        "section": ParagraphStyle(
            "BaziSection",
            parent=base["Heading2"],
            fontName=bold_font,
            fontSize=15,
            leading=22,
            textColor=PRIMARY_COLOR,
            spaceBefore=14,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "subsection": ParagraphStyle(
            "BaziSubsection",
            parent=base["Heading3"],
            fontName=bold_font,
            fontSize=11.5,
            leading=17,
            textColor=GOLD_COLOR,
            spaceBefore=8,
            spaceAfter=5,
            keepWithNext=True,
        ),
        "analysis_title": ParagraphStyle(
            "BaziAnalysisTitle",
            parent=base["Heading3"],
            fontName=bold_font,
            fontSize=13,
            leading=19,
            textColor=colors.white,
            backColor=PRIMARY_COLOR,
            borderPadding=6,
            spaceBefore=10,
            spaceAfter=8,
            keepWithNext=True,
        ),
        "heading": ParagraphStyle(
            "BaziInnerHeading",
            parent=base["Heading4"],
            fontName=bold_font,
            fontSize=11,
            leading=16,
            textColor=GOLD_COLOR,
            spaceBefore=8,
            spaceAfter=4,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "BaziBody",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.2,
            leading=15,
            textColor=TEXT_COLOR,
            alignment=TA_LEFT,
            firstLineIndent=10,
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "BaziBullet",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9.2,
            leading=15,
            textColor=TEXT_COLOR,
            leftIndent=12,
            bulletIndent=3,
            spaceAfter=4,
        ),
        "quote": ParagraphStyle(
            "BaziQuote",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=9,
            leading=14,
            textColor=MUTED_COLOR,
            leftIndent=10,
            borderColor=GOLD_COLOR,
            borderWidth=1,
            borderPadding=5,
            spaceAfter=6,
        ),
        "small": ParagraphStyle(
            "BaziSmall",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=8,
            leading=12,
            textColor=MUTED_COLOR,
        ),
        "table_header": ParagraphStyle(
            "BaziTableHeader",
            parent=base["BodyText"],
            fontName=bold_font,
            fontSize=8.2,
            leading=11,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_label": ParagraphStyle(
            "BaziTableLabel",
            parent=base["BodyText"],
            fontName=bold_font,
            fontSize=8,
            leading=11,
            textColor=PRIMARY_COLOR,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "BaziTableCell",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.5,
            leading=10.5,
            textColor=TEXT_COLOR,
            alignment=TA_CENTER,
        ),
        "table_cell_left": ParagraphStyle(
            "BaziTableCellLeft",
            parent=base["BodyText"],
            fontName=font_name,
            fontSize=7.4,
            leading=10.5,
            textColor=TEXT_COLOR,
            alignment=TA_LEFT,
        ),
    }


def _info_table(rows: Iterable[Tuple[str, Any]], font_name: str, bold_font: str) -> Table:
    data = []
    for label, value in rows:
        data.append([
            Paragraph(f"<b>{_escape(label)}</b>", ParagraphStyle("label", fontName=bold_font, fontSize=9, leading=13, textColor=PRIMARY_COLOR)),
            Paragraph(_escape(value), ParagraphStyle("value", fontName=font_name, fontSize=9, leading=13, textColor=TEXT_COLOR)),
        ])
    table = Table(data, colWidths=[30 * mm, 125 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E7E0D6")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E7E0D6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _cell(value: Any, style: ParagraphStyle, fallback: str = "—") -> Paragraph:
    text = _safe_text(value, "")
    if not text:
        text = fallback
    escaped = "<br/>".join(html.escape(line, quote=False) for line in text.splitlines())
    return Paragraph(escaped or fallback, style)


def _join_list(value: Any, fallback: str = "—") -> str:
    if value in (None, ""):
        return fallback
    if isinstance(value, (list, tuple, set)):
        items = [str(item).strip() for item in value if str(item).strip()]
        return "、".join(items) if items else fallback
    if isinstance(value, dict):
        items = [f"{key}:{val}" for key, val in value.items() if val not in (None, "", [], {})]
        return "；".join(items) if items else fallback
    return str(value)


def _format_stem(stem: Dict[str, Any]) -> str:
    stem = stem if isinstance(stem, dict) else {}
    meta = [stem.get("element"), stem.get("yinYang"), stem.get("tenGod")]
    meta_text = " / ".join(str(item) for item in meta if item)
    return f"{stem.get('char') or '—'}" + (f"\n{meta_text}" if meta_text else "")


def _format_branch(branch: Dict[str, Any]) -> str:
    branch = branch if isinstance(branch, dict) else {}
    meta = [branch.get("element"), branch.get("yinYang")]
    meta_text = " / ".join(str(item) for item in meta if item)
    return f"{branch.get('char') or '—'}" + (f"\n{meta_text}" if meta_text else "")


def _format_hidden_stems(hidden_stems: Any, include_ten_god: bool = True) -> str:
    if not isinstance(hidden_stems, list) or not hidden_stems:
        return "—"
    parts = []
    for item in hidden_stems:
        if not isinstance(item, dict):
            if item:
                parts.append(str(item))
            continue
        role = str(item.get("role") or "").strip()
        role = {"main": "主气", "middle": "中气", "rest": "余气"}.get(role, role)
        char = str(item.get("char") or "").strip()
        ten_god = str(item.get("tenGod") or "").strip()
        element = str(item.get("element") or "").strip()
        if not char:
            continue
        label = f"{role} " if role else ""
        meta = " / ".join(piece for piece in [ten_god if include_ten_god else "", element] if piece)
        parts.append(f"{label}{char}" + (f"（{meta}）" if meta else ""))
    return "\n".join(parts) if parts else "—"


def _make_table(data: List[List[Any]], col_widths: List[Any], styles: Dict[str, ParagraphStyle], header_rows: int = 0) -> Table:
    converted = []
    for row_index, row in enumerate(data):
        converted_row = []
        for col_index, value in enumerate(row):
            if isinstance(value, Paragraph):
                converted_row.append(value)
            elif row_index < header_rows:
                converted_row.append(_cell(value, styles["table_header"]))
            elif col_index == 0:
                converted_row.append(_cell(value, styles["table_label"]))
            else:
                converted_row.append(_cell(value, styles["table_cell"]))
        converted.append(converted_row)
    table = Table(converted, colWidths=col_widths, repeatRows=header_rows, hAlign="LEFT")
    table_style = [
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#E7E0D6")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    if header_rows:
        table_style.append(("BACKGROUND", (0, 0), (-1, header_rows - 1), PRIMARY_COLOR))
    table_style.append(("BACKGROUND", (0, header_rows), (0, -1), LIGHT_BG))
    table.setStyle(TableStyle(table_style))
    return table


def _append_chart_details(
    story: List[Any],
    bazi: Dict[str, Any],
    styles: Dict[str, ParagraphStyle],
    font_name: str,
    bold_font: str,
) -> None:
    chart = bazi.get("chartDetails") if isinstance(bazi, dict) else {}
    if not isinstance(chart, dict):
        return

    meta = chart.get("meta") if isinstance(chart.get("meta"), dict) else {}
    extra = chart.get("extra") if isinstance(chart.get("extra"), dict) else {}
    story.extend([
        Spacer(1, 8),
        Paragraph("完整命盘信息", styles["section"]),
        _info_table(
            [
                ("历法", meta.get("calendarType")),
                ("真太阳时", "已校正" if meta.get("solarTimeApplied") else "未校正"),
                ("真太阳时结果", meta.get("trueSolarTime")),
                ("经度", meta.get("longitude")),
                ("胎元", extra.get("胎元")),
                ("胎息", extra.get("胎息")),
                ("命宫", extra.get("命宫")),
                ("身宫", extra.get("身宫")),
            ],
            font_name,
            bold_font,
        ),
        Spacer(1, 8),
        Paragraph("四柱细盘", styles["subsection"]),
    ])

    pillars = [item for item in (chart.get("pillars") or []) if isinstance(item, dict)]
    labels = [pillar.get("label") or f"第 {idx} 柱" for idx, pillar in enumerate(pillars, 1)]
    table_rows = [["日期"] + labels]
    gender_text = str(meta.get("gender") or "")
    day_master_label = "元女" if gender_text in ("0", "女", "female", "Female", "F", "f") else "元男"
    row_specs = [
        ("主星", lambda p: (p.get("stem") or {}).get("tenGod") or (day_master_label if p.get("label") == "日柱" else "—")),
        ("天干", lambda p: _format_stem(p.get("stem") or {})),
        ("地支", lambda p: _format_branch(p.get("branch") or {})),
        ("藏干", lambda p: _format_hidden_stems((p.get("branch") or {}).get("hiddenStems"), include_ten_god=False)),
        ("副星", lambda p: _format_hidden_stems((p.get("branch") or {}).get("hiddenStems"), include_ten_god=True)),
        ("星运", lambda p: p.get("xingyun") or "—"),
        ("自坐", lambda p: p.get("zizuo") or "—"),
        ("空亡", lambda p: p.get("kongwang") or "—"),
        ("纳音", lambda p: p.get("nayin") or "—"),
        ("旬", lambda p: p.get("xun") or "—"),
        ("神煞", lambda p: _join_list(p.get("shensha"))),
    ]
    for label, getter in row_specs:
        table_rows.append([label] + [getter(pillar) for pillar in pillars])
    if pillars:
        story.append(_make_table(table_rows, [22 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm], styles, header_rows=1))

    dayun = chart.get("dayun") if isinstance(chart.get("dayun"), dict) else {}
    cycles = [item for item in (dayun.get("cycles") or []) if isinstance(item, dict)]
    if cycles:
        story.extend([
            Spacer(1, 10),
            Paragraph("大运流转", styles["subsection"]),
            Paragraph(
                f"起运日期：{_escape(dayun.get('startDate') or '—')}　起运年龄：{_escape(dayun.get('startAge') or '—')} 岁",
                styles["small"],
            ),
            Spacer(1, 4),
        ])
        dayun_rows = [["序", "干支", "年份", "年龄", "天干十神", "地支十神", "地支藏干"]]
        for row in cycles:
            year_range = f"{row.get('startYear') or '—'}-{row.get('endYear') or '—'}"
            age_range = f"{row.get('startAge') or '—'}-{row.get('endAge') or '—'}"
            dayun_rows.append([
                row.get("order"),
                row.get("ganzhi"),
                year_range,
                age_range,
                row.get("stemTenGod") or "—",
                _join_list(row.get("branchTenGods")),
                _join_list(row.get("hiddenStems")),
            ])
        story.append(_make_table(
            dayun_rows,
            [10 * mm, 16 * mm, 26 * mm, 22 * mm, 23 * mm, 39 * mm, 38 * mm],
            styles,
            header_rows=1,
        ))

    relations = chart.get("relations") if isinstance(chart.get("relations"), dict) else {}
    relation_lines: List[str] = []
    for pillar_key in ["年", "月", "日", "时"]:
        pillar_payload = relations.get(pillar_key)
        if not isinstance(pillar_payload, dict):
            continue
        for area in ["天干", "地支"]:
            area_payload = pillar_payload.get(area)
            if not isinstance(area_payload, dict):
                continue
            for relation_name, relation_items in area_payload.items():
                items = relation_items if isinstance(relation_items, list) else [relation_items]
                for item in items:
                    if isinstance(item, dict):
                        pieces = [
                            f"关联{item.get('柱')}" if item.get("柱") else "",
                            str(item.get("知识点") or ""),
                            f"元素{item.get('元素')}" if item.get("元素") else "",
                        ]
                        detail = "，".join(piece for piece in pieces if piece)
                    else:
                        detail = str(item)
                    if detail:
                        relation_lines.append(f"{pillar_key}柱 {area} {relation_name}：{detail}")
    if relation_lines:
        story.extend([Spacer(1, 10), Paragraph("刑冲合会", styles["subsection"])])
        for line in relation_lines:
            story.append(Paragraph(_escape(line), styles["bullet"], bulletText="•"))


def _draw_page(canvas, doc, font_name: str) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#E7E0D6"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 15 * mm, 192 * mm, 15 * mm)
    canvas.setFillColor(MUTED_COLOR)
    canvas.setFont(font_name, 8)
    canvas.drawCentredString(105 * mm, 10 * mm, f"八字命理深度分析报告  ·  第 {doc.page} 页")
    canvas.restoreState()


def _html_escape(value: Any, default: str = "") -> str:
    return html.escape(_safe_text(value, default), quote=True)


def _html_join(value: Any, fallback: str = "—") -> str:
    text = _join_list(value, fallback="")
    return _html_escape(text or fallback)


def _listify(value: Any) -> List[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _element_class(value: Any) -> str:
    text = str(value or "")
    if "木" in text:
        return "wood"
    if "火" in text:
        return "fire"
    if "土" in text:
        return "earth"
    if "金" in text:
        return "metal"
    if "水" in text:
        return "water"
    return ""


def _gan_zhi_span(char: Any, element: Any = "") -> str:
    char_text = _html_escape(char, "—")
    element_class = _element_class(element or char)
    return f'<span class="gz {element_class}">{char_text}</span>'


def _hidden_stems_html(hidden_stems: Any, show_ten_god: bool = True) -> str:
    if not isinstance(hidden_stems, list) or not hidden_stems:
        return '<span class="muted">—</span>'
    parts = []
    for item in hidden_stems:
        if isinstance(item, dict):
            char = item.get("char")
            if not char:
                continue
            ten_god = item.get("tenGod")
            element = item.get("element")
            role = str(item.get("role") or "")
            role = {"main": "主气", "middle": "中气", "rest": "余气"}.get(role, role)
            pieces = [
                f'<span class="hidden-char {_element_class(element)}">{_html_escape(char)}</span>',
            ]
            if show_ten_god and ten_god:
                pieces.append(f'<span class="hidden-god">{_html_escape(ten_god)}</span>')
            if role and role not in ("主气", "中气", "余气"):
                pieces.append(f'<span class="hidden-role">{_html_escape(role)}</span>')
            parts.append(f'<span class="hidden-item">{"".join(pieces)}</span>')
        elif item:
            parts.append(f'<span class="hidden-item">{_html_escape(item)}</span>')
    return "".join(parts) or '<span class="muted">—</span>'


def _simple_markdown_to_html(content: Any) -> str:
    blocks = _strip_html_and_markdown(str(content or ""))
    if not blocks:
        return '<p class="muted">暂无内容</p>'
    rendered = []
    for block_type, text in blocks:
        escaped = _html_escape(text)
        if block_type == "heading":
            rendered.append(f"<h4>{escaped}</h4>")
        elif block_type == "bullet":
            rendered.append(f"<p class=\"bullet\">{escaped}</p>")
        elif block_type == "quote":
            rendered.append(f"<blockquote>{escaped}</blockquote>")
        else:
            rendered.append(f"<p>{escaped}</p>")
    return "\n".join(rendered)


def _find_chromium_executable() -> str | None:
    env_path = os.getenv("PDF_CHROMIUM_PATH")
    if env_path and os.path.exists(env_path):
        return env_path

    candidates = [
        shutil.which("chrome"),
        shutil.which("chromium"),
        shutil.which("msedge"),
        shutil.which("google-chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]

    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        ms_playwright = Path(local_app_data) / "ms-playwright"
        if ms_playwright.exists():
            patterns = [
                "chromium-*/chrome-win/chrome.exe",
                "chromium_headless_shell-*/chrome-win/headless_shell.exe",
                "chromium_headless_shell-*/chrome-win/headless_shell.exe",
            ]
            for pattern in patterns:
                candidates.extend(str(path) for path in ms_playwright.glob(pattern))

    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _html_to_pdf_bytes(html_doc: str) -> bytes:
    chromium = _find_chromium_executable()
    if not chromium:
        raise RuntimeError("未找到 Chromium/Chrome，无法使用 HTML 版 PDF 渲染")

    with tempfile.TemporaryDirectory(prefix="bazi_pdf_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        html_path = tmp_path / "report.html"
        pdf_path = tmp_path / "report.pdf"
        html_path.write_text(html_doc, encoding="utf-8")
        file_url = html_path.resolve().as_uri()
        command = [
            chromium,
            "--headless",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--print-to-pdf-no-header",
            f"--print-to-pdf={pdf_path}",
            file_url,
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        data = pdf_path.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise RuntimeError("HTML 版 PDF 渲染未生成有效 PDF")
        return data


def _build_bazi_plate_html(chart: Dict[str, Any], bazi: Dict[str, Any], user: Dict[str, Any]) -> str:
    meta = chart.get("meta") if isinstance(chart.get("meta"), dict) else {}
    pillars = [item for item in (chart.get("pillars") or []) if isinstance(item, dict)]
    labels = [pillar.get("label") or f"第 {index} 柱" for index, pillar in enumerate(pillars, 1)]
    if len(labels) != 4:
        labels = ["年柱", "月柱", "日柱", "时柱"]

    gender_text = str(user.get("gender") or meta.get("gender") or "")
    day_master_label = "元女" if gender_text in ("0", "女", "female", "Female", "F", "f") else "元男"

    def pillar_cell(index: int, kind: str) -> str:
        pillar = pillars[index] if index < len(pillars) else {}
        stem = pillar.get("stem") if isinstance(pillar.get("stem"), dict) else {}
        branch = pillar.get("branch") if isinstance(pillar.get("branch"), dict) else {}
        hidden_stems = branch.get("hiddenStems") if isinstance(branch, dict) else []
        if kind == "main_star":
            return _html_escape(stem.get("tenGod") or (day_master_label if pillar.get("label") == "日柱" else "—"))
        if kind == "stem":
            return _gan_zhi_span(stem.get("char"), stem.get("element"))
        if kind == "branch":
            return _gan_zhi_span(branch.get("char"), branch.get("element"))
        if kind == "hidden":
            return _hidden_stems_html(hidden_stems, show_ten_god=True)
        if kind == "sub_star":
            return "".join(
                f'<span class="stack-item">{_html_escape(item.get("tenGod"))}</span>'
                for item in hidden_stems
                if isinstance(item, dict) and item.get("tenGod")
            ) or '<span class="muted">—</span>'
        if kind == "xingyun":
            return _html_escape(pillar.get("xingyun"), "—")
        if kind == "zizuo":
            return _html_escape(pillar.get("zizuo"), "—")
        if kind == "kongwang":
            return _html_escape(pillar.get("kongwang"), "—")
        if kind == "nayin":
            return f'<span class="{_element_class(pillar.get("nayin"))}">{_html_escape(pillar.get("nayin"), "—")}</span>'
        if kind == "shensha":
            return "".join(f'<span class="stack-item gold">{_html_escape(item)}</span>' for item in _listify(pillar.get("shensha"))) or '<span class="muted">—</span>'
        return '<span class="muted">—</span>'

    rows = [
        ("主星", "main_star"),
        ("天干", "stem"),
        ("地支", "branch"),
        ("藏干", "hidden"),
        ("副星", "sub_star"),
        ("星运", "xingyun"),
        ("自坐", "zizuo"),
        ("空亡", "kongwang"),
        ("纳音", "nayin"),
        ("神煞", "shensha"),
    ]
    body_rows = []
    for label, kind in rows:
        cells = "".join(f"<td>{pillar_cell(index, kind)}</td>" for index in range(4))
        body_rows.append(f"<tr><th>{_html_escape(label)}</th>{cells}</tr>")

    plate_meta = [
        ("阳历", meta.get("solar") or bazi.get("solarDate")),
        ("农历", meta.get("lunar") or bazi.get("lunarDate")),
        ("八字", meta.get("bazi") or bazi.get("bazi")),
        ("日主", f"{meta.get('dayMaster') or bazi.get('dayMaster') or '—'} · {meta.get('zodiac') or bazi.get('zodiac') or '—'}"),
    ]
    meta_html = "".join(
        f'<div class="meta-item"><div class="meta-label">{_html_escape(label)}</div><div class="meta-value">{_html_escape(value, "—")}</div></div>'
        for label, value in plate_meta
    )

    header_cols = "".join(f"<th>{_html_escape(label)}</th>" for label in labels)
    return f"""
        <div class="meta-grid">{meta_html}</div>
        <table class="bazi-table">
            <thead><tr><th class="row-label">日期</th>{header_cols}</tr></thead>
            <tbody>{''.join(body_rows)}</tbody>
        </table>
    """


def _build_dayun_html(chart: Dict[str, Any]) -> str:
    dayun = chart.get("dayun") if isinstance(chart.get("dayun"), dict) else {}
    cycles = [item for item in (dayun.get("cycles") or []) if isinstance(item, dict)]
    if not cycles:
        return ""
    current_year = datetime.now().year
    cards = []
    current_text = "当前大运未定位"
    for row in cycles:
        start_year = row.get("startYear")
        end_year = row.get("endYear")
        try:
            is_current = int(start_year) <= current_year <= int(end_year)
        except Exception:
            is_current = False
        if is_current:
            current_text = f"当前：{row.get('ganzhi') or '—'} {start_year or ''}-{end_year or ''}"
        ganzhi = str(row.get("ganzhi") or "—")
        stem = ganzhi[0] if ganzhi else "—"
        branch = ganzhi[1] if len(ganzhi) > 1 else "—"
        year_range = f"{start_year or '—'}-{end_year or '—'}"
        age_range = f"{row.get('startAge') or '—'}-{row.get('endAge') or '—'}岁"
        branch_ten_gods = _join_list(row.get("branchTenGods"), "")
        cards.append(f"""
            <div class="dayun-card {'current' if is_current else ''}">
                <div class="dayun-range">{_html_escape(year_range)}</div>
                <div class="dayun-gz">{_gan_zhi_span(stem)}{_gan_zhi_span(branch)}</div>
                <div class="dayun-age">{_html_escape(age_range)}</div>
                <div class="dayun-meta">天干十神：{_html_escape(row.get('stemTenGod'), '—')}</div>
                <div class="dayun-meta">地支十神：{_html_escape(branch_ten_gods or '—')}</div>
            </div>
        """)
    summary_parts = []
    if dayun.get("startDate"):
        summary_parts.append(f"起运日期 {dayun.get('startDate')}")
    if dayun.get("startAge"):
        summary_parts.append(f"起运年龄 {dayun.get('startAge')}岁")
    summary = " · ".join(summary_parts) or "已根据命盘生成十年大运"
    return f"""
        <section class="panel dayun-panel">
            <div class="section-head">
                <div>
                    <h2>大运流转</h2>
                    <p>{_html_escape(summary)}</p>
                </div>
                <span class="current-badge">{_html_escape(current_text)}</span>
            </div>
            <div class="dayun-list">{''.join(cards)}</div>
        </section>
    """


def _build_relations_html(chart: Dict[str, Any]) -> str:
    relations = chart.get("relations") if isinstance(chart.get("relations"), dict) else {}
    lines = []
    for pillar_key in ["年", "月", "日", "时"]:
        pillar_payload = relations.get(pillar_key)
        if not isinstance(pillar_payload, dict):
            continue
        for area in ["天干", "地支"]:
            area_payload = pillar_payload.get(area)
            if not isinstance(area_payload, dict):
                continue
            for relation_name, relation_items in area_payload.items():
                items = relation_items if isinstance(relation_items, list) else [relation_items]
                for item in items:
                    if isinstance(item, dict):
                        pieces = [
                            f"关联{item.get('柱')}" if item.get("柱") else "",
                            str(item.get("知识点") or ""),
                            f"元素{item.get('元素')}" if item.get("元素") else "",
                        ]
                        detail = "，".join(piece for piece in pieces if piece)
                    else:
                        detail = str(item)
                    if detail:
                        lines.append(f"{pillar_key}柱 {area} {relation_name}：{detail}")
    if not lines:
        return ""
    items = "".join(f"<li>{_html_escape(line)}</li>" for line in lines)
    return f"""
        <section class="panel">
            <h2>刑冲合会</h2>
            <ul class="relations">{items}</ul>
        </section>
    """


def _build_report_html(report_data: Dict[str, Any]) -> str:
    user = report_data.get("userInfo") or {}
    bazi = report_data.get("baziInfo") or {}
    chart = bazi.get("chartDetails") if isinstance(bazi.get("chartDetails"), dict) else {}
    analyses = report_data.get("analysisResults") or []
    followups = report_data.get("followUpResults") or []
    name = user.get("name") or "用户"
    avatar = str(name)[0] if name else "命"
    gender = user.get("gender") or "—"
    birth = user.get("birthTime") or user.get("birthDate") or "—"
    zodiac = bazi.get("zodiac") or ((chart.get("meta") or {}).get("zodiac") if isinstance(chart.get("meta"), dict) else "") or "—"

    analysis_cards = []
    for index, analysis in enumerate(analyses, 1):
        title = f"{index}. {analysis.get('dimension') or '分析'}"
        version = analysis.get("version")
        timestamp = analysis.get("timestamp")
        meta = " · ".join(str(item) for item in [version, timestamp] if item)
        analysis_cards.append(f"""
            <section class="analysis-card">
                <h2>{_html_escape(title)}</h2>
                {f'<div class="card-meta">{_html_escape(meta)}</div>' if meta else ''}
                <div class="analysis-content">{_simple_markdown_to_html(analysis.get('content'))}</div>
            </section>
        """)

    followup_cards = []
    for index, followup in enumerate(followups, 1):
        title = f"{index}. {followup.get('dimension') or '追问'}：{followup.get('question') or '追问'}"
        timestamp = followup.get("timestamp")
        followup_cards.append(f"""
            <section class="analysis-card followup">
                <h2>{_html_escape(title)}</h2>
                {f'<div class="card-meta">{_html_escape(timestamp)}</div>' if timestamp else ''}
                <div class="analysis-content">{_simple_markdown_to_html(followup.get('content'))}</div>
            </section>
        """)

    chart_extra = chart.get("extra") if isinstance(chart.get("extra"), dict) else {}
    extra_html = "".join(
        f'<span>{_html_escape(label)}：{_html_escape(value, "—")}</span>'
        for label, value in chart_extra.items()
        if value not in (None, "", [], {})
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
@page {{ size: A4; margin: 10mm; }}
* {{ box-sizing: border-box; }}
body {{
    margin: 0;
    background: #f7f1e8;
    color: #111827;
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans SC", Arial, sans-serif;
    font-size: 12px;
    line-height: 1.55;
}}
.page {{ width: 100%; }}
.profile-card, .panel, .analysis-card {{
    background: #fffdf8;
    border: 1px solid #eadfcd;
    border-radius: 10px;
    padding: 18px;
    margin: 0 0 14px;
    break-inside: avoid;
}}
.profile-header {{
    display: flex;
    align-items: center;
    gap: 16px;
    padding-bottom: 14px;
    border-bottom: 1px solid #eadfcd;
    margin-bottom: 14px;
}}
.avatar {{
    width: 52px;
    height: 52px;
    border-radius: 50%;
    background: #f3dfab;
    color: #d4382a;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 26px;
    font-weight: 700;
}}
h1 {{ margin: 0 0 4px; font-size: 20px; line-height: 1.25; }}
.profile-meta, .card-meta, .muted {{ color: #6b7280; }}
.meta-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin-bottom: 14px;
}}
.meta-item {{
    background: #fffaf2;
    border: 1px solid #eadfcd;
    border-radius: 8px;
    padding: 10px 12px;
}}
.meta-label {{ color: #7c8794; font-weight: 700; font-size: 11px; }}
.meta-value {{ margin-top: 4px; font-weight: 700; font-size: 13px; }}
.extra-line {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px 18px;
    color: #7a4c00;
    margin: -2px 0 12px;
}}
.bazi-table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    border: 1px solid #eadfcd;
    border-radius: 9px;
    overflow: hidden;
    margin-top: 6px;
}}
.bazi-table th, .bazi-table td {{
    border-right: 1px solid #eadfcd;
    border-bottom: 1px solid #eadfcd;
    padding: 10px 8px;
    text-align: center;
    vertical-align: middle;
}}
.bazi-table tr:last-child th, .bazi-table tr:last-child td {{ border-bottom: 0; }}
.bazi-table th:last-child, .bazi-table td:last-child {{ border-right: 0; }}
.bazi-table thead th, .bazi-table tbody th {{
    background: #f8f2e7;
    color: #6b7280;
    font-weight: 700;
}}
.row-label {{ width: 64px; }}
.gz {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 34px;
    height: 34px;
    border-radius: 8px;
    font-size: 25px;
    font-weight: 800;
    line-height: 1;
    border: 1px solid currentColor;
    background: #fff7df;
}}
.wood {{ color: #0b8d64; background-color: #e8f7ef; }}
.fire {{ color: #e14b2f; background-color: #fff0e8; }}
.earth {{ color: #a96d00; background-color: #fff7df; }}
.metal {{ color: #c07a00; background-color: #fff8e8; }}
.water {{ color: #0969b7; background-color: #eaf5ff; }}
.hidden-item, .stack-item {{
    display: block;
    margin: 2px 0;
    white-space: nowrap;
}}
.hidden-char {{ font-weight: 800; margin-right: 4px; }}
.hidden-god {{ color: #374151; }}
.gold {{ color: #9a6300; font-weight: 700; white-space: normal; }}
.section-head {{
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    margin-bottom: 12px;
}}
h2 {{ margin: 0 0 6px; color: #d4382a; font-size: 16px; }}
.section-head p {{ margin: 0; color: #6b7280; }}
.current-badge {{
    border: 1px solid #eadfcd;
    border-radius: 999px;
    padding: 5px 12px;
    background: #fff;
    font-weight: 700;
    color: #374151;
    white-space: nowrap;
}}
.dayun-list {{
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 10px;
}}
.dayun-card {{
    border: 1px solid #eadfcd;
    border-radius: 8px;
    background: #fffaf2;
    padding: 10px;
    min-height: 116px;
    break-inside: avoid;
}}
.dayun-card.current {{ border-color: #d89b14; box-shadow: inset 0 0 0 1px #d89b14; }}
.dayun-range {{ color: #7c8794; font-weight: 700; font-size: 11px; }}
.dayun-gz {{ margin: 8px 0; display: flex; gap: 4px; }}
.dayun-gz .gz {{ min-width: 27px; height: 27px; font-size: 19px; }}
.dayun-age, .dayun-meta {{ font-size: 11px; margin-top: 3px; }}
.relations {{ margin: 0; padding-left: 18px; }}
.relations li {{ margin: 4px 0; }}
.analysis-card {{ padding: 16px 18px; break-inside: auto; }}
.analysis-card h2 {{ color: #b83229; }}
.analysis-content h4 {{
    color: #b8860b;
    font-size: 14px;
    margin: 12px 0 5px;
}}
.analysis-content p {{ margin: 7px 0; text-align: justify; }}
.analysis-content .bullet {{ padding-left: 14px; position: relative; }}
.analysis-content .bullet::before {{ content: "•"; position: absolute; left: 0; color: #b8860b; }}
blockquote {{
    margin: 8px 0;
    padding: 8px 10px;
    border-left: 3px solid #b8860b;
    background: #fff7e6;
    color: #4b5563;
}}
.report-footer {{
    color: #6b7280;
    font-size: 11px;
    text-align: center;
    margin-top: 18px;
}}
@media print {{
    .analysis-card, .panel, .profile-card {{ page-break-inside: avoid; }}
    .analysis-content {{ page-break-inside: auto; }}
}}
</style>
</head>
<body>
<main class="page">
    <section class="profile-card">
        <div class="profile-header">
            <div class="avatar">{_html_escape(avatar)}</div>
            <div>
                <h1>{_html_escape(name)}的命理分析</h1>
                <div class="profile-meta">{_html_escape(gender)} · {_html_escape(birth)} · {_html_escape(zodiac)}年</div>
            </div>
        </div>
        {_build_bazi_plate_html(chart, bazi, user)}
        {f'<div class="extra-line">{extra_html}</div>' if extra_html else ''}
    </section>
    {_build_dayun_html(chart)}
    {_build_relations_html(chart)}
    <section class="panel">
        <h2>详细分析结果</h2>
        <p class="muted">共 {_html_escape(len(analyses))} 个维度</p>
    </section>
    {''.join(analysis_cards)}
    {f'<section class="panel"><h2>追问记录</h2><p class="muted">共 {len(followups)} 条</p></section>' if followups else ''}
    {''.join(followup_cards)}
    <div class="report-footer">生成时间：{_html_escape(report_data.get('generatedTime') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}</div>
</main>
</body>
</html>"""


def build_html_pdf_report(report_data: Dict[str, Any]) -> bytes:
    return _html_to_pdf_bytes(_build_report_html(report_data))


def build_pdf_report(report_data: Dict[str, Any]) -> bytes:
    if os.getenv("PDF_RENDERER", "html").lower() != "reportlab":
        try:
            return build_html_pdf_report(report_data)
        except Exception:
            if os.getenv("PDF_RENDERER", "html").lower() == "html":
                raise

    font_name, bold_font = register_chinese_fonts()
    styles = _styles(font_name, bold_font)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        title="八字命理深度分析报告",
        author="Bazi AI",
    )

    user = report_data.get("userInfo") or {}
    bazi = report_data.get("baziInfo") or {}
    analyses = report_data.get("analysisResults") or []
    followups = report_data.get("followUpResults") or []

    story: List[Any] = [
        Paragraph("八字命理深度分析报告", styles["title"]),
        Paragraph("AI 智能分析 · 高清矢量版 PDF（非截图）", styles["subtitle"]),
        HRFlowable(width="100%", thickness=1, color=PRIMARY_COLOR, spaceBefore=4, spaceAfter=12),
        Paragraph("用户基本信息", styles["section"]),
        _info_table(
            [
                ("姓名", user.get("name")),
                ("性别", user.get("gender")),
                ("出生日期", user.get("birthDate")),
                ("出生时间", user.get("birthTime")),
            ],
            font_name,
            bold_font,
        ),
        Spacer(1, 8),
        Paragraph("八字排盘信息", styles["section"]),
        _info_table(
            [
                ("八字", bazi.get("bazi")),
                ("阳历", bazi.get("solarDate")),
                ("农历", bazi.get("lunarDate")),
                ("生肖", bazi.get("zodiac")),
                ("日主", bazi.get("dayMaster")),
            ],
            font_name,
            bold_font,
        ),
        Spacer(1, 10),
    ]

    _append_chart_details(story, bazi, styles, font_name, bold_font)

    story.extend([
        Spacer(1, 10),
        Paragraph(f"详细分析结果（共 {len(analyses)} 个维度）", styles["section"]),
    ])

    for index, analysis in enumerate(analyses, 1):
        dimension = _safe_text(analysis.get("dimension"), f"分析维度 {index}")
        version = _safe_text(analysis.get("version"), "")
        title = f"{index}. {dimension}" + (f"（{version}）" if version else "")
        story.append(Paragraph(_escape(title), styles["analysis_title"]))

        timestamp = _safe_text(analysis.get("timestamp"), "")
        if timestamp:
            story.append(Paragraph(f"分析时间：{_escape(timestamp)}", styles["small"]))
            story.append(Spacer(1, 3))

        blocks = _strip_html_and_markdown(str(analysis.get("content") or ""))
        if not blocks:
            story.append(Paragraph("暂无有效分析内容。", styles["body"]))
            continue

        for block_type, text in blocks:
            if block_type == "heading":
                story.append(Paragraph(_escape(text), styles["heading"]))
            elif block_type == "bullet":
                story.append(Paragraph(_escape(text), styles["bullet"], bulletText="•"))
            elif block_type == "quote":
                story.append(Paragraph(_escape(text), styles["quote"]))
            else:
                story.append(Paragraph(_escape(text), styles["body"]))

    if followups:
        story.extend([
            Spacer(1, 12),
            Paragraph(f"追问记录（共 {len(followups)} 条）", styles["section"]),
        ])
        for index, followup in enumerate(followups, 1):
            dimension = _safe_text(followup.get("dimension"), "未知维度")
            question = _safe_text(followup.get("question"), "追问")
            title = f"{index}. {dimension}：{question}"
            story.append(Paragraph(_escape(title), styles["analysis_title"]))

            timestamp = _safe_text(followup.get("timestamp"), "")
            if timestamp:
                story.append(Paragraph(f"追问时间：{_escape(timestamp)}", styles["small"]))
                story.append(Spacer(1, 3))

            blocks = _strip_html_and_markdown(str(followup.get("content") or ""))
            if not blocks:
                story.append(Paragraph("暂无有效追问内容。", styles["body"]))
                continue
            for block_type, text in blocks:
                if block_type == "heading":
                    story.append(Paragraph(_escape(text), styles["heading"]))
                elif block_type == "bullet":
                    story.append(Paragraph(_escape(text), styles["bullet"], bulletText="•"))
                elif block_type == "quote":
                    story.append(Paragraph(_escape(text), styles["quote"]))
                else:
                    story.append(Paragraph(_escape(text), styles["body"]))

    story.extend([
        Spacer(1, 14),
        HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#E7E0D6"), spaceBefore=8, spaceAfter=8),
        Paragraph("报告说明", styles["section"]),
        Paragraph(
            "本报告由本地命理分析系统根据用户八字排盘与已完成分析结果生成。内容用于自我理解、情绪支持与命理参考，不构成医学、法律、投资或其他专业决策建议。",
            styles["body"],
        ),
        Paragraph(f"生成时间：{_escape(report_data.get('generatedTime') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}", styles["small"]),
    ])

    doc.build(
        story,
        onFirstPage=lambda canvas, doc_obj: _draw_page(canvas, doc_obj, font_name),
        onLaterPages=lambda canvas, doc_obj: _draw_page(canvas, doc_obj, font_name),
    )
    return buffer.getvalue()


def make_pdf_filename(report_data: Dict[str, Any]) -> str:
    user = report_data.get("userInfo") or {}
    name = _safe_text(user.get("name"), "用户")
    name = re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "用户"
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"八字分析报告_高清矢量版_{name}_{stamp}.pdf"
