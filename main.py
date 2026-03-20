#!/usr/bin/env python3
"""
Aerodrome Base Whale Alert Bot — with wallet tracking
Monitors pool TVL changes, fires alerts, and traces the wallet behind each move.
"""

import os
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

BASE_RPC           = "https://base-mainnet.public.blastapi.io"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
POLL_INTERVAL      = 60       # seconds
WHALE_THRESHOLD    = 0.05     # 5% TVL change
COOLDOWN_SECONDS   = 300

POOLS = [
    {"address":"0x70acdf2ad0bf2402c957154f944c19ef4e1cbae1","name":"WETH/cbBTC", "token0":"WETH", "token1":"cbBTC","d0":18,"d1":8 },
    {"address":"0x6cdcb1c4a4d1c3c6d054b27ac5b77e89eafb971d","name":"USDC/AERO", "token0":"USDC", "token1":"AERO", "d0":6, "d1":18},
    {"address":"0x74f72788f4814d7ff3c49b44684aa98eee140c0e","name":"WETH/msETH","token0":"WETH", "token1":"msETH","d0":18,"d1":18},
    {"address":"0xb2cc224c1c9fee385f8ad6a55b4d94e92359dc59","name":"WETH/USDC", "token0":"WETH", "token1":"USDC", "d0":18,"d1":6 },
    {"address":"0x7501bc8bb51616f79bfa524e464fb7b41f0b10fb","name":"msUSD/USDC","token0":"msUSD","token1":"USDC", "d0":18,"d1":6 },
]

TOKEN_ADDRS = {
    "WETH" :"0x4200000000000000000000000000000000000006",
    "USDC" :"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "AERO" :"0x940181a94A35A4569E4529A3CDfB74e38FD98631",
    "cbBTC":"0xcbB7C0000aB88B473b1f5aFd9ef808440eed33Bf",
    "msETH":"0x7Ba6F01772924a82D9626c126347A28299E98c98",
    "msUSD":"0x526728DBc96689597F85ae4cd716d4f7fCcBAE9d",
}

# Uniswap V3 / Aerodrome CL event topics
# Mint(address sender, address indexed owner, int24 indexed tickLower, int24 indexed tickUpper, uint128 amount, uint256 amount0, uint256 amount1)
MINT_TOPIC  = "0x7a53080ba414158be7ec69b987b5fb7d07dee101fe85488f0853ae16239d0bde"
# Burn(address indexed owner, int24 indexed tickLower, int24 indexed tickUpper, uint128 amount, uint256 amount0, uint256 amount1)
BURN_TOPIC  = "0x0c396cd989a39f4459b5fa1aed6a9a8dcdbc45908acfd67e028cd568da98982c"
# Collect(address indexed owner, address recipient, int24 indexed tickLower, int24 indexed tickUpper, uint128 amount0, uint128 amount1)
COLLECT_TOPIC = "0x70935338e69775456a85ddef226c395fb668b63fa0115f5f20610b388e6ca9c0"

prev_tvl   = {}
cooldowns  = {}

# ── RPC helpers ────────────────────────────────────────────────────────────────

def rpc(method, params):
    r = requests.post(BASE_RPC,
        json={"jsonrpc":"2.0","id":1,"method":method,"params":params},
        timeout=15)
    return r.json().get("result")

def get_block():
    return int(rpc("eth_blockNumber", []), 16)

def balance_of(token, pool):
    pad = "000000000000000000000000" + pool[2:].lower()
    res = rpc("eth_call", [{"to":token,"data":"0x70a08231"+pad},"latest"])
    return int(res, 16) if res and res != "0x" else 0

def get_reserves(pool):
    # Basic AMM
    try:
        h = rpc("eth_call",[{"to":pool["address"],"data":"0x0902f1ac"},"latest"])
        if h and h != "0x" and len(h) >= 130:
            r0, r1 = int(h[2:66],16), int(h[66:130],16)
            if r0 > 0 or r1 > 0: return r0, r1
    except: pass
    # CL pool via balanceOf
    try:
        t0 = TOKEN_ADDRS.get(pool["token0"])
        t1 = TOKEN_ADDRS.get(pool["token1"])
        if t0 and t1:
            r0 = balance_of(t0, pool["address"])
            r1 = balance_of(t1, pool["address"])
            if r0 > 0 or r1 > 0: return r0, r1
    except: pass
    return None, None

# ── Wallet tracker ─────────────────────────────────────────────────────────────

def get_recent_movers(pool_addr, from_block, to_block):
    """
    Fetch Mint/Burn logs for the pool in the given block range.
    Returns list of (event_type, wallet, tx_hash).
    """
    wallets = []
    from_hex = hex(from_block)
    to_hex   = hex(to_block)

    for topic, label in [(MINT_TOPIC, "ADD"), (BURN_TOPIC, "REMOVE")]:
        try:
            logs = rpc("eth_getLogs", [{
                "fromBlock": from_hex,
                "toBlock":   to_hex,
                "address":   pool_addr,
                "topics":    [topic],
            }])
            if not logs: continue
            for log in logs:
                tx   = log.get("transactionHash","")
                # For Mint: sender is in data (first 32 bytes after selector)
                # indexed topics: [topic, owner, tickLower, tickUpper]
                # non-indexed data starts with sender address
                data = log.get("data","")
                topics = log.get("topics",[])

                if label == "ADD" and len(data) >= 66:
                    # sender = first 32 bytes of data = padded address
                    wallet = "0x" + data[26:66]
                elif label == "REMOVE" and len(topics) >= 2:
                    # owner = topics[1]
                    wallet = "0x" + topics[1][-40:]
                else:
                    wallet = "unknown"

                wallets.append((label, wallet.lower(), tx))
        except Exception as e:
            print(f"  getLogs error: {e}")

    return wallets

