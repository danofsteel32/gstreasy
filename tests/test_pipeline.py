from pathlib import Path

import numpy as np
import pytest

from gstreasy import GstPipeline
import gstreasy.utils as utils


def rand_array(channels: int = 3):
    return np.random.randint(low=0, high=255, size=(240, 320, channels), dtype=np.uint8)


def test_simple():
    cmd = "videotestsrc num-buffers=1 ! fakevideosink"
    with GstPipeline(cmd) as pipeline:
        pass


def test_appsink_buffers():
    num_buffers, count = 10, 0
    cmd = f"videotestsrc num-buffers={num_buffers} ! " "appsink emit-signals=true"
    with GstPipeline(cmd) as pipeline:
        while pipeline:
            buffer = pipeline.pop()
            if buffer:
                count += 1
                assert isinstance(buffer.data, np.ndarray)
    assert count == num_buffers


def test_tee():
    num_buffers, count = 10, 0
    out = Path("/tmp/recording.avi")
    if out.exists():
        out.unlink()
    cmd = f"""
        videotestsrc num-buffers={num_buffers} ! tee name=t
        t. ! queue ! video/x-raw,format=RGB,framerate=60/1
           ! appsink emit-signals=true
        t. ! queue ! video/x-raw,format=RGB,framerate=60/1
           ! jpegenc ! avimux
           ! filesink location={str(out)}
    """
    count = 0
    with GstPipeline(cmd) as pipeline:
        while pipeline:
            buffer = pipeline.pop()
            if buffer:
                count += 1
    # Did we get at least 90% of the buffers?
    assert count == num_buffers
    if out.exists():
        out.unlink()


def test_appsrc_with_caps():
    num_buffers = 10
    caps = "video/x-raw,width=320,height=240,framerate=60/1,format=RGB"
    cmd = f"appsrc caps={caps} emit-signals=true num-buffers={num_buffers} ! fakesink"
    with GstPipeline(cmd) as pipeline:
        while pipeline:
            pipeline.push(rand_array())


def test_appsrc_no_caps():
    num_buffers = 10

    cmd = (
        f"appsrc emit-signals=true num-buffers={num_buffers} !"
        "videoconvert ! fakesink"
    )

    with GstPipeline(cmd) as pipeline:
        pipeline.set_appsrc_caps(width=320, height=240, framerate=10, format="GRAY8")
        while pipeline:
            pipeline.push(rand_array(channels=1))

def test_appsrc_and_sink():
    num_buffers, count = 10, 0

    cmd = (
        f"appsrc emit-signals=true num-buffers={num_buffers} ! "
        "appsink emit-signals=true"
    )
    with GstPipeline(cmd) as pipeline:
        pipeline.set_appsrc_caps(width=320, height=240, framerate=10, format="GRAY8")
        while pipeline:
            pipeline.push(rand_array(channels=3))
            buffer = pipeline.pop()
            if buffer:
                assert buffer.data.shape == (240, 320)
                count += 1
        assert count == num_buffers
