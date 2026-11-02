"""The .bgcode file itself: its structure, and that nothing printable is lost."""
import struct

import gcode_lib as gl
import pytest

import bgcode_reader as reader
from conftest import FIXTURE, FIXTURE_WITH_THUMBNAILS, PNG_DATA, QOI_DATA, thumbnail_comment


def convert(plugin, path):
    plugin.convert_in_place(str(path))
    return reader.parse_file(path)


def source_gcode_lines():
    """The executable lines of the fixture, which every conversion must preserve in order."""
    with open(FIXTURE, encoding="utf-8") as file:
        return [line for line in file if not line.startswith(";") and line.strip()]


def test_output_passes_the_strict_reader(plugin, gcode_file):
    converted = convert(plugin, gcode_file)
    assert converted.version == 1


def test_gcode_lib_can_read_the_output_back(plugin, gcode_file):
    convert(plugin, gcode_file)
    loaded = gl.read_bgcode(gcode_file.read_bytes())
    assert loaded.source_format == "bgcode"
    assert [line.raw + "\n" for line in loaded.lines if line.raw.strip() and not line.raw.startswith(";")] == (
        source_gcode_lines()
    )


def test_every_executable_line_survives_in_order(plugin, gcode_file):
    gcode = convert(plugin, gcode_file).gcode
    assert [line for line in gcode.splitlines(True) if not line.startswith(";") and line.strip()] == (
        source_gcode_lines()
    )


def test_gcode_blocks_are_capped_at_the_libbgcode_size(plugin, gcode_file):
    blocks = convert(plugin, gcode_file).of_type(reader.GCODE)
    assert len(blocks) > 1, "the fixture spans several blocks, or this test proves nothing"
    assert all(len(block.payload) <= 65536 for block in blocks)


def test_gcode_blocks_are_filled_rather_than_fragmented(plugin, gcode_file):
    blocks = convert(plugin, gcode_file).of_type(reader.GCODE)
    longest_line = max(len(line) for block in blocks for line in block.payload.splitlines(True))
    assert all(len(block.payload) > 65536 - longest_line for block in blocks[:-1])


def test_block_size_is_counted_in_bytes_not_characters(plugin, tmp_path):
    line = "; " + "é" * 40 + "\n"  # twice as many bytes as characters
    path = tmp_path / "wide.gcode"
    path.write_text(line * 3000, encoding="utf-8")
    converted = convert(plugin, path)
    assert all(len(block.payload) <= 65536 for block in converted.of_type(reader.GCODE))
    assert converted.gcode == line * 3000


def test_non_ascii_text_survives_exactly(plugin, tmp_path):
    text = "; printing object Würfel 立方体 id:0\nM486 AWürfel\nG28\n"
    path = tmp_path / "unicode.gcode"
    path.write_text(text, encoding="utf-8")
    assert convert(plugin, path).gcode == text


def test_gcode_blocks_end_on_whole_lines(plugin, gcode_file):
    blocks = convert(plugin, gcode_file).of_type(reader.GCODE)
    assert all(block.payload.endswith(b"\n") for block in blocks)


def test_gcode_block_params_declare_no_encoding(plugin, gcode_file):
    blocks = convert(plugin, gcode_file).of_type(reader.GCODE)
    assert {block.params for block in blocks} == {struct.pack("<H", 0)}


def test_a_line_longer_than_a_block_is_kept_whole(plugin, tmp_path):
    long_comment = "; " + "x" * 70000 + "\n"
    path = tmp_path / "long.gcode"
    path.write_text("G28\n" + long_comment + "G1 X1\n", encoding="utf-8")
    converted = convert(plugin, path)
    assert converted.gcode == "G28\n" + long_comment + "G1 X1\n"
    assert long_comment.encode() in [block.payload for block in converted.of_type(reader.GCODE)]


def test_config_moves_from_the_gcode_to_slicer_metadata(plugin, gcode_file):
    converted = convert(plugin, gcode_file)
    slicer = converted.metadata(reader.SLICER_METADATA)
    assert slicer["layer_height"] == "0.2"
    assert slicer["filament_type"] == "PLA"
    assert slicer["printer_model"] == "Prusa CORE One"
    assert "CONFIG_BLOCK" not in converted.gcode
    assert "; layer_height = 0.2" not in converted.gcode