def fmt_wallet(w):
    return f"{w[:6]}...{w[-4:]}"

def basescan_link(tx):
    return f"https://basescan.org/tx/{tx}"

# ── Telegram ───────────────────────────────────────────────────────────────────

def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"  [TG] {msg[:80]}")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"},
            timeout=10)
    except Exception as e:
        print(f"  TG error: {e}")

def fmt(n):
    if n >= 1e9: return f"{n/1e9:.2f}B"
    if n >= 1e6: return f"{n/1e6:.2f}M"
    if n >= 1e3: return f"{n/1e3:.2f}K"
    return f"{n:.4f}"

def snapshot_msg(data):
    lines = ["<b>🔵 Aerodrome Base — Pool Snapshot</b>",
             f"<i>{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</i>",""]
    for name,(r0,r1,d0,d1,t0,t1) in data.items():
        lines += [f"<b>{name}</b>",
                  f"  {t0}: {fmt(r0/10**d0)}",
                  f"  {t1}: {fmt(r1/10**d1)}",""]
    return "\n".join(lines)

# ── Main loop ──────────────────────────────────────────────────────────────────

def main():
    print("="*55)
    print("  Aerodrome Whale + Wallet Tracker")
    print(f"  Threshold : {WHALE_THRESHOLD*100:.0f}% TVL change")
    print(f"  Poll      : every {POLL_INTERVAL}s")
    print(f"  Telegram  : {'✅' if TELEGRAM_BOT_TOKEN else '❌'}")
    print("="*55)

    block = get_block()
    print(f"\n[startup] Block #{block:,}")
    snap = {}
    for pool in POOLS:
        r0, r1 = get_reserves(pool)
        if r0 is not None:
            snap[pool["name"]] = (r0,r1,pool["d0"],pool["d1"],pool["token0"],pool["token1"])
            prev_tvl[pool["name"]] = r0 / 10**pool["d0"]
            print(f"  {pool['name']}: {fmt(r0/10**pool['d0'])} {pool['token0']}")
        else:
            print(f"  {pool['name']}: failed")

    send_telegram(f"🟢 <b>Aerodrome Whale Bot started</b> — Block #{block:,}\n\n" + snapshot_msg(snap))

    iteration = 0
    while True:
        time.sleep(POLL_INTERVAL)
        iteration += 1
        ts = datetime.utcnow().strftime("%H:%M:%S")

        try:
            prev_block = block
            block = get_block()
            print(f"\n[{ts}] Poll #{iteration} | Block #{block:,}")
            snap = {}
            now  = time.time()

            for pool in POOLS:
                r0, r1 = get_reserves(pool)
                if r0 is None:
                    print(f"  {pool['name']}: failed")
                    continue

                tvl  = r0 / 10**pool["d0"]
                snap[pool["name"]] = (r0,r1,pool["d0"],pool["d1"],pool["token0"],pool["token1"])
                print(f"  {pool['name']}: {fmt(tvl)} {pool['token0']}")

                prev = prev_tvl.get(pool["name"])
                if prev and prev > 0:
                    change = (tvl - prev) / prev
                    if abs(change) >= WHALE_THRESHOLD:
                        key  = pool["name"]
                        last = cooldowns.get(key, 0)
                        if now - last > COOLDOWN_SECONDS:
                            direction = "📈 ADD" if change > 0 else "📉 REMOVE"

                            # ── Fetch wallet addresses ──────────────────────
                            movers = get_recent_movers(pool["address"], prev_block, block)
                            wallet_lines = ""
                            if movers:
                                seen = set()
                                lines = []
                                for ev, w, tx in movers[:5]:
                                    if w not in seen:
                                        seen.add(w)
                                        lines.append(
                                            f"  {ev} <a href='{basescan_link(tx)}'>{fmt_wallet(w)}</a>"
                                        )
                                wallet_lines = "\nWallets:\n" + "\n".join(lines)
                            else:
                                wallet_lines = "\nWallets: (no Mint/Burn events in range)"

                            alert = (
                                f"🚨 <b>WHALE ALERT: {pool['name']}</b>\n"
                                f"Change : {change*100:+.1f}% {direction}\n"
                                f"TVL now: {fmt(tvl)} {pool['token0']}\n"
                                f"TVL was: {fmt(prev)} {pool['token0']}\n"
                                f"Block  : #{block:,}"
                                f"{wallet_lines}\n"
                                f"Pool: <code>{pool['address']}</code>"
                            )
                            print(f"  🚨 WHALE {pool['name']} {change*100:+.1f}%")
                            send_telegram(alert)
                            cooldowns[key] = now

                prev_tvl[pool["name"]] = tvl

            # Periodic summary every 15 polls
            if iteration % 15 == 0:
                send_telegram(snapshot_msg(snap))

        except KeyboardInterrupt:
            print("\n[stopped]")
            send_telegram("🔴 <b>Aerodrome Bot stopped.</b>")
            break
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    main()
