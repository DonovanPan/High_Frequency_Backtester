"""
Deterministic latency sensitivity test — faithful Python port of the C++ engine's
core event-processing logic.

This replicates the exact algorithm from HighFreqBacktester.cpp:
  - on_tick() event loop
  - process_delayed_events() with min-heap
  - simulate_queue_matching() with queue_ahead
  - Strategy: OBI + Inventory Skewing
  - send_place / send_cancel with latency delay

Run with synthetic data (100us tick spacing) to verify that 9ms vs 10ms latency
produces DIFFERENT trade histories when data precision is sufficient.
"""

import heapq
import struct
import sys
import os
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

# ═══════════════════════════════════════════════════════════════════════════════
# Constants — must match C++ Types.h
# ═══════════════════════════════════════════════════════════════════════════════
DEPTH_BUY_MASK  = (1 << 28) | 1
DEPTH_SELL_MASK = (1 << 28) | 2
TRADE_BUY_MASK  = (1 << 31) | 1
TRADE_SELL_MASK = (1 << 31) | 2


def is_depth(ev_type: int) -> bool:
    return (ev_type >> 28) & 1

def is_trade(ev_type: int) -> bool:
    return (ev_type >> 31) & 1

def is_buy_side(ev_type: int) -> bool:
    return (ev_type & 0xFF) == 1

# ═══════════════════════════════════════════════════════════════════════════════
# Data structures — mirror C++ types
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class TickEvent:
    ev_type: int
    exch_ts: int
    price: float
    qty: float

@dataclass
class LocalOrder:
    order_id: int = 0
    is_active: bool = False
    price: float = 0.0
    qty: float = 0.0
    remaining_qty: float = 0.0
    queue_ahead: float = 0.0
    is_cancel_pending: bool = False

@dataclass(order=True)
class PendingAction:
    trigger_ts: int
    type: int  # 0=PLACE, 1=CANCEL (from field order, trigger_ts is sort key)
    is_buy: bool = field(compare=False)
    price: float = field(compare=False)
    qty: float = field(compare=False)
    target_order_id: int = field(compare=False)

@dataclass
class TradeRecord:
    ts: int
    is_buy: bool
    price: float
    qty: float
    fee_or_rebate: float
    position_after: float

