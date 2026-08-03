# WHI-798：确定各资产类别的资产清单

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-798](https://linear.app/whisker-personal/issue/WHI-798/调研确定各资产类别的资产清单) |
| Milestone | M1 调研与口径定义 |
| Blocks | WHI-809（Section: Crypto blue chips）、[WHI-810](https://linear.app/whisker-personal/issue/WHI-810)（Section: Stocks）、WHI-811（Section: Others） |
| 调研日期 | 2026-08-03（UTC） |
| 方法 | 各 venue **公网 market-list API** live 探测 + 官方文档 + 复用 [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md) prop AMM 资产矩阵（**不重扫 prop AMM**） |
| 样本 | [`samples/WHI-798-asset-venue-matrix.tsv`](./samples/WHI-798-asset-venue-matrix.tsv) |

---

## 1. 结论摘要（TL;DR）

### 1.1 Crypto blue chips（BTC / ETH / SOL）— **P0 可做全 venue 对比**

| 资产 | 跨 venue 结论 | 关键表示差异 |
| --- | --- | --- |
| **BTC** | ✅ 全部 venue class 均可报价 | CEX/Perp DEX：原生 `BTC` 现货/永续；Solana prop AMM：**cbBTC**；Ethereum AMM：**WBTC** / WETH 对；Base：**cbBTC**；BSC：**BTCB**；HL spot：**UBTC** |
| **ETH** | ✅ 全部 venue class 均可报价 | CEX/Perp DEX：`ETH`；Solana prop AMM：**Wormhole WETH**；ETH/Base AMM：**WETH**；BSC：桥接 ETH；HL spot：**UETH** |
| **SOL** | ⚠️ **CEX + Perp DEX + Solana prop AMM 完整**；EVM AMM（Uniswap/Aerodrome/Pancake）**无原生 SOL 主市场**（不纳入 Phase 1 SOL 跨链 AMM 对比） | CEX/Perp：`SOL`；Solana：native / wSOL；HL spot：**USOL** |

**推荐 dashboard P0**：`BTC`、`ETH`、`SOL` 三资产；报价路径用下文 **表示映射表**（§3.3），禁止把 `cbBTC` 与 `WBTC` 当同一 mint 硬编码。

### 1.2 Stocks（tokenized stocks / equity perps）— **多 venue 有货，但「全 venue 交集」为空**

| 路径 | 覆盖 |
| --- | --- |
| Hyperliquid HIP-3 `xyz:` equity perps | ✅ 丰富（TSLA/AAPL/NVDA/MSFT/… + 指数/商品） |
| Lighter equity perps | ✅ 主流美股 + SPY/QQQ |
| ApeX `stockContract` | ✅ 主流美股 + SPY/QQQ 等 |
| Binance `TRADIFI_PERPETUAL` | ✅ 大量 TradFi 永续（含上述 mega-cap） |
| Bybit linear equity perps | ✅ 主流美股 + SPY/QQQ |
| Bybit spot xStocks | ✅ `TSLAX` / `AAPLX` / `NVDAX` 等（Backed 系） |
| Solana xStocks（Backed） | ✅ 链上 SPL Token（mint 以 `Xs…` 前缀为主） |
| Binance spot `*B` equity tokens | ⚠️ API 有 TRADING 符号（如 `TSLABUSDT`）；**Phase 1 明确排除**（见 §4.3.1）— 与 Backed xStocks 非同一发行/赎回模型 |
| Prop AMM（HumidiFi/TesseraV/BisonFi） | ❌ **无** xStocks / equity 直连（WHI-797） |
| Uniswap / Aerodrome / Pancake（本产品 scope） | ❌ **不作为 Stocks section 可比路径**（无与 xStocks/equity-perp 对齐的统一产品） |

**诚实结论**：若「交集」定义为 **同时出现在 CEX + Perp DEX + AMM DEX + Prop AMM**，Stocks **交集为空**（prop AMM 与 EVM AMM 缺席）。

**有意义的子集交集**（equity **perp** 路径，跨 Binance / Bybit / HL-xyz / Lighter / ApeX）：

> **Exact-ticker 五 venue**：`TSLA, AAPL, NVDA, MSFT, AMZN, GOOGL, META, COIN, HOOD, MSTR`（及 AMD/`AMDSTOCKUSDT`、PLTR、CRCL 等扩展）  
> **SPY / QQQ**：BN + BY + Lighter + ApeX 有 exact ticker；HL **无** `xyz:SPY`/`xyz:QQQ`，仅有指数代理 `xyz:SP500` / `xyz:XYZ100`（**proxy-only**，勿当 exact HL 路径）

**Tokenized 现货路径**（Bybit xStock spot ↔ Solana xStocks；**无 prop AMM**；**不含** Binance `*B` — 见 §4.3.1）：

> **TSLA, AAPL(AAPLx), NVDA, META, AMZN, GOOGL, COIN, HOOD, CRCL** 等（Bybit 另有 MCDX；Solana 侧 MSFT/SPY/QQQ/MSTR 等 mint 已解析，Bybit spot 列表未全覆盖）

**Phase 1 建议（二选一或并行轻量）**：

1. **推荐**：Stocks section = **equity-perp 多 venue 价差**（CEX TradFi perp + HL `xyz:` + Lighter + ApeX），**不**强求 prop AMM / EVM AMM。  
2. **备选**：Tokenized 子表 = **Bybit xStock spot vs Solana Jupiter 公共 DEX**（Raydium 等，**排除 prop AMM**；**排除 Binance `*B`**）；dashboard 标注「非 prop 路径」。  
3. **不推荐**：因 prop AMM 缺口而把 Stocks 塞进「全 venue 矩阵」同一语义。

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

---

## 2. 调研范围与「在架」口径

### 2.1 Venue 范围（与 sibling issues 对齐）

| Class | Venues |
| --- | --- |
| CEX | Binance, Bybit |
| Perp DEX | Hyperliquid（主簿 + HIP-3 `xyz` 等）、Lighter、ApeX Omni |
| AMM DEX | Uniswap（Ethereum）、Aerodrome（Base）、PancakeSwap（BSC） |
| Prop AMM（Solana via Jupiter） | HumidiFi, TesseraV, BisonFi（**名单与 label 以 WHI-797 为准**） |

### 2.2 「Present on venue」定义

| Venue class | Present 含义 |
| --- | --- |
| CEX | 公网 `exchangeInfo` / instruments 中 **status=TRADING** 的 spot 或 USDT 永续 |
| Perp DEX | 公网 meta / orderBooks / symbols 中 **可交易** 的永续（HL 含 `dex=xyz` HIP-3） |
| AMM DEX | 该链上 **canonical 包装资产** 有主流 USDC/USDT 池可报价（本调研记录地址；**未**逐池 depth 审计） |
| Prop AMM | Jupiter `dexes=<Label>` + `onlyDirectRoutes=true` 有路由（**直接复用 WHI-797 §6**） |

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
| Prop AMM | [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md) §5–§6 + [`samples/asset-matrix.tsv`](./samples/asset-matrix.tsv) |
| EVM 包装资产 | 链上 canonical 地址（业界标准；**未**发明新地址） |

---

## 3. Section A — Crypto blue chips

### 3.1 覆盖矩阵（是否可交易）

图例：✅ 有主市场 · ⚠️ 仅桥接/包装或无该 venue 的主路径 · ❌ 无

| 资产 | Binance spot | Binance perp | Bybit spot | Bybit perp | HL perp | HL spot | Lighter | ApeX | Prop AMM (SOL) | Uniswap (ETH) | Aerodrome (Base) | Pancake (BSC) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BTC | ✅ `BTCUSDT` | ✅ `BTCUSDT` | ✅ | ✅ `BTCUSDT` | ✅ `BTC` | ✅ `UBTC` | ✅ `BTC` | ✅ `BTC-USDT` | ✅ **cbBTC**/USDC | ✅ **WBTC**/WETH | ✅ **cbBTC**/WETH | ✅ **BTCB** |
| ETH | ✅ `ETHUSDT` | ✅ `ETHUSDT` | ✅ | ✅ `ETHUSDT` | ✅ `ETH` | ✅ `UETH` | ✅ `ETH` | ✅ `ETH-USDT` | ✅ **WETH**/USDC | ✅ **WETH** | ✅ **WETH** | ✅ 桥接 ETH |
| SOL | ✅ `SOLUSDT` | ✅ `SOLUSDT` | ✅ | ✅ `SOLUSDT` | ✅ `SOL` | ✅ `USOL` | ✅ `SOL` | ✅ `SOL-USDT` | ✅ **SOL**/USDC | ⚠️ 无主市场 | ⚠️ 无主市场 | ⚠️ 无主市场 |

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

## 4. Section B — Stocks

### 4.1 产品形态对照

| 形态 | 含义 | 本调研中的 venue |
| --- | --- | --- |
| **Equity perpetual** | 价格跟踪股票/ETF 的永续合约，**非**股权凭证 | Binance TradFi perp、Bybit linear、HL HIP-3 `xyz:`、Lighter、ApeX stockContract |
| **Tokenized stock (xStock)** | 1:1 托管背书的链上/ CEX 现货代币 | Bybit spot `*X`、Solana Backed xStocks（**不含** Binance `*B`，见 §4.3.1） |
| **Prop AMM / 公共 AMM 直连** | — | **基本不可用**（prop 已测无；EVM 不作为本 section 对齐路径） |

### 4.2 Hyperliquid HIP-3（`dex=xyz`，TradeXYZ）

- 列表：`POST /info` `{"type":"meta","dex":"xyz"}` → **104** 个 universe 名称（含股票、ETF、商品、FX、pre-IPO 等）。
- 调用/下单符号形态：`xyz:TSLA`（UI：`xyz:TSLA`）。
- 同日 `metaAndAssetCtxs`+`dex=xyz` 可见活跃 equity 例：`xyz:TSLA`, `xyz:NVDA`, `xyz:AAPL`, `xyz:MSFT`, `xyz:AMZN`, `xyz:GOOGL`, `xyz:META`, `xyz:COIN`, `xyz:HOOD`, `xyz:MSTR`, `xyz:PLTR`, `xyz:CRCL`, `xyz:SP500`, `xyz:XYZ100`, …  
- **注意**：`flx:`（Felix）等多数量 `isDelisted: true`，**不要**作为 Phase 1 依赖；主推 **`xyz`**。
- 主 dex（`dex=""`）**没有** TSLA/AAPL 等美股名。
- **无** `xyz:SPY` / `xyz:QQQ` exact ticker — 仅有指数代理 `xyz:SP500` / `xyz:XYZ100`。

### 4.3 其他 venue Stocks 覆盖（live）

| Underlying | Binance TradFi | Bybit perp | Bybit xStock spot | HL xyz | Lighter | ApeX stock | Solana xStock mint |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TSLA | ✅ `TSLAUSDT` | ✅ | ✅ `TSLAXUSDT` | ✅ `xyz:TSLA` | ✅ | ✅ `TSLA-USDT` | ✅ `XsDoVfqeBukxuZHWhdvWHBhgEHjGNst4MLodqsJHzoB`（TSLAx） |
| AAPL | ✅ | ✅ | ✅ `AAPLXUSDT` | ✅ `xyz:AAPL` | ✅ | ✅ | ✅ `XsbEhLAtcf6HdfpFZ5xEMdqW8nfAvcsP5bdudRLJzJp`（**AAPLx**） |
| NVDA | ✅ | ✅ | ✅ `NVDAXUSDT` | ✅ | ✅ | ✅ | ✅ `Xsc9qvGR1efVDFGLrVsmkzv3qi45LTBjeUKSPmx9qEh` |
| MSFT | ✅ | ✅ | ❌ spot 列表未见 | ✅ | ✅ | ✅ | ✅ `XspzcW1PRtgf6Wj92HCiZdjzKCyFekVD8P5Ueh3dRMX` |
| AMZN | ✅ | ✅ | ✅ `AMZNXUSDT` | ✅ | ✅ | ✅ | ✅ `Xs3eBt7uRfJX8QUs4suhyU8p2M6DoUDrJyWBa8LLZsg` |
| GOOGL | ✅ | ✅ | ✅ `GOOGLXUSDT` | ✅ | ✅ | ✅ | ✅ `XsCPL9dNWBMvFtTmwcCA5v3xWPSMEBCszbQdiLLq6aN` |
| META | ✅ | ✅ | ✅ `METAXUSDT` | ✅ | ✅ | ✅ | ✅ `Xsa62P5mvPszXL1krVUnU5ar38bBSVcWAB6fmPCo5Zu` |
| COIN | ✅ | ✅ | ✅ `COINXUSDT` | ✅ | ✅ | ✅ | ✅ `Xs7ZdzSHLU9ftNJsii5fCeJhoRWSC32SQGzGQtePxNu` |
| HOOD | ✅ | ✅ | ✅ `HOODXUSDT` | ✅ | ✅ | ✅ | ✅ `XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg` |
| MSTR | ✅ | ✅ | ❌ spot 未见 | ✅ | ✅ | ✅ | ✅ `XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ` |
| SPY | ✅ | ✅ | ❌ | ⚠️ **proxy-only**：`xyz:SP500` 等，**无** `xyz:SPY` | ✅ `SPY` | ✅ `SPY-USDT` | ✅ `XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W`（SPYx） |
| QQQ | ✅ | ✅ | ❌ | ⚠️ **proxy-only**：`xyz:XYZ100` 等，**无** `xyz:QQQ` | ✅ | ✅ | ✅ `Xs8S1uUs1zvS2p7iwtsG3b6fkhpvmwz4GYU3gWAmWHZ` |
| CRCL | ✅ | ✅ | ✅ `CRCLXUSDT` | ✅ | ✅（列表有） | ✅ | ✅ `XsueG8BtpquVJX9LVLLEGuViXUungE6WmK5YZ3p3bd1` |
| AMD | ✅ | ✅ **`AMDSTOCKUSDT`**（非 `AMDUSDT`） | ❌ | ✅ | ✅ | ✅ | ✅ `XsXcJ6GZ9kVnjqGsjBnktRcuwMBmvKWh8S93RefZ1rF` |
| Prop AMM | — | — | — | — | — | — | ❌ 无直连 |

> xStock mint 选取规则：Jupiter search 返回中 **symbol 匹配 + mint 以 `Xs` 开头 + 显著 holders/liquidity**；排除 `…pump` 仿盘（例：错误的 `APPLx` pump mint）。**AAPL 官方 symbol 为 `AAPLx`**。

### 4.3.1 Binance spot `*B` equity tokens — **Phase 1 明确排除**

Binance spot `exchangeInfo` 上存在 TRADING 的 **`*B` 股票代币**（例：`TSLABUSDT`, `AAPLBUSDT`, `NVDABUSDT`, `SPYBUSDT`, `AMZNBUSDT`, `AMDBUSDT`, `CRCLBUSDT`, …）。  
**本调研 / Phase 1 tokenized 路径不纳入** 该族，原因：

1. 与 Backed **xStocks**（Bybit `*X` / Solana `Xs…`）**非同一发行、托管与赎回模型**，不可默认 1:1 对齐价格语义；
2. 地区/产品可用性与 TradFi perp 不同，需单独合规评估；
3. 即便纳入，全 venue-class 交集仍为空（prop AMM 仍缺席）。

TSV `binance_spot` 对 stocks 行标 `no(*B_excl)` = **「不在本产品 tokenized 可比集合内」**，不是「API 无 TRADING 符号」。若未来要对比 Binance `*B`，应开独立 scope（issuer 映射 + 合规），勿静默并入 xStock 板。

### 4.4 交集结论

```text
Full venue-class intersection (CEX ∩ PerpDEX ∩ AMM ∩ PropAMM)  =  ∅

Equity-perp exact-ticker intersection (BN ∩ BY ∩ HL-xyz ∩ Lighter ∩ ApeX) ≈
  { TSLA, AAPL, NVDA, MSFT, AMZN, GOOGL, META, COIN, HOOD, MSTR, ... }
  # AMD: Bybit symbol AMDSTOCKUSDT (not AMDUSDT)
  # SPY/QQQ: exclude HL from exact-ticker ∩ (HL = SP500/XYZ100 proxy only)

Tokenized intersection (Bybit xStock spot ∩ Solana xStocks; Binance *B excluded) ≈
  { TSLA, AAPL, NVDA, AMZN, GOOGL, META, COIN, HOOD, CRCL, ... }
  （无 prop AMM；MSFT/SPY/QQQ/MSTR 等 Solana 有、Bybit spot 本快照未挂）
```

### 4.5 Stocks section 推荐方案

| 优先级 | 方案 | 资产建议 | Venue 集合 |
| --- | --- | --- | --- |
| **P0 推荐** | Equity-perp 价差板（**exact ticker**） | TSLA, NVDA, AAPL, MSFT | Binance TradFi + Bybit linear + HL `xyz:` + Lighter + ApeX |
| **P0-lite** | ETF 类 equity-perp；**HL = proxy-only** | SPY, QQQ | BN + BY + Lighter + ApeX exact；HL 仅可选 `xyz:SP500` / `xyz:XYZ100`（须 UI 标注 proxy，**勿**建 `xyz:SPY` adapter） |
| **P1** | 扩展 mega-cap / 加密股 | AMZN, GOOGL, META, COIN, HOOD, MSTR, CRCL, PLTR, AMD（Bybit=`AMDSTOCKUSDT`） | 同 P0 五 venue |
| **P2 可选** | Tokenized 现货板 | TSLAx, AAPLx, NVDAx, … | Bybit spot `*X` + Solana Jupiter（**exclude prop AMM**；**exclude Binance `*B`**） |
| **不推荐 Phase 1** | 「含 prop AMM 的 Stocks」 | — | 无资产 |

**若产品强制「三 section 均全 venue」**：应 **降级 Stocks 为 dashboard-only HL+Lighter+CEX**，或 **Phase 1 暂缓 Stocks（WHI-810 范围收缩）** — 在 issue 评论中明确 prop AMM 缺口。

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

### 6.2 Stocks（equity-perp P0 / P0-lite）

| Logical | BN TradFi | BY perp | HL xyz | Lighter | ApeX | BY xStock | Sol xStock | PropAMM |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TSLA | TSLAUSDT | TSLAUSDT | xyz:TSLA | TSLA | TSLA-USDT | TSLAX | TSLAx mint | — |
| AAPL | AAPLUSDT | AAPLUSDT | xyz:AAPL | AAPL | AAPL-USDT | AAPLX | AAPLx mint | — |
| NVDA | NVDAUSDT | NVDAUSDT | xyz:NVDA | NVDA | NVDA-USDT | NVDAX | NVDAx mint | — |
| MSFT | MSFTUSDT | MSFTUSDT | xyz:MSFT | MSFT | MSFT-USDT | — | MSFTx mint | — |
| SPY (P0-lite) | SPYUSDT | SPYUSDT | proxy:SP500 only | SPY | SPY-USDT | — | SPYx mint | — |
| QQQ (P0-lite) | QQQUSDT | QQQUSDT | proxy:XYZ100 only | QQQ | QQQ-USDT | — | QQQx mint | — |

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

### 7.2 WHI-810 Stocks

```text
P0 (equity perps, exact ticker on all 5 venues): TSLA, NVDA, AAPL, MSFT
P0-lite (ETF; HL proxy-only xyz:SP500 / xyz:XYZ100 — no xyz:SPY/QQQ): SPY, QQQ
P1: AMZN, GOOGL, META, COIN, HOOD, MSTR, CRCL, PLTR, AMD (Bybit=AMDSTOCKUSDT)
P2 (tokenized, optional): TSLAx, AAPLx, NVDAx, … (Bybit *X + Solana; no prop AMM; no Binance *B)
```

- Section 副标题建议：**「Equity perps / tokenized — not prop-AMM venue set」**。  
- **勿**为 SPY/QQQ 实现不存在的 `xyz:SPY` / `xyz:QQQ` adapter。

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
| Q13 | Binance `*B` 若未来纳入，需独立 issuer/合规 scope | Tokenized 扩展 |

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

---

## 10. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-798-asset-category-inventory.md` | 本文 |
| `docs/research/samples/WHI-798-asset-venue-matrix.tsv` | 资产×venue 符号/mint 矩阵（机器可读） |
| `README.md` | Research 表增加 WHI-798 行 |

---

## 11. 与下游 issue 的交接一句话

| Issue | 交接 |
| --- | --- |
| WHI-809 | 只做 BTC/ETH/SOL；用 §3.3 映射；SOL 不含 EVM AMM |
| WHI-810 | P0 exact = TSLA/NVDA/AAPL/MSFT；SPY/QQQ = P0-lite（HL proxy）；Bybit AMD=`AMDSTOCKUSDT`；tokenized 不含 Binance `*B`；prop 不在架 |
| WHI-811 | P0 八个非 meme L1/大盘；P1 缩放 meme；**不要**对 prop 扫 meme |
| WHI-806 | 资产侧继续以 WHI-797 三 pair 为 prop 核心 |