def test_a_config_value_containing_an_equals_sign_is_kept_whole(plugin, tmp_path):
    path = tmp_path / "config.gcode"
    path.write_text("; CONFIG_BLOCK_START\n; start_gcode = M104 S{a=1}\n; CONFIG_BLOCK_END\nG28\n", encoding="utf-8")
    assert convert(plugin, path).metadata(reader.SLICER_METADATA)["start_gcode"] == "M104 S{a=1}"


def test_a_config_line_without_a_value_is_ignored(plugin, tmp_path):
    path = tmp_path / "config.gcode"
    path.write_text("; CONFIG_BLOCK_START\n; not a setting\n; CONFIG_BLOCK_END\nG28\n", encoding="utf-8")
    converted = convert(plugin, path)
    assert converted.metadata(reader.SLICER_METADATA) == {}
    assert converted.gcode == "G28\n"


def test_printer_model_is_the_id_the_firmware_checks(plugin, gcode_file):
    metadata = convert(plugin, gcode_file).metadata(reader.PRINTER_METADATA)
    assert metadata["printer_model"] == "COREONE"


def test_printer_metadata_translates_orca_settings_to_prusa_keys(plugin, gcode_file):
    metadata = convert(plugin, gcode_file).metadata(reader.PRINTER_METADATA)
    assert metadata["filament_type"] == "PLA"
    assert metadata["nozzle_diameter"] == "0.4"
    assert metadata["layer_height"] == "0.2"
    assert metadata["brim_width"] == "5"
    assert metadata["fill_density"] == "15%"
    assert metadata["temperature"] == "220"
    assert metadata["bed_temperature"] == "35"
    assert metadata["support_material"] == "1"
    assert metadata["extruder_colour"] == "#F2754E"
    assert metadata["max_layer_z"] == "20.00"


def test_printer_metadata_carries_what_the_firmware_shows(plugin, gcode_file):
    metadata = convert(plugin, gcode_file).metadata(reader.PRINTER_METADATA)
    assert metadata["estimated printing time (normal mode)"] == "19m 43s"
    assert metadata["filament used [mm]"] == "1275.26"
    assert metadata["filament used [g]"] == "3.80"


@pytest.mark.parametrize(("ironing_type", "expected"), [("no ironing", "0"), ("top", "1")])
def test_ironing_is_reported_as_a_flag(plugin, tmp_path, ironing_type, expected):
    path = tmp_path / "ironing.gcode"
    path.write_text(f"; CONFIG_BLOCK_START\n; ironing_type = {ironing_type}\n; CONFIG_BLOCK_END\nG28\n", encoding="utf-8")
    assert convert(plugin, path).metadata(reader.PRINTER_METADATA)["ironing"] == expected


def test_print_metadata_carries_the_statistics(plugin, gcode_file):
    metadata = convert(plugin, gcode_file).metadata(reader.PRINT_METADATA)
    assert metadata == {
        "filament used [mm]": "1275.26",
        "filament used [cm3]": "3.07",
        "filament used [g]": "3.80",
        "filament cost": "0.10",
        "total filament used [g]": "3.80",
        "total filament cost": "0.10",
        "estimated printing time (normal mode)": "19m 43s",
        "estimated first layer printing time (normal mode)": "4m 32s",
    }


def test_every_statistic_reaches_the_blocks_the_firmware_and_connect_read(plugin, tmp_path):
    path = tmp_path / "statistics.gcode"
    path.write_text(
        "G28\n"
        "; filament used [mm] = 100.00, 200.00\n"
        "; filament used [cm3] = 1.00, 2.00\n"
        "; filament used [g] = 1.20, 2.40\n"
        "; filament cost = 0.10, 0.20\n"
        "; total filament used [g] = 3.60\n"
        "; total filament cost = 0.30\n"
        "; total filament used for wipe tower [g] = 0.50\n"
        "; total filament change = 12\n"
        "; estimated printing time (normal mode) = 1h 2m 3s\n"
        "; estimated first layer printing time (normal mode) = 4m 5s\n",
        encoding="utf-8",
    )
    converted = convert(plugin, path)
    assert converted.metadata(reader.PRINTER_METADATA) == {
        "filament used [mm]": "100.00, 200.00",
        "filament used [cm3]": "1.00, 2.00",
        "filament used [g]": "1.20, 2.40",
        "filament cost": "0.10, 0.20",
        "estimated printing time (normal mode)": "1h 2m 3s",
        "total filament used for wipe tower [g]": "0.50",
        "total toolchanges": "12",
    }
    assert converted.metadata(reader.PRINT_METADATA) == {
        "total toolchanges": "12",
        "filament used [mm]": "100.00, 200.00",
        "filament used [cm3]": "1.00, 2.00",
        "filament used [g]": "1.20, 2.40",
        "filament cost": "0.10, 0.20",
        "total filament used [g]": "3.60",
        "total filament cost": "0.30",
        "total filament used for wipe tower [g]": "0.50",
        "estimated printing time (normal mode)": "1h 2m 3s",
        "estimated first layer printing time (normal mode)": "4m 5s",
    }


