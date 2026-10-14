# Active short-study integration — 14 October 2026

Only Google Forms and Telegram are active.21contact-free fields plus10metadata columns. Main raw destination is Ответы на форму (2); former raw tab and old Telegram rows are preserved as hidden archives. Contact raw destination remains Ответы на форму (1) in its separate private workbook. Old known-version test sessions stay in SQLite but do not enter the current study; unknown versions fail closed. Optional Other detail shares the question note field. Header mapping is exact and unique; a missing column fails before writing. Legacy instructions below describe former setup and are not the active schema.

# Whoof results storage

Existing private native files:

- Answers: Spreadsheet ID configured privately on the VPS
- Interview contacts: Spreadsheet ID configured privately on the VPS

Each Google Form already writes to its respective native `Ответы на форму (1)` sheet. Telegram SQLite remains authoritative on the VPS. Fillout stays manual import only; its three known preview test records must be flagged before analysis.

## Current deployment state

Direct Sheets API implementation replaces the undeployed Apps Script approach with the user's approval on 2026-10-11. Code is prepared locally and tested:12 direct sync tests and10 existing snapshot tests pass. The real71-column main raw header and3-column contact header were copied through Sheets UI and validated. Cloud/API terms accepted with explicit approval, country Germany per latest clarification. Project Whoof survey sync (rapid-strength-511310-b9) created. Service account/key/file grants and live worker deployment remain pending.

## Runtime

- `sync.py`: reused read-only SQLite snapshot; no chat IDs or Q33 in answer rows, separately consented contacts. Partial/non-target/test records flagged. Telegram only stores last state-change time; original response date remains blank.
- `normalize.py` + `google-normalization.json`: strict raw Sheets header/label normalization. Repeated note columns checked in order, checkbox commas parsed unambiguously, zero/refusal and stale hidden branches handled explicitly.
- `sheets_api.py`: service-account authentication and REST calls restricted to the two Whoof spreadsheet IDs. Writes only derived ranges using explicit string/number values, preventing formula interpretation. Raw tabs, formatting and summary formulas remain intact.
- `direct_sync.py`: reads both sources before any write, merges all answers including manual Fillout, preserves interview scheduling fields by source/contact ID, and updates each workbook atomically. Cross-file failures retry on the next complete snapshot.
- `test_direct_sync.py` and `test_sync.py`: synthetic checks for replay, update/deletion, contact separation, partial-write retry, notes, raw tab isolation, schema failure before writes, timestamps, optional contact and formula-like strings. Live Sheets API/server checks still pending.
- `whoof-sheets-sync.service`/`.timer`: separate once-per-minute worker. Telegram poller does not wait for Google, and installation never restarts the bot.
- `receiver.js`/`receiver.gs`: retained prior draft, inactive. No Apps Script endpoint/HMAC secret is used by direct sync.

## Activation

1. Country/terms completed and dedicated project created. Create service account with **no project IAM roles**, enable Sheets API, no billing setup.
2. At actual access/key screens, review and authorize service key creation/storage and editor grants for the two named spreadsheets. Do not make either spreadsheet public. No Forms/Fillout access is needed.
3. Keep downloaded JSON key private/outside Git, local permissions0600. On VPS use `python3 results/setup-sheets-key.py --answers-id <private-id> --contacts-id <private-id>` in ordinary VNC: base64 input is hidden, file creation exclusive, no credentials printed.
4. Publish runtime-only files to the minimal bot repository after a staged secret/data check, pull through existing VNC. No SSH/fullscreen. Install Python venv support if necessary from official Ubuntu packages.
5. `sh results/install-sync.sh` installs an isolated venv, makes the key root:whoof-survey0640 inside root:whoof-survey0750, runs read-only live validation, then installs the independent timer. Env root:root0600 includes private `WHOOF_ANSWERS_ID` / `WHOOF_CONTACTS_ID` and points to `GOOGLE_APPLICATION_CREDENTIALS=/etc/whoof-sheets-sync/google-key.json`. Optional `WHOOF_TEST_IDS` flags organizer participant codes.
6. Compare two live runs for identical source IDs/counts, verify contacts absent from answer rows, scheduling fields retained and bot healthy. Capture proof and report actual state.

## Limits

Telegram maximum1000 records; Google maximum10000 rows per run. Sources are complete snapshots. Failed reads/unknown headers fail closed instead of clearing rows. A failed cross-file write may leave derived tables inconsistent until retry; raw Forms/SQLite remain unchanged. Source reads are sequential, so changes during a run appear on the next run.

Google raw exports do not include native Form response IDs. Derived Google IDs use original numeric timestamp plus occurrence among identical timestamps. Ordinary answer-value edits and removal of distinct timestamps retain other IDs. **Do not manually sort, reorder or edit timestamp columns of raw Forms sheets.** Removing one of multiple exactly equal timestamps can change occurrence identity and needs review of associated contact scheduling notes. Cross-channel person deduplication is not inferred.

Interview scheduling columns are plain values. Free text/contacts, including strings starting with `=`, `+` or `@`, are literal strings. Provider version history/backups may retain deleted rows; Telegram `/delete` reconciles current derived records only. The two files have independent sharing. Uploaded XLSX staging copies remain separate from these native files.
