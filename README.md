# spread-comparison-tools

Tools and research for comparing execution quality / spreads across Solana venues (CEX, public DEX, prop AMM).

## Status

Early research phase (M1). No application runtime yet.

## Research

| Issue | Doc |
| --- | --- |
| WHI-797 — Prop AMM baseline + Jupiter Quote API validation | [docs/research/WHI-797-prop-amm-jupiter-quote-api.md](docs/research/WHI-797-prop-amm-jupiter-quote-api.md) |

## Baseline prop AMMs (confirmed)

| Venue | Jupiter `dexes` label | Program ID |
| --- | --- | --- |
| HumidiFi | `HumidiFi` | `9H6tua7jkLhdm3w8BvgpTn5LZNU7g4ZynDmCiNN3q6Rp` |
| Tessera | `TesseraV` | `TessVdML9pBGgG9yGks7o4HewRaXVAMuoVj4x83GLQH` |
| BisonFi | `BisonFi` | `BiSoNHVpsVZW2F7rx2eQ59yQwKxzU5NvBcmKshCSUypi` |

Quote path for WHI-806 (isolate **one** venue per request via `dexes` label):

```text
GET https://api.jup.ag/swap/v1/quote
  ?inputMint=...&outputMint=...&amount=...
  &dexes=HumidiFi
  # alternatives: dexes=TesseraV   or   dexes=BisonFi
```

Labels are **comma-separated** if you ever pass multiple DEXes (e.g. `dexes=Raydium,Orca+V2`). For prop-AMM isolation, pass a single exact label. Do not use `|` as a separator.
