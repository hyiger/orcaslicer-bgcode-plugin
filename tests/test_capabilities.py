"""The two capabilities: what each destination gets, and the on/off switch."""
import re
import tomllib
from pathlib import Path

import pytest

import bgcode_reader as reader
from conftest import ROOT, Step

PLUGIN_SOURCE = ROOT / "orca_bgcode_plugin_any.py"


# Every Prusa printer_model OrcaSlicer 2.5.1 ships, apart from the MK3S.
ORCA_BUDDY_MODELS = [
    "Prusa CORE One",
    "Prusa CORE One HF",
    "Prusa CORE One INDX 4T",
    "Prusa CORE One INDX 8T",
    "Prusa CORE One L",
    "Prusa CORE One L HF",
    "Prusa CORE One MMU3",
    "Prusa MINI",
    "Prusa MINI IS",
    "Prusa MK3.5",
    "Prusa MK4",
    "Prusa MK4 MMU3",
    "Prusa MK4 MMU3 HF",
    "Prusa MK4S",
    "Prusa MK4S HF",
    "Prusa XL",
    "Prusa XL 5T",
]
# Custom Buddy printers. The Create Printer dialog names one "<vendor> <model>", for good.
CUSTOM_BUDDY_MODELS = [
    # Picked from the dialog's own lists, where six models already carry the vendor.
    "Prusa Prusa CORE One",
    "Prusa Prusa CORE One HF",
    "Prusa Prusa CORE One L",
    "Prusa Prusa CORE One L HF",
    "Prusa Prusa XL",
    "Prusa Prusa XL 5T",
    # Typed there, where the model field drops a ".".
    "Prusa MK39S",
    "Prusa MK39",
    "Prusa MK35S",
    "Prusa MK35",
    "Prusa MK39S MMU3",
    # Copied from PrusaSlicer or the firmware: PrusaSlicer's vendor, and model ids, which run together.
    "Prusa Research MK4S",
    "Prusa MK4SMMU3",
    "Prusa MK4ISMMU3",
    "Prusa MK3.9SMMU3",
    "Prusa MK3.5MMU3",
    "Prusa XL2",
    "Prusa XL5IS",
    "Prusa COREONEL",
    "Prusa COREONEMMU3",
    "Prusa COREONELMMU3",
    "Prusa COREONEOAK",
    "Prusa COREONEINDX",
    "Prusa XLP",
    # A hyphen before the variant.
    "Prusa MK4S-MMU3",
    # Prusa's full product name typed as the model, after the vendor.
    "Prusa Original Prusa MK4S",
    "Prusa Research Original Prusa MK3.9S",
    # Prusa's own names and other spellings of a supported printer.
    "Prusa Signature Oak",
    "Prusa Prusa Signature Oak",
    "Prusa MK3.5S",
    "Prusa MK3.5 MMU3",
    "Prusa MK3.9",
    "Prusa MK3.9S",
    "Prusa MK3.9S MMU3",
    "Prusa MK4S MMU3",
    "Prusa MK4IS",
    "Prusa MINI+",
    "Prusa Mini+",
    "Prusa MINIIS",
    "Prusa XLIS",
    "Prusa XL+",
    "Prusa XL+ 5T",
    "Prusa iX",
    "Prusa CORE One+",
    "Prusa CORE One L+",
    "Prusa CoreOne",
    "Original Prusa MK4S",
]
# The i3 printers on the 8-bit firmware. OrcaSlicer ships only the MK3S; the rest are custom printers.
LEGACY_MODELS = [
    "Prusa MK3S",
    "Prusa MK3S+",
    "Prusa MK3S MMU3",
    "Prusa MK3",
    "Prusa MK3 MMU2S",
    "Prusa MK2.5",
    "Prusa MK2.5S",
    "Prusa MK2.5S MMU2S",
    "Prusa MK2S",
    "Prusa i3 MK3",
    "Original Prusa i3 MK3S+",
    "Prusa Prusa MK3S",
    "Prusa Original Prusa i3 MK3S+",
    "Prusa Research MK3",
    "Prusa MK25S",
    "Prusa MK3SMMU3",
    "Prusa MK3MMU2",
    "Prusa MK2.5SMMU2S",
    "Prusa MK2SMM",
]
# Names that only resemble a supported one, Prusa's other machines, and printers that are not Prusa's.
OTHER_MODELS = [
    "Prusa Signature Oakley",
    "Prusa",
    "Prusa ",
    "Prusa MK3.55",
    "Prusa MK355",
    "Prusa MK395",
    "Prusa MK40",
    "Prusa MK4MMU2",
    "Prusa XLarge",
    "Prusa XL25",
    "Prusa XL3",
    "Prusa Research",
    "Research MK4S",
    "Prusa MINIATURE",
    "Prusa SL1S",
    "Prusa Pro HT90",
    "MK4S",
    "Not a Prusa MK4S",
    "Prusament MK4S",
    "Bambu Lab X1 Carbon",
    "Voron 2.4 XL",
    "",
    None,
]


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


