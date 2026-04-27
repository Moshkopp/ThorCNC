#!/bin/bash
# wj200_vfd Install Script
# Verwendung: ./install_wj200.sh

set -e

USER=$(whoami)
HOME_DIR="/home/$USER"

echo "=== wj200_vfd Installer ==="
echo "Benutzer: $USER"
echo ""

# 1. Abhängigkeiten prüfen
echo "[1/4] Prüfe Abhängigkeiten..."
sudo apt-get install -y build-essential libmodbus-dev linuxcnc-uspace-dev 2>/dev/null || \
sudo pacman -S --needed base-devel libmodbus 2>/dev/null || \
echo "Bitte manuell installieren: build-essential libmodbus-dev linuxcnc-uspace-dev"

# 2. modbus.h Symlinks setzen falls nötig
echo "[2/4] Prüfe modbus Header..."
if [ ! -f /usr/include/modbus.h ] && [ -f /usr/include/modbus/modbus.h ]; then
    echo "Setze modbus Symlinks..."
    sudo ln -sf /usr/include/modbus/modbus.h /usr/include/modbus.h
    sudo ln -sf /usr/include/modbus/modbus-version.h /usr/include/modbus-version.h
    sudo ln -sf /usr/include/modbus/modbus-rtu.h /usr/include/modbus-rtu.h
    sudo ln -sf /usr/include/modbus/modbus-tcp.h /usr/include/modbus-tcp.h
fi

# 3. Kompilieren
echo "[3/4] Kompiliere wj200_vfd..."
halcompile --userspace wj200_vfd.comp

gcc -I$HOME_DIR -I/usr/include -I/usr/include/linuxcnc \
    -URTAPI -U__MODULE__ -DULAPI -Os \
    -o wj200_vfd wj200_vfd.c \
    -Wl,-rpath,/lib -L/lib \
    -llinuxcnchal -lmodbus

# 4. Installieren
echo "[4/4] Installiere nach /usr/bin/..."
sudo cp wj200_vfd /usr/bin/wj200_vfd
sudo chmod +x /usr/bin/wj200_vfd

# Serielle Port Gruppe (dialout auf Debian/Ubuntu, uucp auf Arch)
if getent group dialout > /dev/null; then
    SERIAL_GROUP="dialout"
elif getent group uucp > /dev/null; then
    SERIAL_GROUP="uucp"
fi

if [ -n "$SERIAL_GROUP" ] && ! groups $USER | grep -q $SERIAL_GROUP; then
    echo "Füge $USER zur $SERIAL_GROUP Gruppe hinzu..."
    sudo usermod -aG $SERIAL_GROUP $USER
    echo "WICHTIG: Neu einloggen damit $SERIAL_GROUP Gruppe aktiv wird!"
fi

# Prüfen
echo ""
echo "=== Prüfe Installation ==="
ldd /usr/bin/wj200_vfd | grep modbus
echo ""
echo "=== Fertig! ==="
echo "Binary: /usr/bin/wj200_vfd"
