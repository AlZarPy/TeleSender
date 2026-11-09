"""Сборка DOCX без внешних библиотек: минимальный, но валидный OOXML.

Зачем свой сборщик: python-docx в окружении нет, pandoc тоже, а отчёт нужен сейчас.
Формат docx — это zip с XML; для отчёта достаточно document.xml, styles.xml и
служебных файлов. Форматирование задаём прямо в runs (жирный, размер, цвет).
"""
from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

A4_W, A4_H = 11906, 16838  # A4 в twips
MARGIN = 1134               # ~2 см


def _run(text: str, bold: bool = False, size: int = 21, color: str | None = None,
         italic: bool = False) -> str:
    props = [f'<w:sz w:val="{size}"/>', f'<w:szCs w:val="{size}"/>']
    if bold:
        props.append("<w:b/>")
    if italic:
        props.append("<w:i/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    return (f'<w:r><w:rPr>{"".join(props)}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(text)}</w:t></w:r>')


def para(text: str = "", bold: bool = False, size: int = 21, space_after: int = 120,
         align: str = "left", color: str | None = None, italic: bool = False) -> str:
    return (f'<w:p><w:pPr><w:spacing w:after="{space_after}" w:line="276" w:lineRule="auto"/>'
            f'<w:jc w:val="{align}"/></w:pPr>{_run(text, bold, size, color, italic)}</w:p>')


def heading(text: str, size: int = 28) -> str:
    return (f'<w:p><w:pPr><w:spacing w:before="240" w:after="120"/>'
            f'<w:pBdr><w:bottom w:val="dashed" w:sz="6" w:space="2" w:color="B9A483"/></w:pBdr>'
            f'</w:pPr>{_run(text.upper(), True, size)}</w:p>')


def table(rows: list[list[str]], widths: list[int] | None = None,
          header: bool = True) -> str:
    columns = len(rows[0])
    widths = widths or [int((A4_W - 2 * MARGIN) / columns)] * columns
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)

    out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
           f'<w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
           '<w:tblBorders>'
           '<w:top w:val="single" w:sz="4" w:color="B9A483"/>'
           '<w:bottom w:val="single" w:sz="4" w:color="B9A483"/>'
           '<w:insideH w:val="single" w:sz="2" w:color="D3C3A7"/>'
           '<w:left w:val="none" w:sz="0"/><w:right w:val="none" w:sz="0"/>'
           '<w:insideV w:val="none" w:sz="0"/>'
           '</w:tblBorders></w:tblPr>'
           f'<w:tblGrid>{grid}</w:tblGrid>']

    for index, row in enumerate(rows):
        is_head = header and index == 0
        out.append("<w:tr>")
        if is_head:
            out.append("<w:trPr><w:tblHeader/></w:trPr>")
        for cell, width in zip(row, widths):
            shade = '<w:shd w:val="clear" w:fill="ECE2CF"/>' if is_head else ""
            text = escape(cell)
            out.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                f'<w:p><w:pPr><w:spacing w:after="40" w:line="240" w:lineRule="auto"/></w:pPr>'
                f'{_run(cell, bold=is_head, size=19)}</w:p></w:tc>'
            )
        out.append("</w:tr>")
    out.append("</w:tbl>")
    out.append(para("", space_after=0))
    return "".join(out)


def page_break() -> str:
    return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="Georgia" w:hAnsi="Georgia" w:cs="Georgia"/>
<w:sz w:val="21"/><w:szCs w:val="21"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/>
<w:tblPr><w:tblCellMar><w:left w:w="80" w:type="dxa"/><w:right w:w="80" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
</w:styles>"""


def build(path: str, body: str, title: str, subject: str = "") -> None:
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + body
        + '<w:sectPr><w:pgSz w:w="%d" w:h="%d"/>' % (A4_W, A4_H)
        + '<w:pgMar w:top="%d" w:right="%d" w:bottom="%d" w:left="%d" w:header="720" w:footer="720" w:gutter="0"/>'
        % (MARGIN, MARGIN, MARGIN, MARGIN)
        + "</w:sectPr></w:body></w:document>"
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title)}</dc:title><dc:subject>{escape(subject)}</dc:subject>"
        "<dc:creator>TheПечкин · Почтамт</dc:creator>"
        "</cp:coreProperties>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/styles.xml", STYLES)
        z.writestr("word/document.xml", document)
        z.writestr("docProps/core.xml", core)