# The last is the temporary 3MF of a send through a printer agent, or of an upload as 3MF.
@pytest.mark.parametrize("output_name", ["/out/print.gcode.3mf", "print.GCODE.3MF", "/tmp/.4242.1.3mf"])
@pytest.mark.parametrize("model", ["Prusa CORE One", "Prusa MK3S", "Voron 2.4"])
def test_gcode_inside_a_3mf_stays_text(orca, export, gcode_file, context, output_name, model):
    """Also for a printer the plugin refuses: a 3MF holds text either way, so there is nothing to refuse."""
    original = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, output_name=output_name, printer_model=model))
    assert result.status == orca.PluginResult.Skipped
    assert gcode_file.read_bytes() == original


@pytest.mark.parametrize("model", [*LEGACY_MODELS, *OTHER_MODELS])
def test_printers_without_bgcode_support_are_refused_at_export(orca, export, gcode_file, context, model):
    original = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, printer_model=model))
    printer = f'The printer model "{model}"' if model else "This printer"
    assert result.status == orca.PluginResult.RecoverableError
    assert result.message == (
        f"Binary G-code needs a Prusa MINI, MK3.5, MK3.9, MK4, XL, CORE One or iX. {printer} is not recognised "
        'as one. Run "Toggle Prusa Binary G-code" to turn the feature off.'
    )
    assert gcode_file.read_bytes() == original


@pytest.mark.parametrize("model", [*ORCA_BUDDY_MODELS, *CUSTOM_BUDDY_MODELS])
def test_buddy_printers_get_binary_gcode_at_export(orca, export, gcode_file, context, model):
    assert export.execute(context(gcode_file, printer_model=model)).status == orca.PluginResult.Success
    assert is_binary(gcode_file)


def test_add_line_number_does_not_stop_the_export(orca, export, gcode_file, context):
    """OrcaSlicer 2.5 numbers lines only in a Bambu printer's export, which this plugin never converts.

    For every other printer the setting changes nothing in the saved file, so it is not a reason to
    refuse a conversion that works.
    """
    result = export.execute(context(gcode_file, gcode_add_line_number="1"))
    assert result.status == orca.PluginResult.Success
    assert reader.parse_file(gcode_file).commands


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


@pytest.mark.parametrize("output_name", ["print.bgcode", "/Volumes/USB/print.BGC"])
def test_already_binary_gcode_is_left_alone(orca, export, gcode_file, context, output_name):
    export.execute(context(gcode_file))
    converted = gcode_file.read_bytes()
    result = export.execute(context(gcode_file, output_name=output_name))
    assert result.status == orca.PluginResult.Skipped
    assert gcode_file.read_bytes() == converted


@pytest.mark.parametrize(
    ("output_name", "model", "explanation"),
    [
        ("print.gcode", "Prusa CORE One", '"print.gcode" does not end in .bgcode.'),
        ("/out/print.gcode.3mf", "Prusa CORE One", '"print.gcode.3mf" stores its G-code as text.'),
        ("/tmp/.4242.1.3mf", "Prusa MK3S", '".4242.1.3mf" stores its G-code as text.'),
        ("print.bgcode", "Prusa MK3S", 'The printer model "Prusa MK3S" is not recognised as one.'),
        ("print.gcode", "Prusa MK3S", 'The printer model "Prusa MK3S" is not recognised as one.'),
        # Bambu printers are processed in place under a temporary name. Theirs is the one export
        # OrcaSlicer may number the lines of afterwards, which would turn the magic into "N1 GCDE".
        ("/tmp/.4242.1.gcode", "Bambu Lab X1 Carbon", 'The printer model "Bambu Lab X1 Carbon" is not recognised'),
    ],
)
def test_already_binary_gcode_is_refused_where_it_would_not_print(
    orca, export, gcode_file, context, output_name, model, explanation
):
    """An earlier script or plugin converted the file, and the host would save it as it is."""
    export.execute(context(gcode_file))
    converted = gcode_file.read_bytes()
    assert is_binary(gcode_file)
    result = export.execute(context(gcode_file, output_name=output_name, printer_model=model))
    assert result.status == orca.PluginResult.RecoverableError
    assert explanation in result.message
    # The toggle would not help: the step that converted the file has to go.
    assert "runs before this one already converted" in result.message
    assert "Toggle Prusa Binary G-code" not in result.message
    assert gcode_file.read_bytes() == converted


