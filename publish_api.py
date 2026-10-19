#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 GitHub REST API 建仓库并上传本目录文件 —— 不需要安装 git。

前置：环境变量 GH_TOKEN 里放一个 Fine-grained PAT，需要
  Contents: Read and write
  Administration: Read and write   （仅“新建仓库”需要）

用法：
    $env:GH_TOKEN = "github_pat_xxx"
    python publish_api.py --owner <用户名> --repo steampy-cdk-lister
    python publish_api.py --owner <用户名> --repo steampy-cdk-lister --dry-run
    python publish_api.py --owner <用户名> --repo new-name --private

提醒：上传前会强制跑一次 check_no_secrets.py，不干净就中止。
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

API = "https://api.github.com"
SKIP_DIRS = {".git", "work", "edgeprofile", "__pycache__", ".venv", "venv"}
SKIP_EXT = {".xlsx", ".log", ".db", ".ldb", ".png", ".jpg", ".zip"}
ROOT = os.path.dirname(os.path.abspath(__file__))


def call(method, path, token, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode("utf-8")
            return r.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"message": body[:400]}


def collect():
    files = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in SKIP_EXT:
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            files.append((rel, full))
    files.sort()
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--description",
                    default="Batch-list Steam CDKeys on SteamPY seller center, "
                            "priced by CDKey market top price, rate-limit aware.")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    # 1) 强制自检
    checker = os.path.join(ROOT, "check_no_secrets.py")
    rc = subprocess.call([sys.executable, checker, ROOT])
    if rc != 0:
        print("\n[中止] 自检未通过，先清理再上传（尤其确认 work/ 没被包含进来）。")
        return 1

    files = collect()
    total = sum(os.path.getsize(f) for _, f in files)
    print(f"\n准备上传 {len(files)} 个文件，共 {total/1024:.1f} KB：")
    for rel, _ in files:
        print("   ", rel)

    if a.dry_run:
        print("\n[dry-run] 未发起任何网络请求。")
        return 0

    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        print("\n[错误] 未设置 GH_TOKEN。先 $env:GH_TOKEN = \"github_pat_xxx\"")
        return 1

    # 2) 建仓库（已存在则跳过）
    st, body = call("POST", "/user/repos", token, {
        "name": a.repo, "description": a.description,
        "private": bool(a.private), "auto_init": False,
    })
    if st not in (200, 201):
        if st == 422 and "already exists" in str(body.get("errors", body)).lower():
            print(f"\n仓库 {a.owner}/{a.repo} 已存在，继续上传文件")
        else:
            print(f"\n[错误] 建仓库失败 {st}: {body.get('message')}")
            return 1
    else:
        print(f"\n已创建仓库：{body.get('html_url')}")

    # 3) 逐个上传
    ok = 0
    for rel, full in files:
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")
        path = f"/repos/{a.owner}/{a.repo}/contents/{urllib.parse.quote(rel)}"
        # 覆盖已有文件需要 sha
        st0, meta = call("GET", path + f"?ref={a.branch}", token)
        payload = {"message": f"add {rel}", "content": content, "branch": a.branch}
        if st0 == 200 and isinstance(meta, dict) and meta.get("sha"):
            payload["sha"] = meta["sha"]
            payload["message"] = f"update {rel}"
        st1, res = call("PUT", path, token, payload)
        if st1 in (200, 201):
            ok += 1
            print(f"  ok  {rel}")
        else:
            print(f"  FAIL {rel}: {st1} {res.get('message')}")
    print(f"\n完成：{ok}/{len(files)} 个文件 → https://github.com/{a.owner}/{a.repo}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    sys.exit(main())
