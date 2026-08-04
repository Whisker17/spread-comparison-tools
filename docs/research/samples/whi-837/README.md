# WHI-837 live samples

Captured 2026-08-04 (UTC+8 session / UTC day). Evidence for Solana prop AMM quote redundancy research.

## Jupiter baseline (Metis v1 `dexes` isolation)

- `jup-{humidifi,tesserav,bisonfi}-sol-usdc-{1e8,1e9,1e10}.json` — direct-route isolation at 0.1 / 1 / 10 SOL
- `jup-wrong-label.json` — `dexes=NotAVenue` → 400 `No routes found`
- `jup-v2-quote-*.json` — Swap V2 still routes; same Jupiter upstream (not a redundancy path)

## Titan DART (free keyless)

- `titan-dart-markets.json` — supported pairs
- `titan-dart-include-BisonFi-sol-usdc-1sol.json` — isolation works for BisonFi
- `titan-dart-include-HumidiFi-sol-usdc-1sol.json` / `...TesseraV...` — `No routes found` for baseline labels
- `titan-dart-wrong-label-sol-usdc.json` — same error shape as missing venue
- `titan-dart-nofilter-sol-usdc-1sol.json` — unfiltered DART quote

## Q2 divergence (BisonFi × WHI-799 notional tiers)

- `q2-bisonfi-divergence.json` — summary table
- `q2-bisonfi-n{1000,10000,100000,1000000}-{jup,titan}.json` — paired captures

## Auth / access negatives

- `okx-get-liquidity-unauth.json` — OKX requires `OK-ACCESS-KEY`
- `0x-enabled-sources-unauth.json` — 0x Solana requires `0x-api-key`
- `titan-gateway-unauth.txt` — Titan Gateway requires bearer token
- `dflow-venues-403.meta.txt` — DFlow `quote-api.dflow.net` empty 403 (no keyless body)
