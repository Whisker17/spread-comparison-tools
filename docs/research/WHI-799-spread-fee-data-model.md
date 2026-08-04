# WHI-799：Spread & 费用统计口径 + 统一数据模型

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-799](https://linear.app/whisker-personal/issue/WHI-799) |
| Milestone | M1 调研与口径定义 |
| Blocks | [WHI-801](https://linear.app/whisker-personal/issue/WHI-801)（FastAPI + adapter 接口）、[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)（费用数据整理） |
| Downstream | WHI-802…806（各 venue adapter）、WHI-807（`/quotes` + reference mid 服务）、WHI-813…815（fees / simulate） |
| 规范日期 | 2026-08-03（UTC；v2 同日对齐 WHI-797/798 v2 多链与 stocks 结论） |
| 性质 | **规范（spec）**，非 live 探测；字段名与公式以本文为准，M2 代码不得另立口径 |

> **v2 变更**（因 WHI-797/798 重做而来，公式与模型字段**均不变**）：
> 1. Prop AMM 不再是 Solana 单链 class：Tessera 部署于 Solana + **Base + BSC**（BSC 是其最大链）。venue slug 引入**链维度**：`tessera` 拆为 `tessera_solana` / `tessera_base` / `tessera_bsc`（§6.5）；EVM 侧报价路径为 KyberSwap `includedSources=tessera`（§4.4）。
> 2. Stocks 新增 **bStocks 三方对比**（Binance spot × PancakeSwap × Tessera BSC，同一 BSC 资产）为 P0-A（WHI-798 v2）——tokenized stock 的 reference mid 策略相应分化（§3.3）：有 CEX 现货盘的 tokenized 资产用**该资产自身**的 spot TOB，不再一律借 underlying equity 参考价。

## 1. 结论摘要（TL;DR）

1. **名义金额（notional）**固定五档：`$100` / `$1_000` / `$10_000` / `$100_000` / `$1_000_000`（USD）。先用 **reference mid** 换算目标 base 数量，再 walk book / 调 quoter。
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
   - 若 `gas_unknown`：`total_cost_bps = null`（禁止当 0 排序）
   - 否则：`total_cost_bps = spread_bps + trading_component_bps + platform_fee_bps + gas_bps`
   - `explicit_fee_bps` = `trading_component_bps + platform_fee_bps + gas_bps`（仅 total 非 null 时定义）
6. **统一模型**：`Quote`、`TopOfBook`、`FeeBreakdown`、`FeeSchedule`、`ReferenceMid`；均携带 `snapshot_id`；CEX 经 `instrument_type` 区分 spot/perp；adapter 抽象见 §7。

---

## 2. 范围与术语

### 2.1 Venue classes（与 [WHI-798](./WHI-798-asset-category-inventory.md) 对齐）

| Class | Venues（Phase 1） | 报价机制 |
| --- | --- | --- |
| CEX | Binance, Bybit | Orderbook walk |
| Perp DEX | Hyperliquid, Lighter, ApeX | Orderbook walk |
| AMM DEX | Uniswap (ETH), Aerodrome (Base), PancakeSwap (BSC) | Quoter / router |
| Prop AMM | HumidiFi（Solana）、BisonFi（Solana）、**Tessera（Solana / Base / BSC 三链，BSC 量最大）**（见 [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md) v2） | 净输出报价（fee 内嵌）：Solana 经 Jupiter `dexes=<Label>`；Base/BSC 经 KyberSwap `includedSources=tessera` |

Venue **显示名**用 Tessera；**slug 带链维度**：`tessera_solana` / `tessera_base` / `tessera_bsc`（§6.5）。venue 过滤参数按链取值：Solana = Jupiter `dexes=TesseraV`（精确大小写），Base/BSC = KyberSwap `includedSources=tessera`（全小写）——两者都**不等于** slug，映射只写在 §6.5 注册表。

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
| **P3** | `pyth` | Pyth Hermes/price feed 的 **`price` 字段**（已按 `expo` 缩放后的实数价）。**不要**用 conf 区间中点。Feed id 列表放 `config/`（WHI-807）。 | CEX 均失败；或 `config` 键 `mid.force_pyth = true` |

**配置键（非密钥，进 `config/` 类型化配置，不进 `.env`）**：

文件建议：`config/mid.yaml`（WHI-807 落地时配合 pydantic settings）。下列默认值 **unvalidated（pending `docs/DESIGN.md` §2）**，仅作工程起点：

| 键 | 默认 | 含义 |
| --- | --- | --- |
| `mid.force_pyth` | `false` | 强制 P3 |
| `mid.stale_threshold_sec` | `5` | `mid_stale` 判定：`abs(quote.timestamp - mid_timestamp)` 秒 |
| `mid.cache_max_age_sec` | `30` | mid **服务内部**缓存最大年龄；超过则重拉或失败。与 `stale_threshold_sec` 独立 |

Staleness 语义：

- `ReferenceMid.timestamp` = mid 观测 UTC。
- 每个 Quote 复制 `mid_timestamp`；`mid_stale = abs(quote.timestamp - mid_timestamp) > mid.stale_threshold_sec`。
- **`mid_stale=true` 仍允许 `status=ok`**：报价有效，仅提示 mid 与 quote 时钟偏差；UI 展示警告，**不**改 bps 公式。
- mid 服务整体失败 → 聚合 **不**返回残缺可比集（503/422）。

### 3.3 Stocks / Others

| 资产类 | `mid_source` | mid 策略 |
| --- | --- | --- |
| Equity perps | `cex_tradfi_index` 或 `proxy_perp_mark_median` | 优先 CEX TradFi index；否则取 **Binance + Bybit + Hyperliquid + Lighter + ApeX** 中该标的可用 mark 的中位数。偶数个样本：取中间两档的算术平均。弱于 crypto P0，UI 须标注 |
| **Tokenized spot，有 CEX 现货盘**（bStocks `QQQB` 等 → Binance；xStocks `TSLAX` 等 → Bybit）(v2) | `binance_spot_tob` / `bybit_spot_tob` | 用**该 tokenized 资产自身**在其最深 CEX 现货盘的 bookTicker mid（如 `QQQBUSDT`）。跨 venue 比较（Binance spot × Pancake × Tessera BSC，P0-A）衡量的是**同一资产**的执行偏离——借 underlying equity 参考价会把 wrapper 溢价/折价算进 spread |
| Tokenized spot，无任何 CEX 现货盘 | `equity_ref_same_as_perp` | 回退用对应 equity 的上表参考价；**禁止**单池 mid 当跨 venue reference |
| Others | 同 §3.2 枚举 | 无 index 时 P1/P2 spot TOB |

**Tokenized 资产的两条补充口径（v2）**：

1. **资产 ID 语义**：`asset` 用 tokenized token 自身 ID（`QQQB` ≠ `QQQ`，`TSLAx` ≠ `TSLA` ≠ `TSLAB`）。不同发行方的同 underlying 是**不同 asset**，各自有 mid；「跨发行方基差」（NVDAB vs NVDAx vs NVDAon）与「tokenized vs underlying 基差」都走 `basis_bps` 一类的展示指标，**不**混进 `spread_bps`。
2. **Rebase 警示**：bStocks 用 rebase 处理分红/拆股（WHI-798 v2 Q14）。rebase 生效时刻前后 mid 与各 venue 报价可能出现同步跳变；同一 `snapshot_id` 内自洽即可，但**跨快照的历史对比**（WHI-817）须按 rebase 事件分段，公司行动日的异常 spread 不入统计（实现属 WHI-816/817，此处只定口径）。

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
NOTIONAL_TIERS_USD = [100, 1_000, 10_000, 100_000, 1_000_000]
```

- API 允许子集；collector（WHI-816）必须五档都采。
- `notional_usd` 与档位用 Decimal 精确相等比较。
- `$100` is the retail-sized floor (WHI-838). At this size `gas_bps = gas_usd / notional_usd * 10_000` (§5.2) often dominates AMM total cost (e.g. $3 L1 gas → 300 bps); that is intended signal, not a formula bug. Dashboard heat colouring is **per-column** so the $100 column does not flatten resolution of larger tiers.

### 4.2 数量换算（所有 venue 统一）

```text
q_star = notional_usd / mid
```

- **只用** reference mid 换算；禁止 venue-local mid。
- 深度不足以成交 `q_star` → `status=insufficient_liquidity`，价格字段 null（§6.6）。

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

**Prop AMM — Solana / Jupiter**（[WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md) §3–§6）：

- 用 `outAmount`（已扣 AMM fee；`platformFee` 保持 0）。
- `embedded_in_price = true`。
- 无路由（400 `NO_ROUTES_FOUND`）：`status=no_quote`（不抛 5xx）。

**Prop AMM — Base / BSC / KyberSwap**（WHI-797 v2 §7；v2 新增）：

- `GET /{base|bsc}/api/v1/routes` + `includedSources=tessera`；用 `routeSummary.amountOut`（净输出）。
- `embedded_in_price = true`；同 venue 多跳（全 hop `exchange=tessera`）视为该 venue 报价，与 Jupiter 侧口径一致。
- **gas 与 Solana 侧不同**：响应自带 `gas` / `gasUsd` → `gas_usd` 直接取用，`gas_unknown=false`（Solana prop AMM 约定 `gas_bps=0`，见 §8）。
- 错误映射（body `code`，HTTP 均 200）：`4008 route not found` → `no_quote`；`4000 bad request` 且 token 不在该 source 注册集 → `unsupported_asset`；`40011 filtered liquidity sources` = source id 写错或该链无此 venue → **配置错误，fail-fast**（等价于 Jupiter 侧 label 拼错，不当业务空结果吞掉）。
- 生产带 `x-client-id` header；限速语义见 WHI-797 §7.2。

**公共 AMM**：

- 净输出 → `embedded_in_price=true`；池费档写入 `lp_fee_tier_bps`（**信息字段**，不进 `trading_component_bps`）。
- Gas **不**在价内 → `gas_usd` / `gas_bps`；若无法估算 → `gas_usd=null` 且 `gas_unknown=true`（§5.2）。

ExactOut 不可用时允许 approx，且必须 `qty_method=quote_exact_in_approx`；此时 `qty_base` 记 **实际成交 base**，`notional_usd` 仍为请求档位 N（gas_bps 分母用请求 N，与档位对齐）。

### 4.5 Spread 公式（单边）— 唯一权威

```text
buy:  spread_bps = (P_star - mid) / mid * 10_000
sell: spread_bps = (mid - P_star) / mid * 10_000
```

- 正常流动性下 ≥ 0；负值保留（优于 mid / mid 偏差），**不**截断为 0。
- **谁计算（唯一）**：**adapter** 在收到 `mid` 后计算 `spread_bps` 与 `total_cost_bps`（§5.2）。聚合层 **不得**重算或改 bps；只做并发/拼接/缓存。

### 4.6 双边汇总

对同一 `(snapshot_id, venue, asset, instrument_type, notional_usd)`（**必须含 `instrument_type`**，避免 CEX spot 与 perp 被拼进同一 round-trip）：

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

**Sell 向量**（与 ask 关于 mid 对称的 bids：`99_990 / 99_950 / 99_900`，size `0.04 / 0.04 / 0.10`，walk 0.1）：

`0.04*99990 + 0.04*99950 + 0.02*99900 = 3999.6 + 3998.0 + 1998.0 = 9995.6`  
`P_star = 9995.6 / 0.1 = 99_956`  
`spread_bps = (100000 - 99956) / 100000 * 10000 = 4.4`

**gas_unknown 向量**：AMM `spread_bps=4.4`、`embedded_in_price=true`、`gas_unknown=true` → `total_cost_bps is null`，`explicit_fee_bps is null`。

WHI-802 单测应固定 buy book fixture，断言 `spread_bps == 4.4`；WHI-804 覆盖 `gas_unknown`。

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

# 3) platform（即使 embedded 也加——平台费不在 pool 曲线内；字段非 null，默认 0）
# platform_fee_bps: Decimal  # 已是 0 或正数

# 4) 汇总
if gas_unknown:
    total_cost_bps = null                     # 禁止把未知 gas 当 0 去排序
    fee_breakdown.explicit_fee_bps = null
else:
    # gas_bps 此处已是 Decimal（CEX/perp 为 0，链上为估算值）
    explicit_fee_bps = trading_component_bps + platform_fee_bps + gas_bps
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
  venue:                 str               # §6.5 slug
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

（`TopOfBook` 不复用该枚举——orderbook 适配器用返回值 `None` 表示「本 venue 无 TOB 概念」，见 §6.3 / §7。）

### 6.2 `Quote`

```text
Quote {
  # --- identity ---
  snapshot_id:        str
  venue:              str                 # §6.5 slug
  asset:              str
  venue_symbol:       str | null
  instrument_type:    "spot" | "perp" | "amm_pool" | "prop_amm"
  side:               "buy" | "sell"
  notional_usd:       Decimal

  # --- mid & price ---
  mid:                Decimal
  mid_source:         str
  mid_timestamp:      datetime
  mid_stale:          bool                # 不强制 status!=ok
  effective_price:    Decimal | null
  spread_bps:         Decimal | null

  # --- fees & total ---
  fee_breakdown:      FeeBreakdown
  total_cost_bps:     Decimal | null      # gas_unknown 或 status!=ok 时 null

  # --- book-keeping ---
  timestamp:          datetime            # venue 报价时刻 UTC
  status:             QuoteStatus
  qty_base:           Decimal | null      # 实际用于定价的 base；approx 时为实际成交量
  qty_method:         "base_from_mid" | "quote_exact_in_approx" | null
  venue_mark:         Decimal | null
  basis_bps:          Decimal | null
  raw_ref:            str | null          # 可选调试句柄：上游 request id 或 samples 相对路径

  error_code:         str | null
  error_message:      str | null
}
```

**不变量**：

1. 若 `status == "ok"`：则 `effective_price`、`spread_bps`、`qty_base` 均非 null；**并且**  
   - 若 `fee_breakdown.gas_unknown` 为 true，则 `total_cost_bps is null`；  
   - 若 `fee_breakdown.gas_unknown` 为 false，则 `total_cost_bps` 非 null。  
   （两条合取，不是析取。）
2. 若 `status != "ok"`：则 `effective_price`、`spread_bps`、`total_cost_bps`、`qty_base`、以及 `fee_breakdown.explicit_fee_bps` 均为 null。
3. `snapshot_id` / `mid` / `mid_source` / `mid_timestamp` 在同快照同资产上全 venue 一致。
4. bps 公式 **仅** §4.5 / §5.2。
5. `mid_stale` 与 `status` 独立：`mid_stale=true` 仍可 `status=ok`。

### 6.3 `TopOfBook`

仅 orderbook venue 在 **成功拉簿** 时返回该对象；AMM / Prop **始终**返回 `None`（「无 TOB 概念」）。

```text
TopOfBook {
  snapshot_id:        str
  venue:              str
  asset:              str
  instrument_type:    "spot" | "perp"
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

**失败契约（唯一）**：

| 情况 | 行为 |
| --- | --- |
| Venue 无 orderbook 概念（AMM / Prop） | 返回 `None` |
| Orderbook venue 拉簿失败 / 超时 / 解析失败 | **抛异常**（或 adapter 定义的 `AdapterError`）；聚合层记该 venue error。**禁止**用 `None` 表示失败（`None` 已被「无 TOB 概念」占用） |
| 成功 | 返回完整 `TopOfBook`（size 可为 null） |

主对比用 `spread_bps`（相对 `mid_ref`）。

### 6.4 双边汇总视图（聚合层可合成）

```text
SizeQuotePair {
  snapshot_id:               str
  venue:                     str
  asset:                     str
  instrument_type:           "spot" | "perp" | "amm_pool" | "prop_amm"
  notional_usd:              Decimal
  buy:                       Quote | null
  sell:                      Quote | null
  round_trip_spread_bps:     Decimal | null
  half_spread_bps:           Decimal | null
  round_trip_total_cost_bps: Decimal | null
  top_of_book:               TopOfBook | null  # 若有，instrument_type 必须与 pair 一致
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
| `humidifi` | HumidiFi | Prop AMM | Solana-only；Jupiter `dexes=HumidiFi` |
| `tessera_solana` | Tessera (Solana) | Prop AMM | Jupiter `dexes=TesseraV`（label ≠ slug） |
| `tessera_base` | Tessera (Base) | Prop AMM | KyberSwap `includedSources=tessera`，chain slug `base`（v2） |
| `tessera_bsc` | Tessera (BSC) | Prop AMM | KyberSwap `includedSources=tessera`，chain slug `bsc`（v2）；量最大 |
| `bisonfi` | BisonFi | Prop AMM | Solana-only；Jupiter `dexes=BisonFi` |

**v2 说明**：Tessera 一家 = 三个 venue 实例（同一 MM、三条链、两套报价源），与 AMM 侧 `uniswap_eth` / `aerodrome_base` 的链后缀风格一致；`humidifi` / `bisonfi` 已确认 Solana-only，不加后缀。本表**取代** WHI-797 §8 示例中的 `tesserav@solana` 一类写法——slug 以此处为准。旧 slug `tessera`（v1）作废，禁止别名并存。

### 6.6 错误与降级语义

| 情况 | Quote.status | 聚合 |
| --- | --- | --- |
| 无 pair / 无路由 | `no_quote` | 200，该行 N/A |
| 深度 < `q_star` | `insufficient_liquidity` | 200 |
| 资产不支持 | `unsupported_asset` | 200 |
| 超时 / 上游失败 | `error` | 200 + 该 venue 错误；不整包失败 |
| mid 不可用 | — | 整包 503/422 |

#### 6.6.1 Venue minimums at the $100 tier (WHI-838)

$100 sits near some venue min-order floors. **No new `QuoteStatus` value** — map honestly onto the table above:

| Venue class | Expected at $100 | Status if venue refuses |
| --- | --- | --- |
| CEX spot/perp (`binance`, `bybit`) | Blue-chip min notional typically ≪ $100; continuous `walk_book` on L2. If depth < `q_star` (rare at this size) | `insufficient_liquidity` |
| Perp DEX (`hyperliquid`, `lighter`, `apex`) | Min notional often ~$10; $100 generally quotable. Thin books / size filters → walk fails | `insufficient_liquidity` (or `no_quote` if market absent) |
| AMM DEX (`uniswap_eth`, `aerodrome_base`, `pancakeswap_bsc`) | Quoter returns a price; gas dominates cost (intended). Pool missing / amount too small for pool | `no_quote` |
| Prop AMM Solana (Jupiter) / EVM (KyberSwap) | Route-based; may return no route for illiquid wrappers or amount edge cases | `no_quote` |

Adapters must **not** invent a synthetic fill for a size the venue would reject.

---

## 7. Adapter 抽象（WHI-801 直接输入）

```text
InstrumentType = Literal["spot", "perp", "amm_pool", "prop_amm"]

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
        instrument_type: InstrumentType | None = None,
        # None → 默认：cex→spot, perp_dex→perp, amm_dex→amm_pool, prop_amm→prop_amm
        fee_tier: str | None = None,
    ) -> Quote: ...

    def get_orderbook_spread(
        self,
        asset: str,
        *,
        mid: ReferenceMid,
        instrument_type: Literal["spot", "perp"] | None = None,
    ) -> TopOfBook | None:
        """AMM/Prop: always None.
        CEX/Perp: TopOfBook on success; raise AdapterError on fetch failure.
        """
        ...

    def get_fees(
        self,
        asset: str | None = None,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> FeeSchedule: ...

    def supported_assets(
        self,
        *,
        instrument_type: InstrumentType | None = None,
    ) -> list[str]: ...
```

**CEX spot vs perp（WHI-799 要求可比性处理）**：同一 slug `binance` / `bybit` 通过 **`instrument_type`** 区分盘口与费率，**不**拆成两个 slug。调用方要 perp 时必须显式 `instrument_type="perp"`；默认 spot 以免误用合约深度。`get_fees(asset, instrument_type="perp")` 返回合约 taker/maker，与 spot 表分离。

| 层 | 职责 |
| --- | --- |
| Adapter | 深度/报价；walk 或 quoter；填 `effective_price`、fee/gas；**独自**按 §4.5/§5.2 算 bps |
| Mid service | 解析 `ReferenceMid`（含 `snapshot_id`） |
| Aggregator | 并发、超时、缓存；拼 `SizeQuotePair`；**不**重算 bps |
| Fee config | 静态 `FeeSchedule`（按 venue × instrument_type） |

---

## 8. 按 venue class 的实现备忘

| Class | `get_quote` | `get_orderbook_spread` | Fee |
| --- | --- | --- | --- |
| CEX | L2 walk `q_star`；`instrument_type` spot\|perp | 成功→`TopOfBook`；失败→raise | 默认 taker（按 instrument）；`embedded_in_price=false`；`gas_bps=0` |
| Perp DEX | L2 walk；lot/tick；默认 `perp` | 成功→`TopOfBook`；失败→raise | 同上 + `funding_rate_8h`；可选 `venue_mark` |
| AMM DEX | Quoter + gas | `None` | 价内嵌 LP；gas 可知则填，否则 `gas_unknown=true` |
| Prop AMM（Solana：`humidifi` / `tessera_solana` / `bisonfi`） | Jupiter `dexes=<Label>` 净输出 | `None` | `embedded_in_price=true`；platform 0；`gas_bps=0`（Solana 交易费对五档名义均 <0.1 bps，约定忽略）；无路由 → `no_quote` |
| Prop AMM（EVM：`tessera_base` / `tessera_bsc`，v2） | KyberSwap `includedSources=tessera` 净输出（§4.4） | `None` | `embedded_in_price=true`；platform 0；**gas 用响应 `gasUsd`**（`gas_unknown=false`）；4008→`no_quote`，4000（token 不在集）→`unsupported_asset`，40011→fail-fast |

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

- [x] Effective spread at size（五档、买/卖、双边汇总）
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
| Q1 | Stocks 是否强制外部 equity feed | proxy mark 中位数 + 标注（equity perps 路径；tokenized 现货已改用自身 CEX TOB，§3.3 v2） |
| Q2 | 产品主列默认 half-spread 还是 total cost (buy) | 建议 total cost (buy)；UI 可切换 |
| Q3 | VIP 是否进 Phase 1 主路径 | 仅 `default_taker` |
| Q4 | Gas 用即时价还是分位 | 即时 + 保守 gas limit（WHI-804/812）；EVM prop AMM 直接用 KyberSwap `gasUsd` |
| Q5（v2） | bStocks rebase 事件日的历史统计分段与异常剔除的具体实现 | §3.3 已定口径（rebase 日不入窗口统计）；实现细节归 WHI-816/817 |
| Q6（v2） | KyberSwap 报价对 Tessera BSC「实际成交价」的代表性（~95% 成交经 Binance Wallet 闭环路由，不经 Kyber） | Phase 1 接受 Kyber 报价为该 venue 公开可得价；M2 后可用 `TesseraTrade` 事件对账（WHI-797 §7.1 / WHI-798 Q16） |

---

---

## 12. 参考与复用来源

- [WHI-797 Prop AMM 多链报价](./WHI-797-prop-amm-jupiter-quote-api.md) — Solana：`dexes` label、`outAmount` 语义；**v2** Base/BSC：KyberSwap `includedSources`、`routeSummary.amountOut` / `gasUsd`、4008/4000/40011 错误语义（§7）
- [WHI-798 资产清单](./WHI-798-asset-category-inventory.md) — venue class、包装资产、乘数；**v2** bStocks 三方 P0-A、tokenized 资产多发行方表示
- Binance USDT-M premium index：`GET /fapi/v1/premiumIndex`
- Binance spot bookTicker：`GET /api/v3/ticker/bookTicker`
- Linear [WHI-799](https://linear.app/whisker-personal/issue/WHI-799)、[WHI-801](https://linear.app/whisker-personal/issue/WHI-801)、[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)

---

## 13. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-799-spread-fee-data-model.md` | 本文（M2 口径与模型 SSOT） |
| `README.md` | Research 表增加本 issue 链接 |

---

## 14. 修订记录

| 日期 | 变更 |
| --- | --- |
| 2026-08-03 | 初版 |
| 2026-08-03 | Review round 1：统一 total/explicit 公式；`snapshot_id`/`mid_stale`/`gas_unknown`；可调用 mid 端点；Tessera slug；去掉 LaTeX；TOB 仅 `None` 双轨消除；funding 带 side |
| 2026-08-03 | Review round 2：`instrument_type` 进 adapter；bps 仅 adapter 计算；TOB 失败抛错；修不变量合取；mid 配置键与 stale 语义；增 sell/gas_unknown 向量；修正 § 交叉引用 |
| 2026-08-03 | Review round 3：修正 sell 测试向量盘口；`SizeQuotePair`/双边 key 含 `instrument_type`；非 ok 时 `explicit_fee_bps=null`；`config/mid.yaml` 标注 unvalidated |
| 2026-08-03 | **v2 对齐 WHI-797/798 重做**：slug 拆 `tessera_solana/base/bsc`（作废 `tessera`）；§4.4/§8 增 KyberSwap 报价与错误映射（EVM gas 用 `gasUsd`）；§3.3 tokenized 现货 mid 改用自身 CEX TOB + rebase 口径 + 资产 ID 语义；新增 Q5/Q6。公式与模型字段无变化 |
| 2026-08-04 | **WHI-838**：§4.1 增 `$100` 为第五档 → `[100, 1_000, 10_000, 100_000, 1_000_000]`；collector 改为五档都采；注明零售档 gas_bps 放大与 dashboard 按列 heat。公式与 `QuoteStatus` 词汇无变化 |
