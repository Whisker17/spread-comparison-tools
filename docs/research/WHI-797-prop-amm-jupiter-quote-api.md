# WHI-797：Prop AMM 基准名单 + Jupiter Quote API 接入验证

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-797](https://linear.app/whisker-personal/issue/WHI-797) |
| Milestone | M1 调研与口径定义 |
| Blocks | WHI-806（Prop AMM adapter：Jupiter Quote API + `dexes` 过滤） |
| 调研日期 | 2026-08-03（UTC） |
| 验证环境 | 公网 live 调用 `api.jup.ag` / `lite-api.jup.ag`，**无 API key** |

---

## 1. 结论摘要（TL;DR）

1. **基准名单确认**：HumidiFi、TesseraV、BisonFi 三家均已接入 Jupiter Metis 路由，可通过 Quote API 的 `dexes` 参数**单独**拿到报价。
2. **dex 标识符（大小写敏感，必须精确匹配 label）**：

   | Prop AMM | Jupiter `dexes` label | Program ID |
   | --- | --- | --- |
   | HumidiFi | `HumidiFi` | `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp` |
   | Tessera（Wintermute） | `TesseraV` | `TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH` |
   | BisonFi | `BisonFi` | `BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi` |

3. **API key**：keyless 可用；生产建议申请 `x-api-key`。
4. **Rate limit（keyless）**：官方文档 **0.5 RPS**；冷窗口 live burst 实测 **连续 5 次 200 后第 6 次起 429**（`x-ratelimit-current` 顶到 5）。安全默认间隔 **≥ 2s**。详见 §3.3。
5. **费用**：`outAmount` 为扣除 AMM fee（及可选 platform fee）后的净输出；prop AMM 响应中 **`feeAmount`/`feeMint` 字段缺失**（OpenAPI 标 deprecated；实测不返回），`platformFee` 默认为 `null`。
6. **`excludeDexes` 同样可用**（与 `dexes` **不可同时设置**，同时传返回 400）；见 §3.5。
7. **资产范围（live 探测）**：三家核心都在 **SOL/稳定币 + 主流大币（cbBTC、WETH）**；memecoin / LST / 多数中盘币 **无直连报价**。详见 §6。

> WHI-806 实现时：**不要**写 `Tessera` / `Tessera V` / `Humidifi` 等近似字符串——会直接 `No routes found`。

---

## 2. 背景

Prop AMM 无公开前端、无独立报价 HTTP API；约 90% 成交量经 Jupiter 路由。现实路径：

```
GET /swap/v1/quote?dexes=<Label>&inputMint=...&outputMint=...&amount=...
```

通过 `dexes` 限定单一 prop AMM，即可近似「该 venue 的报价」。

相关行业背景（非本文核心）：prop AMM 依赖高频轻量 oracle 更新 + 自有 vault 库存；Jupiter 集成是其主要获流渠道。参见 Helius 综述 *Solana’s Proprietary AMM Revolution*。

---

## 3. Jupiter Quote API 接入要点

### 3.1 Endpoint

| 项目 | 值 |
| --- | --- |
| 推荐 base（新网关） | `https://api.jup.ag/swap/v1` |
| 旧 free base（逐步废弃） | `https://lite-api.jup.ag/swap/v1` |
| 报价 | `GET /quote` |
| DEX 名单 | `GET /program-id-to-label` |
| Auth header | `x-api-key: <key>`（可选；keyless 允许） |
| 文档 | https://developers.jup.ag/docs/api-reference/swap/v1/quote |
| Portal / 申请 key | https://developers.jup.ag/portal |

> 注意：官方标注 **Metis Swap API v1 不再积极维护**，后续由 Swap V2（`/build` 等）承接。但 **v1 `/quote` + `dexes` 在 2026-08-03 仍 live 可用**，且是 WHI-806 的直接依赖。WHI-806 实现时建议在代码层抽象 base URL，便于迁 V2。

### 3.2 关键查询参数

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `inputMint` | ✓ | 输入 mint |
| `outputMint` | ✓ | 输出 mint |
| `amount` | ✓ | 原始数量（最小单位，uint64 字符串/整数） |
| `slippageBps` | | 默认 50 |
| `dexes` | | 逗号分隔 **label**；指定后路由 **只走** 这些 DEX |
| `excludeDexes` | | 逗号分隔 label；从路由中排除 |
| `onlyDirectRoutes` | | `true` = 单跳；利于确认「该 venue 是否有直连市场」 |
| `swapMode` | | `ExactIn`（默认）/ `ExactOut`（prop AMM 未验证 ExactOut） |
| `forJitoBundle` | | `true` 时会 **排除与 Jito bundle 不兼容的 DEX（文档点名 HumidiFi）** |
| `platformFeeBps` | | 可选平台抽成；与 `/swap` 的 `feeAccount` 配合 |

**Label 空格规则**：文档示例用 `+` 代替空格（如 `Orca+V2`、`Meteora+DLMM`）。本三家 label **无空格**，直接传 `HumidiFi` / `TesseraV` / `BisonFi`。

### 3.3 Auth / Rate limit

| 模式 | Rate limit | 说明 |
| --- | --- | --- |
| Keyless `api.jup.ag` | **0.5 RPS**（[Portal setup](https://developers.jup.ag/docs/portal/setup)） | 与 live 冷窗口 burst 一致：窗口额度约 **5 req**，见下表 |
| Free plan + API key | **1 RPS** | Portal 免费档 |
| Developer / Launch / Pro | 10 / 50 / 150 RPS | 付费档 |

响应头字段（keyless 实测均存在）：`x-ratelimit-remaining`、`x-ratelimit-current`、`x-ratelimit-reset`、`x-api-gateway-request-id`。

**冷窗口 burst**（2026-08-03，先 sleep ≥12s 再无间隔连打 `dexes=HumidiFi`，0.1 SOL→USDC）：

| 请求序号 | HTTP | `x-ratelimit-remaining` | `x-ratelimit-current` | `x-ratelimit-reset` |
| --- | --- | --- | --- | --- |
| 1 | 200 | 4 | 1 | 1785728842 |
| 2 | 200 | 3 | 2 | 1785728842 |
| 3 | 200 | 2 | 3 | 1785728842 |
| 4 | 200 | 1 | 4 | 1785728842 |
| 5 | 200 | 0 | 5 | 1785728842 |
| 6 | **429** | 0 | 5 | 1785728842 |
| 7 | **429** | 0 | 5 | 1785728842 |
| 8 | **429** | 0 | 5 | 1785728842 |

说明：若在窗口**未冷透**时 burst，会看到交错 200/429（滑动窗口部分耗尽），**不能**据此否认 5/window。生产应以文档 0.5 RPS + 响应头为准；keyless 安全默认 **≥ 2s** 间隔。

**WHI-806 建议**：

- 默认走 `api.jup.ag` + 可配置 `x-api-key`
- 客户端限速 ≤ 计划档位；对 429 做指数退避
- 三家串行报价时至少间隔 **≥ 2s**（keyless）或按 key 档位调

### 3.4 报价是否含 fee

官方 schema 对 `outAmount` 的说明：

> Best output amount **after deducting AMM fees and platform fees**. Does not account for slippage.

| 字段 | Prop AMM 实测 |
| --- | --- |
| `outAmount` | 净输出（已扣 AMM 侧费用语义） |
| `otherAmountThreshold` | `outAmount` 再扣 `slippageBps` 后的下限 |
| `platformFee` | 未传 `platformFeeBps` 时为 `null` |
| `routePlan[].swapInfo.feeAmount` | **字段缺失**（OpenAPI 标 deprecated；实测不返回 key） |
| `routePlan[].swapInfo.feeMint` | **字段缺失**（deprecated；实测不返回 key） |

**含义**：价差对比应直接用 `outAmount`（或推导的有效价）。**无法**从 Quote 响应单独拆出「AMM 明文字段 fee」；价差已内嵌在曲线报价里。Jupiter 前端 Ultra 的 5–10 bps 平台费与 Metis Manual/`/quote` 默认路径无关——本 API 默认 `platformFee=null`。

### 3.5 `excludeDexes` 验证

`excludeDexes` 与 `dexes` 对称：逗号分隔 label，从路由中**排除**所列 venue。对 WHI-797 三家均做了 live 排除（1 SOL→USDC，`onlyDirectRoutes` 默认 false）：

| 请求 | HTTP | 结果 `routePlan` labels | 被排除 venue 是否出现 |
| --- | --- | --- | --- |
| `excludeDexes=HumidiFi` | 200 | `GoonFi V2` | 否 |
| `excludeDexes=TesseraV` | 200 | `HumidiFi` | 否（无 TesseraV） |
| `excludeDexes=BisonFi` | 200 | `Scorch` → `Byreal` | 否 |
| `excludeDexes=HumidiFi,TesseraV,BisonFi` | 200 | `Whirlpool` → `Manifest` | 否（三家皆不出现） |

示例请求：

```bash
curl -sS -G "https://api.jup.ag/swap/v1/quote" \
  --data-urlencode "inputMint=So11111111111111111111111111111111111111112" \
  --data-urlencode "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" \
  --data-urlencode "amount=1000000000" \
  --data-urlencode "slippageBps=50" \
  --data-urlencode "excludeDexes=HumidiFi"
```

响应摘录（完整见 [`samples/quote-exclude-humidifi-sol-usdc.json`](./samples/quote-exclude-humidifi-sol-usdc.json)）：

```json
{
  "outAmount": "72771857",
  "routePlan": [
    {
      "swapInfo": {
        "label": "GoonFi V2",
        "inputMint": "So11111111111111111111111111111111111111112",
        "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "inAmount": "1000000000",
        "outAmount": "72771857"
      },
      "percent": 100
    }
  ]
}
```

**与 `dexes` 同时设置**：Jupiter **硬互斥**。

```bash
# dexes=HumidiFi & excludeDexes=HumidiFi → HTTP 400
```

```json
{ "error": "Cannot set dexes and exclude dexes at the same time" }
```

样本：[`samples/quote-dexes-and-exclude-same.json`](./samples/quote-dexes-and-exclude-same.json)。

**WHI-806 建议**：隔离 venue 用 `dexes=<Label>`；全市场对照里剔除某 venue 用 `excludeDexes`；**不要**两参数同传。

其他样本：

- [`samples/quote-exclude-tesserav-sol-usdc.json`](./samples/quote-exclude-tesserav-sol-usdc.json)
- [`samples/quote-exclude-bisonfi-sol-usdc.json`](./samples/quote-exclude-bisonfi-sol-usdc.json)
- [`samples/quote-exclude-prop3-sol-usdc.json`](./samples/quote-exclude-prop3-sol-usdc.json)

---

## 4. 三家 Prop AMM 标识与单独报价验证

### 4.1 获取 label 的权威来源

```bash
curl -sS "https://api.jup.ag/swap/v1/program-id-to-label" | jq 'to_entries[] | select(.value|test("Humidi|Tessera|Bison"))'
```

实测输出：

```json
{ "key": "BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi", "value": "BisonFi" }
{ "key": "TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH", "value": "TesseraV" }
{ "key": "2DNbzPochEcyCcWMbL4d9S3u9QqQEj5bbe6cSZFvKsbh", "value": "BisonFi Predict" }
{ "key": "9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp", "value": "HumidiFi" }
```

> `BisonFi Predict` 为独立 label，**不在** WHI-797 基准三家里；若未来要覆盖 prediction 市场再单独评估。

### 4.2 错误 label 对照（全部 400）

| 错误写法 | 结果 |
| --- | --- |
| `Tessera` / `Tessera V` / `Tessera+V` | No routes found |
| `Humidifi` / `humidifi` | No routes found |
| `Bisonfi` | No routes found |

Live 捕获（`dexes=Tessera`，1 SOL→USDC）→ **HTTP 400**：

```json
{ "error": "No routes found", "errorCode": "NO_ROUTES_FOUND" }
```

完整样本：[`samples/quote-no-routes-wrong-label.json`](./samples/quote-no-routes-wrong-label.json)。  
（无流动性 pair 的 `dexes=<正确 label>` 返回同形 400 body；与拼写错误在 HTTP 层不可区分，故启动时应用 `program-id-to-label` 校验 label。）

### 4.3 示例请求（1 SOL → USDC）

Mints：

- SOL (wSOL): `So11111111111111111111111111111111111111112`
- USDC: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`
- amount: `1000000000`（1 SOL，9 decimals）

```bash
# HumidiFi
curl -sS -G "https://api.jup.ag/swap/v1/quote" \
  --data-urlencode "inputMint=So11111111111111111111111111111111111111112" \
  --data-urlencode "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" \
  --data-urlencode "amount=1000000000" \
  --data-urlencode "slippageBps=50" \
  --data-urlencode "dexes=HumidiFi"

# TesseraV
curl -sS -G "https://api.jup.ag/swap/v1/quote" \
  --data-urlencode "inputMint=So11111111111111111111111111111111111111112" \
  --data-urlencode "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" \
  --data-urlencode "amount=1000000000" \
  --data-urlencode "slippageBps=50" \
  --data-urlencode "dexes=TesseraV"

# BisonFi
curl -sS -G "https://api.jup.ag/swap/v1/quote" \
  --data-urlencode "inputMint=So11111111111111111111111111111111111111112" \
  --data-urlencode "outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" \
  --data-urlencode "amount=1000000000" \
  --data-urlencode "slippageBps=50" \
  --data-urlencode "dexes=BisonFi"
```

三家均返回 **HTTP 200**，且 `routePlan[0].swapInfo.label` 分别严格等于请求的 dex label。`lite-api.jup.ag` 同样可用（已验证 HumidiFi）。

**隔离旁证**：`dexes` 过滤后的响应常带 `mostReliableAmmsQuoteReport.info`，其中未入选的可靠 AMM 会标注  
`"Amm is excluded from request's dexes_selection."`（见完整 sample JSON）。这是 Jupiter 内部确认 `dexes_selection` 生效的额外证据，与 `routePlan[].label` 交叉验证。

### 4.4 响应样例（已截断；完整 JSON 见 `samples/`）

**HumidiFi**（1 SOL → USDC，约 $72.87 量级，随市场波动）：

```json
{
  "inputMint": "So11111111111111111111111111111111111111112",
  "inAmount": "1000000000",
  "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
  "outAmount": "72886151",
  "otherAmountThreshold": "72521721",
  "swapMode": "ExactIn",
  "slippageBps": 50,
  "platformFee": null,
  "priceImpactPct": "0.0000830250516874543128485761",
  "routePlan": [
    {
      "swapInfo": {
        "ammKey": "FksffEqnBRixYGR791Qw2MgdU7zNCpHVFYBL4Fa4qVuH",
        "label": "HumidiFi",
        "inputMint": "So11111111111111111111111111111111111111112",
        "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "inAmount": "1000000000",
        "outAmount": "72886151",
        "updateContextSlot": "436895562"
      },
      "percent": 100,
      "bps": null
    }
  ],
  "contextSlot": 436895562,
  "timeTaken": 0.000345059,
  "swapUsdValue": "72.874610042841",
  "mostReliableAmmsQuoteReport": {
    "info": {
      "BZtgQEyS6eXUXicYPHecYQ7PybqodXQMvkjUbP4R8mUU": "Amm is excluded from request's dexes_selection.",
      "Czfq3xZZDmsdGdUyrNLtRhGc47cXcZtLG4crryfu44zE": "Amm is excluded from request's dexes_selection."
    }
  }
}
```

**TesseraV**（同参数）：

```json
{
  "outAmount": "72889548",
  "routePlan": [
    {
      "swapInfo": {
        "ammKey": "FLckHLGMJy5gEoXWwcE68Nprde1D4araK4TGLw4pQq2n",
        "label": "TesseraV",
        "inAmount": "1000000000",
        "outAmount": "72889548"
      },
      "percent": 100
    }
  ]
}
```

**BisonFi**（同参数）：

```json
{
  "outAmount": "72902315",
  "routePlan": [
    {
      "swapInfo": {
        "ammKey": "8FnX3xo2yYw3EUE6w3nQA4GfXGS9wpK6oj3veJpbFzLo",
        "label": "BisonFi",
        "inAmount": "1000000000",
        "outAmount": "72902315"
      },
      "percent": 100
    }
  ]
}
```

完整文件：

- [`samples/quote-humidifi-sol-usdc.json`](./samples/quote-humidifi-sol-usdc.json)
- [`samples/quote-tesserav-sol-usdc.json`](./samples/quote-tesserav-sol-usdc.json)
- [`samples/quote-bisonfi-sol-usdc.json`](./samples/quote-bisonfi-sol-usdc.json)

### 4.5 同 venue 多跳

当 `onlyDirectRoutes` 未开、且 pair 无直连市场时，路由可能 **在同一 prop AMM 内多跳**（仍全部 `label` 为该 venue）。

HumidiFi 0.1 SOL → JUP 示例（2 hop：SOL→USDC→JUP）：

```json
{
  "routePlan": [
    {
      "swapInfo": {
        "label": "HumidiFi",
        "inputMint": "So11111111111111111111111111111111111111112",
        "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "inAmount": "100000000",
        "outAmount": "7289221"
      }
    },
    {
      "swapInfo": {
        "label": "HumidiFi",
        "inputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "outputMint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
        "inAmount": "7289221",
        "outAmount": "37751330"
      }
    }
  ]
}
```

见 [`samples/quote-humidifi-sol-jup-multihop.json`](./samples/quote-humidifi-sol-jup-multihop.json)。

BisonFi / TesseraV 同样可在无直连时走同 venue 多跳（经 USDC），例如 0.1 SOL→cbBTC：

| Venue | Multi-hop SOL→cbBTC | Multi-hop SOL→WETH | 样本 |
| --- | --- | --- | --- |
| HumidiFi | ✅（SOL→USDC→cbBTC） | ✅ | HumidiFi multi sample 见上；矩阵亦有 |
| TesseraV | ✅ | ✅（live 2026-08-03） | 矩阵 follow-up |
| BisonFi | ✅ | ❌（本 size 无路由） | [`samples/quote-bisonfi-sol-cbbtc-multihop.json`](./samples/quote-bisonfi-sol-cbbtc-multihop.json) |

**对价差工具的含义**：

- 若要「单一市场直连接」→ 加 `onlyDirectRoutes=true`
- 若要「该 venue 能给出的最优执行价」→ 默认多跳（可能经 USDC/SOL 中转）
- 多跳覆盖 **不对称**：直连腿齐全时更容易桥出 SOL↔大币；某腿缺失则多跳也可能 400

---

## 5. 分 venue 调研卡片

### 5.1 HumidiFi

| 项 | 内容 |
| --- | --- |
| Jupiter label | `HumidiFi` |
| Program ID | `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp` |
| 报价获取 | `GET /swap/v1/quote?...&dexes=HumidiFi` |
| 单独报价 | ✅ 验证通过 |
| 特殊约束 | `forJitoBundle=true` 时官方会排除 HumidiFi |
| 运营背景 | 头部 prop AMM（体量上常居 prop 份额前列）；无公开前端 |

**直连市场（`onlyDirectRoutes=true`，live 探测）**：

| 方向 | 结果 |
| --- | --- |
| SOL ↔ USDC | ✅ |
| SOL ↔ USDT | ✅ |
| USDC ↔ JUP | ✅ |
| USDC ↔ cbBTC | ✅ |
| USDC ↔ WETH | ✅ |
| USDC ↔ USDT（直连） | ❌（多跳经 SOL 可 ✅） |
| SOL ↔ JUP / cbBTC / WETH（直连） | ❌（多跳经 USDC 可 ✅；含反向 cbBTC→SOL live） |
| WIF / BONK / POPCAT / mSOL / JitoSOL / PYTH / RAY / ORCA / KMNO | ❌ |

### 5.2 TesseraV（Tessera / Wintermute）

| 项 | 内容 |
| --- | --- |
| Jupiter label | **`TesseraV`**（非 Tessera） |
| Program ID | `TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH` |
| 报价获取 | `GET /swap/v1/quote?...&dexes=TesseraV` |
| 单独报价 | ✅ 验证通过 |
| 运营背景 | Wintermute 运营；2025-06 前后接入 Jupiter |

**直连市场（live 探测）**：

| 方向 | 结果 |
| --- | --- |
| SOL ↔ USDC | ✅ |
| USDC ↔ cbBTC | ✅ |
| USDC ↔ WETH | ✅ |
| SOL → cbBTC / SOL → WETH（多跳经 USDC） | ✅（无直连；`onlyDirectRoutes=false`） |
| SOL ↔ USDT / 任意 USDT | ❌（多跳亦 ❌） |
| JUP 相关 | ❌ |
| Memecoin / LST / 中盘 DeFi | ❌ |

→ TesseraV **资产面最窄**：实测为 SOL-USDC + USDC 兑主流大币（cbBTC、WETH）；无 USDT 腿导致稳定币多跳也失败。

### 5.3 BisonFi

| 项 | 内容 |
| --- | --- |
| Jupiter label | `BisonFi` |
| Program ID | `BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi` |
| 报价获取 | `GET /swap/v1/quote?...&dexes=BisonFi` |
| 单独报价 | ✅ 验证通过 |
| 旁支 | `BisonFi Predict`（独立 label，未纳入基准） |

**直连市场（live 探测）**：

| 方向 | 结果 |
| --- | --- |
| SOL ↔ USDC | ✅ |
| SOL ↔ USDT | ✅ |
| USDC ↔ cbBTC | ✅ |
| USDC ↔ WETH | ✅ |
| USDC ↔ USDT（直连） | ❌（多跳经 SOL 可 ✅） |
| SOL → cbBTC（多跳经 USDC） | ✅ |
| SOL → WETH（多跳） | ❌（本探测 size 无路由；直连 USDC↔WETH 仍 ✅） |
| JUP / memecoin / LST / 中盘 | ❌ |

公开数据侧常强调 **SOL-USD 占绝对主导**（与探测结果一致）。

---

## 6. 支持资产清单（供资产清单 issue 输入）

> 口径：**Jupiter 在 `dexes=<venue>` 下能否给出报价**，不等于链上全部 vault 资产。探测时间 2026-08-03；市场会随 MM 库存策略变化，WHI-806 应把「无路由」当作正常业务态（不是硬错误）。

### 6.1 建议的 M1 对比资产池（三家交集优先）

| 优先级 | Pair | HumidiFi | TesseraV | BisonFi | 备注 |
| --- | --- | --- | --- | --- | --- |
| P0 | SOL/USDC | ✅ 直连 | ✅ 直连 | ✅ 直连 | 核心基准 |
| P0 | USDC/cbBTC | ✅ 直连 | ✅ 直连 | ✅ 直连 | 主流大币 |
| P0 | USDC/WETH | ✅ 直连 | ✅ 直连 | ✅ 直连 | 主流大币 |
| P1 | SOL/USDT | ✅ 直连 | ❌ | ✅ 直连 | Tessera 缺席 |
| P1 | USDC/USDT | 多跳 | ❌ | 多跳 | 无直连稳定币对 |
| P2 | USDC/JUP | ✅ 直连 | ❌ | ❌ | 仅 HumidiFi |
| P2 | SOL/JUP 等 | 多跳 | ❌ | ❌ | 经 USDC |

### 6.2 Mint 速查（矩阵内全部 symbol）

| Symbol | Mint | decimals（探测用） | 探测 amount |
| --- | --- | --- | --- |
| SOL (wSOL) | `So11111111111111111111111111111111111111112` | 9 | `100000000`（0.1 SOL；1 SOL 报价样例用 `1000000000`） |
| USDC | `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | 6 | `50000000`（50 USDC） |
| USDT | `Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB` | 6 | `50000000` |
| JUP | `JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN` | 6 | `10000000` |
| WIF | `EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm` | 6 | `5000000` |
| BONK | `DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263` | 5 | `1000000000` |
| mSOL | `mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So` | 9 | `100000000` |
| JitoSOL | `J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn` | 9 | `100000000` |
| cbBTC | `cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij` | 8 | `100000`（0.001 cbBTC） |
| WETH (Wormhole) | `7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs` | 8 | `1000000` |
| PYTH | `HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3` | 6 | `100000000` |
| RAY | `4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R` | 6 | `10000000` |
| ORCA | `orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE` | 6 | `10000000` |
| KMNO | `KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS` | 6 | `100000000` |
| POPCAT | `7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr` | 9 | `100000000` |

### 6.3 完整探测矩阵

见 [`samples/asset-matrix.tsv`](./samples/asset-matrix.tsv)（文件头注释含 probe 日期、base URL、amount 策略、sleep 间隔）。

---

## 7. 对 WHI-806 的实现建议

```text
PropAmmVenue {
  id: "humidifi" | "tesserav" | "bisonfi"
  jupiter_dex_label: "HumidiFi" | "TesseraV" | "BisonFi"  // 精确字符串
  program_id: ...
}
```

1. **Quote client**
   - Base: `https://api.jup.ag/swap/v1`
   - `GET /quote` + `dexes={label}`
   - Header 可选 `x-api-key`
   - 解析 `outAmount`、`inAmount`、`priceImpactPct`、`routePlan[].swapInfo.ammKey/label`、`contextSlot`、`timeTaken`
2. **错误处理**（按 **body / `errorCode`** 分支，勿把所有 HTTP 400 当成空报价）

   | HTTP | body / `errorCode` | 含义 | 客户端动作 |
   | --- | --- | --- | --- |
   | 400 | `error`: `No routes found`，`errorCode`: `NO_ROUTES_FOUND` | 无路由：该 venue 对该 pair/size 无报价，**或** label 拼写错误 | **业务空结果**（非 fatal）；与错误 label 在 HTTP 层不可分 → 启动时用 `/program-id-to-label` 校验 label |
   | 400 | `error`: `Cannot set dexes and exclude dexes at the same time`（无 `NO_ROUTES_FOUND`） | **客户端配置错误**：同时传了 `dexes` 与 `excludeDexes`（见 §3.5） | **programmer / config error**，应 fail-fast 修调用，不要当 empty quote 吞掉 |
   | 400 | 其他 | 参数非法等 | 记日志 + 按可恢复性分类 |
   | 429 | rate limit | keyless / plan 超额 | 指数退避；读 `x-ratelimit-*` |
   | 5xx / 网络 | — | 上游或传输故障 | 有限次重试 |

   样本：[`quote-no-routes-wrong-label.json`](./samples/quote-no-routes-wrong-label.json)、[`quote-dexes-and-exclude-same.json`](./samples/quote-dexes-and-exclude-same.json)。
3. **对比语义**
   - 默认：`onlyDirectRoutes=true` 保证 apples-to-apples 单市场
   - 可选：关闭 onlyDirect 取 venue 内最优（可能多跳）
4. **不要依赖** `feeAmount` 做 fee 拆解
5. **Jito**：若下游组 Jito bundle，注意 HumidiFi 可能被 `forJitoBundle` 排除（报价层可不传该参数）
6. **限速**：三家 × N pairs 的扫描循环必须有全局 rate limiter
7. **API 演进**：封装 `QuoteProvider` trait/接口，便于以后迁 Swap V2

伪代码：

```rust
// illustrative only — not WHI-806 implementation
let url = format!(
    "{base}/quote?inputMint={in_mint}&outputMint={out_mint}&amount={amount}&slippageBps={bps}&dexes={label}&onlyDirectRoutes=true",
    base = "https://api.jup.ag/swap/v1",
    label = venue.jupiter_dex_label, // e.g. "TesseraV"
    ...
);
```

---

## 8. 风险与局限

| 风险 | 说明 |
| --- | --- |
| 报价 ≠ 可成交保证 | Quote 瞬时有效；prop AMM 曲线高频更新，落地价可能偏移 |
| 库存/风控拒单 | 大 size 可能无路由或冲击显著 |
| Label 变更 | 以 `/program-id-to-label` 为准，避免硬编码过期 |
| lite-api 退役 | 迁移到 `api.jup.ag` |
| Metis v1 维护状态 | 官方已指向 Swap V2；功能仍可用但需关注废弃时间表 |
| 资产列表时效 | 本节矩阵为单日探测快照 |
| 无独立 API | 完全依赖 Jupiter 集成质量与可用性 |

---

## 9. 参考链接

- Jupiter Quote OpenAPI：https://developers.jup.ag/docs/api-reference/swap/v1/quote  
- Developer Portal / key：https://developers.jup.ag/portal  
- Portal setup & plans：https://developers.jup.ag/docs/portal/setup  
- lite-api 迁移说明：https://developers.jup.ag/docs/portal/migration  
- program-id-to-label（live）：https://api.jup.ag/swap/v1/program-id-to-label  
- Helius：Solana’s Proprietary AMM Revolution  

---

## 10. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-797-prop-amm-jupiter-quote-api.md` | 本文 |
| `docs/research/samples/quote-*-sol-usdc.json` | 三家 SOL→USDC 完整响应（`dexes` 隔离） |
| `docs/research/samples/quote-exclude-*.json` | `excludeDexes` 隔离样本（单家 + 三家） |
| `docs/research/samples/quote-dexes-and-exclude-same.json` | 同时传 `dexes`+`excludeDexes` → 400 |
| `docs/research/samples/quote-no-routes-wrong-label.json` | 错误 label → 400 body |
| `docs/research/samples/quote-humidifi-sol-jup-multihop.json` | HumidiFi 同 venue 多跳 |
| `docs/research/samples/quote-bisonfi-sol-cbbtc-multihop.json` | BisonFi 同 venue 多跳 |
| `docs/research/samples/asset-matrix.tsv` | 资产探测矩阵（含元数据注释） |

**本 issue 范围**：调研与 live 验证 only，**不含** WHI-806 adapter 实现。
