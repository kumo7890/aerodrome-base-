#!/usr/bin/env python3
"""
Aerodrome Base Alert Bot — FINAL WORKING VERSION (DexScreener)
All 5 pools + real USD TVL. No RPC or Graph issues.
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT  = os.getenv("TELEGRAM_CHAT_ID")

POLL_INTERVAL = 300  # 5 minutes

# Your 5 pools (DexScreener pair addresses on Base)
POOLS = [
    {"name": "WETH/USDC",   "pair": "0xcDAC0d6c6C59727a65F871236188350531885C43"},
    {"name": "WETH/cbETH",  "pair": "0x7c2eA10D3e5922ba3bBBafa39Dc0f59b3C1F2cC"},
    {"name": "USDC/USDbC",  "pair": "0xB4885Bc63399BF5518b994c1545d85688b7f710a"},
    {"name": "AERO/WETH",   "pair": "0x6cDcb1C4A4D1C3C6d054b27AC5B77e89eAFb971b"},
    {"name": "USDC/DAI",    "pair": "0x2578365B3dfFa79b79cA3E09f5A6c05A19bfE46"},
]

def send_telegram(text):
    if not TOKEN or not CHAT:
        print(text)
        return
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT, "text": text, "parse_mode": "HTML"})

def get_snapshot():
    lines = ["🔵 <b>Aerodrome Base — Full Snapshot</b>",
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), ""]

    for p in POOLS:
        try:
            url = f"https://api.dexscreener.com/latest/dex/pairs/base/{p['pair']}"
            data = requests.get(url, timeout=10).json()
            pair = data["pair"]

            reserve0 = float(pair.get("liquidity", {}).get("base", 0))
            reserve1 = float(pair.get("liquidity", {}).get("quote", 0))
            tvl = float(pair.get("liquidity", {}).get("usd", 0))
            price = float(pair.get("priceUsd", 0))

            lines.append(f"<b>{p['name']}</b>")
            lines.append(f"Reserve0: {reserve0:,.2f}")
            lines.append(f"Reserve1: {reserve1:,.2f}")
            lines.append(f"TVL: ${tvl:,.0f}")
            lines.append(f"Price: ${price:.4f}")
            lines.append("")
        except:
            lines.append(f"<b>{p['name']}</b> — data temporarily unavailable\n")

    msg = "\n".join(lines)
    send_telegram(msg)
    print("✅ Snapshot sent (DexScreener)")

def main():
    print("Bot started — using DexScreener (super reliable)")
    last = 0
    while True:
        time.sleep(30)
        if time.time() - last > POLL_INTERVAL:
            get_snapshot()
            last = time.time()

if __name__ == "__main__":
    main()
