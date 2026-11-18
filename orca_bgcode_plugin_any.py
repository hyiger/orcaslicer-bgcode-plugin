# /// script
# requires-python = ">=3.12"
# dependencies = ["gcode-lib==1.8.0", "heatshrink2==0.15.0"]
#
# [tool.orcaslicer.plugin]
# name = "Prusa Binary G-code"
# description = "Compresses G-code to .bgcode for Prusa printers, for faster uploads to PrusaLink and Prusa Connect."
# author = "hyiger"
# version = "1.0.1"
# type = "slicing-pipeline"
# ///
"""Prusa Binary G-code -- writes Orca's text G-code out as a compressed Prusa .bgcode file.

The point is shorter uploads: the file is about 60% smaller than the text G-code. Two capabilities
cooperate:

* "Prusa Binary G-code Export" converts the file at Step.psGCodePostProcess, the one seam shared by
  file export, PrusaLink and Prusa Connect.
* "Toggle Prusa Binary G-code" is the on/off switch for the active process preset.

The switch has to exist because a plugin cannot rename its output: ctx.output_name is read-only and
the host reads the ".output_name" side file before plugins run. The name comes from the process
preset's filename_format, so turning the feature on sets both that extension and the plugin
selection, and turning it off clears both. Prusa firmware picks its reader by extension, so a binary
file named .gcode or a text file named .bgcode would not print. While the export capability runs it
refuses to write binary under any other name. The opposite mismatch, a .bgcode name with the
capability not running, cannot be caught here, which is why the two settings change together.

G-code inside a .gcode.3mf stays text: the host stores it as Metadata/plate_<N>.gcode.

The host saves whatever the export leaves, also when it reports that it skipped the file. Scripts,
and the plugins listed before the export in slicing_pipeline_plugin, run before it on the same file,
so binary G-code one of them wrote is refused wherever this plugin would not have written it itself.
ctx.output_name is the only sign of the destination. A script can replace it through the
".output_name" file, and when a 3MF is being written the host still packs the file into the 3MF,
which cannot be seen from here. A plugin listed after the export is handed the binary file.

gcode-lib lifts the thumbnails and compresses the G-code with MeatPack and Heatshrink, using the
same settings as PrusaSlicer. heatshrink2 makes that about 25 times faster than gcode-lib's pure
Python encoder, which is what keeps the conversion from costing more time than the smaller file
saves. write_bgcode() alone does not make a complete file, so this plugin adds the metadata blocks
and the file header version the specification defines.

The file is streamed rather than loaded with gcode_lib.load(), whose per-line objects cost about
1 GB of memory on a 40 MB file, on top of the slicer's own use.
"""
import os
import re
import struct
import zlib

import gcode_lib as gl
import orca

EXPORT_NAME = "Prusa Binary G-code Export"
TOGGLE_NAME = "Toggle Prusa Binary G-code"
SERIALIZED_EXPORT_NAME = f'"{EXPORT_NAME}"'  # quoted because the name contains spaces

GCODE_EXTENSION = ".gcode"
BGCODE_EXTENSION = ".bgcode"
# Every extension the firmware reads as binary G-code.
BGCODE_EXTENSIONS = (BGCODE_EXTENSION, ".bgc")

