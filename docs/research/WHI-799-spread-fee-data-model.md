# WHI-799：Spread & 费用统计口径 + 统一数据模型

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-799](https://linear.app/whisker-personal/issue/WHI-799) |
| Milestone | M1 调研与口径定义 |
| Blocks | [WHI-801](https://linear.app/whisker-personal/issue/WHI-801)（FastAPI + adapter 接口）、[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)（费用数据整理） |
| Downstream | WHI-802…806（各 venue adapter）、WHI-807（`/quotes` + reference mid 服务）、WHI-813…815（fees / simulate） |
| 调研日期 | 2026-08-03（UTC） |
| 性质 | **规范（spec）**，非 live 探测；字段名与公式以本文为准，M2 代码不得另立口径 |

---

## 1. 结论摘要（TL;DR）

1. **名义金额（notional）**固定四档：`$1_000` / `$10_000` / `$100_000` / `$1_000_000`（USD）。先用 **reference mid** 换算目标 base 数量，再 walk book / 调 quoter。
2. **Effective spread at size**（单边，bps）：
   - Buy：`spread_bps = (effective_price − mid) / mid × 10_000`
   - Sell：`spread_bps = (mid − effective_price) / mid × 10_000`
   - 双边汇总默认展示 **round-trip** `buy_bps + sell_bps`，并附 **half-spread** `round_trip / 2`。
3. **Top-of-book spread**仅 orderbook venue：`(best_ask − best_bid) / mid_ref × 10_000`；AMM / Prop AMM 返回 `null`。
4. **Reference mid**（全 venue 共用，每资产每快照一条）：
   - Crypto blue chips **主源**：Binance USDT 现货 index（不可用则 Binance spot TOB mid）；**备源** Pyth。
   - Spot 与 Perp **共用同一 mid**（现货 index），禁止用各 venue 自有 mark 当跨 venue 基准。
   - **Funding 不计入** `spread_bps` / 默认 `total_cost_bps`；单独字段记录，仅在「持仓期成本」可选视图中折算。
5. **Total cost of execution**：`total_cost_bps = spread_bps + explicit_fee_bps + gas_bps`。**禁止双计**：若报价已内嵌 fee（Prop AMM / 多数 AMM quoter 的净输出），则 `embedded_in_price=true`，`explicit_fee_bps=0`，`spread_bps` 已含该 fee。
6. **统一模型**（M2 直接落地）：`Quote`、`TopOfBook`、`FeeBreakdown`、`FeeSchedule`、`ReferenceMid`；adapter 抽象见 §7。

---

## 2. 范围与术语

### 2.1 Venue classes（与 WHI-798 对齐）

| Class | Venues（Phase 1） | 报价机制 |
| --- | --- | --- |
| CEX | Binance, Bybit | Orderbook walk |
| Perp DEX | Hyperliquid, Lighter, ApeX | Orderbook walk |
| AMM DEX | Uniswap (ETH), Aerodrome (Base), PancakeSwap (BSC) | Quoter / router |
| Prop AMM | HumidiFi, TesseraV, BisonFi（via Jupiter `dexes`，见 WHI-797） | 净输出报价（fee 内嵌） |

### 2.2 符号约定

| 符号 | 含义 |
| --- | --- |
| `asset` | 规范资产 ID（`BTC` / `ETH` / `SOL` / …）；venue 本地 symbol 进 `venue_symbol`，不进 `asset` |
| `mid` / `mid_ref` | 本快照该 `asset` 的 **reference mid**（quote per base，USD 计价） |
| `notional_usd` \(N\) | 名义金额（USD） |
| \(q^\* = N / mid\) | 目标 base 数量 |
| `effective_price` \(P^\*\) | 成交均价（quote per base） |
| `side` | `buy` = 用 quote 买 base；`sell` = 卖 base 得 quote |
| bps | 1 bps = 0.01% = \(10^{-4}\) 相对 mid；公式统一 × `10_000` |

价格单位：**quote per 1 base**（如 USDT per BTC）。稳定币按 1 USD 计名义；多稳定币对优先 USDC/USDT 映射见 WHI-798 表示表。

### 2.3 非目标（本 spec 不定义）

- 具体 HTTP path 的 OpenAPI（属 WHI-801 / WHI-807）。
- 各 venue 真实费率数字与官方链接清单（属 WHI-812；本文只定 **FeeSchedule 形状** 与入 `total_cost` 规则）。
- 历史窗口统计（mean/median/P95，属 WHI-817）。
- Slippage tolerance / 实际链上成交 vs 报价偏差（Phase 1 只做 **可成交报价** 对比，不做 fill 仿真）。

---

## 3. Reference mid

### 3.1 为何必须「全 venue 同一 mid」

跨 venue 比较的是「相对公允价的执行偏离」，不是「相对自家盘口 mid 的半价差」。若 Binance 用 Binance mid、HL 用 HL mark，则 mid 漂移会被算进 spread，**不可比**。

规则：**同一 `(asset, snapshot_id)` 只取一次 mid**，所有 venue 的 `Quote.mid` 填同一值与同一 `mid_source`。

### 3.2 选取优先级（Crypto blue chips：BTC / ETH / SOL）

| 优先级 | 来源 | 定义 | 何时用 |
| --- | --- | --- | --- |
| **P0** | Binance **spot index**（USDT 对） | 交易所公布的 index price | 有则必用 |
| **P1** | Binance spot TOB mid | `(best_bid + best_ask) / 2` | index 不可用 |
| **P2** | Bybit spot TOB mid | 同上 | Binance 不可用 |
| **P3** | Pyth price feed（对应资产） | oracle 置信区间中点或官方 price | CEX 均不可用；或配置强制 oracle 模式 |

实现备注（WHI-807）：

- 一次聚合请求内 mid 只解析一次，写入 `ReferenceMid` 并下发给各 adapter 或在聚合层统一重算 `spread_bps`。
- 记录 `mid_timestamp`；与 quote 时间差超过阈值（建议 **5s**）时，响应带 `mid_stale=true` 警告，**不**静默使用过期 mid。

### 3.3 Stocks / Others

| 资产类 | mid 策略 |
| --- | --- |
| Equity perps（TSLA 等） | 优先该标的 **CEX TradFi index / mark 的现货等价 index**（若有）；否则用 **多 venue perp mark 的中位数** 作 *proxy mid*，并在 UI 标注 `mid_source=proxy_perp_mark_median`（**弱于** crypto P0） |
| Tokenized spot（xStocks） | 优先对应 equity 参考价（与 perp 对比时共用）；链上仅有池价时 **不得** 用单池 mid 当跨 venue reference |
| Others（meme / L1） | 同 §3.2；无可靠 index 时降级到 Binance/Bybit spot TOB mid |

### 3.4 Spot vs Perp 可比性

| 决策 | 口径 |
| --- | --- |
| 共用 mid | Perp 与 spot **都相对同一 spot/index mid** 算 `spread_bps` |
| Basis 可见性 | 可选字段 `venue_mark` / `basis_bps = (venue_mark − mid) / mid × 10_000`，**不**并入 `spread_bps` |
| Funding | **默认不计入** spread / total cost（见 §5.3） |
| 合约乘数 | `1000PEPE` / `kPEPE` 等在 adapter 内换算为规范 `asset` 的 1× 单位后再报价（WHI-798） |

### 3.5 `ReferenceMid` 模型

```text
ReferenceMid {
  asset:            str              # 规范资产 ID
  mid:              Decimal          # quote per base
  mid_source:       str              # e.g. "binance_spot_index" | "binance_spot_tob" | "pyth" | "proxy_perp_mark_median"
  quote_currency:   str              # "USD" （名义与展示统一折 USD）
  timestamp:        datetime         # mid 观测 UTC
  sources_detail:   list[str] | null # 可选：多源合成时的原始来源
}
```

---

## 4. Effective spread at size

### 4.1 固定 size 档位

```text
NOTIONAL_TIERS_USD = [1_000, 10_000, 100_000, 1_000_000]
```

- Dashboard 默认四档全出；API 允许子集，但 collector（WHI-816）必须四档都采。
- `notional_usd` 与档位比较用数值相等（Decimal），禁止用「约 1k」模糊匹配。

### 4.2 数量换算（所有 venue 统一）

\[
q^\* = \frac{N}{mid}
\]

- 在 **reference mid** 下把 USD 名义换成 base 数量，再向该 venue 要「买入/卖出 \(q^\*\) base」的执行价。
- **不要**按 venue-local mid 换算 \(q^\*\)（否则各 venue 实际比较的 size 不一致）。
- 深度不足：无法填满 \(q^\*\) → `status=insufficient_liquidity`，`effective_price` / `spread_bps` 为 `null`（见 §6.5）。

### 4.3 Orderbook：walk-the-book → VWAP

对 **买**（吃 ask）：

1. 从最优 ask 起沿价位累加 base，直到累计 base \(\ge q^\*\)（最后一档按比例吃 partial level）。
2. \(P^\* = \dfrac{\sum_i p_i \cdot q_i}{\sum_i q_i}\)（成交 quote 总额 / 成交 base 总额）。

对 **卖**（吃 bid）：对称，从最优 bid 向下 walk。

实现约束：

- 使用 **可成交** 深度（L2）；忽略自己的挂单（公开 API 通常无此区分，Phase 1 忽略）。
- 价格与数量精度：中间计算用 `Decimal`；写入 Quote 时价格建议 8 位有效小数、bps 保留 4 位小数（展示可再圆整）。

### 4.4 AMM / Prop AMM：报价 → effective price

目标：得到与 orderbook 同语义的 \(P^\*\)（quote per base）。

| Side | 推荐请求语义 | \(P^\*\) |
| --- | --- | --- |
| `buy` | ExactIn **quote** 使输出 base \(\approx q^\*\)，或 ExactOut base \(= q^\*\)（若 API 支持） | `quote_in / base_out` |
| `sell` | ExactIn base \(= q^\*\) | `quote_out / base_in` |

**Prop AMM / Jupiter**（WHI-797）：

- 使用 `outAmount`（已扣 AMM fee；`platformFee` 保持 null / 0）。
- `embedded_in_price = true`。
- 无路由：`status=no_quote`（**不**抛 5xx）。

**公共 AMM**（Uniswap 等）：

- 优先 quoter 的净输出；LP fee 通常已嵌在价格中 → `embedded_in_price=true`，并在 `FeeBreakdown` 中把 **可知的 pool fee tier** 记为信息字段（`lp_fee_tier_bps`），**不**再加进 `explicit_fee_bps`。
- Gas **不**嵌在价格里 → 记入 `gas_usd` / `gas_bps`。

ExactOut 不可用时的近似（允许，但必须标记 `qty_method=quote_exact_in_approx`）：

1. 用 \(N\) 作为 ExactIn quote 买 base，得 `base_out`；
2. \(P^\* = N / base_out`；
3. 实际 base 可能 ≠ \(q^\*\)；在深度较好时误差可接受。M2 单测需覆盖「ExactOut 路径」与「approx 路径」分支。

### 4.5 Spread 公式（单边）

\[
\begin{aligned}
\text{buy:  } & spread\_bps = \frac{P^\* - mid}{mid} \times 10\,000 \\
\text{sell: } & spread\_bps = \frac{mid - P^\*}{mid} \times 10\,000
\end{aligned}
\]

性质：

- 正常流动性下 **\(spread\_bps \ge 0\)**（买贵卖贱）。负值表示优于 mid（rebate、错价、或 mid 源偏差）——**保留符号**，不截断为 0，便于发现 mid 问题。
- 该 `spread_bps` 是 **价差成本**；是否已含 trading fee 由 `fee_breakdown.embedded_in_price` 解释（§5）。

### 4.6 双边汇总

对同一 `(venue, asset, notional_usd, snapshot)`：

| 指标 | 公式 | 用途 |
| --- | --- | --- |
| `buy_spread_bps` / `sell_spread_bps` | §4.5 | 主表可切换 side |
| `round_trip_spread_bps` | `buy + sell` | 「来回一次」价差 |
| `half_spread_bps` | `round_trip / 2` | 与「单边平均」对齐的摘要 |
| `max_side_spread_bps` | `max(buy, sell)` | 最差单边 |

**默认 dashboard 主指标**：`half_spread_bps`（或同时展示 buy/sell 列）。Summary 文案应用 round-trip 或 half 时必须写明用的是哪一个。

任一侧 `insufficient_liquidity` / `no_quote`：

- 汇总字段为 `null`；
- 另一侧单边 Quote 仍可返回。

### 4.7 数值示例（规范测试向量）

**设定**：`mid = 100_000` USD/BTC，`N = 10_000` → \(q^\* = 0.1\) BTC。

**Orderbook asks**（buy）：

| Level | Price | Size (BTC) |
| --- | --- | --- |
| 1 | 100_010 | 0.04 |
| 2 | 100_050 | 0.04 |
| 3 | 100_100 | 0.10 |

Walk 0.1 BTC：`0.04×100010 + 0.04×100050 + 0.02×100100 = 4000.4 + 4002 + 2002 = 10004.4`  
\(P^\* = 10004.4 / 0.1 = 100\_044\)  
\(spread\_bps = (100044 - 100000) / 100000 × 10000 = 4.4\)

**若 taker fee = 10 bps 且价未含 fee**：`explicit_fee_bps = 10`，`total_cost_bps = 4.4 + 10 = 14.4`（gas=0）。

**若 Prop AMM 净价** \(P^\* = 100\_044\) 且 fee 已嵌：`spread_bps = 4.4`，`embedded_in_price=true`，`explicit_fee_bps=0`，`total_cost_bps=4.4`（+ gas_bps）。

CEX adapter 单测（WHI-802）应固定上述 book fixture，断言 `spread_bps == 4.4`。

---

## 5. 费用与 Total cost of execution

### 5.1 费用组件

| 组件 | 适用 | 计入默认 `total_cost_bps`？ | 说明 |
| --- | --- | --- | --- |
| Trading fee（taker/maker） | CEX / Perp DEX | ✅ 作为 `explicit_fee_bps` | Phase 1 默认 **taker** 档；VIP 档由配置选择 |
| LP / pool fee | AMM | ❌ 若已嵌价格；仅信息字段 | 见 `lp_fee_tier_bps` |
| Embedded AMM/prop fee | Prop AMM / 部分 AMM | ❌ 不再加项 | 已在 \(P^\*\) 内 |
| Platform / aggregator fee | Jupiter 等 | ✅ 若非 0 | Phase 1 Metis 默认 0（WHI-797） |
| Gas | 链上 venue | ✅ `gas_bps` | `gas_usd / N × 10_000` |
| Funding | Perp | ❌ 默认 | 见 §5.3 |
| Deposit/withdraw / bridge | 跨所进出金 | ❌ Phase 1 | 非目标 |

### 5.2 公式

```text
gas_bps            = (gas_usd / notional_usd) * 10_000     # gas_usd 缺失则 0
explicit_fee_bps   = trading_fee_bps + platform_fee_bps    # 仅非内嵌部分
                     # 若 fee 以 USD 给出：fee_usd / notional_usd * 10_000

if embedded_in_price:
    # spread 已含交易 fee；禁止再加 trading_fee_bps
    total_cost_bps = spread_bps + gas_bps + platform_fee_bps
else:
    total_cost_bps = spread_bps + explicit_fee_bps + gas_bps
```

`platform_fee_bps` 在 Jupiter 默认路径为 0；若用户启用平台费，**即使** `embedded_in_price` 也要加（平台费通常不在 pool 曲线内，WHI-797：未设时 `platformFee=null`）。

### 5.3 Funding 政策（明确）

| 场景 | 处理 |
| --- | --- |
| 即时执行质量对比（dashboard 主表、`/quotes`） | **忽略 funding** |
| 费用页信息展示 | 展示 `funding_rate_8h` / 年化，**不**加进主排序 |
| 可选「持有 \(T\) 小时的成本」 | `funding_cost_bps ≈ funding_rate_8h × (T/8) × 10_000`（方向：多付正 funding 为成本）—— **独立字段** `total_cost_with_funding_bps`，默认 API 可省略 |

理由：funding 是 **持仓时间** 的函数，与「市价吃 \(N\) 美元」的瞬时执行质量不同维；混进主指标会让「谁 spread 更低」变成「谁 funding 碰巧为负」。

### 5.4 `FeeBreakdown`（每笔 Quote 内嵌）

```text
FeeBreakdown {
  embedded_in_price:   bool
  fee_tier:            str | null          # e.g. "default_taker" | "vip0" | "pool_0.05%"
  trading_fee_bps:     Decimal | null      # 显式费率；内嵌时可为 null
  trading_fee_usd:     Decimal | null
  platform_fee_bps:    Decimal | null      # 默认 0
  lp_fee_tier_bps:     Decimal | null      # 信息：池费档，不自动计入 total
  gas_usd:             Decimal | null
  gas_bps:             Decimal | null
  funding_rate_8h:     Decimal | null      # 小数或 bps 须在字段注释统一：用「小数」e.g. 0.0001 = 1 bps per 8h
  explicit_fee_bps:    Decimal             # 参与 total 的显式费（见 §5.2）
  notes:               str | null
}
```

### 5.5 `FeeSchedule`（venue 级 / 资产级费率表，WHI-812 填充）

```text
FeeSchedule {
  venue:               str
  asset:               str | null          # null = venue 默认
  instrument_type:     "spot" | "perp" | "amm_pool" | "prop_amm"
  maker_bps:           Decimal | null
  taker_bps:           Decimal | null
  tiers:               list[FeeTier] | null
  default_tier:        str                 # Phase 1: "default_taker"
  lp_fee_tiers_bps:    list[Decimal] | null
  gas_estimate_usd:    Decimal | null      # 静态缺省；实时以 Quote.fee_breakdown.gas_usd 为准
  funding_model:       "none" | "perp_8h" | "perp_continuous"
  fee_embedded_in_quote: bool              # Prop AMM / 多数 AMM = true
  source_urls:         list[str]           # 官方费率页（WHI-812 验收）
  updated_at:          datetime
}

FeeTier {
  name:                str
  maker_bps:           Decimal
  taker_bps:           Decimal
  volume_requirement:  str | null
}
```

静态档进配置文件；动态 gas/funding 由 adapter 实时写入 `FeeBreakdown`。

---

## 6. 统一数据模型

### 6.1 `Quote`（核心）

Issue 要求字段 + M2 必需扩展：

```text
Quote {
  # --- identity ---
  venue:              str                 # 稳定 slug：binance | bybit | hyperliquid | lighter | apex
                                          # | uniswap_eth | aerodrome_base | pancakeswap_bsc
                                          # | humidifi | tesserav | bisonfi
  asset:              str                 # 规范资产 ID
  venue_symbol:       str | null          # 本地符号 / mint / market id
  instrument_type:    "spot" | "perp" | "amm_pool" | "prop_amm"
  side:               "buy" | "sell"
  notional_usd:       Decimal             # 1000 | 10000 | 100000 | 1000000

  # --- mid & price ---
  mid:                Decimal             # = ReferenceMid.mid（同快照）
  mid_source:         str
  effective_price:    Decimal | null      # quote per base；失败时 null
  spread_bps:         Decimal | null

  # --- fees & total ---
  fee_breakdown:      FeeBreakdown
  total_cost_bps:     Decimal | null

  # --- book-keeping ---
  timestamp:          datetime            # 该 venue 报价时刻 UTC
  status:             QuoteStatus
  qty_base:           Decimal | null      # 实际用于定价的 base 数量（目标为 N/mid）
  qty_method:         "base_from_mid" | "quote_exact_in_approx" | null
  venue_mark:         Decimal | null      # perp mark；可选
  basis_bps:          Decimal | null
  raw_ref:            str | null          # 可选：上游请求 id / 样本路径，便于调试

  # --- errors ---
  error_code:         str | null
  error_message:      str | null
}

QuoteStatus =
  | "ok"
  | "no_quote"                 # 无市场 / 无路由
  | "insufficient_liquidity"   # 深度不够 N
  | "unsupported_asset"        # venue 不支持该 asset
  | "error"                    # 上游失败等
```

**不变量（实现与测试必须遵守）**：

1. `status == "ok"` ⇒ `effective_price`、`spread_bps`、`total_cost_bps`、`qty_base` 均非 null。
2. `status != "ok"` ⇒ 上述价格字段为 null；`fee_breakdown` 仍可部分填充。
3. `mid` / `mid_source` 即使失败也应尽量带上（便于 UI 显示「相对何价」）；若 mid 服务整体失败，聚合层失败，不返回残缺可比集。
4. `spread_bps` 与 `total_cost_bps` 的计算 **只** 使用本文公式；adapter 不得自定义 bps 定义。

### 6.2 `TopOfBook`

```text
TopOfBook {
  venue:              str
  asset:              str
  best_bid:           Decimal
  best_ask:           Decimal
  bid_size:           Decimal | null      # base 数量
  ask_size:           Decimal | null
  mid_local:          Decimal             # (bid+ask)/2
  mid_ref:            Decimal             # reference mid
  spread_bps:         Decimal             # (ask - bid) / mid_ref * 10_000
  spread_bps_local:   Decimal             # (ask - bid) / mid_local * 10_000
  timestamp:          datetime
  status:             "ok" | "no_book" | "unsupported" | "error"
}
```

- **仅 orderbook venue** 实现 `get_orderbook_spread`；AMM / Prop AMM 返回 `null`（不是假 TOB）。
- 主对比表展示 `spread_bps`（相对 `mid_ref`）；`spread_bps_local` 供微观结构调试。

### 6.3 双边汇总视图（API 可合成，非 adapter 必返回）

```text
SizeQuotePair {
  venue: str
  asset: str
  notional_usd: Decimal
  buy:  Quote | null
  sell: Quote | null
  round_trip_spread_bps: Decimal | null
  half_spread_bps:       Decimal | null
  round_trip_total_cost_bps: Decimal | null   # buy.total + sell.total（两侧皆 ok）
  top_of_book: TopOfBook | null
}
```

### 6.4 Venue slug 注册表（稳定，禁止别名漂移）

| slug | Class |
| --- | --- |
| `binance` | CEX |
| `bybit` | CEX |
| `hyperliquid` | Perp DEX |
| `lighter` | Perp DEX |
| `apex` | Perp DEX |
| `uniswap_eth` | AMM |
| `aerodrome_base` | AMM |
| `pancakeswap_bsc` | AMM |
| `humidifi` | Prop AMM |
| `tesserav` | Prop AMM |
| `bisonfi` | Prop AMM |

新增 venue 必须改本表（或后续 ADR），adapter registry 的 key 与此一致。

### 6.5 错误与降级语义

| 情况 | status | HTTP 聚合（WHI-807） |
| --- | --- | --- |
| 无 pair / 无路由 | `no_quote` | 200，该行 N/A |
| 深度 < \(q^\*\) | `insufficient_liquidity` | 200，该 size N/A |
| 资产不在 venue | `unsupported_asset` | 200 |
| 超时 / 5xx / 解析失败 | `error` | 200 + 该 venue 错误；**不**导致整包失败 |
| mid 不可用 | — | **整包 503 或 422**（无 mid 则所有 spread 无意义） |

---

## 7. Adapter 抽象（WHI-801 直接输入）

```text
class VenueAdapter(Protocol):
    venue: str                          # §6.4 slug
    venue_class: Literal["cex","perp_dex","amm_dex","prop_amm"]

    def get_quote(
        self,
        asset: str,
        side: Literal["buy","sell"],
        notional_usd: Decimal,
        *,
        mid: ReferenceMid,
        fee_tier: str | None = None,    # 默认 schedule.default_tier
    ) -> Quote: ...

    def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
    ) -> TopOfBook | None:
        """Orderbook venues: TopOfBook. AMM/Prop: None."""
        ...

    def get_fees(self, asset: str | None = None) -> FeeSchedule: ...

    def supported_assets(self) -> list[str]: ...
```

**职责切分**：

| 层 | 职责 |
| --- | --- |
| Adapter | 拉深度/报价；walk 或 quoter；填 `effective_price`、本地 fee/gas；算 `spread_bps` / `total_cost_bps`（公式固定） |
| Mid service（WHI-807） | 解析 `ReferenceMid`，同一快照共用 |
| Aggregator | 并发调用、超时、缓存；拼 `SizeQuotePair`；**不**改 bps 定义 |
| Fee config（WHI-812） | 静态 `FeeSchedule`；adapter 读取 |

**并发契约（给 WHI-807）**：单 venue 超时建议 ≤ 2s；整体 ≤ 3s；结果可含混合 status。

---

## 8. 按 venue class 的实现备忘

| Class | `get_quote` | TOB | Fee 要点 |
| --- | --- | --- | --- |
| CEX | L2 walk \(q^\*\) | ✅ | 默认 taker；`embedded_in_price=false` |
| Perp DEX | L2 walk；注意 lot/tick | ✅ | 同上 + `funding_rate_8h` 信息字段；`venue_mark` 可选 |
| AMM DEX | Quoter；gas 估算 | `None` | 价内嵌 LP fee；+ `gas_bps` |
| Prop AMM | Jupiter `dexes=<Label>` 净 `outAmount` | `None` | `embedded_in_price=true`；platform 0；无路由 → `no_quote` |

---

## 9. 展示与排序约定（前端 / summary）

1. 主表：venue × size，单元格默认 **`half_spread_bps`** 或 **`total_cost_bps`（buy）**——产品可切换；切换控件必须标注指标名。
2. 排序「最优」：`total_cost_bps` 升序（仅 `status=ok`）；N/A 沉底。
3. bps 展示：保留 2 位小数（`4.40 bps`）；导出/API 保留 4 位。
4. 时间：UI 显示 quote 与 mid 的时间戳；相差 >5s 显示 stale 提示。
5. Stocks 闭市：链上/ perps 仍可能有价——标注 session（WHI-810），**不**改公式。

---

## 10. 验收标准（本 issue）

- [x] 定义 effective spread at size（四档、买/卖、双边汇总）
- [x] 定义 top-of-book（仅 orderbook）
- [x] 定义 reference mid 优先级与 spot/perp/funding 政策
- [x] 定义 total cost 与 **反双计** 规则
- [x] 给出 `Quote` / `TopOfBook` / `FeeBreakdown` / `FeeSchedule` / `ReferenceMid` 字段级模型
- [x] 给出 adapter Protocol，可供 WHI-801 直接编码
- [x] 含可复制的数值测试向量（§4.7）

WHI-801 验收时应：Pydantic 模型字段 ⊆ 本文命名；mock adapter 对 §4.7 fixture 得到 `spread_bps=4.4`。

---

## 11. 开放问题（不阻塞 M2；需产品拍板时再 ADR）

| ID | 问题 | 临时默认 |
| --- | --- | --- |
| Q1 | Stocks 无稳健 index 时是否强制 Pyth equity feed | 用 proxy mark 中位数并标注 |
| Q2 | 主表默认列是 half-spread 还是 total cost (buy) | **total cost (buy)** 更贴近「买入成本」；文档/UI 可切换 |
| Q3 | VIP 费率是否进 Phase 1 主路径 | 仅 `default_taker`；VIP 配置预留 |
| Q4 | Gas 用即时 gas price 还是分位估计 | 即时 + 保守 L2 gas limit；WHI-804/812 细化 |

---

## 12. 修订记录

| 日期 | 变更 |
| --- | --- |
| 2026-08-03 | 初版：口径 + 模型 + adapter 契约（WHI-799） |
