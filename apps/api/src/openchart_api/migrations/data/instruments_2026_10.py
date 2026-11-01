# SPDX-License-Identifier: AGPL-3.0-or-later
"""The first instrument catalogue (frozen: later additions go in new migrations).

(id, symbol, name, exchange, currency, asset class). LSE shares are quoted
in pence (GBX); LSE-listed ETFs here trade in pounds (GBP).
"""

INSTRUMENTS: list[tuple[str, str, str, str, str, str]] = [
    # The V4.1 prototype's instruments
    ("LSE:BA.", "BA.", "BAE Systems", "LSE", "GBX", "equity"),
    ("LSE:RR.", "RR.", "Rolls-Royce Holdings", "LSE", "GBX", "equity"),
    ("NASDAQ:GRAB", "GRAB", "Grab Holdings", "NASDAQ", "USD", "equity"),
    ("LSE:MKS", "MKS", "Marks and Spencer Group", "LSE", "GBX", "equity"),
    ("NASDAQ:NVDA", "NVDA", "NVIDIA", "NASDAQ", "USD", "equity"),
    ("CRYPTO:BTC-USD", "BTC-USD", "Bitcoin", "CRYPTO", "USD", "crypto"),
    # London
    ("LSE:AZN", "AZN", "AstraZeneca", "LSE", "GBX", "equity"),
    ("LSE:SHEL", "SHEL", "Shell", "LSE", "GBX", "equity"),
    ("LSE:HSBA", "HSBA", "HSBC Holdings", "LSE", "GBX", "equity"),
    ("LSE:ULVR", "ULVR", "Unilever", "LSE", "GBX", "equity"),
    ("LSE:BP.", "BP.", "BP", "LSE", "GBX", "equity"),
    ("LSE:GSK", "GSK", "GSK", "LSE", "GBX", "equity"),
    ("LSE:RIO", "RIO", "Rio Tinto", "LSE", "GBX", "equity"),
    ("LSE:BARC", "BARC", "Barclays", "LSE", "GBX", "equity"),
    ("LSE:LLOY", "LLOY", "Lloyds Banking Group", "LSE", "GBX", "equity"),
    ("LSE:VOD", "VOD", "Vodafone Group", "LSE", "GBX", "equity"),
    ("LSE:TSCO", "TSCO", "Tesco", "LSE", "GBX", "equity"),
    ("LSE:DGE", "DGE", "Diageo", "LSE", "GBX", "equity"),
    ("LSE:REL", "REL", "RELX", "LSE", "GBX", "equity"),
    ("LSE:LSEG", "LSEG", "London Stock Exchange Group", "LSE", "GBX", "equity"),
    ("LSE:NG.", "NG.", "National Grid", "LSE", "GBX", "equity"),
    ("LSE:BATS", "BATS", "British American Tobacco", "LSE", "GBX", "equity"),
    ("LSE:GLEN", "GLEN", "Glencore", "LSE", "GBX", "equity"),
    ("LSE:IAG", "IAG", "International Consolidated Airlines Group", "LSE", "GBX", "equity"),
    ("LSE:BT.A", "BT.A", "BT Group", "LSE", "GBX", "equity"),
    ("LSE:AV.", "AV.", "Aviva", "LSE", "GBX", "equity"),
    ("LSE:LGEN", "LGEN", "Legal & General Group", "LSE", "GBX", "equity"),
    ("LSE:SBRY", "SBRY", "J Sainsbury", "LSE", "GBX", "equity"),
    ("LSE:PRU", "PRU", "Prudential", "LSE", "GBX", "equity"),
    ("LSE:NWG", "NWG", "NatWest Group", "LSE", "GBX", "equity"),
    ("LSE:IMB", "IMB", "Imperial Brands", "LSE", "GBX", "equity"),
    ("LSE:VUSA", "VUSA", "Vanguard S&P 500 UCITS ETF", "LSE", "GBP", "etf"),
    ("LSE:VWRL", "VWRL", "Vanguard FTSE All-World UCITS ETF", "LSE", "GBP", "etf"),
    ("LSE:VUKE", "VUKE", "Vanguard FTSE 100 UCITS ETF", "LSE", "GBP", "etf"),
    ("LSE:ISF", "ISF", "iShares Core FTSE 100 UCITS ETF", "LSE", "GBX", "etf"),
    # United States
    ("NASDAQ:AAPL", "AAPL", "Apple", "NASDAQ", "USD", "equity"),
    ("NASDAQ:MSFT", "MSFT", "Microsoft", "NASDAQ", "USD", "equity"),
    ("NASDAQ:AMZN", "AMZN", "Amazon.com", "NASDAQ", "USD", "equity"),
    ("NASDAQ:GOOGL", "GOOGL", "Alphabet (Class A)", "NASDAQ", "USD", "equity"),
    ("NASDAQ:META", "META", "Meta Platforms", "NASDAQ", "USD", "equity"),
    ("NASDAQ:TSLA", "TSLA", "Tesla", "NASDAQ", "USD", "equity"),
    ("NASDAQ:AVGO", "AVGO", "Broadcom", "NASDAQ", "USD", "equity"),
    ("NASDAQ:AMD", "AMD", "Advanced Micro Devices", "NASDAQ", "USD", "equity"),
    ("NASDAQ:NFLX", "NFLX", "Netflix", "NASDAQ", "USD", "equity"),
    ("NASDAQ:COST", "COST", "Costco Wholesale", "NASDAQ", "USD", "equity"),
    ("NASDAQ:PLTR", "PLTR", "Palantir Technologies", "NASDAQ", "USD", "equity"),
    ("NASDAQ:QQQ", "QQQ", "Invesco QQQ Trust", "NASDAQ", "USD", "etf"),
    ("NYSE:JPM", "JPM", "JPMorgan Chase", "NYSE", "USD", "equity"),
    ("NYSE:V", "V", "Visa", "NYSE", "USD", "equity"),
    ("NYSE:BRK.B", "BRK.B", "Berkshire Hathaway (Class B)", "NYSE", "USD", "equity"),
    ("NYSE:KO", "KO", "Coca-Cola", "NYSE", "USD", "equity"),
    ("NYSE:DIS", "DIS", "Walt Disney", "NYSE", "USD", "equity"),
    ("NYSE:XOM", "XOM", "Exxon Mobil", "NYSE", "USD", "equity"),
    ("NYSE:WMT", "WMT", "Walmart", "NYSE", "USD", "equity"),
    ("NYSEARCA:SPY", "SPY", "SPDR S&P 500 ETF Trust", "NYSEARCA", "USD", "etf"),
    ("NYSEARCA:VOO", "VOO", "Vanguard S&P 500 ETF", "NYSEARCA", "USD", "etf"),
    # Crypto
    ("CRYPTO:BTC-GBP", "BTC-GBP", "Bitcoin (GBP)", "CRYPTO", "GBP", "crypto"),
    ("CRYPTO:ETH-USD", "ETH-USD", "Ethereum", "CRYPTO", "USD", "crypto"),
    ("CRYPTO:SOL-USD", "SOL-USD", "Solana", "CRYPTO", "USD", "crypto"),
    ("CRYPTO:XRP-USD", "XRP-USD", "XRP", "CRYPTO", "USD", "crypto"),
    ("CRYPTO:ADA-USD", "ADA-USD", "Cardano", "CRYPTO", "USD", "crypto"),
    ("CRYPTO:DOGE-USD", "DOGE-USD", "Dogecoin", "CRYPTO", "USD", "crypto"),
    # Currencies
    ("FX:GBP-USD", "GBP/USD", "British pound / US dollar", "FX", "USD", "fx"),
    ("FX:EUR-USD", "EUR/USD", "Euro / US dollar", "FX", "USD", "fx"),
    ("FX:EUR-GBP", "EUR/GBP", "Euro / British pound", "FX", "GBP", "fx"),
    ("FX:USD-JPY", "USD/JPY", "US dollar / Japanese yen", "FX", "JPY", "fx"),
    # Indices
    ("INDEX:UKX", "UKX", "FTSE 100", "INDEX", "GBP", "index"),
    ("INDEX:SPX", "SPX", "S&P 500", "INDEX", "USD", "index"),
    ("INDEX:NDX", "NDX", "Nasdaq 100", "INDEX", "USD", "index"),
    ("INDEX:DJI", "DJI", "Dow Jones Industrial Average", "INDEX", "USD", "index"),
]

# How the prototype named its instruments, for importing its saved data.
LEGACY_SYMBOLS = {
    "BA.": "LSE:BA.",
    "RR.": "LSE:RR.",
    "GRAB": "NASDAQ:GRAB",
    "MKS": "LSE:MKS",
    "NVDA": "NASDAQ:NVDA",
    "BTC/USD": "CRYPTO:BTC-USD",
}
