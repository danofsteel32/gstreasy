import attrs
import math
from typing import Union, List, Dict
from abc import (
    ABC,
    abstractmethod,
)
from functools import lru_cache

import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("GstAudio", "1.0")

from gi.repository import GLib, Gst, GstVideo, GstAudio  # noqa: E402


@attrs.define(slots=True, frozen=True)
class WrappedCaps(ABC):
    channels: int
    format: Union[GstVideo.VideoFormat, GstAudio.AudioFormat]
    dtype: np.dtype

    @classmethod
    @abstractmethod
    def wrap(cls, caps: Gst.Caps, buf: Gst.Buffer):
        pass

    @property
    @abstractmethod
    def shape(self) -> List[int]:
        pass


@attrs.define(slots=True, frozen=True)
class AudioCaps(WrappedCaps):
    """Wrap `Gst.Caps` to simplify pushing/pulling samples."""

    sampling_frequency: int
    samples_per_channel: int

    @classmethod
    def wrap(cls, caps: Gst.Caps, buf: Gst.Buffer):
        """Transform `Gst.Caps` into `WrappedCaps`."""
        structure = caps.get_structure(0)
        sampling_frequency = structure.get_value("rate")
        format = GstAudio.AudioFormat.from_string(structure.get_value("format"))
        channels = structure.get_value("channels")
        dtype = _get_audio_np_dtype(format)
        samples_per_channel = buf.get_size() // dtype.itemsize // channels
        return cls(
            format=format,
            channels=channels,
            dtype=dtype,
            sampling_frequency=sampling_frequency,
            samples_per_channel=samples_per_channel,
        )

    @property
    def shape(self):
        """Return shape of np.ndarray required to hold buffer with these Caps."""
        return [self.samples_per_channel, self.channels]


@attrs.define(slots=True, frozen=True)
class VideoCaps(WrappedCaps):
    """Wrap `Gst.Caps` to simplify pushing/pulling samples."""

    width: int
    height: int

    @classmethod
    def wrap(cls, caps: Gst.Caps, buf: Gst.Buffer):
        """Transform `Gst.Caps` into `WrappedCaps`."""
        structure = caps.get_structure(0)
        width, height = structure.get_value("width"), structure.get_value("height")
        format = GstVideo.VideoFormat.from_string(structure.get_value("format"))
        channels = get_num_channels(format)
        dtype = _get_video_np_dtype(format)
        return cls(
            width=width, height=height, channels=channels, format=format, dtype=dtype
        )

    @property
    def shape(self):
        """Return shape of np.ndarray required to hold buffer with these Caps."""
        return [self.height, self.width, self.channels]


def _get_audio_np_dtype(fmt: GstAudio.AudioFormat) -> np.dtype:
    dtypes = {
        8: np.dtype(np.int8),
        16: np.dtype(np.int16),
    }
    format_info = GstAudio.AudioFormat.get_info(fmt)
    return dtypes.get(format_info.depth, np.dtype(np.uint8))


def _get_video_np_dtype(fmt: GstVideo.VideoFormat) -> np.dtype:
    dtypes = {
        8: np.dtype(np.uint8),
        16: np.dtype(np.uint16),
    }
    format_info = GstVideo.VideoFormat.get_info(fmt)
    return dtypes.get(format_info.bits, np.dtype(np.uint8))


@lru_cache(1024)
def _format_channels() -> Dict[GstVideo.VideoFormat, int]:
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


def has_flag(value: GstVideo.VideoFormatFlags, flag: GstVideo.VideoFormatFlags) -> bool:
    """Return whether the flag is present in."""
    # in VideoFormatFlags each new value is 1 << 2**{0...8}
    return bool(value & (1 << max(1, math.ceil(math.log2(int(flag))))))
