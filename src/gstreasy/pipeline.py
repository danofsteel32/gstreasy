"""This module provides the GstPipeline class."""

import logging
import queue
import sys
import threading
import time
import typing
from fractions import Fraction

import gi
import numpy as np

from .utils import GstBuffer, LeakyQueue, gst_buffer_to_ndarray, make_video_caps
from .wrapped_caps import AudioCaps, VideoCaps, WrappedCaps

gi.require_version("Gst", "1.0")
gi.require_version("GstApp", "1.0")
gi.require_version("GstAudio", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, GObject, Gst, GstApp  # noqa: E402

Gst.init(sys.argv)

Framerate = typing.Union[int, Fraction, str]


class AppSink:
    """Wraps `GstApp.AppSink` to simplify extracting samples/buffers.

    Attributes:
        sink (GstApp.AppSink): the appsink element.
        queue (queue.Queue, LeakyQueue): The queue buffers are held in.
    """

    def __init__(self, sink: GstApp.AppSink, leaky: bool, qsize: int):
        """Initialize the AppSink class.

        Args:
            sink (GstApp.AppSink): the appsink element.
            leaky (bool): Whether the appsink should put buffers in a
                leaky Queue (oldest buffers dropped if full) or a
                normal Queue (block on `Queue.put` if full).
            qsize (int): Max number of buffers to keep in the Queue.
        """
        self.sink = sink
        self.sink.connect("new-sample", self._on_buffer, None)
        self.queue: typing.Union[queue.Queue, LeakyQueue]
        self.queue = LeakyQueue(qsize) if leaky else queue.Queue(qsize)
        self._caps: typing.Optional[WrappedCaps] = None
        self._log = logging.getLogger("AppSink")
        self._log.addHandler(logging.NullHandler())

    @property
    def caps(self) -> typing.Optional[WrappedCaps]:
        """`WrappedCaps` being used to map `Gst.Buffer`'s to `np.ndarray.`'s."""
        if self._caps:
            return self._caps

        caps = self.sink.get_caps()
        if not caps:
            self._log.warning("AppSink has no caps. Will check again on first sample")
            return self._caps

        self._caps = WrappedCaps.wrap(caps)
        return self._caps

    def _on_buffer(self, sink: GstApp.AppSink, data: typing.Any) -> Gst.FlowReturn:
        """Callback for 'new-sample' signal."""
        sample = sink.emit("pull-sample")
        if not sample:
            self._log.error("Bad sample: type = %s" % type(sample))
            return Gst.FlowReturn.ERROR

        self._log.debug("Got Sample")
        self.queue.put(self._extract_buffer(sample))
        return Gst.FlowReturn.OK

    def _extract_buffer(self, sample: Gst.Sample) -> typing.Optional[GstBuffer]:
        buffer = sample.get_buffer()

        # Extract the width and height info from the sample's caps
        if not self._caps:
            self._log.debug("Getting caps from first sample")
            try:
                caps = sample.get_caps()
                caps_name = caps.get_structure(0).get_name()
                if "audio" in caps_name:
                    self._caps = AudioCaps.wrap(caps, buffer)
                elif "video" in caps_name:
                    self._caps = VideoCaps.wrap(caps, buffer)
                else:
                    raise ValueError("Unsupported Caps!")
            except AttributeError:
                return None

        # Use the cached Caps so don't have to re-calc every sample
        if self._caps:
            array = gst_buffer_to_ndarray(buffer, self._caps)
            return GstBuffer(
                data=array,
                pts=buffer.pts,
                dts=buffer.dts,
                duration=buffer.duration,
                offset=buffer.offset,
            )
        return None

    @property
    def queue_size(self) -> int:
        """Return number of buffers in the `queue`."""
        return self.queue.qsize()


class AppSrc:
    """Wraps `GstApp.AppSrc` to simplify inserting samples/buffers.

    Attributes:
        src (GstApp.AppSrc): the appsrc element.
    """

    def __init__(self, src: GstApp.AppSrc):
        """Initialize the AppSrc class.

        Args:
            src (GstApp.AppSrc): the appsrc element.
        """
        self.src = src
        self._caps: typing.Optional[Gst.Caps] = src.get_caps()

        self.pts: typing.Union[int, float] = 0
        self.dts: int = GLib.MAXUINT64

        self._log = logging.getLogger("AppSrc")
        self._log.addHandler(logging.NullHandler())

        self._duration: typing.Union[int, float] = 0

    @property
    def duration(self) -> typing.Union[int, float]:
        """This is not well understood."""
        if not self._duration:
            self._duration = self._calc_duration()
        return self._duration

    def _calc_duration(self) -> typing.Union[int, float]:
        """Return duration estimate based on the framerate of the src Caps."""
        duration: typing.Union[int, float] = 0
        if not self.caps:
            return duration
        caps_string = self.caps.to_string()
        fps = caps_string.split("(fraction)")[1].split(",")[0]
        if fps:
            framerate = Fraction(fps)
            duration = 10**9 / (framerate.numerator / framerate.denominator)
        return duration

    @property
    def caps(self) -> typing.Optional[Gst.Caps]:
        """Return the `Gst.Caps` being set on pushed samples."""
        return self._caps

    @caps.setter
    def caps(self, new_caps: Gst.Caps):
        self._caps = new_caps

    def push(self, data: np.ndarray):
        """Create a `Gst.Sample` from `np.ndarray` and push it into the pipeline."""
        self.pts += self.duration
        offset = self.pts / self.duration
        gst_buffer = Gst.Buffer.new_wrapped(bytes(data))
        gst_buffer.pts = self.pts
        gst_buffer.dts = self.dts
        gst_buffer.offset = offset
        gst_buffer.duration = self.duration
        sample = Gst.Sample.new(buffer=gst_buffer, caps=self.caps)
        self._log.debug("Push Sample")
        self.src.emit("push-sample", sample)


class GstPipeline:
    """A Simple and efficient interface for running GStreamer Pipelines.

    Designed to be used as a ContextManager, GstPipeline takes care of the setup
    and teardown of the GLib.MainLoop thread to handle messages from the event bus.
    Any appsink or appsrc elements present in the provided command are automatically
    configured. You can `pull` buffers from an `appsink` and `push` buffers to
    an `appsrc`.

    The attributes `pipeline`, `bus`, and `elements` are uninitialized until
    `startup` is called manually or upon entering the context manager.
    """

    def __init__(
        self,
        command: str,
        leaky: bool = False,
        qsize: int = 100,
    ):
        """Create a `GstPipeline` but don't start it yet.

        Args:
            command (str): A pipeline definition that can be run by gst-launch-1.0.
            leaky (bool): Whether the appsink should put buffers in a
                leaky Queue (oldest buffers dropped if full) or a
                normal Queue (block on `Queue.put` if full).
            qsize (int): Max number of buffers to keep in the Queue.
        """
        self.command = command
        self.leaky = leaky
        self.qsize = qsize

        self.pipeline: typing.Optional[Gst.Pipeline] = None
        """The actual Pipeline created by calling
            [`Gst.parse_launch`](https://lazka.github.io/pgi-docs/index.html#Gst-1.0/functions.html#Gst.parse_launch)
            on the provided `command`. Defaults to `None`."""

        self.bus: typing.Optional[Gst.Bus] = None
        """The message bus attached to `pipeline`. Defaults to `None`."""

        self.elements: typing.List[Gst.Element] = []
        """A list of all `Gst.Element`'s in the `pipeline`."""

        self._main_loop = GLib.MainLoop.new(None, is_running=False)
        self._main_loop_thread = threading.Thread(
            target=self._main_loop_run, name="MainLoop"
        )
        self._end_stream_event = threading.Event()

        self._appsink: typing.Optional[AppSink] = None
        self._appsrc: typing.Optional[AppSrc] = None

        self._log = logging.getLogger("GstPipeline")
        self._log.addHandler(logging.NullHandler())

    def __bool__(self) -> bool:
        """Return whether or not pipeline is active or there are buffers to process."""
        if self.appsink:
            return not self.is_done or self.appsink.queue_size > 0
        return not self.is_done

    def __str__(self) -> str:
        """Return string representing the pipelines current state."""
        return f"GstPipeline({self.state})"

    def __repr__(self) -> str:
        """Return string representing GstPipeline object."""
        return f"<{self}>"

    def __enter__(self) -> "GstPipeline":
        """Perform all required setup before running pipeline."""
        self.startup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cleanup all pipeline resources."""
        self.shutdown()

    def _main_loop_run(self):
        try:
            self._main_loop.run()
        except Exception as ex:
            self._log.warning("%s" % ex)
            pass

    def _init_elements(self):
        if self.pipeline:
            elements = self.pipeline.iterate_elements()
            out = []
            while True:
                ret, elem = elements.next()
                if ret == Gst.IteratorResult.DONE:
                    break
                if ret != Gst.IteratorResult.OK:
                    break
                out.append(elem)
        return out

    def get_by_cls(self, cls: GObject.GType) -> typing.List[Gst.Element]:
        """Return a `list[Gst.Element]` of all matching pipeline elements.

        Args:
            cls (GObject.GType): The Element class to match against.
        """
        if not self.elements:
            # FIXME
            return []
        return [e for e in self.elements if isinstance(e, cls)]

    def get_by_name(self, name: str) -> typing.Optional[Gst.Element]:
        """Return Gst.Element from pipeline by name lookup.

        Args:
            name (str): `name` property of the element.
        """
        if self.pipeline:
            return self.pipeline.get_by_name(name)
        return None

    @property
    def state(self) -> Gst.State:
        """Return current state of the pipeline."""
        if self.pipeline:
            return self.pipeline.get_state(timeout=1)[1]
        return Gst.State.NULL

    def _shutdown_pipeline(self, eos: bool = False, timeout: int = 1):
        if not self.pipeline:
            if self._end_stream_event.is_set():
                return
            self._log.warning("Pipeline is not running")
            return

        self._end_stream_event.set()

        if eos and self.state == Gst.State.PLAYING:
            thread = threading.Thread(
                target=self.pipeline.send_event, args=(Gst.Event.new_eos(),)
            )
            thread.start()
            thread.join(timeout=timeout)

        time.sleep(timeout)

        try:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
        except AttributeError:
            pass

    def _shutdown_main_loop(self, eos: bool = False, timeout: int = 1):
        if self._main_loop.is_running():
            self._main_loop.quit()

    def shutdown(self, eos: bool = False, timeout: int = 1):
        """Shutdown the mainloop thread and pipeline.

        Args:
            eos (bool, optional): Whether to send an EOS event to the running
                pipeline. Defaults to False.
            timeout: (int, optional): Timeout in seconds to wait for running
                threads to finish/return. Defaults to 1.
        """
        # Fix so don't print shutdown message twice on KeyboardInterrupt
        if self.state == Gst.State.NULL:
            return
        self._log.info("Shutdown requested ...")
        self._shutdown_pipeline(eos, timeout)
        self._shutdown_main_loop()
        self._log.info("Shutdown success")

    def startup(self):
        """Start the mainloop thread and pipeline."""
        self._log.info("Starting main loop thread")
        if self._main_loop_thread.is_alive():
            self._log.warning("Main loop already running")
            return

        self._main_loop_thread.start()

        if self.pipeline:
            self._log.warning("Pipeline already running")
            return
        self.pipeline = Gst.parse_launch(self.command)
        self.elements = self._init_elements()

        self.bus = self.pipeline.get_bus()
        self.bus.add_signal_watch()
        self.bus.connect("message::error", self.on_error)
        self.bus.connect("message::eos", self.on_eos)
        self.bus.connect("message::warning", self.on_warning)
        self.bus.connect("message::element", self.on_element)
        # STATE_CHANGED does not seem to work
        self.bus.connect("message::STATE_CHANGED", self.on_state_change)

        self.pipeline.set_state(Gst.State.READY)
        self._log.debug("Set pipeline to READY")
        self._end_stream_event.clear()

        # Allow pipeline to PREROLL by setting in PAUSED state so caps
        # negotiation happens before configuring appsink/appsrc
        self.pipeline.set_state(Gst.State.PAUSED)
        self._log.debug("Set pipeline to PAUSED")

        self._log.debug("Detecting and configuring AppSink if exists ...")
        self._appsink = self._setup_appsink()
        if self._appsink:
            self._log.debug("AppSink successfully configured")

        self._log.debug("Detecting and configuring AppSrc if exists...")
        self._appsrc = self._setup_appsrc()
        if self._appsrc:
            self._log.debug("AppSrc successfully configured")

        self.pipeline.set_state(Gst.State.PLAYING)
        # sample = self._appsink.sink.pull_sample()
        self._log.debug("Set pipeline to PLAYING")

    @property
    def is_active(self) -> bool:
        """Return whether or not pipeline is active."""
        return self.pipeline is not None and not self.is_done

    @property
    def is_done(self) -> bool:
        """Return whether or not EOS event has triggered."""
        return self._end_stream_event.is_set()

    @property
    def appsink(self) -> typing.Optional[AppSink]:
        """Return appsink if configured or None."""
        return self._appsink

    @property
    def appsrc(self) -> typing.Optional[AppSrc]:
        """Return appsrc if configured or None."""
        return self._appsrc

    def _setup_appsink(self) -> typing.Optional[AppSink]:
        """Initialize `AppSink` helper class if an appsink element in pipeline.

        Returns:
            A configured `AppSink` or None.
        """
        try:
            appsink_element = self.get_by_cls(GstApp.AppSink)[0]
            self._log.debug("AppSink element detected")
        except IndexError:
            self._log.debug("No AppSink element detected")
            return None
        return AppSink(appsink_element, self.leaky, self.qsize)

    def pop(self, timeout: float = 0.1) -> typing.Optional[GstBuffer]:
        """Return a `GstBuffer` from the `appsink` queue."""
        if not self.appsink:
            self._log.critical("No AppSink to pop buffer from")
            self.shutdown()
            raise RuntimeError

        buf: typing.Optional[GstBuffer] = None
        while (self.is_active or not self.appsink.queue.empty()) and not buf:
            try:
                buf = self.appsink.queue.get(timeout=timeout)
            except queue.Empty:
                pass
            # I think there's a reason I'm catching this here but don't remember
            except KeyboardInterrupt:
                self._log.critical("I'm interrupted!")
                self.shutdown()
        return buf

    def set_appsrc_video_caps(
        self,
        *,
        width: int,
        height: int,
        framerate: Framerate,
        format: str,
    ) -> bool:
        """Set appsrc caps if not already set.

        Note that changing the caps on a running pipeline is not supported!
        Caps are either set before starting the pipeline or are auto detected.

        Args:
            width (int): a positive integer corresponding to buffer width
            height (int): a positive integer corresponding to buffer height
            framerate (int, Fraction, str): A positive integer, `fractions.Fraction`,
                or string that can be understood as a Fraction.
                Ex. 1 -> 10/1, "25/1" -> `Fraction(25, 1)`
            format (str): A string that can be mapped to a `GstVideo.VideoFormat`.
                Ex. "RGB", "GRAY8", "I420"
        Raises:
            ValueError: If `Gst.Caps` cannot be created from arguments
        """
        if not self.appsrc:
            self._log.warning("No AppSrc element")
            return False
        if self.appsrc.caps:
            self._log.warning("AppSrc Caps already set")
            return False

        self._log.debug("Building caps from args ...")
        self.appsrc.caps = make_video_caps(width, height, framerate, format)
        self._log.debug("Caps successfully set")
        return True

    def _setup_appsrc(self) -> typing.Optional[AppSrc]:
        """Initialize `AppSrc` helper class if an appsrc element in pipeline.

        Returns:
            Configured `AppSrc` or None.
        """
        try:
            appsrc_element = self.get_by_cls(GstApp.AppSrc)[0]
        except IndexError:
            self._log.debug("No appsrc element to setup")
            return None
        appsrc_element.set_property("format", Gst.Format.TIME)
        appsrc_element.set_property("block", True)
        return AppSrc(appsrc_element)

    def push(self, data: np.ndarray):
        """Create a `Gst.Sample` from the `ndarray` and push it into the pipeline."""
        if not self.appsrc:
            self._log.critical("No AppSrc to push buffer to!")
            self.shutdown()
            raise RuntimeError
        try:
            self.appsrc.push(data)
        except KeyboardInterrupt:
            self._log.critical("I'm interrupted!")
            self.shutdown()

    def on_error(self, bus: Gst.Bus, msg: Gst.Message):
        """Log `ERROR` message and shutdown."""
        err, debug = msg.parse_error()
        self._log.error("Error %d %s: %s" % (err.code, err.message, debug))
        self.shutdown()

    def on_eos(self, bus: Gst.Bus, msg: Gst.Message):
        """Log `EOS` messages and shutdown pipeline."""
        self._log.debug("Received EOS message")
        self._shutdown_pipeline(eos=True)

    def on_warning(self, bus: Gst.Bus, msg: Gst.Message):
        """Log `WARNING` messages."""
        warn, debug = msg.parse_warning()
        self._log.warning("%s %s" % (warn, debug))

    def on_element(self, bus: Gst.Bus, msg: Gst.Message):
        """Log `ELEMENT` messages.

        Typically you would override this method.
        """
        msg_struct = msg.get_structure()
        name = msg_struct.get_name()
        self._log.debug("Element message %s" % name)

    def on_state_change(self, bus: Gst.Bus, msg: Gst.Message):
        """Log `STATE_CHANGED` messages.

        `STATE_CHANGED` events can be triggered by dynamic pipelines.
        (Ex. updating a sinks Caps)
        """
        old, new, pending = msg.parse_state_changed()
        self._log.debug("State changed from %s -> %s" % (old, new))
