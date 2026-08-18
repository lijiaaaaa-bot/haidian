#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""历史公告（2010-2022 无 ggzyfw 详情页）交易文件 ZIP 全量拉取与指标提取。

背景（data/processed/konggui-parcel-extraction-v2-notes.md §六.1）：
  84 条招拍挂公告中 57 条历史公告（2010-2022）无 ggzyfw 详情页链接，
  tdscjywj 交易文件 ZIP（列表 memo2 字段）覆盖其中 14 条（2018-2021）；
  其中 3 条走廊相关（[2019]034/[2018]052/[2019]056）已在 v2 提取，
  剩余 11 条（永丰/西北旺/西三旗/四季青/苏家坨/西八里庄/北安河等，
  corridor=unknown）本脚本逐一：下载 ZIP → 解包 → 按关键词挑选
  规划条件/招标文件 PDF → 三级解析（PyMuPDF→pdftotext→PaddleOCR）→
  输出 v2 同构 CSV（data/processed/konggui_parcel_indicators_v3_historical.csv）。

铁律（沿用 v2）：
  - 数值必须来自实际下载 PDF 文本；解析不出的字段留空并写 extraction_notes；
  - >8MB 附件只记 URL 不入库；ZIP 本体存 /tmp 不入库；
  - 不编造；下载限速、失败退避重试。

用法：
  python3 scripts/fetch_historical_land_zips.py [--list data/raw/land_list_110108_full.json]
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from extract_land_transfer_indicators import (  # noqa: E402
    DOCNAME_PATTERNS,
    PRIORITY_ORDER,
    corridor_judge,
    parse_doc_no,
    parse_labels,
    parse_notice_no,
    parse_notice_date,
    parse_pdf_indicators,
    parse_plancond_ocr,
    pdftotext,
    verify_pdf,
)

LIST_DEFAULT = ROOT / "data/raw/land_list_110108_full.json"
ZIP_DIR = Path("/tmp/tdzpg_zips")
EXTRACT_DIR = Path("/tmp/tdzpg_zips/x")
OUT_DIR = ROOT / "data/sources/land-transfer"
OUT_CSV = ROOT / "data/processed/konggui_parcel_indicators_v3_historical.csv"
LOG_FILE = ROOT / "data/processed/land-zip-fetch.log"
MAX_PDF_MB = 8.0  # >8MB 只记 URL 不入库（沿用 v2 纪律）
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# v2 已提取（跳过）
DONE_NOTICES = {"京土储挂（海）[2019]034号", "京土储挂（海）[2018]052号", "京土储挂（海）[2019]056号"}

CSV_COLS = [
    "parcel_name", "parcel_code", "land_use_code", "far", "building_height_m",
    "building_density_pct", "green_ratio_pct", "land_area_sqm", "floor_area_sqm",
    "notice_no", "doc_no", "notice_date", "corridor", "source_url",
    "extraction_notes", "transaction_price", "winner", "transaction_date",
]


