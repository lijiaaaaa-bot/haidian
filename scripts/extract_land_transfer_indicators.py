#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""海淀区土地招拍挂 → 单地块控规指标提取（独立脚本，无项目内部依赖）。

用途：
  通过北京市规划和自然资源委员会公示系统招拍挂模块（tdzpgxm/esSearchList API）
  拉取指定区县的土地挂牌出让公告列表，经 ggzyfw.beijing.gov.cn 公告详情页提取
  附件 PDF（“多规合一”协同平台审核意见函 / 建设项目规划条件 / 挂牌文件），
  下载并 file 验真后提取文本，解析地块规划指标（地块编号、用地性质、容积率、
  建筑控制高度、建筑密度、绿地率、用地规模、地上建筑规模、公告编号、文号、
  公告日期），并依据关键词判定是否属于“京张走廊”统筹研究范围相关地块，
  结果写入 CSV。

文本解析三级策略（自动降级）：
  1) PyMuPDF（fitz，如已安装）：按词坐标定位表头列，从多规合一函/规划条件
     的指标表中按行提取数值 —— 最可靠；
  2) pdftotext（poppler-utils）：标签直读（“容积率：X”“用地规模：X 平方米”等）；
  3) tesseract OCR（--ocr 且 PDF 无文本层）：按行解析“用地规模/容积率/地上
     建筑规模/控制高度/建筑密度/绿地率”6 列。

用法示例：
  python3 scripts/extract_land_transfer_indicators.py \
      --county 110108 \
      --out data/processed/konggui_parcel_indicators.csv \
      --tmpdir /tmp/tdzpg \
      --max-mb 8

依赖（系统命令）：curl、file、pdftotext（poppler-utils）；可选 fitz（PyMuPDF）
 与 tesseract（--ocr）。
铁律：本脚本不编造数值——解析不出的字段一律留空并写入 extraction_notes；
  大于 --max-mb 的附件只记录 URL 不下载；未取到详情页的公告标注“未提取”。
