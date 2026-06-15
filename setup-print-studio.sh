#!/bin/bash
set -e

echo "============================================"
echo " Print Studio - Установка"
echo "============================================"
echo ""

# Проверка Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python3 не найден. Установите: sudo apt install python3"
    exit 1
fi

echo "✅ Python3: $(python3 --version)"

# Установка зависимостей
echo ""
echo "📦 Установка зависимостей..."

# apt пакеты
APT_PKGS=(
    python3-pip
    python3-pil
    python3-pil.imagetk
    cups
    cups-filters
    hplip
    hplip-gui
    hpijs-ppds
    printer-driver-hpijs
    epson-inkjet-printer-escpr
    printer-driver-escpr
    printer-driver-gutenprint
    foomatic-db
    foomatic-db-engine
    foomatic-db-hpijs
)

echo "sudo apt install ${APT_PKGS[*]}"
sudo apt update
sudo apt install -y "${APT_PKGS[@]}"

# pip пакеты
echo ""
echo "📦 Установка Python пакетов..."
pip3 install PySide6 Pillow pycups 2>/dev/null || {
    echo "⚠ pip install не удался, пакеты могут уже стоять"
}

echo ""
echo "🎉 Готово!"
echo ""
echo "Запуск: python3 $HOME/print-studio.py"
echo "Или:   ./print-studio.py"
echo ""