# Only Prusa's Buddy firmware reads binary G-code. The i3 printers before the MK3.5 (the MK2, MK2.5,
# MK3 and MK3S, with their S, + and MMU variants) run the 8-bit firmware, which does not, so a name is
# accepted for the family it names, not for looking like a Prusa.
#
# Orca's own profiles are named like "Prusa MK4S", "Prusa CORE One L HF" and "Prusa XL 5T". A custom
# printer is named "<vendor> <model>" by the Create Printer dialog and cannot be renamed afterwards,
# so what that dialog produces has to pass as well. Its own model list repeats the vendor ("Prusa
# Prusa XL"), as does Prusa's full product name typed as the model ("Prusa Original Prusa MK4S"). Its
# text fields drop a typed "." ("Prusa MK39S"). And a name copied from PrusaSlicer or the firmware
# has the vendor "Prusa Research" and a model id that runs together ("MK4SMMU3", "XL5IS", "COREONEL").
BUDDY_PRINTER = re.compile(
    r"""(?:(?:Original\ )?Prusa(?:\ Research)?\ )+
        (?:CORE\ ?One(?:L)?(?:OAK|INDX)?|Signature\ Oak   # the family; the Signature Oak is a CORE One
           |MINI|MK3\.?5|MK3\.?9|MK4|XL(?:[25]|P)?|iX)     # an XL's tool count; "XLP" is the XL+
        (?:IS|S|\+)?(?:MMU3)?                             # input shaper, S or + model, MMU
        (?:[ -].*)?                                       # any variant: HF, L, 5T, INDX 8T
    """,
    re.IGNORECASE | re.VERBOSE,
)
SUPPORTED_PRINTERS = "Prusa MINI, MK3.5, MK3.9, MK4, XL, CORE One or iX"
# What can hand the export G-code that is already binary.
CONVERTED_EARLIER = "A post-processing script or plugin that runs before this one already converted the G-code."

BGCODE_MAGIC = b"GCDE"
# Version 1 is the only one libbgcode defines. gcode-lib 1.2.2 stamps 2, so its header is not reused.
FILE_HEADER = BGCODE_MAGIC + struct.pack("<IH", 1, 1)  # version 1, CRC32 checksums
FILE_HEADER_SIZE = len(FILE_HEADER)
EMPTY_GCODE_BLOCK_SIZE = 14  # write_bgcode("") ends with: 8 header + 2 params + 4 checksum

BLOCK_FILE_METADATA = 0
BLOCK_SLICER_METADATA = 2
BLOCK_PRINTER_METADATA = 3
BLOCK_PRINT_METADATA = 4
COMPRESSION_NONE = 0
COMPRESSION_DEFLATE = 1
ENCODING_INI = 0

# libbgcode's block size. The firmware resumes a print from the start of a block and waits for a
# whole block to arrive, so a single huge block would make it re-read the file from the beginning
# and hold back printing during a Prusa Connect transfer.
GCODE_BLOCK_SIZE = 65536

CONFIG_BEGIN = "; CONFIG_BLOCK_START"
CONFIG_END = "; CONFIG_BLOCK_END"
THUMBNAIL_BEGIN = re.compile(r";\s*thumbnail(?:_\w+)?\s+begin\s", re.IGNORECASE)
THUMBNAIL_END = re.compile(r";\s*thumbnail(?:_\w+)?\s+end\b", re.IGNORECASE)
STATISTIC_SEPARATOR = re.compile(r"[=:]")
GENERATED_BY = re.compile(r";\s*generated by (.+?) on (.+?)\s*$")
PRINTER_CHECK = re.compile(r'M862\.3 P\s*"?([^"\s;]+)')