"""
import argparse
import csv
import html as html_mod
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

LIST_API = "https://yewu.ghzrzyw.beijing.gov.cn/zkdncms/tdgltdsc/tdzpgxm/esSearchList"
GGZYFW_BASE = "https://ggzyfw.beijing.gov.cn"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# 京张走廊统筹研究范围相关地块关键词（北至北五环、东至京藏高速、南至西直门外
# 大街、西至万泉河路；地块名含以下关键词视为 corridor=yes）
CORRIDOR_KEYWORDS = [
    "五塔寺", "明光村", "大钟寺", "知春路", "学院路", "西土城",
    "北下关", "双清路", "清华东路", "清河", "五道口", "西直门", "四道口",
]

# 附件文件名关键词（按优先级挑选含控规指标的 PDF）
# dghy 必须是“供地项目‘多规合一’协同平台审核意见的函”类；市政交通综合方案
# 的“多规合一”初审意见函不在此列
DOCNAME_PATTERNS = {
    "dghy": ["供地项目“多规合一”", "供地审核意见函", "“多规合一”协同平台审核意见的函"],
    "plancond": ["规划条件", "条供字"],
    "gpfile": ["挂牌文件", "招标文件"],
}
PRIORITY_ORDER = ["dghy", "plancond", "gpfile"]

# 文号 / 公告编号 / 日期
RE_DOC_NO = re.compile(r"京规自（海）供审函[〔\[](\d{4})[〕\]]\s*(\d+)\s*号")
RE_DOC_NO_OLD = re.compile(r"(\d{4})\s*规\s*土\s*[(（(]\s*海\s*[)）)]\s*条\s*[供侗]\s*字\s*(\d+)\s*号")
RE_NOTICE_NO = re.compile(r"京土(?:整)?储(?:挂|招)[(（]海[)）]\s*[〔\[](\d{4})[〕\]]\s*(\d+)\s*号")
RE_DATE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")

# 表头列关键词（含跨字拆分形式，如“容/积/率”“绿/地/率”“地上建/筑规模”“控制/高度”）
HEADER_PATTERNS = [
    ("land", ("用地规模",)),
    ("h", ("控制高", "控制")),
    ("far", ("容积", "容")),
    ("floor", ("地上建筑", "地上建")),
    ("green", ("绿地", "绿")),
    ("density", ("建筑密",)),
]
NUM_RE = re.compile(r"\d+(?:\.\d*)?")
CODE_RE = re.compile(r"^[\u4e00-\u9fff0-9A-Za-z-]+$")
# 规划条件 OCR 6 列行（用地规模/容积率/地上建筑规模/控制高度/建筑密度/绿地率）
# 注：tesseract 常在 CJK 字符间插入空格（"用 地"），故用 \s* 兼容
RE_OCR_ROW = re.compile(
    r"([A-J])\s*地\s*块?\s*(?:.*?用\s*地\s*)?([\d.]+)[\s|]+([\d.]+)[\s|]+([\d.]+)[\s|]+(\d+)[\s|]+(\d+)[\s|]+(\d+)")
RE_OCR_DECIMAL = re.compile(r"(\d+\.)\s*(\d+)")


def _run_curl(args, timeout=60):
    """经系统 curl 抓取（ggzyfw 服务器对 Python ssl 握手有 BAD_ECPOINT 问题，curl 正常）。"""
    cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", USER_AGENT] + args
    out = subprocess.run(cmd, capture_output=True, timeout=timeout + 30)
    if out.returncode != 0:
        raise RuntimeError("curl 退出码 %d: %s" % (out.returncode, out.stderr.decode("utf-8", "replace")[:200]))
    return out.stdout


def http_get(url, timeout=30):
    return _run_curl([url], timeout=timeout)


def http_post(url, data, timeout=30):
    return _run_curl(["-d", urllib.parse.urlencode(data), url], timeout=timeout)


def fetch_land_list(county, limit=20, max_pages=300):
    """分页拉取招拍挂列表（county=区县代码），返回记录列表。"""
    rows = []
    page = 1
    while page <= max_pages:
        raw = http_post(LIST_API, {"page": page, "limit": limit, "county": county, "gjz": ""})
        d = json.loads(raw)
        batch = d.get("data") or []
        rows.extend(batch)
        if len(batch) < limit:
            break
        page += 1
    return rows


def find_detail_url(record):
    """从记录中提取 ggzyfw 公告详情页 URL（lsbjQtfs 等字段的 zpgcrgg 链接）。"""
    text = " ".join(str(record.get(k) or "") for k in
                    ("lsbjQtfs", "memo1", "memo2", "add1", "add2", "add3"))
    m = re.search(r"https?://ggzyfw\.beijing\.gov\.cn/zpgcrgg/[0-9]+/[0-9]+\.html", text)
    if m:
        return m.group(0)
    m = re.search(r"zpgcrgg/([0-9]+/[0-9]+\.html)", text)
    if m:
        return GGZYFW_BASE + "/zpgcrgg/" + m.group(1)
    return None


def list_attachments(detail_html):
    """解析 ggzyfw 详情页附件（<a href=...pdf>文件名</a>），返回 [(名称, URL)]。"""
    out = []
    for href, txt in re.findall(r'<a[^>]+href="([^"]+\.pdf[^"]*)"[^>]*>([^<]*)</a>', detail_html, re.I):
        txt = html_mod.unescape(txt).strip()
        href = href.strip()  # 页面 href 值常带尾随空格
        if not href.lower().endswith(".pdf"):
            continue
        full = href if href.startswith("http") else GGZYFW_BASE + href
        out.append((txt, full))
    return out


def pick_key_attachments(attachments):
    """按优先级挑选指标类附件（每个优先级保留一个）。返回 {kind: (name, url)}。"""
    picked = {}
    for kind in PRIORITY_ORDER:
        for name, url in attachments:
            if any(p in name for p in DOCNAME_PATTERNS[kind]):
                picked[kind] = (name, url)
                break
    return picked


def http_head_length(url, timeout=30):
    try:
        out = subprocess.run(
            ["curl", "-sIL", "--max-time", str(timeout), "-A", USER_AGENT, url],
            capture_output=True, timeout=timeout + 20)
        for line in out.stdout.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("content-length:"):
                return int(line.split(":")[1].strip())
    except Exception:
        pass
    return None


def download(url, dest, timeout=120):
    data = http_get(url, timeout=timeout)
    with open(dest, "wb") as f:
        f.write(data)
    return len(data)


def verify_pdf(path):
    try:
        out = subprocess.run(["file", path], capture_output=True, text=True, timeout=20)
        return "PDF document" in out.stdout
    except Exception:
        return False


def pdftotext(path):
    try:
        out = subprocess.run(["pdftotext", "-layout", path, "-"],
                             capture_output=True, text=True, timeout=120)
        if out.returncode == 0:
            return out.stdout
    except Exception:
        pass
    return ""


def ocr_pdf(path):
    """tesseract OCR（chi_sim）全部页面，返回拼接文本；不可用时返回空串。"""
    if not shutil.which("tesseract"):
        return ""
    try:
        info = subprocess.run(["pdfinfo", path], capture_output=True, text=True, timeout=30)
        n_pages = 1
        for line in info.stdout.splitlines():
            if line.startswith("Pages:"):
                n_pages = int(line.split(":")[1].strip())
                break
        with tempfile.TemporaryDirectory() as td:
            png = os.path.join(td, "p")
            subprocess.run(["pdftoppm", "-r", "150", "-png", "-f", "1", "-l", str(n_pages),
                            path, png], capture_output=True, timeout=300)
            texts = []
            for f in sorted(os.listdir(td)):
                if f.endswith(".png"):
                    base = os.path.splitext(f)[0]
                    subprocess.run(["tesseract", os.path.join(td, f), os.path.join(td, base),
                                    "-l", "chi_sim"], capture_output=True, timeout=300)
                    p = os.path.join(td, base + ".txt")
                    if os.path.exists(p):
                        texts.append(open(p, encoding="utf-8").read())
            return "\n".join(texts)
    except Exception:
        return ""


def find_header(path, top_limit=200):
    """PyMuPDF 词坐标定位指标表表头列。返回 (colmap, spread, page_no) 或 None。"""
    try:
        import fitz
    except ImportError:
        return None
    doc = fitz.open(path)
    best = None
    for pno in range(min(3, len(doc))):
        page = doc[pno]
        words = page.get_text("words")
        hits = {}
        for w in words:
            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
            if not (40 < y0 < top_limit) or x0 < 140:
                continue
            for col, pats in HEADER_PATTERNS:
                if any(p in txt for p in pats):
                    hits.setdefault(col, []).append(x0)
        colmap = {}
        if hits.get("land"):
            # 用地规模 单元格内通常有两个词：“用地规模”（值列起点）优先
            xs = hits["land"]
            colmap["land"] = max(xs) if len(xs) > 1 else xs[0]
        for col in ("h", "far", "floor", "green", "density"):
            if hits.get(col):
                colmap[col] = min(hits[col])
        if len(colmap) >= 4:
            xs = list(colmap.values())
            spread = max(xs) - min(xs)
            if best is None or spread > best[1]:
                best = (colmap, spread, pno)
    return best


def extract_rows_pymupdf(path, colmap, tol=14.0):
    """按表头列 x 坐标提取指标行。返回 [{code, lu, vals:{col:str}}]。"""
    import fitz
    doc = fitz.open(path)
    rows = {}          # (page, yk) -> {col: raw}
    codes = {}         # (page, yk) -> [(txt, x0, y0)]  编号列
    lus = {}           # (page, yk) -> [(txt, x0, y0)]  用地性质列
    lu_left = colmap.get("land", 200) - 30
    for pno in range(min(3, len(doc))):
        page = doc[pno]
        for w in page.get_text("words"):
            x0, y0, x1, y1, txt = w[0], w[1], w[2], w[3], w[4]
            yk = round(y0 / 6)
            key = (pno, yk)
            if NUM_RE.fullmatch(txt):
                bcol = None
                bd = tol + 1
                for col, ax in colmap.items():
                    d = abs(x0 - ax)
                    if d < bd:
                        bd = d
                        bcol = col
                if bcol is not None:
                    rows.setdefault(key, {})[bcol] = txt
            else:
                if not (60 < y0 < 500) or not CODE_RE.match(txt):
                    continue
                if x0 < 123:
                    codes.setdefault(key, []).append((txt, x0, y0))
                elif x0 < lu_left:
                    lus.setdefault(key, []).append((txt, x0, y0))
    buckets = []
    for key in sorted(rows):
        rec = dict(rows[key])
        if buckets and key[1] - buckets[-1][1] <= 2 and key[0] == buckets[-1][0]:
            merged = buckets[-1][2]
            for col, val in rec.items():
                prev = merged.get(col)
                if prev is not None and prev.endswith(".") and val.isdigit():
                    merged[col] = prev + val
                else:
                    merged[col] = val
            buckets[-1][1] = key[1]
        else:
            buckets.append([key[0], key[1], rec])
    out = []
    for pno, yk, rec in buckets:
        if len(rec) < 3:
            continue
        cw = []
        for cyk in range(yk - 5, yk + 6):
            for txt, x0, y0 in codes.get((pno, cyk), []):
                cw.append((txt, x0, y0))
        cw.sort(key=lambda t: (t[2], t[1]))
        lw = []
        for cyk in range(yk - 5, yk + 6):
            for txt, x0, y0 in lus.get((pno, cyk), []):
                lw.append((txt, x0, y0))
        lw.sort(key=lambda t: (t[2], t[1]))
        lu_text = "".join(t[0] for t in lw)
        lu = ""
        # 注：\b 在“数字+CJK”间不成立，用 (?![A-Za-z0-9]) 界定代码结束
        m = re.search(r"([A-Z]\d{1,2})(?![A-Za-z0-9])", lu_text)
        if m:
            lu = m.group(1)
        out.append({"code": "".join(t[0] for t in cw), "lu": lu, "vals": dict(rec)})
    return out


def parse_plancond_ocr(text):
    """OCR 文本按 6 列行解析（用地规模/容积率/地上建筑规模/控制高度/建筑密度/绿地率）。"""
    text = RE_OCR_DECIMAL.sub(r"\1\2", text)  # 合并 "25612. 778" 之类 OCR 拆行
    rows = []
    for m in RE_OCR_ROW.finditer(text):
        line = m.group(0)
        lu = ""
        lm = re.search(r"\b([A-Z]\d{1,2})\b", line[: m.end(2) - len(m.group(2))])
        if lm:
            lu = lm.group(1)
        rows.append({
            "code": m.group(1) + "地块", "lu": lu,
            "vals": {"land": m.group(2), "far": m.group(3), "floor": m.group(4),
                     "h": m.group(5), "density": m.group(6), "green": m.group(7)},
        })
    return rows


def parse_labels(text):
    """pdftotext 标签直读兜底。返回 {col: value}。"""
    out = {}
    m = re.search(r"容积率\s*[：:]\s*([\d.]+)", text)
    if m:
        out["far"] = m.group(1)
    m = re.search(r"(?:建筑)?控制高度\s*[：:]\s*([\d.]+)", text)
    if m:
        out["h"] = m.group(1)
    m = re.search(r"建筑密度\s*[：:]\s*([\d.]+)", text)
    if m:
        out["density"] = m.group(1)
    m = re.search(r"绿地率\s*[：:]\s*[≥>]?\s*([\d.]+)\s*%", text)
    if m:
        out["green"] = m.group(1)
    m = re.search(r"用地规模\s*[：:]\s*([\d.]+)\s*平方米", text)
    if m:
        out["land"] = m.group(1)
    m = re.search(r"地上建筑规模\s*[：:]\s*([\d.]+)\s*平方米", text)
    if m:
        out["floor"] = m.group(1)
    return out


def parse_doc_no(text):
    m = RE_DOC_NO.search(text)
    if m:
        return "京规自（海）供审函〔%s〕%s号" % (m.group(1), m.group(2))
    m = RE_DOC_NO_OLD.search(text)
    if m:
        return "%s规土（海）条供字%s号" % (m.group(1), m.group(2))
    return ""


def parse_notice_no(text):
    m = RE_NOTICE_NO.search(text)
    if m:
        return "京土储挂（海）[%s]%s号" % (m.group(1), m.group(2))
    return ""


def parse_notice_date(text):
    m = RE_DATE.search(text)
    if m:
        return "%s-%02d-%02d" % (m.group(1), int(m.group(2)), int(m.group(3)))
    return ""


def corridor_judge(name):
    """按地块名称关键词判定走廊相关性：yes / unknown（不含关键词但未否定）。"""
    for kw in CORRIDOR_KEYWORDS:
        if kw in name:
            return "yes"
    return "unknown"


def parse_pdf_indicators(pdf_path, use_ocr=False):
    """解析单个 PDF 的指标。返回 (rows, notes)。rows=[{code, vals}]。"""
    notes = []
    hdr = find_header(pdf_path)
    if hdr:
        colmap, spread, pno = hdr
        rows = extract_rows_pymupdf(pdf_path, colmap)
        if rows:
            notes.append("PyMuPDF 词坐标法（表头在第 %d 页，列 x 跨度 %.0fpt）" % (pno + 1, spread))
            return rows, notes
        notes.append("PyMuPDF 定位到表头但未解析出行数值")
    text = pdftotext(pdf_path)
    if text.strip():
        rows = parse_labels(text)
        if rows:
            notes.append("pdftotext 标签直读")
            return [{"code": "", "vals": rows}], notes
    if use_ocr:
        ocr = ocr_pdf(pdf_path)
        if ocr.strip():
            rows = parse_plancond_ocr(ocr)
            if rows:
                notes.append("tesseract OCR（chi_sim）按 6 列行解析，可能有识别误差")
                return rows, notes
            notes.append("OCR 完成但未能按 6 列行解析")
        else:
            notes.append("PDF 无文本层且 OCR 不可用/失败")
    else:
        notes.append("PDF 无文本层（扫描件），未开启 --ocr 或 tesseract 缺失")
    return [], notes


def run(args):
    records = fetch_land_list(args.county, limit=args.list_limit)
    os.makedirs(args.tmpdir, exist_ok=True)
    results = []

    for rec in records:
        title = rec.get("title") or ""
        landid = rec.get("landid") or ""
        location = rec.get("landlocation") or ""
        notice_no = parse_notice_no(landid)
        detail_url = find_detail_url(rec)
        base = {"parcel_name": title or landid, "parcel_code": "", "land_use_code": "",
                "far": "", "building_height_m": "", "building_density_pct": "",
                "green_ratio_pct": "", "land_area_sqm": "", "floor_area_sqm": "",
                "notice_no": notice_no or "", "doc_no": "",
                "notice_date": (rec.get("pubdate") or "")[:10],
                "corridor": corridor_judge(title + location),
                "source_url": detail_url or "",
                "extraction_notes": ""}

        if not detail_url:
            row = dict(base)
            row["extraction_notes"] = "列表中无 ggzyfw 详情页链接，指标未提取"
            results.append(row)
            continue

        try:
            detail_html = http_get(detail_url).decode("utf-8", "replace")
        except Exception as e:
            row = dict(base)
            row["extraction_notes"] = "详情页抓取失败：%s" % e
            results.append(row)
            continue

        attachments = list_attachments(detail_html)
        picked = pick_key_attachments(attachments)

        texts = []          # 各附件文本（用于文号/编号/日期）
        indicator_pdf = None
        gpfile_text = ""
        notes = []
        for kind in PRIORITY_ORDER:
            if kind not in picked:
                continue
            name, url = picked[kind]
            size = http_head_length(url)
            if size is not None and size > args.max_mb * 1024 * 1024:
                notes.append("附件“%s” %dMB 超限，仅记录 URL" % (name, size // 1048576))
                continue
            dest = os.path.join(args.tmpdir, "%s_%s.pdf" % (kind, re.sub(r"\D", "", landid)[-6:]))
            if not os.path.exists(dest) or os.path.getsize(dest) == 0:
                try:
                    download(url, dest)
                except Exception as e:
                    notes.append("附件“%s”下载失败：%s" % (name, e))
                    continue
            if not verify_pdf(dest):
                notes.append("附件“%s”不是有效 PDF" % name)
                continue
            if indicator_pdf is None:
                indicator_pdf = dest
            txt = pdftotext(dest)
            if txt.strip():
                texts.append(txt)
            if kind == "gpfile":
                gpfile_text = txt

        if indicator_pdf is None:
            row = dict(base)
            row["extraction_notes"] = "; ".join(notes) or "未取得可用指标附件"
            results.append(row)
            continue

        all_text = "\n".join(texts)
        doc_no = parse_doc_no(all_text) or parse_doc_no(pdftotext(indicator_pdf))
        # 公告日期优先取挂牌文件（挂牌公告发布日期），其次函件/记录发布日期
        notice_date = (parse_notice_date(gpfile_text)
                       or parse_notice_date(all_text)
                       or (rec.get("pubdate") or "")[:10])
        rows, pnotes = parse_pdf_indicators(indicator_pdf, use_ocr=args.ocr)
        notes.extend(pnotes)
        if not rows:
            rows = [{"code": "", "vals": {}}]
            notes.append("指标未能解析")
        if len(rows) == 1 and not rows[0]["vals"] and parse_labels(pdftotext(indicator_pdf)):
            rows[0]["vals"] = parse_labels(pdftotext(indicator_pdf))
            notes.append("pdftotext 标签直读兜底")

        for r in rows:
            vals = r["vals"]
            row = dict(base)
            row["parcel_code"] = r.get("code", "")
            # 用地性质：优先该行的用地性质列/OCR 行代码；否则取全文唯一用地代码
            lu = r.get("lu", "")
            if not lu:
                doc_codes = [c for c in ("B4", "B23", "B2", "B1", "R2", "F1", "F2", "F3", "A33", "S32")
                             if re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % c, all_text)
                             or re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % c, title)]
                if len(doc_codes) == 1:
                    lu = doc_codes[0]
            row["land_use_code"] = lu
            row["far"] = vals.get("far", "")
            row["building_height_m"] = vals.get("h", "")
            row["building_density_pct"] = vals.get("density", "")
            row["green_ratio_pct"] = vals.get("green", "")
            row["land_area_sqm"] = vals.get("land", "")
            row["floor_area_sqm"] = vals.get("floor", "")
            row["notice_no"] = notice_no or ""
            row["doc_no"] = doc_no
            row["notice_date"] = notice_date
            row["corridor"] = corridor_judge(title + location)
            row["extraction_notes"] = "; ".join(notes)
            results.append(row)

    cols = ["parcel_name", "parcel_code", "land_use_code", "far", "building_height_m",
            "building_density_pct", "green_ratio_pct", "land_area_sqm", "floor_area_sqm",
            "notice_no", "doc_no", "notice_date", "corridor", "source_url", "extraction_notes"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k, "") for k in cols})
    print("写入 %s：%d 行" % (args.out, len(results)))


def main():
    ap = argparse.ArgumentParser(description="海淀区土地招拍挂单地块控规指标提取（详见模块 docstring）")
    ap.add_argument("--county", default="110108", help="区县代码（默认 110108=海淀）")
    ap.add_argument("--out", default="konggui_parcel_indicators.csv", help="输出 CSV 路径")
    ap.add_argument("--tmpdir", default="/tmp/tdzpg", help="PDF 下载/复用目录")
    ap.add_argument("--max-mb", type=float, default=8.0, help="附件大小上限（MB），超过只记 URL")
    ap.add_argument("--list-limit", type=int, default=20, help="列表接口每页条数")
    ap.add_argument("--ocr", action="store_true",
                    help="对无文本层 PDF 尝试 tesseract OCR（需 tesseract + chi_sim）")
    args = ap.parse_args()
    run(args)


if __name__ == "__main__":
    main()
