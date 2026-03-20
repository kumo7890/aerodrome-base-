#!/usr/bin/env python3
"""
Aerodrome Base Alert Bot — FINAL + WHALE ALERTS
- DexScreener search
- Fixed price calc
- Whale detection (>10% TVL/reserve change)
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT  = os.getenv("TELEGRAM_CHAT_ID")

POLL_INTERVAL = 100         # 5 minutes
WHALE_THRESHOLD_PCT = 10.0  # % change to trigger alert
WHALE_COOLDOWN_SEC = 600    # 10 minutes per pool

# Last known TVL per pool (for change detection)
_last_tvl = {}

POOLS = [
    {"name": "WETH/USDC",   "search": "WETH USDC base aerodrome"},
    {"name": "WETH/cbETH",  "search": "WETH cbETH base aerodrome"},
    {"name": "USDC/USDbC",  "search": "USDC USDbC base aerodrome"},
    {"name": "AERO/WETH",   "search": "AERO WETH base aerodrome"},
    {"name": "USDC/DAI",    "search": "USDC DAI base aerodrome"},
]

def send_telegram(text, is_alert=False):
    if not TOKEN or not CHAT:
        print(text)
        return
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT, "text": text, "parse_mode": "HTML"})

def get_snapshot():
    global _last_tvl
    lines = ["🔵 <b>Aerodrome Base — Full Snapshot</b>",
             datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), ""]

    current_tvl = {}

    for p in POOLS:
        try:
            url = f"https://api.dexscreener.com/latest/dex/search?q={p['search']}"
            data = requests.get(url, timeout=10).json()
            
            pair = next((item for item in data.get("pairs", []) 
                        if "aerodrome" in item.get("dexId", "").lower() 
                        and "base" in item.get("chainId", "").lower()), None)
            
            if not pair:
                lines.append(f"<b>{p['name']}</b> — no data\n")
                continue

            reserve0 = float(pair.get("liquidity", {}).get("base", 0))
            reserve1 = float(pair.get("liquidity", {}).get("quote", 0))
            tvl_usd  = float(pair.get("liquidity", {}).get("usd", 0))
            dex_price = float(pair.get("priceUsd", 0)) or 0

            base_token = pair.get("baseToken", {}).get("symbol", "").upper()
            quote_token = pair.get("quoteToken", {}).get("symbol", "").upper()

            if reserve0 > 0:
                calculated_price = reserve1 / reserve0
            else:
                calculated_price = dex_price

            if 1000 < calculated_price < 4000 and ("WETH" in base_token or "cbETH" in base_token):
                display_price = calculated_price
            else:
                display_price = dex_price if dex_price > 0 else calculated_price

            lines.append(f"<b>{p['name']}</b>")
            lines.append(f"Reserve0 ({base_token}): {reserve0:,.2f}")
            lines.append(f"Reserve1 ({quote_token}): {reserve1:,.0f}")
            lines.append(f"TVL: ${tvl_usd:,.0f}")
            lines.append(f"Price: ${display_price:,.2f}")
            lines.append("")

            # Save current TVL for next comparison
            current_tvl[p['name']] = tvl_usd

            # Whale check
            if p['name'] in _last_tvl and _last_tvl[p['name']] > 0:
                change_pct = abs(tvl_usd - _last_tvl[p['name']]) / _last_tvl[p['name']] * 100
                if change_pct > WHALE_THRESHOLD_PCT:
                    direction = "+" if tvl_usd > _last_tvl[p['name']] else "-"
                    alert_text = (
                        f"🚨 <b>WHALE ALERT</b>: Big liquidity move in <b>{p['name']}</b>\n"
                        f"Change: {direction}{change_pct:.1f}% | TVL: ${tvl_usd:,.0f} (was ${_last_tvl[p['name']]:,.0f})"
                    )
                    send_telegram(alert_text, is_alert=True)

        except Exception as e:
            lines.append(f"<b>{p['name']}</b> — data unavailable\n")

    _last_tvl = current_tvl  # update for next cycle

    msg = "\n".join(lines)
    send_telegram(msg)
    print("✅ Snapshot sent")

def main():
    print("Bot started — DexScreener + Whale Alerts")
    last = 0
    while True:
        time.sleep(30)
        if time.time() - last > POLL_INTERVAL:
            get_snapshot()
            last = time.time()

if __name__ == "__main__":
    main()
