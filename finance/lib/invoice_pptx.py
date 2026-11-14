"""Build a Farrell Import invoice as .pptx from the PowerPoint template of invoice 13.

The template's service table is a set of free text boxes, not a real table. Line 1
(the fee) has its own three boxes; lines 2..n share three boxes one line lower.
The fee description is split into two paragraphs so nothing depends on font wrapping.

usage: python3 lib/invoice_pptx.py spec.json template.pptx out.pptx
spec: {"number": 15, "date": "14 de Noviembre 2026", "fee_label": "Business Development & Brand Recognition",
       "fee_sub": "October (9 days)", "fee": 1800000,
       "lines": [["Expenses – Jan (London & Madrid)", 123456], ...]}   amounts in cents
"""
from __future__ import annotations
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RPR = ('<a:rPr lang="en-US" sz="999" dirty="0"><a:solidFill><a:srgbClr val="475268"/></a:solidFill>'
       '<a:latin typeface="Glacial Indifference"/><a:ea typeface="Glacial Indifference"/>'
       '<a:cs typeface="Glacial Indifference"/><a:sym typeface="Glacial Indifference"/></a:rPr>')
BR = RPR.replace('<a:rPr', '<a:br><a:rPr').replace('</a:rPr>', '</a:rPr></a:br>')
BLANK = ('<a:p><a:pPr><a:lnSpc><a:spcPts val="1399"/></a:lnSpc></a:pPr><a:endParaRPr lang="en-US" sz="999" dirty="0">'
         '<a:solidFill><a:srgbClr val="475268"/></a:solidFill><a:latin typeface="Glacial Indifference"/>'
         '<a:ea typeface="Glacial Indifference"/><a:cs typeface="Glacial Indifference"/><a:sym typeface="Glacial Indifference"/>'
         '</a:endParaRPr></a:p>')
LINE = 4746625 - 4582002          # vertical pitch of one service line, EMU
MONTHS = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
          "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def es_amount(minor: int) -> str:
    v = abs(minor); s = f"{v // 100:,}".replace(",", ".")
    return f"{'-' if minor < 0 else ''}{s},{v % 100:02d}€"


def para(text: str, algn: str | None = None) -> str:
    ppr = f'<a:pPr{(" algn=%s%s%s" % (chr(34), algn, chr(34))) if algn else ""}><a:lnSpc><a:spcPts val="1399"/></a:lnSpc></a:pPr>'
    return f'<a:p>{ppr}<a:r>{RPR}<a:t xml:space="preserve">{html.escape(text, quote=False)}</a:t></a:r></a:p>'


class Slide:
    def __init__(self, xml: str):
        self.x = xml

    def sp(self, sid: str):
        m = re.search(r'<p:sp><p:nvSpPr><p:cNvPr id="%s" .*?</p:sp>' % sid, self.x, re.S)
        if not m:
            raise SystemExit(f"shape id {sid} not in template")
        return m

    def set_body(self, sid: str, paras: list[str]):
        blk = self.sp(sid).group(0)
        body = re.search(r'<p:txBody>(<a:bodyPr.*?</a:bodyPr>|<a:bodyPr[^>]*/>)<a:lstStyle/>.*?</p:txBody>', blk, re.S)
        self.x = self.x.replace(body.group(0), f'<p:txBody>{body.group(1)}<a:lstStyle/>{"".join(paras)}</p:txBody>', 1)

    def move(self, sid: str, dx: int = 0, dy: int = 0, cx: int | None = None, algn: str | None = None):
        blk = self.sp(sid).group(0)
        m = re.search(r'<a:off x="(\d+)" y="(\d+)"/><a:ext cx="(\d+)" cy="(\d+)"/>', blk)
        ox, oy, ocx, ocy = map(int, m.groups())
        new = blk.replace(m.group(0), f'<a:off x="{ox+dx}" y="{oy+dy}"/><a:ext cx="{cx or ocx}" cy="{ocy}"/>', 1)
        if algn:
            new = new.replace('<a:pPr algn="l">', f'<a:pPr algn="{algn}">', 1)
        self.x = self.x.replace(blk, new, 1)

    def move_group_containing(self, sid: str, dy: int):
        grp = re.search(r'<p:grpSp>(?:(?!</p:grpSp>).)*?<p:cNvPr id="%s" .*?</p:grpSp>' % sid, self.x, re.S)
        if not grp:
            return
        g = grp.group(0)
        m = re.search(r'<p:grpSpPr>.*?<a:off x="(\d+)" y="(\d+)"/>', g, re.S)
        g2 = g.replace(f'<a:off x="{m.group(1)}" y="{m.group(2)}"/>', f'<a:off x="{m.group(1)}" y="{int(m.group(2))+dy}"/>', 1)
        self.x = self.x.replace(g, g2, 1)

    def replace_text(self, old: str, new: str):
        if self.x.count(f'<a:t>{old}</a:t>') != 1:
            raise SystemExit(f"template text {old!r} not found exactly once")
        self.x = self.x.replace(f'<a:t>{old}</a:t>', f'<a:t>{new}</a:t>')


