#!/usr/bin/env python3

"""Pure helpers for dynamic jetracer discovery and parking allocation."""

from collections.abc import Iterable
import threading
import time


def robot_name_from_tf_key(key_expr: object, namespace_prefix: str) -> str | None:
    """Extract a one-segment robot namespace from a ``<name>/tf`` key."""
    chunks = str(key_expr).strip('/').split('/')
    if len(chunks) != 2 or chunks[1] != 'tf':
        return None

    robot_name = chunks[0]
    if not robot_name.startswith(namespace_prefix):
        return None
    if robot_name == namespace_prefix:
        return None
    return robot_name


class ParkingAllocator:
    """Reserve one configured parking waypoint per admitted robot."""

    def __init__(
        self,
        parking_spots: Iterable[str],
        assignments: dict[str, str] | None = None
    ):
        self._spots = tuple(parking_spots)
        if not self._spots:
            raise ValueError('At least one parking spot must be configured')
        if len(set(self._spots)) != len(self._spots):
            raise ValueError('Parking spots must be unique')

        self._assignments = dict(assignments or {})
        unknown = set(self._assignments.values()) - set(self._spots)
        if unknown:
            raise ValueError(
                f'Existing assignments use unknown parking spots: {unknown}'
            )
        if len(set(self._assignments.values())) != len(self._assignments):
            raise ValueError('A parking spot is assigned to more than one robot')
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return len(self._spots)

    def assignment(self, robot_name: str) -> str | None:
        with self._lock:
            return self._assignments.get(robot_name)

    def reserve(self, robot_name: str) -> str | None:
        with self._lock:
            existing = self._assignments.get(robot_name)
            if existing is not None:
                return existing

            occupied = set(self._assignments.values())
            for spot in self._spots:
                if spot not in occupied:
                    self._assignments[robot_name] = spot
                    return spot
            return None

    def release(self, robot_name: str) -> None:
        with self._lock:
            self._assignments.pop(robot_name, None)

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return dict(self._assignments)


class DiscoveryGate:
    """Deduplicate discovery events and apply retry backoff after failures."""

    def __init__(self, retry_interval_sec: float):
        if retry_interval_sec < 0:
            raise ValueError('retry_interval_sec cannot be negative')
        self._retry_interval_sec = retry_interval_sec
        self._pending = set()
        self._active = set()
        self._retry_after = {}
        self._lock = threading.Lock()

    def offer(self, robot_name: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            if robot_name in self._active or robot_name in self._pending:
                return False
            if now < self._retry_after.get(robot_name, 0.0):
                return False
            self._pending.add(robot_name)
            return True

    def admitted(self, robot_name: str) -> None:
        with self._lock:
            self._pending.discard(robot_name)
            self._retry_after.pop(robot_name, None)
            self._active.add(robot_name)

    def failed(self, robot_name: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._pending.discard(robot_name)
            self._retry_after[robot_name] = now + self._retry_interval_sec
