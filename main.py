#!/usr/bin/env python3
"""
Aerodrome Base Alert Bot — FINAL VERSION (uses The Graph, no RPC issues)
"""

import os
import time
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT  = os.getenv("TELEGRAM_CHAT_ID")

GRAPH_URL = "https://gateway.thegraph.com/api/subgraphs/id/GENunSHWLBXm59mBSgPzQ8metBEp9YDfdqwFr91Av1UM"

POOLS = [
    {"address": "0xcDAC0d6c6C59727a65F871236188350531885C43", "name": "WETH/USDC"},
    {"address": "0x7c2eA10D3e5922ba3bBBafa39Dc0f59b3C1F2cC", "name": "WETH/cbETH"},
    {"address": "0xB4885Bc63399BF5518b994c1545d85688b7f710a", "name": "USDC/USDbC"},
    {"address": "0x6cDcb1C4A4D1C3C6d054b27AC5B77e89eAFb971b", "name": "AERO/WETH"},
    {"address": "0x2578365B3dfFa79b79cA3E09f5A6c05A19bfE46", "name": "USDC/DAI"},
]

def send_telegram(text):
    if not TOKEN or not CHAT:
        print(text)
        return
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT, "text": text, "parse_mode": "HTML"})

def get_snapshot():
    # Build GraphQL query for all 5 pools
    addresses = '", "'.join(p["address"].lower() for p in POOLS)
    query = f"""
    {{
      pairs(where: {{id_in: ["{addresses}"]}}) {{
        id
        name
        reserve0
        reserve1
        token0 {{ symbol }}
        token1 {{ symbol }}
      }}
    }}
    """

    try:
        r = requests.post(GRAPH_URL, json={"query": query}, timeout=15)
        data = r.json()["data"]["pairs"]
        
        lines = ["🔵 <b>Aerodrome Base — Full Snapshot</b>",
                 datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"), ""]
        
        for p in data:
            r0 = float(p["reserve0"])
            r1 = float(p["reserve1"])
            name = p["name"] or f"{p['token0']['symbol']}/{p['token1']['symbol']}"
            lines.append(f"<b>{name}</b>")
            lines.append(f"Reserve0: {r0:,.2f}")
            lines.append(f"Reserve1: {r1:,.2f}")
            lines.append(f"TVL ≈ ${r0 + r1:,.0f} (approx)")
            lines.append("")
        
        send_telegram("\n".join(lines))
        print("✅ Snapshot sent with", len(data), "pools")
        
    except Exception as e:
        print("Graph query failed:", e)

def main():
    print("Bot started using The Graph (no more RPC issues)")
    last = 0
    while True:
        time.sleep(30)
        if time.time() - last > 300:  # every 5 minutes
            get_snapshot()
            last = time.time()

if __name__ == "__main__":
    main()
