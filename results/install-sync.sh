#!/bin/sh
set -eu
[ "$(id -u)" = 0 ]
[ -s /etc/whoof-sheets-sync.env ]
[ -s /etc/whoof-sheets-sync/google-key.json ]
getent passwd whoof-survey >/dev/null
package_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install -d -o root -g root -m 755 /opt/whoof-survey/results
for runtime_file in sync.py schema.json normalize.py google-normalization.json sheets_api.py direct_sync.py requirements.txt; do
    install -o root -g root -m 644 "$package_dir/$runtime_file" "/opt/whoof-survey/results/$runtime_file"
done
install -d -o root -g whoof-survey -m 750 /etc/whoof-sheets-sync
chown root:whoof-survey /etc/whoof-sheets-sync/google-key.json
chmod 640 /etc/whoof-sheets-sync/google-key.json
/usr/bin/python3 -m venv /opt/whoof-survey/results/venv
/opt/whoof-survey/results/venv/bin/pip install --disable-pip-version-check -r "$package_dir/requirements.txt"
chown -R root:whoof-survey /opt/whoof-survey/results/venv
chmod -R g+rX /opt/whoof-survey/results/venv
chown root:root /etc/whoof-sheets-sync.env
chmod 600 /etc/whoof-sheets-sync.env
for unit in whoof-sheets-sync.service whoof-sheets-sync.timer; do
    install -o root -g root -m 644 "$package_dir/$unit" "/etc/systemd/system/$unit"
done
systemd-analyze verify /etc/systemd/system/whoof-sheets-sync.service /etc/systemd/system/whoof-sheets-sync.timer
set -a
. /etc/whoof-sheets-sync.env
set +a
runuser -u whoof-survey -- env GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_APPLICATION_CREDENTIALS" WHOOF_ANSWERS_ID="$WHOOF_ANSWERS_ID" WHOOF_CONTACTS_ID="$WHOOF_CONTACTS_ID" /opt/whoof-survey/results/venv/bin/python /opt/whoof-survey/results/direct_sync.py --check-only
systemctl daemon-reload
systemctl enable --now whoof-sheets-sync.timer
systemctl start whoof-sheets-sync.service
systemctl is-active whoof-survey.service
