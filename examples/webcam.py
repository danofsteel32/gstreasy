import logging
import os

from gstreasy import GstPipeline

# Configure logging
fmt = "%(levelname)-6.6s | %(name)-20s | %(asctime)s.%(msecs)03d | %(threadName)s | %(message)s"
dmt_fmt = "%d.%m %H:%M:%S"
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=dmt_fmt))
logging.basicConfig(level=logging.DEBUG, handlers=[log_handler])
log = logging.getLogger(__name__)

# Configure pipeline command
# videoconvert to RGB for numpy compatibility (webcam default usually YUY2)
caps = "video/x-raw, width=(int)640, height=(int)480, framerate=(fraction)30/1"
device = int(os.getenv("WEBCAM", 0))
cmd = f"""
    v4l2src device=/dev/video{device}
      ! {caps} ! videoconvert ! video/x-raw,format=RGB
      ! appsink emit-signals=true
"""

with GstPipeline(cmd) as pipeline:
    while pipeline:
        buffer = pipeline.pop()
        if buffer:
            log.info(buffer.data.shape)
