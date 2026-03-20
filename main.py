#!/usr/bin/env python3
"""
Aerodrome Base Chain Alert Bot - Upgraded Version
Monitors 5 Aerodrome pools on Base, sends Telegram snapshots + alerts.
Features: all pools, USD TVL approx, whale detection, reliable RPC fallbacks.
"""

import os
import time
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

RPC_URLS = [
    "https://mainnet.base.org",
    "https://rpc.ankr.com/base",
    "https://base.llamarpc.com",
    "https://base-mainnet.public.blastapi.io",
    "https://base-rpc.publicnode.com",
]

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

POLL_INTERVAL = 30          # seconds between checks (increase if rate-limited)
SUMMARY_INTERVAL = 1800     # seconds (\~30 min) for full summary snapshot
COOLDOWN_SECONDS = 300      # 5 min cooldown per alert rule

# ── Pools (same as dashboard) ──────────────────────────────────────────────────

POOLS = [
    {"address": "0xcDAC0d6c6C59727a65F871236188350531885C43", "name": "WETH/USDC",   "token0": "WETH", "token1": "USDC",   "stable": False, "decimals0": 18, "decimals1": 6},
    {"address": "0x7c2eA10D3e5922ba3bBBafa39Dc0f59b3C1F2cC", "name": "WETH/cbETH",  "token0": "WETH", "token1": "cbETH",  "stable": False, "decimals0": 18, "decimals1": 18},
    {"address": "0xB4885Bc63399BF5518b994c1545d85688b7f710a", "name": "USDC/USDbC", "token0": "USDC", "token1": "USDbC", "stable": True,  "decimals0": 6,  "decimals1": 6},
    {"address": "0x6cDcb1C4A4D1C3C6d054b27AC5B77e89eAFb971b", "name": "AERO/WETH",  "token0": "AERO", "token1": "WETH",   "stable": False, "decimals0": 18, "decimals1": 18},
    {"address": "0x2578365B3dfFa79b79cA3E09f5A6c05A19bfE46", "name": "USDC/DAI",    "token0": "USDC", "token1": "DAI",    "stable": True,  "decimals0": 6,  "decimals1": 18},
]

# Approximate prices (updated periodically via Coingecko) — fallback values
PRICES = {
    "WETH": 2150.0,     # ETH \~$2150
    "cbETH": 2400.0,
    "USDC": 1.0,
    "USDbC": 1.0,
    "AERO": 0.325,
    "DAI": 1.0,
}

# ── Alert Rules (now applied to all matching pools) ─────────────────────────────

ALERT_RULES = [
    {"pool_name": "WETH/USDC", "type": "tvl_below", "threshold": 2000, "message": "⚠️ {pool} reserve0 dropped below {threshold} WETH!"},
    {"pool_name": None, "type": "reserve_change_pct", "threshold": 10.0, "message": "🚨 WHALE ALERT: {pool} reserve change >{threshold}%!"},  # None = all pools
]

_last_data = {}          # previous snapshot for change detection
_alert_cooldowns = {}    # rule_key -> last sent timestamp

# ── Helpers ────────────────────────────────────────────────────────────────────

def rpc_call(method, params):
    for url in RPC_URLS:
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=10)
            r.raise_for_status()
            result = r.json()
            if "result" in result:
                return result["result"]
        except Exception as e:
            print(f"RPC {url} failed: {e}")
            continue
    raise RuntimeError("All RPC endpoints failed")

def get_block_number():
    hex_num = rpc_call("eth_blockNumber", [])
    return int(hex_num, 16) if hex_num else 0

def get_reserves(address):
    data = rpc_call("eth_call", [{"to": address, "data": "0x0902f1ac"}, "latest"])
    if not data or data == "0x":
        return None
    r0 = int(data[2:66], 16)
    r1 = int(data[66:130], 16)
    return r0, r1

def fetch_prices():
    try:
        url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum,aerodrome-finance,coinbase-wrapped-staked-eth&vs_currencies=usd"
        resp = requests.get(url, timeout=8).json()
        PRICES["WETH"] = resp.get("ethereum", {}).get("usd", PRICES["WETH"])
        PRICES["AERO"] = resp.get("aerodrome-finance", {}).get("usd", PRICES["AERO"])
        PRICES["cbETH"] = resp.get("coinbase-wrapped-staked-eth", {}).get("usd", PRICES["cbETH"])
        print("Prices updated:", PRICES)
    except Exception as e:
        print("Coingecko fetch failed:", e)

