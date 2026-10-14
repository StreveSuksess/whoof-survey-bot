# Two-source short-study results

Active version: whoof-quant-2026-10-14-short.21contact-free fields plus10metadata columns.
Only Telegram and Google Forms enter the current combined answers.

- The main Google Form writes native22-column rows to Ответы на форму (2). The former Ответы на форму (1) is preserved as a hidden archive.
- Google, Telegram and Все ответы have identical31-column headers. Вопросы maps codes and labels. Сводка counts only the two active sources and completed eligible non-test answers.
- A hidden archive retains the two older Telegram test rows. Old known-version SQLite states stay untouched but do not enter this study; unknown versions fail closed.
- Contacts remain in the separate existing private workbook and separate contacts.sqlite. Google contact raw tab stays Ответы на форму (1). Google contacts have no automatic link to main responses; Telegram uses a disclosed pseudonymous participant code.
- Fillout is excluded from reads/writes and the empty old tab is hidden.

sync.py creates read-only snapshots; normalize.py matches unique exact short native headers, parses commas in checkbox labels and clears hidden branches. Optional Other detail shares each question's note. sheets_api.py restricts requests to the existing two IDs and writes typed literal values. direct_sync.py reconciles complete snapshots, preserves interview status/time/notes, and updates each file atomically. Cross-file failure retries on the next run. A separate systemd timer runs60seconds after completion, without slowing Telegram.

No Forms/Sheets responses are fabricated for live checks. Synthetic tests cover snapshot corruption/locks, replay/update/delete, versions, consent, hidden answers, checkbox ambiguities, contact-note preservation, schema failure before writes and formula-safe strings. Main Google raw is currently empty; the displayed old test rows were archived.

Credentials are privately configured through GOOGLE_APPLICATION_CREDENTIALS, WHOOF_ANSWERS_ID and WHOOF_CONTACTS_ID. Existing service account has no project roles and Editor access only to the two private workbooks. Never put its key or bot token in Git/logs. The inactive receiver.js/receiver.gs drafts are not used.

prepare-short-workbook.py is a one-time recoverable schema switch: validates the new native destination, archives old Telegram rows, updates derived headers/dictionary/summary and hides inactive raw/channel tabs. It never writes native response rows.
