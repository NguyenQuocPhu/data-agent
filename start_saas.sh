#!/bin/bash
echo -e "\e[36m==========================================\e[0m"
echo -e "\e[36m   LAMBDA SaaS POC - Startup Script\e[0m"
echo -e "\e[36m==========================================\e[0m"

# 1. Start FastAPI Backend in background
echo -e "\e[33m[1/2] Starting FastAPI Backend on port 8000...\e[0m"
python api_server.py &
BACKEND_PID=$!

# Wait a couple of seconds to let backend initialize
sleep 2

# 2. Start Next.js Frontend
echo -e "\e[33m[2/2] Starting Next.js Frontend on port 3000...\e[0m"
cd ui/deepanalyze_frontend

if command -v pnpm &> /dev/null; then
    pnpm run dev &
else
    npm run dev &
fi
FRONTEND_PID=$!

echo -e "\e[32m==========================================\e[0m"
echo -e "\e[32m SaaS POC is running!\e[0m"
echo -e " Backend API : http://localhost:8000"
echo -e " UI Dashboard: http://localhost:3000"
echo -e "\e[32m==========================================\e[0m"
echo -e "\e[90mPress Ctrl+C to stop both servers.\e[0m"

# Handle graceful shutdown
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
