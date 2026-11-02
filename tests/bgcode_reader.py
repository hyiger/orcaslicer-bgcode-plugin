"""A strict .bgcode reader written from libbgcode's specification.

It deliberately shares nothing with the plugin, so a mistake in the plugin's format constants fails
here instead of being confirmed by them.
"""
import struct
import zlib
from dataclasses import dataclass, field

FILE_METADATA, GCODE, SLICER_METADATA, PRINTER_METADATA, PRINT_METADATA, THUMBNAIL = range(6)
# Each block type's place in the order the specification requires.
SEQUENCE = {FILE_METADATA: 0, PRINTER_METADATA: 1, THUMBNAIL: 2, PRINT_METADATA: 3, SLICER_METADATA: 4, GCODE: 5}
REQUIRED = {PRINTER_METADATA, PRINT_METADATA, SLICER_METADATA, GCODE}


@dataclass
class Block:
    type: int
    params: bytes
    payload: bytes


@dataclass
class BgcodeFile:
    version: int
    blocks: list = field(default_factory=list)

    def of_type(self, block_type):
        return [block for block in self.blocks if block.type == block_type]

    def metadata(self, block_type):
        """A metadata block as a dict. INI lines are key=value, and a value may itself contain '='."""
        text = self.of_type(block_type)[0].payload.decode("utf-8")
        return dict(line.split("=", 1) for line in text.splitlines())

    @property
    def gcode(self):
        return "".join(block.payload.decode("utf-8") for block in self.of_type(GCODE))


def parse(data):
    assert data[:4] == b"GCDE", "bad magic"
    version, checksum_type = struct.unpack_from("<IH", data, 4)
    assert version == 1, f"the specification defines version 1, got {version}"
    assert checksum_type == 1, "expected CRC32 checksums"

    parsed = BgcodeFile(version)
    position, last_place = 10, -1
    while position < len(data):
        block_type, compression, size = struct.unpack_from("<HHI", data, position)
        assert compression == 0, "the plugin only writes uncompressed blocks"
        assert block_type in SEQUENCE, f"unknown block type {block_type}"
        assert SEQUENCE[block_type] >= last_place, f"block type {block_type} is out of sequence"
        last_place = SEQUENCE[block_type]

        params_size = 6 if block_type == THUMBNAIL else 2
        payload_start = position + 8 + params_size
        payload_end = payload_start + size
        assert payload_end + 4 <= len(data), "truncated block"
        stored, = struct.unpack_from("<I", data, payload_end)
        assert stored == zlib.crc32(data[position:payload_end]), f"bad checksum at {position}"

        params = data[position + 8:payload_start]
        if block_type == THUMBNAIL:
            image_format, width, height = struct.unpack("<HHH", params)
            assert image_format in (0, 1, 2), f"unknown thumbnail format {image_format}"
            assert width and height, "thumbnail without a size"
        else:
            encoding, = struct.unpack("<H", params)
            allowed = (0, 1, 2) if block_type == GCODE else (0,)  # metadata is always INI
            assert encoding in allowed, f"block type {block_type} has encoding {encoding}"

        parsed.blocks.append(Block(block_type, params, data[payload_start:payload_end]))
        position = payload_end + 4

    missing = REQUIRED - {block.type for block in parsed.blocks}
    assert not missing, f"required blocks missing: {missing}"
    return parsed


def parse_file(path):
    with open(path, "rb") as file:
        return parse(file.read())
