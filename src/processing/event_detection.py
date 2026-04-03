from __future__ import annotations

import enum
import json
import logging
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias

import numpy as np
import pandas as pd

from .buffers import FIFO
from ..constants import SAMPLE_RATE

### problems: detection of event will only happen after enough data has entered the buffer.
### this is not necessarily an issue but can cause slight delay.

# classes to detect errors with EEG signals in real time. Is not 100% accurate to the time of when events occur

# ── Event type enum ───────────────────────────────────────────────────────────

class EventType(enum.Flag):
    REGULAR  = 0            # no flags set — plain detection (identity for |)
    DEBUG    = enum.auto()
    WARNING  = enum.auto()
    ERROR    = enum.auto()
    DURATION = enum.auto()  # set automatically by DurationEventDetector


# ── Type aliases ──────────────────────────────────────────────────────────────

# Return types for single-channel EventDetector.check()
SingleResult: TypeAlias = float | None                    # timestamp or None
DurationSingleResult: TypeAlias = tuple[float, bool] | None  # (timestamp, is_on) or None
AnySingleResult: TypeAlias = float | tuple[float, bool] | None


# ── Custom exception ──────────────────────────────────────────────────────────

class CriticalEventError(RuntimeError):
    """Raised by ErrorMixin when a critical event is detected."""


# ── Log entry dataclasses ─────────────────────────────────────────────────────

@dataclass
class EventLogEntry:
    timestamp: float
    detector_name: str
    channel_mask: np.ndarray       # shape (n_channels,), dtype bool
    event_type: EventType = EventType.REGULAR
    is_on: bool | None = None      # None for non-duration detectors


@dataclass
class DurationSummary:
    detector_name: str
    onset_timestamp: float
    offset_timestamp: float
    duration: float
    onset_mask: np.ndarray
    offset_mask: np.ndarray


# ── Base EventDetector ────────────────────────────────────────────────────────

class EventDetector(ABC):
    """
    Single-channel event detector.

    Each instance is responsible for exactly one EEG channel.
    DetectorGroup creates and manages one instance per channel.

    check() receives the full buffer and the channel index it is
    responsible for, returning the event timestamp on detection or None.
    _event_type is reset by DetectorGroup before each call and may be
    set by mixins during the call.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[call-arg]
        self._event_type: EventType = EventType.REGULAR

    def extra_message(self, timestamp: float, channel: int) -> str:
        """
        Optional extra context appended to mixin log/warning messages.

        Override in concrete detectors to add detector-specific detail.
        Return an empty string (default) to add nothing.
        """
        return ""

    @abstractmethod
    def check(self, buffer: FIFO, channel: int) -> SingleResult:
        """
        Inspect *buffer* at *channel* and return the event timestamp on
        detection, or None if the event has not occurred.
        """
        ...


# ── Duration detector ─────────────────────────────────────────────────────────

class DurationEventDetector(EventDetector, ABC):
    """
    Single-channel detector that tracks onset/offset pairs.

    Alternates between check_onset (when is_on=False) and check_offset
    (when is_on=True). Returns (timestamp, is_on) so the manager can
    distinguish onset from offset events in the log.

    After each completed offset, _last_duration holds the elapsed seconds.
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.is_on: bool = False
        self._onset_timestamp: float | None = None
        self._last_duration: float | None = None

    @abstractmethod
    def check_onset(self, buffer: FIFO, channel: int) -> SingleResult:
        """Return timestamp when the event begins on *channel*, else None."""
        ...

    @abstractmethod
    def check_offset(self, buffer: FIFO, channel: int) -> SingleResult:
        """Return timestamp when the event ends on *channel*, else None."""
        ...

    def check(self, buffer: FIFO, channel: int) -> DurationSingleResult:
        if not self.is_on:
            ts: SingleResult = self.check_onset(buffer, channel)
            if ts is not None:
                self.is_on = True
                self._onset_timestamp = ts
                self._last_duration = None
                self._event_type |= EventType.DURATION
                return (ts, True)
        else:
            ts = self.check_offset(buffer, channel)
            if ts is not None:
                self.is_on = False
                if self._onset_timestamp is not None:
                    self._last_duration = ts - self._onset_timestamp
                self._onset_timestamp = None
                self._event_type |= EventType.DURATION
                return (ts, False)
        return None

    def get_current_duration(self, current_timestamp: float) -> float | None:
        """Return seconds elapsed since onset if currently on, else None."""
        if self.is_on and self._onset_timestamp is not None:
            return current_timestamp - self._onset_timestamp
        return None