def test_an_earlier_step_is_blamed_only_when_the_gcode_is_already_binary(orca, export, gcode_file, context):
    text = export.execute(context(gcode_file, output_name="print.gcode"))
    export.execute(context(gcode_file))
    binary = export.execute(context(gcode_file, output_name="print.gcode"))
    assert "Toggle Prusa Binary G-code" in text.message and "runs before this one" not in text.message
    assert "runs before this one" in binary.message and "Toggle Prusa Binary G-code" not in binary.message


def test_an_unsupported_printer_is_reported_before_the_file_name(orca, export, gcode_file, context):
    """Bambu printers are post-processed under the temporary file's name, which the user never chose."""
    result = export.execute(context(gcode_file, output_name="/tmp/plate_1.gcode", printer_model="Bambu Lab X1 Carbon"))
    assert result.status == orca.PluginResult.RecoverableError
    assert 'The printer model "Bambu Lab X1 Carbon" is not recognised as one.' in result.message
    assert "plate_1.gcode" not in result.message


@pytest.mark.parametrize(
    "text",
    [
        "",
        "; CONFIG_BLOCK_START\n; layer_height = 0.2\n; CONFIG_BLOCK_END\n",
        "; a comment\n\n",
        "\ufeff; CONFIG_BLOCK_START\n; layer_height = 0.2\n; CONFIG_BLOCK_END\n",
    ],
    ids=["empty", "config_only", "comments_only", "config_only_with_byte_order_mark"],
)
def test_gcode_without_commands_fails_before_the_file_is_replaced(orca, export, gcode_file, context, text):
    """A post-processing script can leave such a file. It has nothing to print, and when it has no
    G-code lines at all, its .bgcode would not even have a G-code block."""
    gcode_file.write_text(text, encoding="utf-8")
    result = export.execute(context(gcode_file))
    assert result.status == orca.PluginResult.RecoverableError
    assert "no commands" in result.message and "post-processing script" in result.message
    assert gcode_file.read_text(encoding="utf-8") == text
    assert [path.name for path in gcode_file.parent.iterdir()] == [gcode_file.name]


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


@pytest.mark.parametrize("model", [*LEGACY_MODELS, *OTHER_MODELS])
def test_printers_without_bgcode_support_are_refused(orca, toggle, model):
    orca.host.printer_model = model
    before = dict(orca.host.process.values)
    result = toggle.execute()
    assert result.status == orca.PluginResult.Skipped
    assert orca.host.process.values == before
    (level, text), = orca.host.notifications
    assert level == orca.host.ui.NotificationLevel.WarningNotificationLevel
    assert text == result.message
    assert "needs a Prusa MINI, MK3.5, MK3.9, MK4, XL, CORE One or iX." in text and "is not recognised as one." in text
    assert "Toggle" not in text  # nothing was turned on, so there is nothing to turn off


@pytest.mark.parametrize("model", [*ORCA_BUDDY_MODELS, *CUSTOM_BUDDY_MODELS])
def test_buddy_printers_can_turn_it_on(orca, toggle, model):
    orca.host.printer_model = model
    assert toggle.execute().status == orca.PluginResult.Success


def test_it_can_always_be_turned_off(orca, toggle):
    toggle.execute()
    orca.host.printer_model = "Prusa MK3S"  # e.g. the printer was changed after turning it on
    assert toggle.execute().status == orca.PluginResult.Success
    assert orca.host.process.values["slicing_pipeline_plugin"] == ""


# A printer preset's own plugin list, as OrcaSlicer leaves it from a change to the Printer Agent setting
# until it restarts: naming an agent plugin, or empty for a built-in agent.
PRINTER_PLUGIN_LISTS = ['"Moonraker Agent;;Moonraker Printer Agent"', '"Cloud Agent;3f2a;Agent";"Other;;Thing"', ""]
# The question is "Keep binary G-code off for now?". Yes has the focus, and a closed box answers "cancel".
KEEP_OFF_ANSWERS = ["yes", "cancel"]
TURN_ON_ANSWER = "no"


