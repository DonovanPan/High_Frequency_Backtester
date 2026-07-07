#include "HighFreqBacktester.h"
#include <algorithm>
#include <cmath>

HighFreqBacktester::HighFreqBacktester() {
    trade_history.reserve(500000); 
    equity_curve.reserve(10000);   
}

void HighFreqBacktester::on_tick(const TickEvent& ev) {
    process_delayed_events(ev.exch_ts);

    // 遇到新的时间戳，说明是新的全量快照，清空旧的盘口
    if (ev.ev_type == DEPTH_BUY_MASK || ev.ev_type == DEPTH_SELL_MASK) {
        
        if (ev.exch_ts > current_ob_ts) {
            book_bids.clear();
            book_asks.clear();
            best_bid = 0.0;
            best_ask = 0.0;
            current_ob_ts = ev.exch_ts;
        }

        if (ev.ev_type == DEPTH_BUY_MASK) {
            if (ev.qty <= 1e-9) book_bids.erase(ev.price);
            else book_bids[ev.price] = ev.qty;

            if (!book_bids.empty()) {
                best_bid = book_bids.begin()->first;
                best_bid_qty = book_bids.begin()->second;
            } else {
                best_bid = 0.0; best_bid_qty = 0.0;
            }
        } else {
            if (ev.qty <= 1e-9) book_asks.erase(ev.price);
            else book_asks[ev.price] = ev.qty;

            if (!book_asks.empty()) {
                best_ask = book_asks.begin()->first;
                best_ask_qty = book_asks.begin()->second;
            } else {
                best_ask = 0.0; best_ask_qty = 0.0;
            }
        }
    } 
    else if (ev.ev_type == TRADE_BUY_MASK || ev.ev_type == TRADE_SELL_MASK) {
        last_price = ev.price;
        simulate_queue_matching(ev);
    }

    // --- 策略发单逻辑 ---
    if (best_bid > 0 && best_ask > 0) {
        
        // 1. 计算微观结构指标
        double mid_price = (best_bid + best_ask) / 2.0;
        
        // OBI (Orderbook Imbalance): 衡量盘口买卖力量对比。范围 [-1, 1]
        // > 0.5 说明买单堆积严重；< -0.5 说明卖单压顶
        double imbalance = (best_bid_qty - best_ask_qty) / (best_bid_qty + best_ask_qty + 1e-9);

        // 2. 策略超参数 (实盘中需通过回测网格搜索优化的核心参数)
        double base_spread = 10.0;           // 基础做市半价差：稍微往深处挂，赚取更厚的利润垫
        double gamma = 30.0;                 // 库存风险厌恶系数：每多持仓 1 个 BTC，报价偏移 30 刀
        double obi_threshold = 0.6;          // 毒性流量阈值：当 OBI 极度失衡时，触发防守动作

        // 3. 库存偏斜定价 (Inventory Skewing)
        // 核心逻辑：如果手里捏着多头仓位 (position > 0)，reservation_price 会向下偏移。
        // 这会导致买单挂得更深，卖单挂得更近。
        double reservation_price = mid_price - gamma * position;

        // 4. 计算理论目标挂单价
        double target_bid = reservation_price - base_spread;
        double target_ask = reservation_price + base_spread;

        // 5. 防止主动穿盘 (强制设为 Maker)
        // 确保挂单价不超过当前的买一卖一，否则会被引擎判定为 Taker 并扣除高额手续费
        target_bid = std::min(best_bid, std::floor(target_bid));
        target_ask = std::max(best_ask, std::ceil(target_ask));

        // --- 撤单动作执行 ---
        // 撤销买单：价格偏离超过 2 刀，或者发现 OBI < -0.6 
        if (active_buy.is_active && !active_buy.is_cancel_pending) {
            if (std::abs(active_buy.price - target_bid) > 2.0 || imbalance < -obi_threshold) {
                send_cancel(true, active_buy.order_id, ev.exch_ts);
            }
        }
        // 撤销卖单：防范暴涨风险
        if (active_sell.is_active && !active_sell.is_cancel_pending) {
            if (std::abs(active_sell.price - target_ask) > 2.0 || imbalance > obi_threshold) {
                send_cancel(false, active_sell.order_id, ev.exch_ts);
            }
        }

        // --- 挂单动作执行 ---
        // 当没有面临暴跌风险 (imbalance >= -0.6) 时，在下方接多单
        if (!active_buy.is_active && !is_buy_place_pending && position < max_position) {
            if (imbalance >= -obi_threshold) { 
                send_place(true, target_bid, order_qty, ev.exch_ts);
            }
        }
        // 当没有面临暴涨风险 (imbalance <= 0.6) 时，在上方挂空单
        if (!active_sell.is_active && !is_sell_place_pending && position > -max_position) {
            if (imbalance <= obi_threshold) {
                send_place(false, target_ask, order_qty, ev.exch_ts);
            }
        }
    }

    // --- 记录资金曲线 ---
    if (last_record_ts == 0) last_record_ts = ev.exch_ts;
    if (ev.exch_ts - last_record_ts >= 3600000000LL) {
        double current_equity = cash + position * last_price;
        equity_curve.push_back({ev.exch_ts, current_equity});
        last_record_ts = ev.exch_ts;
        
        max_equity = std::max(max_equity, current_equity);
        double dd = (max_equity - current_equity) / max_equity;
        max_drawdown = std::max(max_drawdown, dd);
    }
}

uint64_t HighFreqBacktester::send_place(bool is_buy, double px, double qty, int64_t current_ts) {
    uint64_t oid = next_order_id++;
    if (is_buy) is_buy_place_pending = true;
    else is_sell_place_pending = true;
    event_queue.push({current_ts + latency_us, ActionType::PLACE_ORDER, is_buy, px, qty, oid});
    return oid;
}

