"""Playwright browser driver for the steampy CDKey listing workflow.

Keeps ONE headed Microsoft Edge (Playwright persistent context) alive and exposes
a tiny JSON-over-HTTP command interface on 127.0.0.1:<port>, so that separate
`steampy.py` invocations can drive the same logged-in browser session.

Run it as a long-lived background process:
    python driver.py            (default port 8899)
    python driver.py --port 8901

The browser profile lives in <workdir>/edgeprofile; the steampy login session
persists there between runs, so a manual login is only needed once in a while.
"""
import argparse
import asyncio
import json
import os
import traceback

from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "work")
PROFILE = os.path.join(WORK, "edgeprofile")

state = {"pw": None, "ctx": None, "pages": {}}


async def boot(port, headless, profile_dir):
    os.makedirs(profile_dir, exist_ok=True)
    pw = await async_playwright().start()
    ctx = await pw.chromium.launch_persistent_context(
        user_data_dir=profile_dir,
        channel="msedge",
        headless=headless,
        viewport={"width": 1600, "height": 950},
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        ignore_default_args=["--enable-automation"],
    )
    state["pw"] = pw
    state["ctx"] = ctx
    state["port"] = port
    state["headless"] = headless
    state["profile"] = profile_dir
    pages = ctx.pages
    page = pages[0] if pages else await ctx.new_page()
    state["pages"]["a"] = page
    # a same-origin page is required for localStorage / XHR against /xboot
    try:
        await page.goto("https://steampy.com/home", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"WARN: 初始导航失败（{e}），后续用 login 命令再导航", flush=True)
    return port


async def ensure_page(name="a"):
    """Return a live page for `name`, recreating it (and the browser, if needed)
    when the user closed the window or the context died."""
    p = state["pages"].get(name)
    if p is not None and not p.is_closed():
        return p

    ctx = state.get("ctx")
    alive = ctx is not None and not _ctx_dead()
    if not alive:
        print("WARN: 浏览器已关闭，正在重启…", flush=True)
        await boot(state["port"], state["headless"], state["profile"])
        return state["pages"].get("a") or await state["ctx"].new_page()

    live = [x for x in ctx.pages if not x.is_closed()]
    if live:
        state["pages"][name] = live[0]
        return live[0]

    p = await ctx.new_page()
    state["pages"][name] = p
    try:
        await p.goto("https://steampy.com/home", wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"WARN: 重建页面后导航失败（{e}）", flush=True)
    return p


def _ctx_dead():
    try:
        _ = state["ctx"].pages
        return False
    except Exception:
        return True


async def handle(req):
    cmd = req.get("cmd")

    if cmd == "ping":
        pages = {}
        for k, v in state["pages"].items():
            try:
                pages[k] = "<closed>" if v.is_closed() else v.url
            except Exception:
                pages[k] = "<dead>"
        return {"ok": True, "pages": pages}

    if cmd == "newpage":
        name = req.get("name") or f"p{len(state['pages'])}"
        p = await ensure_page(name)
        if req.get("url"):
            await p.goto(req["url"], wait_until="domcontentloaded", timeout=60000)
        return {"ok": True, "name": name, "url": p.url}

    if cmd == "close":
        p = state["pages"].pop(req["page"], None)
        if p:
            await p.close()
        return {"ok": True, "pages": list(state["pages"])}

    if cmd == "goto":
        p = await ensure_page(req.get("page", "a"))
        await p.goto(req["url"], wait_until=req.get("wait_until", "domcontentloaded"),
                     timeout=req.get("timeout", 60000))
        if req.get("wait_ms"):
            await p.wait_for_timeout(req["wait_ms"])
        return {"ok": True, "url": p.url}

    if cmd == "eval":
        # evaluate a JS function source (string) with an optional JSON arg
        p = await ensure_page(req.get("page", "a"))
        if req.get("arg") is None:
            r = await p.evaluate(req["js"])
        else:
            r = await p.evaluate(req["js"], req["arg"])
        try:
            json.dumps(r)
        except Exception:
            r = str(r)
        return {"ok": True, "result": r}

    if cmd == "text":
        p = await ensure_page(req.get("page", "a"))
        return {"ok": True, "url": p.url, "text": await p.inner_text("body")}

    if cmd == "screenshot":
        p = await ensure_page(req.get("page", "a"))
        path = req.get("path") or os.path.join(WORK, "shot.png")
        await p.screenshot(path=path, full_page=bool(req.get("full")))
        return {"ok": True, "path": path, "url": p.url}

    if cmd == "setfiles":
        # 给 <input type=file> 直接塞本地文件（网页上传用）
        p = await ensure_page(req.get("page", "a"))
        loc = p.locator(req["selector"])
        if req.get("nth") is not None:
            loc = loc.nth(req["nth"])
        await loc.first.set_input_files(req["files"], timeout=req.get("timeout", 60000))
        await p.wait_for_timeout(req.get("wait_ms", 1500))
        return {"ok": True, "url": p.url}

    if cmd == "click":
        p = await ensure_page(req.get("page", "a"))
        loc = p.locator(req["selector"])
        if req.get("nth") is not None:
            loc = loc.nth(req["nth"])
        await loc.first.click(timeout=req.get("timeout", 20000))
        await p.wait_for_timeout(req.get("wait_ms", 1200))
        return {"ok": True, "url": p.url}

    if cmd == "fill":
        p = await ensure_page(req.get("page", "a"))
        loc = p.locator(req["selector"])
        if req.get("nth") is not None:
            loc = loc.nth(req["nth"])
        await loc.first.fill(req["value"], timeout=req.get("timeout", 20000))
        return {"ok": True}

    if cmd == "press":
        p = await ensure_page(req.get("page", "a"))
        await p.keyboard.press(req["key"])
        await p.wait_for_timeout(req.get("wait_ms", 800))
        return {"ok": True}

    if cmd == "wait":
        p = await ensure_page(req.get("page", "a"))
        if req.get("ms"):
            await p.wait_for_timeout(req["ms"])
        if req.get("selector"):
            await p.wait_for_selector(req["selector"], timeout=req.get("timeout", 20000),
                                      state=req.get("state", "visible"))
        return {"ok": True}

    return {"ok": False, "error": f"unknown cmd {cmd}"}


async def http_handler(reader, writer):
    try:
        head = await reader.readuntil(b"\r\n\r\n")
        lines = head.decode("latin-1").split("\r\n")
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
        n = int(headers.get("content-length", "0"))
        body = await reader.readexactly(n) if n else b""
        try:
            req = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            req = {}
        if "js" in req and isinstance(req["js"], str) and req["js"].startswith("\ufeff"):
            req["js"] = req["js"].lstrip("\ufeff")
        try:
            res = await handle(req)
        except Exception as e:
            res = {"ok": False, "error": str(e), "trace": traceback.format_exc()[-1500:]}
        payload = json.dumps(res, ensure_ascii=False).encode("utf-8")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n"
                     b"Content-Length: " + str(len(payload)).encode() + b"\r\n\r\n" + payload)
        await writer.drain()
    except Exception:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def main(port, headless, profile_dir):
    await boot(port, headless, profile_dir)
    srv = await asyncio.start_server(http_handler, "127.0.0.1", port)
    print(f"DRIVER_READY port={port} profile={profile_dir}", flush=True)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("DRIVER_PORT", "8899")))
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--profile", default=PROFILE,
                    help="Edge 用户数据目录；指向已有登录态的 profile 可免重复登录")
    a = ap.parse_args()
    try:
        asyncio.run(main(a.port, a.headless, os.path.abspath(a.profile)))
    except KeyboardInterrupt:
        pass
