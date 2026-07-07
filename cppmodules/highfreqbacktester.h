#pragma once
#include "Types.h"
#include <vector>
#include <queue>
#include <utility>
#include <map>

class HighFreqBacktester {
public:
    double cash = 10000.0;
    double initial_cash = 10000.0;
    double position = 0.0;
    double total_volume = 0.0;
    
    // Maker 0.0005手续费，Taker 万分之五惩罚
    double rebate_rate = 0.00005; 
    double taker_fee_rate = -0.0005; 
    
    // 完整的本地订单簿
    std::map<double, double, std::greater<double>> book_bids; // 买盘降序
    std::map<double, double> book_asks;                       // 卖盘升序
    
    int64_t current_ob_ts = 0; // 追踪快照时间戳，用于清除幽灵订单

    double best_bid = 0.0;
    double best_bid_qty = 0.0; 
    double best_ask = 0.0;
    double best_ask_qty = 0.0;
    double last_price = 0.0;

    double order_qty = 0.02;
    double max_position = 0.1; 
    int64_t latency_us = 20000; 

    uint64_t next_order_id = 1; // 订单自增ID

    LocalOrder active_buy;
    LocalOrder active_sell;
    
    bool is_buy_place_pending = false; 
    bool is_sell_place_pending = false;

    std::priority_queue<PendingAction, std::vector<PendingAction>, std::greater<PendingAction>> event_queue;

    std::vector<std::pair<int64_t, double>> equity_curve;
    std::vector<TradeRecord> trade_history;
    
    int64_t last_record_ts = 0;
    double max_equity = 10000.0;
    double max_drawdown = 0.0;

    HighFreqBacktester();

    void on_tick(const TickEvent& ev);

private:
    uint64_t send_place(bool is_buy, double px, double qty, int64_t current_ts);
    void send_cancel(bool is_buy, uint64_t oid, int64_t current_ts);
    void process_delayed_events(int64_t current_ts);
    void simulate_queue_matching(const TickEvent& trade_ev);
    void execute_trade(double px, double qty, bool is_buy, int64_t ts, bool is_taker);
};