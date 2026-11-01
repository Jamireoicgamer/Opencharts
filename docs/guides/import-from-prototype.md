# Coming from the prototype

The V4.1 prototype (`legacy/index.html`) kept everything in your browser's local storage. The new app keeps it on your server, under your account, so it is the same on every device you sign in from. You can bring your prototype data across; nothing in the prototype is changed or deleted by doing so.

## What comes across

| Prototype | New app |
|---|---|
| Watchlist | Watchlist, in the same order |
| Thesis and its saved revisions | Thesis journal: one version per revision, with the original dates |
| Research notes and the three checklist items | Research notes and checklist, ticks kept |
| Positions | Holdings (account "Other", note "Imported from the prototype"); add an average price and account afterwards |
| Price alerts | Price alerts (checked once live data arrives in M3) |
| Grid, crosshair values, compact layout, risk approach, chart type, period, last instrument | Settings |

Symbols are matched to the new instrument catalogue (`BA.` → `LSE:BA.`, `BTC/USD` → `CRYPTO:BTC-USD`, and so on). Anything the catalogue does not know yet is listed as skipped rather than guessed. Importing the same data again adds nothing twice, so it is safe to retry.

## Option 1: export a file from the prototype (works everywhere)

1. Open the prototype (by default `http://localhost:8081`).
2. Open **Preferences → Privacy → Export my workspace as JSON**. Your browser saves `openchart-workspace.json`.
3. Open the new app, sign in, and choose **Settings** in the left rail (the bottom bar on a phone).
4. Under **Your data**, choose **Import an OpenChart export** and pick the file. A summary shows what was added.

## Option 2: import straight from the browser

Browsers keep local storage separately for each address, so this only works if the prototype was used at the **same address** as the new app (for example, you used to serve `legacy/index.html` where the new app now runs). In that case **Settings** shows "This browser has data from the OpenChart prototype". Choose **Import from this browser**, then optionally **Remove the prototype's copy from this browser** once the summary appears.

## Afterwards

**Settings → Export my workspace** downloads everything in your account as JSON at any time: every thesis version, research, holdings, alerts and preferences.