void HighFreqBacktester::send_cancel(bool is_buy, uint64_t oid, int64_t current_ts) {
    if (is_buy) active_buy.is_cancel_pending = true;
    else active_sell.is_cancel_pending = true;
    event_queue.push({current_ts + latency_us, ActionType::CANCEL_ORDER, is_buy, 0.0, 0.0, oid});
}

void HighFreqBacktester::process_delayed_events(int64_t current_ts) {
    while (!event_queue.empty() && event_queue.top().trigger_ts <= current_ts) {
        auto action = event_queue.top();
        event_queue.pop();

        if (action.type == ActionType::PLACE_ORDER) {
            if (action.is_buy) {
                if (best_ask > 0 && action.price >= best_ask) {
                    execute_trade(best_ask, action.qty, true, current_ts, true); // Taker 穿盘惩罚
                    is_buy_place_pending = false;
                } else {
                    active_buy.is_active = true;
                    active_buy.order_id = action.target_order_id;
                    active_buy.price = action.price;
                    active_buy.qty = action.qty;
                    active_buy.remaining_qty = action.qty;
                    
                    auto it = book_bids.find(action.price);
                    active_buy.queue_ahead = (it != book_bids.end()) ? it->second : 0.0;
                    
                    active_buy.is_cancel_pending = false; 
                    is_buy_place_pending = false;         
                }
            } else {
                if (best_bid > 0 && action.price <= best_bid) {
                    execute_trade(best_bid, action.qty, false, current_ts, true); 
                    is_sell_place_pending = false;
                } else {
                    active_sell.is_active = true;
                    active_sell.order_id = action.target_order_id;
                    active_sell.price = action.price;
                    active_sell.qty = action.qty;
                    active_sell.remaining_qty = action.qty;
                    
                    auto it = book_asks.find(action.price);
                    active_sell.queue_ahead = (it != book_asks.end()) ? it->second : 0.0;
                    
                    active_sell.is_cancel_pending = false;
                    is_sell_place_pending = false;
                }
            }
        } 
        else if (action.type == ActionType::CANCEL_ORDER) {
            if (action.is_buy && active_buy.is_active && active_buy.order_id == action.target_order_id) {
                active_buy.is_active = false;
                active_buy.is_cancel_pending = false; 
            } else if (!action.is_buy && active_sell.is_active && active_sell.order_id == action.target_order_id) {
                active_sell.is_active = false;
                active_sell.is_cancel_pending = false;
            }
        }
    }
}

void HighFreqBacktester::simulate_queue_matching(const TickEvent& trade_ev) {
    bool is_market_sell = (trade_ev.ev_type == TRADE_SELL_MASK); 
    bool is_market_buy  = (trade_ev.ev_type == TRADE_BUY_MASK);  

    if (active_buy.is_active) {
        if (trade_ev.price < active_buy.price) {
            execute_trade(active_buy.price, active_buy.remaining_qty, true, trade_ev.exch_ts, false);
            active_buy.remaining_qty = 0;
            active_buy.is_active = false;
            active_buy.is_cancel_pending = false; 
        } 
        else if (trade_ev.price == active_buy.price && is_market_sell) {
            double trade_qty_left = trade_ev.qty;
            if (active_buy.queue_ahead > 0) {
                double consumption = std::min(active_buy.queue_ahead, trade_qty_left);
                active_buy.queue_ahead -= consumption;
                trade_qty_left -= consumption;
            }
            if (active_buy.queue_ahead <= 0 && trade_qty_left > 0) {
                double fill_qty = std::min(active_buy.remaining_qty, trade_qty_left);
                if (fill_qty > 0) {
                    execute_trade(active_buy.price, fill_qty, true, trade_ev.exch_ts, false);
                    active_buy.remaining_qty -= fill_qty;
                }
                if (active_buy.remaining_qty <= 1e-9) {
                    active_buy.is_active = false;
                    active_buy.is_cancel_pending = false;
                }
            }
        }
    }

    if (active_sell.is_active) {
        if (trade_ev.price > active_sell.price) {
            execute_trade(active_sell.price, active_sell.remaining_qty, false, trade_ev.exch_ts, false);
            active_sell.remaining_qty = 0;
            active_sell.is_active = false;
            active_sell.is_cancel_pending = false;
        } 
        else if (trade_ev.price == active_sell.price && is_market_buy) {
            double trade_qty_left = trade_ev.qty;
            if (active_sell.queue_ahead > 0) {
                double consumption = std::min(active_sell.queue_ahead, trade_qty_left);
                active_sell.queue_ahead -= consumption;
                trade_qty_left -= consumption;
            }
            if (active_sell.queue_ahead <= 0 && trade_qty_left > 0) {
                double fill_qty = std::min(active_sell.remaining_qty, trade_qty_left);
                if (fill_qty > 0) {
                    execute_trade(active_sell.price, fill_qty, false, trade_ev.exch_ts, false);
                    active_sell.remaining_qty -= fill_qty;
                }
                if (active_sell.remaining_qty <= 1e-9) {
                    active_sell.is_active = false;
                    active_sell.is_cancel_pending = false;
                }
            }
        }
    }
}

void HighFreqBacktester::execute_trade(double px, double qty, bool is_buy, int64_t ts, bool is_taker) {
    double notional = px * qty;
    double fee_or_rebate = is_taker ? (notional * taker_fee_rate) : (notional * rebate_rate);
    
    if (is_buy) {
        cash -= notional;
        position += qty;
    } else {
        cash += notional;
        position -= qty;
    }
    
    cash += fee_or_rebate;
    total_volume += notional;
    
    trade_history.push_back({ts, is_buy, px, qty, fee_or_rebate, position});
}