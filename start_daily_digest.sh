#!/bin/zsh
set -u

PORT="8503"
URL="http://localhost:${PORT}"
APP_DIR="${0:A:h}"
APP_PY="$APP_DIR/daily_a_share_digest_app.py"
VENV_DIR="$APP_DIR/.venv"
LOCAL_STREAMLIT="$VENV_DIR/bin/streamlit"
PERSONAL_STREAMLIT="$HOME/Quant/qlib_env/bin/streamlit"
LOG_FILE="$APP_DIR/daily_digest_app.log"

mkdir -p "$APP_DIR"

if [[ -x "$PERSONAL_STREAMLIT" ]]; then
  STREAMLIT="$PERSONAL_STREAMLIT"
else
  if [[ ! -x "$LOCAL_STREAMLIT" ]]; then
    /usr/bin/python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/python" -m pip install --upgrade pip
    if [[ -f "$APP_DIR/requirements.txt" ]]; then
      "$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
    else
      "$VENV_DIR/bin/python" -m pip install streamlit pandas
    fi
  fi
  STREAMLIT="$LOCAL_STREAMLIT"
fi

if ! /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  nohup "$STREAMLIT" run "$APP_PY" --server.port "$PORT" --server.headless true > "$LOG_FILE" 2>&1 &
  sleep 4
fi

/usr/bin/open "$URL"
