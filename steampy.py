# -*- coding: utf-8 -*-
"""steampy CDKey 自动上架 CLI.

配合 driver.py（长驻浏览器驱动）使用。所有真正的接口请求都在已登录的页面里
通过 XHR 发出，因此自动带上 cookie 和必需的 accessToken 头。

典型流程：
    python steampy.py ping                      # 驱动活着吗、当前页面
    python steampy.py login                     # 确保已登录（没登录就弹窗让人工登录）
    python steampy.py search --q "Monster Hunter Rise Deluxe Kit"
    python steampy.py plan --items items.json --out plan.json
    python steampy.py list --plan plan.json                       # 默认 dry-run
    python steampy.py list --plan plan.json --execute             # 真上架
    python steampy.py verify --plan plan.json --results results.json
    python steampy.py report --plan plan.json --results results.json --out 上架结果.xlsx

items.json 形如：
[
 {"n":1,"label":"怪物猎人：崛起-标准版","key":"XXXXX-XXXXX-XXXXX",
  "query":"Monster Hunter Rise","match":"MONSTER HUNTER RISE"},
 {"n":2,"label":"生化危机4-标准版","key":"YYYYY-YYYYY-YYYYY","gameId":"595680664305537024"},
 {"n":3,"label":"小黑盒加速器3天","key":"ZZZZZ"}
]
- gameId：直接指定平台条目（最稳，推荐歧义项用这个）
- query + match：按查询词搜索，再用英文名/中文名精确匹配
- 只有 key 没有 query/gameId：计划阶段标为 not_found，不会提交
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
JS_DIR = os.path.join(HERE, "js")
WORK = os.path.abspath(os.path.join(HERE, "..", "work"))
DEFAULT_PORT = 8899
MIN_GAP = 11.5  # 平台限制两次挂单间隔 10 秒，留点余量


# ---------------------------------------------------------------- driver I/O

def driver(payload, port=None, timeout=300):
    port = port or DEFAULT_PORT
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/", data=data,
        headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def bridge(action, port=None, **kw):
    """Run bridge.js in the page with an action payload."""
    with open(os.path.join(JS_DIR, "bridge.js"), encoding="utf-8") as f:
        js = f.read().lstrip("\ufeff")
    arg = {"action": action}
    arg.update(kw)
    res = driver({"cmd": "eval", "js": js, "arg": json.dumps(arg, ensure_ascii=False)},
                 port=port, timeout=kw.pop("_timeout", 300))
    if not res.get("ok"):
        raise SystemExit(f"[bridge:{action}] {res.get('error')}")
    return res.get("result")


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def save(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def money(x):
    if x in (None, ""):
        return "-"
    return f"{float(x):.2f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------- commands

def cmd_ping(a):
    try:
        r = driver({"cmd": "ping"}, port=a.port, timeout=15)
    except Exception as e:
        print(f"驱动未运行（{e}）。先执行： python driver.py --port {a.port}")
        return 1
    print("driver OK:", json.dumps(r.get("pages"), ensure_ascii=False))
    try:
        st = bridge("loginState", port=a.port)
    except SystemExit as e:
        print(f"当前页面不可用（{e}）→ 先导航到站点： python steampy.py login")
        return 1
    print("loginState:", json.dumps(st, ensure_ascii=False))
    return 0 if st.get("loggedIn") else 2


def cmd_login(a):
    try:
        st = bridge("loginState", port=a.port)
    except SystemExit:
        st = {"loggedIn": False}
    if st.get("loggedIn"):
        print(f"已登录：{st.get('url')}")
        return 0
    print("请在打开的 Edge 窗口里登录 steampy.com（账号密码 + 图形验证码，或手机号登录）。")
    print("窗口停在这里，登录成功后我会自动继续：")
    driver({"cmd": "goto", "url": "https://steampy.com/login", "wait_ms": 1500}, port=a.port)
    deadline = time.time() + a.wait
    while time.time() < deadline:
        time.sleep(3)
        try:
            st = bridge("loginState", port=a.port)
        except SystemExit:
            continue
        if st.get("loggedIn"):
            print(f"登录成功：{st.get('url')}")
            return 0
        print("  等待登录…", end="\r", flush=True)
    print(f"\n等待超时（{a.wait}s），请登录后重跑本命令。")
    return 1


def cmd_whoami(a):
    w = bridge("whoami", port=a.port)
    print("当前登录账号：", json.dumps(w, ensure_ascii=False))
    r = bridge("listself", port=a.port, pages=1, size=1)
    print(f"listSelf 可见挂单数：{r.get('total')}")
    if w.get("hasToken") and (r.get("total") or 0) == 0:
        print("警告：有 token 但挂单数为 0 —— 可能是旧会话已被踢（同账号别处登录会失效），建议重新 login。")
        return 2
    return 0


def cmd_search(a):
    r = bridge("search", port=a.port, q=a.q, size=a.size)
    items = r.get("items") or []
    print(f'查询 "{a.q}"：命中 {r.get("total")} 条，显示 {len(items)} 条')
    print(f'{"gameId":<20}{"app":<9}{"type":<7}{"原价":>7}{"最低价":>8}{"挂单价":>8}  英文名 / 中文名')
    for g in items:
        print(f'{str(g["id"]):<20}{str(g["app"] or ""):<9}{str(g["type"] or ""):<7}'
              f'{money(g["ori"]):>7}{money(g["lp"]):>8}{money(g["tx"]):>8}  '
              f'{(g["en"] or "")[:46]} | {g["cn"] or ""}')
    print("\n提示：上架价格取“挂单价”列（= 页面顶部“平台最低价”= keyTxAmt）。")
    return 0


def resolve_item(it, port):
    """Return dict(n,label,key,gameId,en,cn,price,status,candidates?)"""
    rec = {"n": it.get("n"), "label": it.get("label") or "", "key": it.get("key") or "",
           "gameId": it.get("gameId"), "status": "pending"}
    if it.get("price"):
        rec["fixedPrice"] = float(it["price"])
    if rec["gameId"]:
        g = bridge("getone", port=port, ids=[rec["gameId"]])["items"][0]
        rec.update({"en": g.get("en"), "cn": g.get("cn"), "app": g.get("app")})
    elif it.get("query"):
        r = bridge("search", port=port, q=it["query"], size=it.get("size", 10))
        cands = r.get("items") or []
        want = (it.get("match") or "").strip()
        pick = None
        if want:
            for g in cands:
                if want in ((g.get("en") or "").strip(), (g.get("cn") or "").strip()):
                    pick = g
                    break
        if pick is None and len(cands) == 1:
            pick = cands[0]
        if pick is None:
            rec["status"] = "needs_review"
            rec["candidates"] = [{"id": g["id"], "en": g["en"], "cn": g["cn"],
                                 "app": g["app"], "tx": g["tx"], "type": g["type"]} for g in cands[:8]]
            return rec
        rec["gameId"] = pick["id"]
        rec.update({"en": pick.get("en"), "cn": pick.get("cn"), "app": pick.get("app")})
    else:
        rec["status"] = "not_found"
        rec["reason"] = "items.json 里既没有 gameId 也没有 query"
        return rec

    # fresh price from getOne
    g = bridge("getone", port=port, ids=[rec["gameId"]])["items"][0]
    rec.update({"en": g.get("en") or rec.get("en"), "cn": g.get("cn") or rec.get("cn"),
                "app": g.get("app") or rec.get("app"), "lp": g.get("lp"), "ave": g.get("ave")})
    price = rec.get("fixedPrice") if rec.get("fixedPrice") else g.get("tx")
    rec["price"] = price
    if not price or float(price) < 0.1:
        rec["status"] = "no_price"
        rec["reason"] = "平台无有效最低价（keyTxAmt 为空或 < 0.1）"
    else:
        rec["status"] = "ok"
    return rec


def cmd_plan(a):
    items = load(a.items)
    if isinstance(items, dict):
        items = items.get("items", [])
    plan = []
    for it in items:
        rec = resolve_item(it, a.port)
        plan.append(rec)
        flag = {"ok": "OK  ", "needs_review": "待确认", "not_found": "未找到", "no_price": "无价格"}.get(rec["status"], rec["status"])
        print(f'{flag:<5}{str(rec.get("n")):<3}{(rec.get("label") or "")[:30]:<32}'
              f'{money(rec.get("price")):>7}  {(rec.get("en") or "")[:40]}')
        if rec["status"] == "needs_review":
            for c in rec["candidates"]:
                print(f'        候选 id={c["id"]} app={c["app"]} tx={c["tx"]} | {c["en"]} | {c["cn"]}')
    save(a.out, {"generated": time.strftime("%Y-%m-%d %H:%M:%S"), "items": plan})
    n_ok = sum(1 for r in plan if r["status"] == "ok")
    print(f"\n计划已写入 {a.out}：可上架 {n_ok} / {len(plan)}")
    amb = [r for r in plan if r["status"] == "needs_review"]
    if amb:
        print("有歧义项，请在 items.json 里给它们补 gameId（或用 match 精确指定），然后重跑 plan：")
        for r in amb:
            print(f'  #{r["n"]} {r["label"]}')
    return 0


def classify(res):
    msg = (res.get("message") or "")
    if res.get("success"):
        return "listed"
    if re.search(r"间隔|等待|频繁|稍后", msg):
        return "rate_limited"
    if re.search(r"已.*(上架|挂单|存在)|重复|已有", msg):
        return "duplicate"
    return "failed"


def cmd_list(a):
    plan = load(a.plan)["items"]
    todo = [r for r in plan if r["status"] == "ok"]
    if a.only:
        want = {int(x) for x in str(a.only).split(",") if x.strip()}
        todo = [r for r in todo if int(r["n"]) in want]
    if a.limit:
        todo = todo[:a.limit]
    results = []
    if os.path.exists(a.results) and not a.fresh:
        results = load(a.results).get("items", [])
    done = {str(r["n"]) for r in results if r.get("status") in ("listed", "duplicate")}
    todo = [r for r in todo if str(r["n"]) not in done]

    print(f"待提交 {len(todo)} 条；间隔 {a.gap}s；"
          f"{'执行' if a.execute else 'DRY-RUN（不提交，加 --execute 才真上架）'}")
    last_submit = 0.0
    for i, r in enumerate(todo, 1):
        if not a.execute:
            print(f'  [{i}/{len(todo)}] #{r["n"]} {r["label"][:26]} → {r["gameId"]} @ {money(r["price"])}')
            results.append({**r, "status": "dry_run", "message": "dry-run"})
            continue

        # refresh price right before submitting (market moves)
        try:
            g = bridge("getone", port=a.port, ids=[r["gameId"]])["items"][0]
            if g.get("tx") and float(g["tx"]) >= 0.1:
                r["priceFresh"] = g["tx"]
        except SystemExit:
            pass
        price = r.get("fixedPrice") or r.get("priceFresh") or r["price"]

        rec = None
        for attempt in range(3):
            wait = a.gap - (time.time() - last_submit) if last_submit else 0
            if wait > 0:
                time.sleep(wait)
            res = bridge("startsell", port=a.port, gameId=r["gameId"], key=r["key"], price=price)
            last_submit = time.time()
            kind = classify(res)
            rec = {**r, "status": kind, "message": res.get("message"),
                   "saleId": res.get("saleId"), "submittedPrice": price, "attempts": attempt + 1,
                   "time": time.strftime("%Y-%m-%d %H:%M:%S")}
            if kind == "rate_limited":
                print(f'  [{i}/{len(todo)}] #{r["n"]} 触发限流，等 {a.gap}s 重试…')
                last_submit = 0
                continue
            break
        results = [x for x in results if str(x.get("n")) != str(r["n"])]
        results.append(rec)
        save(a.results, {"items": results})
        tag = {"listed": "已上架", "duplicate": "重复跳过", "failed": "失败"}.get(rec["status"], rec["status"])
        print(f'  [{i}/{len(todo)}] #{r["n"]} {r["label"][:24]:<26} {money(price):>6}  {tag}  {rec.get("message") or ""}')

    save(a.results, {"items": results})
    ok = sum(1 for x in results if x.get("status") == "listed")
    dup = sum(1 for x in results if x.get("status") == "duplicate")
    bad = sum(1 for x in results if x.get("status") == "failed")
    print(f"\n结果写入 {a.results}：成功 {ok}，重复跳过 {dup}，失败 {bad}")
    return 0


def cmd_verify(a):
    plan = load(a.plan)["items"]
    results = load(a.results)["items"] if os.path.exists(a.results) else []
    rmap = {str(x.get("n")): x for x in results}
    rows = bridge("listself", port=a.port, pages=a.pages, size=50)["rows"]
    out = []
    for r in plan:
        if r["status"] != "ok":
            out.append({**r, "verified": False, "verifyNote": "未提交"})
            continue
        cands = [x for x in rows if str(x.get("gameId")) == str(r["gameId"])]
        price = (rmap.get(str(r["n"])) or {}).get("submittedPrice") or r.get("price")
        exact = [x for x in cands if x.get("price") is not None and abs(float(x["price"]) - float(price)) < 0.005]
        hit = (exact or cands)
        hit.sort(key=lambda x: x.get("time") or "")
        last = hit[-1] if hit else None
        out.append({**r, "verified": bool(last),
                    "saleId": (last or {}).get("id"), "listTime": (last or {}).get("time"),
                    "listStock": (last or {}).get("stock"), "listPrice": (last or {}).get("price"),
                    "priceMatched": bool(exact)})
    save(os.path.join(os.path.dirname(a.results) or ".", "verified.json"), {"items": out})
    ok = sum(1 for x in out if x.get("verified"))
    for x in out:
        mark = "OK  " if x.get("verified") else "MISS"
        print(f'{mark}{str(x.get("n")):<3}{(x.get("label") or "")[:28]:<30}{money(x.get("price")):>7}  '
              f'{x.get("listTime") or x.get("status")}  {x.get("saleId") or ""}')
    print(f"\n核对：{ok} / {sum(1 for x in out if x.get('status') == 'ok')} 条已确认在售")
    return 0


def cmd_report(a):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    plan = load(a.plan)["items"]
    results = load(a.results)["items"] if os.path.exists(a.results) else []
    rmap = {str(x.get("n")): x for x in results}
    vpath = os.path.join(os.path.dirname(a.results) or ".", "verified.json")
    vmap = {}
    if os.path.exists(vpath):
        vmap = {str(x.get("n")): x for x in load(vpath)["items"]}

    wb = Workbook()
    ws = wb.active
    ws.title = "上架结果"
    HDR = ["序号", "原始名称", "CDKey", "上架游戏（平台英文名）", "平台中文名", "gameId",
           "上架价格(元)", "状态", "挂单号", "上架时间", "备注"]
    ws.append(HDR)
    head_fill = PatternFill("solid", fgColor="1F4E79")
    head_font = Font(color="FFFFFF", bold=True)
    thin = Side(style="thin", color="BFBFBF")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    ok_fill = PatternFill("solid", fgColor="E2EFDA")
    skip_fill = PatternFill("solid", fgColor="FFF2CC")
    for c in ws[1]:
        c.fill, c.font, c.border = head_fill, head_font, border
        c.alignment = Alignment(horizontal="center", vertical="center")

    total_ok, total_amt = 0, 0.0
    for r in plan:
        n = str(r.get("n"))
        v = vmap.get(n, {})
        res = rmap.get(n, {})
        st = r["status"]
        if st == "ok" and v.get("verified"):
            status, sale_id, when = "已上架", v.get("saleId"), v.get("listTime")
            fill = ok_fill
            total_ok += 1
            total_amt += float(res.get("submittedPrice") or r.get("price") or 0)
        elif st == "ok" and res.get("status") == "duplicate":
            status, sale_id, when, fill = "重复跳过", "", "", skip_fill
        elif st == "ok":
            status, sale_id, when, fill = "已提交待核对", res.get("saleId") or "", res.get("time") or "", skip_fill
        else:
            status, sale_id, when, fill = {"not_found": "已跳过（平台无此游戏）",
                                           "needs_review": "待确认（多候选）",
                                           "no_price": "已跳过（无有效价格）"}.get(st, st), "", "", skip_fill
        note = r.get("reason") or ""
        if r.get("candidates"):
            note = "候选：" + "; ".join(f'{c["id"]}={c["en"]}' for c in r["candidates"][:4])
        ws.append([r.get("n"), r.get("label"), r.get("key"), r.get("en") or "", r.get("cn") or "",
                   r.get("gameId") or "", r.get("price") if st == "ok" else "", status,
                   sale_id or "", when or "", note])
        for c in ws[ws.max_row]:
            c.border, c.fill = border, fill
            c.alignment = Alignment(vertical="center", wrap_text=c.column in (2, 4, 5, 11))

    widths = [6, 34, 22, 42, 28, 20, 12, 18, 24, 20, 48]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:K{ws.max_row}"

    ws2 = wb.create_sheet("汇总")
    for row in [("统计项", "数值"), ("条目总数", len(plan)), ("成功上架", total_ok),
                ("跳过/待确认", len(plan) - total_ok),
                ("上架价格合计(元)", round(total_amt, 2)),
                ("预计到账合计(元)", round(total_amt * 0.97, 2)),
                ("价格口径", "详情页顶部“平台最低价”= 接口 keyTxAmt"),
                ("生成时间", time.strftime("%Y-%m-%d %H:%M:%S"))]:
        ws2.append(list(row))
    for c in ws2[1]:
        c.fill, c.font = head_fill, head_font
    ws2.column_dimensions["A"].width = 22
    ws2.column_dimensions["B"].width = 44

    out = a.out
    if not out.lower().endswith(".xlsx"):
        out += ".xlsx"
    wb.save(out)
    print(f"已生成 {out}：成功上架 {total_ok} 条，合计 ¥{round(total_amt, 2)}，"
          f"预计到账 ¥{round(total_amt * 0.97, 2)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="steampy CDKey 自动上架")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ping", help="检查驱动与登录状态").set_defaults(fn=cmd_ping)

    sub.add_parser("whoami", help="当前账号 + 能看到多少挂单（判断会话是否有效）").set_defaults(fn=cmd_whoami)

    p = sub.add_parser("login", help="确保已登录（必要时人工登录）")
    p.add_argument("--wait", type=int, default=300)
    p.set_defaults(fn=cmd_login)

    p = sub.add_parser("search", help="按名字搜索平台游戏条目")
    p.add_argument("--q", required=True)
    p.add_argument("--size", type=int, default=10)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("plan", help="把 key 清单解析成上架计划（不提交）")
    p.add_argument("--items", required=True)
    p.add_argument("--out", default="plan.json")
    p.set_defaults(fn=cmd_plan)

    p = sub.add_parser("list", help="按计划上架（默认 dry-run）")
    p.add_argument("--plan", required=True)
    p.add_argument("--results", default="results.json")
    p.add_argument("--execute", action="store_true", help="真正提交")
    p.add_argument("--gap", type=float, default=MIN_GAP)
    p.add_argument("--only", default="", help="只处理这些序号，如 3,7,9")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--fresh", action="store_true", help="忽略已有 results 重跑")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("verify", help="回查挂单列表核对")
    p.add_argument("--plan", required=True)
    p.add_argument("--results", default="results.json")
    p.add_argument("--pages", type=int, default=10)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("report", help="导出 xlsx 结果表")
    p.add_argument("--plan", required=True)
    p.add_argument("--results", default="results.json")
    p.add_argument("--out", default="上架结果.xlsx")
    p.set_defaults(fn=cmd_report)

    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
