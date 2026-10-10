# Telegram hosting

Target: existing Play2Go VPS#128980,31.76.24.157. Bot [@whoofserveybot](https://t.me/whoofserveybot), verified through getMe. No active webhook. Deployment is prepared but not yet performed: existing SSH key is rejected and VMmanager requires login.

Python3.10+ with SQLite/SSL and systemd are required. Runtime uses only the Python standard library. The script does not install packages, reinstall the OS, change network settings or reboot the server.

## Files on the server

- `/opt/whoof-survey/`: bot.py,engine.py,storage.py,instrument.json, root-owned code.
- `/etc/whoof-survey.env`: TELEGRAM_BOT_TOKEN and SURVEY_MODE=core, root0600; systemd reads it.
- `/var/lib/whoof-survey/`: responses.sqlite,contacts.sqlite,poller.lock; service user only, directory0700, databases0600.
- `/etc/systemd/system/whoof-survey.service`: one polling service, auto-start/auto-restart. No public HTTP port needed.

After inspecting the host, transfer the code archive separately from the `.env`, install the latter at `/etc/whoof-survey.env`, then run `deploy/install.sh` as root from the extracted archive. Preserve any pre-existing Whoof runtime/data before an upgrade. Never upload `.env`, data or exports to a public repository.

## Operations after deployment

```sh
sudo systemctl status whoof-survey --no-pager
sudo journalctl -u whoof-survey -n 30 --no-pager
sudo systemctl restart whoof-survey
sudo systemctl stop whoof-survey
sudo -u whoof-survey /usr/bin/python3 /opt/whoof-survey/bot.py --data /var/lib/whoof-survey --export /var/lib/whoof-survey/exports/responses.json
```

Export contains completed responses without Telegram chat IDs or contacts. Contacts are stored in their separate SQLite database. Backups/exports need the same access and retention rules as the originals. Built-in purge removes records after365 inactive days. Host paid through2026-11-06 with auto-renew off (observed2026-10-10); service stops if hosting expires.

State mutations and Telegram update cursor are committed together; retried delivery cannot apply the same answer twice. A failure after committing an answer can leave the next message undelivered; `/start` resumes from the saved question. Telegram message delivery itself is not exactly-once. A file lock prevents two pollers sharing one data directory. Do not run another polling instance with a separate directory and the same token.

Verification before participant invitation: service active, restart retains state, `/start` and buttons work in Telegram, one eligible core path completes, invalid amounts/notes are rejected, consent/contact separation and deletion work. Live participant interaction remains untested until server access is provided.
