#include "HighFreqBacktester.h"
#include "Reporter.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <iomanip>

int main() {
    std::setlocale(LC_ALL, "zh_CN.UTF-8");
    HighFreqBacktester engine;
    
    int64_t first_ts = 0;
    int64_t last_ts = 0;

    for (int day = 1; day <= 31; ++day) {
        std::ostringstream oss;
        oss << R"(C:\Users\mrp\Desktop\cpp_market_data\market_data_2026_01_)"
            << std::setw(2) << std::setfill('0') << day 
            << ".bin";
        
        std::string file_path = oss.str();
        std::ifstream ifs(file_path, std::ios::binary);

        if (!ifs) {
            std::cerr << "⚠️ 警告：无法打开文件，跳过 -> " << file_path << std::endl;
            continue; 
        }

        std::cout << "正在加载并回测: " << file_path << " ..." << std::endl;

        TickEvent ev;
        size_t tick_count = 0;
        
        while (ifs.read(reinterpret_cast<char*>(&ev), sizeof(TickEvent))) {
            if (first_ts == 0) first_ts = ev.exch_ts; 
            last_ts = ev.exch_ts;                     
            
            engine.on_tick(ev);
            tick_count++;
        }
        
        std::cout << "  -> 本日处理完成，共灌入 " << tick_count << " 个 Tick。当前净值: " 
                  << std::fixed << std::setprecision(2) << (engine.cash + engine.position * engine.last_price) 
                  << " USD\n" << std::endl;
    }

    if (first_ts == 0) {
        std::cerr << "错误：没有读取到任何有效数据！" << std::endl;
        return 1;
    }

    std::cout << "\n 所有日度数据处理完毕，开始计算统计指标..." << std::endl;
    calculate_metrics(engine, first_ts, last_ts);
    export_to_csv(engine); 
    
    return 0;
}