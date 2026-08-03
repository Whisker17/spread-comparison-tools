# WHI-799：Spread & 费用统计口径 + 统一数据模型

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-799](https://linear.app/whisker-personal/issue/WHI-799) |
| Milestone | M1 调研与口径定义 |
| Blocks | [WHI-801](https://linear.app/whisker-personal/issue/WHI-801)（FastAPI + adapter 接口）、[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)（费用数据整理） |
| Downstream | WHI-802…806（各 venue adapter）、WHI-807（`/quotes` + reference mid 服务）、WHI-813…815（fees / simulate） |
| 规范日期 | 2026-08-03（UTC） |
| 性质 | **规范（spec）**，非 live 探测；字段名与公式以本文为准，M2 代码不得另立口径 |

---

## 1. 结论摘要（TL;DR）

1. **名义金额（notional）**固定四档：`$1_000` / `$10_000` / `$100_000` / `$1_000_000`（USD）。先用 **reference mid** 换算目标 base 数量，再 walk book / 调 quoter。
2. **Effective spread at size**（单边，bps）：
   - Buy：`spread_bps = (effective_price - mid) / mid * 10_000`
   - Sell：`spread_bps = (mid - effective_price) / mid * 10_000`
   - 双边汇总：`round_trip_spread_bps = buy + sell`，`half_spread_bps = round_trip / 2`。
3. **Top-of-book spread**仅 orderbook venue：`(best_ask - best_bid) / mid_ref * 10_000`；AMM / Prop AMM 的 `get_orderbook_spread` **返回 `None`**（不用假 TOB）。
4. **Reference mid**（全 venue 共用，绑定 `snapshot_id`）：
   - Crypto blue chips **P0**：Binance USDT-M **indexPrice**（`GET /fapi/v1/premiumIndex`）；**P1** Binance spot TOB mid；**P2** Bybit spot TOB；**P3** Pyth `price`（不用 conf 区间中点）。
   - Spot 与 Perp **共用同一 mid**；**Funding 不计入**默认 `total_cost_bps`。
5. **Total cost（单一权威公式，§5.2）**：
   - `trading_component_bps` = 0 若 `embedded_in_price`，否则 = 显式 trading fee bps
   - `total_cost_bps = spread_bps + trading_component_bps + platform_fee_bps + gas_bps`
   - `explicit_fee_bps` 定义为 **已计入 total 的非价差费之和** = `trading_component_bps + platform_fee_bps + gas_bps`（始终与 total 一致，禁止第三套定义）
6. **统一模型**：`Quote`、`TopOfBook`、`FeeBreakdown`、`FeeSchedule`、`ReferenceMid`；均携带 `snapshot_id`；adapter 抽象见 §7。

---

## 2. 范围与术语

### 2.1 Venue classes（与 [WHI-798](./WHI-798-asset-category-inventory.md) 对齐）

| Class | Venues（Phase 1） | 报价机制 |
| --- | --- | --- |
| CEX | Binance, Bybit | Orderbook walk |
| Perp DEX | Hyperliquid, Lighter, ApeX | Orderbook walk |
| AMM DEX | Uniswap (ETH), Aerodrome (Base), PancakeSwap (BSC) | Quoter / router |
| Prop AMM | HumidiFi, **Tessera**（Jupiter label `TesseraV`）, BisonFi（见 [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md)） | 净输出报价（fee 内嵌） |

Venue **显示名**用 Tessera；**slug** `tessera`；Jupiter `dexes` 参数仍必须精确 `TesseraV`（WHI-797）。

### 2.2 符号约定

| 符号 | 含义 |
| --- | --- |
| `asset` | 规范资产 ID（`BTC` / `ETH` / `SOL` / …）；venue 本地 symbol 进 `venue_symbol` |
| `snapshot_id` | 一次聚合/采集快照的 UUID 或时间桶 ID；同一快照内 mid 与全部 Quote 共享 |
| `mid` / `mid_ref` | 该快照该 `asset` 的 **reference mid**（quote per base，USD） |
| `N` / `notional_usd` | 名义金额（USD） |
| `q_star = N / mid` | 目标 base 数量 |
| `P_star` / `effective_price` | 成交均价（quote per base） |
| `side` | `buy` = 用 quote 买 base；`sell` = 卖 base 得 quote |
| bps | 1 bps = 0.01%；相对量一律 `* 10_000` |

价格单位：**quote per 1 base**（如 USDT per BTC）。稳定币按 1 USD 计名义；包装资产映射见 [WHI-798 §3.3](./WHI-798-asset-category-inventory.md)。

### 2.3 非目标（本 spec 不定义）

- 具体 HTTP path 的 OpenAPI（属 WHI-801 / WHI-807）。
- 各 venue 真实费率数字与官方链接清单（属 WHI-812；本文只定 **FeeSchedule 形状** 与入 total 规则）。
- 历史窗口统计（mean/median/P95，属 WHI-817）。
- 聚合层超时/缓存的最终 SLA 数字（属 WHI-807；本文仅约定 adapter 同步返回语义）。
- Slippage tolerance / 链上真实 fill vs 报价（Phase 1 只做 **可成交报价** 对比）。
- 前端默认列、排序文案、闭市标注等 UI 政策（属 WHI-808+；§9 仅列**指标可选集合**，不锁死产品默认）。

---

## 3. Reference mid

### 3.1 为何必须「全 venue 同一 mid」

跨 venue 比较的是「相对公允价的执行偏离」。若各 venue 用自家 mid/mark，mid 漂移会被算进 spread，**不可比**。

规则：

1. 每次聚合或采集 tick 分配一个 **`snapshot_id`**。
2. 对该 `snapshot_id` 下每个 `asset` **只解析一次** `ReferenceMid`。
3. 所有 venue 的 `Quote.mid` / `Quote.mid_source` / `Quote.snapshot_id` / `Quote.mid_timestamp` 填同一套值。

### 3.2 选取优先级（Crypto blue chips：BTC / ETH / SOL）

| 优先级 | `mid_source` 枚举值 | 定义与可调用端点 | 何时用 |
| --- | --- | --- | --- |
| **P0** | `binance_usdm_index` | Binance USDT-M **indexPrice**：`GET https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT`（字段 `indexPrice`；ETH/SOL 同理 `ETHUSDT` / `SOLUSDT`）。这是合约 index（一篮子现货合成），**不是** spot 专用 index API——行业里常作 crypto fair mid。 | 有则必用 |
| **P1** | `binance_spot_tob` | Spot bookTicker mid：`GET https://api.binance.com/api/v3/ticker/bookTicker?symbol=BTCUSDT` → `(bidPrice+askPrice)/2` | P0 失败 |
| **P2** | `bybit_spot_tob` | Bybit spot best bid/ask mid（linear/spot ticker） | Binance 均失败 |
| **P3** | `pyth` | Pyth Hermes/price feed 的 **`price` 字段**（已按 `expo` 缩放后的实数价）。**不要**用 conf 区间中点。Feed id 进配置（WHI-807）。 | CEX 均失败；或配置 `MID_FORCE_PYTH=true` |

Staleness：

- `ReferenceMid.timestamp` = mid 观测 UTC。
- 每个 Quote 复制 `mid_timestamp`；并算 `mid_stale = abs(quote.timestamp - mid_timestamp) > 5s`（阈值常量 `MID_STALE_THRESHOLD_SEC = 5`，可配置）。
- mid 服务整体失败 → 聚合 **不**返回残缺可比集（503/422）；**禁止**静默用过期缓存超过配置上限（建议 max age 30s）。

### 3.3 Stocks / Others

| 资产类 | mid 策略 |
| --- | --- |
| Equity perps | 优先 CEX TradFi index（若 API 有）；否则 **多 venue perp mark 中位数**，`mid_source=proxy_perp_mark_median`（弱于 crypto P0，UI 须标注） |
| Tokenized spot（xStocks） | 与对应 equity 共用参考价；**禁止**单池 mid 当跨 venue reference |
| Others | 同 §3.2；无 index 时 P1/P2 spot TOB |

### 3.4 Spot vs Perp 可比性

| 决策 | 口径 |
| --- | --- |
| 共用 mid | Perp 与 spot 都相对 **同一** reference mid 算 `spread_bps` |
| Basis | 可选 `venue_mark`、`basis_bps = (venue_mark - mid) / mid * 10_000`；**不**并入 `spread_bps` |
| Funding | **默认不计入** spread / total cost（§5.3） |
| 合约乘数 | `1000PEPE` / `kPEPE` 等在 adapter 内换算为规范 `asset` 的 1× 单位（[WHI-798](./WHI-798-asset-category-inventory.md)） |

### 3.5 `ReferenceMid` 模型

```text
ReferenceMid {
  snapshot_id:      str              # 与同批 Quote 共享
  asset:            str
  mid:              Decimal          # quote per base，USD
  mid_source:       str              # 仅允许 §3.2 / §3.3 枚举值
  timestamp:        datetime         # mid 观测 UTC（= Quote.mid_timestamp）
  sources_detail:   list[str] | null # 多源合成时的原始源
}
```

`quote_currency` 固定为 USD 名义口径，**不**进模型字段（避免单值字段）。

---

## 4. Effective spread at size

### 4.1 固定 size 档位

```text
NOTIONAL_TIERS_USD = [1_000, 10_000, 100_000, 1_000_000]
```

- API 允许子集；collector（WHI-816）必须四档都采。
- `notional_usd` 与档位用 Decimal 精确相等比较。

### 4.2 数量换算（所有 venue 统一）

```text
q_star = notional_usd / mid
```

- **只用** reference mid 换算；禁止 venue-local mid。
- 深度不足以成交 `q_star` → `status=insufficient_liquidity`，价格字段 null（§6.5）。

### 4.3 Orderbook：walk-the-book → VWAP

**Buy**（吃 ask）：从最优 ask 起累加 base 至 ≥ `q_star`（末档可 partial）。

```text
P_star = sum(price_i * qty_i) / sum(qty_i)
```

**Sell**（吃 bid）：对称从最优 bid 向下。

- 中间计算 `Decimal`；落库/API：价格 ≥8 位有效数字，bps 保留 4 位小数。

### 4.4 AMM / Prop AMM：报价 → effective price

| Side | 推荐请求 | `P_star` |
| --- | --- | --- |
| `buy` | ExactOut base = `q_star`（若支持）；否则 ExactIn quote≈N | `quote_in / base_out` |
| `sell` | ExactIn base = `q_star` | `quote_out / base_in` |

**Prop AMM / Jupiter**（[WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md)）：

- 用 `outAmount`（已扣 AMM fee；`platformFee` 保持 0）。
- `embedded_in_price = true`。
- 无路由：`status=no_quote`（不抛 5xx）。

**公共 AMM**：

- 净输出 → `embedded_in_price=true`；池费档写入 `lp_fee_tier_bps`（**信息字段**，不进 `trading_component_bps`）。
- Gas **不**在价内 → `gas_usd` / `gas_bps`；若无法估算 → `gas_usd=null` 且 `gas_unknown=true`（§5.2）。

ExactOut 不可用时允许 approx，且必须 `qty_method=quote_exact_in_approx`。

### 4.5 Spread 公式（单边）— 唯一权威

```text
buy:  spread_bps = (P_star - mid) / mid * 10_000
sell: spread_bps = (mid - P_star) / mid * 10_000
```

- 正常流动性下 ≥ 0；负值保留（优于 mid / mid 偏差），**不**截断为 0。
- **谁计算**：adapter 在已知 `mid` 后计算 `spread_bps` 与 `total_cost_bps`。聚合层 **不得**改 bps 定义；仅在「adapter 只回 raw price、由聚合层统一套 mid」的实现变体中，聚合层用**同一公式**补算——两种实现选其一，测试锁定结果。

### 4.6 双边汇总

对同一 `(snapshot_id, venue, asset, notional_usd)`：

| 指标 | 公式 |
| --- | --- |
| `round_trip_spread_bps` | `buy_spread_bps + sell_spread_bps` |
| `half_spread_bps` | `round_trip_spread_bps / 2` |
| `round_trip_total_cost_bps` | `buy.total_cost_bps + sell.total_cost_bps`（两侧皆 `ok` 且 gas 可知） |

任一侧非 `ok` → 对应汇总字段 `null`；另一侧单边 Quote 仍返回。

### 4.7 数值示例（规范测试向量）

**设定**：`mid = 100_000` USD/BTC，`N = 10_000` → `q_star = 0.1` BTC。

**Orderbook asks**（buy）：

| Level | Price | Size (BTC) |
| --- | --- | --- |
| 1 | 100_010 | 0.04 |
| 2 | 100_050 | 0.04 |
| 3 | 100_100 | 0.10 |

Walk 0.1 BTC：`0.04*100010 + 0.04*100050 + 0.02*100100 = 10004.4`  
`P_star = 10004.4 / 0.1 = 100_044`  
`spread_bps = (100044 - 100000) / 100000 * 10000 = 4.4`

**CEX，taker 10 bps，价未含 fee**：

```text
embedded_in_price = false
trading_component_bps = 10
platform_fee_bps = 0
gas_bps = 0
explicit_fee_bps = 10
total_cost_bps = 4.4 + 10 = 14.4
```

**Prop AMM，净价 `P_star = 100_044`，fee 已嵌，无 gas**：

```text
embedded_in_price = true
trading_component_bps = 0
platform_fee_bps = 0
gas_bps = 0
explicit_fee_bps = 0
total_cost_bps = 4.4
```

WHI-802 单测应固定上述 book fixture，断言 `spread_bps == 4.4`。

---

## 5. 费用与 Total cost of execution

### 5.1 费用组件

| 组件 | 适用 | 计入默认 total？ | 说明 |
| --- | --- | --- | --- |
| Trading fee（taker/maker） | CEX / Perp | ✅ 经 `trading_component_bps` | Phase 1 默认 **taker** |
| LP / pool fee | AMM | ❌ 价内；仅 `lp_fee_tier_bps` 信息 | |
| Embedded AMM/prop fee | Prop / 部分 AMM | ❌ 已在 `P_star` | `embedded_in_price=true` |
| Platform fee | 聚合器 | ✅ `platform_fee_bps` | Phase 1 Jupiter 默认 0 |
| Gas | 链上 | ✅ `gas_bps`；未知则见下 | |
| Funding | Perp | ❌ 默认 | §5.3 |
| 出入金 / bridge | — | ❌ Phase 1 | |

### 5.2 唯一权威公式

所有章节（含 TL;DR、示例）引用本节，不得另写分支语义。

```text
# 1) trading 是否已在价内
if fee_breakdown.embedded_in_price:
    trading_component_bps = 0
else:
    trading_component_bps = trading_fee_bps   # 来自 FeeSchedule 选用档，通常 taker

# 2) gas
if gas_unknown:
    gas_bps = null                            # 见下：total 也 null
elif gas_usd is null:
    gas_bps = 0                               # 明确「无链上 gas」（CEX/perp）
else:
    gas_bps = gas_usd / notional_usd * 10_000

# 3) platform（即使 embedded 也加——平台费不在 pool 曲线内）
platform_fee_bps = platform_fee_bps or 0

# 4) 汇总
explicit_fee_bps = trading_component_bps + platform_fee_bps + (gas_bps or 0)
# 注意：gas_unknown 时不定义 explicit/total（见下）

if gas_unknown:
    total_cost_bps = null                     # 禁止把未知 gas 当 0 去排序
    fee_breakdown.explicit_fee_bps = null
else:
    total_cost_bps = spread_bps + trading_component_bps + platform_fee_bps + gas_bps
    fee_breakdown.explicit_fee_bps = explicit_fee_bps
```

**排序规则（给 dashboard / simulate）**：仅 `status=ok` 且 `total_cost_bps is not null` 参与「最优」排序；`gas_unknown` 行单独分组或标「成本不完整」，**不得**因 gas=0 幻觉排到最前。

### 5.3 Funding 政策

| 场景 | 处理 |
| --- | --- |
| 主表 / `/quotes` | **忽略 funding** |
| 费用信息展示 | 展示 `funding_rate_8h`（**小数**，如 `0.0001` = 每 8h 1 bps 名义） |
| 可选持有 T 小时 | 见下式；字段名 `total_cost_with_funding_bps`，默认 API 可省略 |

```text
# position_side: 与 Quote.side 对齐——buy=开/持有多，sell=开/持有空（Phase 1 简化）
# funding_rate_8h > 0 表示多头支付空头
sign = +1 if position_side == "buy" else -1
funding_cost_bps = sign * funding_rate_8h * (T_hours / 8) * 10_000
total_cost_with_funding_bps = total_cost_bps + funding_cost_bps
# 仅当 total_cost_bps 非 null
```

### 5.4 `FeeBreakdown`（每笔 Quote 内嵌）

```text
FeeBreakdown {
  embedded_in_price:   bool
  fee_tier:            str | null          # "default_taker" | "vip0" | "pool_0.05%"
  trading_fee_bps:     Decimal | null      # 费率表取值；embedded 时可为 null
  trading_fee_usd:     Decimal | null      # 可选；若填则应 ≈ trading_fee_bps/1e4 * N
  platform_fee_bps:    Decimal             # 默认 0，非 null
  lp_fee_tier_bps:     Decimal | null      # 信息
  gas_usd:             Decimal | null
  gas_bps:             Decimal | null
  gas_unknown:         bool                # true ⇒ total_cost_bps 必须 null
  funding_rate_8h:     Decimal | null      # 小数，非 bps
  explicit_fee_bps:    Decimal | null      # §5.2 定义
  notes:               str | null
}
```

bps 与 USD 成对字段：以 **bps 为权威**；USD 为派生展示，测试只锁 bps。

### 5.5 `FeeSchedule`（venue 级，WHI-812 填充）

```text
FeeSchedule {
  venue:                 str               # §6.4 slug
  asset:                 str | null        # null = venue 默认
  instrument_type:       "spot" | "perp" | "amm_pool" | "prop_amm"
  maker_bps:             Decimal | null
  taker_bps:             Decimal | null
  tiers:                 list[FeeTier] | null
  default_tier:          str               # Phase 1: "default_taker"
  lp_fee_tiers_bps:      list[Decimal] | null
  gas_estimate_usd:      Decimal | null    # 静态缺省；实时以 Quote 为准
  funding_model:         "none" | "perp_8h" | "perp_continuous"
  fee_embedded_in_quote: bool
  source_urls:           list[str]         # 官方费率页（WHI-812 验收）
  updated_at:            datetime
}

FeeTier {
  name:                  str
  maker_bps:             Decimal
  taker_bps:             Decimal
  volume_requirement:    str | null
}
```

---

## 6. 统一数据模型

### 6.1 共享状态枚举

```text
QuoteStatus =
  | "ok"
  | "no_quote"                 # 无市场 / 无路由
  | "insufficient_liquidity"   # 深度不够 q_star
  | "unsupported_asset"
  | "error"
```

（`TopOfBook` 不复用该枚举——orderbook 适配器用返回值 `None` 表示「本 venue 无 TOB 概念」，见 §6.2 / §7。）

### 6.2 `Quote`

```text
Quote {
  # --- identity ---
  snapshot_id:        str
  venue:              str                 # §6.4 slug
  asset:              str
  venue_symbol:       str | null
  instrument_type:    "spot" | "perp" | "amm_pool" | "prop_amm"
  side:               "buy" | "sell"
  notional_usd:       Decimal

  # --- mid & price ---
  mid:                Decimal
  mid_source:         str
  mid_timestamp:      datetime
  mid_stale:          bool
  effective_price:    Decimal | null
  spread_bps:         Decimal | null

  # --- fees & total ---
  fee_breakdown:      FeeBreakdown
  total_cost_bps:     Decimal | null      # gas_unknown 或 status!=ok 时 null

  # --- book-keeping ---
  timestamp:          datetime            # venue 报价时刻 UTC
  status:             QuoteStatus
  qty_base:           Decimal | null
  qty_method:         "base_from_mid" | "quote_exact_in_approx" | null
  venue_mark:         Decimal | null
  basis_bps:          Decimal | null
  raw_ref:            str | null

  error_code:         str | null
  error_message:      str | null
}
```

**不变量**：

1. `status == "ok"` ⇒ `effective_price`、`spread_bps`、`qty_base` 非 null；且（`gas_unknown` ⇒ `total_cost_bps is null`）或（非 `gas_unknown` ⇒ `total_cost_bps` 非 null）。
2. `status != "ok"` ⇒ `effective_price`、`spread_bps`、`total_cost_bps`、`qty_base` 均为 null。
3. `snapshot_id` / `mid` / `mid_source` / `mid_timestamp` 在同快照同资产上全 venue 一致。
4. bps 公式 **仅** §4.5 / §5.2。

### 6.3 `TopOfBook`

仅 orderbook venue 返回该对象；AMM / Prop 的接口返回 **`None`**（不是带 `unsupported` status 的空壳）。

```text
TopOfBook {
  snapshot_id:        str
  venue:              str
  asset:              str
  best_bid:           Decimal
  best_ask:           Decimal
  bid_size:           Decimal | null      # base
  ask_size:           Decimal | null
  mid_local:          Decimal             # (bid+ask)/2
  mid_ref:            Decimal
  mid_timestamp:      datetime
  spread_bps:         Decimal             # (ask - bid) / mid_ref * 10_000
  spread_bps_local:   Decimal             # (ask - bid) / mid_local * 10_000
  timestamp:          datetime
}
```

- 拉簿失败：`get_orderbook_spread` 抛错或由 adapter 约定返回错误由聚合层记 venue error——**不要**用「status 枚举 + 空价格」双轨。成功则字段全非 null（size 除外）。
- 主对比用 `spread_bps`（相对 `mid_ref`）。

### 6.4 双边汇总视图（聚合层可合成）

```text
SizeQuotePair {
  snapshot_id:               str
  venue:                     str
  asset:                     str
  notional_usd:              Decimal
  buy:                       Quote | null
  sell:                      Quote | null
  round_trip_spread_bps:     Decimal | null
  half_spread_bps:           Decimal | null
  round_trip_total_cost_bps: Decimal | null
  top_of_book:               TopOfBook | null
}
```

### 6.5 Venue slug 注册表（稳定，禁止别名漂移）

| slug | 显示名 | Class | 备注 |
| --- | --- | --- | --- |
| `binance` | Binance | CEX | |
| `bybit` | Bybit | CEX | |
| `hyperliquid` | Hyperliquid | Perp DEX | |
| `lighter` | Lighter | Perp DEX | |
| `apex` | ApeX | Perp DEX | |
| `uniswap_eth` | Uniswap (Ethereum) | AMM | |
| `aerodrome_base` | Aerodrome (Base) | AMM | |
| `pancakeswap_bsc` | PancakeSwap (BSC) | AMM | |
| `humidifi` | HumidiFi | Prop AMM | Jupiter `dexes=HumidiFi` |
| `tessera` | Tessera | Prop AMM | Jupiter `dexes=TesseraV`（label ≠ slug） |
| `bisonfi` | BisonFi | Prop AMM | Jupiter `dexes=BisonFi` |

### 6.6 错误与降级语义

| 情况 | Quote.status | 聚合 |
| --- | --- | --- |
| 无 pair / 无路由 | `no_quote` | 200，该行 N/A |
| 深度 < `q_star` | `insufficient_liquidity` | 200 |
| 资产不支持 | `unsupported_asset` | 200 |
| 超时 / 上游失败 | `error` | 200 + 该 venue 错误；不整包失败 |
| mid 不可用 | — | 整包 503/422 |

---

## 7. Adapter 抽象（WHI-801 直接输入）

```text
class VenueAdapter(Protocol):
    venue: str                          # §6.5 slug
    venue_class: Literal["cex", "perp_dex", "amm_dex", "prop_amm"]

    def get_quote(
        self,
        asset: str,
        side: Literal["buy", "sell"],
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,              # 含 snapshot_id
        fee_tier: str | None = None,
    ) -> Quote: ...

    def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
    ) -> TopOfBook | None:
        """CEX/Perp: TopOfBook. AMM/Prop: always None."""
        ...

    def get_fees(self, asset: str | None = None) -> FeeSchedule: ...

    def supported_assets(self) -> list[str]: ...
```

| 层 | 职责 |
| --- | --- |
| Adapter | 深度/报价；walk 或 quoter；填 `effective_price`、fee/gas；按 §4.5/§5.2 算 bps |
| Mid service | 解析 `ReferenceMid`（含 `snapshot_id`） |
| Aggregator | 并发、超时、缓存；拼 `SizeQuotePair`；**不**另立 bps 公式 |
| Fee config | 静态 `FeeSchedule` |

---

## 8. 按 venue class 的实现备忘

| Class | `get_quote` | `get_orderbook_spread` | Fee |
| --- | --- | --- | --- |
| CEX | L2 walk `q_star` | `TopOfBook` | 默认 taker；`embedded_in_price=false`；`gas_unknown=false`，`gas_bps=0` |
| Perp DEX | L2 walk；lot/tick | `TopOfBook` | 同上 + `funding_rate_8h`；可选 `venue_mark` |
| AMM DEX | Quoter + gas | `None` | 价内嵌 LP；gas 可知则填，否则 `gas_unknown=true` |
| Prop AMM | Jupiter `dexes=<Label>` 净输出 | `None` | `embedded_in_price=true`；platform 0；无路由 → `no_quote` |

---

## 9. 指标在产品中的用法（非 UI 规格）

供 dashboard / summary **选用**的指标集合（具体默认列由 WHI-808+ 定）：

- 单边：`spread_bps`、`total_cost_bps`（buy 或 sell）
- 双边：`half_spread_bps`、`round_trip_spread_bps`、`round_trip_total_cost_bps`
- 盘口：`TopOfBook.spread_bps`（仅 orderbook）
- 完整性：过滤 `status!=ok` 与 `total_cost_bps is null`（`gas_unknown`）后再比「谁更便宜」
- 时间：展示 `timestamp` 与 `mid_timestamp`；`mid_stale=true` 时提示

bps API 保留 4 位小数；展示可再圆整到 2 位。

---

## 10. 验收标准（本 issue）

- [x] Effective spread at size（四档、买/卖、双边汇总）
- [x] Top-of-book（仅 orderbook；AMM 返回 `None`）
- [x] Reference mid 优先级（可调用端点）+ spot/perp/funding 政策
- [x] Total cost **单一**公式 + 反双计 + `gas_unknown` 不假排序
- [x] `Quote` / `TopOfBook` / `FeeBreakdown` / `FeeSchedule` / `ReferenceMid`（含 `snapshot_id`、`mid_stale`）
- [x] Adapter Protocol 可供 WHI-801 直接编码
- [x] 数值测试向量（§4.7 → `spread_bps=4.4`）

---

## 11. 开放问题（不阻塞 M2；拍板后 ADR）

| ID | 问题 | 临时默认 |
| --- | --- | --- |
| Q1 | Stocks 是否强制外部 equity feed | proxy mark 中位数 + 标注 |
| Q2 | 产品主列默认 half-spread 还是 total cost (buy) | 建议 total cost (buy)；UI 可切换 |
| Q3 | VIP 是否进 Phase 1 主路径 | 仅 `default_taker` |
| Q4 | Gas 用即时价还是分位 | 即时 + 保守 gas limit（WHI-804/812） |

---

## 12. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-799-spread-fee-data-model.md` | 本文（M2 口径与模型 SSOT） |
| `README.md` | Research 表增加本 issue 链接 |

## 13. 参考与复用来源

- [WHI-797 Prop AMM + Jupiter Quote](./WHI-797-prop-amm-jupiter-quote-api.md) — `dexes` label、fee 内嵌、`outAmount` 语义
- [WHI-798 资产清单](./WHI-798-asset-category-inventory.md) — venue class、包装资产、乘数
- Binance USDT-M premium index：`GET /fapi/v1/premiumIndex`
- Binance spot bookTicker：`GET /api/v3/ticker/bookTicker`
- Linear [WHI-799](https://linear.app/whisker-personal/issue/WHI-799)、[WHI-801](https://linear.app/whisker-personal/issue/WHI-801)、[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)

## 14. 修订记录

| 日期 | 变更 |
| --- | --- |
| 2026-08-03 | 初版 |
| 2026-08-03 | Review round 1：统一 total/explicit 公式；`snapshot_id`/`mid_stale`/`gas_unknown`；可调用 mid 端点；Tessera slug；去掉 LaTeX；TOB 仅 `None` 双轨消除；funding 带 side |
