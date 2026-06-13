import math
import random
from typing import List, Dict

class EvolutionStrategy:
    """
    [Baseline Strategy]
    Thuật toán gốc dùng để chọn lọc tự nhiên (Parent Selection) trong Outer Loop.
    File này đóng vai trò là 'Seed DNA' và sẽ bị LLM viết đè (Meta-Evolution) sau mỗi 5 chu kỳ.
    
    Thuật toán hiện tại: UCB1 (Upper Confidence Bound)
    Cân bằng giữa Exploitation (Điểm số cao) và Exploration (Số lần sinh con ít).
    """

    def select_parent(self, archive: List[Dict]) -> Dict:
        """
        Chọn ra một candidate tốt nhất từ archive để làm cha mẹ cho thế hệ đột biến tiếp theo.
        archive: Danh sách các dict, mỗi dict là một candidate đã được đánh giá.
        """
        if not archive:
            return {}

        # Lọc ra những ứng viên đã chạy qua Outer Loop (có fitness_score) 
        # hoặc ít nhất đã qua được Inner Loop (có epiplexity_score)
        valid_candidates = [
            node for node in archive 
            if "fitness_score" in node or "epiplexity_score" in node
        ]
        
        if not valid_candidates:
            # Fallback nếu archive toàn rác
            return random.choice(archive)

        # Tính tổng số lượng "con" (children) đã được sinh ra từ toàn bộ quần thể
        # (Để tránh chia cho 0 trong công thức log, ta cộng thêm 1)
        total_children_generated = sum(node.get("children_count", 0) for node in valid_candidates) + 1
        
        best_node = None
        max_ucb_score = -float('inf')
        
        # Hằng số Khám phá (Exploration Constant C). 
        # Tăng C sẽ ép hệ thống chọn các node ít được thử nghiệm hơn.
        exploration_constant = 1.414 

        for node in valid_candidates:
            # 1. Exploitation: Lấy điểm thực chiến (fitness_score) làm ưu tiên số 1, 
            # nếu chưa có thì dùng tạm điểm surrogate (epiplexity_score) thu nhỏ.
            exploitation_score = node.get("fitness_score", node.get("epiplexity_score", 0.1) * 0.1)
            
            # Số lần node này đã được chọn làm cha mẹ
            node_children = node.get("children_count", 0)
            
            # 2. Exploration & Tính UCB1
            if node_children == 0:
                # Nếu node chưa từng đẻ con, đẩy điểm UCB lên vô cực để ép buộc thuật toán phải khám phá nó
                ucb_score = float('inf')
            else:
                # Công thức UCB1 chuẩn: Vi + C * sqrt(ln(N) / ni)
                exploration_term = exploration_constant * math.sqrt(math.log(total_children_generated) / node_children)
                ucb_score = exploitation_score + exploration_term
                
            # Thêm một lượng nhiễu ngẫu nhiên siêu nhỏ để phá vỡ các trường hợp hòa điểm (Tie-breaker)
            ucb_score += random.uniform(0.0, 0.0001)
            
            # 3. Cập nhật node có UCB cao nhất
            if ucb_score > max_ucb_score:
                max_ucb_score = ucb_score
                best_node = node

        return best_node if best_node else random.choice(valid_candidates)
