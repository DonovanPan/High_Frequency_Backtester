#include "Reporter.h"
#include <iostream>
#include <fstream>
#include <iomanip>
#include <cmath>

void calculate_metrics(const HighFreqBacktester& engine, int64_t first_ts, int64_t last_ts) {
    double final_equity = engine.cash + engine.position * engine.last_price;
    double total_return = (final_equity - engine.initial_cash) / engine.initial_cash;
    double total_turnover = engine.total_volume / engine.initial_cash;

    double days_passed = static_cast<double>(last_ts - first_ts) / 86400000000.0;
    if (days_passed <= 0.0001) days_passed = 0.0001; 

    double annual_multiplier = 365.0 / days_passed;
    double annualized_return = total_return * annual_multiplier;
    double daily_turnover = total_turnover / days_passed; 

    double sharpe = 0.0;
    if (engine.equity_curve.size() > 2) {
        double sum_returns = 0;
        std::vector<double> hourly_returns;
        for (size_t i = 1; i < engine.equity_curve.size(); ++i) {
            double r = (engine.equity_curve[i].second - engine.equity_curve[i-1].second) / engine.equity_curve[i-1].second;
            hourly_returns.push_back(r);
            sum_returns += r;
        }
        double mean_return = sum_returns / hourly_returns.size();
        double sum_sq_diff = 0;
        for (double r : hourly_returns) sum_sq_diff += pow(r - mean_return, 2);
        double std_dev = sqrt(sum_sq_diff / hourly_returns.size());
        
        sharpe = (std_dev > 0) ? (mean_return / std_dev) * sqrt(24 * 365.0) : 0; 
    }

    double calmar = (engine.max_drawdown > 0) ? annualized_return / engine.max_drawdown : 0;

    std::cout << std::fixed << std::setprecision(4);
    std::cout << "\n========== 高频回测报告 ==========" << std::endl;
    std::cout << "测试跨度: " << days_passed << " 天" << std::endl;
    std::cout << "最终净值: " << final_equity << " USD" << std::endl;
    std::cout << "累计收益: " << total_return * 100 << "%" << std::endl;
    std::cout << "日均周转: " << daily_turnover << " 倍" << std::endl;
    std::cout << "最大回撤: " << engine.max_drawdown * 100 << "%" << std::endl;
    std::cout << "年化收益: " << annualized_return * 100 << "%" << std::endl;
    std::cout << "年化夏普: " << sharpe << std::endl;
    std::cout << "卡玛比率: " << calmar << std::endl;
    std::cout << "==================================" << std::endl;
}

void export_to_csv(const HighFreqBacktester& engine, const std::string& eq_filename, const std::string& tr_filename) {
    std::cout << "正在导出数据..." << std::endl;
    std::ofstream eq_file(eq_filename);
    if (eq_file) {
        eq_file << "timestamp,equity\n";
        for (const auto& pt : engine.equity_curve) {
            eq_file << pt.first << "," << std::fixed << std::setprecision(6) << pt.second << "\n";
        }
        eq_file.close();
    }

    std::ofstream tr_file(tr_filename);
    if (tr_file) {
        tr_file << "timestamp,side,price,qty,fee_or_rebate,position\n";
        for (const auto& tr : engine.trade_history) {
            tr_file << tr.ts << "," 
                    << (tr.is_buy ? "BUY" : "SELL") << ","
                    << std::fixed << std::setprecision(2) << tr.price << ","
                    << std::setprecision(4) << tr.qty << ","
                    << std::setprecision(6) << tr.fee_or_rebate << "," 
                    << tr.position_after << "\n";
        }
        tr_file.close();
    }
    std::cout << "导出完成！" << std::endl;
}