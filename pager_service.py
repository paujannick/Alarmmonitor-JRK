"""Background queue for Retekess TD175P pager transmissions."""

from __future__ import annotations

import atexit
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from typing import Callable, Optional


MIN_PAGER = 1
MAX_PAGER = 30


def pager_bcd(pager: int) -> int:
    if not MIN_PAGER <= pager <= MAX_PAGER:
        raise ValueError("Pagernummer muss zwischen 1 und 30 liegen.")
    return ((pager // 10) << 4) | (pager % 10)


def pager_payload(pager: int) -> bytes:
    return bytes([pager_bcd(pager), 0x00, 0x92, 0x02])


@dataclass(frozen=True)
class PagerConfig:
    enabled: bool = True
    gpio: int = 24
    spi_bus: int = 0
    spi_device: int = 0
    power: int = 0xC0
    repeats: int = 30
    inverted: bool = True
    timeout_seconds: float = 5.0
    sender_script: Path = Path("td175p_send.py")

    @classmethod
    def from_settings(cls, settings: dict) -> "PagerConfig":
        raw = settings.get("pager") or {}
        if not isinstance(raw, dict):
            raw = {}
        return cls(
            enabled=_as_bool(raw.get("enabled"), cls.enabled),
            gpio=_as_int(raw.get("gpio"), cls.gpio),
            spi_bus=_as_int(raw.get("spi_bus"), cls.spi_bus),
            spi_device=_as_int(raw.get("spi_device"), cls.spi_device),
            power=_as_int(raw.get("power"), cls.power),
            repeats=_as_int(raw.get("repeats"), cls.repeats),
            inverted=_as_bool(raw.get("inverted"), cls.inverted),
            timeout_seconds=float(_as_int(raw.get("timeout_seconds"), int(cls.timeout_seconds))),
            sender_script=Path(str(raw.get("sender_script") or cls.sender_script)),
        )


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    return default


def _as_int(value: object, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 0)
        except ValueError:
            return default
    return default


Sender = Callable[[int, PagerConfig], None]


class PagerService:
    def __init__(self, config: PagerConfig, logger: logging.Logger, sender: Optional[Sender] = None):
        self.config = config
        self.logger = logger
        self.sender = sender or self._send_subprocess
        self._queue: Queue[tuple[int, str | None] | None] = Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="pager-worker", daemon=True)
        self._thread.start()
        atexit.register(self.stop)
        if not self.config.enabled:
            self.logger.info("Pagerfunktion ist deaktiviert; Pageraufträge werden nur protokolliert.")

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=2)

    def enqueue(self, pager: int | None, unit: str | None = None) -> bool:
        if pager is None:
            self.logger.info("Kein Pager für %s hinterlegt; überspringe Pageralarm.", unit or "unbekannte Einheit")
            return False
        try:
            pager = pager_bcd(int(pager))
        except (TypeError, ValueError) as exc:
            self.logger.error("Ungültige Pagernummer für %s: %s", unit or "unbekannte Einheit", exc)
            return False
        # Store the decimal pager number, not the encoded BCD byte, for sender compatibility.
        decoded_pager = ((pager >> 4) * 10) + (pager & 0x0F)
        if not self.config.enabled:
            self.logger.info("Pagerfunktion ist deaktiviert; Auftrag für %s/%s nicht gesendet.", unit or "unbekannte Einheit", decoded_pager)
            return False
        self._queue.put((decoded_pager, unit))
        self.logger.info("Pagerauftrag für %s/%s eingereiht.", unit or "unbekannte Einheit", decoded_pager)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.get(timeout=0.2)
            except Empty:
                continue
            try:
                if job is None:
                    return
                pager, unit = job
                self.logger.info("Sende Pageralarm an %s/%s.", unit or "unbekannte Einheit", pager)
                self.sender(pager, self.config)
            except Exception as exc:  # noqa: BLE001 - worker must survive transmission failures
                self.logger.error("Pageralarm fehlgeschlagen: %s", exc)
            finally:
                self._queue.task_done()

    def _send_subprocess(self, pager: int, config: PagerConfig) -> None:
        script = config.sender_script
        if not script.exists():
            raise FileNotFoundError(f"{script} nicht gefunden")
        cmd = [
            sys.executable,
            str(script),
            str(pager),
            "--gpio",
            str(config.gpio),
            "--power",
            f"0x{config.power:02X}",
            "--repeats",
            str(config.repeats),
            "--yes",
        ]
        if not config.inverted:
            cmd.append("--no-invert")
        subprocess.run(cmd, check=True, timeout=config.timeout_seconds, capture_output=True, text=True)
