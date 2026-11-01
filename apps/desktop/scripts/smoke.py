# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke test of the desktop app's stack, with no window.

    uv run python apps/desktop/scripts/smoke.py -- <openchart-stack and its options>

Starts the stack on a fresh data folder, then, through the API the window
uses:
- sets up the owner with the start URL's token,
- adds BTC to the watchlist and waits for a live Coinbase price,
- exports the workspace, stops, starts again, signs in, and checks that the
  watchlist survived.
"""

import json
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import httpx2

OWNER = {
    "display_name": "Desktop smoke test",
    "email": "owner@example.com",
    "password": "correct horse battery staple",
}
BTC = "CRYPTO:BTC-USD"


def step(message: str) -> None:
    print(f"• {message}", flush=True)


class Running:
    def __init__(self, command: list[str]) -> None:
        self.process = subprocess.Popen(  # noqa: S603 - the caller's own command line
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True
        )
        line = self.process.stdout.readline() if self.process.stdout else ""
        if not line:
            raise SystemExit(f"stack failed to start (exit {self.process.wait()})")
        self.info: dict[str, Any] = json.loads(line)
        origin = self.info["origin"]
        self.client = httpx2.Client(base_url=origin, headers={"Origin": origin}, timeout=30)

    def stop(self) -> None:
        self.client.close()
        if self.process.stdin:
            self.process.stdin.close()
        rest = self.process.stdout.read() if self.process.stdout else ""
        code = self.process.wait(timeout=60)
        if code != 0 or '"stopped"' not in rest:
            raise SystemExit(f"stack did not stop cleanly (exit {code})")


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


def main() -> None:
    command = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    check(bool(command), "pass the openchart-stack command after --")

    step("first start on a fresh data folder")
    started = time.monotonic()
    stack = Running(command)
    step(f"up in {time.monotonic() - started:.1f} s at {stack.info['origin']}")
    http = stack.client
    check(urlsplit(stack.info["origin"]).hostname == "localhost", "served on localhost")
    token = stack.info["setup_token"]
    check(bool(token) and stack.info["start_url"].endswith(f"/setup#token={token}"), "setup URL")

    page = http.get("/setup")
    check(page.status_code == 200 and "<div id=" in page.text, "web app is served")
    check("default-src 'self'" in page.headers["content-security-policy"], "CSP is sent")

    owner = http.post("/api/setup", json={**OWNER, "setup_token": token})
    check(owner.status_code == 201, f"owner setup: {owner.status_code} {owner.text}")
    check(http.get("/api/auth/me").json()["role"] == "owner", "signed in as owner")

    check(http.post("/api/watchlist", json={"instrument_id": BTC}).status_code == 201, "watch BTC")
    step("waiting for a live BTC price")
    quote: dict[str, Any] | None = None
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        quote = http.get("/api/market/quotes", params={"ids": BTC}).json()[0]["quote"]
        if quote:
            break
        time.sleep(1)
    if quote is None:
        raise SystemExit("FAILED: no live BTC quote arrived")
    price = f"{quote['price']} {quote['currency']}"
    step(f"BTC {price}, {quote['source']} {quote['delay']}, as of {quote['at']}")
    check(float(quote["price"]) > 0, "price is positive")

    candles = http.get(f"/api/market/candles/{BTC}", params={"period": "1W"})
    check(candles.status_code == 200 and len(candles.json()["candles"]) > 24, "history loads")

    export = http.get("/api/export").json()
    check(export["watchlist"] == [BTC], "export holds the watchlist")
    stack.stop()
    step("stopped cleanly")

    step("second start")
    stack = Running(command)
    http = stack.client
    check(stack.info["setup_token"] is None, "no setup on the second start")
    login = http.post(
        "/api/auth/login", json={"email": OWNER["email"], "password": OWNER["password"]}
    )
    check(login.status_code == 200, f"sign in: {login.status_code} {login.text}")
    watchlist = [item["id"] for item in http.get("/api/watchlist").json()]
    check(watchlist == [BTC], f"watchlist survived a restart: {watchlist}")
    stack.stop()
    step("all checks passed")


if __name__ == "__main__":
    main()