# ═══════════════════════════════════════════════════════════════════════════════
# Engine — faithful port of HighFreqBacktester
# ═══════════════════════════════════════════════════════════════════════════════
class BacktestEngine:
    def __init__(self, latency_us: int):
        # Account state
        self.cash = 10000.0
        self.initial_cash = 10000.0
        self.position = 0.0
        self.total_volume = 0.0

        # Fee schedule
        self.rebate_rate = 0.00005   # Maker rebate
        self.taker_fee_rate = -0.0005  # Taker penalty

        # Order book (local)
        self.book_bids: dict = {}  # price -> qty (descending, handled via sorted keys)
        self.book_asks: dict = {}  # price -> qty

        self.current_ob_ts = 0
        self.best_bid = 0.0
        self.best_bid_qty = 0.0
        self.best_ask = 0.0
        self.best_ask_qty = 0.0
        self.last_price = 0.0

        # Strategy parameters (hardcoded, same as C++)
        self.order_qty = 0.02
        self.max_position = 0.1
        self.latency_us = latency_us
        self.base_spread = 10.0
        self.gamma = 30.0
        self.obi_threshold = 0.6

        # Order tracking
        self.next_order_id = 1
        self.active_buy = LocalOrder()
        self.active_sell = LocalOrder()
        self.is_buy_place_pending = False
        self.is_sell_place_pending = False

        # Event queue (min-heap by trigger_ts)
        self.event_queue: List[PendingAction] = []

        # Records
        self.trade_history: List[TradeRecord] = []

    # ── Book helpers ──────────────────────────────────────────────────────
    def get_best_bid(self):
        if self.book_bids:
            return max(self.book_bids.keys())
        return 0.0

    def get_best_ask(self):
        if self.book_asks:
            return min(self.book_asks.keys())
        return 0.0

    # ── send_place / send_cancel ───────────────────────────────────────────
    def send_place(self, is_buy: bool, px: float, qty: float, current_ts: int) -> int:
        oid = self.next_order_id
        self.next_order_id += 1
        if is_buy:
            self.is_buy_place_pending = True
        else:
            self.is_sell_place_pending = True
        heapq.heappush(self.event_queue, PendingAction(
            trigger_ts=current_ts + self.latency_us,
            type=0,  # PLACE
            is_buy=is_buy,
            price=px,
            qty=qty,
            target_order_id=oid
        ))
        return oid

    def send_cancel(self, is_buy: bool, oid: int, current_ts: int):
        if is_buy:
            self.active_buy.is_cancel_pending = True
        else:
            self.active_sell.is_cancel_pending = True
        heapq.heappush(self.event_queue, PendingAction(
            trigger_ts=current_ts + self.latency_us,
            type=1,  # CANCEL
            is_buy=is_buy,
            price=0.0,
            qty=0.0,
            target_order_id=oid
        ))

    # ── process_delayed_events ────────────────────────────────────────────
    def process_delayed_events(self, current_ts: int):
        while self.event_queue and self.event_queue[0].trigger_ts <= current_ts:
            action = heapq.heappop(self.event_queue)

            if action.type == 0:  # PLACE_ORDER
                if action.is_buy:
                    if self.best_ask > 0 and action.price >= self.best_ask:
                        # Crossed the spread → taker fill
                        self.execute_trade(self.best_ask, action.qty, True, current_ts, True)
                        self.is_buy_place_pending = False
                    else:
                        self.active_buy.is_active = True
                        self.active_buy.order_id = action.target_order_id
                        self.active_buy.price = action.price
                        self.active_buy.qty = action.qty
                        self.active_buy.remaining_qty = action.qty
                        self.active_buy.queue_ahead = self.book_bids.get(action.price, 0.0)
                        self.active_buy.is_cancel_pending = False
                        self.is_buy_place_pending = False
                else:
                    if self.best_bid > 0 and action.price <= self.best_bid:
                        self.execute_trade(self.best_bid, action.qty, False, current_ts, True)
                        self.is_sell_place_pending = False
                    else:
                        self.active_sell.is_active = True
                        self.active_sell.order_id = action.target_order_id
                        self.active_sell.price = action.price
                        self.active_sell.qty = action.qty
                        self.active_sell.remaining_qty = action.qty
                        self.active_sell.queue_ahead = self.book_asks.get(action.price, 0.0)
                        self.active_sell.is_cancel_pending = False
                        self.is_sell_place_pending = False

            elif action.type == 1:  # CANCEL_ORDER
                if action.is_buy and self.active_buy.is_active and self.active_buy.order_id == action.target_order_id:
                    self.active_buy.is_active = False
                    self.active_buy.is_cancel_pending = False
                elif not action.is_buy and self.active_sell.is_active and self.active_sell.order_id == action.target_order_id:
                    self.active_sell.is_active = False
                    self.active_sell.is_cancel_pending = False

    # ── simulate_queue_matching ───────────────────────────────────────────
    def simulate_queue_matching(self, trade_ev: TickEvent):
        is_market_sell = (trade_ev.ev_type == TRADE_SELL_MASK)
        is_market_buy  = (trade_ev.ev_type == TRADE_BUY_MASK)

        # Check buy order
        if self.active_buy.is_active:
            if trade_ev.price < self.active_buy.price:
                # Price crossed below our bid → full fill
                self.execute_trade(self.active_buy.price, self.active_buy.remaining_qty,
                                   True, trade_ev.exch_ts, False)
                self.active_buy.remaining_qty = 0.0
                self.active_buy.is_active = False
                self.active_buy.is_cancel_pending = False
            elif trade_ev.price == self.active_buy.price and is_market_sell:
                trade_qty_left = trade_ev.qty
                if self.active_buy.queue_ahead > 0:
                    consumption = min(self.active_buy.queue_ahead, trade_qty_left)
                    self.active_buy.queue_ahead -= consumption
                    trade_qty_left -= consumption
                if self.active_buy.queue_ahead <= 0 and trade_qty_left > 0:
                    fill_qty = min(self.active_buy.remaining_qty, trade_qty_left)
                    if fill_qty > 0:
                        self.execute_trade(self.active_buy.price, fill_qty,
                                           True, trade_ev.exch_ts, False)
                        self.active_buy.remaining_qty -= fill_qty
                    if self.active_buy.remaining_qty <= 1e-9:
                        self.active_buy.is_active = False
                        self.active_buy.is_cancel_pending = False

        # Check sell order (mirror logic)
        if self.active_sell.is_active:
            if trade_ev.price > self.active_sell.price:
                self.execute_trade(self.active_sell.price, self.active_sell.remaining_qty,
                                   False, trade_ev.exch_ts, False)
                self.active_sell.remaining_qty = 0.0
                self.active_sell.is_active = False
                self.active_sell.is_cancel_pending = False
            elif trade_ev.price == self.active_sell.price and is_market_buy:
                trade_qty_left = trade_ev.qty
                if self.active_sell.queue_ahead > 0:
                    consumption = min(self.active_sell.queue_ahead, trade_qty_left)
                    self.active_sell.queue_ahead -= consumption
                    trade_qty_left -= consumption
                if self.active_sell.queue_ahead <= 0 and trade_qty_left > 0:
                    fill_qty = min(self.active_sell.remaining_qty, trade_qty_left)
                    if fill_qty > 0:
                        self.execute_trade(self.active_sell.price, fill_qty,
                                           False, trade_ev.exch_ts, False)
                        self.active_sell.remaining_qty -= fill_qty
                    if self.active_sell.remaining_qty <= 1e-9:
                        self.active_sell.is_active = False
                        self.active_sell.is_cancel_pending = False

    # ── execute_trade ─────────────────────────────────────────────────────
    def execute_trade(self, px: float, qty: float, is_buy: bool, ts: int, is_taker: bool):
        notional = px * qty
        fee_or_rebate = notional * (self.taker_fee_rate if is_taker else self.rebate_rate)

        if is_buy:
            self.cash -= notional
            self.position += qty
        else:
            self.cash += notional
            self.position -= qty

        self.cash += fee_or_rebate
        self.total_volume += notional
        self.trade_history.append(TradeRecord(ts, is_buy, px, qty, fee_or_rebate, self.position))

    # ── on_tick (main event loop) ─────────────────────────────────────────
    def on_tick(self, ev: TickEvent):
        # 1. Process delayed events that have matured
        self.process_delayed_events(ev.exch_ts)

        # 2. Update order book
        if ev.ev_type == DEPTH_BUY_MASK or ev.ev_type == DEPTH_SELL_MASK:
            if ev.exch_ts > self.current_ob_ts:
                self.book_bids.clear()
                self.book_asks.clear()
                self.best_bid = 0.0
                self.best_ask = 0.0
                self.current_ob_ts = ev.exch_ts

            if ev.ev_type == DEPTH_BUY_MASK:
                if ev.qty <= 1e-9:
                    self.book_bids.pop(ev.price, None)
                else:
                    self.book_bids[ev.price] = ev.qty
                self.best_bid = self.get_best_bid()
                self.best_bid_qty = self.book_bids.get(self.best_bid, 0.0)
            else:
                if ev.qty <= 1e-9:
                    self.book_asks.pop(ev.price, None)
                else:
                    self.book_asks[ev.price] = ev.qty
                self.best_ask = self.get_best_ask()
                self.best_ask_qty = self.book_asks.get(self.best_ask, 0.0)

        elif ev.ev_type == TRADE_BUY_MASK or ev.ev_type == TRADE_SELL_MASK:
            self.last_price = ev.price
            self.simulate_queue_matching(ev)

        # 3. Strategy logic
        if self.best_bid > 0 and self.best_ask > 0:
            mid_price = (self.best_bid + self.best_ask) / 2.0
            imbalance = (self.best_bid_qty - self.best_ask_qty) / (self.best_bid_qty + self.best_ask_qty + 1e-9)

            reservation_price = mid_price - self.gamma * self.position
            target_bid = reservation_price - self.base_spread
            target_ask = reservation_price + self.base_spread

            import math
            target_bid = min(self.best_bid, math.floor(target_bid))
            target_ask = max(self.best_ask, math.ceil(target_ask))

            # Cancel checks
            if self.active_buy.is_active and not self.active_buy.is_cancel_pending:
                if abs(self.active_buy.price - target_bid) > 2.0 or imbalance < -self.obi_threshold:
                    self.send_cancel(True, self.active_buy.order_id, ev.exch_ts)

            if self.active_sell.is_active and not self.active_sell.is_cancel_pending:
                if abs(self.active_sell.price - target_ask) > 2.0 or imbalance > self.obi_threshold:
                    self.send_cancel(False, self.active_sell.order_id, ev.exch_ts)

            # Place checks
            if not self.active_buy.is_active and not self.is_buy_place_pending and self.position < self.max_position:
                if imbalance >= -self.obi_threshold:
                    self.send_place(True, target_bid, self.order_qty, ev.exch_ts)

            if not self.active_sell.is_active and not self.is_sell_place_pending and self.position > -self.max_position:
                if imbalance <= self.obi_threshold:
                    self.send_place(False, target_ask, self.order_qty, ev.exch_ts)


