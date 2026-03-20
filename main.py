#!/usr/bin/env python3
"""
Aerodrome Base Whale Alert Bot
Monitors pool TVL changes and fires Telegram alerts on big moves.
"""

import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_RPC = "https://base-mainnet.public.blastapi.io"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
POLL_INTERVAL = 60        # poll every 60 seconds
WHALE_THRESHOLD = 0.05    # 5% change = whale alert
COOLDOWN_SECONDS = 300    # 5 min cooldown per pool

POOLS = [
    {"address": "0x70acdf2ad0bf2402c957154f944c19ef4e1cbae1", "name": "WETH/cbBTC",  "token0": "WETH",  "token1": "cbBTC", "d0": 18, "d1": 8 },
    {"address": "0x6cdcb1c4a4d1c3c6d054b27ac5b77e89eafb971d", "name": "USDC/AERO",  "token0": "USDC",  "token1": "AERO",  "d0": 6,  "d1": 18},
    {"address": "0x74f72788f4814d7ff3c49b44684aa98eee140c0e", "name": "WETH/msETH", "token0": "WETH",  "token1": "msETH", "d0": 18, "d1": 18},
    {"address": "0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59", "name": "WETH/USDC",  "token0": "WETH",  "token1": "USDC",  "d0": 18, "d1": 6 },
    {"address": "0x7501bc8bb51616f79bfa524e464fb7b41f0b10fb", "name": "msUSD/USDC", "token0": "msUSD", "token1": "USDC",  "d0": 18, "d1": 6 },
]

TOKEN_ADDRS = {
    "WETH":  "0x4200000000000000000000000000000000000006",
    "USDC":  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "AERO":  "0x940181a94A35A4569E4529A3CDfB74e38FD98631",
    "cbBTC": "0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
    "msETH": "0x7Ba6F01772924a82D9626c126347A28299E98c98",
    "msUSD": "0x526728DBc96689597F85ae4cd716d4f7fCcBAE9d",
}

# State
prev_tvl = {}
cooldowns = {}

def rpc_call(method, params):
    r = requests.post(BASE_RPC, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=10)
    return r.json().get("result")

def get_block():
    return int(rpc_call("eth_blockNumber", []), 16)

def balance_of(token_addr, pool_addr):
    pad = "000000000000000000000000" + pool_addr[2:].lower()
    result = rpc_call("eth_call", [{"to": token_addr, "data": "0x70a08231" + pad}, "latest"])
    if result and result != "0x":
        return int(result, 16)
    return 0

def get_reserves(pool):
    # Method 1: getReserves() for basic AMM
    try:
        hex_data = rpc_call("eth_call", [{"to": pool["address"], "data": "0x0902f1ac"}, "latest"])
        if hex_data and hex_data != "0x" and len(hex_data) >= 130:
            r0 = int(hex_data[2:66], 16)
            r1 = int(hex_data[66:130], 16)
            if r0 > 0 or r1 > 0:
                return r0, r1
    except:
        pass

    # Method 2: balanceOf on token contracts
    try:
        t0 = TOKEN_ADDRS.get(pool["token0"])
        t1 = TOKEN_ADDRS.get(pool["token1"])
        if t0 and t1:
            r0 = balance_of(t0, pool["address"])
            r1 = balance_of(t1, pool["address"])
            if r0 > 0 or r1 > 0:
                return r0, r1
    except:
        pass

    return None, None

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"  [TELEGRAM] {msg}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10
        )
    except Exception as e:
        print(f"  Telegram error: {e}")

def fmt(n):
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.2f}M"
    if n >= 1e3: return f"{n/1e3:.2f}K"
    return f"{n:.4f}"

def snapshot_message(data):
    lines = ["<b>🔵 Aerodrome Base — Pool Snapshot</b>",
             f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>", ""]
    for name, vals in data.items():
        r0, r1, d0, d1, t0, t1 = vals
        lines.append(f"<b>{name}</b>")
        lines.append(f"  {t0}: {fmt(r0 / 10**d0)}")
        lines.append(f"  {t1}: {fmt(r1 / 10**d1)}")
        lines.append("")
    return "\n".join(lines)

def main():
    print("=" * 55)
    print("  Aerodrome Whale Alert Bot")
    print(f"  Threshold: {WHALE_THRESHOLD*100:.0f}% TVL change")
    print(f"  Poll: every {POLL_INTERVAL}s")
    print(f"  Telegram: {'✅' if TELEGRAM_BOT_TOKEN else '❌ not set'}")
    print("=" * 55)

    # Startup snapshot
    block = get_block()
    print(f"\n[startup] Block #{block:,}")
    snap = {}
    for pool in POOLS:
        r0, r1 = get_reserves(pool)
        if r0 is not None:
            snap[pool["name"]] = (r0, r1, pool["d0"], pool["d1"], pool["token0"], pool["token1"])
            tvl = r0 / 10**pool["d0"]
            prev_tvl[pool["name"]] = tvl
            print(f"  {pool['name']}: {fmt(tvl)} {pool['token0']}")
        else:
            print(f"  {pool['name']}: failed")

    send_telegram(f"🟢 <b>Aerodrome Whale Bot started</b> — Block #{block:,}\n\n" + snapshot_message(snap))

    iteration = 0
    while True:
        time.sleep(POLL_INTERVAL)
        iteration += 1
        ts = datetime.utcnow().strftime("%H:%M:%S")
        print(f"\n[{ts}] Poll #{iteration}")

        try:
            block = get_block()
            now = time.time()
            snap = {}

            for pool in POOLS:
                r0, r1 = get_reserves(pool)
                if r0 is None:
                    print(f"  {pool['name']}: failed")
                    continue

                tvl = r0 / 10**pool["d0"]
                snap[pool["name"]] = (r0, r1, pool["d0"], pool["d1"], pool["token0"], pool["token1"])
                print(f"  {pool['name']}: {fmt(tvl)} {pool['token0']}")

                # Check whale move
                prev = prev_tvl.get(pool["name"])
                if prev and prev > 0:
                    change = (tvl - prev) / prev
                    if abs(change) >= WHALE_THRESHOLD:
                        key = pool["name"]
                        last = cooldowns.get(key, 0)
                        if now - last > COOLDOWN_SECONDS:
                            direction = "📈 ADD" if change > 0 else "📉 REMOVE"
                            alert = (
                                f"🚨 <b>WHALE ALERT: Big liquidity move in {pool['name']}</b>\n"
                                f"Change: {change*100:+.1f}% {direction}\n"
                                f"TVL now: {fmt(tvl)} {pool['token0']}\n"
                                f"TVL was: {fmt(prev)} {pool['token0']}\n"
                                f"Block: #{block:,}\n"
                                f"Pool: <code>{pool['address']}</code>"
                            )
                            print(f"  🚨 WHALE ALERT: {pool['name']} {change*100:+.1f}%")
                            send_telegram(alert)
                            cooldowns[key] = now

                prev_tvl[pool["name"]] = tvl

            # Periodic summary every 15 polls (~15 min)
            if iteration % 15 == 0:
                send_telegram(snapshot_message(snap))

        except KeyboardInterrupt:
            print("\n[stopped]")
            send_telegram("🔴 <b>Aerodrome Whale Bot stopped.</b>")
            break
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    main()
