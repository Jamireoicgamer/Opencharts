# Charts: indicators and drawings

## Indicators

Choose **Indicators** (the wavy-line button above the chart, top right) to add or remove them. They're saved to your account, so they appear on every device you sign in from. You can have up to 10 at once.

| Indicator | Where | Default | How it's calculated |
|---|---|---|---|
| Simple moving average (SMA) | On the price | 20 bars | The average close of the last *n* bars |
| Exponential moving average (EMA) | On the price | 20 bars | Weights recent closes more: k = 2/(n+1), starting from the SMA of the first *n* bars |
| Bollinger Bands | On the price | 20 bars, 2 deviations | The SMA, with bands 2 standard deviations (population) above and below |
| VWAP | On the price | — | The volume-weighted average of (high + low + close)/3, restarting each day (UTC) |
| Volume | Bottom of the price pane | — | Each bar's traded volume, green on up bars and red on down bars |
| RSI | Its own pane | 14 bars | Wilder's relative strength index, with guide lines at 70 and 30 |
| MACD | Its own pane | 12, 26, 9 | EMA 12 minus EMA 26, a 9-bar EMA of that (signal), and their difference (histogram) |

You can add SMA and EMA more than once with different periods, for example EMA 20 and EMA 50. Periods can be from 2 to 400 bars.

Hover over the chart to read every indicator's value at that bar; otherwise the readout shows the latest values. Indicators update with live prices.

An indicator needs enough history before it has a value: an EMA 50 starts at the 50th bar, MACD's signal line at the 34th. On short periods, such as 1D, some may not appear. Choose a longer period if so.

**Every value is calculated by fixed formulas in your browser, never by AI.** The same formulas are written twice, once in TypeScript for the app and once in Python as a reference, and tests check that the two agree to nine decimal places on real market data. The reference also matches Wilder's own RSI example.

VWAP and volume need volume data. Most sources supply it for crypto and shares; where a source doesn't, those indicators stay empty rather than guessing.

## Drawings

Choose **Draw** (the pen above the chart's price scale), then a tool:

| Tool | How to place it |
|---|---|
| Trend line | Click the start, then the end |
| Horizontal level | Click the price |
| Rectangle | Click one corner, then the opposite corner |
| Fibonacci retracement | Click the start of the swing, then its end. Levels are drawn at 0, 23.6, 38.2, 50, 61.8, 78.6 and 100% |
| Note | Click where it goes, then type its text |

While a tool is active the chart doesn't pan, so clicks place points. Press **Esc** to stop.

**To change a drawing,** click it. A small toolbar shows its colour, its label (for levels, rectangles and notes) and **Delete**. Drag the shape to move it, or drag one of its corner handles to reshape it. **Delete** or **Backspace** removes the selected drawing, and **Esc** lets go of it. On a phone, tap instead of clicking.

**To remove every drawing** on the instrument, use the bin button in the drawing tools.

Drawings are saved to your account for each instrument, in time and price. They stay in place when you scroll, zoom or switch period, and they appear on your other devices. They're included when you export your workspace (**Settings → Your data**), so they move between the desktop app and a server.
