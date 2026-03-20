#!/usr/bin/env python3
"""
Aerodrome Base Chain Alert Bot
Monitors on-chain pool reserves and sends Telegram alerts.

Setup:
  pip install requests python-dotenv

Config:
  Create a .env file with:
    TELEGRAM_BOT_TOKEN=your_bot_token
    TELEGRAM_CHAT_ID=your_chat_id

Get a bot token: message @BotFather on Telegram -> /newbot
Get your chat ID: message @userinfobot on Telegram
"""

import os
import time
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

BASE_RPC = "https://mainnet.base.org"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
POLL_INTERVAL = 15  # seconds

# ── Aerodrome Pools ─────────────────────────────────────────────────────────────

POOLS = [
    {
        "address": "0xcDAC0d6c6C59727a65F871236188350531885C43",
        "name": "WETH/USDC",
        "token0": "WETH",
        "token1": "USDC",
        "stable": False,
        "decimals0": 18,
        "decimals1": 6,
    },
    {
        "address": "0x7c2eA10D3e5922ba3bBBafa39Dc0f59b3C1F2cC",
        "name": "WETH/cbETH",
        "token0": "WETH",
        "token1": "cbETH",
        "stable": False,
        "decimals0": 18,
        "decimals1": 18,
    },
    {
        "address": "0xB4885Bc63399BF5518b994c1545d85688b7f710a",
        "name": "USDC/USDbC",
        "token0": "USDC",
        "token1": "USDbC",
        "stable": True,
        "decimals0": 6,
        "decimals1": 6,
    },
    {
        "address": "0x6cDcb1C4A4D1C3C6d054b27AC5B77e89eAFb971b",
        "name": "AERO/WETH",
        "token0": "AERO",
        "token1": "WETH",
        "stable": False,
        "decimals0": 18,
        "decimals1": 18,
    },
    {
        "address": "0x2578365B3dfFa79b79cA3E09f5A6c05A19bfE46",
        "name": "USDC/DAI",
        "token0": "USDC",
        "token1": "DAI",
        "stable": True,
        "decimals0": 6,
        "decimals1": 18,
    },
]

# ── Alert Rules ─────────────────────────────────────────────────────────────────
# Add your own rules here. Types: "tvl_below", "tvl_above", "ratio_change_pct"

ALERT_RULES = [
    {
        "pool": "WETH/USDC",
        "type": "tvl_below",
        "threshold": 500,           # in token0 units (WETH)
        "message": "⚠️ WETH/USDC reserve0 dropped below 500 WETH!",
    },
    {
        "pool": "WETH/USDC",
        "type": "tvl_above",
        "threshold": 5000,
        "message": "📈 WETH/USDC reserve0 surged above 5000 WETH!",
    },
    {
        "pool": "AERO/WETH",
        "type": "ratio_change_pct",
        "threshold": 5.0,           # percent change triggers alert
        "message": "🔄 AERO/WETH price ratio moved more than 5%!",
    },
]

# ── RPC Helpers ─────────────────────────────────────────────────────────────────

def rpc_call(method, params):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = requests.post(BASE_RPC, json=payload, timeout=10)
    r.raise_for_status()
    result = r.json()
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


def get_block_number():
    return int(rpc_call("eth_blockNumber", []), 16)


def get_reserves(pool_address):
    """Call getReserves() -> (uint112 r0, uint112 r1, uint32 ts)"""
    data = "0x0902f1ac"
    result = rpc_call("eth_call", [{"to": pool_address, "data": data}, "latest"])
    if not result or result == "0x":
        return None, None
    r0 = int(result[2:66], 16)
    r1 = int(result[66:130], 16)
    return r0, r1


def fetch_all_pools():
    snapshot = {}
    for pool in POOLS:
        try:
            r0, r1 = get_reserves(pool["address"])
            if r0 is None:
                continue
            d0, d1 = pool["decimals0"], pool["decimals1"]
            snapshot[pool["name"]] = {
                "reserve0": r0 / (10 ** d0),
                "reserve1": r1 / (10 ** d1),
                "ratio": (r1 / (10 ** d1)) / (r0 / (10 ** d0)) if r0 > 0 else 0,
                "raw0": r0,
                "raw1": r1,
            }
        except Exception as e:
            print(f"  [!] Failed to fetch {pool['name']}: {e}")
    return snapshot

# ── Telegram ────────────────────────────────────────────────────────────────────

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"  [TELEGRAM disabled] {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        print(f"  ✅ Telegram sent: {message[:60]}...")
    except Exception as e:
        print(f"  ❌ Telegram failed: {e}")


