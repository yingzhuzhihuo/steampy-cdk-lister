#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送前自检：仓库里不能出现登录态、真实 CDKey、绝对用户路径。

用法：
    python scripts/check_no_secrets.py            # 扫描仓库根目录
    python scripts/check_no_secrets.py path       # 扫描指定目录

退出码 0 = 干净，1 = 发现可疑内容（不要提交 / 不要推送）。
"""
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKIP_DIRS = {".git", "work", "edgeprofile", "__pycache__", ".venv", "venv", "node_modules"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".zip", ".xlsx", ".db", ".ldb", ".log"}
MAX_BYTES = 2_000_000

PATTERNS = [
    ("疑似 accessToken（32 位十六进制）", re.compile(r"\b[0-9a-f]{32}\b"), "token"),
    ("疑似真实 CDKey（5-5-5 大写字母数字）", re.compile(r"\b[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{5}\b"), "cdkey"),
    ("Windows 绝对用户路径（含用户名）", re.compile(r"[A-Za-z]:\\Users\\[^\\\s\"']+\\"), "path"),
    ("疑似 localStorage 导出", re.compile(r'"accessToken"\s*:\s*"[0-9a-f]{8}'), "token"),
]

# 占位符 / 示例值白名单
ALLOW = [
    # 每组字符全相同：XXXXX-XXXXX-XXXXX / YYYYY-YYYYY-YYYYY / AAAAA-...
    re.compile(r"^(.)\1{4}-(.)\2{4}-(.)\3{4}$"),
    # 官方占位风格：AAAAA-BBBBB-CCCCC
    re.compile(r"^A{5}-B{5}-C{5}$"),
    re.compile(r"^TEST[A-Z]-"),
]


def allowed(text):
    return any(p.match(text) or p.search(text) for p in ALLOW)


def scan(root):
    findings = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT:
                findings.append(("禁止纳入版本库的二进制/产物", path, "—"))
                continue
            try:
                if os.path.getsize(path) > MAX_BYTES:
                    continue
                with open(path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception:
                continue
            for label, rx, kind in PATTERNS:
                for m in rx.finditer(text):
                    hit = m.group(0)
                    if kind in ("token", "cdkey") and allowed(hit):
                        continue
                    line_no = text[:m.start()].count("\n") + 1
                    findings.append((label, path, f"line {line_no}: {hit[:60]}"))
    return findings


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    findings = scan(root)
    if not findings:
        print(f"[OK] {root} 未发现登录态 / 真实 key / 绝对用户路径")
        return 0
    print(f"[!] {root} 发现 {len(findings)} 处可疑内容，先处理再提交：\n")
    seen = set()
    for label, path, where in findings:
        key = (label, path)
        if key in seen:
            continue
        seen.add(key)
        print(f"  - {label}\n      {os.path.relpath(path, root)}  {where}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