# Printer metadata key -> the Orca config key holding the same value.
PRINTER_CONFIG_KEYS = {
    "filament_type": "filament_type",
    "nozzle_diameter": "nozzle_diameter",
    "brim_width": "brim_width",
    "fill_density": "sparse_infill_density",
    "layer_height": "layer_height",
    "temperature": "nozzle_temperature",
    "support_material": "enable_support",
    "extruder_colour": "filament_colour",
}
PRINTER_STATISTICS = (
    "filament used [mm]",
    "filament used [cm3]",
    "filament used [g]",
    "filament cost",
    "estimated printing time (normal mode)",
    "total filament used for wipe tower [g]",
    "total toolchanges",
)
PRINT_STATISTICS = (
    "total toolchanges",
    "filament used [mm]",
    "filament used [cm3]",
    "filament used [g]",
    "filament cost",
    "total filament used [g]",
    "total filament cost",
    "total filament used for wipe tower [g]",
    "estimated printing time (normal mode)",
    "estimated first layer printing time (normal mode)",
)
# PrusaSlicer parses the slicer metadata of any .bgcode, whoever produced it, and refuses to open the
# file if it cannot read a value of a setting it also has, such as Orca's ironing_type "no ironing".
# Orca shares 138 setting names with it, not all with the same meaning or values, so only the settings
# its G-code viewer reads and that mean the same in both keep a PrusaSlicer name (PrusaSlicer name ->
# Orca config key). The whole Orca config follows under a prefix, which PrusaSlicer ignores.
SLICER_CONFIG_KEYS = {
    "bed_shape": "bed_shape",
    "extruder_colour": "extruder_colour",
    "filament_colour": "filament_colour",
    "filament_cost": "filament_cost",
    "filament_density": "filament_density",
    "filament_diameter": "filament_diameter",
    "first_layer_height": "first_layer_height",
    "gcode_flavor": "gcode_flavor",
    "machine_max_acceleration_e": "machine_max_acceleration_e",
    "machine_max_acceleration_extruding": "machine_max_acceleration_extruding",
    "machine_max_acceleration_retracting": "machine_max_acceleration_retracting",
    "machine_max_acceleration_travel": "machine_max_acceleration_travel",
    "machine_max_acceleration_x": "machine_max_acceleration_x",
    "machine_max_acceleration_y": "machine_max_acceleration_y",
    "machine_max_acceleration_z": "machine_max_acceleration_z",
    "machine_max_feedrate_e": "machine_max_speed_e",
    "machine_max_feedrate_x": "machine_max_speed_x",
    "machine_max_feedrate_y": "machine_max_speed_y",
    "machine_max_feedrate_z": "machine_max_speed_z",
    "machine_max_jerk_e": "machine_max_jerk_e",
    "machine_max_jerk_x": "machine_max_jerk_x",
    "machine_max_jerk_y": "machine_max_jerk_y",
    "machine_max_jerk_z": "machine_max_jerk_z",
    "max_print_height": "printable_height",
    "nozzle_diameter": "nozzle_diameter",
    "single_extruder_multi_material": "single_extruder_multi_material",
    "z_offset": "z_offset",
}
ORCA_CONFIG_PREFIX = "orca_"
# Orca's bed type -> the config key of its temperature after the first layer, like PrusaSlicer's
# bed_temperature.
BED_TEMPERATURE_KEYS = {
    "Cool Plate": "cool_plate_temp",
    "Engineering Plate": "eng_plate_temp",
    "High Temp Plate": "hot_plate_temp",
    "Textured PEI Plate": "textured_plate_temp",
    "Textured Cool Plate": "textured_cool_plate_temp",
    "Supertack Plate": "supertack_plate_temp",
}
# Orca's spelling of a statistic -> the name the firmware and libbgcode use.
STATISTIC_ALIASES = {"total filament change": "total toolchanges"}
HEADER_HEIGHT = "max_z_height"
KNOWN_STATISTICS = {*PRINTER_STATISTICS, *PRINT_STATISTICS}


def is_bgcode_name(name):
    return name.lower().endswith(BGCODE_EXTENSIONS)


def with_extension(filename_format, extension):
    """filename_format ending in extension, in place of any G-code extension the firmware knows."""
    stem = re.sub(r"\.(?:b?gcode|bgc|gco|gc|g)$", "", filename_format, flags=re.IGNORECASE)
    return (stem or "{input_filename_base}") + extension


