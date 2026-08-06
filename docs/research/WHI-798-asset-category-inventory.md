# WHI-798：确定各资产类别的资产清单

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-798](https://linear.app/whisker-personal/issue/WHI-798/调研确定各资产类别的资产清单) |
| Milestone | M1 调研与口径定义 |
| Blocks | WHI-809（Section: Crypto blue chips）、[WHI-810](https://linear.app/whisker-personal/issue/WHI-810)（Section: Stocks）、WHI-811（Section: Others） |
| 调研日期 | 2026-08-03（UTC；v2 同日重做 Stocks 部分；**v3 2026-08-06** underlying-first，见 [WHI-880](https://linear.app/whisker-personal/issue/WHI-880)） |
| 方法 | 各 venue **公网 market-list API** live 探测 + 官方文档 + 复用 [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md)（v2 多链版）prop AMM 资产矩阵 |
| 样本 | [`samples/WHI-798-asset-venue-matrix.tsv`](./samples/WHI-798-asset-venue-matrix.tsv) |

> **v2 变更**：初版 Stocks 用「venue 交集优先」方法，得出「全 venue 交集为空 → Stocks 降级/收缩」的结论——方向反了。本版按 issue 要求改为 **asset-first**：先按链上成交量列全 tokenized stocks（不限发行形式：bStocks、xStocks、Ondo 等都算），再逐 venue 找支持并全部纳入矩阵。两个关键事实修正：
> 1. 初版 §4.3.1 把 Binance `*B` 当作「非 xStocks 发行模型」排除——**错误**。`*B` = **bStocks**（BTech/Binance 系，2026-06-12 上线，ADGM 批准 1:1 托管），是**当前链上成交量最大的 tokenized stocks 家族**，必须纳入。
> 2. 初版认为 prop AMM 与 Stocks 无交集——**错误**。Tessera 在 **BSC** 上的成交主力（采样 ~94%）就是 tokenized equities（QQQB 等），且可经 KyberSwap 隔离报价（WHI-797 v2 §7.4）。
>
> **v3 变更（[WHI-880](https://linear.app/whisker-personal/issue/WHI-880)，2026-08-06）**：v2 仍把 **同一 underlying 的不同发行表示**（`NVDAB` / `NVDAON` / `NVDA` perp）编成**互不相关的 catalog 行**，导致 reference mid 分叉、bps 跨 form 不可比。v3 改为 **underlying-first**：catalog 的 logical `asset` = 单一 underlying（`NVDA` / `QQQ` / `SPCX` / …）；每一种可交易形态是 **form** 维度（`perp` / `bstock` / `ondo` / `xstock` / `xstock_cex`）。行身份、表示映射与 mid 策略以 §4.6 / §6.2 v3 与 [WHI-799](./WHI-799-spread-fee-data-model.md) §3.3 v3 为准。**项目规则**：asset-first，**永不静默丢弃**某个 form——未验证的 form 标 `unverified` / `no_quote`，而不是从清单删掉。

---

## 1. 结论摘要（TL;DR）

### 1.1 Crypto blue chips（BTC / ETH / SOL）— **P0 可做全 venue 对比**

| 资产 | 跨 venue 结论 | 关键表示差异 |
| --- | --- | --- |
| **BTC** | ✅ 全部 venue class 均可报价 | CEX/Perp DEX：原生 `BTC` 现货/永续；Solana prop AMM：**cbBTC**；Ethereum AMM：**WBTC** / WETH 对；Base：**cbBTC**；BSC：**BTCB**；HL spot：**UBTC** |
| **ETH** | ✅ 全部 venue class 均可报价 | CEX/Perp DEX：`ETH`；Solana prop AMM：**Wormhole WETH**；ETH/Base AMM：**WETH**；BSC：桥接 ETH；HL spot：**UETH** |
| **SOL** | ⚠️ **CEX + Perp DEX + Solana prop AMM 完整**；EVM AMM（Uniswap/Aerodrome/Pancake）**无原生 SOL 主市场**（不纳入 Phase 1 SOL 跨链 AMM 对比） | CEX/Perp：`SOL`；Solana：native / wSOL；HL spot：**USOL** |

**推荐 dashboard P0**：`BTC`、`ETH`、`SOL` 三资产；报价路径用下文 **表示映射表**（§3.3），禁止把 `cbBTC` 与 `WBTC` 当同一 mint 硬编码。

### 1.2 Stocks — **v3：underlying-first（form 为维度）**

**方法（v2 保留 + v3 重组）**：先按链上成交量列全 tokenized stocks（§4.2），再逐 underlying 扫 venue（§4.3）；**v3 起 catalog 只登记 underlying**，发行形态挂在 **form** 上（§4.6），不再为每个 token 开独立 logical asset。

**核心发现（v2，仍成立）**：

1. **链上成交量最大的 tokenized stocks 家族是 bStocks（BNB Chain，`*B` 后缀）**——SPCXB、QQQB、NVDAB、SKHYB、MUB、SNDKB 等，单资产 24h $4M–$23M 量级；xStocks（Solana）与 Ondo（`*on`）在其后。
2. **BSC 上存在完整的「CEX 现货 × AMM DEX × Prop AMM」三方可比闭环**：同一 bStocks **form** 在 **Binance spot**、**PancakeSwap v3**、**Tessera prop AMM** 三处同时可报价——产品主场景。
3. Equity **perp form** 路径仍成立（BN TradFi + BY + HL `xyz:` + Lighter + ApeX exact-ticker：TSLA/AAPL/NVDA/MSFT…）。
4. 同一 underlying 常有 **3–5 种 form**（NVIDIA = `bstock` NVDAB + `xstock` NVDAx + `ondo` NVDAon + `xstock_cex` NVDAX + `perp`）——跨 form 基差是可展示指标（`basis_bps`），**不得**混进 `spread_bps`（WHI-799 §3.3 v3）。

**v3 产品口径（WHI-880）**：

| 概念 | 定义 |
| --- | --- |
| **Logical asset** | 单一 underlying 权益/ETF/私募标的（`NVDA`、`QQQ`、`SPCX`、`TSLA`…） |
| **Form** | 该 underlying 的一种可交易形态（稳定 id，§4.6） |
| **Row identity** | `(venue, asset, form, instrument_type)` — 同一 venue 可挂多个 form（例：`tessera_bsc` 同时报 NVDAB 与 NVDAon） |
| **Mid** | **每个 underlying 每个 snapshot 一个 reference mid**；所有 form 共用，使 bps 跨 form 可比 |

**Phase 1 覆盖（v3 重组，不增 ticker）**：

1. **Underlying 集合**：`NVDA`、`TSLA`、`AAPL`、`MSFT`、`QQQ`、`SPCX`（吸收旧 catalog 的 NVDAB/NVDAON/QQQB/SPCXB 与 equity_perp 行）。
2. **Live forms（已在架 / 当前代码路径）**：
   - `perp`：TSLA/NVDA/AAPL/MSFT × 五 orderbook venues
   - `bstock`：QQQ/SPCX/NVDA × Binance spot + Pancake BSC + Tessera BSC
   - `ondo`：NVDA × Pancake BSC + Tessera BSC（无 Binance spot）
3. **Catalogued but not yet live-quoted（标 unverified / 可挂 `no_quote`，不得静默删除）**：
   - `xstock`（Solana mint：NVDAx / TSLAx / …）
   - `xstock_cex`（Bybit `*X` spot：NVDAX / TSLAX / SPCXX…）
4. Solana prop AMM 对 xStocks 仍无路由（2026-08-03）——`xstock` 的 prop 列为 ⛔，不整 form 删除。

### 1.3 Others（高成交量交集）— **prop AMM 把交集压成 blue-chip 级**

WHI-797 live：prop AMM 直连实质只有 **SOL/稳定币 + USDC/cbBTC + USDC/WETH**（HumidiFi 另有 USDC/JUP）。**Memecoin / 多数 L1 mid-cap 不在 prop AMM 直连接**。

因此：

| 口径 | 结果 |
| --- | --- |
| **含 prop AMM 的全 venue 交集** | ≈ 仅 blue chips（BTC/ETH/SOL 表示层）→ Others section **几乎无可增量资产** |
| **不含 prop AMM：CEX + Perp DEX 交集** | 宽：`DOGE, WIF, XRP, BNB, AVAX, LINK, SUI, ADA, 1000PEPE/kPEPE, 1000BONK/kBONK, …` |
| **高波动 meme 注意** | 合约乘数差异：`PEPE` vs `1000PEPE` / HL `kPEPE`；`BONK` 同理 |

**推荐 Others P0（CEX + 三家 Perp DEX，不依赖 prop AMM）**：`DOGE`, `WIF`, `XRP`, `SUI`, `LINK`, `AVAX`, `ADA`, `BNB`。  
**P1（须做 1000× / `k` 前缀缩放对齐）**：`PEPE` 族、`BONK` 族。  
**P2 观察仓**：`JUP`（prop 仅 HumidiFi）、`PUMP`, `FARTCOIN`, `HYPE`（HL/部分 venue 特有或权重极不均，不进严格交集）。

**v2 增量**：Tessera 的 Base 部署给 Others 添了三个 prop-AMM 可报价资产——`AERO`、`VIRTUAL`、`EURC`（均 vs USDC，WHI-797 §7.4）。其中 AERO/VIRTUAL 在 CEX + Perp DEX 也广泛在架，可入 P2 观察仓做「CEX vs Base prop AMM」对比。

---

## 2. 调研范围与「在架」口径

### 2.1 Venue 范围（与 sibling issues 对齐）

| Class | Venues |
| --- | --- |
| CEX | Binance, Bybit |
| Perp DEX | Hyperliquid（主簿 + HIP-3 `xyz` 等）、Lighter、ApeX Omni |
| AMM DEX | Uniswap（Ethereum）、Aerodrome（Base）、PancakeSwap（BSC） |
| Prop AMM | HumidiFi / TesseraV / BisonFi（Solana via Jupiter）+ **Tessera（Base、BSC via KyberSwap，v2 新增）**——名单、label 与报价路径以 WHI-797 v2 为准 |

### 2.2 「Present on venue」定义

| Venue class | Present 含义 |
| --- | --- |
| CEX | 公网 `exchangeInfo` / instruments 中 **status=TRADING** 的 spot 或 USDT 永续 |
| Perp DEX | 公网 meta / orderBooks / symbols 中 **可交易** 的永续（HL 含 `dex=xyz` HIP-3） |
| AMM DEX | 该链上 **canonical 包装资产** 有主流 USDC/USDT 池可报价（本调研记录地址；**未**逐池 depth 审计） |
| Prop AMM | Solana：Jupiter `dexes=<Label>` + `onlyDirectRoutes=true` 有路由（复用 WHI-797 §6）；Base/BSC：KyberSwap `includedSources=tessera` 有直连路由（复用 WHI-797 §7.4） |

**非 present**：仅有 prediction/事件合约、已 `isDelisted`、`enableTrade=false`、或假冒同名 mint。

### 2.3 数据源（live 2026-08-03 UTC）

| Venue | Endpoint / 来源 |
| --- | --- |
| Binance spot | `GET https://api.binance.com/api/v3/exchangeInfo` + `ticker/24hr` |
| Binance USDT-M | `GET https://fapi.binance.com/fapi/v1/exchangeInfo`（含 `TRADIFI_PERPETUAL`） |
| Bybit | `GET https://api.bybit.com/v5/market/instruments-info?category=spot\|linear` |
| Hyperliquid | `POST https://api.hyperliquid.xyz/info` — `meta`, `metaAndAssetCtxs`, `perpDexs`, `meta&dex=xyz`, `spotMeta` |
| Lighter | `GET https://mainnet.zklighter.elliot.ai/api/v1/orderBooks` + `orderBookDetails` |
| ApeX Omni | `GET https://omni.apex.exchange/api/v3/symbols`（`perpetualContract` / `stockContract`） |
| Solana xStocks mints | `GET https://lite-api.jup.ag/tokens/v2/search?query=…`（取 Backed `Xs…` mint + 合理 liq/holders） |
| Prop AMM | [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md) §5–§7 + samples（Solana `asset-matrix.tsv`、EVM `WHI-797-tessera-evm-matrix.tsv`） |
| EVM 包装资产 | 链上 canonical 地址（业界标准；**未**发明新地址） |
| Tokenized stocks 成交量（v2） | CoinGecko tokenized-stock 分类 + GeckoTerminal 池级 API（`api.geckoterminal.com/api/v2/search/pools`）+ rwa.xyz stocks dashboard |
| Tessera EVM 报价（v2） | KyberSwap `GET /{base\|bsc}/api/v1/routes?includedSources=tessera`（live 探测） |

---

## 3. Section A — Crypto blue chips

### 3.1 覆盖矩阵（是否可交易）

图例：✅ 有主市场 · ⚠️ 仅桥接/包装或无该 venue 的主路径 · ❌ 无

| 资产 | Binance spot | Binance perp | Bybit spot | Bybit perp | HL perp | HL spot | Lighter | ApeX | Prop AMM (SOL) | Uniswap (ETH) | Aerodrome (Base) | Pancake (BSC) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTC | ✅ `BTCUSDT` | ✅ `BTCUSDT` | ✅ | ✅ `BTCUSDT` | ✅ `BTC` | ✅ `UBTC` | ✅ `BTC` | ✅ `BTC-USDT` | ✅ **cbBTC**/USDC | ✅ **WBTC**/WETH | ✅ **cbBTC**/WETH | ✅ **BTCB** |
| ETH | ✅ `ETHUSDT` | ✅ `ETHUSDT` | ✅ | ✅ `ETHUSDT` | ✅ `ETH` | ✅ `UETH` | ✅ `ETH` | ✅ `ETH-USDT` | ✅ **WETH**/USDC | ✅ **WETH** | ✅ **WETH** | ✅ 桥接 ETH |
| SOL | ✅ `SOLUSDT` | ✅ `SOLUSDT` | ✅ | ✅ `SOLUSDT` | ✅ `SOL` | ✅ `USOL` | ✅ `SOL` | ✅ `SOL-USDT` | ✅ **SOL**/USDC | ⚠️ 无主市场 | ⚠️ 无主市场 | ⚠️ 无主市场 |

> **v2**：Prop AMM 列不再只有 Solana——Tessera 在 **Base**（cbBTC/USDC、WETH/USDC 直连）与 **BSC**(BTCB/USDT 直连) 也能报 BTC/ETH（KyberSwap `includedSources=tessera`，见 WHI-797 §7.4）。即 BTC 的 prop AMM 报价点 = Solana cbBTC + Base cbBTC + BSC BTCB；ETH = Solana WETH(Wormhole) + Base WETH。SOL 仍仅 Solana。

### 3.2 分 venue 合约 / 交易形式（精确 instrument）

#### CEX

| 资产 | Binance spot | Binance USDT-M perp | Bybit spot | Bybit linear perp |
| --- | --- | --- | --- | --- |
| BTC | `BTCUSDT` | `BTCUSDT` PERPETUAL | `BTCUSDT` | `BTCUSDT`（另有 `BTCPERP`） |
| ETH | `ETHUSDT` | `ETHUSDT` | `ETHUSDT` | `ETHUSDT` / `ETHPERP` |
| SOL | `SOLUSDT` | `SOLUSDT` | `SOLUSDT` | `SOLUSDT` / `SOLPERP` |

#### Perp DEX

| 资产 | Hyperliquid | Lighter | ApeX Omni |
| --- | --- | --- | --- |
| BTC | perp name `BTC`（主 dex `meta`）；spot token `UBTC` pair `@142` ≈ UBTC/USDC | `BTC` perp | `BTC-USDT` / cross `BTCUSDT` |
| ETH | `ETH`；spot `UETH` | `ETH`（另有 `ETH/USDC` spot-like 符号，以 orderBooks 为准） | `ETH-USDT` |
| SOL | `SOL`；spot `USOL` | `SOL` | `SOL-USDT` |

#### Prop AMM（Solana / Jupiter）— 复用 WHI-797

| 逻辑资产 | 表示 | Mint | 三家直连（onlyDirect） |
| --- | --- | --- | --- |
| SOL | wSOL | `So11111111111111111111111111111111111111112` | ✅ SOL↔USDC（三家） |
| BTC | **cbBTC**（非 WBTC） | `cbbtcf3aa214zXHbiAZQwf4122FBYbraNdFqgw4iMij` | ✅ USDC↔cbBTC（三家）；SOL↔cbBTC 仅多跳 |
| ETH | **Wormhole WETH** | `7vfCXTUXx5WJV5JADk17DUJ4ksgau7utNKj4b963voxs` | ✅ USDC↔WETH（三家） |

USDC mint：`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`。

#### AMM DEX — canonical 包装（对比时需按链选地址）

| 链 / Venue | BTC 表示 | ETH 表示 | USD 稳定币（常用） |
| --- | --- | --- | --- |
| Ethereum / Uniswap | WBTC `0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599` | WETH `0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2` | USDC `0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48` |
| Base / Aerodrome | cbBTC `0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf` | WETH `0x4200000000000000000000000000000000000006` | USDC `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| BSC / PancakeSwap | BTCB `0x7130d2A12B9BCbFAe4f2634d864A1Ee1Ce3Ead9c` | ETH `0x2170Ed0880ac9A755fd29B2688956BD959F933F8` | USDT `0x55d398326f99059fF775485246999027B3197955` |

> 池地址会随 fee tier 变化；M2 adapter 应用「token in/out」解析，不要写死单一 pool。

### 3.3 表示映射（产品层 logical asset → venue instrument）

| Logical | Binance | Bybit | HL perp | HL Unit spot | Lighter | ApeX | Prop AMM | Uniswap | Aerodrome | Pancake |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTC | `BTCUSDT` s/p | `BTCUSDT` s/p | `BTC` | `UBTC` | `BTC` | `BTC-USDT` | `cbBTC` | `WBTC` | `cbBTC` | `BTCB` |
| ETH | `ETHUSDT` s/p | `ETHUSDT` s/p | `ETH` | `UETH` | `ETH` | `ETH-USDT` | Wormhole `WETH` | `WETH` | `WETH` | BSC `ETH` |
| SOL | `SOLUSDT` s/p | `SOLUSDT` s/p | `SOL` | `USOL` | `SOL` | `SOL-USDT` | wSOL | — | — | — |

**风险**：`cbBTC` ≠ `WBTC` ≠ `BTCB` ≠ `UBTC` — 脱锚/桥风险不同；价差 dashboard 应显示 **表示标签**，并在文档声明「同一 logical BTC 的跨包装基差」。

### 3.4 推荐 Blue chips section 列表

| 优先级 | Logical | 对比 venue 集合 | 备注 |
| --- | --- | --- | --- |
| **P0** | BTC | 全 class（AMM 用各链包装） | 核心 |
| **P0** | ETH | 全 class | 核心 |
| **P0** | SOL | CEX + Perp DEX + Prop AMM | **不含** EVM AMM |
| P1 | BTC-ETH 交叉 | 可选 | 非必须 |

---

## 4. Section B — Stocks（v2 asset-first 重做）

### 4.0 方法

v1 从「预设 venue 集合的交集」出发，交集为空即降级——被本次重做推翻。v2 流程：

1. **资产先行**：按链上成交量列全 tokenized stocks（不限发行形式、不限链）→ §4.2 top 榜
2. **逐资产扫 venue**：对每个上榜 underlying，逐一检查本产品 venue 集合内的支持情况，**有交易对就纳入**（不因不在交集而丢弃）→ §4.3 矩阵
3. equity perps 作为同一 underlying 的补充路径并列记录（与 tokenized 现货分开标注）→ §4.4

### 4.1 发行家族总览（2026-08 在市）

| 家族 | 发行方 / 模式 | 链 | 命名 | 备注 |
| --- | --- | --- | --- | --- |
| **bStocks** | BTech Holdings（Binance 系），ADGM FSRA 批准；Alpaca 托管清算 | **BNB Chain** | `TSLAB`、`QQQB`（B 后缀） | 2026-06-12 上线；法律形式为 1:1 Certificate；rebase 处理分红/拆股；**当前链上成交量第一家族** |
| **xStocks** | Backed Finance（Kraken 收购中），1:1 托管 | Solana 为主（另有 ETH/TON/BNB 等） | `TSLAx`（小写 x 后缀）；Solana mint `Xs…` 前缀 | ~74 资产在 Solana；Bybit 现货挂 `*X` |
| **Ondo Stocks**（原 Ondo GM） | Ondo Finance，US broker-dealer 托管 | Ethereum、BNB Chain、Solana | `TSLAon`（on 后缀） | 430+ 资产；TVL 口径市占最高 |
| Backpack Securities | Backpack 券商 + Wormhole Sunrise | Solana | 裸 ticker（`SPCX`、`SKHY`） | IPO 当日代币化（SpaceX/SK Hynix/SanDisk） |
| Dinari dShares | SEC transfer agent + FINRA BD | Arbitrum 为主、ETH、Base、Polygon 等 | `AAPL.d` | 真实股份所有权；主要不在本产品 venue 集合内 |
| Robinhood Stock Tokens | Robinhood（Jersey），债权凭证 | Robinhood Chain（Arbitrum L2） | 裸 ticker | 链不在本产品 venue 集合内 |
| Bitget rToken | Reality Protocol | Arbitrum、Morph | `rNVDA` | 同上，观察 |
| PreStocks / Jarsy 等 pre-IPO SPV | 第三方 SPV，**非发行方授权** | Solana | `SPACEX`、`OPENAI` | SEC 2026-01 点名风险；**排除** |

### 4.2 链上成交量 Top 榜（快照 2026-08-03，CoinGecko tokenized-stock 分类 24h + GeckoTerminal 池级数据）

| # | Token | Underlying | 家族/链 | 24h 链上成交 |
| --- | --- | --- | --- | --- |
| 1 | SPCXB | SpaceX | bStocks / BSC | $22.9M |
| 2 | QQQB | Invesco QQQ | bStocks / BSC | ~$23M（Pancake 池级；CoinGecko 分类页未列全） |
| 3 | NVDAB | NVIDIA | bStocks / BSC | $19.4M（另 Pancake QQQB 口径 $12.2M/池） |
| 4 | SKHYB | SK Hynix | bStocks / BSC | $18.7M |
| 5 | MUB | Micron | bStocks / BSC | $15.9M |
| 6 | SNDKB | SanDisk | bStocks / BSC | $13.7M |
| 7 | SKHY | SK Hynix | Backpack / Solana | $5.2M |
| 8 | CRCLB | Circle | bStocks / BSC | $4.5M |
| 9 | TSLAB | Tesla | bStocks / BSC | $4.1M |
| 10 | TSLAx | Tesla | xStocks / Solana | $3.2M |
| 11 | NVDAx | NVIDIA | xStocks / Solana | $2.9M |
| 12 | AMZNx | Amazon | xStocks / Solana | $2.9M |
| 13 | NBISB | Nebius | bStocks / BSC | $2.7M |
| 14 | AAPLx | Apple | xStocks / Solana | $2.7M |
| 15 | MUon | Micron | Ondo / 多链 | $2.2M |
| 16 | CRCLx | Circle | xStocks / Solana | $2.1M |
| 17 | GOOGLon | Alphabet | Ondo / 多链 | $1.8M |
| 18 | GOOGLx / COINx / SPCXx | — | xStocks / Solana | $1.7M 各 |
| 19 | NVDAon / TSLAon / NBISon | — | Ondo / 多链 | $1.4–1.6M 各 |
| 20 | METAx | Meta | xStocks / Solana | $1.2M |

主题：成交集中在 **AI/半导体（NVDA、MU、SNDK、SKHY、NBIS）+ SpaceX + Tesla + Circle + QQQ**；同一 underlying 普遍有 3–4 个表示（SK Hynix 四重：SKHYB/SKHY/SKHYx/SKHYon，均 2026-07-10 IPO 日发行）。榜单会快速轮动（bStocks 上线不足 2 月即登顶），清单需周期性重扫。

### 4.3 逐资产 venue 支持矩阵（tokenized 现货，live 验证 2026-08-03）

图例：✅ live 验证有交易对 · ⛔ live 验证无 · ─ 不适用。venue 集合 = §2.1。
（Binance spot = `*B`USDT 符号 status TRADING；Pancake = GeckoTerminal 有活跃 v3 池；Tessera BSC = KyberSwap `includedSources=tessera` 有直连报价；Bybit spot = `*X`USDT Trading；Sol xStocks mint 见 v1 数据 + samples TSV）

| Underlying | bStocks (BSC) | Binance spot | Pancake v3 | **Tessera BSC (prop)** | Ondo 表示 | Uniswap (ETH) | Bybit spot xStock | Solana xStocks mint | Sol prop AMM |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Invesco QQQ | QQQB | ✅ | ✅（24h ~$23M） | **✅ 直连** | — | ⛔ | ⛔ | QQQx `Xs8S…WHZ` | ⛔ |
| SpaceX | SPCXB | ✅ | ✅（~$10M） | **✅ 直连** | — | ⛔ | ✅ `SPCXXUSDT` | SPCXx | ⛔ |
| NVIDIA | NVDAB | ✅ | ✅（~$12M） | **✅ 直连** | NVDAon（BSC/ETH/Sol） | ✅ NVDAon 池 | ✅ `NVDAXUSDT` | NVDAx `Xsc9…qEh` | ⛔（复测） |
| SK Hynix | SKHYB | ✅ | ✅ | ⛔（4000） | SKHYon | ⛔ | ⛔ | SKHYx | ⛔ |
| Micron | MUB | ✅ | ✅ | ⛔ | MUon | 未验证 | ⛔ | — | ⛔ |
| SanDisk | SNDKB | ✅ | ✅ | ⛔ | SNDKon | ⛔ | ⛔ | SNDK（Backpack） | ⛔ |
| Tesla | TSLAB | ✅ | ✅ | ⛔ | TSLAon | 未验证 | ✅ `TSLAXUSDT` | TSLAx `XsDo…zoB` | ⛔（复测） |
| Circle | CRCLB | ✅ | ✅ | ⛔ | CRCLon | 未验证 | ✅ `CRCLXUSDT` | CRCLx `Xsue…bd1` | ⛔ |
| Apple | AAPLB | ✅ | 未验证 | 未验证 | AAPLon | 未验证 | ✅ `AAPLXUSDT` | AAPLx `XsbE…zJp` | ⛔ |
| Amazon | AMZNB | ✅ | 未验证 | 未验证 | AMZNon | 未验证 | ✅ `AMZNXUSDT` | AMZNx | ⛔ |
| Alphabet | GOOGLB | ✅ | 未验证 | 未验证 | GOOGLon | 未验证 | ✅ `GOOGLXUSDT` | GOOGLx | ⛔ |
| Meta | METAB | ✅ | 未验证 | 未验证 | METAon | 未验证 | ✅ `METAXUSDT` | METAx | ⛔ |
| Coinbase | COINB | ✅ | 未验证 | 未验证 | — | 未验证 | ✅ `COINXUSDT` | COINx | ⛔ |
| Robinhood | HOODB | ✅ | 未验证 | 未验证 | — | 未验证 | ✅ `HOODXUSDT` | HOODx | ⛔ |
| Strategy (MSTR) | MSTRB | ✅ | 未验证 | 未验证 | — | 未验证 | ⛔ | MSTRx `XsP7…xyZ` | ⛔ |
| Microsoft | MSFTB | ✅ | 未验证 | 未验证 | — | 未验证 | ⛔ | MSFTx `Xspz…RMX` | ⛔ |
| SPDR S&P 500 | SPYB | ✅ | 未验证 | 未验证 | SPYon | 未验证 | ⛔ | SPYx `XsoC…F2W` | ⛔ |
| Nebius | NBISB | ✅ | ✅ | 未验证 | NBISon | 未验证 | ⛔ | — | ⛔ |
| McDonald's | MCDB？ | 未验证 | 未验证 | 未验证 | — | 未验证 | ✅ `MCDXUSDT` | MCDx | ⛔ |

关键读法：

- **QQQB / SPCXB / NVDAB 一行三绿（Binance spot + Pancake + Tessera）**——同一资产、同一链、三个 venue class，可直接做 CEX vs AMM vs prop AMM 价差；NVIDIA 还叠加 Ondo/xStocks 跨发行方基差。
- Tessera BSC 对 bStocks 的覆盖是**子集**（QQQB/SPCXB/NVDAB/NVDAon ✅；TSLAB/SKHYB/SNDKB/MUB ⛔，KyberSwap 返回 4000）——池集随 Wintermute 库存策略变动，需周期性重扫（WHI-797 §7.4）。
- 「未验证」= 本轮未逐一 live 打（Binance `*B` 18 个符号全部验证 TRADING；Pancake 只验证了 top 7 的池；Ondo 在 Uniswap 只验证 NVDAon）。M2 adapter 起步资产集不受影响（P0 三资产全绿）。
- Solana 侧：xStocks mint 与 Bybit `*X`（11 个 Trading，含新增 SPCXX/MCDX）沿用 v1 live 数据；三家 Solana prop AMM 对 TSLAx/NVDAx 复测仍无路由。

### 4.4 Equity perps（补充路径，沿用 v1 live 数据，同日快照仍有效）

| Underlying | Binance TradFi | Bybit perp | HL `xyz:` | Lighter | ApeX |
| --- | --- | --- | --- | --- | --- |
| TSLA / AAPL / NVDA / MSFT / AMZN / GOOGL / META / COIN / HOOD / MSTR | ✅ | ✅ | ✅ | ✅ | ✅ |
| PLTR / CRCL | ✅ | ✅ | ✅ | ✅ | ✅ |
| AMD | ✅ | ✅ `AMDSTOCKUSDT`（非常规命名） | ✅ | ✅ | ✅ |
| SPY / QQQ | ✅ | ✅ | ⚠️ proxy-only（`xyz:SP500` / `xyz:XYZ100`，无 exact） | ✅ | ✅ |

注意：HL `flx:` 等子 dex 大量 delist，白名单仅 `xyz` + 主簿（同 v1）。**QQQ 的 tokenized 现货（QQQB）与 QQQ perp 可做「现货 vs 永续」跨形态基差**——v1 无此路径。

### 4.5 Stocks section 推荐方案（v2）

| 优先级 | 方案 | 资产 | Venue 集合 |
| --- | --- | --- | --- |
| **P0-A（新增，最高）** | bStocks 三方价差（CEX spot × AMM × prop AMM，全在 BSC） | **QQQB、SPCXB、NVDAB** | Binance spot + PancakeSwap v3 + Tessera（KyberSwap `includedSources=tessera`） |
| **P0-B（沿用）** | Equity-perp 五 venue exact-ticker | TSLA、NVDA、AAPL、MSFT | BN TradFi + BY + HL `xyz:` + Lighter + ApeX |
| **P1** | 跨发行方基差（同 underlying 不同表示） | NVDA（NVDAB/NVDAx/NVDAon）、TSLA（TSLAB/TSLAx/TSLAon） | 各表示所在 venue |
| **P1** | xStocks 路径 | TSLAx、NVDAx、AAPLx、CRCLx… | Bybit `*X` spot + Solana（Jupiter 公共 DEX；无 prop） |
| **P1-lite** | ETF：tokenized vs perp 跨形态 | QQQ（QQQB ↔ QQQ perp）、SPY（SPYB ↔ SPY perp） | BSC 三方 + BN/BY/Lighter/ApeX perp；HL 仅 proxy |
| **P2** | 扩展 mega-cap | AMZN、GOOGL、META、COIN、HOOD、MSTR、CRCL、PLTR、AMD | 视表示可用性 |
| **排除** | pre-IPO SPV（PreStocks 等） | — | 非发行方授权，SEC 点名 |

**对 WHI-810 的直接影响**：v1 交接语「prop 不在架、tokenized 不含 Binance `*B`」作废；新 P0 以 bStocks 三方对比为核心，配套需要 KyberSwap adapter（与 WHI-806 共用）。

### 4.6 Form 分类法与稳定 id（v3 / WHI-880）

SSOT 落地位置：`spread_compare/assets.py`（实现 issue [WHI-881](https://linear.app/whisker-personal/issue/WHI-881)）。本表是 **form 词汇表**——新增发行家族时只允许扩展此表，禁止为同一 form 发明别名。

| `form` id（稳定） | 发行家族 / 含义 | 典型命名 | 默认 `instrument_type`（venue 可覆盖） | 常见 venues |
| --- | --- | --- | --- | --- |
| `perp` | Exact-ticker 股票/ETF 永续 | `NVDAUSDT`、`xyz:NVDA` | `perp` | `binance`, `bybit`, `hyperliquid`, `lighter`, `apex` |
| `bstock` | bStocks（BTech / Binance 系，BSC） | `NVDAB`、`QQQB`、`SPCXB` | `spot`（CEX）/ `amm_pool` / `prop_amm` | `binance` spot、`pancakeswap_bsc`、`tessera_bsc` |
| `ondo` | Ondo Stocks | `NVDAon` | `amm_pool` / `prop_amm`（CEX 现货常无） | `pancakeswap_bsc`、`tessera_bsc`；（ETH Uniswap 可选） |
| `xstock` | Backed xStocks **链上 mint**（主 Solana） | `NVDAx` mint `Xs…` | `amm_pool`（公共 DEX）；prop 当前 ⛔ | Solana AMM / 未来 prop |
| `xstock_cex` | xStocks **CEX 现货**（Bybit `*X`） | `NVDAXUSDT` | `spot` | `bybit` spot |

**Form class**（用于 §5.2 best 分组，见 WHI-799 §5.2 v3）：

| `form_class` | 包含 form | 暴露性质 |
| --- | --- | --- |
| `perp` | `perp` | 资金费率 + 保证金；无托管正股/证书 |
| `tokenized` | `bstock`, `ondo`, `xstock`, `xstock_cex` | 托管 / 证书 / 1:1 包装现货；无 funding |

**规则**：

1. `form` 是稳定 slug（小写 snake）；**不是** display label（label 仍走 `representations[venue]`）。
2. 一个 `(venue, asset)` **可以**挂多个 form（`tessera_bsc` + `NVDA` → `bstock` 与 `ondo` 两行）。
3. 未 live 验证的 form **仍写入 catalog**，`status`/`coverage` 用 `unverified` 或报价 `no_quote`——**禁止**因「暂不对比」而从 inventory 删除。
4. Crypto blue chips / Others **不**强制 `form` 字段（隐式单 form；实现可省略或 null）——行为不变。

**Legacy asset id 映射（breaking rename，pre-v1）**：

| 旧 catalog id（废除） | 新 `asset` | 新 `form` |
| --- | --- | --- |
| `NVDAB` | `NVDA` | `bstock` |
| `NVDAON` | `NVDA` | `ondo` |
| `QQQB` | `QQQ` | `bstock` |
| `SPCXB` | `SPCX` | `bstock` |
| `TSLA` / `NVDA` / `AAPL` / `MSFT`（旧 category=`equity_perp`） | 同 id | `perp`（保留 underlying id；category 改为 `stock`） |

旧 id **不再**作为 top-level asset；API 对旧 id 返回错误 + 迁移提示（WHI-799 §6.7）。**不做**静默 alias 双写。

---

## 5. Section C — Others

### 5.1 快照方法

| 源 | 指标 | 日期 |
| --- | --- | --- |
| Binance spot `ticker/24hr` | `quoteVolume` USDT 对 | 2026-08-03 |
| HL `metaAndAssetCtxs` | `dayNtlVlm` | 2026-08-03 |
| Lighter `orderBookDetails` | `daily_quote_token_volume` | 2026-08-03 |
| Prop AMM | WHI-797 直连矩阵 | 2026-08-03 |

成交量排名 **会变**；Others 清单应季度复核或挂「滚动 top-N ∩ 白名单」。

### 5.2 Prop AMM 对 Others 的硬约束（WHI-797）

| Pair | HumidiFi | TesseraV | BisonFi |
| --- | --- | --- | --- |
| SOL/USDC | ✅ | ✅ | ✅ |
| USDC/cbBTC | ✅ | ✅ | ✅ |
| USDC/WETH | ✅ | ✅ | ✅ |
| USDC/JUP | ✅ | ❌ | ❌ |
| WIF / BONK / POPCAT / 等 meme | ❌ | ❌ | ❌ |
| mSOL / JitoSOL / 中盘 | ❌ | ❌ | ❌ |

→ **凡进入「含 prop AMM 的 Others」候选，今日快照下可增量资产 ≈ 0**（JUP 仅 HumidiFi，不算三家交集）。

### 5.3 CEX + Perp DEX 宽交集（推荐 Others 主池）

下列在 **Binance + Bybit（spot 与/或 perp）+ HL 主簿 + Lighter + ApeX** 均观测到可交易符号（乘数名可能不同）：

| Logical | Binance | Bybit | HL | Lighter | ApeX | Prop AMM |
| --- | --- | --- | --- | --- | --- | --- |
| DOGE | ✅ | ✅ | ✅ `DOGE` | ✅ | ✅ | ❌ |
| WIF | ✅ | ✅ | ✅ `WIF` | ✅ | ✅ | ❌ |
| XRP | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| BNB | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| AVAX | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| LINK | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| SUI | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| ADA | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| PEPE 族 | spot `PEPEUSDT`；perp **`1000PEPEUSDT`** | 同 **`1000PEPE`** | **`kPEPE`** | **`1000PEPE`** | **`1000PEPE-USDT`** | ❌ |
| BONK 族 | spot `BONK`；perp **`1000BONK`** | **`1000BONK`** | **`kBONK`** | **`1000BONK`** | **`1000BONK-USDT`** | ❌ |
| JUP | ✅ | ✅ | ✅ `JUP` | ✅ `JUP` | ✅ `JUP-USDT` | 仅 HumidiFi USDC/JUP |

### 5.4 高量但非严格交集（观察）

| 资产 | 现象 | 建议 |
| --- | --- | --- |
| HYPE | HL 现货/永续核心；他 venue 覆盖不均 | P2 / 标注 HL-centric |
| PUMP | HL 等高量 | 可选 meme 观察 |
| FARTCOIN | 多所出现但波动/上币策略不一 | 观察 |
| ZEC / ENA / KAITO | 某日 top 量 | 勿写死进 P0 |

### 5.5 Others 推荐列表

| 优先级 | 资产 | Venue 范围 | 说明 |
| --- | --- | --- | --- |
| **P0** | DOGE, WIF, XRP, SUI, LINK | CEX + 三 Perp DEX | 流动性与覆盖均衡 |
| **P0** | AVAX, ADA, BNB | 同上 | L1/大盘 |
| **P1** | PEPE 族, BONK 族 | 同上 | **必须做 1000× / k 前缀缩放对齐** |
| **P2** | JUP | CEX + HL + Lighter + ApeX；prop **仅 HumidiFi** | 非三家 prop 交集 |
| **排除（Phase 1）** | 依赖 prop AMM 的 meme 对比 | — | 无路由 |

---

## 6. 全量资产 × Venue 覆盖矩阵（汇总）

> 完整机器可读表见 [`samples/WHI-798-asset-venue-matrix.tsv`](./samples/WHI-798-asset-venue-matrix.tsv)。  
> 下表为 dashboard 决策用压缩版。符号列为 **代表性 instrument**（非穷尽）。

### 6.1 Blue chips

| Logical | Binance | Bybit | HL | Lighter | ApeX | PropAMM | Uni | Aero | Cake |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTC | BTCUSDT s+p | BTCUSDT s+p | BTC / UBTC | BTC | BTC-USDT | cbBTC | WBTC | cbBTC | BTCB |
| ETH | ETHUSDT s+p | ETHUSDT s+p | ETH / UETH | ETH | ETH-USDT | WETH (Wormhole) | WETH | WETH | ETH |
| SOL | SOLUSDT s+p | SOLUSDT s+p | SOL / USOL | SOL | SOL-USDT | wSOL | — | — | — |

### 6.2 Stocks（v3：underlying × form × venue）

> v2 的「P0-A 独立 tokenized 资产 id + P0-B equity_perp 资产 id」作废为 **catalog 形状**；venue 覆盖事实不变。  
> 行 = `(asset, form, venue)`；`instrument_type` 由 form 默认值或 venue 覆盖（WHI-799 §6.2）。  
> 图例：✅ live 已报价路径 · 📌 catalogued / unverified（勿静默删除）· ⛔ live 验证无 · — 不适用。

#### 6.2.1 Phase-1 underlyings（当前产品行，不含新增 ticker）

| asset | form | form_class | binance | bybit | hyperliquid | lighter | apex | pancakeswap_bsc | tessera_bsc | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **NVDA** | `perp` | perp | ✅ NVDAUSDT p | ✅ NVDAUSDT p | ✅ xyz:NVDA | ✅ NVDA | ✅ NVDA-USDT | — | — | 五 venue exact-ticker |
| **NVDA** | `bstock` | tokenized | ✅ NVDABUSDT s | — | — | — | — | ✅ NVDAB | ✅ NVDAB | BSC 三方闭环 |
| **NVDA** | `ondo` | tokenized | — | — | — | — | — | ✅ NVDAon | ✅ NVDAon | 无 Binance spot |
| **NVDA** | `xstock_cex` | tokenized | — | 📌 NVDAXUSDT s | — | — | — | — | — | catalogued；Bybit live 符号已确认 |
| **NVDA** | `xstock` | tokenized | — | — | — | — | — | — | — | 📌 Sol mint NVDAx；Sol prop ⛔ |
| **TSLA** | `perp` | perp | ✅ | ✅ | ✅ xyz:TSLA | ✅ | ✅ | — | — | |
| **TSLA** | `bstock` | tokenized | 📌 TSLABUSDT | — | — | — | — | 📌 TSLAB | ⛔ Tessera 无池 | P1 扩展 |
| **TSLA** | `xstock_cex` | tokenized | — | 📌 TSLAXUSDT | — | — | — | — | — | |
| **TSLA** | `xstock` | tokenized | — | — | — | — | — | — | — | 📌 TSLAx mint；Sol prop ⛔ |
| **TSLA** | `ondo` | tokenized | — | — | — | — | — | 📌 | 📌 | 未逐池 live 钉死 |
| **AAPL** | `perp` | perp | ✅ | ✅ | ✅ xyz:AAPL | ✅ | ✅ | — | — | |
| **AAPL** | `xstock_cex` | tokenized | — | 📌 AAPLXUSDT | — | — | — | — | — | |
| **AAPL** | `xstock` | tokenized | — | — | — | — | — | — | — | 📌 AAPLx mint |
| **MSFT** | `perp` | perp | ✅ | ✅ | ✅ xyz:MSFT | ✅ | ✅ | — | — | |
| **MSFT** | `xstock` | tokenized | — | — | — | — | — | — | — | 📌 MSFTx mint；无 Bybit `*X` |
| **QQQ** | `bstock` | tokenized | ✅ QQQBUSDT s | — | — | — | — | ✅ QQQB | ✅ QQQB | 旧 id `QQQB` |
| **QQQ** | `perp` | perp | 📌 QQQUSDT p | 📌 | ⛔ proxy-only xyz:XYZ100 | 📌 | 📌 | — | — | HL **禁止**假装 exact `xyz:QQQ` |
| **QQQ** | `xstock` | tokenized | — | — | — | — | — | — | — | 📌 QQQx mint |
| **SPCX** | `bstock` | tokenized | ✅ SPCXBUSDT s | — | — | — | — | ✅ SPCXB | ✅ SPCXB | 旧 id `SPCXB`；**无公开 equity ref** |
| **SPCX** | `xstock_cex` | tokenized | — | 📌 SPCXXUSDT | — | — | — | — | — | |
| **SPCX** | `xstock` | tokenized | — | — | — | — | — | — | — | 📌 SPCXx mint |
| **SPCX** | `perp` | perp | — | — | — | — | — | — | — | ⛔ 无私募 SpaceX exact perp（当前 venue 集） |

**读法**：

- 产品问题「NVIDIA 暴露在我的 size 上哪里最便宜」→ 查 `asset=NVDA` 一次，拿回所有 form 行，**共用一个 mid**（WHI-799 §3.3 v3）。
- `tessera_bsc` 对 NVDA 贡献 **两行**（`bstock` + `ondo`），不再需要两个 logical asset id。
- SPCX **没有** TradFi index / equity perp 中位数可用 → mid 固定走 bstock CEX TOB 链（WHI-799 §3.3.1）。

#### 6.2.2 旧表对照（v2 兼容阅读）

v2 的「P0-A tokenized 三方」= 上表 `QQQ/SPCX/NVDA` × `bstock`（+ `NVDA` × `ondo`）。  
v2 的「P0-B equity-perp」= 上表 `TSLA/NVDA/AAPL/MSFT` × `perp`。

### 6.3 Others（P0 压缩 — 与 §7.3 一致）

| Logical | BN | BY | HL | Lighter | ApeX | PropAMM |
| --- | --- | --- | --- | --- | --- | --- |
| DOGE | ✅ | ✅ | DOGE | DOGE | DOGE-USDT | — |
| WIF | ✅ | ✅ | WIF | WIF | WIF-USDT | — |
| XRP | ✅ | ✅ | XRP | XRP | XRP-USDT | — |
| SUI | ✅ | ✅ | SUI | SUI | SUI-USDT | — |
| LINK | ✅ | ✅ | LINK | LINK | LINK-USDT | — |
| AVAX | ✅ | ✅ | AVAX | AVAX | AVAX-USDT | — |
| ADA | ✅ | ✅ | ADA | ADA | ADA-USDT | — |
| BNB | ✅ | ✅ | BNB | BNB | BNB-USDT | — |

---

## 7. Dashboard sections 最终推荐清单

### 7.1 WHI-809 Crypto blue chips

```text
P0: BTC, ETH, SOL
```

- 报价映射严格按 §3.3。  
- SOL 行隐藏或禁用 EVM AMM 列。  
- 稳定币报价腿优先 **USDC**（perp 多为 USDT 结算 — UI 需标注 quote currency）。

### 7.2 Stocks section（v3 / WHI-880 → 实现 WHI-881 + FE 跟随 issue）

```text
Logical assets (underlyings):
  NVDA, TSLA, AAPL, MSFT, QQQ, SPCX

Live forms (Phase 1 UI / backend):
  NVDA:  perp + bstock + ondo
  TSLA:  perp
  AAPL:  perp
  MSFT:  perp
  QQQ:   bstock
  SPCX:  bstock

Catalogued-not-live (keep in catalog; quote as no_quote / unverified — do NOT drop):
  NVDA/TSLA/AAPL/… × xstock | xstock_cex
  TSLA/QQQ/… 扩展 bstock / ondo / perp 按 §6.2

P1 survey (WHI-883): 更多 high-volume underlyings，必须沿用 form 分类法
排除: pre-IPO SPV (PreStocks/Jarsy)
```

- **Dashboard 形状**：从「两个无关子板（tokenized 资产列表 vs equity_perp 资产列表）」改为 **按 underlying 一块板**，行 = venue×form（或 form 作列维度）；`frontend/src/config/sections/stocks.ts` 的 `TOKENIZED_STOCK_ASSETS` / `EQUITY_PERP_ASSETS` 拆分作废（FE 跟随后续 issue）。
- **表示标签**仍必须展示（NVDAB vs NVDAon vs xyz:NVDA），来源 `GET /assets` nested forms。
- **勿**为 SPY/QQQ 实现不存在的 `xyz:SPY` / `xyz:QQQ`。
- bStocks rebase：见 §8 Q14 + WHI-799 §3.3。

### 7.3 WHI-811 Others

```text
P0: DOGE, WIF, XRP, SUI, LINK, AVAX, ADA, BNB
P1: PEPE (scaled), BONK (scaled)
P2: JUP, venue-specific high-vol (HYPE, PUMP) — flagged
```

- 默认 **不** 对 prop AMM 拉 Others 报价（避免满屏 `NO_ROUTES_FOUND`）。  
- 若 UI 仍展示 prop 列：仅 blue-chip 行亮灯。

---

## 8. 对 M2–M3 adapter 的开放问题与风险

| ID | 问题 | 影响 |
| --- | --- | --- |
| Q1 | BTC 包装基差（cbBTC/WBTC/BTCB/UBTC）是否进入「价差」还是单独「bridge basis」指标？ | 蓝色筹对比语义 |
| Q2 | HL HIP-3 下单/查询必须带 `dex=xyz`；资产 index 与主簿隔离 | WHI-810 adapter |
| Q3 | PEPE/BONK 的 1 vs 1000 vs k 前缀归一化 | Others 价格可比性 |
| Q4 | Binance TradFi / Bybit 股票合约的合规与地区限制是否影响产品展示 | 产品/法务 |
| Q5 | xStock mint 仿盘（pump）过滤规则需固化（`Xs` 前缀 + issuer metadata） | Solana tokenized 板 |
| Q6 | Prop AMM 资产列表随 MM 库存变化；Others 不可假设静态 | 监控与告警 |
| Q7 | ApeX / Lighter 股票与加密 API 字段分裂（`stockContract` vs `perpetualContract`） | 客户端模型 |
| Q8 | Uniswap 多 fee tier 选池策略（deepest / 0.05% 等） | AMM adapter |
| Q9 | 快照日成交量 ≠ 长期可对比集合；需刷新任务 | M3 |
| Q10 | flx/vntl 等 HIP-3 子 dex 大量 delist — 白名单仅 `xyz` + 主簿 | HL 配置 |
| Q11 | Bybit AMD 符号为 `AMDSTOCKUSDT` 非常规命名 | WHI-810 symbol map |
| Q12 | SPY/QQQ 在 HL 仅 proxy（SP500/XYZ100）— 是否做指数代理对比 | WHI-810 产品语义 |
| Q13 | ~~Binance `*B` 若未来纳入，需独立 issuer/合规 scope~~ **v2 已纳入**：bStocks = BTech（Binance 系）ADGM 合规发行，为 P0-A 核心 | Tokenized（已解决） |
| Q14 | **bStocks rebase 机制**（分红/拆股按 rebase 调整余额）对价差计算的影响：rebase 当日 CEX 价与链上池价的跳变语义需对齐 | WHI-810 P0-A |
| Q15 | Tessera BSC 池集随库存策略变动（stocks 池为 2026-06 后新增），P0-A 资产需周期性可用性重扫 + 告警 | WHI-810 / 监控 |
| Q16 | BSC 上 Binance Wallet 专属订单流（~95%）不经 KyberSwap——Kyber 报价对「Tessera 实际成交价」的代表性需在 M2 用 `TesseraTrade` 事件对账验证 | 数据质量 |
| Q17（v3） | ~~同一 underlying 是否拆多 logical asset~~ **已拍板（WHI-880）**：一个 underlying = 一个 asset；form 为维度；legacy id breaking rename | WHI-881 |
| Q18（v3） | 新 form 家族（Backpack 裸 ticker、Dinari、rToken…）是否扩展 form 表 | 仅当进入本产品 venue 集时加 form id；默认 `unverified` 挂起 |

---

## 9. 参考与复用来源

- WHI-797 全文与 prop 矩阵：[`WHI-797-prop-amm-jupiter-quote-api.md`](./WHI-797-prop-amm-jupiter-quote-api.md)、[`samples/asset-matrix.tsv`](./samples/asset-matrix.tsv)
- Binance API：`/api/v3/exchangeInfo`, `/fapi/v1/exchangeInfo`, `/api/v3/ticker/24hr`
- Bybit API：`/v5/market/instruments-info`
- Hyperliquid Docs — perps info / HIP-3：`perpDexs`, `meta?dex=`
- Lighter：`mainnet.zklighter.elliot.ai/api/v1/orderBooks`
- ApeX Omni：`omni.apex.exchange/api/v3/symbols`
- Jupiter token search：`lite-api.jup.ag/tokens/v2/search`
- Backed xStocks 背景：backed.fi / Kraken xStocks 公开说明（发行与 1:1 托管模型）
- Canonical EVM 包装地址：各链标准代币合约（WBTC/WETH/cbBTC/BTCB）

**v2 新增（tokenized stocks）**：

- bStocks 上线公告（PRNewswire，2026-06-12）：https://www.prnewswire.com/news-releases/binance-exchange-launches-bstocks-tokenized-securities-11-backing-and-247-trading-302798876.html
- BNB Chain 官方 bStocks 介绍：https://www.bnbchain.org/en/blog/introducing-bstocks-on-bnb-chain-trade-24-7-with-zero-fees-deploy-across-defi-protocols-with-full-self-custody
- PancakeSwap bStocks：https://blog.pancakeswap.finance/articles/bstocks-on-pancakeswap
- Kraken：xStocks $25B 累计成交（2026-02-19）：https://blog.kraken.com/product/xstocks/25-billion-in-total-transaction-volume
- Ondo Stocks（原 Ondo GM）：https://genfinity.io/2026/07/13/ondo-global-markets-becomes-ondo-stocks-tokenized-equities-leader/
- rwa.xyz tokenized stocks dashboard：https://app.rwa.xyz/stocks （2026-08-03：总规模 ~$2.15B）
- CoinGecko tokenized-stock 分类（24h 成交快照来源）：https://www.coingecko.com/en/categories/tokenized-stock
- Tessera BSC stocks 池报价验证：WHI-797 v2 §7.4 + `samples/WHI-797-tessera-evm-matrix.tsv`

---

## 10. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-798-asset-category-inventory.md` | 本文 |
| `docs/research/samples/WHI-798-asset-venue-matrix.tsv` | 资产×venue 符号/mint 矩阵（机器可读；**v3 未强制改 TSV**——新列 `form` 随 WHI-881/扩表再版） |
| `README.md` | Research 表增加 WHI-798 行 |

---

## 12. 修订记录

| 日期 | 变更 |
| --- | --- |
| 2026-08-03 | 初版 + v2 asset-first Stocks 重做（bStocks / Tessera BSC） |
| 2026-08-06 | **v3 / WHI-880**：underlying-first；§1.2 / §4.6 form 分类法；§6.2 改为 underlying×form×venue；§7.2 与下游交接更新；legacy id breaking rename 表；Q17/Q18 |

---

## 11. 与下游 issue 的交接一句话

| Issue | 交接 |
| --- | --- |
| WHI-809 | 只做 BTC/ETH/SOL；用 §3.3 映射；SOL 不含 EVM AMM；**v2：BTC/ETH 的 prop AMM 报价点扩展到 Tessera Base/BSC** |
| WHI-810 / FE stocks | **v3**：section 以 underlying 列表驱动；forms 来自 `GET /assets`；旧 `TOKENIZED_STOCK_ASSETS`/`EQUITY_PERP_ASSETS` 双板作废（FE issue 跟 WHI-881） |
| WHI-881 | **实现** underlying-first catalog + `Quote.form` + 共享 mid + API（本文件 §4.6/§6.2 + WHI-799 §3.3/§5.2/§6 为 SSOT） |
| WHI-883 | 高成交量 stock underlying 扩表 survey — **必须**采用 §4.6 form 分类法 |
| WHI-811 | P0 八个非 meme L1/大盘；P1 缩放 meme；**不要**对 Solana prop 扫 meme；v2：Base Tessera 增量资产 AERO/VIRTUAL/EURC 可选入观察仓 |
| WHI-806 | 资产侧：Solana 三 pair 之外，**新增 Tessera EVM（KyberSwap）**：Base WETH/cbBTC/AERO/VIRTUAL/EURC vs USDC；BSC BTCB + **forms** `bstock`/`ondo` under QQQ/SPCX/NVDA vs USDT |
