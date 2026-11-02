# Prusa Binary G-code for OrcaSlicer

Writes OrcaSlicer's G-code out as Prusa `.bgcode`, whether you save it to a file or upload it to
PrusaLink or Prusa Connect. Requires OrcaSlicer 2.5.0-rc or later, and converts with
[gcode-lib](https://github.com/hyiger/gcode-lib) 1.2.2, which OrcaSlicer installs on first load.

## Using it

1. Install `orca_bgcode_plugin_any.py` from OrcaSlicer's Plugins window.
2. Select a Prusa printer and the process preset you want binary G-code for.
3. Run **Toggle Prusa Binary G-code** from the Plugins window. A notification confirms the new state.
4. Save the process preset, or the setting only lasts until you switch presets.

Run the same command to turn it off. It works per process preset, so you can have both kinds.

The toggle changes two settings in the process preset, under **Others**:

- **Filename format** gets the `.bgcode` extension. Prusa firmware chooses how to read a file from its
  extension, and a plugin cannot rename its output, so the name has to come from here.
- **Slicing Pipeline Plugin** gets *Prusa Binary G-code Export*, which does the conversion.

MINI, MK3.5, MK3.9, MK4, MK4S, XL and CORE One printers are supported. The toggle and the export both
refuse the MK3S family, whose firmware cannot read the format, and printers from other vendors.

### Good to know

- **Always use the toggle to change the feature, and turn it off before disabling or uninstalling
  the plugin.** If the conversion does not run while the filename format still ends in `.bgcode`,
  the result is a text file the printer cannot read, with no error, because the plugin is not there
  to report one. This happens if the plugin is disabled or uninstalled, or if you remove the export
  from Slicing Pipeline Plugin or revert only one of the two settings by hand. If this happens, run
  the toggle once to bring them back in step.
- **A printer preset with its own plugin list can cause the same problem.** OrcaSlicer 2.5.0-rc lets
  a `plugins` entry on the printer preset, such as one written by the Printer Agent setting, replace
  the process preset's list, and the conversion is then skipped. Check that a saved `.bgcode` file
  starts with `GCDE` if you use a printer agent.
- **Files are about the same size as `.gcode`.** Blocks are stored uncompressed, because gcode-lib
  has no heatshrink or MeatPack encoder. You get the format's metadata and thumbnails but not its
  smaller files. A cube with five thumbnails went from 279,024 to 271,334 bytes.
- If you rename the output to `.gcode` in the save or upload dialog, the export fails with an
  explanation, since binary content under that name would not print.
- **G-code inside a `.gcode.3mf` stays text.** OrcaSlicer stores it in the bundle under a `.gcode`
  name, so *Export plate sliced file* keeps working with the feature on.
- Turning the feature off always gives a `.gcode` extension, even if the filename format used `.gco`,
  `.gc` or `.g` before.
- The G-code preview in OrcaSlicer is unaffected. It always shows the text G-code from before the
  conversion.

## What the plugin adds to gcode-lib

`gcode_lib.write_bgcode()` 1.2.2 serialises thumbnails and one G-code block. Prusa's format asks for
more, so the plugin provides it:

| | `write_bgcode()` 1.2.2 | This plugin |
| --- | --- | --- |
| File header version | 2, which libbgcode rejects when it enforces the version | 1 |
| Printer, print and slicer metadata | absent, though the specification requires them | present |
| File metadata (producer) | absent | present |
| G-code blocks | one, however large | 64 KiB each, as libbgcode writes them |

Printer metadata uses the `M862.3` printer id from the G-code, such as `COREONE`, because that is
what the firmware checks. Orca's own `printer_model` value is a display name, such as
`Prusa CORE One`.

The file is streamed rather than loaded with `gcode_lib.load()`, which took about 1.1 GB of memory
on a 40 MB file. Streaming peaks at about 31 MB.

## Development

```bash
python -m venv .venv
.venv/bin/pip install gcode-lib==1.2.2 pytest pytest-cov
.venv/bin/python -m pytest
```

`pytest` fails below 100% line and branch coverage. Tests run against the real gcode-lib and a stand-in
for OrcaSlicer's `orca` module, with two real files sliced by OrcaSlicer 2.5.0-rc in
`tests/fixtures/`: one from the command line, and one from the GUI that has thumbnails.
`tests/bgcode_reader.py` is a strict reader written from the
[specification](https://github.com/prusa3d/libbgcode/blob/main/doc/specifications.md) that shares no
constants with the plugin.

## Testing in OrcaSlicer

The unit tests cannot reach the steps below, which need the running app or a printer. Slice a model
with the feature on for each:

- [ ] Run the toggle. The filename format ends in `.bgcode` and the Slicing Pipeline Plugin lists the
      export. Run it again and both are restored.
- [ ] **Export G-code file.** The save dialog proposes `.bgcode` and the saved file starts with `GCDE`.
- [ ] Rename to `.gcode` in that dialog. The export fails with the explanatory message.
- [ ] **Send to PrusaLink**, with and without *Upload and Print*. The printer lists the file with its
      thumbnail, print time and filament, and it prints.
- [ ] **Send to Prusa Connect.** Connect accepts the file and shows the same details.
- [ ] **Export plate sliced file.** The `.gcode.3mf` is written, with text G-code inside.
- [ ] Toggle off and export. The result is ordinary `.gcode`.
- [ ] Resume a print after a power panic, which reads the file by block.
