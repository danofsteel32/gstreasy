from pathlib import Path

import numpy as np
import pytest

from gstreasy import GstPipeline
import gstreasy.utils as utils

# leaky
PIPE_LINE_ARGS = [
    (False,),
    (False,),
    (True,),
    (True,),
]


@pytest.mark.parametrize(
    "leaky",
    PIPE_LINE_ARGS,
)
def test_simple(leaky):
    simple_cmd = "videotestsrc num-buffers=10 ! fakevideosink"
    with GstPipeline(simple_cmd, leaky) as pipeline:
        pass


@pytest.mark.parametrize(
    "leaky",
    PIPE_LINE_ARGS,
)
def test_appsink(leaky):
    appsink_cmd = "videotestsrc num-buffers=10 ! appsink emit-signals=true sync=false"
    count = 0
    with GstPipeline(appsink_cmd, leaky) as pipeline:
        while pipeline:
            buffer = pipeline.pop()
            if buffer:
                count += 1
                assert isinstance(buffer.data, np.ndarray)
    assert count == 10


@pytest.mark.parametrize(
    "leaky",
    PIPE_LINE_ARGS,
)
def test_tee(leaky):
    out = Path("/tmp/recording.mp4")
    out.unlink(missing_ok=True)
    tee_cmd = """
        videotestsrc num-buffers=60 ! tee name=t
        t. ! queue ! video/x-raw,format=RGB,framerate=60/1
           ! appsink emit-signals=true sync=false
        t. ! queue ! video/x-raw,format=RGB,framerate=60/1
           ! videoconvert
           ! x264enc tune=zerolatency
           ! mp4mux
           ! filesink location=/tmp/recording.mp4
    """
    count = 0
    with GstPipeline(tee_cmd, leaky) as pipeline:
        while pipeline:
            buffer = pipeline.pop()
            if buffer:
                count += 1
    # Did we get at least 90% of the buffers?
    assert count >= int(60 * 0.90)
    assert out.exists()
    out.unlink()
