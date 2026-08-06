# WHI-890 raw probe artifacts

Live survey capture for [WHI-890](https://linear.app/whisker-personal/issue/WHI-890) (2026-08-06 UTC).

| File | Contents |
| --- | --- |
| `bsc_tokens.json` | Per-ticker BSC address, decimals, on-chain symbol/name, pool TVL/vol, provenance |
| `pancake_extended_stock_tokens.json` | Subset of PancakeSwap extended tokenlist matching catalog underlyings |
| `dex_pools.json` | DexScreener search hits (first-pass discovery) |
| `gecko_pools.json` | GeckoTerminal search (partial — 429 after a handful of queries) |
| `kyber_tessera_probes.json` | KyberSwap `includedSources=tessera` probes at $100 / $1k / $10k both sides |
| `jup_prop_xstock_probes.json` | Jupiter `onlyDirectRoutes=true&dexes=` probes per mint × {HumidiFi,TesseraV,BisonFi} × both sides @ ~$1k |
| `xstock_mints.json` | Solana xStock mint map for catalogued underlyings |
| `bsc_tokens_transcription.py.txt` | Drop-in `TokenInfo(...)` lines for `BSC_TOKENS` |
| `missing_hunt.json` | Negative hunt for thin/missing symbols |

Machine-readable matrix: [`../WHI-890-underlying-form-venue-matrix.tsv`](../WHI-890-underlying-form-venue-matrix.tsv).  
Narrative: [`../../WHI-890-stock-dex-prop-amm-coverage-survey.md`](../../WHI-890-stock-dex-prop-amm-coverage-survey.md).