def build_summary(snapshot):
    lines = ["<b>🔵 Aerodrome Base — Pool Snapshot</b>", f"<i>{datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>", ""]
    for name, data in snapshot.items():
        lines.append(f"<b>{name}</b>")
        lines.append(f"  Reserve0: {data['reserve0']:.4f}")
        lines.append(f"  Reserve1: {data['reserve1']:.4f}")
        lines.append(f"  Ratio:    {data['ratio']:.6f}")
        lines.append("")
    return "\n".join(lines)

# ── Alert Engine ────────────────────────────────────────────────────────────────

# Track last known ratios to detect changes, and cooldowns to avoid spam
_last_ratios = {}
_alert_cooldowns = {}  # rule_key -> last triggered timestamp
COOLDOWN_SECONDS = 300  # 5 min cooldown per rule


def check_alerts(snapshot, rules):
    now = time.time()
    for i, rule in enumerate(rules):
        pool_name = rule["pool"]
        rule_key = f"{i}_{pool_name}_{rule['type']}"
        data = snapshot.get(pool_name)
        if not data:
            continue

        triggered = False
        detail = ""

        if rule["type"] == "tvl_below":
            if data["reserve0"] < rule["threshold"]:
                triggered = True
                detail = f"reserve0 = {data['reserve0']:.4f} (threshold: {rule['threshold']})"

        elif rule["type"] == "tvl_above":
            if data["reserve0"] > rule["threshold"]:
                triggered = True
                detail = f"reserve0 = {data['reserve0']:.4f} (threshold: {rule['threshold']})"

        elif rule["type"] == "ratio_change_pct":
            current_ratio = data["ratio"]
            last_ratio = _last_ratios.get(pool_name)
            if last_ratio and last_ratio > 0:
                pct_change = abs((current_ratio - last_ratio) / last_ratio) * 100
                if pct_change >= rule["threshold"]:
                    triggered = True
                    detail = f"ratio changed {pct_change:.2f}% ({last_ratio:.6f} → {current_ratio:.6f})"
            _last_ratios[pool_name] = current_ratio

        if triggered:
            last_sent = _alert_cooldowns.get(rule_key, 0)
            if now - last_sent > COOLDOWN_SECONDS:
                msg = f"{rule['message']}\n<code>{detail}</code>"
                send_telegram(msg)
                _alert_cooldowns[rule_key] = now
            else:
                remaining = int(COOLDOWN_SECONDS - (now - last_sent))
                print(f"  [cooldown] {rule_key} — {remaining}s remaining")

# ── Main Loop ───────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Aerodrome Base Alert Bot")
    print("=" * 60)
    print(f"  Polling every {POLL_INTERVAL}s")
    print(f"  Monitoring {len(POOLS)} pools, {len(ALERT_RULES)} rules")
    print(f"  Telegram: {'✅ configured' if TELEGRAM_BOT_TOKEN else '❌ not set (console only)'}")
    print("=" * 60)

    # Send startup summary
    print("\n[startup] Fetching initial snapshot...")
    try:
        block = get_block_number()
        print(f"  Base block: #{block:,}")
        snapshot = fetch_all_pools()
        if snapshot:
            summary = build_summary(snapshot)
            send_telegram(f"🟢 <b>Aerodrome Bot started</b> — block #{block:,}\n\n{summary}")
            for name, data in snapshot.items():
                print(f"  {name}: r0={data['reserve0']:.4f} r1={data['reserve1']:.4f} ratio={data['ratio']:.6f}")
    except Exception as e:
        print(f"  [!] Startup error: {e}")

    iteration = 0
    while True:
        time.sleep(POLL_INTERVAL)
        iteration += 1
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{ts}] Poll #{iteration}")

        try:
            block = get_block_number()
            snapshot = fetch_all_pools()
            print(f"  Block #{block:,} | Pools fetched: {len(snapshot)}")
            check_alerts(snapshot, ALERT_RULES)

            # Send periodic summary every 60 iterations (~15 min)
            if iteration % 60 == 0:
                send_telegram(build_summary(snapshot))

        except KeyboardInterrupt:
            print("\n[stopped] Bot shut down.")
            send_telegram("🔴 <b>Aerodrome Bot stopped.</b>")
            break
        except Exception as e:
            print(f"  [!] Poll error: {e}")


if __name__ == "__main__":
    main()
