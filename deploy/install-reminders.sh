#!/bin/sh
# Backup private data before the additive reminder metadata migration.
set -eu
[ "$(id -u)" = 0 ]
package_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
backup_dir=/var/backups/whoof-survey/reminders-2026-10-14
if [ ! -e "$backup_dir" ]; then
    install -d -o root -g root -m 700 "$backup_dir"
    cp -a /opt/whoof-survey "$backup_dir/runtime"
    python3 - "$backup_dir" <<'PY'
import os,sqlite3,sys
from pathlib import Path
for name in ('responses.sqlite','contacts.sqlite'):
    source=sqlite3.connect('file:/var/lib/whoof-survey/'+name+'?mode=ro',uri=True)
    path=Path(sys.argv[1])/name
    dest=sqlite3.connect(path)
    with dest: source.backup(dest)
    dest.close(); source.close(); os.chmod(path,0o600)
print('Private SQLite backup created; original data preserved.')
PY
fi
sh "$package_dir/deploy/install.sh"
systemctl is-active whoof-survey.service whoof-sheets-sync.timer
