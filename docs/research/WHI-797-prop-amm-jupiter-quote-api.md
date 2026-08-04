# WHI-797：Prop AMM 基准名单 + 多链报价接入验证（Solana Jupiter / EVM KyberSwap）

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-797](https://linear.app/whisker-personal/issue/WHI-797) |
| Milestone | M1 调研与口径定义 |
| Blocks | WHI-806（Prop AMM adapter：按 chain 选聚合器 + venue 过滤） |
| 调研日期 | 2026-08-03（UTC；v2 同日补 Tessera Base/BSC 多链验证） |
| 验证环境 | 公网 live 调用 `api.jup.ag` / `lite-api.jup.ag` / `aggregator-api.kyberswap.com`，**无 API key** |

> **v2 变更**：初版只覆盖 Solana（Jupiter 路径），漏掉了 Tessera 在 **Base / BSC** 上的高交易量部署（DefiLlama 口径下 BSC 是 Tessera 交易量最大的链）。本版按 **venue × chain** 补齐：新增 §7 Tessera 多链接入（KyberSwap Aggregator API），§8 实现建议改为多链 venue 模型。

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
7. **资产范围（live 探测，Solana）**：三家核心都在 **SOL/稳定币 + 主流大币（cbBTC、WETH）**；memecoin / LST / 多数中盘币 **无直连报价**。详见 §6。
8. **Tessera 是多链 venue（v2 新增）**：DefiLlama 收录链为 **Solana + Base + BSC**；24h（2026-08-03）**BSC $195M > Solana $34M > Base $2.6M**（7d：BSC $952M / Solana $241M / Base $67M）——**BSC 是 Tessera 交易量最大的链**（BSC 全链 DEX 排名 #3），只看 Solana 会漏掉大头。EVM 两链共用同一合约 **`TesseraSwap` `0x55555522005BcAE1c2424D474BfD5ed477749E3e`**（Base 部署于 2025-10-30，BSC 自 2025-11-13 活跃）。HumidiFi / BisonFi 确认无非 Solana 部署。Base/BSC 排查过其余 prop AMM：ElfomoFi（Base+BSC，~$4.5M/d，**唯一报 BNB 的 prop AMM**）、Lunarbase（Base，~$4.1M/d）、Axima（Base，未被 DefiLlama 收录）均可经 KyberSwap 隔离报价但体量与 Tessera 差两个数量级，列为 watchlist 不入基准；BSC 第一大 DEX **Native Swap（$437M/d）是多 MM 的 PMM/RFQ 网络**，属另一 venue class。详见 §7、§7.6。
9. **EVM 报价路径（v2 新增）**：KyberSwap Aggregator API（keyless 可用）`includedSources=tessera` / `excludedSources=tessera` 可在 Base、BSC 单独隔离 Tessera 报价；source id 全小写 **`tessera`**。Base 直连：WETH、cbBTC、AERO、VIRTUAL、EURC（全部 vs USDC）；BSC 直连：BTCB/USDT + **tokenized stocks（QQQB、SPCXB、NVDAB、NVDAon，全部 vs USDT）**。ParaSwap 无 Tessera；0x / 1inch / OKX 需 API key 未验证。详见 §7。
10. **Tessera BSC 的成交主力是 tokenized equities（v2 新增，与 WHI-798 直接相关）**：链上采样约 **94% 的 swap 是 QQQB/USDT 等股票代币对**，且 ~95% 流量来自 Binance Wallet DEX Router（非公开聚合器）。**prop AMM × tokenized stocks 在 BSC 上是真实存在的可报价交叉**。详见 §7.4。

> WHI-806 实现时：**不要**写 `Tessera` / `Tessera V` / `Humidifi` 等近似字符串——Jupiter 会直接 `No routes found`；KyberSwap 传错 source id 返回 `40011 filtered liquidity sources`。

---

## 2. 背景

Prop AMM 无公开前端、无独立报价 HTTP API；成交量几乎全部经聚合器路由。因此「拿某家 prop AMM 的报价」= **该链主流聚合器的 Quote API + venue 过滤参数**：

| Chain | 聚合器 | venue 过滤参数 | 本文验证 |
| --- | --- | --- | --- |
| Solana | Jupiter Metis `GET /swap/v1/quote` | `dexes=<Label>` / `excludeDexes` | §3–§6 |
| Base / BSC | KyberSwap `GET /{chain}/api/v1/routes` | `includedSources=<id>` / `excludedSources` | §7 |

通过 venue 过滤限定单一 prop AMM，即可近似「该 venue 的报价」。

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
| **多链** | ⚠️ 本表仅 Solana 侧。Tessera 另部署于 **Base、BSC**（BSC 交易量最大）——报价路径、池子与资产见 **§7** |

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

## 7. Tessera 多链接入：Base / BSC（v2 新增）

### 7.1 量级与部署：为什么不能只看 Solana

DefiLlama（protocol `tessera-v`，id 6557）收录 Tessera 的链为 **Solana、Base、BSC**。分链交易量（live 拉取 2026-08-03）：

| Chain | 24h | 7d | 30d | 累计 |
| --- | --- | --- | --- | --- |
| **BSC** | **$195.1M** | **$951.7M** | **$1.46B** | $3.28B |
| Solana | $33.8M | $241M | $1.45B | $62.7B |
| Base | $2.6M（7d 均值 ≈ $9.6M/d，日间波动大） | $66.9M | $197.9M | $6.18B |

**BSC 已超过 Solana，是 Tessera 当前交易量最大的链**（BSC 全链 DEX 24h 排名 **#3**，仅次于 Native Swap 与 PancakeSwap V3）；30d 口径 BSC ≈ Solana。只覆盖 Solana 会漏掉大部分 Tessera 流量。对照：HumidiFi（24h $45.6M）与 BisonFi（24h $89.3M）在 DefiLlama 均为 **Solana 单链**，确认无非 Solana 部署；EVM 上另一家 prop AMM 是 **ElfomoFi**（Base+BSC，KyberSwap id `elfomofi`，24h ≈ $4.6M，暂不入基准名单）。

**部署事实（链上验证）**：

| 项 | 值 |
| --- | --- |
| EVM swap 合约（Base 与 BSC **同一 vanity 地址**） | `0x55555522005BcAE1c2424D474BfD5ed477749E3e`，验证源码名 **`TesseraSwap`**（Solidity 0.8.30） |
| Base 部署 | 2025-10-30 12:17 UTC，block 37518648，creation tx `0xf1b7…00c0`（Blockworks 报道 Tessera「2025-11 初」登陆 Base，吻合） |
| BSC 活跃起点 | 2025-11-13（DefiLlama adapter 起算日；同地址 live 发出 swap 事件） |
| Swap 事件 | `TesseraTrade(address tokenIn, address tokenOut, uint256 amountIn, uint256 amountOut, address recipient)`——可作为链上成交监控/对账的直接数据源（DefiLlama volume 即按此事件统计） |
| 运营方 | Wintermute（对 DL News 确认运营 Tessera V；无官网、无前端、无公开文档，"dark AMM"） |

**流量归属（链上 caller 采样，2026-08-03）**：BSC 侧 **~95% 来自 Binance Wallet「Binance: DEX Router」`0xb300…028d`**（Binance Wallet / Alpha 订单流，闭环、无公开报价 API）；Base 侧以 **OKX DEX Router、KyberSwap MetaAggregationRouterV2** 为主，另有 0x AllowanceHolder、Relay、LI.FI 等。含义：**KyberSwap 报价 ≈ Tessera 对公开聚合器的报价面**，但 BSC 上最大的那部分（Binance Wallet 专属流）我们只能间接经同一池子的公开报价近似。

### 7.2 报价路径：KyberSwap Aggregator API

EVM 链上与「Jupiter + `dexes`」等价的现实路径是 **KyberSwap Aggregator API**（三大免 key 聚合器里唯一同时收录 Tessera 且暴露 source 过滤的）：

| 项目 | 值 |
| --- | --- |
| Base URL | `https://aggregator-api.kyberswap.com/{chain}/api/v1/routes`（GET，报价）；`/route/build`（POST，构造 calldata，报价场景不需要） |
| chain slug | `base`（8453）、`bsc`（56） |
| venue 过滤 | `includedSources=<id>` / `excludedSources=<id>`（逗号分隔 DEX id） |
| Tessera source id | **`tessera`**（全小写；`routeSummary.route[].exchange` 亦返回 `tessera`） |
| Auth | 无需 API key；header `x-client-id: <app>` 标识集成方，**不带会被更严限速**（官方未公布数字） |
| Rate limit 实测 | keyless 无 `x-client-id` 冷启动连打 12 次全 200，未触发 429——远宽松于 Jupiter keyless 的 0.5 RPS；生产仍建议带 `x-client-id` + 客户端限速 |
| 报价字段 | `routeSummary.amountOut`（wei）、`amountOutUsd`、`gas`/`gasUsd`、`route[][]`（hop 数组：`exchange`/`pool`/`swapAmount`/`amountOut`） |
| Fee 语义 | 默认不收平台费；`extraFee` 对象（`feeAmount`/`chargeFeeBy`/`isInBps`/`feeReceiver`）为集成方自定义抽成，报价对比场景**不传**即可 |
| 文档 | https://docs.kyberswap.com/developer-guide/aggregator-api/aggregator-api-specification/evm-swaps |

### 7.3 错误语义（与 Jupiter 对照）

| 场景 | Jupiter (Solana) | KyberSwap (Base/BSC) |
| --- | --- | --- |
| venue 对该 pair 无报价 | HTTP 400 `NO_ROUTES_FOUND` | HTTP 200，body `code: 4008, message: "route not found"` |
| venue 标识符拼错 / 该链不存在 | HTTP 400 `NO_ROUTES_FOUND`（与无路由**同形**，不可区分） | body `code: 40011, message: "filtered liquidity sources"`（与无路由**可区分**） |
| 参数非法 | HTTP 400 其他 error | `code: 4000, message: "bad request"`——注意：**混合大小写地址必须是合法 EIP-55 checksum**，错一个字母就 4000；全小写地址可接受。另外经验现象（语义未官宣）：`includedSources=tessera` + **token 完全不在该 source 已注册 token 集内**时也返回 4000 而非 4008（例：TSLAB） |
| include 与 exclude 冲突 | 400 `Cannot set dexes and exclude dexes at the same time` | 未验证（避免同传） |

判别要点：KyberSwap 的 `40011` 能把「source id 写错」从「无路由」里区分出来，比 Jupiter 更友好；但 `tessera` id 在**不存在该 venue 的链**（如 Ethereum）同样返回 40011，所以 40011 = 「过滤后无可用 source」，启动时仍建议对每条链做一次已知 pair 的冒烟验证。

### 7.4 直连池与资产范围（live 探测 2026-08-03）

> 下表 `pool` 为 KyberSwap 响应中的 per-pair 标识（是否为独立合约未确认；实际成交合约统一是 `TesseraSwap 0x5555…9E3e`）。所有报价均单 hop 直连、双向验证或至少单向验证。

**Base（quote 腿全部是 USDC）**：

| Pair | Kyber pool id | 结果 |
| --- | --- | --- |
| WETH/USDC | `0xf524c1bc1c64a2c99bc7eccf19ede9a1d89d5a7c` | ✅ 直连双向（原生 ETH 伪地址 `0xeeee…` 等同 WETH） |
| cbBTC/USDC | `0xed57bacdc2a990b631f8817853935791c122c356` | ✅ 直连双向 |
| AERO/USDC | `0x3b84be4d48888a6bc385eea93e522246b214069e` | ✅ 直连双向 |
| VIRTUAL/USDC | `0xe1191102bdcea1928a93b4d6ea7bf5c4e9207210` | ✅ 直连（链上采样中 VIRTUAL 是 Base 第一大成交对，~32%） |
| EURC/USDC | `0x4b963fb4a26f082d94f964fa3c2764821cc06bd4` | ✅ 直连 |
| WETH↔cbBTC / WETH↔AERO / cbBTC↔AERO | — | ✅ 全 tessera 2-hop 经 USDC |
| 任何 USDT / wstETH 腿 | — | ❌（无池） |
| VVV/USDC、deSPXA/USDC | — | 链上 `TesseraTrade` 采样中出现过，KyberSwap 侧未逐一验证 |

**BSC（quote 腿全部是 USDT）——成交主力是 tokenized equities**：

| Pair | Kyber pool id | 结果 |
| --- | --- | --- |
| BTCB/USDT | `0xe1191102bdcea1928a93b4d6ea7bf5c4e9207210` | ✅ 直连双向 |
| **QQQB/USDT**（bStocks，Invesco QQQ） | `0xc2bdd7d2dbf7e5ffbd9371804755dda85ce7e7b8` | ✅ 直连双向——链上采样中占 Tessera BSC 成交 **~94%** |
| **SPCXB/USDT**（bStocks，SpaceX） | `0x016e4491ce6203a61b9cc22c349cbfa8fe545594` | ✅ 直连 |
| **NVDAB/USDT**（bStocks，NVIDIA） | —（id 未记录） | ✅ 直连（且无过滤时最优路由本身 100% 走 tessera） |
| **NVDAon/USDT**（Ondo，NVIDIA） | `0x4055346e1886ec083786dcf026cdd21f6b300ddf` | ✅ 直连 |
| TSLAB / SKHYB / SNDKB / MUB（bStocks 其他） | — | ❌（`4000 bad request`，稳定复现——经验上 = token 不在 tessera 已注册 token 集内；与 `4008`「token 已知但无路由」不同） |
| WBNB、ETH、USDC、CAKE、USD1、DOGE、XRP、SOL、WBETH 任意组合 | — | ❌ 4008 |
| ASTER/USDT | — | 链上采样出现过，未验证 |

⚠️ 两点提醒：
1. **BSC 侧 Tessera ≈「bStocks/Ondo 股票代币 + BTCB 的 USDT 做市商」**——这与 WHI-798 的 Stocks 重点直接交叉：prop AMM × tokenized stocks 在 BSC 是真实可报价的组合。
2. 池集是**单日快照**，Wintermute 随时增/撤池（如 stocks 池 2026-06 后才出现）；WHI-806 不要硬编码 pair 列表（「无路由是业务态」原则），资产发现建议周期性重扫。

完整矩阵（含全部 token 地址与 amount）：[`samples/WHI-797-tessera-evm-matrix.tsv`](./samples/WHI-797-tessera-evm-matrix.tsv)。

**对 M1 资产池的含义**：
- 跨链交集里 Tessera 三链都能报的 logical 资产 = **BTC**（Solana cbBTC / Base cbBTC / BSC BTCB）与 **ETH**（Solana WETH / Base WETH；BSC ❌）；**SOL 仅 Solana**。
- Base 特有增量：**AERO、VIRTUAL、EURC**。
- **BSC 特有增量：QQQB、SPCXB、NVDAB、NVDAon（tokenized stocks）**——直接进入 WHI-798 Stocks section 的 venue 矩阵。

### 7.5 示例请求 / 响应

```bash
# Base: 1 WETH -> USDC，只走 Tessera
curl -sS "https://aggregator-api.kyberswap.com/base/api/v1/routes?tokenIn=0x4200000000000000000000000000000000000006&tokenOut=0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913&amountIn=1000000000000000000&includedSources=tessera" \
  -H "x-client-id: spread-comparison-tools"

# BSC: 0.02 BTCB -> USDT，只走 Tessera
curl -sS "https://aggregator-api.kyberswap.com/bsc/api/v1/routes?tokenIn=0x7130d2a12b9bcbfae4f2634d864a1ee1ce3ead9c&tokenOut=0x55d398326f99059ff775485246999027b3197955&amountIn=20000000000000000&includedSources=tessera" \
  -H "x-client-id: spread-comparison-tools"
```

响应摘录（Base WETH→USDC，完整见 samples）：

```json
{
  "code": 0,
  "data": {
    "routeSummary": {
      "amountIn": "1000000000000000000",
      "amountOut": "1854960936",
      "amountOutUsd": "1845.07",
      "gas": "693831",
      "route": [[{ "exchange": "tessera", "pool": "0xf524c1bc1c64a2c99bc7eccf19ede9a1d89d5a7c", "swapAmount": "1000000000000000000", "amountOut": "1854960936" }]]
    }
  }
}
```

样本文件（全部 live 捕获 2026-08-03）：

- [`samples/ks-route-tessera-base-weth-usdc.json`](./samples/ks-route-tessera-base-weth-usdc.json)
- [`samples/ks-route-tessera-base-cbbtc-usdc.json`](./samples/ks-route-tessera-base-cbbtc-usdc.json)
- [`samples/ks-route-tessera-bsc-btcb-usdt.json`](./samples/ks-route-tessera-bsc-btcb-usdt.json)
- [`samples/ks-route-exclude-tessera-base-weth-usdc.json`](./samples/ks-route-exclude-tessera-base-weth-usdc.json)（`excludedSources` 对照）
- [`samples/ks-route-wrong-source-id.json`](./samples/ks-route-wrong-source-id.json)（错误 id → 40011）
- [`samples/ks-route-tessera-bsc-wbnb-usdt-noroute.json`](./samples/ks-route-tessera-bsc-wbnb-usdt-noroute.json)（无池 pair → 4008）

### 7.6 Base / BSC 其他 prop AMM（watchlist，live 2026-08-03）

按「Base/BSC 上还有没有其他大体量 prop AMM」做了一轮排查：拉 DefiLlama 两链 DEX 24h 榜 top 25，逐个核对分类标签，再用 KyberSwap `includedSources` 验证可隔离性：

| 名称 | 分类（DefiLlama tags） | 链 | 24h 交易量 | KyberSwap id | 隔离报价验证（pair 覆盖） | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| **ElfomoFi** | `Prop AMM`（oracle-based） | Base + BSC | ~$4.5M（Base $3.4M / BSC $1.0M） | `elfomofi` | ✅ Base：WETH/USDC；**BSC：BTCB、WBNB、ETH（均 vs USDT）**——BSC 上唯一报 BNB 的 prop AMM；无 stocks | watchlist |
| **Lunarbase** | `Prop AMM`（PMM + 集中流动性） | Base（+Monad） | ~$4.1M | `lunarbase` | ✅ WETH/USDC、cbBTC/USDC | watchlist |
| **Axima** | **未被 DefiLlama 收录**（体量未知） | Base | ? | `axima-v2` | ✅ WETH/USDC、cbBTC/USDC、AERO/USDC；实测偶尔给出全场最优价 | watchlist（隐身运营，关注） |
| Hanji Protocol | `Order Book`（自述 CLOB + prop-amm 混合） | Base 等 | Base ~$2.5M | `hanji`（poolType `lgl-clob`） | ✅ WETH/USDC | 形态混合，暂不归入 prop AMM |
| **Native Swap** | `AMM`（实为 **PMM/RFQ 流动性网络**，多家 MM 接入） | **BSC #1（$437M/24h**，DefiLlama 标记非双计）+ 7 链 | $447M 全链 | ❌ 无 KyberSwap source id（`native`/`native-v2`/`native-v3` 均无效） | 报价需走 native.org 自有 API（要 key） | **另一类 venue**：不是单一 prop 桌而是多 MM RFQ 网络；若产品未来加「RFQ 网络」venue class，它是 BSC 头号候选 |
| Metric（metric.xyz） | 无 tags，自述仅 "DEX" | Base $18.4M / BSC $3.9M 等 10 链 | ~$67M 全链 | ❌ 无 source id | — | 分类不明（多链新部署、无公开定性），**待查**，暂不认定为 prop AMM |
| GoonFi | `Prop AMM` | Solana only（$59.9M/24h） | — | —（Jupiter label `GoonFi V2`） | — | Solana 侧候选，与本节无关 |

**结论**：Base/BSC 上 Tessera 之外**没有体量接近的纯 prop AMM**——ElfomoFi/Lunarbase/Axima 合计 <$10M/d，与 Tessera BSC 单日 $195M 差两个数量级；基准名单维持 HumidiFi/Tessera/BisonFi 不变。但有两个值得跟踪的点：
1. **ElfomoFi 是唯一同时部署 Base+BSC 且报 BNB 的 prop AMM**——若未来纳入，可给 BNB 补上 prop AMM 报价点（当前基准三家都不报 BNB）；
2. **Native Swap $437M/24h 是 BSC 第一大 DEX**，形态是多 MM 的 PMM/RFQ 网络（非单一 prop 桌、无免 key 报价路径）——是否作为独立 venue class 建议在 DESIGN.md 层面单独决策，不塞进 prop AMM 语义。

样本：[`samples/ks-route-elfomofi-bsc-wbnb-usdt.json`](./samples/ks-route-elfomofi-bsc-wbnb-usdt.json)、[`samples/ks-route-lunarbase-base-weth-usdc.json`](./samples/ks-route-lunarbase-base-weth-usdc.json)。

### 7.7 其他聚合器（EVM 侧替代路径评估）

| 聚合器 | Tessera 收录 | source 过滤 | 结论 |
| --- | --- | --- | --- |
| KyberSwap | ✅ `tessera`（Base+BSC，本文 live 全链路验证；官方 dex-ids 文档页尚未收录该 id——文档滞后于现实） | `includedSources`/`excludedSources`，免 key | **主路径（唯一端到端确认）** |
| OKX DEX | ✅ 链上确认（OKX Router 是 Base 上 TesseraSwap 的第一大 caller） | `dexIds`（quote 侧 include-only）/`excludeDexIds` | 需 API key；label 字符串需 authed `get-liquidity` 查询，**候选冗余路径** |
| 0x Swap API | ✅ 链上确认（0x 官方博客：Base 已集成 5 家 prop AMM，占其 Base 量 40–50%） | 公开仅 `excludedSources`（v2） | 需 API key，未验证 |
| Binance Wallet router | ✅（**BSC ~95% 流量来源**） | 无公开 API，闭环 | 不可作报价源；其成交只能经同池公开报价近似 |
| ParaSwap | ❌ Base/BSC source 列表均无（live 2026-08-03） | `includeDEXS` | 不可用 |
| 1inch | 链上 caller 采样未观测到 v6 router → 大概率未集成 | `protocols` | 需 API key，未验证 |
| Odos | 未知（`/info/liquidity-sources` 被 Cloudflare 1033 拦；链上也未见其 router） | `sourceWhitelist` | 未验证 |

**建议**：主依赖 KyberSwap；若后续拿到 OKX / 0x key，各验证一条冗余路径（记录到 ADR）。另一兜底是直接订阅 `TesseraTrade` 事件做成交价（非报价）监控。

---

## 8. 对 WHI-806 的实现建议

**venue 模型必须带 chain 与 quote_source 维度**（v2 变更——Tessera 一家对应三个 venue 实例）：

```text
PropAmmVenue {
  id: "humidifi@solana" | "tesserav@solana" | "bisonfi@solana"
    | "tessera@base"    | "tessera@bsc"
  chain: "solana" | "base" | "bsc"
  quote_source: Jupiter { dex_label: "HumidiFi" | "TesseraV" | "BisonFi" }   // 精确字符串，大小写敏感
              | KyberSwap { source_id: "tessera", chain_slug: "base" | "bsc" }
  program_id / pool_allowlist: ...   // Solana: program id；EVM: 可选记录已知池（仅用于展示，不做路由硬编码）
}
```

`QuoteProvider` 抽象出两个实现：`JupiterQuoteProvider`（§3–§4）与 `KyberSwapQuoteProvider`（§7）。以下 1–7 条为 Solana/Jupiter 侧细节，EVM 侧对应差异见 §7.2–§7.3。

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

## 9. 风险与局限

| 风险 | 说明 |
| --- | --- |
| 报价 ≠ 可成交保证 | Quote 瞬时有效；prop AMM 曲线高频更新，落地价可能偏移 |
| 库存/风控拒单 | 大 size 可能无路由或冲击显著 |
| Label 变更 | Solana 以 `/program-id-to-label` 为准；KyberSwap source id 无公开枚举接口，靠已知 pair 冒烟验证 |
| lite-api 退役 | 迁移到 `api.jup.ag` |
| Metis v1 维护状态 | 官方已指向 Swap V2；功能仍可用但需关注废弃时间表 |
| 资产列表时效 | 本文矩阵均为单日探测快照；**BSC 侧当前单池（BTCB/USDT），池集变动风险最高** |
| 无独立 API | Solana 完全依赖 Jupiter（**WHI-837 已结**：无第二供应商可 live 隔离 HumidiFi+TesseraV+BisonFi；Titan DART 仅 BisonFi；DFlow/OKX 待 key。决策：接受 SPOF + 显式降级，见 [WHI-837](./WHI-837-solana-prop-amm-quote-redundancy.md) / [ADR 0001](../adr/0001-solana-prop-amm-jupiter-sole-path.md)）。Base/BSC 仍依赖 KyberSwap Tessera 集成（ParaSwap 无收录；OKX/0x EVM 冗余仍未 key 验证） |
| KyberSwap 限速未量化 | 官方不公布数字，仅承诺带 `x-client-id` 更宽松；实测 12 连发未限流，但生产仍需客户端限速 + 429 退避 |
| 跨链表示差异 | 同一 logical 资产在三链是不同合约（cbBTC vs BTCB；Wormhole WETH vs 原生 WETH），价差语义须带表示标签（同 WHI-798 口径） |

---

## 10. 参考链接

- Jupiter Quote OpenAPI：https://developers.jup.ag/docs/api-reference/swap/v1/quote  
- Developer Portal / key：https://developers.jup.ag/portal  
- Portal setup & plans：https://developers.jup.ag/docs/portal/setup  
- lite-api 迁移说明：https://developers.jup.ag/docs/portal/migration  
- program-id-to-label（live）：https://api.jup.ag/swap/v1/program-id-to-label  
- Helius：Solana’s Proprietary AMM Revolution  
- KyberSwap Aggregator API（EVM Swaps 规格）：https://docs.kyberswap.com/developer-guide/aggregator-api/aggregator-api-specification/evm-swaps  
- DefiLlama Tessera V（多链交易量）：https://defillama.com/protocol/tessera-v ；API：https://api.llama.fi/summary/dexs/tessera-v  
- TesseraSwap 合约（Base，已验证源码）：https://base.blockscout.com/address/0x55555522005BcAE1c2424D474BfD5ed477749E3e （BSC 同地址）  
- DefiLlama volume adapter（`TesseraTrade` 事件定义）：https://github.com/DefiLlama/dimension-adapters/blob/master/dexs/tessera/index.ts  
- Blockworks 0xResearch「Prop AMMs expand to Base」：https://blockworks.com/newsletter/0xresearch/issue/post_27a40a19-c423-4427-9dfe-28002a03ca74  
- 0x「PropAMM Shenanigans」（Base prop AMM 集成与报价行为观察）：https://0x.org/post/propamm-shenanigans  
- DL News：Wintermute 确认运营 Tessera V：https://www.dlnews.com/articles/defi/solana-dark-amms-make-trading-more-efficient-but-at-a-cost/  
- DefiLlama 分链 DEX 榜（watchlist 排查来源）：https://defillama.com/dexs/chain/base ；https://defillama.com/dexs/chain/bsc  
- ElfomoFi：https://elfomo.fi/ ；DefiLlama：https://defillama.com/protocol/elfomofi  
- Lunarbase（Prop AMM，Base）：https://defillama.com/protocol/lunarbase  
- Native（PMM/RFQ 网络，BSC 第一大 DEX）：https://native.org ；DefiLlama：https://defillama.com/protocol/native-swap  

---

## 11. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-797-prop-amm-jupiter-quote-api.md` | 本文 |
| `docs/research/samples/quote-*-sol-usdc.json` | 三家 SOL→USDC 完整响应（`dexes` 隔离） |
| `docs/research/samples/quote-exclude-*.json` | `excludeDexes` 隔离样本（单家 + 三家） |
| `docs/research/samples/quote-dexes-and-exclude-same.json` | 同时传 `dexes`+`excludeDexes` → 400 |
| `docs/research/samples/quote-no-routes-wrong-label.json` | 错误 label → 400 body |
| `docs/research/samples/quote-humidifi-sol-jup-multihop.json` | HumidiFi 同 venue 多跳 |
| `docs/research/samples/quote-bisonfi-sol-cbbtc-multihop.json` | BisonFi 同 venue 多跳 |
| `docs/research/samples/asset-matrix.tsv` | Solana 资产探测矩阵（含元数据注释） |
| `docs/research/samples/ks-route-*.json` | **v2**：Tessera Base/BSC KyberSwap 样本（隔离 / exclude / 错误 id / 无路由） |
| `docs/research/samples/WHI-797-tessera-evm-matrix.tsv` | **v2**：Tessera Base/BSC pair 探测矩阵 |

**本 issue 范围**：调研与 live 验证 only，**不含** WHI-806 adapter 实现。