def read_sections(path):
    """Yield (section, line) for each line, the section being "gcode", "config" or "thumbnail".

    The config and thumbnail sections consist of comments, so a line of G-code always ends them. A
    missing end marker can then not swallow the print.
    """
    section = "gcode"
    # Universal newlines: a bare CR ends a line as LF and CRLF do, which is how the firmware reads it.
    # The split has to come before the section is chosen, or a command after a CR would stay attached
    # to the comment before it and leave the print with that comment's section. utf-8-sig drops a byte
    # order mark, which would hide a marker on the first line and pass for a command.
    with open(path, encoding="utf-8-sig", errors="replace") as lines:
        for line in lines:
            if section != "gcode" and not line.startswith(";"):
                if not line.strip():
                    continue  # not G-code: a file with CR CR LF line ends has a blank line after every line
                section = "gcode"
            if section == "gcode":
                if line.startswith(CONFIG_BEGIN):
                    section = "config"
                elif THUMBNAIL_BEGIN.match(line):
                    section = "thumbnail"
            elif section == "config" and line.startswith(CONFIG_END):
                section = "gcode"
                continue
            yield section, line
            if section == "thumbnail" and THUMBNAIL_END.match(line):
                section = "gcode"


def parse_statistic(line):
    """(key, value) of a "; key = value" or "; key: value" comment, or None.

    Not a regular expression: user comments are arbitrary, and backtracking on a long run of blanks
    would stall the export with the GIL held.
    """
    separator = STATISTIC_SEPARATOR.search(line)
    if separator is None:
        return None
    return line[1:separator.start()].strip(), line[separator.end():].strip()


def is_command(line):
    """Whether a line of G-code holds anything besides blanks and a comment."""
    return bool(line.partition(";")[0].strip())


def scan_file(path):
    """Everything the metadata blocks need from the text G-code, and whether it has any commands."""
    scan = {
        "config": {},
        "statistics": {},
        "thumbnail_text": [],
        "printer_model": "",
        "producer": "",
        "produced_on": "",
        "has_commands": False,
    }
    for section, line in read_sections(path):
        if section == "config":
            key, separator, value = line[1:].partition("=")
            if separator:
                scan["config"][key.strip()] = value.strip()
        elif section == "thumbnail":
            scan["thumbnail_text"].append(line)
        elif line.startswith("; "):
            # Header values come first, so anything later is custom G-code. The statistics are
            # written last, after any custom G-code.
            if not scan["producer"] and (generated := GENERATED_BY.match(line)):
                scan["producer"], scan["produced_on"] = generated.groups()
            elif statistic := parse_statistic(line):
                key, value = STATISTIC_ALIASES.get(statistic[0], statistic[0]), statistic[1]
                if key == HEADER_HEIGHT:
                    scan["statistics"].setdefault(key, value)
                elif key in KNOWN_STATISTICS:
                    scan["statistics"][key] = value
        else:
            scan["has_commands"] = scan["has_commands"] or is_command(line)
            # The id the firmware itself checks, unlike Orca's printer_model ("Prusa CORE One").
            if not scan["printer_model"] and (check := PRINTER_CHECK.match(line)):
                scan["printer_model"] = check[1]
    return scan


def file_metadata(scan):
    metadata = {"Producer": scan["producer"], "Produced on": scan["produced_on"]}
    return {key: value for key, value in metadata.items() if value}


def printer_metadata(scan):
    config, statistics = scan["config"], scan["statistics"]
    metadata = {"printer_model": scan["printer_model"]}
    metadata.update({key: config.get(source, "") for key, source in PRINTER_CONFIG_KEYS.items()})
    bed_temperature_key = BED_TEMPERATURE_KEYS.get(config.get("curr_bed_type"), "first_layer_bed_temperature")
    metadata["bed_temperature"] = config.get(bed_temperature_key, "")
    if "ironing_type" in config:
        metadata["ironing"] = "0" if config["ironing_type"] == "no ironing" else "1"
    metadata["max_layer_z"] = statistics.get(HEADER_HEIGHT, "")
    metadata.update({key: statistics.get(key, "") for key in PRINTER_STATISTICS})
    return {key: value for key, value in metadata.items() if value}


def print_metadata(scan):
    return {key: scan["statistics"][key] for key in PRINT_STATISTICS if key in scan["statistics"]}


