# WHI-800：各对比 venue 的 API（endpoint / rate limit / 认证）

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-800](https://linear.app/whisker-personal/issue/WHI-800) |
| Milestone | M1 调研与口径定义 |
| Blocks | WHI-802…806（各 venue adapter）、[WHI-801](https://linear.app/whisker-personal/issue/WHI-801)（adapter 接口落地时可引用本表） |
| 调研日期 | 2026-08-03（UTC） |
| 方法 | **官方文档主源** + **公网 live 探测**（无 API key / 无私有签名）；延迟为从本机（NRT 出口附近）测得的 RTT 量级，**非** SLA |
| 样本 | [`samples/venue-api/`](./samples/venue-api/) |
| 对齐 | Venue 名单与 [WHI-798](./WHI-798-asset-category-inventory.md) / [WHI-799](./WHI-799-spread-fee-data-model.md) 一致；Prop AMM 见 [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md)（本文不重复） |

---

## 1. 结论摘要（TL;DR）

### 1.1 报价路径选型（Phase 1）

| Class | Venue | **推荐数据路径** | Auth | 深度粒度 | 备注 |
| --- | --- | --- | --- | --- | --- |
| CEX | Binance | Spot `GET /api/v3/depth` + USDT-M `GET /fapi/v1/depth` | 公开 market data **无需 key** | Spot ≤5000；FAPI 常见 ≤1000 | 权重随 `limit` 变；mid 用 bookTicker / premiumIndex |
| CEX | Bybit | `GET /v5/market/orderbook`（`category=spot\|linear`） | 公开 **无需 key** | 每侧 ≤1000 | IP：600 req / 5s；UID 限流主要打 private |
| Perp DEX | Hyperliquid | `POST /info` `type=l2Book` | 公开 **无需 key** | **最多每侧 20 档** | weight=2；全量 weight 池 1200/min/IP |
| Perp DEX | Lighter | `GET /api/v1/orderBookOrders?market_id=&limit=` | 公开 orderbook **无需 auth** | 按 `limit`（live `limit=5` OK） | Standard：60 req/min（未加权）；Builder 更高 |
| Perp DEX | ApeX Omni | `GET /api/v3/depth?symbol=BTCUSDT` | 公开 **无需 key** | live `limit` 5…200 有效；默认 25 | 符号注意：`crossSymbolName=BTCUSDT` vs 配置内 `symbol=BTC-USDT` |
| AMM | Uniswap (ETH) | **优先**官方 Trading API `/v1/quote`；备选链上 QuoterV2 | API key（Trading API）/ 仅 RPC（链上） | 净输出报价（非 orderbook） | 单 venue 对比时注意聚合可能掺其他池 |
| AMM | Aerodrome (Base) | 链上 Quoter / MixedQuoter；或 QuickNode Aerodrome Swap API | RPC / 商业 addon | 净输出 | 无一等公民公开 REST quoter |
| AMM | PancakeSwap (BSC) | 链上 QuoterV2 / Smart Router | 仅 RPC | 净输出 | 官方合约地址明确 |

### 1.2 实现默认建议（给 adapter）

1. **Orderbook venue（CEX + Perp DEX）**：REST 快照 walk book 即可满足 WHI-799 的 `effective_price @ notional`；高频刷新再加 WS。
2. **深度默认**：CEX/ApeX 用 **50–200 档** 足够覆盖 `$1k…$1M` 蓝筹 walk；HL **硬上限 20 档**——大 notional 可能 walk 不满，须返回 `insufficient_depth` 而非假价。
3. **ccxt（4.5.x live 探测）**：`binance` / `bybit` / `hyperliquid` / `apex` / `lighter` 均声明 `fetchOrderBook=True`。CEX 可直接用；Perp DEX 建议 **先直连官方 REST** 再决定是否包一层 ccxt（字段/符号映射仍要自建）。
4. **AMM**：**不要**用 0x/1inch 当「该 venue 独占报价」的默认源（聚合会混入其他 DEX）。0x/1inch 仅作 **fallback / 对照**；单 venue 语义走 **链上 quoter 固定 factory** 或官方 router（Uniswap Trading API 若无法锁源，也不宜冒充 uniswap-only）。
5. **延迟（本机 3 次采样中位，2026-08-03）**：Binance FAPI ~380ms、spot depth5 ~600ms；Bybit ~500–660ms；HL ~800ms；Lighter ~610ms；ApeX ~590ms。量级均为数百毫秒 RTT——**批量并行 + 短缓存** 是 M2 必选项。

### 1.3 样本索引

| 文件 | 内容 |
| --- | --- |
| [`binance-spot-depth-btcusdt.json`](./samples/venue-api/binance-spot-depth-btcusdt.json) | Spot depth `limit=5` |
| [`binance-fapi-depth-btcusdt.json`](./samples/venue-api/binance-fapi-depth-btcusdt.json) | USDT-M depth `limit=5` |
| [`binance-spot-bookticker-btcusdt.json`](./samples/venue-api/binance-spot-bookticker-btcusdt.json) | Spot TOB（P1 mid） |
| [`bybit-spot-orderbook-btcusdt.json`](./samples/venue-api/bybit-spot-orderbook-btcusdt.json) | Spot orderbook |
| [`bybit-linear-orderbook-btcusdt.json`](./samples/venue-api/bybit-linear-orderbook-btcusdt.json) | Linear orderbook |
| [`hyperliquid-l2book-btc.json`](./samples/venue-api/hyperliquid-l2book-btc.json) | `l2Book` BTC（截断 5 档） |
| [`lighter-orderbook-orders-btc.json`](./samples/venue-api/lighter-orderbook-orders-btc.json) | `market_id=1` BTC 档位 |
| [`lighter-orderbook-details-btc.json`](./samples/venue-api/lighter-orderbook-details-btc.json) | BTC 元数据（mark/index 等） |
| [`apex-depth-btcusdt.json`](./samples/venue-api/apex-depth-btcusdt.json) | Depth（截断 5 档） |
| [`apex-ticker-btcusdt.json`](./samples/venue-api/apex-ticker-btcusdt.json) | Ticker |
| [`apex-symbol-perpetualcontract-btc.json`](./samples/venue-api/apex-symbol-perpetualcontract-btc.json) | 合约配置片段 |

---

## 2. 范围与非目标

### 2.1 范围内

- Phase 1 对比 venue 的 **只读报价 / depth** 路径：endpoint、认证、rate limit、深度粒度、延迟量级、SDK/ccxt。
- 每个 venue 至少一份 live 请求/响应样本（AMM 以合约地址 + 调用形状为主，见 §6）。

### 2.2 非目标

- 费率数字清单（[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)）。
- Spread 公式与统一模型（[WHI-799](./WHI-799-spread-fee-data-model.md) 已定）。
- 资产是否在架（[WHI-798](./WHI-798-asset-category-inventory.md)）。
- Prop AMM / Jupiter（[WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md)）。
- 下单、私有账户、WS 本地 orderbook 同步的完整工程实现（仅给选型指针）。

---

## 3. CEX

### 3.1 Binance

| 项目 | Spot | USDT-M Futures |
| --- | --- | --- |
| Base | `https://api.binance.com` | `https://fapi.binance.com` |
| Depth | `GET /api/v3/depth` | `GET /fapi/v1/depth` |
| TOB（轻量） | `GET /api/v3/ticker/bookTicker` | `GET /fapi/v1/ticker/bookTicker` |
| Reference mid（WHI-799 P0） | — | `GET /fapi/v1/premiumIndex` → `indexPrice` |
| 认证 | 公开 market data：**无** | 同左 |
| 文档 | [Spot REST market](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)、[spot-api-docs](https://github.com/binance/binance-spot-api-docs/blob/master/rest-api.md) | [USDⓈ-M futures](https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures) |

#### Depth 参数与权重（Spot，官方表）

| `limit` | Request weight |
| --- | --- |
| 1–100 | 5 |
| 101–500 | 25 |
| 501–1000 | 50 |
| 1001–5000 | 250 |

- `limit` 默认 100，最大 5000。
- 响应：`bids`/`asks` = `[price, qty]` 字符串数组；`lastUpdateId`。

#### Rate limit（live `exchangeInfo` 2026-08-03）

Spot：

| type | interval | limit |
| --- | --- | --- |
| `REQUEST_WEIGHT` | 1 MINUTE | **6000** |
| `RAW_REQUESTS` | 5 MINUTE | 300000 |
| `ORDERS` | … | （交易用，本调研可忽略） |

USDT-M（live `fapi/v1/exchangeInfo`）：

| type | interval | limit |
| --- | --- | --- |
| `REQUEST_WEIGHT` | 1 MINUTE | **2400** |
| `ORDERS` | 1 MINUTE / 10 SECOND | 1200 / 300 |

响应头：`x-mbx-used-weight-1m`（spot 还有 `x-mbx-used-weight`）。超限 → 429 / IP ban；文档建议行情用 **WebSocket** 减负。

#### Live 延迟（3 次，ms）

| 调用 | min | med | max |
| --- | --- | --- | --- |
| spot depth5 | 411 | 599 | 1268 |
| spot depth1000 | 572 | 756 | 962 |
| fapi depth5 | 373 | 379 | 399 |
| fapi depth1000 | 604 | 954 | 1061 |

#### 示例

```http
GET https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5
```

响应见 [`samples/venue-api/binance-spot-depth-btcusdt.json`](./samples/venue-api/binance-spot-depth-btcusdt.json)。

```http
GET https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=5
```

FAPI 额外字段：`E`（event time）、`T`（transaction time）。见 [`binance-fapi-depth-btcusdt.json`](./samples/venue-api/binance-fapi-depth-btcusdt.json)。

#### ccxt

- `ccxt.binance`：`fetchOrderBook` ✅（ccxt 4.5.70）。
- 统一接口便于 spot/future 切换，但 **weight 与 symbol 规则仍应按 Binance 原生计**；adapter 内建议显式设 `limit` 并记录 weight。

#### Phase 1 推荐

| 用途 | Endpoint | limit 建议 |
| --- | --- | --- |
| Spot walk | `/api/v3/depth` | 100（weight 5）起步；深度不足升到 500/1000 |
| Perp walk | `/fapi/v1/depth` | 50–100 |
| Mid P0 | `/fapi/v1/premiumIndex` | — |
| Mid P1 | `/api/v3/ticker/bookTicker` | weight 很低，适合高频 |

---

### 3.2 Bybit

| 项目 | 值 |
| --- | --- |
| Base | `https://api.bybit.com` |
| Orderbook | `GET /v5/market/orderbook` |
| 认证 | 公开 market：**无** |
| 文档 | [Get Orderbook](https://bybit-exchange.github.io/docs/v5/market/orderbook)、[Rate limits](https://bybit-exchange.github.io/docs/v5/rate-limit) |

#### 参数

| 参数 | 必需 | 说明 |
| --- | --- | --- |
| `category` | ✓ | `spot` / `linear` / `inverse` / `option` |
| `symbol` | ✓ | 如 `BTCUSDT`（大写） |
| `limit` | | spot/linear：**1–1000**；spot 默认 **1**；linear 默认 **25**；option 最大 25 |

#### 响应形状

```json
{
  "retCode": 0,
  "result": {
    "s": "BTCUSDT",
    "a": [["askPx", "askSz"], ...],
    "b": [["bidPx", "bidSz"], ...],
    "ts": 0,
    "u": 0,
    "seq": 0,
    "cts": 0
  }
}
```

- **RPI 订单不进 API book**（官方说明）——walk 得到的是可见簿。
- 样本：[`bybit-spot-orderbook-btcusdt.json`](./samples/venue-api/bybit-spot-orderbook-btcusdt.json)、[`bybit-linear-orderbook-btcusdt.json`](./samples/venue-api/bybit-linear-orderbook-btcusdt.json)。

#### Rate limit

| 层 | 规则 |
| --- | --- |
| **HTTP IP** | **600 requests / 5s** 窗口，覆盖 `api.bybit.com` 等；超限 **403 access too frequent**，需停会话 ≥10 分钟 |
| **API（UID）** | 按 endpoint 每秒限流；header：`X-Bapi-Limit` / `X-Bapi-Limit-Status` / `X-Bapi-Limit-Reset-Timestamp`；`retCode=10006` Too many visits |
| 市场数据 | 文档明确：**只拉行情优先 WebSocket**，WS 不计入 REST IP 限流 |

公开 orderbook 无 UID；生产批量拉簿时主要撞 **IP 600/5s**。粗算安全上限 ≈ **100 rps 持续**，留余量建议 **≤50 rps** 或上 WS。

#### Live 延迟（ms）

| 调用 | min | med | max |
| --- | --- | --- | --- |
| spot limit=5 | 469 | 529 | 1569 |
| linear limit=50 | 662 | 663 | 979 |

#### ccxt

- `ccxt.bybit`：`fetchOrderBook` ✅。须传 `params.category`（或依赖 market type）。

#### Phase 1 推荐

```http
GET /v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=50
GET /v5/market/orderbook?category=spot&symbol=BTCUSDT&limit=50
```

Equity / TradFi linear 符号与 WHI-798 矩阵对齐；`category` 勿混。

---

## 4. Perp DEX

### 4.1 Hyperliquid

| 项目 | 值 |
| --- | --- |
| Base | `https://api.hyperliquid.xyz`（testnet: `api.hyperliquid-testnet.xyz`） |
| Info | `POST /info` + JSON body |
| L2 book | `{"type":"l2Book","coin":"BTC"}` |
| 认证 | 公开 info：**无** |
| 官方 SDK | [hyperliquid-python-sdk](https://github.com/hyperliquid-dex/hyperliquid-python-sdk) |
| 文档 | [Info endpoint](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint)、[Rate limits](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits) |

#### L2 book 要点

- **最多每侧 20 档**（硬上限）。
- 档位：`{px, sz, n}`（`n` = 该价位订单数）。
- `levels[0]` = bids，`levels[1]` = asks。
- 可选 `nSigFigs`（2/3/4/5/null）聚合；`mantissa` 仅当 `nSigFigs=5`。
- Spot coin 命名与 UI 不同（如 `UBTC`）；perp 蓝筹用 `BTC`/`ETH`/`SOL`。
- HIP-3：`coin` 带 dex 前缀（如 `xyz:TSLA`）；info 可带 `dex` 字段（见官方 meta 文档）。

#### Rate limit（IP）

| 规则 | 值 |
| --- | --- |
| 聚合 weight | **1200 / 分钟 / IP** |
| `l2Book` weight | **2** → 理论峰值 ≈ **600 次/min**（若只打 l2Book） |
| 多数其他 info | weight 20 → ≈ 60 次/min |
| WS | 连接 ≤10；订阅 ≤1000；等 |

地址级限流主要约束 **exchange 动作**，不约束 info。

#### Live 延迟（ms）

| min | med | max |
| --- | --- | --- |
| 614 | 816 | 1029 |

#### 示例

```bash
curl -sS -X POST https://api.hyperliquid.xyz/info \
  -H 'Content-Type: application/json' \
  -d '{"type":"l2Book","coin":"BTC"}'
```

样本：[`hyperliquid-l2book-btc.json`](./samples/venue-api/hyperliquid-l2book-btc.json)。

#### ccxt / SDK

- 官方 Python SDK：推荐。
- `ccxt.hyperliquid`：`fetchOrderBook` ✅。

#### Phase 1 风险

- **20 档可能撑不住 $1M walk**（尤其薄簿 alt / equity HIP-3）。Adapter 必须在耗尽档位时 **显式失败**（WHI-799：禁止编造深度）。
- 需要更深簿时：没有 REST 更深接口；只能接受 20 档或换数据源（第三方 mirror，**非** Phase 1 默认）。

---

### 4.2 Lighter

| 项目 | 值 |
| --- | --- |
| Base | `https://mainnet.zklighter.elliot.ai` |
| 市场列表 | `GET /api/v1/orderBooks` |
| 元数据（含 mark/index） | `GET /api/v1/orderBookDetails` |
| **深度订单** | `GET /api/v1/orderBookOrders?market_id={id}&limit={n}` |
| 认证 | 上述只读：**无**；交易/账户需 API key + signer |
| 官方 SDK | Python [`lighter-sdk`](https://github.com/elliottech/lighter-python) / Go [`lighter-go`](https://github.com/elliottech/lighter-go) |
| 文档 | [Get Started](https://apidocs.lighter.xyz/docs/get-started)、[Rate limits](https://apidocs.lighter.xyz/docs/rate-limits) |
| Colocation 提示 | 官方：AWS Tokyo `ap-northeast-1a` |

#### 关键 ID（live 2026-08-03）

| symbol | market_id |
| --- | --- |
| ETH | 0 |
| BTC | 1 |
| SOL | 2 |
| TSLA | 112 |

（完整表以 `orderBookDetails` 为准，会变。）

#### 响应形状（orderBookOrders）

- `asks` / `bids`：逐单（非聚合价位）——含 `price`、`remaining_base_amount`、`order_id` 等。
- Walk 时须 **按 price 聚合** 再累计 size（与 CEX 聚合簿不同）。
- `limit` 为返回条数；live `limit=5` 返回 `total_asks=5` 等。

样本：[`lighter-orderbook-orders-btc.json`](./samples/venue-api/lighter-orderbook-orders-btc.json)。

#### Rate limit（官方）

| 账户类型 | REST（排除 sendTx） |
| --- | --- |
| Standard | **60 requests / rolling minute**（不按 weight 计，但若 premium 折算更严则取更严） |
| Premium | 24,000 weighted / min |
| Plus | 120,000 weighted / min |
| Builder | 240,000 weighted / min（只读友好；需申请） |

权重示例：`orderBookOrders` 等多数 endpoint weight=**300** → Premium 理论 ≈ 80 次/min/该端点；**Standard 直接 60 次/min**。

超限：HTTP **429 或 405**。

**含义**：Standard 账号下，对多 symbol轮询 orderbook **极易打满**。Phase 1 应：

1. 申请 **Builder** 只读额度，或  
2. 用 **WebSocket** `order_book/{MARKET_INDEX}`（官方 50ms 批量推送），REST 仅作快照校准。

#### Live 延迟（ms）

| min | med | max |
| --- | --- | --- |
| 608 | 614 | 628 |

#### ccxt

- `ccxt.lighter`：`fetchOrderBook` ✅（4.5.70）；hostname 模板 `mainnet.{hostname}`。

#### Phase 1 推荐

```http
GET /api/v1/orderBookDetails          # 启动时缓存 market_id / decimals / mark
GET /api/v1/orderBookOrders?market_id=1&limit=100
```

---

### 4.3 ApeX Omni

| 项目 | 值 |
| --- | --- |
| Base | `https://omni.apex.exchange/api/`（路径带 **v3**） |
| 配置/符号 | `GET /v3/symbols`（`data.contractConfig.perpetualContract` / `stockContract`） |
| Depth | `GET /v3/depth?symbol={crossSymbolName}` |
| Ticker | `GET /v3/ticker?symbol=BTCUSDT` |
| 认证 | 公开 market：**无**；私有需 `APEX-API-KEY` 等 + HMAC，交易另需 zkKeys |
| 官方 SDK | [apexpro-openapi](https://github.com/ApeX-Protocol/apexpro-openapi)（Python）、[apexomni-connector-node](https://github.com/ApeX-Protocol/apexomni-connector-node) |
| 文档 | [api-docs.pro.apex.exchange](https://api-docs.pro.apex.exchange/) |

#### 符号陷阱（live 验证）

| 字段 | BTC 永续示例 |
| --- | --- |
| 配置内 `symbol` | `BTC-USDT` |
| `crossSymbolName` / **depth 查询** | **`BTCUSDT`**（无连字符） |

错误示例：`symbol=BTC-USDT` → `a/b` 为 `null`。  
正确：`symbol=BTCUSDT` → 有深度。

#### Depth 行为（live）

| `limit` | 每侧档数 |
| --- | --- |
| （默认） | 25 |
| 5 / 25 / 50 / 200 | 与参数一致 |

响应：`data.a` / `data.b` = `[price, size]`；`data.s`；`data.u`（更新 id）；顶层 `timeCost`。

样本：[`apex-depth-btcusdt.json`](./samples/venue-api/apex-depth-btcusdt.json)。

#### Rate limit（官方）

| 层 | 限制 |
| --- | --- |
| IP | **600 requests / 60s** |
| Private GET | 600 / 60s / account |
| Private POST | 300 / 60s / account |

#### Live 延迟（ms）

| min | med | max |
| --- | --- | --- |
| 492 | 594 | 911 |

#### WebSocket（可选）

Public：`wss://quote.omni.apex.exchange/realtime_public?v=2&timestamp=...`  
Depth topic：`orderBook{25|200}.H.{symbol}`（先 snapshot 后 delta）。

#### ccxt

- `ccxt.apex`：`fetchOrderBook` ✅。

#### Phase 1 推荐

```http
GET /api/v3/symbols                 # 缓存 crossSymbolName / stepSize
GET /api/v3/depth?symbol=BTCUSDT&limit=50
GET /api/v3/ticker?symbol=BTCUSDT   # mark/index 辅助
```

RWA / stockContract 下单走 RWA 子账户；**只读 depth 仍用同一 public depth**（符号以 symbols 为准）。

---

## 5. AMM DEX

> AMM **没有** CEX 式 L2 book。WHI-799：`get_orderbook_spread` → `None`；用 quoter / router 的 **净输出** 反推 `effective_price`。

### 5.1 Uniswap（Ethereum）

#### 路径 A — 官方 Trading / Aggregator API（HTTP）

| 项目 | 值 |
| --- | --- |
| Quote | `POST https://trade-api.gateway.uniswap.org/v1/quote` |
| Auth | Header `x-api-key`（[developers.uniswap.org](https://developers.uniswap.org) portal） |
| 其它 header | `x-universal-router-version: 2.0` 等（见官方 API Reference） |
| 文档 | [Get a quote](https://developers.uniswap.org/docs/api-reference/aggregator_quote)、[Swapping via API](https://developers.uniswap.org/docs/trading/swapping-api/getting-started) |
| 费用 | 文档宣传 API free / no per-call；以 portal 为准 |

示意 body：

```json
{
  "type": "EXACT_INPUT",
  "amount": "1000000000",
  "tokenInChainId": 1,
  "tokenOutChainId": 1,
  "tokenIn": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
  "tokenOut": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
  "swapper": "0x..."
}
```

**风险**：路由可能跨协议；若产品文案是「Uniswap venue」，须确认响应能否 **证明只走 Uniswap 池**，否则标注为 `uniswap_routing_api` 而非纯 on-chain Uniswap。

#### 路径 B — 链上 QuoterV2（单 venue 语义更干净）

| 项目 | 值 |
| --- | --- |
| QuoterV2（Ethereum） | `0x61fFE014bA17989E743c5F6cB21bF9697530B21e`（业界标准 periphery；部署以 [Uniswap deployments](https://docs.uniswap.org/contracts/v3/reference/deployments) 为准） |
| 调用 | `eth_call`：`quoteExactInputSingle` / `quoteExactInput`（多跳 path） |
| 依赖 | ETH RPC（自建 / Alchemy / QuickNode…） |
| Rate limit | **RPC 供应商**限流，非 Uniswap 协议 |
| Gas | `eth_call` 无上链 gas；节点 CPU 成本仍在 |

#### Phase 1 推荐

- **默认**：链上 QuoterV2 + 固定 fee tier 探测（100/500/3000/10000）取最优可成交报价 → 语义 = Uniswap v3。  
- **可选加速**：Trading API 作对照，不作为唯一真相源，除非锁定 protocol filter。

---

### 5.2 Aerodrome（Base）

| 项目 | 值 |
| --- | --- |
| 架构 | Velodrome V2 系：vAMM / sAMM + CL |
| Router | `0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43` |
| Quoter | `0x254cF9E1E6e233aa1AC962CB9B05b2cfeAaE15b0` |
| MixedQuoter | `0x0A5aA5D3a4d28014f967Bf0f29EAA3FF9807D5c6` |
| 来源 | [aerodrome.finance/security](https://aerodrome.finance/security)、[aerodrome-finance/contracts](https://github.com/aerodrome-finance/contracts) |
| 公开 REST | **无**一等公民免费 quoter HTTP |
| 商业替代 | QuickNode **Aerodrome Swap API** addon：`GET .../v1/quote?target=base&from_token=&to_token=&amount=`（需 QN endpoint） |
| SDK 线索 | Velodrome/Aerodrome sugar-sdk（Base MCP 插件亦用其做 quote） |

#### Phase 1 推荐

1. Base RPC + **MixedQuoter**（同时覆盖 volatile/stable/CL）`eth_call`。  
2. 若团队已有 QuickNode：addon 可加速，但引入供应商依赖与计费。

---

### 5.3 PancakeSwap（BSC）

| 项目 | 值 |
| --- | --- |
| QuoterV2（BSC） | `0xB048Bbc1Ee6b733FFfCFb9e9CeF7375518e25997` |
| Smart Router（BSC/ETH 等同址文档列出） | `0x13f4EA83D0bd40E75C8222255bc855a974568Dd4` |
| 文档 | [PancakeSwap v3 addresses](https://developer.pancakeswap.finance/contracts/v3/addresses) |
| 调用 | 与 Uniswap v3 quoter 同族：`quoteExactInputSingle` 等 via `eth_call` |
| Rate limit | BSC RPC 供应商 |

#### Phase 1 推荐

- BSC RPC + QuoterV2；多版本池（v2/v3/Infinity）若要「全站最优」再上 Smart Router off-chain 路由库（`@pancakeswap/smart-router`），复杂度显著上升——**蓝筹 USDT/USDC 对先固定 v3 fee tier** 足够。

---

### 5.4 聚合器替代（0x / 1inch）— **仅 fallback**

| 聚合器 | Endpoint（现行） | Auth | Rate limit（公开档） | 是否适合当 venue 报价 |
| --- | --- | --- | --- | --- |
| **0x** | `GET https://api.0x.org/swap/allowance-holder/price`（指示性）/ `.../quote`（可执行） | `0x-api-key` + `0x-version: v2` | Free ≈ **5 RPS**（[docs](https://docs.0x.org/docs/developer-resources/rate-limits)） | ❌ 默认否：多源聚合 |
| **1inch** | Classic Swap quote API（portal） | API key | Free ≈ **1 RPS / 100k calls/mo**；Startup 10 RPS 等（[pricing](https://business.1inch.com/pricing)） | ❌ 默认否 |

**允许用法**：

- 探测「链上整体可成交价」对照；  
- RPC 故障时的降级（UI 须标注 `source=aggregator`）。

**禁止用法**：

- 把 0x/1inch 输出标成 `venue=uniswap` / `aerodrome` / `pancakeswap`。

---

## 6. 跨 venue 对照表（实现 checklist）

| Venue | Method | Path / 调用 | Auth | 深度 / 报价形态 | Rate limit（只读） | SDK / ccxt | 样本 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Binance spot | GET | `/api/v3/depth` | 无 | 聚合簿 ≤5000 | 6000 weight/min | ccxt ✅ / 原生 | ✅ |
| Binance USDM | GET | `/fapi/v1/depth` | 无 | 聚合簿（常用 ≤1000） | 2400 weight/min | ccxt ✅ | ✅ |
| Bybit | GET | `/v5/market/orderbook` | 无 | 聚合簿 ≤1000/侧 | IP 600/5s | ccxt ✅ | ✅ |
| Hyperliquid | POST | `/info` `l2Book` | 无 | ≤20/侧 | 1200 weight/min；l2=2 | 官方 SDK + ccxt ✅ | ✅ |
| Lighter | GET | `/api/v1/orderBookOrders` | 无 | 逐单 + limit | Standard 60/min | 官方 SDK + ccxt ✅ | ✅ |
| ApeX | GET | `/api/v3/depth` | 无 | 聚合簿 limit≤200 live | IP 600/min | 官方 SDK + ccxt ✅ | ✅ |
| Uniswap | eth_call / HTTP | QuoterV2 / Trading API | RPC / API key | 净输出 | RPC 或 portal | 合约 ABI | 地址表 |
| Aerodrome | eth_call | Quoter/MixedQuoter | RPC | 净输出 | RPC | sugar / ABI | 地址表 |
| Pancake | eth_call | QuoterV2 | RPC | 净输出 | RPC | ABI / smart-router | 地址表 |
| Prop AMM | GET | Jupiter `/quote?dexes=` | 可选 key | 净输出 | 见 WHI-797 | — | WHI-797 |

---

## 7. Adapter 落地注意事项（对接 WHI-799 / WHI-801）

1. **统一输出**：orderbook venue → walk 到 `q_star` 得 `effective_price`；AMM → `outAmount/inAmount` 得价格；均填同一 `Quote` + `snapshot_id`。
2. **符号映射**集中配置（WHI-798）：ApeX `BTCUSDT` vs `BTC-USDT`；HL spot `UBTC`；Lighter `market_id`。
3. **并发预算**（单 IP 粗算，保守）：

   | 源 | 建议稳态 |
   | --- | --- |
   | Binance spot | ≤20 depth/s（limit≤100 → weight 5 → 100 weight/s ≪ 6000/min） |
   | Binance fapi | ≤15 depth/s |
   | Bybit | ≤30 orderbook/s（远低于 600/5s） |
   | HL | ≤5 l2Book/s（weight 2） |
   | Lighter Standard | ≤1 orderBookOrders/s；**上 Builder 或 WS** |
   | ApeX | ≤5 depth/s |

4. **超时**：HTTP 客户端默认 2–3s；聚合层（WHI-807）对慢 venue 短路。
5. **不要**在 adapter 内用 ccxt 隐藏 rate limit——必须可读 `used-weight` / 429 并退避。

---

## 8. 源与复现

### 8.1 官方文档

- Binance Spot depth / limits：`binance-spot-api-docs` REST；`exchangeInfo.rateLimits` live  
- Bybit V5 orderbook + rate limit pages  
- Hyperliquid GitBook：info + rate limits  
- Lighter：`apidocs.lighter.xyz` rate-limits + orderBookOrders  
- ApeX：`api-docs.pro.apex.exchange`  
- Uniswap Developers Trading API  
- Aerodrome security / contracts addresses  
- PancakeSwap developer contracts v3 addresses  
- 0x rate limits；1inch portal pricing  

### 8.2 Live 探测命令（摘要）

```bash
# CEX
curl -sS 'https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=5'
curl -sS 'https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=5'
curl -sS 'https://api.bybit.com/v5/market/orderbook?category=linear&symbol=BTCUSDT&limit=5'

# Perp DEX
curl -sS -X POST 'https://api.hyperliquid.xyz/info' -H 'Content-Type: application/json' \
  -d '{"type":"l2Book","coin":"BTC"}'
curl -sS 'https://mainnet.zklighter.elliot.ai/api/v1/orderBookOrders?market_id=1&limit=5'
curl -sS 'https://omni.apex.exchange/api/v3/depth?symbol=BTCUSDT&limit=5'
```

### 8.3 已知缺口（可开后续 issue）

| 缺口 | 说明 |
| --- | --- |
| AMM live quoter 响应样本 | 本机无稳定公共 ETH/Base/BSC RPC 密钥；落地 WHI-80x 时用 CI 密钥补 JSON 样本 |
| Uniswap Trading API 是否可 filter 仅 Uniswap | 需持 key 实测响应 `route` 字段 |
| Lighter Builder 申请 | 多市场轮询生产路径前置 |
| HL >20 档 | 协议无官方更深 REST；大 notional 策略未决 |

---

## 9. 变更记录

| 日期 | 变更 |
| --- | --- |
| 2026-08-03 | 初版：CEX / Perp DEX live 样本 + AMM 合约路径 + 聚合器边界；对齐 WHI-798/799 |
