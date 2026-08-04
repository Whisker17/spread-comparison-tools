# WHI-839 live samples

Captured 2026-08-04 (UTC). Follow-up to WHI-837: DFlow (keyless **dev** endpoint) + OKX (still unauth).

## DFlow Q1 isolation (`dev-quote-api.dflow.net`)

- `dflow-dev-venues.json` — venue string table (includes `HumidiFi`, `Tessera V`, `BisonFi`)
- `dflow-q1-humidifi-sol-usdc-1sol.json` — `dexes=HumidiFi` → single-leg HumidiFi
- `dflow-q1-tessera_v-sol-usdc-1sol.json` — `dexes=Tessera%20V` → single-leg Tessera V
- `dflow-q1-bisonfi-sol-usdc-1sol.json` — `dexes=BisonFi` → single-leg BisonFi
- `dflow-q1-notavenue-sol-usdc-1sol.json` — invalid label → 400 `Invalid DEX 'NotAVenue'…`
- `dflow-q1-tesserav_nospace-sol-usdc-1sol.json` — `TesseraV` (Jupiter spelling) → 400 invalid
- `dflow-q1-nofilter-sol-usdc-1sol.json` — unfiltered control
- `dflow-prod-venues-403.*` — production `quote-api.dflow.net` still empty **403** without `x-api-key`

## Q2 divergence (DFlow vs Jupiter, WHI-799 notionals)

- `q2-dflow-divergence.json` — summary table + timing / reverse-order controls
- `q2-{humidifi,tesserav,bisonfi}-n{1000,10000,100000,1000000}-{jup,dflow}.json` — paired captures
- `q2-*-retry.json` — re-attempts for cells that failed on first pass
- `q2-mid-jup-humidifi-1sol.json` — mid used only for size conversion
- `q2-control-humidifi-n10000-jup{1,2}.json` — Jupiter-twice timing control
- `q2-control-bisonfi-n10000-reverse-*.json` — DFlow-first reverse-order control

## OKX (still key-blocked)

- `okx-get-liquidity-unauth.json` — 401 `OK-ACCESS-KEY can not be empty`
- `okx-quote-unauth.json` — same
