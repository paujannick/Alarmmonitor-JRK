"""Pager integration for linking incidents to TD175P alerting hardware."""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from td175p_radio import (
    TD175PConfig,
    TD175PSender,
    TD175PTiming,
    payload_for,
    validate_pager_command,
)


def pager_bcd(pager: int) -> int:
    """Return the low BCD address byte for the supported vehicle pagers."""

    validate_pager_command(pager)
    if pager == 999:
        raise ValueError('Pagernummer muss zwischen 1 und 30 liegen.')
    return payload_for(pager)[0]


def pager_payload(pager: int) -> bytes:
    """Return the TD175P payload bytes for a pager command."""

    return payload_for(pager)


@dataclass(frozen=True, slots=True)
class PagerConfig:
    """Runtime configuration for the Leitstelle-to-pager bridge."""

    enabled: bool = True
    gpio: int = 24
    spi_bus: int = 0
    spi_device: int = 0
    power: int = 0x60
    repeats: int = 30
    inverted: bool = True
    sender_script: Path | None = None
    queue_size: int = 100

    @classmethod
    def from_settings(cls, settings: dict) -> 'PagerConfig':
        pager = settings.get('pager') if isinstance(settings, dict) else {}
        pager = pager or {}
        return cls(
            enabled=True,
            gpio=int(pager.get('gpio', 24)),
            spi_bus=int(pager.get('spi_bus', 0)),
            spi_device=int(pager.get('spi_device', 0)),
            power=int(pager.get('power', 0x60)),
            repeats=int(pager.get('repeats', 30)),
            inverted=bool(pager.get('inverted', True)),
        )

    def radio_config(self) -> TD175PConfig:
        return TD175PConfig(
            gpio=self.gpio,
            spi_bus=self.spi_bus,
            spi_device=self.spi_device,
            power=self.power,
        )

    def radio_timing(self) -> TD175PTiming:
        return TD175PTiming(repeats=self.repeats)


PagerSender = Callable[[int, PagerConfig], None]


class PagerService:
    """Background queue that decouples Flask requests from radio transmission."""

    _STOP = object()

    def __init__(
        self,
        config: PagerConfig | None = None,
        logger: logging.Logger | None = None,
        *,
        sender: PagerSender | None = None,
    ) -> None:
        self.config = config or PagerConfig()
        self.logger = logger or logging.getLogger(__name__)
        self._sender = sender or self._send_with_td175p_library
        self._queue: queue.Queue[tuple[int, str | None] | object] = queue.Queue(
            maxsize=self.config.queue_size
        )
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._radio_sender: TD175PSender | None = None

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker,
                name='pager-alarm-worker',
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            if not thread:
                self._close_radio_sender()
                return
            self._queue.put(self._STOP)
        thread.join(timeout=5)
        self._close_radio_sender()
        with self._lock:
            self._thread = None

    def enqueue(self, pager: int | str | None, unit: str | None = None) -> bool:
        """Queue a pager alarm. Returns False when no pager is assigned."""

        if pager in (None, ''):
            return False
        pager_number = int(pager)
        validate_pager_command(pager_number)
        if not self.config.enabled:
            self.logger.info('Pageralarm für %s unterdrückt: Pagerdienst deaktiviert', unit)
            return False
        self.start()
        try:
            self._queue.put_nowait((pager_number, unit))
        except queue.Full:
            self.logger.error('Pageralarm für %s konnte nicht eingereiht werden: Warteschlange voll', unit)
            return False
        self.logger.info('Pageralarm für %s auf Pager %s eingereiht', unit, pager_number)
        return True

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return
                pager, unit = item
                try:
                    self._sender(pager, self.config)
                    self.logger.info('Pageralarm für %s auf Pager %s gesendet', unit, pager)
                except Exception as exc:  # keep worker alive after hardware errors
                    self.logger.error('Pageralarm für %s auf Pager %s fehlgeschlagen: %s', unit, pager, exc)
            finally:
                self._queue.task_done()

    def _send_with_td175p_library(self, pager: int, config: PagerConfig) -> None:
        if self._radio_sender is None:
            self._radio_sender = TD175PSender(
                config=config.radio_config(),
                timing=config.radio_timing(),
            )
        self._radio_sender.send(pager)

    def _close_radio_sender(self) -> None:
        if self._radio_sender is not None:
            self._radio_sender.close()
            self._radio_sender = None

    def _send_subprocess(self, pager: int, config: PagerConfig) -> None:
        """Legacy sender hook retained for existing installations and tests."""

        script = config.sender_script or Path(__file__).with_name('td175p_radio.py')
        script = script if script.is_absolute() else Path(__file__).parent / script
        subprocess.run(
            [
                sys.executable,
                str(script),
                str(pager),
                '--gpio',
                str(config.gpio),
                '--spi-bus',
                str(config.spi_bus),
                '--spi-device',
                str(config.spi_device),
                '--power',
                f'0x{config.power:02x}',
                '--repeats',
                str(config.repeats),
                '--yes',
            ],
            check=True,
        )
