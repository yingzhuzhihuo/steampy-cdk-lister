# steampy.com 接口与页面参考

所有接口同源 `https://steampy.com`，前缀 `/xboot`，GET/POST 混合。
**认证**：cookie + 请求头 `accessToken`（值来自 `localStorage.accessToken`）。
少了这个头，服务端直接掐连接，浏览器里表现为 `Failed to fetch` / `xhr_error`，
不会返回 401 —— 这是最容易误判成"网络问题"的坑。

```
headers: { Accept: application/json, text/plain, */*, accessToken: <localStorage.accessToken> }
POST 时额外: Content-Type: application/x-www-form-urlencoded
```

## 接口表

| 用途 | 请求 | 关键返回 |
|---|---|---|
| 卖家中心游戏目录搜索 | `GET /xboot/steamGame/saleKeyByName?pageNumber=1&pageSize=10&sort=id&order=asc&gameUrl=&gameName=<关键词>` | `result.content[]`：`id`（gameId）、`gameName`、`gameNameCn`、`appId`、`gameUrl`、`oriPrice`、`keyPrice`、`keyTxAmt`、`keyAveAmt`、`steamApp.type` |
| 游戏详情（定价用） | `GET /xboot/steamGame/getOne?gameId=<id>` | 同上单条；`keyTxAmt` = 页面顶部「平台最低价」 |
| 市场游戏列表 | `GET /xboot/steamGame/keyByName?pageNumber=1&pageSize=30&sort=keyTx&order=asc&gameName=<关键词>` | 与销售目录字段类似 |
| 市场某游戏全部挂单 | `GET /xboot/steamKeySale/listSale?pageNumber=1&pageSize=20&sort=keyPrice&order=asc&gameId=<id>` | `keyPrice`（该卖家单价）、`stock`、`sold`、`saleId` |
| 上架 | `POST /xboot/steamKeySale/startSell` | body：`gameId=&keys=<KEY>&keyWord=&sellPrice=<价格>&syncUs=0&osflag=0`；返回 `{success, message, result:{id}}` |
| 我的挂单 | `GET /xboot/steamKeySale/listSelf?pageNumber=1&pageSize=50&sort=saleStatus&order=desc&gameId=` | `content[]`：`id`（挂单号）、`gameId`、`stock`、`sold`、`saleStatus`、`keyPrice` |
| 余额 | `GET /xboot/payWallet/getBalance` | 钱包金额 |
| 销售统计 | `GET /xboot/keySaleReport/getSelf` | 当天/累计销售额与笔数 |

> `keys` 支持多行（一个 key 一行）一次提交多个同游戏 key；不同游戏必须分开提交。

## 字段同名不同义（重要）

| 字段 | 在游戏目录（saleKeyByName/getOne） | 在我的挂单（listSelf） |
|---|---|---|
| `keyPrice` | **近期最低挂单价格**（可能是 0.47 这类钓鱼价） | **我自己这条挂单的售价** |
| `keyTxAmt` | 页面顶部「平台最低价」，**就是要抄的价格** | — |
| `keyAveAmt` | 近期平均成交价 | — |
| `price` | — | 不返回；用 `keyPrice` 当挂单售价 |

## 价格核对方式

页面 `/cdkDetail?name=cn&gameId=<id>` 顶部显示 `平台最低价: ￥X`，X == `keyTxAmt`。
下方的卖家表格（`listSale`，按 `keyPrice` 升序）第一行通常比 X 略低，**不是**要抄的数。

## 上架相关的规则（卖家中心「出售说明」要点）

- 必须能在 Steam 找到对应商店页面才能挂；搜不到 = 不能挂。
- 挂错地区 / 把本体当合集、低级版当高级版 → 判「货不对板」，退款 + 扣罚金。
- 合集包或含本体的高级版本可以当本体卖；反向不行。
- 本体与 DLC 是两个独立 key 时必须分开挂。
- 验证失败会自动下架该 CDK 的其他挂单。
- 平台手续费 3%（`实际到账 = 价格 × 0.97`）。

## 限流

`POST startSell` 之间至少间隔 **10 秒**，否则返回
`CDKey挂单操作间隔为10秒,请耐心等待后再试`。实测 11.5 秒安全；
连续提交中偶尔仍会命中，加重试即可。

## 响应结构

```json
{ "success": true, "message": "success", "code": 200, "timestamp": 1792394386169,
  "result": { ... } }
```
`success=false` 时读 `message` 判断：`/间隔|等待/` → 限流；`/已.*上架|已存在|重复/` → 重复 key。

## DOM 备忘（如需走 UI）

- 框架是 iView（Vue2）。**页面上存在多个相同弹窗实例，必须用 `:visible` 过滤**，
  否则 Playwright 会选中隐藏的那个并报 "element is not visible"。
- 受控输入要用原生 setter + `input` 事件，直接改 `.value` 不会同步到 Vue：
  ```js
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, v); el.dispatchEvent(new Event('input', { bubbles: true }));
  ```
- 上架按钮流程：`添加CDKey` → 填链接/关键词 → `搜索` → 点结果行 → 填 `CDKey` 文本域与 `价格`
  → `提交` → 二次确认弹窗点 `确认出售`。接口就是上面的 `startSell`，所以脚本直接调接口。

## 注意

- 站点时间可能是"未来"的（服务器时钟），别拿本地日期做过滤条件，按 `gameId` + 价格匹配更稳。
- 会话掉线时 `loginState` 会看到 `path=/login`；重新人工登录即可，脚本不要去解验证码。
