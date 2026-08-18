#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PaddleOCR 批量识别 PDF（扫描件）→ 纯文本输出（一行=一个文本块）。

必须用安装了 paddleocr 的解释器运行（本机：/Volumes/innerdisk/anaconda3/bin/python）。

用法（单文件）：
  /Volumes/innerdisk/anaconda3/bin/python scripts/paddle_ocr_pdf.py <in.pdf> <out.txt> [max_pages]

用法（批量，复用同一模型实例，避免重复加载）：
  /Volumes/innerdisk/anaconda3/bin/python scripts/paddle_ocr_pdf.py <jobs.json>
  jobs.json = [{"pdf": "...", "out": "...", "max_pages": 3}, ...]

说明：200dpi 渲染 + ch 语言模型 + 方向分类；输出按页内文本块顺序排列。
首次运行会下载/加载模型，之后复用缓存。
"""
import json
import subprocess
import sys
import tempfile
import os


def run_job(ocr, pdf_path: str, out_txt: str, max_pages: int) -> int:
    """OCR 一页一页输出 TSV：y_center \\t x_center \\t text（按 y 升序）。

    输出坐标供上游按表格行聚类（y）+ 列排序（x）重建指标行。
    """
    with tempfile.TemporaryDirectory() as td:
        cmd = ["pdftoppm", "-r", "200", "-png", pdf_path, td + "/p"]
        if max_pages:
            cmd += ["-f", "1", "-l", str(max_pages)]
        subprocess.run(cmd, capture_output=True, timeout=300)
        out_lines: list[tuple[float, float, str]] = []
        for f in sorted(os.listdir(td)):
            if not f.endswith(".png"):
                continue
            try:
                res = ocr.ocr(os.path.join(td, f), cls=True)
            except Exception:  # noqa: BLE001
                continue
            for r in (res[0] or []):
                box = r[0]
                y = (box[0][1] + box[2][1]) / 2
                x = (box[0][0] + box[1][0]) / 2
                out_lines.append((y, x, r[1][0]))
    out_lines.sort(key=lambda b: (b[0], b[1]))
    with open(out_txt, "w", encoding="utf-8") as f:
        for y, x, txt in out_lines:
            f.write("%d\t%d\t%s\n" % (round(y), round(x), txt))
    return len(out_lines)


def main() -> None:
    from paddleocr import PaddleOCR  # 延迟导入，避免无 paddleocr 环境时报错

    args = sys.argv[1:]
    if len(args) >= 2 and args[0].endswith(".json"):
        jobs = json.loads(open(args[0], encoding="utf-8").read())
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        for j in jobs:
            n = run_job(ocr, j["pdf"], j["out"], int(j.get("max_pages", 0)))
            print("PaddleOCR: %d lines → %s" % (n, j["out"]), flush=True)
    elif len(args) >= 2:
        ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        n = run_job(ocr, args[0], args[1], int(args[2]) if len(args) > 2 else 0)
        print("PaddleOCR: %d lines → %s" % (n, args[1]), flush=True)
    else:
        sys.exit("用法：paddle_ocr_pdf.py <in.pdf> <out.txt> [max_pages] | <jobs.json>")


if __name__ == "__main__":
    main()
