#!/bin/bash
echo "🛠️ Khởi tạo môi trường WSL sạch cho Polyglot Harness..."

# Cập nhật Ubuntu và cài đặt pip, venv
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv

# Tạo và kích hoạt virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Cập nhật pip để tránh các lỗi compile
pip install --upgrade pip

# Cài đặt docker và ép phiên bản swebench
pip install docker
pip install swebench==1.0.1

echo "✅ Môi trường đã sẵn sàng! Chạy 'source .venv/bin/activate' trước khi khởi động Phase 2."
