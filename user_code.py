import logging

import numpy as np

from gstreasy import GstPipeline

LOG_FORMAT = "%(levelname)-6.6s | %(name)-20s | %(asctime)s.%(msecs)03d | %(threadName)s | %(message)s"
LOG_DATE_FORMAT = "%d.%m %H:%M:%S"
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
logging.basicConfig(level=logging.DEBUG, handlers=[log_handler])

log = logging.getLogger(__name__)


CAPS = "video/x-raw,width=320,height=240,framerate=30/1,format=RGB"
APPSRC_WITH_CAPS = f"appsrc caps={CAPS} emit-signals=true num-buffers=10 ! fakesink"
APPSRC_NO_CAPS = f"appsrc emit-signals=true num-buffers=300 is-live=true caps={CAPS} ! videoconvert ! autovideosink"
APPSRC_AND_APPSINK = (
    f"appsrc emit-signals=true num-buffers=10 ! appsink emit-signals=true sync=false"
)

if __name__ == "__main__":
    count = 0
    with GstPipeline(APPSRC_AND_APPSINK) as pipeline:
        pipeline.set_appsrc_caps(width=320, height=240, framerate=10, format="RGB")
        while pipeline:
            rand_array = np.random.randint(
                low=0, high=255, size=(240, 320, 3), dtype=np.uint8
            )
            pipeline.push(rand_array)
            buffer = pipeline.pop()
            if buffer:
                print(buffer.data.shape)
    # # log.info("Count %d" % count)

    # with GstPipeline(appsink_cmd) as pipeline:
    #     while pipeline:
    #         pipeline.push(rand_array)
    #         buffer = pipeline.pop()
    #         if buffer:
    #             logging.info(buffer.data.shape)
    #             assert rand_array.all() == buffer.data.all()
    #             break
    #         break
    #         count += 1
    #     logging.info("%s %d" % (str(buffer.data.shape), count))
