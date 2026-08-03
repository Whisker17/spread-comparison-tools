# spread-comparison-tools

Tools and research for comparing execution quality / spreads across Solana venues (CEX, public DEX, prop AMM).

## Status

Early research phase (M1). No application runtime yet.

## Research

| Issue | Doc |
| --- | --- |
| WHI-797 — Prop AMM baseline + multichain quote API validation (Jupiter / KyberSwap) | [docs/research/WHI-797-prop-amm-jupiter-quote-api.md](docs/research/WHI-797-prop-amm-jupiter-quote-api.md) |
| WHI-798 — Asset category inventory (blue chips / stocks / others) | [docs/research/WHI-798-asset-category-inventory.md](docs/research/WHI-798-asset-category-inventory.md) |
| WHI-799 — Spread & fee metrics + unified data model (spec) | [docs/research/WHI-799-spread-fee-data-model.md](docs/research/WHI-799-spread-fee-data-model.md) |

## Baseline prop AMMs (confirmed — venue × chain)

| Venue | Chain | Quote source | Venue filter value | Identifier |
| --- | --- | --- | --- | --- |
| HumidiFi | Solana | Jupiter `dexes` | `HumidiFi` | program `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp` |
| Tessera | Solana | Jupiter `dexes` | `TesseraV` | program `TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH` |
| Tessera | Base | KyberSwap `includedSources` | `tessera` | contract `TesseraSwap 0x5555…9E3e`; pairs: WETH, cbBTC, AERO, VIRTUAL, EURC (all vs USDC) |
| Tessera | BSC | KyberSwap `includedSources` | `tessera` | same contract; pairs: BTCB + **tokenized stocks QQQB/SPCXB/NVDAB/NVDAon** (all vs USDT) |
| BisonFi | Solana | Jupiter `dexes` | `BisonFi` | program `BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi` |

Tessera volume is **majority BSC** (DefiLlama 7d: BSC ≈ $136M/d, Solana ≈ $34M/d, Base ≈ $9.5M/d) — Solana-only coverage misses most of it. HumidiFi / BisonFi are Solana-only.

Quote paths for WHI-806 (isolate **one** venue per request):

```text
# Solana
GET https://api.jup.ag/swap/v1/quote
  ?inputMint=...&outputMint=...&amount=...
  &dexes=HumidiFi            # or TesseraV / BisonFi (exact, case-sensitive)

# Base / BSC
GET https://aggregator-api.kyberswap.com/{base|bsc}/api/v1/routes
  ?tokenIn=...&tokenOut=...&amountIn=...
  &includedSources=tessera   # lowercase source id
```

Jupiter labels are **comma-separated** if you ever pass multiple DEXes (e.g. `dexes=Raydium,Orca+V2`); for prop-AMM isolation pass a single exact label, never `|`. Full details: `docs/research/WHI-797-prop-amm-jupiter-quote-api.md` §7.
