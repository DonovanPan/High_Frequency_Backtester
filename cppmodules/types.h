#pragma once
#include <cstdint>

#pragma pack(push, 1)
struct TickEvent {
    uint64_t ev_type;
    int64_t  exch_ts;
    double   price;
    double   qty;
};
#pragma pack(pop)

constexpr uint64_t DEPTH_BUY_MASK  = (1ULL << 28) | 1;
constexpr uint64_t DEPTH_SELL_MASK = (1ULL << 28) | 2;
constexpr uint64_t TRADE_BUY_MASK  = (1ULL << 31) | 1;
constexpr uint64_t TRADE_SELL_MASK = (1ULL << 31) | 2;

struct TradeRecord {
    int64_t ts;
    bool is_buy;
    double price;
    double qty;
    double fee_or_rebate; // 费用/返佣
    double position_after;
};

enum class ActionType {
    PLACE_ORDER,
    CANCEL_ORDER
};

struct PendingAction {
    int64_t trigger_ts;
    ActionType type;
    bool is_buy;
    double price; 
    double qty;   
    uint64_t target_order_id; // 追踪具体操作的订单ID
    
    bool operator>(const PendingAction& other) const {
        return trigger_ts > other.trigger_ts;
    }
};

struct LocalOrder {
    uint64_t order_id = 0;    // 全局唯一订单编号
    bool is_active = false;
    double price = 0.0;
    double qty = 0.0;
    double remaining_qty = 0.0; 
    double queue_ahead = 0.0;
    bool is_cancel_pending = false; 
};