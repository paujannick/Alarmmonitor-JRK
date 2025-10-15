#!/usr/bin/env python3
"""Launch the alarm monitor browser once per boot if enabled in settings."""

from __future__ import annotations

import json
import logging
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from shutil import which
from typing import Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / 'data'
SETTINGS_FILE = DATA_DIR / 'settings.json'
LOG_FILE = DATA_DIR / 'browser-launch.log'
DEFAULT_URL = 'http://localhost:5000/monitor?autoplay=1'
SENTINEL_FILE = Path(os.environ.get('ALARM_MONITOR_BROWSER_SENTINEL', '/tmp/alarmmonitor-browser-launched'))


def configure_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('alarmmonitor.browser')
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(LOG_FILE, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


def parse_bool(value, default=False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {'true', '1', 'yes', 'on'}:
            return True
        if lowered in {'false', '0', 'no', 'off'}:
            return False
    return default


def load_monitor_settings(logger: logging.Logger) -> dict:
    if SETTINGS_FILE.exists():
        try:
            with SETTINGS_FILE.open(encoding='utf-8') as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning('Konnte Einstellungen nicht lesen: %s', exc)
            data = {}
    else:
        data = {}
    monitor = {}
    if isinstance(data, dict):
        monitor = data.get('monitor') or {}
    if not isinstance(monitor, dict):
        monitor = {}
    return monitor


def should_launch(monitor_settings: dict) -> bool:
    return parse_bool(monitor_settings.get('auto_launch_browser'), False)


def detect_browser_command(url: str, logger: logging.Logger) -> Optional[list[str]]:
    command_template = os.environ.get('ALARM_MONITOR_BROWSER_COMMAND')
    if command_template:
        args = shlex.split(command_template)
        replaced = False
        command: list[str] = []
        for arg in args:
            if '{url}' in arg:
                command.append(arg.replace('{url}', url))
                replaced = True
            else:
                command.append(arg)
        if not replaced:
            command.append(url)
        logger.info('Verwende benutzerdefinierten Browser-Befehl: %s', command[0] if command else command_template)
        return command

    candidates: Iterable[tuple[str, list[str]]] = (
        ('chromium-browser', ['--kiosk', '--autoplay-policy=no-user-gesture-required', '--noerrdialogs', '--disable-session-crashed-bubble']),
        ('chromium', ['--kiosk', '--autoplay-policy=no-user-gesture-required', '--noerrdialogs', '--disable-session-crashed-bubble']),
        ('google-chrome', ['--kiosk', '--autoplay-policy=no-user-gesture-required']),
        ('chromium-browser', ['--start-fullscreen', '--autoplay-policy=no-user-gesture-required']),
        ('firefox', ['--kiosk']),
        ('firefox', ['--fullscreen']),
    )
    for binary, flags in candidates:
        path = which(binary)
        if path:
            logger.info('Nutze Browser "%s" mit Flags %s', path, ' '.join(flags) or '-')
            return [path, *flags, url]

    fallback = which('x-www-browser')
    if fallback:
        logger.info('Nutze Fallback-Browser %s', fallback)
        return [fallback, url]

    logger.error('Kein unterstützter Browser gefunden. Bitte Chromium oder Firefox installieren.')
    return None


def ensure_audio_enabled(logger: logging.Logger) -> None:
    mixer = which('amixer')
    if not mixer:
        logger.info('amixer nicht gefunden, überspringe Audio-Aktivierung.')
        return
    for control in ('Master', 'PCM'):
        subprocess.run([mixer, 'set', control, 'unmute'], check=False)
        subprocess.run([mixer, 'set', control, '90%'], check=False)
    logger.info('Audioausgabe aktiviert (Master/PCM ungemutet).')


def prepare_environment(logger: logging.Logger) -> dict:
    env = os.environ.copy()
    display = env.get('ALARM_MONITOR_DISPLAY') or env.get('DISPLAY')
    if not display:
        display = ':0'
        env['DISPLAY'] = display
    logger.info('Verwende DISPLAY=%s', display)
    if 'XDG_RUNTIME_DIR' not in env:
        runtime_dir = Path(f"/run/user/{os.getuid()}")
        if runtime_dir.exists():
            env['XDG_RUNTIME_DIR'] = str(runtime_dir)
            logger.info('Setze XDG_RUNTIME_DIR auf %s', runtime_dir)
    return env


def main() -> int:
    logger = configure_logging()

    if SENTINEL_FILE.exists():
        logger.info('Browser wurde bereits in diesem Startvorgang geöffnet. Beende.')
        return 0

    monitor_settings = load_monitor_settings(logger)
    if not should_launch(monitor_settings):
        logger.info('Automatischer Browserstart ist deaktiviert.')
        return 0

    try:
        delay_seconds = float(os.environ.get('ALARM_MONITOR_BROWSER_DELAY', '5'))
    except ValueError:
        delay_seconds = 5.0
    delay_seconds = max(0.0, delay_seconds)

    url = os.environ.get('ALARM_MONITOR_BROWSER_URL', DEFAULT_URL)
    command = detect_browser_command(url, logger)
    if not command:
        return 1

    if delay_seconds > 0:
        logger.info('Warte %.1f Sekunden bevor der Browser gestartet wird.', delay_seconds)
        time.sleep(delay_seconds)

    ensure_audio_enabled(logger)
    env = prepare_environment(logger)

    try:
        subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.error('Browser konnte nicht gestartet werden: %s', exc)
        return 1

    try:
        SENTINEL_FILE.write_text(str(time.time()), encoding='utf-8')
    except OSError as exc:
        logger.warning('Konnte Sentinel-Datei %s nicht schreiben: %s', SENTINEL_FILE, exc)
    else:
        logger.info('Sentinel-Datei %s geschrieben.', SENTINEL_FILE)

    logger.info('Browser erfolgreich gestartet: %s', ' '.join(command))
    return 0


if __name__ == '__main__':
    sys.exit(main())