def viewer_nozzle_diameters(config):
    """nozzle_diameter with an entry per filament.

    PrusaSlicer's viewer counts tools by nozzle_diameter and ignores tool changes past that count, but
    a single-nozzle MMU printer has one entry however many filaments it uses.
    """
    nozzles = config["nozzle_diameter"].split(",")
    filaments = config.get("extruder_colour", "").count(";") + 1
    return ",".join(nozzles + nozzles[-1:] * (filaments - len(nozzles)))


def slicer_metadata(scan):
    config = scan["config"]
    metadata = {key: config[source] for key, source in SLICER_CONFIG_KEYS.items() if source in config}
    if "nozzle_diameter" in metadata:
        metadata["nozzle_diameter"] = viewer_nozzle_diameters(config)
    metadata.update({ORCA_CONFIG_PREFIX + key: value for key, value in config.items()})
    return metadata


def metadata_block(block_type, metadata, deflate=False):
    """A metadata block, deflated like PrusaSlicer's print and slicer metadata.

    The firmware cannot read compressed metadata, but it only reads the printer metadata.
    """
    text = "".join(f"{key}={value}\n" for key, value in metadata.items()).encode("utf-8")
    params = struct.pack("<H", ENCODING_INI)
    if deflate:
        payload = zlib.compress(text)
        header = struct.pack("<HHII", block_type, COMPRESSION_DEFLATE, len(text), len(payload))
    else:
        payload = text
        header = struct.pack("<HHI", block_type, COMPRESSION_NONE, len(text))
    body = header + params + payload
    return body + struct.pack("<I", zlib.crc32(body))


def thumbnail_blocks(thumbnail_text):
    thumbnails = gl.from_text("".join(thumbnail_text)).thumbnails
    return gl.write_bgcode("", thumbnails)[FILE_HEADER_SIZE:-EMPTY_GCODE_BLOCK_SIZE]


def gcode_block(text):
    return gl.write_bgcode(text, compress=True)[FILE_HEADER_SIZE:]


def gcode_blocks(path):
    """The file's G-code as blocks of at most GCODE_BLOCK_SIZE bytes, each ending on a whole line."""
    pending, size = [], 0
    for section, line in read_sections(path):
        if section != "gcode":
            continue
        length = len(line.encode("utf-8"))
        if pending and size + length > GCODE_BLOCK_SIZE:
            yield gcode_block("".join(pending))
            pending, size = [], 0
        pending.append(line)
        size += length
    if pending:
        yield gcode_block("".join(pending))


class NothingToPrint(Exception):
    """The G-code has no commands, so there is nothing to print.

    Without any G-code line, its .bgcode would also lack the G-code block every reader requires.
    """


def write_bgcode_file(source, target):
    scan = scan_file(source)
    if not scan["has_commands"]:
        raise NothingToPrint
    with open(target, "wb") as out:
        # The specification's block order.
        out.write(FILE_HEADER)
        out.write(metadata_block(BLOCK_FILE_METADATA, file_metadata(scan)))
        out.write(metadata_block(BLOCK_PRINTER_METADATA, printer_metadata(scan)))
        out.write(thumbnail_blocks(scan["thumbnail_text"]))
        out.write(metadata_block(BLOCK_PRINT_METADATA, print_metadata(scan), deflate=True))
        out.write(metadata_block(BLOCK_SLICER_METADATA, slicer_metadata(scan), deflate=True))
        for block in gcode_blocks(source):
            out.write(block)


def is_bgcode_file(path):
    with open(path, "rb") as file:
        return file.read(len(BGCODE_MAGIC)) == BGCODE_MAGIC


