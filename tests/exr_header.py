"""A minimal OpenEXR header reader, with no third-party dependencies.

Used by the integration tests to check what Blender *actually wrote*, rather
than what the RNA properties claimed. That distinction is not academic: the
File Output node reports a 16-bit ZIP item format while writing 32-bit
uncompressed files, because depth and codec are taken from the node format.

Only the header is parsed; pixel data is never touched.
"""

import struct
from dataclasses import dataclass

EXR_MAGIC = 20000630

_PIXEL_TYPES = {0: "UINT", 1: "HALF", 2: "FLOAT"}
_COMPRESSION = {
    0: "NONE",
    1: "RLE",
    2: "ZIPS",
    3: "ZIP",
    4: "PIZ",
    5: "PXR24",
    6: "B44",
    7: "B44A",
    8: "DWAA",
    9: "DWAB",
}


@dataclass(frozen=True)
class ExrHeader:
    channels: tuple
    """``(name, pixel_type)`` pairs, sorted by name."""

    compression: str
    multipart: bool

    @property
    def channel_names(self):
        return tuple(name for name, _ in self.channels)

    @property
    def pixel_types(self):
        return {ptype for _, ptype in self.channels}

    @property
    def layer_prefixes(self):
        """Layer names implied by dotted channel names, e.g. ``beauty.R``."""
        return tuple(sorted({n.rsplit(".", 1)[0] for n in self.channel_names if "." in n}))


def _read_cstr(buf, index):
    end = buf.index(b"\x00", index)
    return buf[index:end].decode("utf-8", "replace"), end + 1


def read_header(path):
    """Parse the header of the EXR at ``path``."""
    with open(path, "rb") as handle:
        buf = handle.read(65536)

    magic, version = struct.unpack_from("<ii", buf, 0)
    if magic != EXR_MAGIC:
        raise ValueError(f"{path} is not an OpenEXR file")

    index = 8
    attributes = {}
    while True:
        name, index = _read_cstr(buf, index)
        if not name:
            break
        _type, index = _read_cstr(buf, index)
        (size,) = struct.unpack_from("<i", buf, index)
        index += 4
        attributes[name] = buf[index : index + size]
        index += size

    channels = []
    data = attributes.get("channels", b"")
    pos = 0
    while pos < len(data) and data[pos] != 0:
        name, pos = _read_cstr(data, pos)
        (ptype,) = struct.unpack_from("<i", data, pos)
        pos += 16  # pixel type, pLinear + 3 reserved, xSampling, ySampling
        channels.append((name, _PIXEL_TYPES.get(ptype, str(ptype))))

    raw_compression = attributes.get("compression", b"\xff")[0]
    return ExrHeader(
        channels=tuple(sorted(channels)),
        compression=_COMPRESSION.get(raw_compression, str(raw_compression)),
        multipart=bool(version & 0x1000),
    )
