---
name: steampy-cdk-lister
description: 在 SteamPY（steampy.com）卖家中心批量上架 Steam CDKey：按游戏名解析平台条目、抓 CDKey 市场“平台最低价”作为挂单价、按平台 10 秒限流自动节流提交、遇重复 key 跳过、搜不到的游戏标记跳过，最后回查挂单列表并导出 xlsx 结果表。当用户给出 CDKey 清单要挂到 steampy/SteamPY、要查某游戏 CDKey 市场最低价、或要核对已上架的 CDKey 时使用。
whenToUse: 用户提供一批 CDKey 要求上架到 steampy 售卖、要求按市场最低价挂单、要求批量核对/导出挂单结果时。不含改价、下架、订单处理（那些走同一套 driver，但需要另写步骤）。
metadata:
  platforms: steampy.com
  requires: Microsoft Edge, python3.10+, playwright, openpyxl
---

# SteamPY 批量上架 CDKey

这套东西把「卖家中心 → 卖家中心-CDK → 添加CDKey」的手工流程变成可复用脚本：
长驻一个已登录的 Edge（Playwright 持久化 profile），所有站点请求都在页面内用
XHR 发出（自动带 cookie 和必需的 `accessToken` 头），Python 侧只做编排。

## 0. 一句话流程

```
ping → login(人工) → 写 items.json → plan(解析+定价) → [确认歧义/价格] → list --execute → verify → report
```

## 1. 前置（只做一次）

```powershell
python -m pip install -r requirements.txt   # playwright + openpyxl
# 用系统已装的 Edge，不需要 playwright install
```

启动驱动（后台长驻，窗口会弹出来）：

```powershell
cd scripts
python driver.py --port 8899
```

profile 存在 `scripts/../work/edgeprofile`，登录态跨次保留；掉登录时重跑 `login` 让人工登一次。
想复用一份已有的登录态，加 `--profile "<某个已登录的 profile 目录>"` 即可免登录。

## 2. 登录（必须人工）

```powershell
& python steampy.py login --wait 300
```
**绝不向用户索要账号密码**，也不要尝试识别图形验证码。窗口停在登录页，让用户自己输，
脚本每 3 秒轮询直到 URL 离开 `/login`。用户说已登录时直接 `ping` 确认。

登录后用 `whoami` 复核会话是否真的有效：

```powershell
& python steampy.py whoami      # 打印账号 id/昵称 + listSelf 可见挂单数
```
`hasToken=true` 但挂单数为 0 → 旧会话已被踢（同一账号在别处登录会失效另一方），重新 `login`。
**同一时间只跑一个 driver**，多开会互相踢线。

## 3. 写 items.json

每项三种写法，优先用 `gameId`：

```json
[
  {"n": 1, "label": "星露谷物语-标准版", "key": "YYYYY-YYYYY-YYYYY",
   "gameId": "496138616573968"},
  {"n": 2, "label": "空洞骑士（用查询+匹配）", "key": "AAAAA-BBBBB-CCCCC",
   "query": "Hollow Knight", "match": "Hollow Knight"},
  {"n": 3, "label": "非 Steam 商品（会被跳过）", "key": "XXXXXXXXXXXXXXX"}
]
```

- `gameId`：平台条目 id，最稳。
- `query` + `match`：`match` 与平台的 `gameName`/`gameNameCn` 精确相等才采用。
- 只有 `key`：`plan` 会标 `not_found`，不提交（用于非 Steam 商品）。

## 4. plan：解析条目 + 定价（不提交）

```powershell
& python steampy.py search --q "生化危机启示录2"        # 先看候选
& python steampy.py plan --items items.json --out plan.json
```

`plan` 对每项给出 `ok / needs_review / not_found / no_price`。
`needs_review` 会打印候选（id、app、type、价格），此时**必须问用户**选哪个，
把选定的 id 写回 items.json 再重跑 —— 不要自己猜版本。

## 5. 价格口径（踩过的坑）

挂单价 = 游戏详情页**顶部**“平台最低价” ，接口字段 `keyTxAmt`。

它**不等于**：
- 卖家列表第一行的 CDkey 单价（通常低 0.5~1 元，例如某游戏表头 ¥15、顶部 ¥15.7）
- `keyPrice`（= “近期最低挂单价格”，可能有 ¥0.47 这种钓鱼价）