def test_the_tail_statistics_win_over_custom_gcode(plugin, tmp_path):
    path = tmp_path / "custom.gcode"
    path.write_text("; filament used [g] = 99\nG28\n; filament used [g] = 3.80\n", encoding="utf-8")
    assert convert(plugin, path).metadata(reader.PRINT_METADATA)["filament used [g]"] == "3.80"


@pytest.mark.parametrize(
    ("bed_type", "expected"),
    [
        ("Cool Plate", "35"),
        ("Engineering Plate", "70"),
        ("High Temp Plate", "60"),
        ("Textured PEI Plate", "45"),
        ("Textured Cool Plate", "40"),
        ("Supertack Plate", "30"),
        ("Unknown Plate", "99"),
    ],
)
def test_bed_temperature_is_the_one_for_the_plate_in_use(plugin, tmp_path, bed_type, expected):
    path = tmp_path / "bed.gcode"
    path.write_text(
        "; CONFIG_BLOCK_START\n"
        f"; curr_bed_type = {bed_type}\n"
        "; cool_plate_temp = 35\n; eng_plate_temp = 70\n; hot_plate_temp = 60\n"
        "; textured_plate_temp = 45\n; textured_cool_plate_temp = 40\n; supertack_plate_temp = 30\n"
        "; first_layer_bed_temperature = 99\n"
        "; CONFIG_BLOCK_END\nG28\n",
        encoding="utf-8",
    )
    assert convert(plugin, path).metadata(reader.PRINTER_METADATA)["bed_temperature"] == expected


def test_a_long_blank_comment_does_not_stall_the_export(plugin, tmp_path):
    path = tmp_path / "blank.gcode"  # a backtracking parser would not finish this within the run
    path.write_text(";" + " " * 200000 + "\n; a\nG28\n", encoding="utf-8")
    assert convert(plugin, path).gcode.endswith("G28\n")


def test_file_metadata_names_the_producer(plugin, gcode_file):
    metadata = convert(plugin, gcode_file).metadata(reader.FILE_METADATA)
    assert metadata == {"Producer": "OrcaSlicer 2.5.0-rc", "Produced on": "2026-11-01 at 15:36:26"}


def test_a_file_without_metadata_comments_still_gets_the_required_blocks(plugin, tmp_path):
    path = tmp_path / "bare.gcode"
    path.write_text("G28\nG1 X10\n", encoding="utf-8")
    converted = convert(plugin, path)  # the strict reader rejects missing required blocks
    assert converted.gcode == "G28\nG1 X10\n"
    assert converted.metadata(reader.PRINTER_METADATA) == {}


def test_the_generated_by_line_is_read_from_the_header(plugin, tmp_path):
    path = tmp_path / "producer.gcode"
    path.write_text("; generated by OrcaSlicer 2.5.0-rc on today\n; generated by a macro on tomorrow\nG28\n", encoding="utf-8")
    assert convert(plugin, path).metadata(reader.FILE_METADATA) == {"Producer": "OrcaSlicer 2.5.0-rc", "Produced on": "today"}


def test_a_file_of_only_comments_has_no_blocks_to_split(plugin, tmp_path):
    path = tmp_path / "config_only.gcode"
    path.write_text("; CONFIG_BLOCK_START\n; a = 1\n; CONFIG_BLOCK_END\n", encoding="utf-8")
    assert list(plugin.gcode_blocks(str(path))) == []


def test_custom_gcode_cannot_override_the_header_height(plugin, tmp_path):
    path = tmp_path / "height.gcode"
    path.write_text("; max_z_height: 20.00\nG28\n; max_layer_z = 99\n; max_z_height: 98\n", encoding="utf-8")
    assert convert(plugin, path).metadata(reader.PRINTER_METADATA)["max_layer_z"] == "20.00"


def test_an_only_first_printer_check_is_used(plugin, tmp_path):
    path = tmp_path / "checks.gcode"
    path.write_text('M862.3 P "MK4S" ; printer model check\nM862.3 P "XL"\n', encoding="utf-8")
    assert convert(plugin, path).metadata(reader.PRINTER_METADATA)["printer_model"] == "MK4S"


