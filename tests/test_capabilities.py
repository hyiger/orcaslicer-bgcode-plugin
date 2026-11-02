"""The two capabilities: what each destination gets, and the on/off switch."""
import re
import tomllib
from pathlib import Path

import pytest

import bgcode_reader as reader
from conftest import ROOT, Step

PLUGIN_SOURCE = ROOT / "orca_bgcode_plugin_any.py"


def is_binary(path):
    return Path(path).read_bytes()[:4] == b"GCDE"


@pytest.fixture
def export(plugin):
    return plugin.PrusaBinaryGCodeExport()


@pytest.fixture
def toggle(plugin):
    return plugin.TogglePrusaBinaryGCode()


@pytest.mark.parametrize("host", ["File", "PrusaLink", "PrusaConnect"])
def test_each_destination_receives_binary_gcode(orca, export, gcode_file, context, host):
    result = export.execute(context(gcode_file, host=host))
    assert result.status == orca.PluginResult.Success
    assert host in result.message
    reader.parse_file(gcode_file)


def test_a_full_path_output_name_counts(orca, export, gcode_file, context):
    result = export.execute(context(gcode_file, output_name="/Volumes/USB/print.BGCODE"))
    assert result.status == orca.PluginResult.Success
    assert is_binary(gcode_file)


def test_the_short_binary_extension_counts(orca, export, gcode_file, context):
    assert export.execute(context(gcode_file, output_name="print.bgc")).status == orca.PluginResult.Success
    assert is_binary(gcode_file)


@pytest.mark.parametrize("output_name", ["/out/print.gcode.3mf", "print.GCODE.3MF"])
def test_gcode_inside_a_3mf_stays_text(orca, export, gcode_file, context, output_name):
    original = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, output_name=output_name))
    assert result.status == orca.PluginResult.Skipped
    assert gcode_file.read_bytes() == original


@pytest.mark.parametrize("model", ["Prusa MK3S", "Bambu Lab X1 Carbon", None])
def test_printers_without_bgcode_support_are_refused_at_export(orca, export, gcode_file, context, model):
    original = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, printer_model=model))
    assert result.status == orca.PluginResult.RecoverableError
    assert "not supported" in result.message
    assert gcode_file.read_bytes() == original


def test_geometry_steps_do_nothing(orca, export, gcode_file, context):
    original = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, output_name="", step=Step.posSlice))
    assert result.status == orca.PluginResult.Success
    assert gcode_file.read_bytes() == original


def test_an_output_name_ending_in_gcode_fails_rather_than_mislabel_binary(orca, export, gcode_file, context):
    original = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, output_name="/a/long/path/print.gcode"))
    assert result.status == orca.PluginResult.RecoverableError
    assert '"print.gcode"' in result.message  # the name, not the path, which can be very long
    assert "Toggle Prusa Binary G-code" in result.message
    assert gcode_file.read_bytes() == original


def test_already_binary_gcode_is_left_alone(orca, export, gcode_file, context):
    export.execute(context(gcode_file))
    converted = gcode_file.read_bytes()
    result = export.execute(context(gcode_file))
    assert result.status == orca.PluginResult.Skipped
    assert gcode_file.read_bytes() == converted


def test_a_conversion_error_reaches_the_host(plugin, export, gcode_file, context, monkeypatch):
    def fail(_):
        raise OSError("disk full")

    monkeypatch.setattr(plugin, "convert_in_place", fail)
    with pytest.raises(OSError, match="disk full"):  # the host reports it as a failed export
        export.execute(context(gcode_file))


def test_turning_on_selects_the_plugin_and_names_the_output_bgcode(orca, toggle):
    result = toggle.execute()
    values = orca.host.process.values
    assert result.status == orca.PluginResult.Success
    assert values["slicing_pipeline_plugin"] == '"Prusa Binary G-code Export"'
    assert values["filename_format"] == "{input_filename_base}_{print_time}.bgcode"


def test_turning_off_restores_the_preset(orca, toggle):
    before = dict(orca.host.process.values)
    toggle.execute()
    toggle.execute()
    assert orca.host.process.values == before


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('"Other Plugin";Plain', '"Other Plugin";Plain;"Prusa Binary G-code Export"'),
        ('"Say \\"hi\\""', '"Say \\"hi\\"";"Prusa Binary G-code Export"'),
        ('"C:\\\\x"', '"C:\\\\x";"Prusa Binary G-code Export"'),
        ('"two\\nlines"', '"two\\nlines";"Prusa Binary G-code Export"'),
    ],
)
def test_other_selected_plugins_are_kept_exactly(orca, toggle, before, after):
    orca.host.process.values["slicing_pipeline_plugin"] = before
    toggle.execute()
    assert orca.host.process.values["slicing_pipeline_plugin"] == after
    toggle.execute()
    assert orca.host.process.values["slicing_pipeline_plugin"] == before


def test_an_unset_plugin_list_is_handled(orca, toggle):
    del orca.host.process.values["slicing_pipeline_plugin"]
    toggle.execute()
    assert orca.host.process.values["slicing_pipeline_plugin"] == '"Prusa Binary G-code Export"'