def build(spec: dict, template: Path, out: Path) -> dict:
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(template) as z:
        z.extractall(tmp)
    p = tmp / "ppt/slides/slide1.xml"
    s = Slide(p.read_text(encoding="utf-8"))
    # header
    s.replace_text("Factura: 13", f"Factura: {spec['number']}")
    s.replace_text("20 de ", spec["date"].split(" de ")[0] + " de ")
    s.replace_text("Septiembre", spec["date"].split(" de ")[1].split(" ")[0])
    s.replace_text(" 2026", " " + spec["date"].split(" ")[-1])
    # service lines
    lines = spec["lines"]
    descs = [para(spec["fee_label"], "l"), para(spec["fee_sub"])] + [para(d) for d, _ in lines]
    approve = ('<a:p><a:pPr algn="l"><a:lnSpc><a:spcPts val="1399"/></a:lnSpc></a:pPr><a:r>' + RPR +
               '<a:t xml:space="preserve">     To be approved by: Kevin Gillan</a:t></a:r></a:p>')
    s.set_body("27", descs + [BLANK, approve])
    amts = [es_amount(m) for _, m in lines]
    s.set_body("44", ['<a:p><a:pPr algn="l"><a:lnSpc><a:spcPts val="1399"/></a:lnSpc></a:pPr>' +
                      BR.join(f'<a:r>{RPR}<a:t>{a}</a:t></a:r>' for a in amts) + '</a:p>'])
    s.set_body("45", [para("1") for _ in amts])
    s.set_body("46", [para(a, "r") for a in amts])
    for sid in ("44", "45", "46"):
        s.move(sid, dy=LINE)               # one line lower: the fee now takes two paragraphs
    s.move("28", cx=800000); s.move("44", cx=800000)
    s.move("38", dx=-200000, cx=641626 + 200000, algn="r")
    # fee amount boxes
    fee = es_amount(spec["fee"])
    s.x = s.x.replace('<a:t>18.000,00€</a:t>', f'<a:t>{fee}</a:t>')
    # push the rule and totals down for every line beyond the template's three visual lines
    extra = max(0, (2 + len(lines)) - 3)
    down = extra * LINE + 40000
    for sid in ("13", "30", "31"):
        s.move(sid, dy=down)
    s.move_group_containing("17", down)
    total = spec["fee"] + sum(m for _, m in lines)
    s.replace_text("Subtotal:\t23.921,20€", f"Subtotal:\t{es_amount(total)}")
    s.replace_text("23.921,20€", es_amount(total))
    p.write_text(s.x, encoding="utf-8")
    out = Path(out)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(tmp.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(tmp).as_posix())
    shutil.rmtree(tmp)
    return {"number": spec["number"], "fee": spec["fee"], "lines": lines, "total": total}


if __name__ == "__main__":
    spec_path, template, out = sys.argv[1:4]
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    print(build(spec, Path(template), Path(out)))
