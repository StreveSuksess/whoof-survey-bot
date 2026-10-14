# Whoof short survey

Active source: approved 17-question quantitative section in the existing collaborative Google Doc. Runtime version: whoof-quant-2026-10-14-short.
Two active channels: Telegram @whoofserveybot and existing Google Forms. Fillout is excluded.

## Flow
Screening plus10common questions; up to five questions about a recent case; optional contact after consent. Unknown frequency, no case, old or skipped date go directly to everyday questions. All answers are optional; a skipped screening ends the survey. Other text uses an optional explanation and adds no required step.5–7minutes is an unmeasured pilot target.

Google uses16main questions+fiveoptional explanations in six sections and a separate contact form. The new native raw destination is Ответы на форму (2) in the existing answer workbook. The original raw sheet and old Telegram test rows are retained. Exact labels/codes match both channels; Google checkbox exclusives are explained in the prompt and flagged during normalization.

## Code
instrument.json is the active runtime source. short-v2/instrument.json and short-v2/build.py hold its research source; build_instrument.py copies the approved short JSON after checks. Former long instrument/generator/tests live in source/long-v1 and are inactive. Existing older Google/Fillout export builders describe the historical long study and must not be used to update the active form.

engine.py routes and validates; presentation.py provides readable short button labels with expandable exact wording; bot.py implements polling/progress/back/skip/notes/version guard. storage.py separates progress from consented contacts. results/ handles read-only snapshots and two-workbook synchronization.

Old test sessions are preserved until their owner sends /delete, then /start. They are never migrated or included as current responses. The bot avatar and existing URLs remain unchanged.

## Checks and deployment
python3 -m unittest discover -s survey-kit -p test_survey.py -q
python3 -m unittest discover -s survey-kit/results -p 'test_*.py' -q

The minimal GitHub runtime is deployed through ordinary Play2Go VNC. deploy/install-short.sh validates the live new schema, creates a private runtime/SQLite backup, installs only runtime files, and restarts the existing bot and independent Sheets timer. Credentials stay outside Git and are unchanged.