def test_a_stored_empty_entry_is_not_carried_over(orca, toggle):
    orca.host.process.values["slicing_pipeline_plugin"] = '""'
    toggle.execute()
    assert orca.host.process.values["slicing_pipeline_plugin"] == '"Prusa Binary G-code Export"'


@pytest.mark.parametrize(
    ("filename_format", "turned_on", "turned_off"),
    [
        ("{a}.gcode", "{a}.bgcode", "{a}.gcode"),
        ("{a}.GCODE", "{a}.bgcode", "{a}.gcode"),
        ("{a}", "{a}.bgcode", "{a}.gcode"),
        ("{a}.bgcode", "{a}.bgcode", "{a}.gcode"),
        ("{a}.bgc", "{a}.bgcode", "{a}.gcode"),
        ("{a}.gco", "{a}.bgcode", "{a}.gcode"),
        ("{a}.gc", "{a}.bgcode", "{a}.gcode"),
        ("{a}.g", "{a}.bgcode", "{a}.gcode"),
        ("{a}.gcode.txt", "{a}.gcode.txt.bgcode", "{a}.gcode.txt.gcode"),
        ("", "{input_filename_base}.bgcode", "{input_filename_base}.gcode"),
        (None, "{input_filename_base}.bgcode", "{input_filename_base}.gcode"),
        (".gcode", "{input_filename_base}.bgcode", "{input_filename_base}.gcode"),
    ],
)
def test_filename_format_extension(orca, toggle, filename_format, turned_on, turned_off):
    orca.host.process.values["filename_format"] = filename_format
    toggle.execute()
    assert orca.host.process.values["filename_format"] == turned_on
    toggle.execute()
    assert orca.host.process.values["filename_format"] == turned_off


@pytest.mark.parametrize("model", ["Prusa MK3S", "Prusa MK3S MMU3", "Bambu Lab X1 Carbon", "", None])
def test_printers_without_bgcode_support_are_refused(orca, toggle, model):
    orca.host.printer_model = model
    before = dict(orca.host.process.values)
    result = toggle.execute()
    assert result.status == orca.PluginResult.Skipped
    assert orca.host.process.values == before
    (level, text), = orca.host.notifications
    assert level == orca.host.ui.NotificationLevel.WarningNotificationLevel
    assert "not supported" in text


@pytest.mark.parametrize(
    "model",
    ["Prusa CORE One", "Prusa CORE One L", "Prusa MK4S", "Prusa MK4", "Prusa MK3.5", "Prusa MINI", "Prusa XL"],
)
def test_buddy_printers_can_turn_it_on(orca, toggle, model):
    orca.host.printer_model = model
    assert toggle.execute().status == orca.PluginResult.Success


def test_it_can_always_be_turned_off(orca, toggle):
    toggle.execute()
    orca.host.printer_model = "Prusa MK3S"  # e.g. the printer was changed after turning it on
    assert toggle.execute().status == orca.PluginResult.Success
    assert orca.host.process.values["slicing_pipeline_plugin"] == ""


def test_the_user_is_told_the_state_and_to_save(orca, toggle):
    toggle.execute()
    toggle.execute()
    (first_level, first), (_, second) = orca.host.notifications
    assert first_level == orca.host.ui.NotificationLevel.RegularNotificationLevel
    assert "is on" in first and "0.20mm Standard" in first and "Save the preset" in first
    assert "is off" in second


def test_a_failed_commit_reaches_the_host_without_a_success_notice(orca, toggle):
    before = dict(orca.host.process.values)
    orca.host.commit_error = RuntimeError("the preset changed")
    with pytest.raises(RuntimeError, match="the preset changed"):
        toggle.execute()
    assert orca.host.process.values == before
    assert orca.host.notifications == []


def test_both_capabilities_are_registered(orca, plugin):
    plugin.PrusaBinaryGCodePackage().register_capabilities()
    assert orca.registered == [plugin.PrusaBinaryGCodeExport, plugin.TogglePrusaBinaryGCode]


def test_capability_names_are_the_ones_the_preset_stores(export, toggle):
    assert export.get_name() == "Prusa Binary G-code Export"
    assert toggle.get_name() == "Toggle Prusa Binary G-code"


def manifest():
    """The PEP 723 block OrcaSlicer's loader reads."""
    source = PLUGIN_SOURCE.read_text(encoding="utf-8")
    block = re.search(r"^# /// script\n(.*?)^# ///$", source, re.MULTILINE | re.DOTALL)[1]
    return tomllib.loads("".join(line[2:] + "\n" for line in block.splitlines()))


def test_dependencies_are_pinned_and_include_the_fast_encoder():
    assert manifest()["dependencies"] == ["gcode-lib==1.8.0", "heatshrink2==0.15.0"]


def test_manifest_identifies_the_plugin():
    plugin_table = manifest()["tool"]["orcaslicer"]["plugin"]
    assert plugin_table["type"] == "slicing-pipeline"
    assert plugin_table["name"] and plugin_table["description"] and plugin_table["author"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", plugin_table["version"])


def test_manifest_targets_the_bundled_python():
    assert manifest()["requires-python"] == ">=3.12"
