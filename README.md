# steampy-cdk-lister

在 [SteamPY（steampy.com）](https://steampy.com) 卖家中心批量上架 Steam CDKey 的命令行工具：
**按游戏名解析平台条目 → 抓市场“平台最低价”定价 → 按平台限流自动节流提交 → 回查核对 → 导出 xlsx 结果表**。

同时也是一个可直接装进 AI Agent（DSH skill 格式）的技能包，让智能体按固定流程跑，而不是每次重新摸接口。

> 面向自己的账号、自己的库存 key。请先阅读文末的[安全与合规](#安全与合规)。

---

## 核心卖点

### 1. 全流程真的跑通了，不是 demo

2026-10-19 的一次完整运行（可复现）：

| 指标 | 结果 |
|---|---|
| 输入 key | 22 个 |
| 成功上架 | **21 个** |
| 主动跳过（平台无此游戏，非 Steam 商品） | 1 个 |
| 回查核对一致 | **21 / 21** |
| 提交失败 | **0** |
| 挂单金额合计 | ¥427.96（扣 3% 手续费预计到账 ¥415.12） |

四条链路（解析 → 定价 → 提交 → 核对）都有对应命令和落盘产物，`verify` 能独立复跑验证。

### 2. 价格口径对齐，不是“大概取最低价”

CDKey 详情页上其实有**三个**价格，取错就是白亏钱：

| 页面位置 | 语义 | 例子 |
|---|---|---|
| 顶部大红字「平台最低价」 | 接口 `keyTxAmt` | **¥15.7** ← 本工具取这个 |
| 卖家列表第一行 CDkey 单价 | 当前最低挂单 | ¥15 |
| 「近期最低挂单价格」 | `keyPrice`，常有钓鱼价 | ¥0.47 |

工具直接对齐 `keyTxAmt`，并用真实页面文本回归验证过（某游戏 API `38` ↔ 页面顶部 `￥38`，而列表首行是 `￥37.88`）。
定价在提交前会**重新拉一次**，避免列表变动导致的时差。

### 3. 平台 10 秒限流自适应，批量不中断

平台对 `startSell` 有硬限制：两次挂单间隔 <10 秒直接拒绝（`CDKey挂单操作间隔为10秒…`）。
**这条限制没写在文档里，是实测撞出来的**——第一轮用 0.7s 间隔提交，连续被拒。

- 默认 11.5s 节流：21 条最终全部上架，0 失败
- 过程中仍有 2 次触发限流提示，自动退避重试后补上，不会卡住整批
- 分批建议（每批 ≤9 条）写在文档里，避免单次调用超时

### 4. 默认安全：想造成损失得额外加参数

- `list` **默认 dry-run**，只打印将提交的内容，必须显式 `--execute` 才真提交
- `--only 3,7,9` / `--limit N` 限定作用范围，其余条目一根手指都不碰
- 版本有歧义时（同名多版本、Deluxe Kit vs 豪华版）会停在 `needs_review` 并打印候选，**拒绝猜**
- 搜不到的游戏标 `not_found`，不提交、不瞎挂
- 重复 key 自动识别并跳过，继续下一条
- 单条失败不影响整批，状态逐条落盘
- 仓库自带 **推送前自检** `check_no_secrets.py`：扫描 `accessToken`、真实 CDKey、
  带用户名的绝对路径，配合 `.gitignore` 挡住浏览器 profile（内含登录 cookie），防止误提交

```powershell
python check_no_secrets.py     # 干净则 exit 0；发现可疑内容 exit 1
```

### 5. 不碰你的密码，也不碰验证码

登录是**人工完成**的：工具把 Edge 停在登录页，每 3 秒轮询检测会话，用户自己输账号密码和图形验证码。
代码里没有密码字段、没有 OCR、没有破解。登录态存在独立 Edge profile 里，跨次复用。

### 6. 零 DOM 依赖，页面改版也大概率不坏

UI 自动化容易因为一个 class 改名全面崩。本工具只调用 4 个站点接口（搜索 / 详情 / 上架 / 我的挂单），
不模拟点击、不依赖选择器；`accessToken` 从 `localStorage` 取，请求在已登录页面内发出。

### 7. 可审计、可续跑

- `plan.json`：每条 key 解析到哪个平台条目、appid、价格、状态
- `results.json`：逐条提交结果（含挂单号、时间、尝试次数），**增量写入**，中断后重跑不会重复提交
- `verified.json`：回查结果
- `上架结果.xlsx`：两个 sheet（明细 + 汇总），跳过项标黄并写明原因

---

## 快速开始

要求：Windows + Microsoft Edge + Python 3.10+

```powershell
git clone https://github.com/<you>/steampy-cdk-lister.git
cd steampy-cdk-lister
python -m pip install -r requirements.txt

# 1) 起浏览器驱动（长驻，会弹出 Edge 窗口）
python driver.py --port 8899

# 2) 另开一个终端：登录（人工，工具只负责等你登完）
python steampy.py login --wait 300

# 3) 确认账号与会话有效
python steampy.py whoami
#    → id + 昵称 + listSelf 可见挂单数

# 4) 搜条目，拿 gameId
python steampy.py search --q "Monster Hunter Rise Deluxe Kit"

# 5) 写清单 → 解析定价（不提交）
copy items.example.json items.json
python steampy.py plan --items items.json --out plan.json

# 6) 先 dry-run，确认无误再真提交
python steampy.py list --plan plan.json
python steampy.py list --plan plan.json --execute

# 7) 核对 + 出表
python steampy.py verify --plan plan.json --results results.json
python steampy.py report --plan plan.json --results results.json --out 上架结果.xlsx
```

### 命令一览

| 命令 | 作用 |
|---|---|
| `ping` | 驱动是否存活、当前页面、登录状态 |
| `whoami` | 账号 id/昵称 + 可见挂单数（判断会话是否被踢） |
| `login` | 把窗口停在登录页并等待人工登录 |
| `search --q` | 平台游戏目录搜索，输出 gameId / appid / 原价 / 最低挂单 / 挂单价 |
| `plan --items` | 解析条目 + 定价，输出 `ok / needs_review / not_found / no_price` |
| `list --plan` | 上架（默认 dry-run；`--execute` 真提交；`--only 3,7` / `--limit N` 分批） |
| `verify --plan` | 按 gameId + 价格回查 `listSelf` |
| `report --plan` | 导出 xlsx（明细 + 汇总） |

### 清单格式（`items.json`）

```json
[
  {"n": 1, "label": "某游戏-标准版", "key": "AAAAA-BBBBB-CCCCC", "gameId": "496138616573972"},
  {"n": 2, "label": "某 DLC 豪华组合", "key": "DDDDD-EEEEE-FFFFF",
   "query": "Monster Hunter Rise Deluxe Kit", "match": "MONSTER HUNTER RISE Deluxe Kit"},
  {"n": 3, "label": "某加速器体验卡", "key": "GGGGGGGGGGGGGGG"}
]
```

- `gameId`：最稳，直接指定平台条目
- `query` + `match`：按关键词搜，`match` 与平台英文名/中文名**精确相等**才采用
- 只有 `key`：`plan` 阶段标 `not_found`，永不提交

---

## 工作原理

```
┌──────────────┐   JSON over HTTP    ┌────────────────────────────┐
│ steampy.py   │  ───────────────▶   │ driver.py (Playwright)     │
│  编排/限流   │   127.0.0.1:8899    │  长驻已登录 Edge           │
└──────────────┘                     └─────────────┬──────────────┘
       │                                           │ eval(bridge.js)
       ▼                                           ▼
  plan / results / verified            页面内 XHR + accessToken
  / xlsx（可复跑、可审计）              ──▶ /xboot/steamGame/* ,
                                            /xboot/steamKeySale/*
```

为什么把请求放在页面里发：站点要求请求头带 `accessToken`（取自 `localStorage`），
缺了它服务端直接掐连接（浏览器里表现为 `Failed to fetch`，非常像网络故障）。
放在已登录页面里发，cookie 和 token 天然对齐，比自己拼 header 稳。

接口清单、字段同名不同义的坑、DOM 备忘都在 [`API.md`](API.md)。

---

## 已知限制

- **Windows 专用**：用 `channel="msedge"` 调系统 Edge，Playwright 无需下载浏览器；其他平台需改 channel
- **单实例**：同一时间只能跑一个 driver；同账号多开会互相踢掉会话
- **受平台限流约束**：整批耗时约 `条目数 × 11.5s`，无法更快
- **只做上架与核对**：改价、下架、订单处理未实现（接口已知，欢迎 PR）
- **接口非官方**：是站点自用接口，字段可能变；变了改 `bridge.js` 即可

## 数据真实性

README 里所有数字来自一次真实运行，不是估算：21 条挂单号、时间戳、金额都可以在
`verify` / `report` 的产物里对上。仓库里**没有**任何缓存层，因此也**不会**声称缓存命中率——
只有真实的、可复现的指标才写在这里。

---

## 安全与合规

- 仅用于**本人账号**与**自有库存 CDKey**；不要托管他人 key
- 不存储、不传输你的账号密码；登录完全由你本人在弹出的浏览器里完成
- 不绕过验证码、不规避风控；内置节流是**为遵守**平台 10 秒限制，不是为了更快
- 自动化操作可能违反站点用户协议，账号风险由使用者自负；请先用 1 条 key 试跑
- 挂错版本会被平台判「货不对板」并退款罚款，所以工具在歧义处会停下来问你——**请认真回答**
- `.gitignore` 已排除 `work/`（浏览器 profile，含登录 cookie）；**永远不要提交它**

## 许可证

[MIT](LICENSE)
