"""Utility Classes and functions."""
import math
import queue
import typing
from contextlib import contextmanager
from fractions import Fraction
from functools import lru_cache

import attrs
import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import GLib, Gst, GstVideo  # noqa: E402

BITS_PER_BYTE = 8


Framerate = typing.Union[int, Fraction, str]


@attrs.define(slots=True, frozen=True)
class WrappedCaps:
    """Wrap `Gst.Caps` to simplify pushing/pulling samples."""

    width: int
    height: int
    channels: int
    format: GstVideo.VideoFormat
    dtype: np.dtype
    bpp: int

    @classmethod
    def wrap(cls, caps: Gst.Caps):
        """Transform `Gst.Caps` into `WrappedCaps`."""
        structure = caps.get_structure(0)
        width, height = structure.get_value("width"), structure.get_value("height")
        format = GstVideo.VideoFormat.from_string(structure.get_value("format"))
        channels = get_num_channels(format)
        dtype = _get_np_dtype(format)
        bpp = GstVideo.VideoFormat.get_info(format).bits // BITS_PER_BYTE
        return cls(width, height, channels, format, dtype, bpp)

    @property
    def shape(self) -> typing.Tuple[int, int, int]:
        """Return shape of np.ndarray required to hold buffer with these Caps."""
        return self.height, self.width, self.channels


@attrs.define(slots=True, frozen=True)
class GstBuffer:
    """Use np.ndarray as backing for buffer."""

    data: np.ndarray
    pts: int = GLib.MAXUINT64
    dts: int = GLib.MAXUINT64
    offset: int = GLib.MAXUINT64
    duration: int = GLib.MAXUINT64


class LeakyQueue(queue.Queue):
    """Mimics behavior of gstreamer `queue leaky=2`.

    Oldest buffers are dropped if queue at maxsize.

    Args:
        maxsize (int): Maximum number of buffers to hold before dropping.

    Attributes:
        dropped (int): Total number of dropped buffers.
    """

    def __init__(
        self,
        maxsize: int = 100,
    ):
        """Initialize the Queue."""
        super().__init__(maxsize=maxsize)
        self.dropped: int = 0

    def put(self, item, block=True, timeout=None):
        """Insert new item into queue. Drop oldest item if full."""
        if self.full():
            self.get_nowait()
            self.dropped += 1
        super().put(item, block, timeout)


def make_caps(
    width: int, height: int, framerate: Framerate, format: str
) -> Gst.Caps:
    """Return Gst.Caps built from arguments."""
    framerate = str(Fraction(framerate))
    if "/" not in framerate:
        framerate = framerate + "/1"
    video_format = GstVideo.VideoFormat.from_string(format)
    if not video_format:
        raise ValueError("caps format %s" % format)
    caps_str = (
        f"video/x-raw,width={width},height={height},"
        f"framerate={framerate},format={format}"
    )
    caps = Gst.Caps.from_string(caps_str)
    if not caps:
        raise ValueError("Could not create Gst.Caps")
    return caps


def has_flag(value: GstVideo.VideoFormatFlags, flag: GstVideo.VideoFormatFlags) -> bool:
    """Return whether the flag is present in."""
    # in VideoFormatFlags each new value is 1 << 2**{0...8}
    return bool(value & (1 << max(1, math.ceil(math.log2(int(flag))))))


def _get_num_channels(fmt: GstVideo.VideoFormat) -> int:
    frmt_info = GstVideo.VideoFormat.get_info(fmt)

    # temporal fix
    if fmt == GstVideo.VideoFormat.BGRX:
        return 4
    if has_flag(frmt_info.flags, GstVideo.VideoFormatFlags.ALPHA):
        return 4
    if has_flag(frmt_info.flags, GstVideo.VideoFormatFlags.RGB):
        return 3
    if has_flag(frmt_info.flags, GstVideo.VideoFormatFlags.GRAY):
        return 1
    return -1


@lru_cache(1024)
def _format_channels() -> typing.Dict[GstVideo.VideoFormat, int]:
    all_formats = [
        GstVideo.VideoFormat.from_string(f.strip())
        for f in GstVideo.VIDEO_FORMATS_ALL.strip("{ }").split(",")
    ]
    format_channels = {}
    for fmt in all_formats:
        channels = _get_num_channels(fmt)
        format_channels[fmt] = channels
    return format_channels


def get_num_channels(fmt: GstVideo.VideoFormat) -> int:
    """Raise KeyError if not present."""
    return _format_channels()[fmt]


def _get_np_dtype(fmt: GstVideo.VideoFormat) -> np.dtype:
    dtypes = {
        16: np.dtype(np.int16),
    }
    format_info = GstVideo.VideoFormat.get_info(fmt)
    return dtypes.get(format_info.bits, np.dtype(np.uint8))


@contextmanager
def map_gst_buffer(buf: Gst.Buffer, flags: Gst.MapFlags):
    """Map Gst.Buffer with READ or WRITE flags."""
    try:
        mapped, map_info = buf.map(flags)
        # FIXME figure out what should happen if !mapped
        if mapped:
            yield map_info
    finally:
        buf.unmap(map_info)


def caps_from_string(string: str) -> Gst.Caps:
    """Return `Gst.Caps` from string."""
    return Gst.Caps.from_string(string)


def gst_buffer_to_ndarray(buf: Gst.Buffer, caps: WrappedCaps) -> np.ndarray:
    """Return ndarray extracted from Gst.Buffer."""
    arr: np.ndarray
    with map_gst_buffer(buf, Gst.MapFlags.READ) as mapped:
        arr = np.ndarray(caps.shape, buffer=mapped.data, dtype=caps.dtype)
    if caps.channels > 0:
        return arr.squeeze()
    return arr