用户若说“和上面价格一样”，先确认是顶部那个数还是表格首行 —— 用一句话问清，
再用 `{"price": 15.7}` 固定下来，或依赖默认的 `keyTxAmt`。

## 6. list：上架（默认 dry-run）

```powershell
& python steampy.py list --plan plan.json                    # 只打印，不提交
& python steampy.py list --plan plan.json --execute --gap 11.5
```

- **平台硬限制：两次挂单间隔 10 秒**（早于 10 秒返回“CDKey挂单操作间隔为10秒…”）。
  脚本默认 11.5s 节流，撞限流会自动加重试（最多 3 次）。
- 返回 success=false 且提示含“已…上架/已存在/重复” → 记为 `duplicate` 并**继续下一个**。
- 每条结果即时写回 `results.json`，中断后可续跑（已完成的不重复提交）。
- 单次 tool 调用别跑太久：一批 ≤ 9 条（约 110 秒），否则会超时。用 `--only 3,7,9` 或
  `--limit` 拆批。

## 7. verify + report

```powershell
& python steampy.py verify --plan plan.json --results results.json
& python steampy.py report --plan plan.json --results results.json --out 上架结果.xlsx
```

`verify` 用 `listSelf` 接口按 `gameId` + 价格比对，输出 `verified.json`；
`report` 生成两个 sheet（上架结果 / 汇总），跳过项标黄并在备注列写明原因。

## 8. 版本 → 平台条目映射经验（最容易挂错的地方）

平台把本体、合集包、DLC 拆成不同条目，**挂错会被判货不对板、退款 + 罚金**。规则：

| 用户说法 | 平台条目 | 说明 |
|---|---|---|
| 某某-标准版 | 本体条目（`type=game`） | |
| 某某-豪华组合 / Deluxe Kit | 对应 **Deluxe Kit DLC 条目**（`type=dlc`） | 如 `MONSTER HUNTER RISE Deluxe Kit`、`Iceborne Deluxe Kit`、`SUNBREAK 豪华组合` |
| 某某-豪华版 | **豪华版条目**（可能是 game 或 bundle） | 与 Deluxe Kit 是两条不同记录，别混 |
| 某某-DLC | 纯 DLC 条目 | 如 `Monster Hunter World: Iceborne`（纯 DLC） |
| 章节 1 / Episode | 单独章节条目 | 如 `RER2 Episode One: Penal Colony` |
| 加速器 / 体验卡 / 非 Steam 商品 | 无条目 → `not_found` | 平台只收 Steam 游戏 key |

同名多版本时（如「生化危机4」同时有 2005 原版、2023 重置版、重置豪华版、黄金版），
**必须让用户确认**。判断依据是 `app`：`254700` = 2005 原版，`2050650` = 重置版系列。

## 9. 排障

| 现象 | 原因 / 处理 |
|---|---|
| `驱动未运行` | `driver.py` 没起或端口不对 → `--port` 对上 |
| 所有请求 `xhr_error` / `Failed to fetch` | 缺 `accessToken` 头，或页面停在未登录态 → `ping` 看 URL，`login` |
| `bridge: 返回 unknown action` | `bridge.js` 被改坏 → 从本 skill 恢复 |
| 挂单成功但列表里没有 | 用 `verify` 再确认；`listSelf` 有缓存，等 3~5 秒 |
| `listSelf` 返回 0 条但确实挂过单 | token 失效（同账号其他窗口登录会踢掉本会话）→ 重新 `login`，用 `whoami` 复核 |
| 页面 DOM 变了导致 UI 自动化失败 | 本套流程只依赖两个接口，不依赖 DOM，一般不受影响 |

## 10. 安全边界

- dry-run 默认开启，`--execute` 才真提交；提交前把「游戏/版本/价格/条数」跟用户复述一遍。
- 不替用户猜版本、不猜价格；歧义必须问。
- 不接触账号密码、不解除验证码、不批量下架或改价（需用户逐条确认）。
- 用户是账号本人、key 是自有库存时才执行。

接口细节见 `reference/api.md`，模板见 `work/template_items.json`。
