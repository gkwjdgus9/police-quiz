#!/bin/bash
# macOS: 더블클릭하면 터미널이 열리고 앱이 뜬다. (처음 한 번은 터미널 > 보안 설정에서 허용이 필요할 수 있다)
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  python3 app.py
else
  echo "Python 3.11 이상이 필요합니다. https://www.python.org/downloads/"
  read -r -p "Enter 를 누르면 닫힙니다."
fi
