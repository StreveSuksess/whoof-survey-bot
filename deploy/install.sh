#!/bin/sh
set -eu

# Run after inspecting the host, from an unpacked runtime archive.
# The existing secret file is transferred separately, never included in source.
[ "$(id -u)" = 0 ] || { echo 'Run as root.' >&2; exit 1; }
command -v systemctl >/dev/null
/usr/bin/python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"; import sqlite3, ssl, fcntl'
[ -d /run/systemd/system ] || { echo 'A running systemd host is required.' >&2; exit 1; }
[ -s /etc/whoof-survey.env ] || { echo 'Install the secret at /etc/whoof-survey.env first.' >&2; exit 1; }
chown root:root /etc/whoof-survey.env
chmod 600 /etc/whoof-survey.env

package_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
for runtime_file in bot.py engine.py storage.py presentation.py instrument.json; do
    [ -f "$package_dir/$runtime_file" ]
done
if ! getent passwd whoof-survey >/dev/null; then
    useradd --system --user-group --home-dir /var/lib/whoof-survey --shell /usr/sbin/nologin whoof-survey
fi
[ "$(id -u whoof-survey)" != 0 ]
if systemctl is-active --quiet whoof-survey.service; then
    systemctl stop whoof-survey.service
fi
install -d -o root -g root -m 755 /opt/whoof-survey
for runtime_file in bot.py engine.py storage.py presentation.py instrument.json; do
    install -o root -g root -m 644 "$package_dir/$runtime_file" "/opt/whoof-survey/$runtime_file"
done
install -d -o whoof-survey -g whoof-survey -m 700 /var/lib/whoof-survey
install -o root -g root -m 644 "$package_dir/deploy/whoof-survey.service" /etc/systemd/system/whoof-survey.service
systemd-analyze verify /etc/systemd/system/whoof-survey.service
systemctl daemon-reload
systemctl enable --now whoof-survey.service
systemctl is-active whoof-survey.service