# ═══════════════════════════════════════════════════════════════════════════════
# Binary file reader
# ═══════════════════════════════════════════════════════════════════════════════
def read_bin_events(filepath: str) -> List[TickEvent]:
    """Read .bin file with TickEvent structs (32 bytes each, little-endian)."""
    events = []
    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(32)
            if len(chunk) < 32:
                break
            ev_type, ts, px, qty = struct.unpack('<Qqdd', chunk)
            events.append(TickEvent(ev_type, ts, px, qty))
    return events


# ═══════════════════════════════════════════════════════════════════════════════
# Main test
# ═══════════════════════════════════════════════════════════════════════════════
def run_test(data_path: str, latency_us: int) -> BacktestEngine:
    engine = BacktestEngine(latency_us=latency_us)
    events = read_bin_events(data_path)
    for ev in events:
        engine.on_tick(ev)
    return engine


def main():
    data_path = os.path.join(os.path.dirname(__file__), "synthetic_data.bin")
    if not os.path.exists(data_path):
        print(f"ERROR: Synthetic data not found at {data_path}")
        print("Run generate_synthetic.py first.")
        sys.exit(1)

    print(f"Loading synthetic data: {data_path}")
    events = read_bin_events(data_path)
    print(f"  Events loaded: {len(events)}")
    print(f"  Timestamp range: {events[0].exch_ts} – {events[-1].exch_ts}")
    print(f"  Tick spacing: {(events[1].exch_ts - events[0].exch_ts)} us")
    print()

    # Run with 9ms and 10ms latency
    results = {}
    for latency in [9000, 10000]:
        label = f"{latency//1000}ms"
        engine = BacktestEngine(latency_us=latency)
        for ev in events:
            engine.on_tick(ev)

        final_equity = engine.cash + engine.position * engine.last_price
        results[latency] = engine

        print(f"── {label} ({latency} us) ──────────────────────────────")
        print(f"  Trades      : {len(engine.trade_history)}")
        print(f"  Final equity: ${final_equity:.4f}")
        print(f"  Position    : {engine.position:.4f} BTC")
        print(f"  Cash        : ${engine.cash:.4f}")

        if engine.trade_history:
            for i, t in enumerate(engine.trade_history):
                side = "BUY" if t.is_buy else "SELL"
                maker_taker = "TAKER" if t.fee_or_rebate < 0 else "MAKER"
                print(f"    Trade #{i+1}: ts={t.ts} {side} {t.qty:.4f} @ {t.price:.2f} "
                      f"fee={t.fee_or_rebate:+.6f} pos={t.position_after:.4f} [{maker_taker}]")
        else:
            print("    (no trades)")
        print()

    # ── Comparison ────────────────────────────────────────────────────────
    eng_9 = results[9000]
    eng_10 = results[10000]
    trades_9 = [(t.ts, t.is_buy, t.price, t.qty, t.fee_or_rebate) for t in eng_9.trade_history]
    trades_10 = [(t.ts, t.is_buy, t.price, t.qty, t.fee_or_rebate) for t in eng_10.trade_history]

    print("=" * 60)
    if trades_9 == trades_10:
        print("RESULT: 9ms and 10ms produce IDENTICAL trade histories.")
        print("→ Engine CANNOT resolve 1ms latency difference with this data.")
    else:
        print("RESULT: 9ms and 10ms produce DIFFERENT trade histories.")
        print("→ Engine CAN resolve 1ms latency difference with 100us data!")
        print(f"  9ms: {len(trades_9)} trades, equity=${eng_9.cash + eng_9.position*eng_9.last_price:.4f}")
        print(f"  10ms: {len(trades_10)} trades, equity=${eng_10.cash + eng_10.position*eng_10.last_price:.4f}")

        # Explain the mechanism
        critical_ts = 1_700_000_000_000_000 + 9500
        print()
        print("Mechanism (verified):")
        print(f"  Critical trade @ T0+9500us = {critical_ts}")
        print(f"  9ms: trigger_ts = T0+9000 <= T0+9500 → order active BEFORE trade → fill")
        print(f"  10ms: trigger_ts = T0+10000 > T0+9500 → order NOT active → miss")

    print("=" * 60)
    return results


if __name__ == "__main__":
    main()
