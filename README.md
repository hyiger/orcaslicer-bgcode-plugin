# Prusa Binary G-code for OrcaSlicer

Compresses OrcaSlicer's G-code to Prusa `.bgcode` so uploads to the printer take less time. Files are
about 60% smaller than the text G-code, whether you save to a file or upload to PrusaLink or Prusa
Connect. Requires OrcaSlicer 2.5.0-rc or later. OrcaSlicer installs
[gcode-lib](https://github.com/hyiger/gcode-lib) 1.8.0 and `heatshrink2` on first load.

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

MINI, MK3.5, MK3.9, MK4, XL, CORE One and iX printers are supported, in every variant: S, +, IS, HF,
L, MMU3, INDX and multi-tool. Their firmware reads the format from version 5.1.0. The toggle and the
export both refuse every other printer. That includes the MK3S, MK3, MK2.5 and older, whose 8-bit
firmware cannot read the format, and printers from other vendors.

A custom printer is recognised by the vendor and model it was given in **Create Printer**, which
OrcaSlicer joins into one name and does not let you change afterwards. Renaming the preset has no
effect on it. A printer picked from that dialog's Prusa list is recognised, apart from the MK3S,
which cannot read the format. For one you type in, use the vendor `Prusa` and the model as Prusa
writes it, such as `MK3.9S`. The dialog drops a typed `.`, so `MK39S` is recognised too. If the
export refuses a printer that can read the format, run the toggle to turn the feature off for it.

### Good to know

- **Always use the toggle to change the feature, and turn it off before disabling or uninstalling
  the plugin.** If the conversion does not run while the filename format still ends in `.bgcode`,
  the result is a text file the printer cannot read, with no error, because the plugin is not there
  to report one. This happens if the plugin is disabled or uninstalled, or if you remove the export
  from Slicing Pipeline Plugin or revert only one of the two settings by hand. If this happens, run
  the toggle once to bring them back in step.
- **A printer preset with its own plugin list can cause the same problem.** Changing a printer
  preset's Printer Agent setting leaves a `plugins` entry on it until OrcaSlicer restarts, and that
  entry replaces the process preset's list. OrcaSlicer 2.5.1 still finds the conversion by name.
  OrcaSlicer 2.5.0 and earlier, and nightly builds without that fix, skip it. The toggle cannot tell
  which OrcaSlicer it runs in, so for such a printer preset it explains this and asks whether to
  keep the feature off. **Yes**, the safe answer, keeps it off until you have restarted OrcaSlicer
  and run the toggle again. If the filename format already ended in `.bgcode`, it is set back to
  `.gcode`. **No** turns the feature on at once. The toggle cannot notice a Printer Agent change
  made while the feature is already on. On those older versions, restart OrcaSlicer after such a
  change, and check that a saved `.bgcode` file starts with `GCDE`. Turning the feature off never
  asks, and the toggle never changes the printer preset.
- **The commands stay the same, but the text does not.** `G` commands made only of uppercase words
  lose their spaces and any comment after the command, blank lines are dropped, and CRLF or CR line
  endings become LF. Other lines stay as written.
- **Do not import settings from a `.bgcode` into PrusaSlicer.** It would take only the few settings it
  shares with this file and use its defaults for the rest. Use the file to view or print.
- If you rename the output to `.gcode` in the save or upload dialog, the export fails with an
  explanation, since binary content under that name would not print.
- **Post-processing scripts, and plugins listed before the export in Slicing Pipeline Plugin, run
  first, and their result is checked.** If one of them already wrote binary G-code, the export
  leaves it as it is for a `.bgcode` name on a supported printer, and fails for a `.gcode` name, a
  3MF or any other printer. If one of them left a file with no commands, the export fails instead
  of writing a `.bgcode` with nothing to print. Two cases are out of its reach:
  - A plugin you add after turning the feature on is listed after the export, so it is handed the
    binary file and nothing checks what it leaves. Run the toggle off and on again to move the export
    back to the end of the list.
  - The export knows the destination only by the name OrcaSlicer gives it. If a script renames the
    output to `.bgcode` while a `.gcode.3mf` is being written, OrcaSlicer passes on that name but
    still packs the file into the 3MF, so binary G-code ends up inside it without an error.
- **G-code inside a `.gcode.3mf` stays text.** OrcaSlicer stores it in the bundle under a `.gcode`
  name, so *Export plate sliced file* keeps working with the feature on.
- Turning the feature off always gives a `.gcode` extension, even if the filename format used `.gco`,
  `.gc` or `.g` before.
- The G-code preview in OrcaSlicer is unaffected. It always shows the text G-code from before the
  conversion.

## What the plugin adds to gcode-lib

gcode-lib compresses the G-code with the settings PrusaSlicer uses: Heatshrink 12/4 over MeatPack,
keeping comments, in blocks of 64 KiB of text. `heatshrink2` is what makes this worthwhile, because
conversion time counts against what the smaller file saves. Its C encoder takes about 0.03 s per MB
of G-code. gcode-lib's pure-Python fallback takes about 0.9 s, which would cancel the saving on a fast
connection.

Prusa's format asks for more than `gcode_lib.write_bgcode()` provides, so the plugin adds it:

| | `write_bgcode()` | This plugin |
| --- | --- | --- |
| File header version | 2, which libbgcode rejects when it enforces the version | 1 |
| Printer, print and slicer metadata | absent, though the specification requires them | present, with print and slicer metadata deflated as in PrusaSlicer |
| File metadata (producer) | absent | present |
| Slicer settings | absent | safe for other tools to read |

PrusaSlicer reads the slicer metadata of every `.bgcode` and refuses to open the file if it cannot
parse a value of a setting it also has, such as Orca's `ironing_type = no ironing`. So the settings
its G-code viewer needs are written under their PrusaSlicer names, and the whole Orca config follows
with an `orca_` prefix, which it ignores.

Printer metadata uses the `M862.3` printer id from the G-code, such as `COREONE`, because that is
what the firmware checks. Orca's own `printer_model` value is a display name, such as
`Prusa CORE One`.

The file is streamed rather than loaded with `gcode_lib.load()`, which took about 1.1 GB of memory
on a 40 MB file. Streaming peaks at about 31 MB.

## Development

```bash
python -m venv .venv
.venv/bin/pip install gcode-lib==1.8.0 heatshrink2==0.15.0 pytest pytest-cov
.venv/bin/python -m pytest
```

`pytest` fails below 100% line and branch coverage, and if the output stops being substantially smaller
than the text G-code. Tests run against the real gcode-lib and a stand-in
for OrcaSlicer's `orca` module, with two real files sliced by OrcaSlicer 2.5.0-rc in
`tests/fixtures/`: one from the command line, and one from the GUI that has thumbnails.
`tests/bgcode_reader.py` is a strict reader written from the
[specification](https://github.com/prusa3d/libbgcode/blob/main/doc/specifications.md) that shares no
constants with the plugin.

GitHub runs the same suite on every pull request and push to `main`, through
`.github/workflows/test.yml`. It uses Python 3.12, which OrcaSlicer bundles, and installs the
dependencies at the versions pinned in the plugin's header.

## Publishing

Each GitHub release publishes `orca_bgcode_plugin_any.py` to the plugin's Orca Cloud listing, through `.github/workflows/publish-orcacloud.yml`, which follows [Orca Cloud's guide](https://cloud.orcaslicer.com/wiki/). The repository must first be connected to the listing, in its **Edit plugin** > **GitHub publishing**.

1. Raise `version` in the plugin's header and push.
2. Create a release whose tag is that version with a `v`, such as `v1.2.0`. Orca Cloud needs it higher than the listing's current version. The release notes become the changelog.

The workflow runs the test suite on the tagged revision first. It stops without publishing if a test
fails or the tag is not the header's version.

## Testing in OrcaSlicer

The unit tests cannot reach the steps below, which need the running app or a printer. Slice a model
with the feature on for each:

- [ ] Run the toggle. The filename format ends in `.bgcode` and the Slicing Pipeline Plugin lists the
      export. Run it again and both are restored.
- [ ] **Export G-code file.** The save dialog proposes `.bgcode` and the saved file starts with `GCDE`.
- [ ] Open that file in PrusaSlicer's G-code viewer. It loads and shows the toolpaths on the right bed.
- [ ] Rename to `.gcode` in that dialog. The export fails with the explanatory message.
- [ ] **Send to PrusaLink**, with and without *Upload and Print*. The printer lists the file with its
      thumbnail, print time and filament, and it prints.
- [ ] **Send to Prusa Connect.** Connect accepts the file and shows the same details.
- [ ] **Export plate sliced file.** The `.gcode.3mf` is written, with text G-code inside.
- [ ] Toggle off and export. The result is ordinary `.gcode`.
- [ ] Change the printer preset's Printer Agent setting, then run the toggle with the feature off. A
      message box names the printer preset and asks whether to keep the feature off. **Yes**, which
      has the focus, and closing the box leave the process preset unchanged. **No** turns the feature
      on, and running the toggle again turns it off without asking.
- [ ] In **Create Printer**, pick vendor `Prusa` and model `Prusa CORE One`, and run the toggle. It
      turns the feature on. Do the same with a typed model `MK3`. It refuses.
- [ ] Resume a print after a power panic, which reads the file by block.
