# WHI-883：高成交量股票 underlying × form × venue 覆盖调研

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-883](https://linear.app/whisker-personal/issue/WHI-883/m7-docs-survey-venue-coverage-for-additional-high-volume-stock) |
| Milestone | M7 股票资产模型重构（underlying + form） |
| Blocked by | [WHI-880](https://linear.app/whisker-personal/issue/WHI-880)（form 分类法） |
| Blocks | [WHI-884](https://linear.app/whisker-personal/issue/WHI-884)（catalog / stocks section 扩容） |
| 调研日期 | **2026-08-06**（UTC） |
| 方法 | 各 venue **公网 market-list / meta API live 探测** + GeckoTerminal 池搜索 + Jupiter token search + Jupiter prop `dexes=` 抽检；形状对齐 [WHI-798](./WHI-798-asset-category-inventory.md) §4.6 / §6.2 v3 |
| 机器可读表 | [`samples/WHI-883-underlying-form-venue-matrix.tsv`](./samples/WHI-883-underlying-form-venue-matrix.tsv) |
| 原始摘要 | [`samples/whi-883-raw/`](./samples/whi-883-raw/)（`probe_rows.csv`、`lighter_equity_slim.json`、`apex_equity_slim.json`、`hl_xyz_vol.json`、`gecko_pools.json`、`jup_xstocks.json`、`jup_prop_xstock_probes.json`、`kyber_tessera_probes.json`） |

> **范围**：在 Phase-1 锚点（`NVDA` / `TSLA` / `AAPL` / `MSFT` / `QQQ` / `SPCX`）之外，为 Stocks section 扩容候选 underlying。  
> **不做**：catalog / adapter / FE 代码（WHI-884）；不改 form 词汇表（WHI-880 / WHI-798 §4.6）。  
> **项目规则**：asset-first — form 存在但本轮未能 live 钉死 → 标 **`unverified`**，**禁止静默删除**。

---

## 1. 结论摘要（TL;DR）

1. **13 个候选 underlying 全部有可交易的 equity perp 路径**（Binance TradFi + Bybit linear + Lighter + ApeX stockContract；HL `xyz:` exact 除 SPY/QQQ 外全有）。相对 Phase-1 仅 4 个 perp ticker，扩容空间很大。
2. **bStocks（`*B`）Binance spot 对本名单全覆盖**——含 WHI-798 快照中曾记为 absent 的 **`AMDB`**（本轮 `AMDBUSDT` TRADING，24h quote ≈ $4.5M）。Pancake v3 池对多数 `*B` 可搜到，但 **TVL/成交量高度不均**（QQQB/SPYB/NVDAB 厚；AVGOB/AMDB 等极薄）。
3. **Bybit xStock spot（`*X`）是子集**：AMZN/GOOGL/META/COIN/HOOD/CRCL（+ 锚点 TSLA/NVDA/AAPL）live；**AMD / PLTR / MSTR / AVGO / ORCL / SPY / QQQ 无 `*X`**。
4. **Solana xStocks mint 全员有**（Jupiter tokens v2）。Prop 抽检：**`AMZNx` × HumidiFi/TesseraV/BisonFi** → 全部 `NO_ROUTES_FOUND`（`absent_no_route`）；**`NVDAx` × HumidiFi only** → `NO_ROUTES_FOUND`（其它 prop **未测**，正文不写「三家」）。**其余 xStock prop 列为 `unverified`**（含高 liq 的 SPYx/QQQx）——不得外推，也**不得**在未逐 mint 复测前塞进 Jupiter poller。
5. **Tessera BSC** 已知 live 子集仍是 **QQQB / SPCXB / NVDAB / NVDAon**（本轮 Kyber 复测 QQQB ✅）。其它 `*B`/`*on` 一律 **`unverified`**（Gecko pool-detail 429 阻断批量拿合约地址），**不**写成 absent。
6. **P0 推荐 8 个新增/扩容 underlying**（见 §5）：`CRCL`, `GOOGL`, `AMD`, `PLTR`, `META`, `AMZN`, `SPY`, `MSTR`。  
   **P1**：`COIN`, `HOOD`, `ORCL`, `AVGO`，以及 `QQQ` 的 **perp form 扩容**（bstock 已在 Phase-1）。

### 1.1 关于「≥3 venues 才值得做板」

Issue 提出的 **「≥3 venues to be worth a board」是未验证参数**，不在 `docs/DESIGN.md` §2 / WHI-798 / WHI-799。本轮观测：

| 事实 | 含义 |
| --- | --- |
| 本名单几乎所有 exact equity perp 在 **4–5** 个 orderbook venue 同时 live | 「≥3」对 **perp 板**几乎不过滤任何人 |
| 真正拉开差距的是 **exact vs proxy（HL）**、**ApeX enableTrade**、以及 **tokenized 多 form** | 过滤应看形态质量，不是 raw venue 计数 |
| 薄 bStock 池（TVL ≪ $1k）即使「有 venue」也不适合进 fan-out | 应用 **流动性门槛** 而不是 venue 数 |

**决定：丢弃「≥3 venues」硬阈值**。下面两条是 **本调研提出的替代启发式**（同样 **未** 写入 `docs/DESIGN.md` §2；WHI-884 可采纳、改数或再丢弃）：

| 启发式（unvalidated） | 意图 |
| --- | --- |
| **Perp board 优先** | 优先 exact ticker 在 orderbook 五家里 **覆盖尽量完整** 的 underlying；HL 必须是 **exact `xyz:TICKER`**（禁止把 `xyz:SP500` / `xyz:XYZ100` 记成 SPY/QQQ exact）。本轮 P0 用 **观测到的 BN/HL 成交量** 排序，不是用 venue 计数阈值卡人。 |
| **Multi-form 加分** | 有 live CEX tokenized spot（bStock / `*X`）或 **可识别的** AMM 池时，跨 form 板更有产品价值；薄池 / 非 adapter 路径（非 Pancake v3）标 `live_thin` / `unverified`，**不进 fan-out**。 |
| **不进 fan-out（仍 catalog）** | `unverified` / `live_thin` / `proxy` / `disabled` / `absent_no_route` 行：`coverage=unverified` 或报价 `no_quote`，**不删 form** |

---

## 2. 候选集合与方法

### 2.1 候选 underlying

Issue 名单（成交量排序意图；本轮按 live 数据重排 §5）：

`AMZN`, `GOOGL`, `META`, `AMD`, `PLTR`, `COIN`, `HOOD`, `MSTR`, `AVGO`, `ORCL`, `SPY`, `QQQ`（perp 扩容）, 以及高量附属 **`CRCL`**（WHI-798 P1 / BN TradFi 本轮 24h 名义成交量榜首）。

已在 Phase-1 锚点、**不作为「新增 underlying」计数**但用于对照：`NVDA`, `TSLA`, `AAPL`, `MSFT`, `QQQ`(bstock), `SPCX`。

`assets.py` 的 `EQUITY_PERP_ASSETS` 已白名单 `AMZN/GOOGL/META/COIN/HOOD/MSTR` 供 mid 分类，但 **从未 catalog**——与本调研一致。

### 2.2 数据源（live 2026-08-06）

| Venue / 源 | Endpoint | 用途 |
| --- | --- | --- |
| Binance spot | `GET https://api.binance.com/api/v3/exchangeInfo` + `ticker/24hr` | bStocks `*B` TRADING + quoteVolume |
| Binance USDT-M | `GET https://fapi.binance.com/fapi/v1/exchangeInfo` + `ticker/24hr` | TradFi `TRADIFI_PERPETUAL` |
| Bybit | `GET https://api.bybit.com/v5/market/instruments-info?category=linear\|spot` + `tickers` | perp + `*X` spot + turnover24h |
| Hyperliquid | `POST https://api.hyperliquid.xyz/info` `metaAndAssetCtxs` `dex=xyz` | HIP-3 exact names + `dayNtlVlm` |
| Lighter | `GET …/api/v1/orderBooks` + `orderBookDetails` | equity symbols + `daily_quote_token_volume` |
| ApeX Omni | `GET https://omni.apex.exchange/api/v3/symbols` → `contractConfig.stockContract` | `enableTrade` / `symbol`（`TICKER-USDT`） |
| GeckoTerminal | `GET api.geckoterminal.com/api/v2/search/pools?query=` | Pancake BSC 池存在性 + 24h vol / TVL |
| Jupiter tokens | `GET https://lite-api.jup.ag/tokens/v2/search?query=` | xStocks mint / liq / holders |
| Jupiter quote | `GET …/swap/v1/quote?onlyDirectRoutes=true&dexes=` | Sol prop 对 xStocks 路由（抽检） |
| KyberSwap | `GET …/bsc/api/v1/routes?includedSources=tessera` | Tessera BSC（已知地址复测） |

### 2.3 Status 词汇

| status | 含义 |
| --- | --- |
| `live` | 本轮 API 确认可交易 / 有池 |
| `live_thin` | live 但 24h vol≈0 或与 TVL 极低（产品 fan-out 慎用；TSV 用于 Lighter AVGO 等） |
| `proxy` | 仅有指数/代理合约（如 HL `xyz:SP500`），**不是** exact underlying |
| `disabled` | 符号存在但 `enableTrade=false`（ApeX ORCL） |
| `absent` | 本轮 instruments 中无该市场 |
| `absent_no_route` | 资产存在但 prop 报价明确无路由 |
| `unverified` | 预期/历史存在，本轮未能钉死 —— **保留在 inventory** |

---

## 3. Perp form 覆盖（orderbook venues）

图例：✅ live exact · ⚠️ proxy / disabled · ⛔ absent

| asset | binance TradFi | bybit linear | HL `xyz:` | Lighter | ApeX stock | BN 24h quote (perp) | HL dayNtlVlm |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **CRCL** | ✅ CRCLUSDT | ✅ | ✅ xyz:CRCL | ✅ | ✅ CRCL-USDT | **$381M** | $95M |
| **QQQ** | ✅ QQQUSDT | ✅ | ⚠️ xyz:XYZ100 only | ✅ | ✅ QQQ-USDT | **$219M** | — |
| **GOOGL** | ✅ | ✅ | ✅ | ✅ | ✅ | **$188M** | $84M |
| **AMD** | ✅ | ✅ **AMDSTOCKUSDT** | ✅ | ✅ | ✅ | **$128M** | **$97M** |
| **MSTR** | ✅ | ✅ | ✅ | ✅ | ✅ | $65M | $11M |
| **SPY** | ✅ | ✅ | ⚠️ xyz:SP500 only | ✅ | ✅ | $66M | — |
| **PLTR** | ✅ | ✅ | ✅ | ✅ | ✅ | $58M | $23M |
| **META** | ✅ | ✅ | ✅ | ✅ | ✅ | $55M | $55M |
| **AMZN** | ✅ | ✅ | ✅ | ✅ | ✅ | $37M | $20M |
| **ORCL** | ✅ | ✅ | ✅ | ✅ (薄) | ⚠️ enableTrade=**false** | $28M | $20M |
| **COIN** | ✅ | ✅ | ✅ | ✅ | ✅ | $28M | $7.8M |
| **HOOD** | ✅ | ✅ | ✅ | ✅ | ✅ | $14M | $6.2M |
| **AVGO** | ✅ | ✅ | ✅ | ✅ status=active **vol≈0** | ✅ | $8.6M | $3.1M |

**乘数 / 命名 quirks（实现必读）**：

| Venue | Quirk |
| --- | --- |
| Bybit | **`AMDSTOCKUSDT`**（不是 `AMDUSDT`）— 已在 WHI-798 记录，本轮确认仍 Trading |
| Hyperliquid | meta `name` 字段为 **`xyz:TICKER`**；adapter 继续 `xyz:` 前缀。`SPY`/`QQQ` **无 exact** |
| ApeX | stock 合约在 `contractConfig.stockContract`；wire `TICKER-USDT`；**ORCL 整合约关闭**；本轮 **无** 公开 24h volume 字段（TSV volume 空，非零） |
| Lighter | 本轮 `multiplier=1`（见 slim JSON）；**Binance TradFi / Bybit / ApeX 合约乘数未逐合约导出**（实现时读 exchangeInfo/instruments，勿假设 1） |
| Lighter liq | AVGO `status=active` 但 `daily_quote=0` → TSV `live_thin` |

---

## 4. Tokenized forms

Form 词汇 SSOT：[WHI-798 §4.6](./WHI-798-asset-category-inventory.md) — `bstock` / `ondo` / `xstock` / `xstock_cex`。

### 4.1 `bstock`（Binance spot + Pancake + Tessera）

| asset | BN spot `*B` | BN 24h quote | Pancake BSC（Gecko） | Tessera BSC |
| --- | --- | --- | --- | --- |
| CRCL | ✅ CRCLBUSDT | **$22.0M** | Gecko 本轮 null → **unverified**（未区分 429 vs 无池） | unverified |
| QQQ | ✅ QQQBUSDT | $3.3M | ✅ QQQB/USDT vol **~$72M** TVL ~$2.0M | ✅ **live**（Kyber 复测） |
| NVDA (锚) | ✅ NVDABUSDT | $3.6M | Gecko 高量池为 **NVDAB/GPU**（非 USDT）→ 不作 USDT-comparable 主证据 | ✅ Tessera live（WHI-798） |
| GOOGL | ✅ GOOGLBUSDT | $1.7M | ✅ vol ~$73k TVL ~$110k | unverified |
| SPY | ✅ SPYBUSDT | $1.5M | ✅ SPYB/USDT vol **~$10.2M** TVL ~$792k | unverified |
| COIN | ✅ COINBUSDT | $648k | Gecko 本轮 null → unverified | unverified |
| ORCL | ✅ ORCLBUSDT | $526k | ✅ 薄（vol ~$1.8k） | unverified |
| META | ✅ METABUSDT | $435k | ✅ vol ~$9.6k TVL ~$46k | unverified |
| MSTR | ✅ MSTRBUSDT | $410k | ⚠️ 异常/薄池 | unverified |
| PLTR | ✅ PLTRBUSDT | $312k | ⚠️ 极薄 | unverified |
| HOOD | ✅ HOODBUSDT | $302k | ✅ vol ~$133k TVL ~$51k | unverified |
| AVGO | ✅ AVGOBUSDT | $296k | ⚠️ 极薄 | unverified |
| AMZN | ✅ AMZNBUSDT | $144k | ✅ vol ~$9.7k TVL ~$45k | unverified |
| **AMD** | ✅ **AMDBUSDT** | **$4.5M** | ⚠️ infinity/极薄池 | unverified |

**相对 WHI-798（2026-08-03）的修正**：`AMDB` 现已 TRADING；勿再写「AMD 无 bStock」。

### 4.2 `ondo`

本轮 Gecko 钉到 BSC 池的包括：`AMZNon`, `GOOGLon`, `METAon`, `NVDAon`, `TSLAon`, `AAPLon`, `SPYon`, `CRCLon`, `COINon` 等——多数 **vol/TVL 远低于 bStocks 头部**。  
`tessera_bsc` 对 Ondo **仅 NVDAon 在历史 live 子集**；其余 **unverified**。

### 4.3 `xstock_cex`（Bybit `*X`）

| live `*X` | 24h turnover (Bybit spot) |
| --- | --- |
| CRCLXUSDT | $3.50M |
| NVDAXUSDT (锚) | $2.46M |
| COINXUSDT | $1.41M |
| GOOGLXUSDT | $1.40M |
| HOODXUSDT | $1.08M |
| AAPLXUSDT (锚) | $0.79M |
| AMZNXUSDT | $0.46M |
| TSLAXUSDT (锚) | $0.47M |
| METAXUSDT | $0.19M |

**absent**：AMD, PLTR, MSTR, AVGO, ORCL, SPY, QQQ, MSFT（锚点亦无）。

### 4.4 `xstock`（Solana mint）+ prop

| asset | symbol | mint (prefix) | Jupiter liq (USD) | holders | Sol prop (本轮) |
| --- | --- | --- | --- | --- | --- |
| SPY | SPYx | XsoCS1Tf…F2W | **$2.53M** | 27k | **unverified**（未 quote 探测） |
| QQQ | QQQx | Xs8S1uUs…WHZ | **$2.04M** | 9.7k | **unverified** |
| NVDA (锚点) | NVDAx | Xsc9qvGR…qEh | $1.86M | 63k | HumidiFi `NO_ROUTES`；TesseraV/BisonFi **未测** → 不写全 prop `absent_no_route` |
| CRCL | CRCLx | XsueG8Bt…bd1 | $867k | 13k | unverified |
| MSTR | MSTRx | XsP7xzNP…xyZ | $481k | 9.1k | unverified |
| GOOGL | GOOGLx | XsCPL9dN…6aN | $330k | 18k | unverified |
| HOOD | HOODx | XsvNBAYk…zpg | $295k | 4.6k | unverified |
| COIN | COINx | Xs7ZdzSH…xNu | $255k | 3.8k | unverified |
| AMZN | AMZNx | Xs3eBt7u…Zsg | $202k | 6.2k | **⛔ `absent_no_route`**（三 prop 抽检） |
| AVGO | AVGOx | XsgSaSvN…JGo | $76k | 492 | unverified |
| PLTR | PLTRx | XsoBhf2u…AA4 | $54k | 1.1k | unverified |
| META | METAx | Xsa62P5m…o5Zu | $46k | 5.9k | unverified |
| ORCL | ORCLx | XsjFwUPi…jeL | $4.3k | 900 | unverified |
| AMD | AMDx | XsXcJ6GZ…r1rF | $1.7k | 935 | unverified |

完整 mint：[`jup_xstocks.json`](./samples/whi-883-raw/jup_xstocks.json)。  
Prop 抽检原始结果：[`jup_prop_xstock_probes.json`](./samples/whi-883-raw/jup_prop_xstock_probes.json)。

---

## 5. P0 / P1 推荐（给 WHI-884）

### 5.1 排序依据（可复核）

主排序键：**Binance TradFi 24h quoteVolume**（全市场最大、可比的 equity perp 量纲）。  
次键：HL `dayNtlVlm`、tokenized 多 form 丰富度、Bybit `*X`、bStock BN spot 量。  
**不用** raw venue count ≥3。

### 5.2 P0 — 建议进入下一轮 catalog + stocks section

| # | asset | 理由 | 优先 live forms（fan-out） | catalog 但暂不 fan-out |
| --- | --- | --- | --- | --- |
| 1 | **CRCL** | BN perp $381M + BN bStock $22M 双料头部；5 exact perps；`*X` + xStock 厚 | `perp` 五 venue；`bstock` BN spot（+ Pancake 待地址） | `xstock_cex`, `xstock`, `ondo` unverified |
| 2 | **GOOGL** | BN perp $188M；HL $84M；完整 multi-form（`*B`/`*X`/xStock/ondo 池） | `perp` 五 venue；`bstock` BN；`xstock_cex` | Pancake/Tessera/`ondo`/`xstock` |
| 3 | **AMD** | BN $128M + HL **$97M** 半导体高波动；**Bybit=`AMDSTOCKUSDT`** | `perp` 五 venue（wire map 特判） | `bstock` BN（Pancake 薄）；无 `*X`；`xstock` 极薄 |
| 4 | **PLTR** | HL $23M + 五 exact perps；叙事高波动 | `perp` 五 venue | `bstock` BN；无 `*X`；`xstock` |
| 5 | **META** | 五 exact + `*X` + 中等 bStock | `perp`；`xstock_cex`；`bstock` BN | pancake/ondo/xstock |
| 6 | **AMZN** | 五 exact + 全 tokenized 形态齐全（量中等） | `perp`；`xstock_cex`；`bstock` BN | 薄 pancake / ondo / xstock |
| 7 | **SPY** | ETF 对标；BN+BY+Lighter+ApeX exact；**HL 仅 proxy**；bStock SPYB 池厚（~$10M/24h） | `perp` **四 venue（禁 HL exact）**；`bstock` BN (+ Pancake 厚池) | `xstock`（厚 mint）；无 `*X`；HL proxy **不入 best** |
| 8 | **MSTR** | BN $65M；五 exact；无 `*X` 但 xStock liq 较好 | `perp` 五 venue；`bstock` BN | `xstock`；无 xstock_cex |

**另：`QQQ` perp 扩容**（underlying 已在 Phase-1 via bstock）→ 加 BN/BY/Lighter/ApeX `perp` 行；**禁止** `xyz:QQQ`。

### 5.3 P1 — 有覆盖，优先级低于 P0

| asset | 理由 | 注意 |
| --- | --- | --- |
| **COIN** | 五 exact + `*X` + bStock；perp 量低于 META/AMZN | crypto 股权，和本产品叙事贴 |
| **HOOD** | 同上，BN perp 更低 | `*X` 流动性尚可 |
| **ORCL** | HL/BN 有量；**ApeX 关闭** → perp 板 4 venue | 缺 ApeX 列或标 disabled |
| **AVGO** | 有五家 listing 但 **Lighter vol≈0、BN perp 最低** | 适合观察仓，不急 fan-out |

### 5.4 明确不推荐（本轮）

| 项 | 原因 |
| --- | --- |
| 把 **Sol xStocks 写入 Jupiter poller** | 抽检 NO_ROUTES + 未测 mint 不得外推；poller 只会消耗 WHI-864 Free-plan 预算 |
| 把 **HL `xyz:SP500` / `xyz:XYZ100`** 当作 SPY/QQQ exact 行 | 违背 exact-ticker 口径（WHI-798 §4.4） |
| 为 **pre-IPO SPV** 扩容 | 仍排除（WHI-798 §4.5） |
| 仅因「有 Pancake 池」就对薄 `*B` 开 Tessera/AMM fan-out | Tessera 子集 + 薄池噪声 |

---

## 6. 运营成本：Jupiter Free-plan 预算（WHI-864）

### 6.1 现状（`config/jupiter.yaml` + `config/poller.yaml`）

| 参数 | 值 |
| --- | --- |
| Keyed sustained | ~**1 RPS**（`keyed_capacity=10`, `window_sec=10`） |
| Poller `budget_share` | 0.6 → 有效 **0.6 RPS** |
| 采样矩阵 | 3 prop × 3 assets × **3 tiers** × **2 sides** = **54 calls** |
| 墙钟 | 54 / 0.6 ≈ **90 s**；`interval_sec=120` 有 ~30 s 余量 |

### 6.2 若 P0 误加 Sol xStocks

假设对 P0 中 8 个 underlying 的 `xstock` 各扫 3 prop × 3 tier × 2 side：

`8 × 3 × 3 × 2 = 144` calls → **144 / 0.6 ≈ 240 s** ≫ 120 s interval → **必然 sweep overlap / `skip_count` / `quote_stale`**。

AMZNx 三 prop 已是 **NO_ROUTES**；NVDAx 仅 HumidiFi 无路由。未探测的厚 mint（SPYx/QQQx）**不能**靠「家族模式」假设有路由——把它们放进 poller 在出绿测之前同样是预算浪费。

**结论**：P0 扩容 **只应增加 orderbook（WS）与 Kyber/RPC 路径上已验证的 bStock 行**；  
**Sol xStocks：catalog + `no_quote` / `unverified`，零 Jupiter 请求**，直到 **逐 mint** WHI-797 式复测出现 prop 路由。

### 6.3 Kyber / RPC

- Tessera：仅对 **已知有路由的 token 地址** 发请求（现网 adapter 白名单 QQQB/SPCXB/NVDAB/NVDAon）。P0 新增 bStock **在 Tessera 未验证前不要扩白名单**。
- Pancake quoter：每新 token 增加 fee-tier probe 成本；受 `config/rpc.yaml` 限流。P0 若只开 **BN spot bStock + perp**，可零 RPC 增量。

### 6.4 推荐 WHI-884 落地顺序（预算安全）

1. **Catalog**：P0 underlyings × 全 form（含 unverified）。  
2. **Fan-out phase A**：仅 `perp`（五/四 venue）— 走已有 WS orderbook，**零 Jupiter**。  
3. **Fan-out phase B**：`bstock` @ `binance` spot（+ 可选 Pancake 对 TVL ≳ $10k 的池）。  
4. **Fan-out phase C**：`xstock_cex` @ Bybit（不碰 Jupiter）。  
5. **永不默认开启**：`xstock` @ Sol prop；Tessera 直至 per-token Kyber 绿。

---

## 7. 压缩矩阵（决策用）

完整行级表见 TSV。下表：每个 underlying 的 form 就绪度。

| asset | perp exact (n/5) | bstock BN | pancake *B | tessera *B | ondo | xstock_cex | xstock mint | prop sol |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CRCL | 5 | ✅ $22M | unverified | unverified | unverified (BTC-quote risk) | ✅ | ✅ high liq | unverified prop |
| GOOGL | 5 | ✅ | ✅ pancake pool | unverified | pool/unverified | ✅ | ✅ | unverified prop |
| AMD | 5† | ✅ $4.5M | non-v3 / thin | unverified | unverified | ⛔ | low liq | unverified prop |
| PLTR | 5 | ✅ | thin / non-v3 | unverified | unverified | ⛔ | mid | unverified prop |
| META | 5 | ✅ | pool | unverified | thin/unverified | ✅ | mid | unverified prop |
| AMZN | 5 | ✅ | pool | unverified | thin | ✅ | mid | **⛔ 3-prop probed** |
| SPY | 4 + HL **proxy row** | ✅ | ✅ high vol pool | unverified | thin/unverified | ⛔ | ✅ high liq | unverified prop |
| MSTR | 5 | ✅ | corrupt/thin TVL | unverified | unverified | ⛔ | ✅ | unverified prop |
| QQQ | 4 + HL **proxy row** | ✅ Phase-1 | ✅ high vol | ✅ | unverified | ⛔ | ✅ high liq | unverified prop |
| COIN | 5 | ✅ | unverified | unverified | unverified (BTC-quote risk) | ✅ | mid | unverified prop |
| HOOD | 5 | ✅ | pool | unverified | unverified | ✅ | mid | unverified prop |
| ORCL | 4 (ApeX off) | ✅ | thin | unverified | unverified | ⛔ | low/thin | unverified prop |
| AVGO | 5 (Lighter **live_thin**) | ✅ | thin / non-v3 | unverified | unverified | ⛔ | mid | unverified prop |

† Bybit wire = `AMDSTOCKUSDT`。

---

## 8. 对 WHI-798 的修正（本 PR 已落地）

本文件是 **WHI-798 的 companion expansion**，不替换 §6.2.1 Phase-1 表。**已在同一 PR 写入 WHI-798 的**：

1. §6.2.2 / §7.2 → 引用本文 P0/P1 与 TSV（2026-08-06）。  
2. §4.3 AMD 增补 **✅ AMDB** 行；Sol prop 不得对未测 mint 写 ⛔。  
3. §4.5 P2 → 指针「见 WHI-883 §5」。  
4. §12 修订记录 + matrix TSV 头注释。

---

## 9. 开放风险 / 后续

| ID | 风险 | 跟进 |
| --- | --- | --- |
| R1 | Tessera 池集随做市库存变动（WHI-798 Q15） | 有合约地址后批量 Kyber 绿测；失败保持 unverified |
| R2 | Gecko 429 导致部分 pancake/ondo 未钉 | WHI-884 实现前可再扫；未钉 ≠ 删除 |
| R3 | ApeX ORCL 可能重新 enable | 启动时读 `enableTrade`，勿写死 |
| R4 | HL 未来若上 exact SPY/QQQ | 替换 proxy 行；在此之前禁止假 exact |
| R5 | xStocks 若出现 prop 路由 | 先单资产 probe，再谈 poller 预算重算 |

---

## 10. 验收对照

| AC | 状态 |
| --- | --- |
| Inventory table in `docs/research/`，≥6 new underlyings，per-venue + evidence | ✅ TSV + 本文 §3–§4；13 候选（≥6 新增） |
| Explicit P0/P1 + unverified 不省略 | ✅ §5；TSV 含 `unverified` / `absent_no_route` 行 |
| ≥3 venues 参数处理 | ✅ §1.1 **丢弃**，改 multi-form / exact 规则 |
| Jupiter 预算 | ✅ §6：P0 不增加 xStock Jupiter 负载 |

---

## 11. 参考

- [WHI-798 asset inventory](./WHI-798-asset-category-inventory.md) §4.3–§4.6 / §6.2 v3  
- [WHI-799 data model](./WHI-799-spread-fee-data-model.md) §3.3 / §5.2 / §6.2  
- [WHI-797 prop AMM](./WHI-797-prop-amm-jupiter-quote-api.md) Jupiter `dexes=`  
- WHI-864 / `config/jupiter.yaml` + `config/poller.yaml`  
- `spread_compare/assets.py` `EQUITY_PERP_ASSETS`
