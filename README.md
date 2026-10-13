# Whoof Telegram survey

Python 3.10+ / standard library / SQLite / systemd. Core quantitative questionnaire for dog owners. Bot: [@whoofserveybot](https://t.me/whoofserveybot).

## Install on the existing Whoof server

As root, clone this repository into a new directory. Inspect existing `/opt/whoof-survey`, `/etc/whoof-survey.env` and `/var/lib/whoof-survey` before an upgrade. Preserve existing runtime and participant data.

```sh
git clone https://github.com/StreveSuksess/whoof-survey-bot.git /tmp/whoof-survey-source
cd /tmp/whoof-survey-source
python3 -m unittest discover -p 'test_*.py' -v
python3 deploy/setup-token.py
sh deploy/install.sh
systemctl status whoof-survey --no-pager
```

`setup-token.py` asks for the token with echo disabled, checks the exact Whoof bot identity and absence of a webhook, and creates root0600 `/etc/whoof-survey.env`. It refuses to replace an existing file. `--hex` accepts lowercase hexadecimal input for a VNC keyboard. Never put a token in a shell command, GitHub or logs.

The installer uses existing Python/systemd, creates a dedicated service user and private state directory, and enables one polling service. It does not install packages, modify networking or reboot the host. The bot opens no incoming port. Systemd restarts failures and starts it at boot.

## Participant flow and data

One question at a time, inline buttons, branching, saved progress, `/start`, `/back`, `/skip`, `/help`, `/delete`. Answer mutations and update cursor commit together; outgoing delivery can fail after commit, and `/start` resumes. Core is the deployment default.

Private databases live in `/var/lib/whoof-survey/`: responses/Telegram chat IDs and voluntary contacts are stored separately, linked by participant code. This is not anonymity or encryption. Inactive records are purged after365 days. Organizer must also manage exported copies and backups.

See [operations](deploy/README.md) for status/restart/export commands. Deployed on Linux/systemd on2026-10-10. Progress/branding update deployed from8ce8be9 on2026-10-13; all37 tests pass on the host. Every question shows its ordinal, visual progress and remaining reachable range (including current); unknown branches narrow as answered, optional explanation notes do not advance progress. Screening is one separate check. The exact Figma mascot is installed as the bot avatar; source assets are in assets/. Service active/enabled, Telegram readiness checked; existing private data retained. Short meaningful text buttons replace numbers, one option per row; exact source labels can be expanded with “Полные варианты”. The bot advances immediately after an answer. Optional explanation is added to the immediately previous answer through “Пояснить прошлый ответ”, with saved next-question selections retained on cancel. Prior pending notes remain compatible. Organizer confirmed the original introduction; live verification of the new controls and full participant path remains pending.
