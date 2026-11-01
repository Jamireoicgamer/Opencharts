# Market data

OpenChart shows prices only from real sources, and always says which source, how delayed and as of when. If no source covers an instrument, the chart says so rather than drawing anything.

## Sources

| Source | Covers | Delay | Needs |
|---|---|---|---|
| **Coinbase** | Crypto (BTC, ETH, SOL, …) | Real-time, streamed | Nothing: on by default |
| **Kraken** | Crypto | Real-time, polled every 10 s | Nothing: on by default, used when Coinbase fails |
| **Yahoo Finance** | UK and US shares, ETFs, indices, FX, crypto | Delayed (Yahoo doesn't say by how much; the time of each price is shown) | The owner accepting Yahoo's terms |
| **Twelve Data** | US shares and ETFs, FX, crypto. UK shares need a paid Twelve Data plan and aren't used yet | Shown as delayed | Your own API key ([free plan](https://twelvedata.com/pricing): 8 requests a minute) |

Sources are tried in the order shown in **Settings → Data sources**. If one fails twice for an instrument, the next source that covers it takes over for five minutes.

## Turning sources on (owner or admin)

1. Open **Settings** in the left rail (the bottom bar on a phone), then **Data sources**. You'll be asked to confirm your sign-in if you haven't recently.
2. **UK and US shares, the simple way:** tick the Yahoo Finance terms box. This also switches Yahoo on.
   - Yahoo's data is for personal, non-commercial use.
   - The feed is unofficial and can stop working without notice.
   - Don't use it to share data with others.
3. **With your own key:** paste a Twelve Data API key and choose **Save key**.
   - The key is encrypted with the server's master key before it's stored.
   - It's only ever sent to Twelve Data, and it's never shown again; only its last four characters are.
4. Use the switches and the arrow to choose which sources run, and in what order.

Changes apply at once for everyone on the server. Members can see which sources are in use.

## What you'll see

- **The price header** shows a label such as "Coinbase · real-time · 14:03:22" or "Yahoo Finance · delayed · as of 16:30". It adds "market closed" outside trading hours.
- **The chart:**
  - **1D** shows 5-minute bars of the last session;
  - **1W** and **1M** show hourly bars;
  - **3M** and **1Y** show daily bars;
  - **ALL** shows weekly bars.
  - Live prices move the last bar.
- **The footer** shows the live connection:
  - "LIVE PRICES" means it's streaming.
  - "UPDATING EVERY 15 S" means a proxy is blocking WebSockets, so the app is polling instead.
- **Holdings** show market value and unrealised profit in each instrument's currency. Pence (GBX) holdings are valued in pounds. Totals are per currency; nothing is converted between currencies yet.
- **Price alerts** are checked on the server, even with no browser open. When one fires you see a notice in the app, and the alert is marked **Triggered**; choose **Re-arm** to use it again. Phone, email and ntfy notifications arrive in M6.

## History is fetched once

Price history is saved in your database the first time a chart needs it. After that, only the newest bars are fetched again, and opening a longer period fetches only the older part. If every source fails, the chart shows the saved bars and says so.

## Network access

The server needs outbound HTTPS to the sources you turn on:

- Coinbase: `api.exchange.coinbase.com`, `ws-feed.exchange.coinbase.com`
- Kraken: `api.kraken.com`
- Yahoo Finance: `query1.finance.yahoo.com`
- Twelve Data: `api.twelvedata.com`

If a source can't be reached, the server log says which one and why, for example `WARNING: openchart_api.market.hub: coinbase feed for CRYPTO:BTC-USD failed: …`.

## Rate limits

Yahoo's unofficial endpoint limits how often it can be asked. OpenChart asks Yahoo once a minute per instrument, and identifies itself honestly rather than pretending to be a browser. If Yahoo refuses, the price shows as "not responding", and another enabled source takes over if one covers the instrument.

## Status

Checked against the live services on 1 November 2026:

- **Coinbase**: real-time BTC streamed (about 3 updates a second), with history from its candles API.
- **Kraken**: took over seamlessly when Coinbase was switched off.
- **Yahoo Finance**: BAE (in pence) and NVIDIA quotes labelled "delayed · as of …" and "market closed" at the weekend, with daily and hourly history.
- **The cache**: a year of daily BTC history took 563 ms the first time and 18 ms the second.
- **Alerts**: a BTC alert fired one second after it was set, while the price was live.

The adapter tests use responses recorded from these services (`apps/api/scripts/record_market_fixtures.py`).

**Twelve Data** is built and tested against its documented formats, but hasn't been tried with a real key yet. If you use it and something looks wrong, please open an issue with the server log lines.