def convert_in_place(path):
    """Replace the text G-code at path with .bgcode. A failure leaves the original untouched.

    Raises NothingToPrint for G-code without commands, such as an empty file.
    """
    temporary = path + ".bgcode.tmp"
    try:
        write_bgcode_file(path, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def split_strings(serialized):
    """The items of a serialized strings option, kept serialized so the toggle cannot alter them."""
    items = re.findall(r'"(?:[^"\\]|\\.)*"|[^;]+', serialized or "")
    return [item for item in items if item != '""']


def supports_bgcode(printer_model):
    """Whether Orca's printer_model names a printer that runs Prusa's Buddy firmware."""
    return bool(printer_model) and BUDDY_PRINTER.fullmatch(printer_model) is not None


def unsupported_message(printer_model):
    printer = f'The printer model "{printer_model}"' if printer_model else "This printer"
    return f"Binary G-code needs a {SUPPORTED_PRINTERS}. {printer} is not recognised as one."


def capability_names(manifest):
    """The capability each "plugin;uuid;capability" entry of a serialized plugin list refers to."""
    names = []
    for entry in split_strings(manifest):
        # The host quotes an entry, which holds semicolons, and takes it for a reference only when it
        # has all three parts and names a plugin and a capability. Escapes are left in: no name with
        # one can equal the export's.
        parts = (entry[1:-1] if entry.startswith('"') else entry).split(";", 2)
        if len(parts) == 3 and parts[0] and parts[2]:
            names.append(parts[2])
    return names


def hides_export(printer_preset):
    """Whether the printer preset's own plugin list would keep the host from finding the export.

    The host looks a selected capability up in the "plugins" list of the full config, where a printer
    preset's list replaces the process preset's. A printer preset has none when it is loaded. Changing
    its Printer Agent setting gives it one, often empty, that lasts until OrcaSlicer restarts and never
    names the export. OrcaSlicer 2.5.1 then finds the capability by name. 2.5.0 and earlier, and
    nightly builds without that fix, skip it without an error. Nothing tells a script which host it
    runs in.
    """
    manifest = printer_preset.config_value("plugins")
    return manifest is not None and EXPORT_NAME not in capability_names(manifest)


def accepts_skipped_conversion(printer_name):
    """Ask before turning the feature on where the host may skip the conversion. True to turn it on.

    Yes is the safe answer because the host gives that button the focus, so Enter never turns the
    feature on. Closing the box answers "cancel", which is taken the same way.
    """
    answer = orca.host.ui.message(
        f'The printer preset "{printer_name}" carries a plugin list of its own, which a change to its '
        "Printer Agent setting leaves behind until OrcaSlicer restarts. OrcaSlicer 2.5.1 runs the "
        "conversion all the same. Earlier versions, and some nightly builds, use that list in place of the "
        f"process preset's: they skip the conversion and save text G-code under a {BGCODE_EXTENSION} name, "
        "which the printer cannot read.\n\n"
        "Keep binary G-code off for now?\n"
        f'Yes: it stays off. Restart OrcaSlicer, then run "{TOGGLE_NAME}" again.\n'
        "No: turn it on now, which is only safe in OrcaSlicer 2.5.1 or later.",
        TOGGLE_NAME,
        "yes_no",
        "warning",
    )
    return answer == "no"


def notify(level, text):
    orca.host.ui.push_notification(level, text)


def failure(message):
    """A failed export. The host shows the message and keeps the destination from being written."""
    return orca.ExecutionResult.failure(orca.PluginResult.RecoverableError, message)


class PrusaBinaryGCodeExport(orca.slicing.SlicingPipelineCapabilityBase):
    def get_name(self):
        return EXPORT_NAME

    def execute(self, ctx):
        if ctx.step != orca.slicing.Step.psGCodePostProcess:
            return orca.ExecutionResult.success()
        # The host runs the preset's post-processing scripts, then the plugins selected before this one,
        # and any of them may already have written binary G-code. The host saves whatever this step
        # leaves, so the destination is checked even when there is nothing left to convert.
        already_binary = is_bgcode_file(ctx.gcode_path)
        name = os.path.basename(ctx.output_name)
        if name.lower().endswith(".3mf"):
            if already_binary:
                return failure(
                    f'"{name}" stores its G-code as text. {CONVERTED_EARLIER} Remove that step to save a 3MF.'
                )
            return orca.ExecutionResult.skipped("G-code inside a 3MF stays text.")
        printer_model = ctx.config_value("printer_model")
        if not supports_bgcode(printer_model):
            # With the feature on for such a printer every export stops here, so say how to go on.
            if already_binary:
                return failure(f"{unsupported_message(printer_model)} {CONVERTED_EARLIER} Remove that step.")
            return failure(f'{unsupported_message(printer_model)} Run "{TOGGLE_NAME}" to turn the feature off.')
        if not is_bgcode_name(name):
            # Binary content under a .gcode name would be read as text by the firmware.
            if already_binary:
                return failure(
                    f'"{name}" does not end in {BGCODE_EXTENSION}. {CONVERTED_EARLIER} '
                    f"Name the file {BGCODE_EXTENSION}, or remove that step."
                )
            return failure(
                f'"{name}" does not end in {BGCODE_EXTENSION}, so it cannot hold binary G-code. '
                f'Name it {BGCODE_EXTENSION}, or run "{TOGGLE_NAME}" to turn the feature off.'
            )
        if already_binary:
            return orca.ExecutionResult.skipped("G-code is already binary.")
        try:
            convert_in_place(ctx.gcode_path)
        except NothingToPrint:
            return failure(
                "The G-code has no commands, so there is nothing to convert. Slice again, and check any "
                "post-processing script or plugin that runs before this one."
            )
        return orca.ExecutionResult.success(f"Converted {ctx.output_name} ({ctx.host}) to binary G-code.")


class TogglePrusaBinaryGCode(orca.script.ScriptPluginCapabilityBase):
    def get_name(self):
        return TOGGLE_NAME

    def execute(self):
        bundle = orca.host.preset_bundle()
        preset = bundle.prints.edited_preset()
        filename_format = preset.config_value("filename_format") or ""
        plugins = split_strings(preset.config_value("slicing_pipeline_plugin"))
        advice = "Save the preset to keep this setting."

        turn_on = SERIALIZED_EXPORT_NAME not in plugins
        if turn_on:
            printer_model = bundle.full_config_value("printer_model")
            printer = bundle.printers.edited_preset()
            if not supports_bgcode(printer_model):
                advice = unsupported_message(printer_model)
                if not is_bgcode_name(filename_format):
                    notify(orca.host.ui.NotificationLevel.WarningNotificationLevel, advice)
                    return orca.ExecutionResult.skipped(advice)
                turn_on = False
            elif hides_export(printer) and not accepts_skipped_conversion(printer.name):
                advice = (
                    f'Restart OrcaSlicer to clear the plugin list of the printer preset "{printer.name}", '
                    f'then run "{TOGGLE_NAME}" again.'
                )
                if not is_bgcode_name(filename_format):
                    return orca.ExecutionResult.skipped(f"Binary G-code stays off. {advice}")
                turn_on = False
            if not turn_on:
                # The name is binary without the export, as after removing the export by hand. Staying
                # off has to undo the name, or text would go on being saved under it.
                advice = f"Its filename format ended in a binary extension, and now ends in {GCODE_EXTENSION}. {advice}"

        if turn_on:
            plugins.append(SERIALIZED_EXPORT_NAME)
            filename_format, state = with_extension(filename_format, BGCODE_EXTENSION), "on"
        else:
            plugins = [plugin for plugin in plugins if plugin != SERIALIZED_EXPORT_NAME]
            filename_format, state = with_extension(filename_format, GCODE_EXTENSION), "off"

        transaction = orca.host.preset.process.begin_update()
        transaction.set("slicing_pipeline_plugin", ";".join(plugins))
        transaction.set("filename_format", filename_format)
        result = transaction.commit()

        message = f'Binary G-code is {state} for "{result.target_name}". {advice}'
        notify(orca.host.ui.NotificationLevel.RegularNotificationLevel, message)
        return orca.ExecutionResult.success(message)


@orca.plugin
class PrusaBinaryGCodePackage(orca.base):
    def register_capabilities(self):
        orca.register_capability(PrusaBinaryGCodeExport)
        orca.register_capability(TogglePrusaBinaryGCode)