# ── Counter mixin ─────────────────────────────────────────────────────────────

class CounterMixin:
    """
    Adds a detection counter to a single-channel EventDetector.

    When the count reaches count_threshold, on_threshold() is called once.
    Re-armed by reset_counter().

    Parameters
    ----------
    count_threshold:
        Number of detections needed to trigger on_threshold().

    Usage
    -----
    class MyDetector(CounterMixin, EventDetector):
        def __init__(self):
            super().__init__(count_threshold=10)
    """

    def __init__(self, *, count_threshold: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.count_threshold: int = count_threshold
        self._count: int = 0
        self._threshold_fired: bool = False

    def check(self, buffer: FIFO, channel: int) -> AnySingleResult:
        result: AnySingleResult = super().check(buffer, channel)  # type: ignore[misc]
        if result is not None:
            self._count += 1
            if not self._threshold_fired and self._count >= self.count_threshold:
                self._threshold_fired = True
                self.on_threshold()
        return result

    def on_threshold(self) -> None:
        """Called once when count reaches count_threshold. Override to customise."""

    def reset_counter(self) -> None:
        """Reset count and re-arm threshold firing."""
        self._count = 0
        self._threshold_fired = False

    @property
    def count(self) -> int:
        return self._count


# ── Logging mixins ────────────────────────────────────────────────────────────

_logger = logging.getLogger(__name__)


class DebugMixin:
    """
    Automatically emits a debug log on every detected event and tags
    the entry as EventType.DEBUG.

    Also provides log_debug() for manual debug messages.
    """

    def check(self, buffer: FIFO, channel: int) -> AnySingleResult:
        result: AnySingleResult = super().check(buffer, channel)  # type: ignore[misc]
        if result is not None:
            ts: float = result[0] if isinstance(result, tuple) else result  # type: ignore[assignment]
            extra: str = getattr(self, "extra_message", lambda *_: "")(ts, channel)
            msg = f"[{type(self).__name__} ch{channel}] Event at t={ts:.4f}s"
            if extra:
                msg += f" | {extra}"
            _logger.debug(msg)
            self._event_type |= EventType.DEBUG  # type: ignore[attr-defined]
        return result

    def log_debug(self, msg: str) -> None:
        _logger.debug("[%s] %s", type(self).__name__, msg)


class WarningMixin:
    """
    Automatically emits a warnings.warn on every detected event, including
    timestamp, channel, and duration if available.
    """

    def check(self, buffer: FIFO, channel: int) -> AnySingleResult:
        result: AnySingleResult = super().check(buffer, channel)  # type: ignore[misc]
        if result is not None:
            ts: float = result[0] if isinstance(result, tuple) else result  # type: ignore[assignment]
            last_duration: float | None = getattr(self, "_last_duration", None)
            extra: str = getattr(self, "extra_message", lambda *_: "")(ts, channel)
            msg = f"[{type(self).__name__} ch{channel}] Event detected at t={ts:.4f}s"
            if last_duration is not None:
                msg += f", duration={last_duration:.4f}s"
            if extra:
                msg += f" | {extra}"
            warnings.warn(msg, stacklevel=2)
            self._event_type |= EventType.WARNING  # type: ignore[attr-defined]
        return result


class ErrorMixin:
    """
    Raises CriticalEventError (and logs at ERROR level) when an event is
    detected. Stops the program unless the caller catches the exception.
    """

    def check(self, buffer: FIFO, channel: int) -> AnySingleResult:
        result: AnySingleResult = super().check(buffer, channel)  # type: ignore[misc]
        if result is not None:
            ts: float = result[0] if isinstance(result, tuple) else result  # type: ignore[assignment]
            last_duration: float | None = getattr(self, "_last_duration", None)
            extra: str = getattr(self, "extra_message", lambda *_: "")(ts, channel)
            msg = f"[{type(self).__name__} ch{channel}] CRITICAL EVENT at t={ts:.4f}s"
            if last_duration is not None:
                msg += f", duration={last_duration:.4f}s"
            if extra:
                msg += f" | {extra}"
            self._event_type |= EventType.ERROR  # type: ignore[attr-defined]
            _logger.error(msg)
            raise CriticalEventError(msg)
        return result


# ── DetectorGroup ─────────────────────────────────────────────────────────────

class DetectorGroup:
    """
    Factory and coordinator for one event phenomenon across N channels.

    Instantiates one EventDetector per assigned channel, calls each per
    timestep, aggregates results into a single EventLogEntry with a
    channel mask, and owns the combined EventType for that step.

    Parameters
    ----------
    cls:
        EventDetector subclass to instantiate (the factory target).
    name:
        Unique identifier for this phenomenon.
    channels:
        Channel indices this group monitors.
    n_total_channels:
        Total number of EEG channels (sets the width of channel_mask).
    **init_kwargs:
        Forwarded to each EventDetector instance's __init__.
    """

    def __init__(
        self,
        cls: type[EventDetector],
        name: str,
        channels: list[int],
        n_total_channels: int,
        **init_kwargs: object,
    ) -> None:
        self.name: str = name
        self.n_total_channels: int = n_total_channels
        self._cls: type[EventDetector] = cls
        self._init_kwargs: dict[str, object] = init_kwargs
        self._instances: dict[int, EventDetector] = {
            ch: cls(**init_kwargs) for ch in channels
        }
        self._event_type: EventType = EventType.REGULAR

    # ── Channel management ────────────────────────────────────────────────────

    @property
    def channels(self) -> list[int]:
        return list(self._instances.keys())

    def get_instance(self, channel: int) -> EventDetector:
        if channel not in self._instances:
            raise KeyError(f"Channel {channel} not registered in group '{self.name}'.")
        return self._instances[channel]

    def add_channel(self, channel: int) -> None:
        """Add a new channel, creating a fresh detector instance for it."""
        if channel in self._instances:
            raise ValueError(f"Channel {channel} already registered in group '{self.name}'.")
        self._instances[channel] = self._cls(**self._init_kwargs)

    def remove_channel(self, channel: int) -> None:
        if channel not in self._instances:
            raise KeyError(f"Channel {channel} not registered in group '{self.name}'.")
        del self._instances[channel]

    # ── Step ──────────────────────────────────────────────────────────────────

    def check(self, buffer: FIFO) -> EventLogEntry | None:
        """
        Run every channel instance against *buffer*.

        Returns a single EventLogEntry (with an aggregated channel mask and
        event_type) if any channel fired, else None.
        """
        channel_mask: np.ndarray = np.zeros(self.n_total_channels, dtype=bool)
        self._event_type = EventType.REGULAR
        timestamp: float | None = None
        is_on: bool | None = None

        for ch, instance in self._instances.items():
            instance._event_type = EventType.REGULAR
            result: AnySingleResult = instance.check(buffer, ch)
            if result is not None:
                ts: float
                if isinstance(result, tuple):
                    ts, inst_is_on = result
                    if is_on is None:
                        is_on = inst_is_on
                else:
                    ts = result  # type: ignore[assignment]
                channel_mask[ch] = True
                timestamp = ts
                self._event_type |= instance._event_type

        if timestamp is None:
            return None

        return EventLogEntry(
            timestamp=timestamp,
            detector_name=self.name,
            channel_mask=channel_mask,
            event_type=self._event_type,
            is_on=is_on,
        )


# ── EventDetectorManager ──────────────────────────────────────────────────────

class EventDetectorManager:
    """
    Top-level manager. Owns a set of DetectorGroups (one per phenomenon)
    and the full event log.

    Parameters
    ----------
    n_channels:
        Total number of EEG channels in the recording.
    """

    def __init__(self, n_channels: int) -> None:
        self.n_channels: int = n_channels
        self._groups: dict[str, DetectorGroup] = {}
        self.event_log: list[EventLogEntry] = []

    # ── Group management ──────────────────────────────────────────────────────

    @property
    def groups(self) -> list[DetectorGroup]:
        return list(self._groups.values())

    def add_detector(
        self,
        cls: type[EventDetector],
        name: str,
        channels: list[int],
        **init_kwargs: object,
    ) -> DetectorGroup:
        """
        Register a new detector phenomenon.

        Creates one EventDetector instance per channel via DetectorGroup.
        Returns the created group for direct inspection if needed.
        """
        if name in self._groups:
            raise ValueError(f"A detector named '{name}' is already registered.")
        group = DetectorGroup(cls, name, channels, self.n_channels, **init_kwargs)
        self._groups[name] = group
        return group

    def remove_detector(self, name: str) -> None:
        if name not in self._groups:
            raise KeyError(f"No detector named '{name}'.")
        del self._groups[name]

    def get_group(self, name: str) -> DetectorGroup:
        if name not in self._groups:
            raise KeyError(f"No detector named '{name}'.")
        return self._groups[name]

    # ── Step ──────────────────────────────────────────────────────────────────

    def check(self, name: str, buffer: FIFO) -> EventLogEntry | None:
        """Run a single detector group by name and return its log entry (or None)."""
        entry = self.get_group(name).check(buffer)
        if entry is not None:
            self.event_log.append(entry)
        return entry

    def check_all(self, buffer: FIFO) -> list[EventLogEntry]:
        """
        Run every detector group against *buffer*.

        Returns entries that fired this timestep. All detections are
        appended to event_log.
        """
        step_entries: list[EventLogEntry] = []
        for group in self._groups.values():
            entry = group.check(buffer)
            if entry is not None:
                self.event_log.append(entry)
                step_entries.append(entry)
        return step_entries

    # ── Duration analysis ─────────────────────────────────────────────────────

    def get_durations(self) -> list[DurationSummary]:
        """
        Scan the event log and return completed onset/offset pairs for
        every duration detector, in chronological order.
        """
        summaries: list[DurationSummary] = []
        by_detector: dict[str, list[EventLogEntry]] = {}
        for entry in self.event_log:
            if entry.is_on is None:
                continue
            by_detector.setdefault(entry.detector_name, []).append(entry)

        for det_name, entries in by_detector.items():
            pending_onset: EventLogEntry | None = None
            for entry in entries:
                if entry.is_on:
                    pending_onset = entry
                elif pending_onset is not None:
                    summaries.append(DurationSummary(
                        detector_name=det_name,
                        onset_timestamp=pending_onset.timestamp,
                        offset_timestamp=entry.timestamp,
                        duration=entry.timestamp - pending_onset.timestamp,
                        onset_mask=pending_onset.channel_mask,
                        offset_mask=entry.channel_mask,
                    ))
                    pending_onset = None
        return summaries

    # ── Export ────────────────────────────────────────────────────────────────

    def to_dataframe(self) -> pd.DataFrame:
        """Convert the full event log to a DataFrame for analysis or export."""
        if not self.event_log:
            return pd.DataFrame(
                columns=["timestamp", "detector_name", "channel_mask", "event_type", "is_on"]
            )
        return pd.DataFrame([
            {
                "timestamp": e.timestamp,
                "detector_name": e.detector_name,
                "channel_mask": e.channel_mask,
                "event_type": e.event_type,
                "is_on": e.is_on,
            }
            for e in self.event_log
        ])

    def to_json(self, path: str | Path) -> None:
        """Serialize the event log to a JSON file at *path*."""

        def _serialize(entry: EventLogEntry) -> dict[str, object]:
            return {
                "timestamp": entry.timestamp,
                "detector_name": entry.detector_name,
                "channel_mask": entry.channel_mask.tolist(),
                "event_type": entry.event_type.name,
                "is_on": entry.is_on,
            }

        with open(path, "w", encoding="utf-8") as f:
            json.dump([_serialize(e) for e in self.event_log], f, indent=2)


# ── Concrete detectors ────────────────────────────────────────────────────────

# helpers
# def is_flat(signal: np.array, diff_thresh: float = 1, activity_thresh: float = 0.5):
#     diff = np.diff(signal)
#     # quantize
#     quantized_diff = (np.abs(diff) > diff_thresh).astype(np.int8)
#     return np.mean(quantized_diff) < activity_thresh

def high_line_noise(signal: np.ndarray, line_noise: float, noise_thresh: float = 0.3) -> bool:
    """
    Return True if the relative power at *line_noise* Hz exceeds *noise_thresh*.

    Relative power = power at line_noise bin / total signal power,
    giving a 0–1 scale independent of signal amplitude.
    A threshold of 0.3 means line noise accounts for >30 % of total power.
    """
    freqs = np.fft.rfftfreq(len(signal), d=1.0 / SAMPLE_RATE)
    power = np.abs(np.fft.rfft(signal)) ** 2
    idx = int(np.argmin(np.abs(freqs - line_noise)))
    return bool(power[idx] / power.sum() > noise_thresh)


def is_flat(signal: np.ndarray, var_thresh: float = 0.1) -> bool:
    return np.var(signal) < var_thresh

class DisconnectionDetector(WarningMixin, DurationEventDetector):
    def __init__(self, var_thresh) -> None:
        super().__init__()
        # we will store threshold here
        self.var_thresh = var_thresh

    def check_onset(self, buffer: FIFO, channel: int) -> SingleResult:
        # if flat signal → disconnection started
        result = buffer.timestamp if is_flat(buffer[channel,], self.var_thresh) else None
        return SingleResult(result)

    def check_offset(self, buffer: FIFO, channel: int) -> SingleResult:
        # if signal is no longer flat → disconnection ended
        result = buffer.timestamp if not is_flat(buffer[channel,], self.var_thresh) else None
        return SingleResult(result)

class LineNoiseDetector(WarningMixin, DurationEventDetector):
    def __init__(self, line_noise, noise_thresh) -> None:
        super().__init__()
        self.line_noise = line_noise
        self.noise_thresh = noise_thresh

    def check_onset(self, buffer: FIFO, channel: int) -> SingleResult:
        # if flat signal → disconnection started
        result = buffer.timestamp if high_line_noise(buffer[channel,], self.line_noise, self.noise_thresh) else None
        return SingleResult(result)

    def check_offset(self, buffer: FIFO, channel: int) -> SingleResult:
        # if signal is no longer flat → disconnection ended
        result = buffer.timestamp if not high_line_noise(buffer[channel,], self.line_noise, self.noise_thresh) else None
        return SingleResult(result)


class IdenticalSignalDetector(WarningMixin, DurationEventDetector):
    def __init__(self) -> None:
        super().__init__()

    # some how need to check all channels that are far away from channel of interest have low correlation, may need to do this at the group level
    def check_onset(self, buffer: FIFO, channel: int) -> SingleResult:
        return None
    def check_offset(self, buffer: FIFO, channel: int) -> SingleResult:
        return None