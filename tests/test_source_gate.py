import unittest
from unittest import mock

from app.runtime import source_gate
from app.runtime.source_gate import select_enabled


def _entry(name):
    return {"name": name, "spider": name, "title": name}


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _sql, _params=None):
        pass

    def fetchall(self):
        return self.rows


class _FakeConnection:
    def __init__(self, rows):
        self.rows = rows

    def cursor(self):
        return _FakeCursor(self.rows)

    def close(self):
        pass


def _factory(rows):
    def connect(**_kwargs):
        return _FakeConnection(rows)

    return connect


class SourceGateTests(unittest.TestCase):
    def _patch_flags(self, gate_on, allow_unknown=True):
        p1 = mock.patch.object(source_gate, "gate_enabled", return_value=gate_on)
        p2 = mock.patch.object(source_gate, "allow_unknown_sources", return_value=allow_unknown)
        return p1, p2

    def test_gate_off_runs_everything(self):
        entries = [_entry("a"), _entry("b")]
        with mock.patch.object(source_gate, "gate_enabled", return_value=False):
            enabled, disabled = select_enabled(entries, connection_factory=_factory([]))
        self.assertEqual(entries, enabled)
        self.assertEqual([], disabled)

    def test_disabled_source_is_filtered_out(self):
        entries = [_entry("a"), _entry("b"), _entry("c")]
        rows = [("a", True), ("b", False), ("c", True)]
        p1, p2 = self._patch_flags(True)
        with p1, p2:
            enabled, disabled = select_enabled(entries, connection_factory=_factory(rows))
        self.assertEqual([_entry("a"), _entry("c")], enabled)
        self.assertEqual([(_entry("b"), "disabled_in_pipesight")], disabled)

    def test_unknown_rows_default_to_allowed(self):
        entries = [_entry("a"), _entry("b")]
        rows = [("a", True)]
        p1, p2 = self._patch_flags(True, allow_unknown=True)
        with p1, p2:
            enabled, disabled = select_enabled(entries, connection_factory=_factory(rows))
        self.assertEqual(entries, enabled)
        self.assertEqual([], disabled)

    def test_unknown_rows_can_be_denied(self):
        entries = [_entry("a"), _entry("b")]
        rows = [("a", True)]
        p1, p2 = self._patch_flags(True, allow_unknown=False)
        with p1, p2:
            enabled, disabled = select_enabled(entries, connection_factory=_factory(rows))
        self.assertEqual([_entry("a")], enabled)
        self.assertEqual([(_entry("b"), "not_in_pipesight")], disabled)

    def test_database_error_falls_back_to_running_all(self):
        entries = [_entry("a")]

        def connect(**_kwargs):
            raise RuntimeError("connection refused")

        p1, p2 = self._patch_flags(True)
        with p1, p2:
            enabled, disabled = select_enabled(entries, connection_factory=connect)
        self.assertEqual(entries, enabled)
        self.assertEqual([], disabled)


if __name__ == "__main__":
    unittest.main()
