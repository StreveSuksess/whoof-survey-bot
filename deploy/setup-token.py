"""Write the server secret from an echo-free prompt, never a shell argument."""
import argparse
import getpass
import os
import re
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot import Telegram


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hex', action='store_true', help='Input lowercase token hex for a VNC keyboard')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Run as root.')
    target = Path('/etc/whoof-survey.env')
    if target.exists() or target.is_symlink():
        parser.error('Existing secret file preserved; inspect it before any update.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            value = getpass.getpass('Token hex (hidden): ' if args.hex else 'Bot token (hidden): ').strip()
        token = bytes.fromhex(value).decode('ascii') if args.hex else value
        if not re.fullmatch(r'\d{6,15}:[A-Za-z0-9_-]{20,}', token):
            raise ValueError('Invalid token format; nothing saved.')
        api = Telegram(token)
        identity = api.call('getMe')
        if identity.get('id') != 8836023714:
            raise ValueError('This token belongs to a different bot; nothing saved.')
        if api.call('getWebhookInfo').get('url'):
            raise ValueError('Existing webhook detected; nothing changed.')
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as secret:
            secret.write('TELEGRAM_BOT_TOKEN=' + token + '\nSURVEY_MODE=core\n')
            secret.flush()
            os.fsync(secret.fileno())
    except (UnicodeError, ValueError):
        parser.exit(1, 'Invalid input or bot identity/webhook mismatch; nothing saved.\n')
    except (getpass.GetPassWarning, EOFError, KeyboardInterrupt):
        parser.exit(1, '\nA working echo-free terminal is required; nothing saved.\n')
    except RuntimeError:
        parser.exit(1, 'Telegram verification failed; nothing saved.\n')
    except OSError:
        parser.exit(1, 'Cannot create the private secret file; inspect permissions.\n')
    print('Verified @whoofserveybot; private /etc/whoof-survey.env created.')


if __name__ == '__main__':
    main()
