#pragma once
#include "HighFreqBacktester.h"
#include <string>

void calculate_metrics(const HighFreqBacktester& engine, int64_t first_ts, int64_t last_ts);
void export_to_csv(const HighFreqBacktester& engine, const std::string& eq_filename = "equity_curve.csv", const std::string& tr_filename = "trade_history.csv");