def fetch_all_pools():
    snapshot = {}
    for pool in POOLS:
        reserves = get_reserves(pool["address"])
        if reserves:
            r0_raw, r1_raw = reserves
            r0 = r0_raw / (10 ** pool["decimals0"])
            r1 = r1_raw / (10 ** pool["decimals1"])
            p0 = PRICES.get(pool["token0"], 1.0)
            p1 = PRICES.get(pool["token1"], 1.0)
            tvl_usd = (r0 * p0) + (r1 * p1)
            ratio = r1 / r0 if r0 > 0 else 0

            snapshot[pool["name"]] = {
                "reserve0": r0,
                "reserve1": r1,
                "ratio": ratio,
                "tvl_usd": tvl_usd,
                "raw_r0": r0_raw,
                "raw_r1": r1_raw,
            }
    return snapshot

def build_summary(snapshot):
    lines = ["🔵 <b>Aerodrome Base — Pool Snapshot</b>"]
    lines.append(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    lines.append("")
    for name, data in snapshot.items():
        lines.append(f"<b>{name}</b>")
        lines.append(f"Reserve0: {data['reserve0']:.4f} {name.split('/')[0]}")
        lines.append(f"Reserve1: {data['reserve1']:,.4f} {name.split('/')[1]}")
        lines.append(f"Ratio: {data['ratio']:.8f}")
        lines.append(f"TVL ≈ ${data['tvl_usd']:,.0f}")
        lines.append("")
    return "\n".join(lines)

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[Telegram] Not configured — skipping send")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send failed: {e}")

def check_alerts(snapshot):
    now = time.time()
    for pool_name, data in snapshot.items():
        prev = _last_data.get(pool_name, {})
        if not prev:
            continue

        # Whale detection (reserve change %)
        for rule in [r for r in ALERT_RULES if r["type"] == "reserve_change_pct" and (r["pool_name"] is None or r["pool_name"] == pool_name)]:
            chg0 = abs((data["reserve0"] - prev["reserve0"]) / prev["reserve0"]) * 100 if prev["reserve0"] > 0 else 0
            chg1 = abs((data["reserve1"] - prev["reserve1"]) / prev["reserve1"]) * 100 if prev["reserve1"] > 0 else 0
            max_chg = max(chg0, chg1)
            if max_chg >= rule["threshold"]:
                rule_key = f"whale_{pool_name}"
                if now - _alert_cooldowns.get(rule_key, 0) > COOLDOWN_SECONDS:
                    msg = rule["message"].format(pool=pool_name, threshold=rule["threshold"])
                    send_telegram(msg)
                    _alert_cooldowns[rule_key] = now

        # Other rules (tvl_below etc.)
        for rule in [r for r in ALERT_RULES if r["pool_name"] == pool_name]:
            triggered = False
            detail = ""
            if rule["type"] == "tvl_below" and data["reserve0"] < rule["threshold"]:
                triggered = True
                detail = f"reserve0 = {data['reserve0']:.4f}"
            # Add more types if needed

            if triggered:
                rule_key = f"{rule['type']}_{pool_name}"
                if now - _alert_cooldowns.get(rule_key, 0) > COOLDOWN_SECONDS:
                    msg = rule["message"].format(pool=pool_name, threshold=rule["threshold"])
                    if detail:
                        msg += f"\n<code>{detail}</code>"
                    send_telegram(msg)
                    _alert_cooldowns[rule_key] = now

    _last_data.update(snapshot)

# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 70)
    print("  Aerodrome Base Alert Bot — Upgraded")
    print("  Pools:", ", ".join(p["name"] for p in POOLS))
    print("  Polling every", POLL_INTERVAL, "s | Summary every", SUMMARY_INTERVAL//60, "min")
    print("  Telegram:", "✅ ready" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "❌ console only")
    print("=" * 70)

    iteration = 0
    last_summary = 0

    while True:
        time.sleep(POLL_INTERVAL)
        iteration += 1
        ts = datetime.utcnow().strftime("%H:%M:%S UTC")

        try:
            fetch_prices()  # update prices occasionally
            block = get_block_number()
            snapshot = fetch_all_pools()

            print(f"[{ts}] Block #{block:,} | Pools: {len(snapshot)}")

            check_alerts(snapshot)

            # Periodic full summary
            if time.time() - last_summary > SUMMARY_INTERVAL:
                summary = build_summary(snapshot)
                send_telegram(summary)
                last_summary = time.time()
                print("Sent full summary")

        except Exception as e:
            print(f"[!] Error: {e}")
            time.sleep(60)  # backoff

if __name__ == "__main__":
    main()
