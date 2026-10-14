#!/bin/bash
# XAU_SCALP5 Dashboard Launcher
# Usage: ./run_dashboard.sh [port]

set -e

PORT=${1:-8501}
DASHBOARD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$DASHBOARD_DIR/.venv"
DASHBOARD_FILE="$DASHBOARD_DIR/dashboard_streamlit.py"

echo "🚀 Starting XAU_SCALP5 Dashboard..."
echo "   Directory: $DASHBOARD_DIR"
echo "   Port: $PORT"

# Check virtual environment
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment not found at $VENV_DIR"
    echo "   Run: python -m venv .venv && .venv/bin/pip install -r requirements_dashboard.txt"
    exit 1
fi

# Activate venv and install/check dependencies
echo "📦 Checking dependencies..."
"$VENV_DIR/bin/pip" install -q -r "$DASHBOARD_DIR/requirements_dashboard.txt"

# Check database
DB_PATH="$DASHBOARD_DIR/data/scalp5.db"
if [ ! -f "$DB_PATH" ]; then
    echo "❌ Database not found at $DB_PATH"
    exit 1
fi

echo "✅ Database found: $DB_PATH"

# Launch Streamlit
echo "🌐 Launching dashboard on http://localhost:$PORT"
echo "   Press Ctrl+C to stop"
echo ""

cd "$DASHBOARD_DIR"
exec "$VENV_DIR/bin/streamlit" run "$DASHBOARD_FILE" \
    --server.port "$PORT" \
    --server.address "0.0.0.0" \
    --server.headless true \
    --browser.gatherUsageStats false \
    --theme.base "light" \
    --theme.primaryColor "#6750A4" \
    --theme.backgroundColor "#FFFBFE" \
    --theme.secondaryBackgroundColor "#E7E0EC" \
    --theme.textColor "#1C1B1F"