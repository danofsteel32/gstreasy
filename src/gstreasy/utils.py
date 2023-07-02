"""Utility Classes and functions."""
import queue
import typing
from contextlib import contextmanager
from fractions import Fraction

import attrs
import gi
import numpy as np

from .wrapped_caps import WrappedCaps

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")

from gi.repository import GLib, Gst, GstVideo, GstAudio  # noqa: E402

Framerate = typing.Union[int, Fraction, str]


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


def make_video_caps(
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
        arr = np.ndarray(
            mapped.size // caps.dtype.itemsize, buffer=mapped.data, dtype=caps.dtype
        )
        arr = arr.reshape(caps.shape)

    return arr.squeeze()
