"""A strict .bgcode reader written from libbgcode's specification.

It deliberately shares nothing with the plugin, so a mistake in the plugin's format constants fails
here instead of being confirmed by them.
"""
import struct
import zlib
from dataclasses import dataclass, field

# The reference decoders, which the plugin does not use.
from gcode_lib._bgcode import _heatshrink_decompress, _meatpack_decode

FILE_METADATA, GCODE, SLICER_METADATA, PRINTER_METADATA, PRINT_METADATA, THUMBNAIL = range(6)
# Each block type's place in the order the specification requires.
SEQUENCE = {FILE_METADATA: 0, PRINTER_METADATA: 1, THUMBNAIL: 2, PRINT_METADATA: 3, SLICER_METADATA: 4, GCODE: 5}
REQUIRED = {PRINTER_METADATA, PRINT_METADATA, SLICER_METADATA, GCODE}
COMPRESSION_NONE, COMPRESSION_DEFLATE, COMPRESSION_HEATSHRINK_11_4, COMPRESSION_HEATSHRINK_12_4 = range(4)
ENCODING_MEATPACK_COMMENTS = 2
# What each block type may use: the firmware reads printer metadata and only streams heatshrink.
ALLOWED_COMPRESSION = {
    FILE_METADATA: (COMPRESSION_NONE,),
    PRINTER_METADATA: (COMPRESSION_NONE,),
    THUMBNAIL: (COMPRESSION_NONE,),
    PRINT_METADATA: (COMPRESSION_DEFLATE,),
    SLICER_METADATA: (COMPRESSION_DEFLATE,),
    GCODE: (COMPRESSION_HEATSHRINK_12_4,),
}


@dataclass
class Block:
    type: int
    params: bytes
    payload: bytes
    compression: int
    stored_size: int
    uncompressed_size: int


@dataclass
class BgcodeFile:
    version: int
    blocks: list = field(default_factory=list)

    def of_type(self, block_type):
        return [block for block in self.blocks if block.type == block_type]

    def metadata(self, block_type):
        """A metadata block as a dict. INI lines are key=value, and a value may itself contain '='."""
        block = self.of_type(block_type)[0]
        payload = zlib.decompress(block.payload) if block.compression == COMPRESSION_DEFLATE else block.payload
        return dict(line.split("=", 1) for line in payload.decode("utf-8").splitlines())

    @property
    def gcode(self):
        """The text of every G-code block, as a printer would read it."""
        text = ""
        for block in self.of_type(GCODE):
            assert struct.unpack("<H", block.params)[0] == ENCODING_MEATPACK_COMMENTS
            text += _meatpack_decode(_heatshrink_decompress(block.payload, 12, 4, block.uncompressed_size))
        return text

    @property
    def commands(self):
        """The G-code without comments, spaces or blank lines, which compression may change."""
        return commands(self.gcode)


def commands(text):
    lines = (line.partition(";")[0].replace(" ", "").strip() for line in text.split("\n"))  # not on a bare CR
    return [line for line in lines if line]


def parse(data):
    assert data[:4] == b"GCDE", "bad magic"
    version, checksum_type = struct.unpack_from("<IH", data, 4)
    assert version == 1, f"the specification defines version 1, got {version}"
    assert checksum_type == 1, "expected CRC32 checksums"

    parsed = BgcodeFile(version)
    position, last_place = 10, -1
    while position < len(data):
        block_type, compression, uncompressed_size = struct.unpack_from("<HHI", data, position)
        assert block_type in SEQUENCE, f"unknown block type {block_type}"
        assert compression in ALLOWED_COMPRESSION[block_type], f"block type {block_type} uses compression {compression}"
        assert SEQUENCE[block_type] >= last_place, f"block type {block_type} is out of sequence"
        last_place = SEQUENCE[block_type]

        header_size = 8 if compression == COMPRESSION_NONE else 12
        size = uncompressed_size if compression == COMPRESSION_NONE else struct.unpack_from("<I", data, position + 8)[0]
        params_size = 6 if block_type == THUMBNAIL else 2
        payload_start = position + header_size + params_size
        payload_end = payload_start + size
        assert payload_end + 4 <= len(data), "truncated block"
        stored, = struct.unpack_from("<I", data, payload_end)
        assert stored == zlib.crc32(data[position:payload_end]), f"bad checksum at {position}"

        params = data[position + header_size:payload_start]
        if block_type == THUMBNAIL:
            image_format, width, height = struct.unpack("<HHH", params)
            assert image_format in (0, 1, 2), f"unknown thumbnail format {image_format}"
            assert width and height, "thumbnail without a size"
        else:
            encoding, = struct.unpack("<H", params)
            allowed = (0, 1, 2) if block_type == GCODE else (0,)  # metadata is always INI
            assert encoding in allowed, f"block type {block_type} has encoding {encoding}"

        parsed.blocks.append(
            Block(block_type, params, data[payload_start:payload_end], compression, size, uncompressed_size)
        )
        position = payload_end + 4

    missing = REQUIRED - {block.type for block in parsed.blocks}
    assert not missing, f"required blocks missing: {missing}"
    return parsed


def parse_file(path):
    with open(path, "rb") as file:
        return parse(file.read())
