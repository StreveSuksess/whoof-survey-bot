#!/bin/sh
# Update existing services only; credentials and original databases remain in place.
set -eu
[ "$(id -u)" = 0 ]
package_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
set -a
. /etc/whoof-sheets-sync.env
set +a
# Validate current native headers and read-only snapshots before stopping the bot.
/opt/whoof-survey/results/venv/bin/python "$package_dir/results/direct_sync.py" --check-only
backup_dir=/var/backups/whoof-survey/short-2026-10-14
if [ ! -e "$backup_dir" ]; then
install -d -o root -g root -m 700 "$backup_dir"
cp -a /opt/whoof-survey "$backup_dir/runtime"
python3 - "$backup_dir" <<'PY'
import os,sqlite3,sys
from pathlib import Path
target=Path(sys.argv[1])
for name in ('responses.sqlite','contacts.sqlite'):
    source=sqlite3.connect('file:/var/lib/whoof-survey/'+name+'?mode=ro',uri=True)
    dest=sqlite3.connect(target/name)
    with dest: source.backup(dest)
    dest.close(); source.close(); os.chmod(target/name,0o600)
print('Private backup created; source databases preserved')
PY
fi
systemctl stop whoof-sheets-sync.timer whoof-sheets-sync.service whoof-survey.service
for file in bot.py engine.py storage.py presentation.py instrument.json; do
    install -o root -g root -m 644 "$package_dir/$file" "/opt/whoof-survey/$file"
done
for file in sync.py schema.json normalize.py google-normalization.json sheets_api.py direct_sync.py requirements.txt; do
    install -o root -g root -m 644 "$package_dir/results/$file" "/opt/whoof-survey/results/$file"
done
systemctl start whoof-survey.service
systemctl start whoof-sheets-sync.timer
systemctl start whoof-sheets-sync.service
systemctl is-active whoof-survey.service whoof-sheets-sync.timer
systemctl show whoof-survey.service -p MainPID -p TasksCurrent -p SubState