def log(msg: str) -> None:
    line = "%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def curl_download(url: str, dest: Path, timeout=1800) -> bool:
    """下载（支持断点续传）；完整性由 zipfile.testzip() 在调用方校验。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        cmd = ["curl", "-sL", "--max-time", str(timeout), "-A", USER_AGENT]
        if dest.exists() and dest.stat().st_size > 0:
            cmd += ["-C", "-"]
        cmd += ["-o", str(dest), url]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return True
        log("下载失败(尝试%d): %s  rc=%d" % (attempt + 1, url, r.returncode))
        time.sleep(5 * (attempt + 1))
    return False


def unzip(zip_path: Path, out_dir: Path) -> list[Path]:
    """解包（zipfile，GBK→UTF-8 文件名编码回退）；CRC 校验失败返回 []。"""
    import zipfile

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            bad = zf.testzip()
            if bad is not None:
                log("ZIP CRC 校验失败（%s）——文件不完整，将删除重下" % bad)
                return []
        for enc in ("gbk", "utf-8"):
            try:
                with zipfile.ZipFile(zip_path, metadata_encoding=enc) as zf:
                    zf.extractall(out_dir)
                pdfs = sorted(p for p in out_dir.rglob("*") if p.suffix.lower() == ".pdf")
                if pdfs:
                    log("  解包编码 %s，PDF %d 个" % (enc, len(pdfs)))
                    return pdfs
            except Exception as e:  # noqa: BLE001
                log("  解包尝试 %s 失败：%s" % (enc, e))
                continue
        return []
    except Exception as e:  # noqa: BLE001
        log("ZIP 打开失败：%s" % e)
        return []


def pick_attachments(pdfs: list[Path]) -> dict[str, Path]:
    """按 v2 优先级挑 PDF：dghy(多规合一函) > plancond(规划条件) > gpfile(挂牌/招标文件)。

    2018-2021 交易文件命名补充匹配：规划条件类含"规划意见复函/规划意见"；
    挂牌/招标文件常以公告编号命名（"0-京土整储挂（海）[XXXX]XXX号.pdf"）。
    """
    patterns = {
        "dghy": DOCNAME_PATTERNS["dghy"] + ["多规合一"],
        "plancond": DOCNAME_PATTERNS["plancond"] + ["规划意见复函", "规划意见"],
        "gpfile": DOCNAME_PATTERNS["gpfile"] + ["京土整储"],
    }
    picked: dict[str, Path] = {}
    for kind in PRIORITY_ORDER:
        for p in pdfs:
            name = p.name
            if any(pat in name for pat in patterns[kind]):
                picked[kind] = p
                break
    return picked


def parse_announcement_labels(text: str) -> dict:
    """公告级标签直读（挂牌/招标文件）：总用地面积/土地面积/建筑控制规模。

    最后回退到"挂牌编号"表：表段内（表头"（平方米）"之后）第一个大数为
    土地面积、最后一个为建筑控制规模（2019-2020 挂牌文件文本层实测）。
    """
    out = {}
    m = re.search(r"(?:总)?用地面积\s*[：:]\s*([\d,]+(?:\.\d+)?)\s*平方米", text)
    if m:
        out["land"] = m.group(1).replace(",", "")
    m = re.search(r"土地面积\s*[：:]\s*([\d,]+(?:\.\d+)?)\s*平方米", text)
    if m and "land" not in out:
        out["land"] = m.group(1).replace(",", "")
    m = re.search(r"(?:总)?地上建筑规模\s*[：:]\s*([\d,]+(?:\.\d+)?)\s*平方米", text)
    if m:
        out["floor"] = m.group(1).replace(",", "")
    m = re.search(r"建筑控制规模\s*[：:]\s*([\d,]+(?:\.\d+)?)\s*平方米", text)
    if m and "floor" not in out:
        out["floor"] = m.group(1).replace(",", "")

    if not out.get("land") or not out.get("floor"):
        # 挂牌编号表兜底：表头"（平方米）"之后第一个大数为土地面积、
        # 建筑控制规模取表中最大值（"建设用地"重复数在后时用 max 区分）。
        # 仅补缺失字段，不覆盖标签直读结果。
        fb: dict = {}
        m = re.search(r"挂牌编号(.{0,400})", text, re.S)
        if m:
            seg = m.group(1)
            for stop in ("起始价", "万元"):
                j = seg.find(stop)
                if j >= 0:
                    seg = seg[:j]
            h = seg.find("（平方米）")
            if h >= 0:
                seg = seg[h:]
            nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", seg)
                    if float(n.replace(",", "")) >= 100]
            if nums:
                fb["land"] = str(nums[0]) if nums[0].is_integer() else str(nums[0])
            if len(nums) >= 2:
                floor = max(nums[1:]) if len(nums) >= 3 else nums[1]
                fb["floor"] = str(int(floor)) if floor.is_integer() else str(floor)
        for k in ("land", "floor"):
            if not out.get(k) and fb.get(k):
                out[k] = fb[k]
    return out


def normalize_plot_code(token: str) -> str:
    """归一化 OCR 噪声地块编号：HD00-0403-0043（O→0，去 <>= 等噪声）。"""
    t = re.sub(r"[Oo]", "0", token)
    m = re.search(r"[Hh][Dd][0Pp0-9]{1,4}[=\-]?\s*(\d{3,4})[=\-<>]?\s*<?(\d{3,4})", t)
    if m:
        return "HD00-%s-%s" % (m.group(1), m.group(2))
    return token


# 非 HD 前缀的地块编号（2018-2019 西三旗/安宁庄等）：1814-630 / 1811-L04 / 1820-618A
RE_CODE_FALLBACK = re.compile(r"(?<![\dA-Za-z])((?:18|19|20)\d{2})-[A-Z]?\d{2,3}[A-Z]?(?![\dA-Za-z])")


def _match_row_vals(nums: list[float], has_density: bool) -> dict | None:
    """按列序范围约束顺序匹配指标值；行必须含 land≥100 且 floor≥1000。"""
    vals: dict[str, str] = {}

    def take(pred):
        nonlocal nums
        for k, n in enumerate(nums):
            if pred(n):
                nums = nums[k + 1:]
                return n
        return None

    land = take(lambda n: n >= 100)
    if land is None:
        return None
    vals["land"] = str(int(land)) if land.is_integer() else str(land)
    far = take(lambda n: 0.1 <= n <= 8.0)
    if far is not None:
        vals["far"] = str(int(far)) if far.is_integer() else str(far)
    if has_density:
        density = take(lambda n: 20 <= n <= 60)
        if density is not None:
            vals["density"] = str(int(density))
    h = take(lambda n: 10 <= n <= 80)
    if h is not None:
        vals["h"] = str(int(h))
    floor = take(lambda n: n >= 1000)
    if floor is None:
        return None
    vals["floor"] = str(int(floor))
    green = take(lambda n: 10 <= n <= 60)
    if green is not None:
        vals["green"] = str(int(green))
    return vals


RE_CODE_HD = re.compile(r"[Hh][Dd][0OoPp0-9]{1,5}[=\-]?\s*\d{3,4}[=\-<>]?\s*<?\d{3,4}")


def _parse_plancond_totals(text: str) -> dict:
    """从 OCR 文本提取函/规划条件指标表"总计"行：{land, floor}（±1% 校验用）。

    PaddleOCR 按单元格拆块，总计行碎片可能跨 band 散落（如 floor 掉入相邻
    band），故以"总计/合计"块为锚点收集其 ±40px 内所有数字，按 x 排序取
    前两个 ≥100 的数值（总计 行 土地面积、建筑控制规模）。
    """
    items = []
    tsv = True
    for line in text.splitlines():
        m = re.match(r"^(\d+)\t(\d+)\t(.*)$", line)
        if m:
            items.append((int(m.group(1)), int(m.group(2)), m.group(3)))
        else:
            tsv = False
            break
    if tsv and items:
        total_items = [it for it in items if ("总" in it[2] or "合" in it[2]) and "计" in it[2]]
        if not total_items:
            return {}
        y0 = total_items[0][0]
        near = [it for it in items if abs(it[0] - y0) <= 40]
        near.sort(key=lambda b: b[1])
        s = " ".join(t for _, _, t in near)
        s = re.sub(r"(\d+)\.\s*(\d+)", r"\1.\2", s)
        s = re.sub(r"(\d+)\.\s*(\d+)", r"\1.\2", s)
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s) if float(n) >= 100]
        if len(nums) >= 2:
            return {"land": nums[0], "floor": nums[1]}
        return {}
    for line in text.splitlines():
        if re.search(r"(?:总|合)\s*[计計]", line):
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", line) if float(n) >= 100]
            if len(nums) >= 2:
                return {"land": nums[0], "floor": nums[1]}
    return {}


def parse_plancond_ocr_table(text: str) -> list[dict]:
    """规划条件/函指标表 OCR 行解析（地块编号锚定 + 列序范围约束）。

    输入支持两种格式：
      - PaddleOCR TSV（本脚本 ocr_pdf_paddle 输出）：每行 "y\\tx\\ttext"，
        按 y 聚类成表格行、x 排序成列，重建指标序列（对单元格拆分稳定）；
      - 纯文本行：按行切片拼接。
    列序随年份/公告不同（PaddleOCR 实测）：
      - 有"建筑密度"列（2020 年函，如 [2020]001）：land→far→density→h→floor→green
      - 无密度列（2019 年函，如 [2019]044）：land→far→h→floor→green
    行必须含 land≥100 且 floor≥1000（过滤叙事文本）。中置信，待人工核验。
    """
    text = re.sub(r"(\d+)\.\s*(\d+)", r"\1.\2", text)      # OCR 数字内空格合并
    text = re.sub(r"(\d+)\.\s*(\d+)", r"\1.\2", text)
    text = re.sub(r"(\d{3,})[:：](\d{2,3})", r"\1.\2", text)  # 冒号误读小数点
    has_density = "密度" in text
    rows: dict[str, dict] = {}

    # 尝试解析 TSV 坐标（PaddleOCR 输出）
    items = []
    tsv = True
    for line in text.splitlines():
        m = re.match(r"^(\d+)\t(\d+)\t(.*)$", line)
        if m:
            items.append((int(m.group(1)), int(m.group(2)), m.group(3)))
        else:
            tsv = False
            break

    if tsv and items:
        # 按 y 聚类成行（行内碎片 y 差 ≤25px，行距 ~70-100px）
        items.sort(key=lambda b: (b[0], b[1]))
        bands: list[list] = []
        for it in items:
            if not bands or it[0] - bands[-1][0][0] > 25:
                bands.append([it])
            else:
                bands[-1].append(it)
        for band in bands:
            band.sort(key=lambda b: b[1])  # 行内按 x 排序
            code_token = None
            code = ""
            for _, x, t in band:
                m = RE_CODE_HD.search(t)
                if m:
                    code_token = m
                    code = normalize_plot_code(m.group(0))
                    break
            if not code_token:
                fm = RE_CODE_FALLBACK.search(" ".join(t for _, _, t in band))
                if fm:
                    code = fm.group(0)
                    code_token = fm
                else:
                    continue
            if code in rows:
                continue
            window = " ".join(t for _, _, t in band)
            window = window.replace(code_token.group(0), " ", 1)
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", window)]
            # 剔除地块编号自身的数字片段（OCR 把编号拆开时数字会泄漏进来）
            code_parts = {s for s in re.findall(r"\d+", code)}
            nums = [n for n in nums if str(int(n)) not in code_parts]
            vals = _match_row_vals(nums, has_density)
            if vals is None:
                continue
            rows[code] = {"code": code, "lu": "", "vals": vals}
        return list(rows.values())

    # 纯文本行模式（无坐标）
    lines = text.splitlines()
    for i, line in enumerate(lines):
        code_token = RE_CODE_HD.search(line)
        if code_token:
            code = normalize_plot_code(code_token.group(0))
        else:
            fm = RE_CODE_FALLBACK.search(line)
            if not fm:
                continue
            code = fm.group(0)
            code_token = fm
        if code in rows:
            continue
        # 窗口：本行到下一个含地块编号的行
        j = i + 1
        while j < min(len(lines), i + 30):
            if RE_CODE_HD.search(lines[j]) or RE_CODE_FALLBACK.search(lines[j]):
                break
            j += 1
        window = " ".join(lines[i:j])
        window = window.replace(code_token.group(0), " ", 1)
        nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", window)]
        code_parts = {s for s in re.findall(r"\d+", code)}
        nums = [n for n in nums if str(int(n)) not in code_parts]
        vals = _match_row_vals(nums, has_density)
        if vals is None:
            continue
        rows[code] = {"code": code, "lu": "", "vals": vals}
    return list(rows.values())


def file_mb(path: Path) -> float:
    return path.stat().st_size / (1024 * 1024)


def parse_dghy_ocr_loose(text: str) -> list[dict]:
    """（已弃用）函（扫描件）指标表 OCR 宽松解析——2026-08-14 实测在低质量
    扫描上产生垃圾数值（备注列数字被当作指标），违反"解析不出就留空"铁律，
    故不再使用。保留函数体仅为记录决策，实际调用已移除。"""
    return []


def _dedup_rows(rows_: list) -> list:
    seen_codes: set = set()
    dedup: list = []
    for r in rows_:
        c = r.get("code")
        if c and c in seen_codes:
            continue
        if c:
            seen_codes.add(c)
        dedup.append(r)
    return dedup


def ocr_pdf_paddle(path: str, max_pages: int = 3) -> str:
    """PaddleOCR（anaconda 环境）识别 PDF → 文本；不可用时返回空串。"""
    helper = ROOT / "scripts/paddle_ocr_pdf.py"
    out_txt = os.path.join(tempfile.mkdtemp(), "ocr.txt")
    for py in ("/Volumes/innerdisk/anaconda3/bin/python", "python3"):
        try:
            r = subprocess.run([py, str(helper), str(path), out_txt, str(max_pages)],
                               capture_output=True, timeout=1200)
            if r.returncode == 0 and os.path.exists(out_txt) and os.path.getsize(out_txt) > 0:
                t = open(out_txt, encoding="utf-8").read()
                os.unlink(out_txt)
                return t
        except Exception:  # noqa: BLE001
            continue
    if os.path.exists(out_txt):
        os.unlink(out_txt)
    return ""


def _row_plausible(vals: dict) -> bool:
    """单行合理性过滤：用地规模/地上建筑规模须在合理范围且非年份/数字粘连。"""
    land = vals.get("land", "")
    floor = vals.get("floor", "")
    try:
        land_f, floor_f = float(land), float(floor)
    except ValueError:
        return False
    if not (1000 <= land_f <= 500000):
        return False
    if not (1000 <= floor_f <= 2000000):
        return False
    if 1950 <= floor_f <= 2030:  # 年份误读（如 2012/2015）
        return False
    if any("." in v and len(v.split(".")[-1]) > 3 for v in (land, floor)):  # 数字粘连（仅含小数时）
        return False
    return True


def build_rows(rec: dict, picked: dict[str, Path], notice_no: str,
               corridor: str, source_url: str) -> list[dict]:
    """生成 v2 同构行：宗地级（规划条件/函）+ 公告级（挂牌/招标文件标签直读）。"""
    rows: list[dict] = []
    notes_all: list[str] = []
    indicator_pdf = None
    texts: list[str] = []

    # 只对 <8MB 的 PDF 入库解析；超限记 URL
    for kind, path in list(picked.items()):
        if file_mb(path) > MAX_PDF_MB:
            notes_all.append("附件 %s %.1fMB 超限(>8MB)，仅记 URL 不入库" % (path.name, file_mb(path)))
            picked.pop(kind)
            continue
        txt = pdftotext(path)
        if txt.strip():
            texts.append(txt)

    indicator_pdf = picked.get("plancond") or picked.get("dghy")
    zb_pdf = picked.get("gpfile")
    base = {
        "parcel_name": rec.get("title") or rec.get("landid") or "",
        "parcel_code": "", "land_use_code": "",
        "far": "", "building_height_m": "", "building_density_pct": "",
        "green_ratio_pct": "", "land_area_sqm": "", "floor_area_sqm": "",
        "notice_no": notice_no, "doc_no": "",
        "notice_date": (rec.get("pubdate") or "")[:10],
        "corridor": corridor, "source_url": source_url,
        "extraction_notes": "",
        "transaction_price": "", "winner": "",
        "transaction_date": (rec.get("chegnJiaoShiJian") or "")[:10],
    }

    all_text = "\n".join(texts)
    doc_no = parse_doc_no(all_text)

    # 宗地级：有文本层走严格解析；无文本层（扫描件）用 300dpi OCR 指标表解析
    # （地块编号锚定 + 列序范围约束），失败才如实留空。不做宽松数值抓取——
    # 2026-08-14 实测低质量 OCR 宽松解析会产出垃圾数值，违反"解析不出就留空"铁律。
    parsed_pdf_name = ""
    if indicator_pdf is not None:
        parsed_pdf_name = indicator_pdf.name
        txt_layer = pdftotext(indicator_pdf)
        if txt_layer.strip():
            rows_, pnotes = parse_pdf_indicators(str(indicator_pdf), use_ocr=False)
            notes_all.extend(pnotes)
            if not rows_:
                notes_all.append("指标未能解析（严格解析）")
        else:
            notes_all.append("无文本层（扫描件），PaddleOCR 指标表解析")
            paddle_txt = ocr_pdf_paddle(str(indicator_pdf), max_pages=3)
            rows_ = parse_plancond_ocr_table(paddle_txt)
            rows_.extend(parse_plancond_ocr(paddle_txt))  # legacy A-J 地块 6 列行解析（在 Paddle 文本上）
            rows_ = _dedup_rows(rows_)
            # 单行合理性过滤（面积范围/年份误读/数字粘连）——无条件执行
            rows_ = [r for r in rows_ if _row_plausible(r["vals"])]
            if rows_:
                # 合计校验闸门：行合计必须与函"总计"行一致（±1%），
                # 否则整组弃用（防止 OCR 错位/编号泄漏的垃圾数值入库）
                totals = _parse_plancond_totals(paddle_txt)
                if totals:
                    sum_land = sum(float(r["vals"].get("land") or 0) for r in rows_)
                    sum_floor = sum(float(r["vals"].get("floor") or 0) for r in rows_)
                    ok = (abs(sum_land - totals["land"]) / totals["land"] <= 0.01
                          and abs(sum_floor - totals["floor"]) / totals["floor"] <= 0.01)
                    if not ok:
                        rows_ = []
                        notes_all.append(
                            "宗地级行合计与函总计不符（land %.0f vs %.0f / floor %.0f vs %.0f），"
                            "行解析弃用，PDF 入库备查" % (
                                sum_land, totals["land"], sum_floor, totals["floor"]))
                    else:
                        notes_all.append(
                            "PaddleOCR 指标表行解析（合计校验通过 land %.0f/floor %.0f，中置信，待人工核验）"
                            % (sum_land, sum_floor))
                        # 公告级面积与函总计不一致时提示归属核对（共用函场景）
                        zb0 = parse_announcement_labels(pdftotext(zb_pdf)) if zb_pdf else {}
                        if zb0.get("land") and abs(float(zb0["land"]) - totals["land"]) / totals["land"] > 0.01:
                            notes_all.append(
                                "公告级面积（%s）与函总计（%.2f）不一致，宗地级归属以挂牌公告宗地范围为准"
                                % (zb0["land"], totals["land"]))
                else:
                    notes_all.append(
                        "函总计行未解析到，宗地级行按单行合理性过滤后保留 %d 行（中置信，待人工核验）"
                        % len(rows_))
            else:
                notes_all.append("指标未能解析（PaddleOCR 未匹配指标表行或行不满足合理性过滤）")
    else:
        rows_ = []

    # 过滤空行：严格解析失败时不输出占位行（notes 已如实说明）
    rows_ = [r for r in rows_ if r.get("code") or any(r.get("vals", {}).values())]

    # 公告级行（挂牌/招标文件文本层标签直读——可靠）
    zb_text = pdftotext(zb_pdf) if zb_pdf else ""
    zb_labels = parse_announcement_labels(zb_text) or parse_labels(zb_text)
    if zb_labels:
        crow = dict(base)
        crow["doc_no"] = doc_no
        crow["land_area_sqm"] = zb_labels.get("land", "")
        crow["floor_area_sqm"] = zb_labels.get("floor", "")
        crow["extraction_notes"] = "; ".join(notes_all + ["公告级指标来自%s 文本层" % zb_pdf.name])
        rows.append(crow)

    if not zb_labels and not rows_:
        row = dict(base)
        row["doc_no"] = doc_no
        row["extraction_notes"] = "; ".join(notes_all) or "ZIP 内未找到规划条件/多规合一函/挂牌文件"
        return [row]

    for r in rows_:
        vals = r["vals"]
        row = dict(base)
        row["parcel_code"] = r.get("code", "")
        row["land_use_code"] = r.get("lu", "")
        row["far"] = vals.get("far", "")
        row["building_height_m"] = vals.get("h", "")
        row["building_density_pct"] = vals.get("density", "")
        row["green_ratio_pct"] = vals.get("green", "")
        row["land_area_sqm"] = vals.get("land", "")
        row["floor_area_sqm"] = vals.get("floor", "")
        row["doc_no"] = doc_no
        row["extraction_notes"] = "; ".join(notes_all) + ("；PDF=%s" % parsed_pdf_name)
        rows.append(row)

    return rows


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=str(LIST_DEFAULT))
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（测试用）")
    ap.add_argument("--only", default="", help="只处理指定公告号子串（测试用）")
    args = ap.parse_args()

    recs = json.loads(Path(args.list).read_text(encoding="utf-8"))
    targets = []
    for rec in recs:
        m2 = rec.get("memo2") or ""
        if not m2:
            continue
        landid = rec.get("landid") or ""
        notice_no = parse_notice_no(landid) or landid
        if notice_no in DONE_NOTICES:
            continue
        targets.append(rec)

    if args.limit:
        targets = targets[:args.limit]
    if args.only:
        targets = [r for r in targets if args.only in (r.get("landid") or "")]

    log("待处理 %d 条历史公告交易文件 ZIP" % len(targets))
    all_rows: list[dict] = []
    for i, rec in enumerate(targets, 1):
        landid = rec.get("landid") or ""
        notice_no = parse_notice_no(landid) or landid
        m2 = rec.get("memo2") or ""
        corridor = corridor_judge((rec.get("title") or "") + (rec.get("landlocation") or ""))
        log("[%d/%d] %s %s（corridor=%s）" % (i, len(targets), notice_no, (rec.get("title") or "")[:36], corridor))

        safe = re.sub(r"[^\w\-\[\]（）()]", "_", notice_no) + ".zip"
        zip_path = ZIP_DIR / safe
        pdfs: list[Path] = []
        for cycle in range(3):
            if not (zip_path.exists() and zip_path.stat().st_size > 0):
                if not curl_download(m2, zip_path):
                    log("  下载失败，跳过")
                    break
            log("  ZIP %.1fMB → %s" % (zip_path.stat().st_size / 1048576, zip_path))
            xdir = EXTRACT_DIR / safe[:-4]
            if xdir.exists():
                shutil.rmtree(xdir)
            pdfs = unzip(zip_path, xdir)
            if pdfs:
                break
            # CRC 校验失败/解包失败 → 删除重下
            log("  ZIP 校验或解包失败，删除重下（周期 %d）" % (cycle + 1))
            zip_path.unlink(missing_ok=True)
        if not pdfs:
            log("  ZIP 未取得可用 PDF，跳过")
            continue
        picked = pick_attachments(pdfs)
        if not picked:
            log("  未匹配到 规划条件/多规合一函/招标文件 关键词，跳过")
            continue
        log("  匹配附件：%s" % {k: p.name for k, p in picked.items()})

        # 入库：拷贝 <8MB PDF 到 data/sources/land-transfer/
        yymm = re.sub(r"\D", "", notice_no)[-6:]
        for kind, p in picked.items():
            if file_mb(p) > MAX_PDF_MB:
                continue
            dest = OUT_DIR / ("%s_%s.pdf" % (kind, yymm))
            shutil.copyfile(p, dest)
            log("  入库 %s" % dest.name)

        source_url = "zkdncmsUploadFile/tdscjywj/" + m2.split("tdscjywj/")[-1]
        rows = build_rows(rec, picked, notice_no, corridor, source_url)
        for r in rows:
            r["notice_no"] = notice_no
        all_rows.extend(rows)
        log("  → %d 行" % len(rows))

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in all_rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLS})
    log("完成：%d 条公告 → %d 行 → %s" % (len(targets), len(all_rows), OUT_CSV))


if __name__ == "__main__":
    main()
