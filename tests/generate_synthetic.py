"""
Deterministic synthetic market data generator for latency sensitivity testing.

Generates a .bin file with TickEvents at precisely 100μs intervals.
Designed to produce DIFFERENT results for 9ms vs 10ms latency when the
engine correctly resolves sub-millisecond event timing.

Timeline (μs from T0):
  T0 = 1,700,000,000,000,000

  T0 +      0: DEPTH_BUY  @ 100000, qty=0.01   ← establishes best_bid
  T0 +      0: DEPTH_SELL @ 100030, qty=0.01   ← establishes best_ask
                 → Strategy fires: places buy @ 100000, sell @ 100030
                 → trigger_ts = T0 + latency (9000 or 10000)

  T0 +    100 – T0 +  20000: ticks every 100μs (innocuous OB refreshes)

  T0 +   9500: TRADE_SELL @ 100000, qty=0.03   ← ★ CRITICAL TRADE (9.5ms)
                 → 9ms latency: order active at T0+9000 → gets filled
                 → 10ms latency: order NOT active (arrives T0+10000) → MISS

  T0 +  20000: end of data

Expected results:
  - 9ms latency: ≥1 trade (filled at T0+9500)
  - 10ms latency: 0 trades (missed the only opportunity)

Spread of 30 (bid=100000, ask=100030) ensures strategy places AT best_bid/best_ask
given hardcoded base_spread=10, gamma=30.
"""

import numpy as np
import os
import struct

# ── Event masks (must match C++ Types.h) ──────────────────────────────
DEPTH_EVENT = 1 << 28  # 268435456
TRADE_EVENT = 1 << 31  # 2147483648
BUY_SIDE = 1
SELL_SIDE = 2

DEPTH_BUY_MASK = DEPTH_EVENT | BUY_SIDE   # (1<<28) | 1
DEPTH_SELL_MASK = DEPTH_EVENT | SELL_SIDE  # (1<<28) | 2
TRADE_BUY_MASK = TRADE_EVENT | BUY_SIDE   # (1<<31) | 1
TRADE_SELL_MASK = TRADE_EVENT | SELL_SIDE  # (1<<31) | 2

STRUCT_DTYPE = np.dtype([("ev", "u8"), ("ts", "i8"), ("px", "f8"), ("qty", "f8")])

# ── Market parameters ─────────────────────────────────────────────────
BEST_BID = 100_000.0
BEST_ASK = 100_030.0  # spread=30 ensures target_bid=best_bid with base_spread=10
OB_QTY = 0.01  # thin depth → queue_ahead is small, easy to fill through


def generate(output_path: str) -> np.ndarray:
    T0 = 1_700_000_000_000_000
    events = []

    # ── Step 1: Establish order book at T0 ──
    # DEPTH_BUY first, then DEPTH_SELL (order in file matters: strategy
    # needs best_ask set before it fires, so BUY→SELL ordering at same ts)
    events.append((DEPTH_BUY_MASK, T0, BEST_BID, OB_QTY))
    events.append((DEPTH_SELL_MASK, T0, BEST_ASK, OB_QTY))

    # ── Step 2: Fill ticks at 100μs intervals ──
    # Every 1ms (10 ticks): refresh OB to prevent book staleness
    # At exactly T0+9500: insert the critical trade
    for offset_us in range(100, 20_001, 100):
        ts = T0 + offset_us

        if offset_us == 9500:
            # ★ The critical trade — only order active with ≤9ms latency catches this
            events.append((TRADE_SELL_MASK, ts, BEST_BID, 0.03))
        elif offset_us % 1000 == 0:
            # Refresh OB every 1ms to keep best_bid/best_ask alive
            events.append((DEPTH_BUY_MASK, ts, BEST_BID, OB_QTY))
            events.append((DEPTH_SELL_MASK, ts, BEST_ASK, OB_QTY))

    # ── Step 3: Sort by timestamp (mergesort is stable) ──
    arr = np.array(events, dtype=STRUCT_DTYPE)
    arr = np.sort(arr, order="ts", kind="mergesort")

    # ── Step 4: Write binary ──
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(arr.tobytes())

    # ── Diagnostic output ──
    print(f"[OK] Synthetic data: {len(arr)} events -> {output_path}")
    print(f"  Timestamp range: {arr[0]['ts']} – {arr[-1]['ts']}")
    print(f"  Tick spacing: 100μs")
    print(f"  Critical trade @ T0+9500μs: SELL {BEST_BID} qty=0.03")
    print(f"  Expected: 9ms→filled | 10ms→miss")

    # Verify critical trade exists at right timestamp
    critical = arr[arr["ts"] == T0 + 9500]
    assert len(critical) == 1, f"Critical trade missing! Found {len(critical)} events at T0+9500"
    assert critical[0]["ev"] == TRADE_SELL_MASK, "Wrong event type at critical timestamp"
    print(f"  [OK] Critical trade verified at ts={T0 + 9500}")

    return arr


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "synthetic_data.bin")
    generate(out)
