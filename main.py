#!/usr/bin/env python3
"""
Aerodrome Base Alert Bot — PRICE FIXED VERSION
Correct WETH/USDC price calculation + reliable DexScreener search
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

POOLS = [
    {"name": "WETH/USDC",   "search": "WETH USDC base aerodrome"},
    {"name": "WETH/cbETH",  "search": "WETH cbETH base aerodrome"},
    {"name": "USDC/USDbC",  "search": "USDC USDbC base aerodrome"},
    {"name": "AERO/WETH",   "search": "AERO WETH base aerodrome"},
    {"name": "USDC/DAI",    "search": "USDC DAI base aerodrome"},
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
            url = f"https://api.dexscreener.com/latest/dex/search?q={p['search']}"
            data = requests.get(url, timeout=10).json()
            
            # Find the Aerodrome/Base pair
            pair = next((item for item in data.get("pairs", []) 
                        if "aerodrome" in item.get("dexId", "").lower() 
                        and "base" in item.get("chainId", "").lower()), None)
            
            if not pair:
                lines.append(f"<b>{p['name']}</b> — no data\n")
                continue

            # Reserves
            reserve0 = float(pair.get("liquidity", {}).get("base", 0))
            reserve1 = float(pair.get("liquidity", {}).get("quote", 0))
            tvl_usd  = float(pair.get("liquidity", {}).get("usd", 0))
            dex_price = float(pair.get("priceUsd", 0)) or 0

            # Determine which is WETH side (for price calc)
            base_token = pair.get("baseToken", {}).get("symbol", "")
            quote_token = pair.get("quoteToken", {}).get("symbol", "")
            is_weth_base = "WETH" in base_token.upper()

            # Correct price: quote per base (USDC per WETH if WETH is base)
            if reserve0 > 0:
                calculated_price = reserve1 / reserve0
            else:
                calculated_price = dex_price

            # If calculated looks realistic for WETH pairs (\~2000–3000), use it
            if 1000 < calculated_price < 4000 and ("WETH" in p["name"] or "cbETH" in p["name"]):
                display_price = calculated_price
            else:
                display_price = dex_price if dex_price > 0 else calculated_price

            lines.append(f"<b>{p['name']}</b>")
            lines.append(f"Reserve0 ({base_token}): {reserve0:,.2f}")
            lines.append(f"Reserve1 ({quote_token}): {reserve1:,.2f}")
            lines.append(f"TVL: ${tvl_usd:,.0f}")
            lines.append(f"Price: ${display_price:,.2f}")
            lines.append("")

        except Exception as e:
            lines.append(f"<b>{p['name']}</b> — data unavailable ({str(e)[:30]}...)\n")

    msg = "\n".join(lines)
    send_telegram(msg)
    print("✅ Snapshot sent")

def main():
    print("Bot started — DexScreener with fixed price logic")
    last = 0
    while True:
        time.sleep(30)
        if time.time() - last > POLL_INTERVAL:
            get_snapshot()
            last = time.time()

if __name__ == "__main__":
    main()
