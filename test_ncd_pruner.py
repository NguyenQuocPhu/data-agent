import pandas as pd
import zlib
import sys
import os

# Add parent directory to path to import dgm_agent
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dgm_agent.blackboard import FileAgent

def test_ncd():
    # Khởi tạo mock FileAgent
    agent = FileAgent("test_01", "test_cluster", [])
    
    # Tạo một dataframe giả với 1000 dòng rác và 1 dòng chứa thông tin vàng
    data = []
    for i in range(100):
        data.append({"Price": 100+i, "Volume": 500+i, "Date": f"2023-01-{i%28+1}"})
        
    # Chèn dòng thông tin thật ở giữa
    data.append({"Price": 25, "Volume": 0.45, "Date": "Age=25, APP-Z=0.45, True"})
    
    for i in range(100):
        data.append({"Price": 200+i, "Volume": 600+i, "Date": f"2023-02-{i%28+1}"})
        
    df = pd.DataFrame(data)
    
    goal_hint = "Question: Find the row where Age is 25 and APP-Z is 0.45."
    
    print("Goal Hint:", goal_hint)
    print(f"Tổng số dòng ban đầu: {len(df)}")
    
    # Thử prune
    preview = agent._prune_dataframe(df, goal_hint)
    print("\n--- KẾT QUẢ PRUNE (TOP 20 DÒNG TỐT NHẤT) ---")
    print(preview)
    
    print("\n--- NHẬN XÉT ---")
    if "Age=25" in preview and "APP-Z=0.45" in preview:
        print("✅ Thành công! MDL-Pruner đã bắt được dòng mục tiêu từ hàng trăm dòng nhiễu.")
    else:
        print("❌ Thất bại! NCD không bắt được dòng mục tiêu.")

if __name__ == "__main__":
    test_ncd()
