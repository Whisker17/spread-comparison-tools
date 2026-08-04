# WHI-837：Solana prop AMM 报价冗余路径调研（Jupiter SPOF）

| 字段 | 值 |
| --- | --- |
| Issue | [WHI-837](https://linear.app/whisker-personal/issue/WHI-837) |
| Closes risk | [WHI-797](./WHI-797-prop-amm-jupiter-quote-api.md) §9「Solana 完全依赖 Jupiter……暂无冗余路径」 |
| Related | WHI-799 §4.1 notional tiers; WHI-836 (throughput — **different problem**) |
| 调研日期 | 2026-08-04（UTC） |
| 验证环境 | 公网 live：Jupiter（`JUPITER_API_KEY`）、Titan DART（keyless）、DFlow/OKX/0x/Titan Gateway（unauth 负样本） |

---

## 1. 结论摘要（TL;DR）

1. **没有找到可替代 Jupiter 的、覆盖 HumidiFi + TesseraV + BisonFi 三家的 live 冗余报价源。** Solana prop AMM 矩阵在可预见的产品窗口内仍是 **Jupiter single point of failure**。
2. **Titan DART**（`POST https://api.titan.exchange/dart/swap`，keyless，文档含 `includeDexes`）是唯一 live 验证了 **include 过滤 + 至少一家 baseline prop AMM** 的候选：
   - `includeDexes=["BisonFi"]` → **200**，指令账户含 BisonFi program `BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi`（隔离旁证）。
   - `includeDexes=["HumidiFi"]` / `["TesseraV"]` → **400** `No routes found for request`（与错误 label 同形）。
   - **Q1 对三家基线：FAIL**（仅 BisonFi 通）。
3. **Q2（BisonFi only）**：四档 WHI-799 notional 上 Titan vs Jupiter 有效价差 **约 −1.0 ～ −1.8 bps**（Titan 略差），远小于「个位数 bps 价差」量级里我们要分辨的噪声上限 → **BisonFi 单家可比**，但不能撑起矩阵 failover。
4. **文档上最接近的完整候选（DFlow、OKX、Titan Gateway）均因鉴权/网络门禁无法在本调研完成 Q1 live 隔离证明**：
   - DFlow：`dexes` include + 明确 prop AMM 集成（Helius 一作、官方 venues 文案）；`quote-api.dflow.net` 对本环境返回 **空 body 403**。
   - OKX：`dexIds` include + 文档点名 HumidiFi/BisonFi（`forJitoBundle`）；**无 key 401**。
   - Titan Gateway：与 DART 同源路由能力 + `dexes`；**需 bearer token 401**。
5. **明确淘汰**：0x Solana Swap 仅有 `disabled_sources`（exclude-only）；1inch Solana **无 Classic SWAP**（仅 Intent / cross-chain）；Jupiter Ultra / Swap V2 **同一上游，不算冗余**（V2 仅作 Metis v1 迁移备注）。
6. **推荐**：接受风险 + **显式降级**（Jupiter 不可用时 Solana prop 列标 unavailable，禁止用另一聚合器半覆盖数填矩阵）。可选跟进：申请 DFlow / OKX key 后重跑完整 Q1×Q2（见 §8 后续 issue）。ADR：[docs/adr/0001-solana-prop-amm-jupiter-sole-path.md](../adr/0001-solana-prop-amm-jupiter-sole-path.md)。

---

## 2. 问题定义（两个真问题）

### Q1 — Feasibility

候选是否 **同时**：(a) 集成 HumidiFi / TesseraV / BisonFi；(b) 暴露 **per-DEX include 过滤**（exclude-only 不够）。

### Q2 — Comparability

即使 Q1 通过，也必须在 **同 venue × 同 pair × 同 size × 同窗口** 与 Jupiter 比有效价，用 **bps of effective price** 表达分歧。若分歧 ≥ 我们试图测量的价差（个位数 bps），则不是 drop-in。

背景（WHI-797 §2）：prop AMM 无公开前端、无独立 quote HTTP API；「拿某家报价」= 聚合器 Quote + venue 过滤。EVM 侧 KyberSwap `includedSources=tessera` 已证明模式，**但不覆盖 Solana**。

---

## 3. 候选总表（Q1 裁决）

| 候选 | Solana | Include filter | Prop AMM 集成证据 | Live 隔离（三家） | Q1 裁决 | 取消原因 |
| --- | --- | --- | --- | --- | --- | --- |
| **Jupiter Metis v1**（现状） | ✅ | `dexes` | ✅ WHI-797 | ✅ 三家 | **主路径** | — |
| **Jupiter Swap V2 / Ultra** | ✅ | V2 live `dexes=HumidiFi` 仍可 | ✅ 同上游 | ✅（同 upstream） | **OUT as redundancy** | 同一故障域 |
| **Titan DART**（keyless） | ✅ | `includeDexes` | 部分 prop（BisonFi live；GoonFi V2 曾通） | **仅 BisonFi** | **OUT（不完整）** | 缺 HumidiFi / TesseraV 路由 |
| **Titan Gateway / Direct** | ✅ | `dexes` / `excludeDexes`（文档） | 未 live 验证 | 未测 | **OUT（key）** | Gateway 401；token 需 Triton/QuickNode/waitlist |
| **DFlow** | ✅ | `dexes` / `excludeDexes` | 文档 + Helius：HumidiFi/SolFi 等 | 未测 | **OUT（key / 403）** | keyless 空 403；生产 key 表单 2–5 日 |
| **OKX DEX Aggregator** | ✅ | `dexIds` / `excludeDexIds` | 文档 `forJitoBundle` 点名 HumidiFi、BisonFi | 未测 | **OUT（key）** | 签名四元组 + Project ID；get-liquidity 需 auth |
| **0x Solana Swap** | ✅ | **仅** `disabled_sources` | 未验证 prop 名单 | n/a | **OUT** | **无 include-filter** |
| **1inch** | Intent only | n/a Classic | n/a | n/a | **OUT** | Solana Classic SWAP ❌ |
| **直接 on-chain 报价** | n/a | n/a | 闭源 + 私有 oracle 曲线 | n/a | **OUT** | 不可从账户状态重建 `Quote` |
| **链上成交事件** | n/a | n/a | 可做 realized | n/a | **非 Quote 路径** | 不能填请求 size 的 `Quote` |

---

## 4. 分候选卡片

### 4.1 Jupiter Metis v1（对照 / 主路径）

| 项 | 值 |
| --- | --- |
| Endpoint | `GET https://api.jup.ag/swap/v1/quote` |
| Filter | `dexes=HumidiFi\|TesseraV\|BisonFi`（精确 label） |
| Auth | 可选 `x-api-key`；本调研用 portal key |
| 文档 | https://developers.jup.ag/docs/api-reference/swap/v1/quote |

**Live 2026-08-04**（`onlyDirectRoutes=true`，SOL→USDC）：三家均 200，`routePlan[].swapInfo.label` 单一匹配。样本：`samples/whi-837/jup-*-sol-usdc-*.json`。

错误 label：`dexes=NotAVenue` → 400 `No routes found`（`jup-wrong-label.json`）。

### 4.2 Jupiter Swap V2 / Ultra（迁移备注，非冗余）

- Live：`GET https://api.jup.ag/swap/v2/quote` 对 SOL/USDC 返回 200；`dexes=HumidiFi` 仍隔离到 HumidiFi（`jup-v2-quote-dexes-humidifi.json`）。
- **同一 `api.jup.ag` 故障域**；Metis v1「不再积极维护」时的迁移目标是 V2，**不是**第二供应商。
- Ultra 前端平台费路径与 Metis Manual `/quote` 默认 `platformFee=null` 不同（WHI-797 §3.4）——比较口径不要混用。

### 4.3 Titan DART（唯一 live 部分通过）

| 项 | 值 |
| --- | --- |
| Base | `https://api.titan.exchange/dart` |
| Quote | `POST /swap`（JSON） |
| Include | `includeDexes: string[]` |
| Exclude | `excludeDexes: string[]` |
| Auth | keyless；文档 1 rps/IP，超限 429（nginx） |
| 文档 | https://titan-exchange.gitbook.io/titan/developer-doc/dart-swap-api/ |

**Live 隔离（1 SOL → USDC，2026-08-04）：**

| `includeDexes` | HTTP | 结果 |
| --- | --- | --- |
| `["BisonFi"]` | 200 | `outputAmount` 有值；账户含 BisonFi program id |
| `["HumidiFi"]` | 400 | `{"code":15,"message":"No routes found for request"}` |
| `["TesseraV"]` | 400 | 同上 |
| `["NotAVenue"]` | 400 | 同上（与缺路由不可区分） |
| _(none)_ | 200 | 聚合 DART 最优 |

样本：`titan-dart-include-BisonFi-sol-usdc-1sol.json`、`titan-dart-include-HumidiFi-sol-usdc-1sol.json`、`titan-dart-include-TesseraV-sol-usdc-1sol.json`、`titan-dart-wrong-label-sol-usdc.json`、`titan-dart-markets.json`。

**Q1 裁决：OUT（不完整）** — include 过滤器真实可用，但 **不满足「三家全部可隔离」**。

**Rate limit（实测）**：文档 1 rps；连续探测易 429 HTML。生产若采用需客户端串行 ≥1s + 退避。

**费用**：文档「Up to 1 bps fee」on-chain program；Q2 中 Titan 持续略逊 ~1 bps，与「≤1 bps 平台费」方向一致，但 **未** 在响应中拆出独立 fee 字段（只有 `outputAmount`）。

### 4.4 Titan Gateway / Direct

| 项 | 值 |
| --- | --- |
| Filter | `dexes` / `excludeDexes` / `providers` / venue allow|ban list |
| Auth | Bearer / query `auth`；Triton / QuickNode / Titan |
| Live | `GET .../api/v1/quote/price` → **401** `Missing authentication token` |

文档：https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/guides/configure-routing.md  

**Q1：OUT（key unobtainable in this research）**。能力上可能比 DART 更完整（多 provider 竞赛），但无 token 无法证明三家 prop label。

### 4.5 DFlow

| 项 | 值 |
| --- | --- |
| Quote | `GET https://quote-api.dflow.net/quote` |
| Venues | `GET /venues` |
| Filter | `dexes` / `excludeDexes`（OpenAPI 明文 include） |
| Auth | 文档：developer 可无 key（限速）；生产 key 表单 2–5 日 |
| Prop AMM | 官方 *Liquidity and Venues*：含 Prop AMMs；Helius「How DFlow Uses LaserStream…」点名 HumidiFi、SolFi |

**Live：** `/venues` 与 `/quote` 均 **HTTP 403、body 空、无 WWW-Authenticate**（`dflow-venues-403.meta.txt`）。无法取得 venue 字符串表，无法完成隔离。

**Q1：OUT（key / access blocked）** — 文档面最像「Jupiter 镜像 API」的候选，**优先排队申请 key 后重开**。

### 4.6 OKX DEX Aggregator

| 项 | 值 |
| --- | --- |
| Quote | `GET https://web3.okx.com/api/v6/dex/aggregator/quote` |
| Liquidity list | `GET .../get-liquidity?chainIndex=501`（Solana） |
| Filter | `dexIds` / `excludeDexIds`（comma ids） |
| Auth | `OK-ACCESS-KEY/SIGN/TIMESTAMP/PASSPHRASE` + Project |
| Prop 信号 | Quote 文档：`forJitoBundle` 排除 **HumidiFi and BisonFi** → 至少这两家在路由图中 |

**Live：** unauth get-liquidity → 401 `Request header OK-ACCESS-KEY can not be empty.`（`okx-get-liquidity-unauth.json`）。

**Tessera 未在公开文档点名**；需 auth `get-liquidity` 扫 name。  
**Q1：OUT（key）** — 文档强候选，与 WHI-797 §7.7 EVM 侧判断一致，Solana 侧仍待 key。

### 4.7 0x Solana Swap API

| 项 | 值 |
| --- | --- |
| Quote/build | `POST https://api.0x.org/solana/swap-instructions` |
| Sources | `GET /solana/enabled-sources` |
| Filter | **`disabled_sources` only**（exclude） |
| Auth | `0x-api-key` 必填 |

OpenAPI：无 include-only 参数。Exclude 不能把路由 **限制到单 venue**。  
**Q1：OUT（no include-filter）**。样本：`0x-enabled-sources-unauth.json`。

### 4.8 1inch

官方 portal：Solana chain id 501 → **Classic SWAP ❌**，Intent ✅ / Cross-chain ✅。Intent resolver 网络不是「per-DEX include 报价面」。  
**Q1：OUT（no Solana classic aggregation with include filter）**。  
来源：https://business.1inch.com/portal/documentation/apis/swap

---

## 5. Q2 — Comparability（仅 BisonFi × Titan DART）

**方法：**

1. 用 Jupiter `dexes=BisonFi` 1 SOL→USDC 估 mid（USDC/SOL）。
2. 对 WHI-799 §4.1 四档 `N ∈ {1000, 10_000, 100_000, 1_000_000}` USD，设 `amount = round(N / mid * 1e9)` lamports。
3. 紧接调用：Jupiter `dexes=BisonFi` 然后 Titan `includeDexes=["BisonFi"]`。
4. 有效价 `P = (out_amount / 1e6) / (amount / 1e9)`（USDC per SOL）。
5. `div_bps = (P_titan - P_jup) / P_jup * 10_000`。

**结果（2026-08-04；summary `q2-bisonfi-divergence.json`）：**

| notional_usd | amount (lamports) | Jupiter out (USDC raw) | Titan out | div_bps |
| ---: | ---: | ---: | ---: | ---: |
| 1_000 | 13_534_238_822 | 1_000_485_200 | 1_000_306_573 | **−1.79** |
| 10_000 | 135_342_388_226 | 10_001_598_644 | 10_000_611_011 | **−0.99** |
| 100_000 | 1_353_423_882_263 | 100_011_420_672 | 99_998_356_548 | **−1.31** |
| 1_000_000 | 13_534_238_822_633 | 994_570_296_438 | 994_472_832_193 | **−0.98** |

**解读：**

- 分歧 **稳定在 ~1 bps 量级**，方向一致（Titan 更差）→ 与 DART「up to 1 bps fee」叙事相容；**不是** 几十 bps 的口径错乱。
- 相对「我们想分辨的 venue 间个位数 bps 价差」，**BisonFi 单家** Titan 可作为近似对照，但 **不能** 在 HumidiFi/TesseraV 缺失时当作矩阵级 failover（会引入 **aggregator 选择偏置**：只替换一家）。
- **Drop-in 可用性（三家矩阵）：否。** Drop-in（仅 BisonFi 列）：条件性可用，**本 issue 不建议接入**（不完整覆盖 + 额外依赖 + 1 rps）。

HumidiFi / TesseraV：无 Q2 表（Q1 未通过）。

---

## 6. 降级路径评估

### 6.1 链上 realized prices（swap events）

- **能做：** 订阅各 prop program 的成功 swap，推导成交价、滞后、健康度。
- **不能做：** 在任意请求 `notional` 上生成 WHI-799 `Quote`（无 size 控制、有 survivor bias、滞后）。
- **产品角色：** Jupiter stale/outage 时的 **health / sanity** 信号，**不是** 矩阵单元格填充。EVM 侧类比 WHI-797 §7.7 `TesseraTrade`。

### 6.2 直接 on-chain quoting

- Prop AMM 闭源、私有 IDL/oracle 驱动定价（Solana Foundation *Understanding Proprietary AMMs*；WHI-797 §2）。
- **结论：关闭该选项**——无法从账户状态可靠重建与 aggregator 同口径的 pre-trade quote。

### 6.3 显式降级（推荐）

当 Jupiter 超时 / 429 / 5xx / 维护：

1. Solana prop 列（HumidiFi / TesseraV / BisonFi）→ **unavailable**（已有 adapter 错误态 / FE status SSOT）。
2. **禁止** 用 Titan 只填 BisonFi、或用未验证 OKX 半表糊数，以免 **aggregator 差异伪装成 venue 价差**（Q2 动机）。
3. 与 WHI-836 正交：836 修吞吐；本结论修 **无第二供应商** 时的诚实 UX。

---

## 7. 推荐

| 选项 | 决定 |
| --- | --- |
| 采用某冗余源做生产 failover | **否**（无三家齐备的 live 源） |
| 采用 Titan DART 作 BisonFi 旁路 | **否**（覆盖不全；会污染矩阵可比性） |
| 接受 Jupiter SPOF + 显式降级 | **是**（默认） |
| 申请 DFlow / OKX key 后重测 | **是**（研究跟进，非阻塞实现） |
| Metis v1 → Swap V2 迁移跟踪 | **是**（同供应商；另开/挂在 836 后续） |

**推理一句话：** 冗余的价值在于 **故障域分离 + 口径可比**；目前唯一 live 可隔离的「第二源」既 **不覆盖三家**，又引入 ~1 bps 系统偏差——不如在 outage 时诚实空窗。

---

## 8. 风险与后续

| 项 | 说明 |
| --- | --- |
| Jupiter 停服 / `dexes` 语义变更 | 矩阵 Solana prop 全空；靠显式降级 |
| Metis v1 废弃 | 迁 V2（同 SPOF）；已 live 确认 V2 `dexes` |
| DFlow/OKX 未来变完整冗余 | 需 key + Q1 三家样本 + Q2 表；**通过后** 再 ADR 修订 + 实现 issue |
| Titan DART 1 rps | 即便未来补齐 venue，吞吐也不够矩阵热路径（仍要 Gateway） |

**建议 follow-up issue（研究，非实现）：**  
「Re-run WHI-837 Q1/Q2 with DFlow + OKX API keys」— 阻塞于凭证；若任一家三家齐备且 Q2 ≤ ~2 bps，再开 adapter 实现单。

---

## 9. 参考

- WHI-797：`docs/research/WHI-797-prop-amm-jupiter-quote-api.md` §2, §3.1, §3.5, §4, §7.7, §9  
- WHI-799：`docs/research/WHI-799-spread-fee-data-model.md` §4.1, §4.4  
- Titan DART：https://titan-exchange.gitbook.io/titan/developer-doc/dart-swap-api/overview.md  
- Titan routing filters：https://titan-exchange.gitbook.io/titan/developer-doc/swap-api/guides/configure-routing.md  
- DFlow quote OpenAPI：https://pond.dflow.net/resources/trading-api/imperative/quote  
- DFlow venues：https://pond.dflow.net/spot/liquidity-venues  
- DFlow API keys：https://pond.dflow.net/get-started/api-key  
- Helius on DFlow + prop AMMs：https://www.helius.dev/blog/dflow  
- OKX get quote / liquidity：https://web3.okx.com/onchainos/dev-docs/trade/dex-get-quote  
- 0x Solana swap-instructions：https://docs.0x.org/api-reference/solana-swap-ap-is/swap/instructions.md  
- 1inch swap modes：https://business.1inch.com/portal/documentation/apis/swap  
- Solana.com Understanding Proprietary AMMs：https://solana.com/news/understanding-proprietary-amms  

---

## 10. 产出物清单

| 路径 | 说明 |
| --- | --- |
| `docs/research/WHI-837-solana-prop-amm-quote-redundancy.md` | 本文 |
| `docs/research/samples/whi-837/` | live 样本（见该目录 `README.md`） |
| `docs/adr/0001-solana-prop-amm-jupiter-sole-path.md` | 接受 Jupiter  sole path + 显式降级 |
| WHI-797 §9 更新 | 风险行指向本文 |
