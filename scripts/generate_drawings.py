#!/usr/bin/env python3
"""Generate A0 board + A3 booklet drawing PDFs for a submission package.

Data-driven: reads metrics.json, proposal.md front matter, and geometry/*.geojson
from the target submission directory, then produces:

  drawings/a0-boards.pdf   — one landscape A0 board (title, scope, metrics,
                             key areas, layer stats, provisional notice)
  drawings/a3-booklet.pdf  — A3 portrait booklet (cover + scope/metrics +
                             key areas + implementation/AI scenarios +
                             data/assumptions/risk)

Replaces scaffold placeholder PDFs. Run after finalizing content:

    python3 scripts/generate_drawings.py submissions/test/test
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A0, A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

CJK_FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]
LATIN_FONT = "Helvetica"

ACCENT = colors.HexColor("#1a1a2e")
RED = colors.HexColor("#e94560")
MUTED = colors.HexColor("#667085")
LINE = colors.HexColor("#d7dee8")
BG = colors.HexColor("#f4f7fa")


def register_fonts() -> str:
    for path in CJK_FONT_CANDIDATES:
        name = f"CJK-{Path(path).stem.replace(' ', '')}"
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
            return name
        except Exception:
            continue
    print("warning: no CJK font found; Chinese text will not render", file=sys.stderr)
    return LATIN_FONT


def fmt_sqm(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v:,.0f} m²"


def fmt_ha(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v / 1e4:,.1f} 公顷"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def proposal_title(summary_dir: Path) -> str:
    text = summary_dir.joinpath("proposal.md").read_text(encoding="utf-8")
    m = re.search(r"(?m)^title:\s*[\"']?(.+?)[\"']?\s*$", text)
    return m.group(1).strip() if m else summary_dir.name


def collect_metrics(submission: Path) -> dict:
    metrics = load_json(submission / "metrics.json").get("metrics", {})
    wanted = [
        "site_area_sqm",
        "coordinated_research_area_sqm",
        "key_detailed_design_area_sqm",
        "building_footprint_area_sqm",
        "green_space_area_sqm",
        "public_space_area_sqm",
        "green_ratio",
        "public_space_ratio",
        "key_area_count",
        "zhongzhiyuan_ai_acceleration_area_sqm",
        "beijing_ai_origin_community_area_sqm",
        "dazhongsi_ai_industry_cluster_area_sqm",
    ]
    out: dict[str, dict] = {}
    for name in wanted:
        m = metrics.get(name)
        if isinstance(m, dict):
            out[name] = m
    return out


def collect_layer_stats(submission: Path) -> list[tuple[str, int]]:
    stats: list[tuple[str, int]] = []
    for f in sorted((submission / "geometry").glob("*.geojson")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            n = len(data.get("features", []))
        except Exception:
            n = -1
        stats.append((f.name, n))
    return stats


def build_styles(cjk: str) -> dict:
    return {
        "title": ParagraphStyle("title", fontName=cjk, fontSize=30, leading=36,
                                textColor=ACCENT, spaceAfter=4 * mm),
        "subtitle": ParagraphStyle("subtitle", fontName=cjk, fontSize=13, leading=18,
                                   textColor=MUTED),
        "h2": ParagraphStyle("h2", fontName=cjk, fontSize=17, leading=22,
                             textColor=ACCENT, spaceBefore=8 * mm, spaceAfter=4 * mm),
        "h3": ParagraphStyle("h3", fontName=cjk, fontSize=13, leading=17,
                             textColor=RED, spaceBefore=5 * mm, spaceAfter=2 * mm),
        "body": ParagraphStyle("body", fontName=cjk, fontSize=10.5, leading=15,
                               textColor=colors.HexColor("#333333")),
        "small": ParagraphStyle("small", fontName=cjk, fontSize=8.5, leading=12,
                                textColor=MUTED),
        "cell": ParagraphStyle("cell", fontName=cjk, fontSize=10, leading=14),
        "cellb": ParagraphStyle("cellb", fontName=cjk, fontSize=10, leading=14,
                                fontName2=cjk, textColor=ACCENT),
    }


def metric_table(metrics: dict, styles: dict) -> Table:
    rows = [["指标", "数值", "说明"]]
    labels = {
        "site_area_sqm": "总体设计范围面积",
        "coordinated_research_area_sqm": "统筹研究范围面积",
        "key_detailed_design_area_sqm": "重点区域面积",
        "building_footprint_area_sqm": "建筑基底面积",
        "green_space_area_sqm": "绿地面积",
        "public_space_area_sqm": "公共空间面积",
        "green_ratio": "绿地率",
        "public_space_ratio": "公共空间率",
        "key_area_count": "重点区域数量",
    }
    for name, m in metrics.items():
        if name not in labels:
            continue
        if name.endswith("_ratio"):
            value = f"{m.get('value') or 0:.4f}"
        elif name.endswith("_count"):
            value = str(m.get("value"))
        else:
            value = fmt_sqm(m.get("value"))
        note = m.get("status", "")
        rows.append([Paragraph(labels[name], styles["cell"]),
                     Paragraph(value, styles["cell"]),
                     Paragraph(note, styles["cell"])])
    t = Table(rows, colWidths=[70 * mm, 50 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTNAME", (0, 0), (-1, 0), styles["cell"].fontName),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
    ]))
    return t


def key_area_table(metrics: dict, styles: dict) -> Table:
    rows = [["重点片区", "面积", "定位"]]
    areas = [
        ("zhongzhiyuan_ai_acceleration_area_sqm", "众智园AI自主创新加速区", "花园型全栈自主创新街区"),
        ("beijing_ai_origin_community_area_sqm", "北京AI原点社区", "近校型成果转化与人才社区"),
        ("dazhongsi_ai_industry_cluster_area_sqm", "大钟寺AI产业聚集区", "城市型智能经济与国际交往街区"),
    ]
    for key, name_zh, desc in areas:
        m = metrics.get(key)
        rows.append([Paragraph(name_zh, styles["cell"]),
                     Paragraph(fmt_sqm(m.get("value")) if m else "—", styles["cell"]),
                     Paragraph(desc, styles["cell"])])
    t = Table(rows, colWidths=[55 * mm, 45 * mm, 50 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), RED),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BG]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def draw_site_plan(submission: Path, cjk: str = "Helvetica") -> Drawing:
    """Vector schematic site plan: site bbox, key areas, blue-green corridors,
    roads, north arrow, scale bar and legend.

    Provisional boundaries are rendered as dashed, low-contrast outlines with
    a watermark (per formal-submission-guide.md); CJK font is applied to all
    text; scale bar is corrected for cos(mid_lat)."""
    import math
    W, H = 700, 430
    d = Drawing(W, H)
    # collect geometries (EPSG:4326 lon/lat)
    geoms: dict[str, list[list[tuple[float, float]]]] = {}
    for gf in sorted((submission / "geometry").glob("*.geojson")):
        try:
            data = json.loads(gf.read_text(encoding="utf-8"))
        except Exception:
            continue
        polys: list[list[tuple[float, float]]] = []
        for f in data.get("features", []):
            g = f.get("geometry", {})
            if g.get("type") == "Polygon":
                polys.append([tuple(c) for c in g["coordinates"][0]])
            elif g.get("type") == "LineString":
                pts = [tuple(c) for c in g["coordinates"]]
                polys.append(pts)  # rendered as thick line below
        if polys:
            geoms[gf.name] = polys
    site = geoms.get("site_boundary.geojson")
    if not site:
        return d
    lons = [p[0] for ring in site for p in ring]
    lats = [p[1] for ring in site for p in ring]
    minx, maxx, miny, maxy = min(lons), max(lons), min(lats), max(lats)
    mid_lat = (miny + maxy) / 2.0
    pad_x, pad_y = (maxx - minx) * 0.03, (maxy - miny) * 0.03
    minx -= pad_x; maxx += pad_x; miny -= pad_y; maxy += pad_y

    def px(x: float, y: float) -> tuple[float, float]:
        return ((x - minx) / (maxx - minx) * (W - 60) + 30,
                (y - miny) / (maxy - miny) * (H - 80) + 40)

    # site base: provisional -> dashed, low-contrast outline + light fill
    ring = [px(x, y) for x, y in site[0]]
    d.add(Polygon([c for pt in ring for c in pt], strokeColor=colors.HexColor("#e94560aa"),
                  strokeWidth=1.4, fillColor=BG, strokeDash=[5, 4]))
    # key areas (soft red fills)
    for polys in geoms.get("key_areas.geojson", []):
        pts = [px(x, y) for x, y in polys]
        d.add(Polygon([c for pt in pts for c in pt], strokeColor=RED, strokeWidth=1.0,
                      fillColor=colors.HexColor("#e9456033")))
    # green / public (soft fills)
    for key, fill in (("green_space.geojson", "#2f9e4433"),
                      ("public_space.geojson", "#2f6fe433"),
                      ("land_use.geojson", "#f2c14e22")):
        for polys in geoms.get(key, []):
            pts = [px(x, y) for x, y in polys]
            d.add(Polygon([c for pt in pts for c in pt], strokeColor=colors.HexColor("#999999"),
                          strokeWidth=0.6, fillColor=colors.HexColor(fill)))
    # corridors / roads (thick lines)
    for key, color in (("constraints.geojson", "#8d5524"),
                       ("roads.geojson", "#555555")):
        for poly in geoms.get(key, []):
            pts = [px(x, y) for x, y in poly]
            for a, b in zip(pts, pts[1:]):
                d.add(Line(a[0], a[1], b[0], b[1], strokeColor=colors.HexColor(color),
                           strokeWidth=2.5 if key == "constraints.geojson" else 1.6))
    # north arrow
    d.add(Line(W - 50, H - 70, W - 50, H - 45, strokeColor=ACCENT, strokeWidth=2))
    d.add(Polygon([W - 50, H - 40, W - 53, H - 47, W - 47, H - 47],
                  strokeColor=ACCENT, strokeWidth=0.5, fillColor=RED))
    d.add(String(W - 50, H - 40, "N", fontName="Helvetica-Bold", fontSize=12,
                 fillColor=ACCENT, textAnchor="middle"))
    # scale bar (1 km, corrected for cos(mid_lat))
    km = 1.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(mid_lat))
    scale_len = (W - 60) * (km * 1000) / ((maxx - minx) * m_per_deg_lon)
    y0 = 26
    d.add(Line(30, y0, 30 + scale_len, y0, strokeColor=ACCENT, strokeWidth=2))
    d.add(Line(30, y0 - 3, 30, y0 + 3, strokeColor=ACCENT, strokeWidth=2))
    d.add(Line(30 + scale_len, y0 - 3, 30 + scale_len, y0 + 3, strokeColor=ACCENT, strokeWidth=2))
    d.add(String(30 + scale_len / 2, y0 - 10, "≈ 1 km", fontName=cjk, fontSize=9,
                 fillColor=MUTED, textAnchor="middle"))
    d.add(String(30, H - 18, "示意平面（provisional 几何，非精确控制图；底图参考：天地图 1:100万公众版）",
                 fontName=cjk, fontSize=8, fillColor=MUTED, textAnchor="start"))
    # watermark
    d.add(String(W / 2, H / 2, "PROVISIONAL", fontName="Helvetica-Bold", fontSize=30,
                 fillColor=colors.HexColor("#e9456018"), textAnchor="middle"))
    # legend
    lx0, ly1 = W - 150, 150
    lw, lh = 128, 128
    d.add(Rect(lx0, ly1 - lh, lw, lh, strokeColor=LINE, fillColor=colors.white))
    d.add(String(lx0 + 8, ly1 - 10, "图例", fontName=cjk, fontSize=9,
                 fillColor=ACCENT, textAnchor="start"))
    legend_items = [
        ("#e9456033", "重点区域", True),
        ("#2f9e4433", "绿地", True),
        ("#2f6fe433", "公共空间", True),
        ("#f2c14e22", "用地分区", True),
        ("#555555", "道路（示意）", False),
        ("#8d5524", "约束廊道（示意）", False),
    ]
    y = ly1 - 26
    for color, label, is_fill in legend_items:
        if is_fill:
            d.add(Rect(lx0 + 8, y - 8, 14, 10, strokeColor=colors.HexColor("#999999"),
                       fillColor=colors.HexColor(color)))
        else:
            d.add(Line(lx0 + 8, y - 3, lx0 + 22, y - 3, strokeColor=colors.HexColor(color),
                       strokeWidth=2))
        d.add(String(lx0 + 28, y - 4, label, fontName=cjk, fontSize=8,
                     fillColor=colors.HexColor("#333333"), textAnchor="start"))
        y -= 17
    return d


def make_a0(submission: Path, title: str, metrics: dict, styles: dict, cjk: str) -> list:
    story = []
    story.append(Paragraph(title, styles["title"]))
    story.append(Paragraph("城市设计数据看板 · 概念方案（provisional）", styles["subtitle"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph("空间结构示意", styles["h2"]))
    story.append(draw_site_plan(submission, cjk))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("三层范围", styles["h2"]))
    scope = [
        ["范围层级", "面积"],
        ["统筹研究范围", fmt_sqm(metrics.get("coordinated_research_area_sqm", {}).get("value"))],
        ["总体设计范围", fmt_sqm(metrics.get("site_area_sqm", {}).get("value"))],
        ["重点区域范围", fmt_sqm(metrics.get("key_detailed_design_area_sqm", {}).get("value"))],
    ]
    st = Table(scope, colWidths=[70 * mm, 70 * mm])
    st.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(st)
    story.append(Paragraph("核心指标", styles["h2"]))
    story.append(metric_table(metrics, styles))
    story.append(Paragraph("重点区域", styles["h2"]))
    story.append(key_area_table(metrics, styles))
    story.append(Paragraph("图层构成（geometry/*.geojson 要素数）", styles["h2"]))
    layer_rows = [["图层文件", "要素数"]]
    for name, count in collect_layer_stats(submission):
        layer_rows.append([name, str(count if count >= 0 else "?" )])
    lt = Table(layer_rows, colWidths=[100 * mm, 40 * mm])
    lt.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(lt)
    story.append(Spacer(1, 8 * mm))
    story.append(Paragraph(
        "声明：本图纸基于 provisional boundary 与 agent 生成几何，仅供设计讨论与展示，"
        "不得作为 official redline、审批依据或精确面积依据；正式控制与边界以官方批复为准。",
        styles["small"]))
    story.append(Paragraph(
        f"生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | 包：{submission}",
        styles["small"]))
    return story


def make_a3(submission: Path, title: str, metrics: dict, styles: dict, cjk: str) -> list:
    story = []
    # 封面
    story.append(Spacer(1, 40 * mm))
    story.append(Paragraph(title, styles["title"]))
    story.append(Paragraph("概念方案文册 · 三层范围 / 重点区域 / 实施与数据说明", styles["subtitle"]))
    story.append(Spacer(1, 20 * mm))
    story.append(Paragraph("（本页为封面；后续页为内容摘要）", styles["small"]))
    story.append(PageBreak())
    # 范围与指标
    story.append(Paragraph("1 范围与核心指标", styles["h2"]))
    story.append(Paragraph(
        f"统筹研究范围 {fmt_sqm(metrics.get('coordinated_research_area_sqm', {}).get('value'))}；"
        f"总体设计范围 {fmt_sqm(metrics.get('site_area_sqm', {}).get('value'))}；"
        f"重点区域 {fmt_sqm(metrics.get('key_detailed_design_area_sqm', {}).get('value'))}，"
        f"共 {metrics.get('key_area_count', {}).get('value', '—')} 处重点片区。",
        styles["body"]))
    story.append(Spacer(1, 4 * mm))
    story.append(draw_site_plan(submission, cjk))
    story.append(Spacer(1, 4 * mm))
    story.append(metric_table(metrics, styles))
    story.append(PageBreak())
    # 重点区域
    story.append(Paragraph("2 重点区域", styles["h2"]))
    story.append(key_area_table(metrics, styles))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(
        "三个片区分别承担自主创新加速、成果转化与人才社区、智能经济与国际交往职能，"
        "围绕京张遗址走廊与清河-小月河蓝绿廊道组织空间与慢行联系。",
        styles["body"]))
    story.append(PageBreak())
    # 实施与 AI 场景
    story.append(Paragraph("3 实施路径与 AI 场景", styles["h2"]))
    story.append(Paragraph(
        "实施方案按近期试点、中期更新与长期治理分阶段推进；AI 场景覆盖自主模型测试、"
        "标准制定工作坊、安全治理展示、低碳算力体验、开源社区、成果发布、人才特区服务与"
        "近校孵化等方向，全部场景须落位到具体图层与指标（见 compliance_matrix.json）。",
        styles["body"]))
    story.append(PageBreak())
    # 数据与风险
    story.append(Paragraph("4 数据、假设与风险", styles["h2"]))
    story.append(Paragraph(
        "边界与重点区为 provisional（assumptions.json A-BOUNDARY-001）；控规强度、红线、"
        "权属、市政与工程条件待专业确认（A-CONTROLS-001/002）。正式控制条件发布后需重算"
        "全部图层与指标。图纸为数据驱动的概念表达，不构成法定成果。",
        styles["body"]))
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        f"生成时间：{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | 包：{submission}",
        styles["small"]))
    return story


def build(submission: Path) -> None:
    cjk = register_fonts()
    styles = build_styles(cjk)
    title = proposal_title(submission)
    metrics = collect_metrics(submission)
    drawings = submission / "drawings"
    drawings.mkdir(parents=True, exist_ok=True)

    a0_path = drawings / "a0-boards.pdf"
    a0 = BaseDocTemplate(str(a0_path), pagesize=landscape(A0),
                         leftMargin=20 * mm, rightMargin=20 * mm,
                         topMargin=18 * mm, bottomMargin=18 * mm,
                         title=f"{title} - A0 展板", author="goal-driven-agent")
    a0.addPageTemplates([PageTemplate(id="a0", frames=[
        Frame(20 * mm, 18 * mm, landscape(A0)[0] - 40 * mm, landscape(A0)[1] - 36 * mm)])])
    a0.build(make_a0(submission, title, metrics, styles, cjk))
    print(f"wrote {a0_path} ({a0_path.stat().st_size} bytes)")

    a3_path = drawings / "a3-booklet.pdf"
    a3 = BaseDocTemplate(str(a3_path), pagesize=A3,
                         leftMargin=18 * mm, rightMargin=18 * mm,
                         topMargin=16 * mm, bottomMargin=16 * mm,
                         title=f"{title} - A3 文册", author="goal-driven-agent")
    a3.addPageTemplates([PageTemplate(id="a3", frames=[
        Frame(18 * mm, 16 * mm, A3[0] - 36 * mm, A3[1] - 32 * mm)])])
    a3.build(make_a3(submission, title, metrics, styles, cjk))
    print(f"wrote {a3_path} ({a3_path.stat().st_size} bytes)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission_dir", help="target submission dir, e.g. submissions/test/test")
    args = parser.parse_args()
    submission = Path(args.submission_dir).resolve()
    if not (submission / "metrics.json").is_file():
        parser.error(f"{submission}/metrics.json not found")
    build(submission)
    return 0


if __name__ == "__main__":
    sys.exit(main())