def test_a_printer_without_its_own_plugin_list_is_not_asked_about(orca, toggle):
    orca.host.answer = "yes"  # would keep it off
    assert toggle.execute().status == orca.PluginResult.Success
    assert orca.host.messages == []


@pytest.mark.parametrize("answer", KEEP_OFF_ANSWERS)
@pytest.mark.parametrize("plugin_list", PRINTER_PLUGIN_LISTS)
def test_a_printer_plugin_list_that_hides_the_converter_is_explained_first(orca, toggle, plugin_list, answer):
    """OrcaSlicer before 2.5.1 would skip the conversion and save text under the .bgcode name."""
    orca.host.printer.values["plugins"] = plugin_list
    orca.host.answer = answer
    process, printer = dict(orca.host.process.values), dict(orca.host.printer.values)
    result = toggle.execute()
    assert result.status == orca.PluginResult.Skipped
    assert "stays off" in result.message and "Restart OrcaSlicer" in result.message
    assert '"Prusa CORE One 0.4 nozzle"' in result.message
    assert orca.host.process.values == process  # no .bgcode name without a converter
    assert orca.host.printer.values == printer
    assert orca.host.notifications == []
    (text, title, buttons, icon), = orca.host.messages
    assert '"Prusa CORE One 0.4 nozzle"' in text and "Printer Agent" in text
    assert "2.5.1" in text and "Restart OrcaSlicer" in text
    assert "Keep binary G-code off for now?\nYes: it stays off." in text  # the focused button is the safe one
    assert (title, buttons, icon) == ("Toggle Prusa Binary G-code", "yes_no", "warning")


@pytest.mark.parametrize("plugin_list", PRINTER_PLUGIN_LISTS)
def test_binary_gcode_can_be_turned_on_despite_a_printer_plugin_list(orca, toggle, plugin_list):
    """OrcaSlicer 2.5.1 finds the converter by name, so the user decides."""
    orca.host.printer.values["plugins"] = plugin_list
    orca.host.answer = TURN_ON_ANSWER
    printer = dict(orca.host.printer.values)
    assert toggle.execute().status == orca.PluginResult.Success
    assert len(orca.host.messages) == 1
    assert orca.host.process.values["slicing_pipeline_plugin"] == '"Prusa Binary G-code Export"'
    assert orca.host.process.values["filename_format"].endswith(".bgcode")
    assert orca.host.printer.values == printer  # the Printer Agent's entry is left alone
    (_, notice), = orca.host.notifications
    assert "is on" in notice and "Save the preset" in notice


@pytest.mark.parametrize("answer", KEEP_OFF_ANSWERS)
@pytest.mark.parametrize("filename_format", ["{a}.bgcode", "{a}.BGC"])
@pytest.mark.parametrize("plugin_list", PRINTER_PLUGIN_LISTS)
def test_keeping_it_off_also_undoes_a_binary_name_left_without_the_converter(
    orca, toggle, plugin_list, filename_format, answer
):
    """The state after removing the export by hand. Left alone, text would be saved as .bgcode."""
    orca.host.process.values["filename_format"] = filename_format
    orca.host.printer.values["plugins"] = plugin_list
    orca.host.answer = answer
    printer = dict(orca.host.printer.values)
    result = toggle.execute()
    assert result.status == orca.PluginResult.Success
    assert orca.host.process.values == {"filename_format": "{a}.gcode", "slicing_pipeline_plugin": ""}
    assert orca.host.printer.values == printer
    assert len(orca.host.messages) == 1
    (_, notice), = orca.host.notifications
    assert notice == result.message
    assert "is off" in notice and "now ends in .gcode" in notice and "Restart OrcaSlicer" in notice


