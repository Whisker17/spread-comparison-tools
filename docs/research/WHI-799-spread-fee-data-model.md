# WHI-799：Spread & 费用统计口径 + 统一数据模型

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-799](https://linear.app/whisker-personal/issue/WHI-799) |
| Milestone | M1 调研与口径定义 |
| Blocks | [WHI-801](https://linear.app/whisker-personal/issue/WHI-801)（FastAPI + adapter 接口）、[WHI-812](https://linear.app/whisker-personal/issue/WHI-812)（费用数据整理） |
| Downstream | WHI-802…806（各 venue adapter）、WHI-807（`/quotes` + reference mid 服务）、WHI-813…815（fees / simulate）、**[WHI-880](https://linear.app/whisker-personal/issue/WHI-880) / [WHI-881](https://linear.app/whisker-personal/issue/WHI-881)**（underlying-first stocks） |
| 规范日期 | 2026-08-03（UTC；v2 同日对齐 WHI-797/798 v2；**v3 2026-08-06** underlying-first stocks） |
| 性质 | **规范（spec）**，非 live 探测；字段名与公式以本文为准，M2 代码不得另立口径 |

> **v2 变更**（因 WHI-797/798 重做而来，公式与模型字段**均不变**）：
> 1. Prop AMM 不再是 Solana 单链 class：Tessera 部署于 Solana + **Base + BSC**（BSC 是其最大链）。venue slug 引入**链维度**：`tessera` 拆为 `tessera_solana` / `tessera_base` / `tessera_bsc`（§6.5）；EVM 侧报价路径为 KyberSwap `includedSources=tessera`（§4.4）。
> 2. Stocks 新增 **bStocks 三方对比**（Binance spot × PancakeSwap × Tessera BSC）为 P0-A（WHI-798 v2）——tokenized 路径曾用**该 token 自身** CEX TOB 作 mid。
>
> **v3 变更（[WHI-880](https://linear.app/whisker-personal/issue/WHI-880)，2026-08-06）**——**推翻** v2 §3.3「每个 tokenized token id 各自 mid」：
> 1. Stock **logical asset = underlying**（`NVDA` / `QQQ` / `SPCX`…）；可交易形态是 **`form`**（`perp` / `bstock` / `ondo` / `xstock` / `xstock_cex`，见 WHI-798 §4.6）。
> 2. **每个 underlying 每个 snapshot 只解析一次 mid**；所有 form 共用 → `spread_bps` / `total_cost_bps` **跨 form 可比**。Wrapper 溢价/折价进 **`basis_bps`**，不进 spread。
> 3. 行身份变为 `(venue, asset, form, instrument_type)`；`Quote.form` 入模型（§6.2）。
> 4. §5.2 **best** 默认按 **`form_class`**（`perp` | `tokenized`）分组；overall-best 仅作可选、带 caveat。
> 5. 公式（§4.5 / §5.2 算术）不变；bps 定义不变。

## 1. 结论摘要（TL;DR）

1. **名义金额（notional）**固定五档：`$100` / `$1_000` / `$10_000` / `$100_000` / `$1_000_000`（USD）。先用 **reference mid** 换算目标 base 数量，再 walk book / 调 quoter。
2. **Effective spread at size**（单边，bps）：
   - Buy：`spread_bps = (effective_price - mid) / mid * 10_000`
   - Sell：`spread_bps = (mid - effective_price) / mid * 10_000`
   - 双边汇总：`round_trip_spread_bps = buy + sell`，`half_spread_bps = round_trip / 2`。
3. **Top-of-book spread**仅 orderbook venue：`(best_ask - best_bid) / mid_ref * 10_000`；AMM / Prop AMM 的 `get_orderbook_spread` **返回 `None`**（不用假 TOB）。
4. **Reference mid**（全 venue 共用，绑定 `snapshot_id`；**stock 另见 §3.3 v3**）：
   - Crypto blue chips **P0**：Binance USDT-M **indexPrice**（`GET /fapi/v1/premiumIndex`）；**P1** Binance spot TOB mid；**P2** Bybit spot TOB；**P3** Pyth `price`（不用 conf 区间中点）。
   - **Stocks（v3）**：每个 **underlying** 一个 mid（`cex_tradfi_index` → `proxy_perp_mark_median` → tokenized CEX spot TOB fallback）；**所有 form 共用**。Spot 与 Perp 共用同一 mid。
   - **Funding 不计入**默认 `total_cost_bps`。
5. **Total cost（单一权威公式，§5.2）**：
   - `trading_component_bps` = 0 若 `embedded_in_price`，否则 = 显式 trading fee bps
   - 若 `gas_unknown`：`total_cost_bps = null`（禁止当 0 排序）
   - 否则：`total_cost_bps = spread_bps + trading_component_bps + platform_fee_bps + gas_bps`
   - `explicit_fee_bps` = `trading_component_bps + platform_fee_bps + gas_bps`（仅 total 非 null 时定义）
   - **Stocks best（v3）**：默认 **按 `form_class` 分组**后取最优；overall 跨 class 仅可选且必须带 form caveat。
6. **统一模型**：`Quote`、`TopOfBook`、`FeeBreakdown`、`FeeSchedule`、`ReferenceMid`；均携带 `snapshot_id`；CEX 经 `instrument_type` 区分 spot/perp；**stocks 经 `form` 区分形态**（§6.2）；adapter 抽象见 §7。

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
| `asset` | 规范资产 ID（`BTC` / `ETH` / `SOL` / **`NVDA`** / …）；venue 本地 symbol 进 `venue_symbol`。**Stocks v3**：`asset` = **underlying**，不是 token 后缀 id（`NVDAB` 不再是 asset） |
| `form` | Stock 可交易形态稳定 id（`perp` / `bstock` / `ondo` / `xstock` / `xstock_cex`；WHI-798 §4.6）。非 stock 可为 null |
| `form_class` | best 分组：`perp` \| `tokenized`（由 form 派生，不必持久化进 Quote，但 API/UI 可暴露） |
| `snapshot_id` | 一次聚合/采集快照的 UUID 或时间桶 ID；同一快照内 mid 与全部 Quote 共享 |
| `mid` / `mid_ref` | 该快照该 `asset`（underlying）的 **reference mid**（quote per base，USD）——**不**按 form 分叉 |
| `N` / `notional_usd` | 名义金额（USD） |
| `q_star = N / mid` | 目标 base 数量（1× underlying 单位口径） |
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

**WHI-846 补充（pull-only 后台 sweep）**：`snapshot_id` 标识的是 **某一个 source group 的一次采样 pass**（例如一次 Jupiter 类 sweep、一次 orderbook 实时 fan-out），**不是**一次 HTTP 响应。`GET /quotes` 响应可以混入不同 `snapshot_id` 的行（实时 orderbook 行 vs 上一轮 pull sweep 行）。在任意 `(asset, snapshot_id)` 上，上述「只解析一次 mid、全 venue 同 mid」规则仍然严格成立。对 store 中的 pull 报价：**禁止**在读时用更新的 mid 重算 `spread_bps` / `total_cost_bps`（pairing invariant）——数字与观测时刻的 mid 绑定。

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

### 3.3 Stocks / Others（**v3 underlying-first**）

#### 3.3.1 Stock underlyings — 单一 mid 优先级链

对每个 **underlying** `asset`（`NVDA` / `TSLA` / `QQQ` / `SPCX` / …），在给定 `snapshot_id` 下 **只解析一次** `ReferenceMid`。该 mid 复制到该 underlying **全部 form、全部 venue** 的 Quote（与 §3.1 不变量一致：`(snapshot_id, asset)` → 唯一 mid）。

| 优先级 | `mid_source` | 定义 | 何时用 |
| --- | --- | --- | --- |
| **P0** | `cex_tradfi_index` | CEX TradFi / stock-perp **index**（优先 Binance stock/TradFi index；字段以 adapter 实测为准，如 premiumIndex / 专用 TradFi ticker 的 index 侧） | 该 underlying 有可用 equity/TradFi index |
| **P1** | `proxy_perp_mark_median` | **Binance + Bybit + Hyperliquid + Lighter + ApeX** 上该 underlying **perp form** 可用 mark 的中位数；偶数样本 → 中间两档算术平均（与现 `median_marks` 一致） | P0 失败 |
| **P2** | `binance_spot_tob` 或 `bybit_spot_tob` | **Tokenized CEX spot TOB fallback**（不是「按 form 分 mid」）。**固定尝试序**（第一个成功即停，**不**按实时深度动态排序）：① `bstock` @ Binance spot → `mid_source=binance_spot_tob`；② 否则 `xstock_cex` @ Bybit spot → `mid_source=bybit_spot_tob`。Wire symbol **只** 从 catalog / `cex_symbols` 的 `(asset, form)` 映射取（如 `NVDABUSDT`），**禁止**靠 `{TICKER}B` 字符串模板猜（反例：命名不规则资产） | P0/P1 皆失败（常见：无 perp 的 underlying，或私募无 index） |

**Config 表面（WHI-881）**：废除按旧 token id 键控的 `TOKENIZED_CEX_SPOT` / `TOKENIZED_UNDERLYING`。在 `config/mid.yaml`（或等价 typed settings）增加 underlying 级：

| 键 | 默认 | 标注 |
| --- | --- | --- |
| `mid.stock_mid_p2_order` | `[{form: bstock, venue: binance}, {form: xstock_cex, venue: bybit}]` | **unvalidated** pending `docs/DESIGN.md` §2 |

`SPCX` 等同默认但跳过 P0/P1。P1 mark 采样：允许读 **catalog 中存在的** perp venue 符号，即使该 form 当前 `coverage=unverified` / 未 fan-out 到 dashboard（mark 拉取样 ≠ quote fan-out）。

**刻意推翻 v2 的点**：v2 让 `NVDAB` 用 `NVDABUSDT` TOB、`NVDAON` 用 equity ref、`NVDA` perp 用 mark median——**三个 mid**，bps 不可比。v3 只保留 **underlying 一个 mid**；tokenized CEX TOB 降为 **P2 fallback**（及 basis 的本地锚，见下），不再是 bstock 行的专属 mid。

**UI**：stock mid 弱于 crypto P0——dashboard 须强调 `mid_source`（现有 `STOCKS_MID_SOURCE_HINT` 继续适用）。

#### 3.3.2 特例：`SPCX`（SpaceX，私募 / 无公开 equity ref）

| 项 | 口径 |
| --- | --- |
| 无 P0 | 无私募 SpaceX 的公开 TradFi index（本产品 venue 集内） |
| 无 P1 | 无 exact `SPCX` perp（§6.2 WHI-798） |
| **钉死 mid** | **P2 only**：优先 `binance_spot_tob` on `SPCXBUSDT`（`bstock`）；失败则 `bybit_spot_tob` on `SPCXXUSDT`（`xstock_cex`，若在架） |
| 失败 | mid 服务对该 asset 失败 → 与全局一致，聚合 **不**返回残缺可比集（503/422） |
| `sources_detail` | 应含 `private_underlying_no_equity_ref` 之类可机读标记，供 UI 文案 |

#### 3.3.3 跨 form 基差（`basis_bps`）与 spread 的关系

在 **单一 underlying mid**（≈ fair equity / index）下，§4.5 的

```text
spread_bps = (P* − mid) / mid * 10_000   # buy
```

**按构造**会把「形态溢价/折价 + 执行偏离」合在一个数字里。这是 v3 的**刻意选择**：产品问题是「相对公允价，拿 NVIDIA 暴露的 all-in 偏离」，跨 form 必须共用 mid 才可比。

| 规则 | 口径 |
| --- | --- |
| 分解（展示） | `basis_bps = (local_anchor - mid) / mid * 10_000`（与 `costs.basis_bps` 同形）≈ **结构性** wrapper/NAV/形态基差；`spread_bps − basis_bps`（若两者皆非 null）≈ 相对 **该 form 本地锚** 的执行偏离——**仅诊断**，不另立排序主键 |
| `local_anchor` | **Phase 1**：仅 orderbook 行填 — `venue_mark` 或 local TOB mid。AMM / prop：**`basis_bps=null`**（不为分解再打一枪 quoter；避免 WHI-864 Jupiter 预算被吃穿）。后续若要 AMM basis，另开 issue + 配置 notional（须 `unvalidated` + DESIGN.md §2） |
| **禁止双重计数** | **不得**再把 `basis_bps` 加进 `total_cost_bps`（total 已含相对 fair mid 的 all-in 偏离 + 显式费） |
| **排序主键** | 默认仍 `total_cost_bps`（§5.2）；它回答「相对 fair mid 谁更便宜」。同一 `form_class` 内跨 form 比较时，**用户应同时看 `basis_bps`**（orderbook 行）——较低 total 可能来自较负的形态基差而非更薄的盘口 |
| Rebase | bStocks rebase 日：同一 `snapshot_id` 内自洽；**跨快照**历史对比（WHI-817）按 rebase 事件分段，公司行动日异常不入窗口统计（实现 WHI-816/817） |

**废弃**：`equity_ref_same_as_perp` 作为「某 tokenized token 的独立 mid 源」。实现 **删除** 对该源的分 asset 解析路径（与 legacy asset id 一样做 breaking 清理，不留静默 alias）。若枚举值暂留在 `MidSource` 类型里仅为反序列化旧缓存，不得再写出新 Quote。

#### 3.3.4 Others

| 资产类 | 策略 |
| --- | --- |
| Others | 同 §3.2 枚举；无 index 时 P1/P2 spot TOB。**无 form 维度**（与 blue chips 相同） |

### 3.4 Spot vs Perp 可比性

| 决策 | 口径 |
| --- | --- |
| 共用 mid | **同一 underlying 的** perp form 与 tokenized forms 都相对 **同一** reference mid 算 `spread_bps`（v3） |
| Basis | `venue_mark` / local anchor → `basis_bps`；**不**并入 `spread_bps`（§3.3.3） |
| Funding | **默认不计入** spread / total cost（§5.3） |
| 合约乘数 | `1000PEPE` / `kPEPE` 等在 adapter 内换算为规范 `asset` 的 1× 单位（[WHI-798](./WHI-798-asset-category-inventory.md)） |
| 暴露差异 | perp vs tokenized **不是**同质持仓——best 规则见 §5.2 v3（按 `form_class` 分组） |

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
- **Lot / tick rounding (WHI-838):** adapters walk continuous `q_star` (no lot/step quantize yet — see `docs/DEFERRED_ISSUES.md` WHI-803). At the $100 tier with typical CEX lots (BTC `1e-5`, ETH `1e-4`, SOL `1e-2`) and blue-chip mids, continuous vs nearest-lot `walk_book` Δspread_bps is **0** on a tight synthetic book (qty relative error ≤0.5% for SOL; 0% for BTC). **Conclusion: not material** — no silent rounding change in this issue.

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

**排序规则（给 dashboard / simulate）**：仅 `status=ok` 且 `total_cost_bps is not null` 参与「最优」排序；`gas_unknown` 行单独分组或标「成本不完整」，**不得**因 gas=0 幻觉排到最前；`excessive_impact`（WHI-845）保留数字但**永不** best，且不进入 heat 范围。`quote_stale` / `not_sampled` / `rate_limited` 等同前：不参与 best。

#### 5.2.1 Stocks：跨 form 的 `best` 语义（v3 / WHI-880）

`form_class` 成员与暴露定义见 **WHI-798 §4.6**（此处不重抄表）。产品问题「哪里买 NVIDIA 暴露最便宜」同时碰到 `perp` vs `tokenized` 两类不同暴露。

**拍板（默认 + 可选）**：

1. **默认 best（dashboard 矩阵徽章 / summary engine）**：**按 `form_class` 分组**后，在每个 class 内对 `status=ok` 且 `total_cost_bps is not null` 的行取 `min(total_cost_bps)`（side 与现 FE 一致，默认 buy）。  
   - 结果形状：每个 underlying 可有 **两个** best（`best_perp`、`best_tokenized`），而不是一个跨 class 冠军。  
   - 同一 `form_class` 内跨 form（如 `bstock` vs `ondo`）用同一 mid 比 total cost = 比 **相对 fair mid 的 all-in**（可含形态基差；见 §3.3.3）。徽章旁应能看到赢家 `form` 与可选 `basis_bps`。
2. **Overall-best（可选视图）**：可在全部 form 上再取全局 `min(total_cost_bps)`，但 UI **必须**同时展示获胜行的 `form` + `form_class` caveat（例如「cheapest path is perp — funding not in cost」）。Overall-best **不得**作为默认 heat/徽章唯一来源。
3. 非 stock（blue chips / others）：无 form_class 分区——保持今日「全局 min total_cost」行为。
4. **`POST /simulate`（非本 issue API 范围；WHI-881 顺带对齐）**：若请求带 form 则只扩该 form；未带则扩 live forms，**排名仍按 form_class 分区**或返回分区 best 字段——不得无标注地混排 perp 与 tokenized。

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
  | "rate_limited"             # WHI-844：限流等待会超过本 call 剩余 budget（非 timeout）
  | "excessive_impact"         # WHI-845：价格冲击超过 config 阈值；数字仍展示，不参与 best/heat
  | "not_sampled"              # WHI-865：pull poller 故意不采该 (notional, side) 或本进程尚未产出样本；非失败
```

（`TopOfBook` 不复用该枚举——orderbook 适配器用返回值 `None` 表示「本 venue 无 TOB 概念」，见 §6.3 / §7。）

### 6.2 `Quote`

```text
Quote {
  # --- identity ---
  snapshot_id:        str
  venue:              str                 # §6.5 slug
  asset:              str                 # underlying / logical id（stocks v3 = underlying）
  form:               str | null          # WHI-880：stocks 必填（WHI-798 §4.6 词汇）；
                                          # blue chips / others = null（隐式单形态）
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
  total_cost_bps:     Decimal | null      # gas_unknown 或非 priced status 时 null

  # --- book-keeping ---
  timestamp:          datetime            # venue 报价时刻 UTC
  status:             QuoteStatus
  qty_base:           Decimal | null      # 实际用于定价的 base；approx 时为实际成交量
  qty_method:         "base_from_mid" | "quote_exact_in_approx" | null
  venue_mark:         Decimal | null
  basis_bps:          Decimal | null      # §3.3.3：相对同一 underlying mid 的形态/本地基差
  raw_ref:            str | null          # 可选调试句柄：上游 request id 或 samples 相对路径

  error_code:         str | null
  error_message:      str | null
  price_impact_bps:   Decimal | null      # WHI-845：上游/推导的价格冲击（bps）；诊断用
}
```

**行身份（v3）**：可比报价行的唯一键为

```text
(venue, asset, form, instrument_type, side, notional_usd)
```

（`form=null` 时退化为今日的 `(venue, asset, instrument_type, …)`。）  
**禁止**假设 `(venue, asset)` 或 `(venue, asset, instrument_type)` 唯一——反例：`tessera_bsc` + `NVDA` 同时有 `bstock` 与 `ondo`（二者常同为 `prop_amm`）。

**Stream / cache / store 键（WHI-848 / WHI-846 / WHI-843）**：所有把 pair 压成字符串键的路径（至少 `stream.py` delta key、`quote_store`、orderbook cache、poller 矩阵、以及仍读 `TOKENIZED_CEX_SPOT` 的 `ws_bootstrap` 订阅范围）**必须**纳入 `form`（null 时用哨兵如 `-`）。今日 `f"{venue}|{notional}|{instrument_type}"` 在双 form 同 instrument_type 时会静默互相覆盖——WHI-881 必改。

**`instrument_type` 派生（唯一规则）**：

| Venue class | 规则 |
| --- | --- |
| CEX (`binance`, `bybit`) | `form_class=perp` → `perp`；`form_class=tokenized` → `spot` |
| Perp DEX | 恒 `perp`（仅 `form=perp` 有意义） |
| AMM DEX | 恒 `amm_pool` |
| Prop AMM | 恒 `prop_amm` |

Adapter **不得**另立推导；catalog 只提供 form + venue 覆盖，不覆盖上表。

**不变量**：

1. 若 `status` 为 **priced**（`ok` 或 `excessive_impact`，WHI-845）：则 `effective_price`、`spread_bps`、`qty_base` 均非 null；**并且**  
   - 若 `fee_breakdown.gas_unknown` 为 true，则 `total_cost_bps is null`；  
   - 若 `fee_breakdown.gas_unknown` 为 false，则 `total_cost_bps` 非 null。  
   （两条合取，不是析取。）  
   另：`status=excessive_impact` 时 `price_impact_bps` 必须非 null。
2. 若 `status` **不是** priced（即不是 `ok` / `excessive_impact`）：则 `effective_price`、`spread_bps`、`total_cost_bps`、`qty_base`、以及 `fee_breakdown.explicit_fee_bps` 均为 null。
3. **同 `(snapshot_id, asset)` ⇒ 同 mid**（`mid` / `mid_source` / `mid_timestamp` 在同一 `snapshot_id` 的同一 `asset` 上**全 venue、全 form**一致）。**不再**要求「同一次 HTTP 响应 ⇒ 同一 `snapshot_id`」——WHI-846 起，一个 `GET /quotes` 响应可混合多个 source group 的 `snapshot_id`（见 §3.1）。
4. bps 公式 **仅** §4.5 / §5.2；`basis_bps` **不**进入 total。
5. `mid_stale` 与 `status` 独立：`mid_stale=true` 仍可 `status=ok`。
6. **WHI-845 价格冲击护栏**（AMM / prop-AMM 报价路径；CEX/perp 盘口不在此护栏范围）：当 adapter 测得 `price_impact_bps` 且超过 `config/impact.yaml` 的 `max_price_impact_bps`（**unvalidated** pending DESIGN.md §2）时，`status` 置为 `excessive_impact`。**不得**静默丢行——数字保留可读，但不参与 §5.2 best，也不进入 dashboard 分列 heat 范围。Jupiter 用 `priceImpactPct`（单位分数）× 10_000；Kyber / on-chain quoter 无独立字段时用 **adverse** mid 相对 spread（`max(spread_bps, 0)`，有利偏差不触发）。`price_impact_bps` 为诊断字段，非 priced status 下通常为 null（不强制与 mid_stale 同级的正交语义）。
7. **WHI-846 观测年龄门闩**：store-backed 行带 `age_sec` 与正交标志 `quote_stale`。当年龄超过该 source group 的 `max_quote_age_for_best_sec`（`config/poller.yaml`，**unvalidated**；默认 2× sweep interval）时 `quote_stale=true`——数字仍可读，**不**参与 §5.2 best（与 `excessive_impact` 同模式）。live fan-out 行 `quote_stale=false`、`age_sec` 可 null。
8. **WHI-880 form 约束**：若 `asset` 的 catalog category 为 stock（underlying-first），则 `form` 必须为 WHI-798 §4.6 词汇表中的值；非 stock 的 `form` 必须为 null。

### 6.3 `TopOfBook`

仅 orderbook venue 在 **成功拉簿** 时返回该对象；AMM / Prop **始终**返回 `None`（「无 TOB 概念」）。

```text
TopOfBook {
  snapshot_id:        str
  venue:              str
  asset:              str
  form:               str | null          # 与 Quote.form 对齐（WHI-880）
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
  form:                      str | null        # WHI-880；与 buy/sell Quote.form 一致
  instrument_type:           "spot" | "perp" | "amm_pool" | "prop_amm"
  notional_usd:              Decimal
  buy:                       Quote | null
  sell:                      Quote | null
  round_trip_spread_bps:     Decimal | null
  half_spread_bps:           Decimal | null
  round_trip_total_cost_bps: Decimal | null
  top_of_book:               TopOfBook | null  # 若有，instrument_type（及 form）必须与 pair 一致
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
| 限流等待会超过本 call 剩余 budget（本地 limiter 或上游 429） | `rate_limited` | 200 + 该 venue 错误；**不得**与 `timeout` 混淆；不参与 §5.2 best（WHI-844） |
| 价格冲击超过 config 阈值（池深度被吃穿等） | `excessive_impact` | 200；**保留** effective/spread/total 数字可读；不参与 §5.2 best；排除出 heat 范围（WHI-845） |
| pull poller 未采样该 (notional, side)（稀疏矩阵或进程内尚未 sweep） | `not_sampled` | 200；**不得**写成 `error`（`error` = tried and failed）；不参与 §5.2 best；非 priced 故不进 WHI-819 fresh-quote 探针（与 `PRICED_QUOTE_STATUSES` 对齐，WHI-865） |
| mid 不可用 | — | 整包 503/422 |

#### 6.6.1 Venue minimums at the $100 tier (WHI-838)

$100 sits near some venue min-order floors. **No new `QuoteStatus` value** — map honestly onto the table above. **Expectations below are engineering priors, not live-measured at every venue** (confirm with `@pytest.mark.live` / dashboard after deploy):

| Venue class | Expected at $100 (unverified prior) | Status if venue refuses |
| --- | --- | --- |
| CEX spot/perp (`binance`, `bybit`) | Blue-chip min notional typically ≪ $100; continuous `walk_book` on L2. If depth < `q_star` (rare at this size) | `insufficient_liquidity` |
| Perp DEX (`hyperliquid`, `lighter`, `apex`) | Min notional often ~$10; $100 generally quotable. Thin books / size filters → walk fails | `insufficient_liquidity` (or `no_quote` if market absent) |
| AMM DEX (`uniswap_eth`, `aerodrome_base`, `pancakeswap_bsc`) | Quoter returns a price; gas dominates cost (intended). Pool missing / amount too small for pool | `no_quote` |
| Prop AMM Solana (Jupiter) / EVM (KyberSwap) | Route-based; may return no route for illiquid wrappers or amount edge cases | `no_quote` |

Adapters must **not** invent a synthetic fill for a size the venue would reject.

**Solana prop `gas_bps=0` at $100:** base fee is still ≪ EVM L1 gas, but discretionary priority fees can be tens of bps on a $100 notional. The project keeps the §8 `gas_bps=0` convention (no `gas_unknown`) so Solana props remain §5.2 best-eligible; the intentional gas-dominance signal is the EVM AMM row. Revisit if priority-fee accounting lands.

### 6.7 API 契约草案（WHI-880 → 实现 WHI-881；对照当前 FE）

> 非 OpenAPI 定稿（OpenAPI 仍由代码生成），但是 **形状 SSOT**。对照今日 `frontend/src/config/sections/stocks.ts`：  
> - 旧：`TOKENIZED_STOCK_ASSETS = QQQB|SPCXB|NVDAB|NVDAON` 与 `EQUITY_PERP_ASSETS = TSLA|NVDA|AAPL|MSFT` 两套无关 id。  
> - 新：单一 underlying 列表 + nested forms；FE 跟随后续 issue 改 section config。

#### 6.7.1 `GET /assets`

form id / form_class 词汇表：**只引用** [WHI-798 §4.6](./WHI-798-asset-category-inventory.md)，此处不重抄。

```text
AssetResponse {
  id:              str                 # underlying，如 "NVDA"
  category:        str                 # 见 §6.7.3 category 重命名
  forms:           list[FormInfo] | null
    # stock：非 null，至少含 Phase-1 live forms；可含 coverage=unverified 的 catalog 行
    # 非 stock：null（表示标签只用扁平 representations，行为与今日兼容）
  representations: dict[str, str] | null
    # 非 stock：必填，= 今日 venue→label
    # stock：必须为 null（表示只在 forms[].representations；禁止「主 form 扁平投影」双写）
}

FormInfo {
  id:               str                # WHI-798 §4.6
  form_class:       "perp" | "tokenized"
  # 无单一 instrument_type 字段——一个 form 可跨 spot / amm_pool / prop_amm
  # （例 bstock：binance=spot，pancakeswap_bsc=amm_pool，tessera_bsc=prop_amm）
  # 具体 Quote.instrument_type 由 (venue, form) 在 adapter/catalog 解析
  representations:  dict[str, str]     # venue slug → display label
  coverage:         "live" | "unverified" | "absent"
    # live = 当前会 fan-out；unverified = catalog 保留（WHI-798 📗/📌）；absent = 明确无市场
}
```

**示例（NVDA，节选）**：

```json
{
  "id": "NVDA",
  "category": "stock",
  "representations": null,
  "forms": [
    {
      "id": "perp",
      "form_class": "perp",
      "coverage": "live",
      "representations": {
        "binance": "NVDAUSDT",
        "bybit": "NVDAUSDT",
        "hyperliquid": "xyz:NVDA",
        "lighter": "NVDA",
        "apex": "NVDA-USDT"
      }
    },
    {
      "id": "bstock",
      "form_class": "tokenized",
      "coverage": "live",
      "representations": {
        "binance": "NVDABUSDT",
        "pancakeswap_bsc": "NVDAB",
        "tessera_bsc": "NVDAB"
      }
    },
    {
      "id": "ondo",
      "form_class": "tokenized",
      "coverage": "live",
      "representations": {
        "pancakeswap_bsc": "NVDAon",
        "tessera_bsc": "NVDAon"
      }
    },
    {
      "id": "xstock_cex",
      "form_class": "tokenized",
      "coverage": "unverified",
      "representations": { "bybit": "NVDAXUSDT" }
    },
    {
      "id": "xstock",
      "form_class": "tokenized",
      "coverage": "unverified",
      "representations": {}
    }
  ]
}
```

#### 6.7.2 `GET /quotes`

| 参数 | 语义 |
| --- | --- |
| `asset` | **Required.** Underlying id（`NVDA` / `QQQ` / `SPCX` / …）。 |
| `forms` | Optional. 逗号分隔 form id 过滤；缺省 = 该 asset 全部 **live** forms。 |
| `notional` / `notionals` | 不变（WHI-843）。 |
| `venues` / `instrument_type` | 保持现有过滤能力；与上表 `instrument_type` 派生叠加。 |

**响应**：

```text
QuotesResponse {
  snapshot_id:   str          # 主 source-group 的 id（WHI-846 混 snapshot 规则不变）
  asset:         str          # underlying
  notional_usd:  Decimal
  mid:           ReferenceMid # 该 underlying 唯一 mid
  pairs:         list[SizeQuotePair]  # 含 form；可多 form
  notionals:     list[Decimal]
}
```

**不变量**：一次 `asset=NVDA` 响应内，所有 form 行共享同一 `ReferenceMid`（在各自 `snapshot_id` 规则下）；`tessera_bsc` 可出现 **两条** pair（`form=bstock` 与 `form=ondo`）。

#### 6.7.2b `WS /stream`（WHI-848；dashboard 主路径）

| 项 | 口径 |
| --- | --- |
| Subscribe filter | 在现有 asset/venues/notionals 上增加可选 `forms`（与 HTTP 同语义；缺省 = live forms） |
| Delta / snapshot 行 | 每条 pair 带 `form`；coalesce 键含 form（§6.2） |
| Resnapshot | 同 filter 全量重发 |

#### 6.7.2c `POST /simulate`（WHI-881 顺带；非本 issue 实现）

可选 body/query 字段 `form`（单值）或 `forms`（列表）。缺省 = 扩全部 live forms；§5.2.1 form_class 分区排名。形状细节留给实现 issue，但 **不得** 无 form 维度地混排。

#### 6.7.3 Breaking renames（asset id + category）

| 决策 | **Breaking，不做静默 alias 双写**（pre-v1 可接受） |
| --- | --- |
| 废除 top-level asset | `NVDAB`, `NVDAON`, `QQQB`, `SPCXB` |
| 迁移 | WHI-798 §4.6 → `(NVDA,bstock)` / `(NVDA,ondo)` / `(QQQ,bstock)` / `(SPCX,bstock)`；旧 `equity_perp` 行 `TSLA|NVDA|AAPL|MSFT` → 同 id + `form=perp` |
| 请求旧 id | **HTTP 422** + 机读 body：`error_code: legacy_asset_id`，`message` 含目标 `asset`+`form`（与 WHI-815 结构化 422 一致；**不用** 404）。**WS `/stream` subscribe** 若带旧 asset id：同机读错误帧关闭或 error 事件（实现二选一，但 **不得** 静默忽略） |
| `GET /assets` | **不**再列出旧 id 行 |
| **Category 枚举** | 废除 `tokenized_stock` 与 `equity_perp`；stock underlyings 统一 `category="stock"`。`crypto_blue_chip` / `other` 不变 |
| Mid 枚举 | 停止写出 `equity_ref_same_as_perp` 作为新 mid 源（§3.3.3） |
| Crypto / others 资产 id | 无变更 |

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
| Prop AMM（Solana：`humidifi` / `tessera_solana` / `bisonfi`） | Jupiter `dexes=<Label>` 净输出 | `None` | `embedded_in_price=true`；platform 0；`gas_bps=0`（base fee 对 ≥$1k 档 <0.1 bps，约定忽略；`$100` 档若 priority fee 显著则仍可能 ≥0.1 bps，但不改 `gas_bps=0` 约定 — Solana 侧相对 EVM L1 仍可忽略）；无路由 → `no_quote` |
| Prop AMM（EVM：`tessera_base` / `tessera_bsc`，v2） | KyberSwap `includedSources=tessera` 净输出（§4.4） | `None` | `embedded_in_price=true`；platform 0；**gas 用响应 `gasUsd`**（`gas_unknown=false`）；4008→`no_quote`，4000（token 不在集）→`unsupported_asset`，40011→fail-fast |

---

## 9. 指标在产品中的用法（非 UI 规格）

供 dashboard / summary **选用**的指标集合（具体默认列由 WHI-808+ 定）：

- 单边：`spread_bps`、`total_cost_bps`（buy 或 sell）
- 双边：`half_spread_bps`、`round_trip_spread_bps`、`round_trip_total_cost_bps`
- 盘口：`TopOfBook.spread_bps`（仅 orderbook）
- **Stocks（v3）**：`basis_bps`（形态/本地相对 fair mid）；`form` / `form_class` 标签；best 徽章默认 **per form_class**（§5.2.1）
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
| Q1 | Stocks 是否强制外部 equity feed | **v3**：P0 `cex_tradfi_index` → P1 mark 中位数 → P2 tokenized CEX TOB；不强制外部 equity vendor |
| Q2 | 产品主列默认 half-spread 还是 total cost (buy) | 建议 total cost (buy)；UI 可切换 |
| Q3 | VIP 是否进 Phase 1 主路径 | 仅 `default_taker` |
| Q4 | Gas 用即时价还是分位 | 即时 + 保守 gas limit（WHI-804/812）；EVM prop AMM 直接用 KyberSwap `gasUsd` |
| Q5（v2） | bStocks rebase 事件日的历史统计分段与异常剔除的具体实现 | §3.3 已定口径（rebase 日不入窗口统计）；实现细节归 WHI-816/817 |
| Q6（v2） | KyberSwap 报价对 Tessera BSC「实际成交价」的代表性（~95% 成交经 Binance Wallet 闭环路由，不经 Kyber） | Phase 1 接受 Kyber 报价为该 venue 公开可得价；M2 后可用 `TesseraTrade` 事件对账（WHI-797 §7.1 / WHI-798 Q16） |
| Q7（v3） | ~~Tokenized 是否各自 mid~~ **已拍板（WHI-880）**：underlying 单一 mid；spread 按构造含形态基差，basis 作分解、禁止双重计数 | §3.3 v3 |
| Q8（v3） | ~~跨 form best 是否全局~~ **已拍板**：默认 per-`form_class`；overall 可选 + caveat | §5.2.1 |
| Q9（v3） | ~~Legacy id / category alias~~ **已拍板**：breaking rename + `legacy_asset_id`；`category=stock` | §6.7.3 |

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
| 2026-08-04 | **WHI-844**：§6.1 / §6.6 增 `rate_limited`（限流等待会超过本 call 剩余 budget，fail-fast，与 `timeout` 区分）；§5.2 best 规则不变（仅 `status=ok` 且 `total_cost_bps` 非 null） |
| 2026-08-04 | **WHI-845**：§6.1 / §6.6 增 `excessive_impact`；§6.2 增 `price_impact_bps` 与 priced-status 不变量（`ok`/`excessive_impact` 保留数字；阈值 `config/impact.yaml` unvalidated）；§5.2 best 仍仅 `status=ok` 且 `total_cost_bps` 非 null；heat 排除非 ok |
| 2026-08-05 | **WHI-846**：§3.1 明确 `snapshot_id` = source-group 采样 pass（非 HTTP 响应）；§6.2 不变量 3 改为「同 snapshot_id ⇒ 同 mid」；增不变量 7 `quote_stale`/`age_sec` 与 best 年龄门闩（`config/poller.yaml` unvalidated）。store 行禁止读时重算 bps |
| 2026-08-05 | **WHI-865**：§6.1 / §6.6 增 `not_sampled`（pull poller 稀疏矩阵未采 / 本进程尚未采样；非 transport 失败）。§5.2 best 仍仅 `status=ok` 且 `total_cost_bps` 非 null；不计入 error-rate / WHI-819 失败信号。Jupiter 采样档改 `$100/$1k/$10k`（见 `config/poller.yaml` 算术注释） |
| 2026-08-06 | **v3 / WHI-880**：underlying-first stocks。§2.2 增 `form`/`form_class`；§3.3 重写为单一 underlying mid 链 + SPCX 特例 + `basis_bps` 规则（推翻 v2 分 form mid）；§5.2.1 best 按 form_class；§6.2/6.3/6.4 增 `form` 与行身份；§6.7 API 草案 + legacy breaking rename。公式算术不变 |
| 2026-08-06 | Review r1：P2 mid 固定尝试序 + config 表面；澄清 spread 含形态基差但禁止双重计数；stream/store 键必含 form；`FormInfo` 去掉错误的单一 `instrument_type`；stock `representations` 强制 null；category/`equity_ref` breaking 表；simulate 标为 WHI-881 顺带 |
| 2026-08-06 | Review r2：`stock_mid_p2_order` 标 unvalidated；P1 mark 可读未 fan-out perp；AMM basis Phase1=null；instrument_type 派生表；stream `forms` 过滤；legacy 固定 422；符号只走 catalog 映射 |