def with_thumbnails(path, thumbnail_text):
    path.write_text(thumbnail_text + path.read_text(encoding="utf-8"), encoding="utf-8")


def test_thumbnails_become_blocks_in_their_own_format(plugin, gcode_file, thumbnail_text):
    with_thumbnails(gcode_file, thumbnail_text)
    converted = convert(plugin, gcode_file)
    blocks = converted.of_type(reader.THUMBNAIL)
    assert [(block.params, block.payload) for block in blocks] == [
        (struct.pack("<HHH", 2, 16, 16), QOI_DATA),  # format 2 is QOI
        (struct.pack("<HHH", 0, 640, 480), PNG_DATA),  # format 0 is PNG
    ]


def test_thumbnails_are_removed_from_the_gcode(plugin, gcode_file, thumbnail_text):
    with_thumbnails(gcode_file, thumbnail_text)
    assert "thumbnail" not in convert(plugin, gcode_file).gcode


def test_real_thumbnails_from_the_gui_become_blocks(plugin, tmp_path):
    path = tmp_path / "gui.gcode"
    path.write_bytes(FIXTURE_WITH_THUMBNAILS.read_bytes())
    converted = convert(plugin, path)
    assert [struct.unpack("<HHH", block.params) for block in converted.of_type(reader.THUMBNAIL)] == [
        (2, 16, 16),
        (2, 313, 173),
        (2, 440, 240),
        (2, 480, 240),
        (0, 640, 480),
    ]
    assert all(block.payload[:4] in (b"qoif", b"\x89PNG") for block in converted.of_type(reader.THUMBNAIL))


def test_comments_around_real_thumbnails_are_not_lost(plugin, tmp_path):
    path = tmp_path / "gui.gcode"
    path.write_bytes(FIXTURE_WITH_THUMBNAILS.read_bytes())
    converted = convert(plugin, path)
    assert converted.metadata(reader.FILE_METADATA)["Producer"] == "OrcaSlicer 2.5.0-rc"
    assert converted.gcode.count("; THUMBNAIL_BLOCK_START") == 5  # the wrapper stays, its data does not
    assert converted.gcode.count("; THUMBNAIL_BLOCK_END") == 5  # the comment right after each image
    assert "; external perimeters extrusion width" in converted.gcode
    assert "thumbnail_QOI" not in converted.gcode


def test_no_thumbnail_blocks_when_the_gcode_has_none(plugin, gcode_file):
    assert convert(plugin, gcode_file).of_type(reader.THUMBNAIL) == []


@pytest.mark.parametrize(
    "unterminated",
    [
        thumbnail_comment("thumbnail", 16, 16, PNG_DATA).rsplit("; thumbnail end", 1)[0],
        "; CONFIG_BLOCK_START\n; layer_height = 0.2\n",
    ],
    ids=["thumbnail", "config"],
)
def test_a_missing_end_marker_cannot_swallow_the_print(plugin, tmp_path, unterminated):
    path = tmp_path / "unterminated.gcode"
    path.write_text(unterminated + "G28\nG1 X10\n", encoding="utf-8")
    assert "G28\nG1 X10\n" in convert(plugin, path).gcode


def test_windows_line_endings_are_normalised(plugin, tmp_path):
    path = tmp_path / "crlf.gcode"
    path.write_bytes(b"G28\r\nG1 X10\r\n")
    assert convert(plugin, path).gcode == "G28\nG1 X10\n"


def test_non_utf8_bytes_do_not_stop_the_export(plugin, tmp_path):
    path = tmp_path / "latin1.gcode"
    path.write_bytes(b"; caf\xe9\nG28\n")
    assert convert(plugin, path).gcode.endswith("G28\n")


def test_a_failed_write_leaves_the_text_gcode_and_no_temporary_file(plugin, gcode_file, monkeypatch):
    original = gcode_file.read_bytes()

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr(plugin, "gcode_block", fail)
    with pytest.raises(OSError, match="disk full"):
        plugin.convert_in_place(str(gcode_file))
    assert gcode_file.read_bytes() == original
    assert [path.name for path in gcode_file.parent.iterdir()] == [gcode_file.name]


def test_a_successful_conversion_leaves_no_temporary_file(plugin, gcode_file):
    plugin.convert_in_place(str(gcode_file))
    assert [path.name for path in gcode_file.parent.iterdir()] == [gcode_file.name]
