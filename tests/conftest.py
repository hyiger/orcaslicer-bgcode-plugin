"""Stands in for the `orca` module, which only exists inside OrcaSlicer's embedded interpreter.

gcode-lib is the real package, so the tests catch a change in its behaviour.
"""
import base64
import enum
import importlib
import shutil
import struct
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "coreone_cube.gcode"  # sliced by the command line, which renders no thumbnails
FIXTURE_WITH_THUMBNAILS = FIXTURES / "coreone_cube_with_thumbnails.gcode"  # sliced in the GUI
sys.path.insert(0, str(ROOT))


class Step(enum.Enum):
    posSlice = 0
    psGCodePostProcess = 1


class PluginResult(enum.Enum):
    Success = 0
    Skipped = 1
    RecoverableError = 2
    FatalError = 3


class ExecutionResult:
    def __init__(self, status, message=""):
        self.status = status
        self.message = message

    @staticmethod
    def success(message="", data=""):
        return ExecutionResult(PluginResult.Success, message)

    @staticmethod
    def skipped(message=""):
        return ExecutionResult(PluginResult.Skipped, message)

    @staticmethod
    def failure(status, message, data=""):
        return ExecutionResult(status, message)


class NotificationLevel(enum.Enum):
    RegularNotificationLevel = 0
    WarningNotificationLevel = 1


class Transaction:
    """Applies its staged values on commit, as the host's PresetTransaction does."""

    def __init__(self, preset, commit_error=None):
        self.preset = preset
        self.staged = {}
        self.commit_error = commit_error

    def set(self, key, value):
        self.staged[key] = value

    def commit(self):
        if self.commit_error:
            raise self.commit_error
        self.preset.values.update(self.staged)
        return SimpleNamespace(target_name=self.preset.name)


class Preset:
    def __init__(self, name, values):
        self.name = name
        self.values = values

    def config_value(self, key):
        return self.values.get(key)


class Host:
    """The parts of orca.host the toggle uses, around one process preset."""

    def __init__(self):
        self.printer_model = "Prusa CORE One"
        self.process = Preset(
            "0.20mm Standard",
            {"filename_format": "{input_filename_base}_{print_time}.gcode", "slicing_pipeline_plugin": ""},
        )
        self.notifications = []
        self.commit_error = None
        self.ui = SimpleNamespace(NotificationLevel=NotificationLevel, push_notification=self._notify)
        self.preset = SimpleNamespace(
            process=SimpleNamespace(begin_update=lambda: Transaction(self.process, self.commit_error))
        )

    def _notify(self, level, text):
        self.notifications.append((level, text))

    def preset_bundle(self):
        return SimpleNamespace(
            prints=SimpleNamespace(edited_preset=lambda: self.process),
            full_config_value=lambda key: self.printer_model if key == "printer_model" else None,
        )


def _make_orca():
    orca = types.ModuleType("orca")
    orca.slicing = SimpleNamespace(Step=Step, SlicingPipelineCapabilityBase=object)
    orca.script = SimpleNamespace(ScriptPluginCapabilityBase=object)
    orca.ExecutionResult = ExecutionResult
    orca.PluginResult = PluginResult
    orca.base = object
    orca.plugin = lambda cls: cls
    orca.registered = []
    orca.register_capability = orca.registered.append
    orca.host = Host()
    return orca


@pytest.fixture
def orca(monkeypatch):
    fake = _make_orca()
    monkeypatch.setitem(sys.modules, "orca", fake)
    return fake


@pytest.fixture
def plugin(orca):
    sys.modules.pop("orca_bgcode_plugin_any", None)
    module = importlib.import_module("orca_bgcode_plugin_any")
    yield module
    sys.modules.pop("orca_bgcode_plugin_any", None)


@pytest.fixture
def gcode_file(tmp_path):
    """A copy of a file sliced by OrcaSlicer 2.5.0-rc for a Prusa CORE One, named as the host names it."""
    path = tmp_path / "plate_1.gcode.pp"
    shutil.copyfile(FIXTURE, path)
    return path


def thumbnail_comment(keyword, width, height, data):
    encoded = base64.b64encode(data).decode("ascii")
    lines = [f"; {keyword} begin {width}x{height} {len(encoded)}"]
    lines += [f"; {encoded[i:i + 78]}" for i in range(0, len(encoded), 78)]
    lines.append(f"; {keyword} end")
    return "\n".join(lines) + "\n"


# Bytes of each format's signature, enough for the block's format field to be checked.
PNG_DATA = b"\x89PNG\r\n\x1a\n" + bytes(range(32))
QOI_DATA = b"qoif" + struct.pack(">II", 16, 16) + bytes(range(32))


@pytest.fixture
def thumbnail_text():
    """The two formats Prusa's printer profiles request, as the G-code's header carries them."""
    return thumbnail_comment("thumbnail_QOI", 16, 16, QOI_DATA) + thumbnail_comment("thumbnail", 640, 480, PNG_DATA)


def make_context(
    orca, gcode_path, output_name="print.bgcode", host="File", step=Step.psGCodePostProcess, printer_model="Prusa CORE One"
):
    config = {"printer_model": printer_model}
    return SimpleNamespace(
        step=step, gcode_path=str(gcode_path), output_name=output_name, host=host, config_value=config.get
    )


@pytest.fixture
def context(orca):
    return lambda *args, **kwargs: make_context(orca, *args, **kwargs)
