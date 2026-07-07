/**
 * Deterministic latency sensitivity test harness.
 *
 * Usage:
 *   test_latency.exe <latency_us> [data_path]
 *
 * Example:
 *   test_latency.exe 9000  tests/synthetic_data.bin
 *   test_latency.exe 10000 tests/synthetic_data.bin
 *
 * Output:
 *   trade_history_<latency_us>.csv  — for diff comparison
 *   Prints trade count + final equity to stdout
 */

#include "../cppmodules/HighFreqBacktester.h"
#include "../cppmodules/Reporter.h"
#include <iostream>
#include <fstream>
#include <cstdlib>
#include <cstdio>

int main(int argc, char* argv[]) {
    // ── Parse arguments ──────────────────────────────────────────────
    int64_t latency = 10000;
    const char* data_path = "tests/synthetic_data.bin";

    if (argc >= 2) latency = std::atoll(argv[1]);
    if (argc >= 3) data_path = argv[2];

    // ── Configure engine ─────────────────────────────────────────────
    HighFreqBacktester engine;
    engine.latency_us = latency;

    // ── Load and replay ──────────────────────────────────────────────
    std::ifstream ifs(data_path, std::ios::binary);
    if (!ifs) {
        std::cerr << "ERROR: Cannot open " << data_path << std::endl;
        return 1;
    }

    int64_t first_ts = 0, last_ts = 0;
    TickEvent ev;
    size_t tick_count = 0;

    while (ifs.read(reinterpret_cast<char*>(&ev), sizeof(TickEvent))) {
        if (first_ts == 0) first_ts = ev.exch_ts;
        last_ts = ev.exch_ts;
        engine.on_tick(ev);
        tick_count++;
    }

    // ── Report ───────────────────────────────────────────────────────
    double final_equity = engine.cash + engine.position * engine.last_price;

    std::cout << "========================================" << std::endl;
    std::cout << "  latency     : " << latency << " us" << std::endl;
    std::cout << "  ticks       : " << tick_count << std::endl;
    std::cout << "  trades      : " << engine.trade_history.size() << std::endl;
    std::cout << "  final equity: " << final_equity << " USD" << std::endl;
    std::cout << "  position    : " << engine.position << std::endl;
    std::cout << "  cash        : " << engine.cash << std::endl;
    std::cout << "========================================" << std::endl;

    // ── Export trade history ─────────────────────────────────────────
    char fname[256];
    std::snprintf(fname, sizeof(fname), "trade_history_%lld.csv", latency);
    std::ofstream tr(fname);
    if (tr) {
        tr << "timestamp,side,price,qty,fee_or_rebate,position\n";
        for (const auto& t : engine.trade_history) {
            tr << t.ts << ","
               << (t.is_buy ? "BUY" : "SELL") << ","
               << std::fixed << std::setprecision(2) << t.price << ","
               << std::setprecision(4) << t.qty << ","
               << std::setprecision(6) << t.fee_or_rebate << ","
               << t.position_after << "\n";
        }
        tr.close();
        std::cout << "  exported     : " << fname << std::endl;
    }

    return 0;
}