@pytest.mark.parametrize("model", ["Prusa MK3", "Prusa3D MK4S", "Voron 2.4", None])
@pytest.mark.parametrize("filename_format", ["{a}.bgcode", "{a}.BGC"])
@pytest.mark.parametrize("plugin_list", [None, *PRINTER_PLUGIN_LISTS])
def test_a_binary_name_without_the_converter_is_undone_for_a_refused_printer_too(
    orca, toggle, model, filename_format, plugin_list
):
    """Otherwise the toggle could never bring such a preset back in step, and text would be saved as .bgcode."""
    orca.host.printer_model = model
    orca.host.process.values.update({"filename_format": filename_format, "slicing_pipeline_plugin": '"Other Plugin"'})
    if plugin_list is not None:
        orca.host.printer.values["plugins"] = plugin_list
    orca.host.answer = TURN_ON_ANSWER  # not asked: this printer cannot have the feature
    result = toggle.execute()
    assert result.status == orca.PluginResult.Success
    assert orca.host.process.values == {"filename_format": "{a}.gcode", "slicing_pipeline_plugin": '"Other Plugin"'}
    assert orca.host.messages == []
    (level, notice), = orca.host.notifications
    assert level == orca.host.ui.NotificationLevel.RegularNotificationLevel and notice == result.message
    assert "is off" in notice and "now ends in .gcode" in notice and "is not recognised as one." in notice
    assert "Save the preset" not in notice and "Restart" not in notice


def test_turning_off_removes_the_export_however_often_it_is_listed(orca, toggle):
    """The host's plugin picker does not stop the export being added a second time."""
    orca.host.process.values.update(
        {
            "filename_format": "{a}.bgcode",
            "slicing_pipeline_plugin": '"Other Plugin";"Prusa Binary G-code Export";Plain;"Prusa Binary G-code Export"',
        }
    )
    assert toggle.execute().status == orca.PluginResult.Success
    assert orca.host.process.values == {"filename_format": "{a}.gcode", "slicing_pipeline_plugin": '"Other Plugin";Plain'}


def test_keeping_it_off_leaves_the_other_selected_plugins(orca, toggle):
    orca.host.process.values.update({"filename_format": "{a}.bgcode", "slicing_pipeline_plugin": '"Other Plugin";Plain'})
    orca.host.printer.values["plugins"] = ""
    orca.host.answer = "yes"
    toggle.execute()
    assert orca.host.process.values == {"filename_format": "{a}.gcode", "slicing_pipeline_plugin": '"Other Plugin";Plain'}


@pytest.mark.parametrize(
    "plugin_list",
    [
        '"orca_bgcode_plugin_any;;Prusa Binary G-code Export"',
        '"Agent;;Agent";"Prusa Binary G-code;0b5e;Prusa Binary G-code Export"',
        '"A \\"quoted\\" plugin;;Prusa Binary G-code Export"',
    ],
)
def test_a_printer_plugin_list_that_names_the_converter_is_not_asked_about(orca, toggle, plugin_list):
    orca.host.printer.values["plugins"] = plugin_list
    orca.host.answer = "yes"  # would keep it off
    assert toggle.execute().status == orca.PluginResult.Success
    assert orca.host.messages == []


@pytest.mark.parametrize(
    "plugin_list",
    [
        # The export's name in the plugin or uuid part, or as part of another capability's name.
        '"Prusa Binary G-code Export;;Agent"',
        '"Agent;Prusa Binary G-code Export;Agent"',
        '"Agent;;Other;Prusa Binary G-code Export"',
        '"Agent;;Not Prusa Binary G-code Export"',
        # Not a reference at all for the host, which wants a plugin, a uuid part and a capability.
        "Prusa",
        '"Prusa Binary G-code Export"',
        '"uuid;Prusa Binary G-code Export"',
        '";;Prusa Binary G-code Export"',
    ],
)
def test_only_the_capability_of_a_plugin_list_entry_counts(orca, toggle, plugin_list):
    orca.host.printer.values["plugins"] = plugin_list
    orca.host.answer = "yes"
    assert toggle.execute().status == orca.PluginResult.Skipped
    assert len(orca.host.messages) == 1


@pytest.mark.parametrize("plugin_list", PRINTER_PLUGIN_LISTS)
def test_it_can_be_turned_off_under_a_printer_plugin_list_without_being_asked(orca, toggle, plugin_list):
    before = dict(orca.host.process.values)
    toggle.execute()
    orca.host.printer.values["plugins"] = plugin_list  # e.g. a Printer Agent was set up afterwards
    assert toggle.execute().status == orca.PluginResult.Success
    assert orca.host.process.values == before
    assert orca.host.messages == []


def test_an_unsupported_printer_is_refused_before_its_plugin_list_is_looked_at(orca, toggle):
    orca.host.printer_model = "Prusa MK3S"
    orca.host.printer.values["plugins"] = ""
    assert toggle.execute().status == orca.PluginResult.Skipped
    assert orca.host.messages == []


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
