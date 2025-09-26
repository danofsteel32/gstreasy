"""An example of pushing numpy arrays to a videosink with the gstreasy library.

This program was originally used to create a fake video feed of an automotive
stamping transfer press while we were waiting on real cameras to arrive.

The press cycle generator is silly but I had it lying around from
a previous project and wanted something more interesting than using
`np.rand.randint` The generated frames are displayed on the `autovideosink`
at ~30 fps and are a crude simulation of a running industrial stamping press.
"""

import logging
import typing

import numpy as np

from gstreasy import GstPipeline

# Configure logging
fmt = "%(levelname)-6.6s | %(name)-20s | %(asctime)s.%(msecs)03d | %(threadName)s | %(message)s"  # noqa: E501
dmt_fmt = "%d.%m %H:%M:%S"
log_handler = logging.StreamHandler()
log_handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=dmt_fmt))
logging.basicConfig(level=logging.INFO, handlers=[log_handler])
log = logging.getLogger(__name__)


COLORS = {
    "red": (255, 0, 0),
    "yellow": (255, 255, 0),
    "blue": (0, 0, 255),
    "green": (0, 128, 0),
    "white": (255, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "orange": (255, 175, 0),
    "gray": (188, 188, 188),
}


def press_cycle_gen(
    shape: typing.Tuple[int, int, int],
    fps: int = 30,
    crash_cycle: int = 1,
    color: str = "white",
):
    """Dumb stamping press simulation with special die-crash effects.

    I only made this because we didn't have the real camera hooked up yet.

    Args:
        shape (tuple): The shape of the ndarray's to generate.
            Ex: (240, 320, 3)
        fps (int): Simulated frame rate that changes much the dies move
            per frame. Defaults to 30.
        crash_cycle (int): Do a simulated die-crash every n cycles.
            Defaults to 1 (every cycle)
        color (str): String key that maps to a RGB value in `COLORS`.
            Sets color of press die. Defaults to 'white'.
    """
    h, w, _ = shape
    cycle_length = 3  # How many secs to complete full 360°
    total_frames = cycle_length * fps
    half = total_frames // 2
    strip_color = COLORS["gray"]

    def crash_strip(width, length):
        strip = np.ones((width // 2, length, shape[-1]), dtype=np.uint8)
        for x in range(0, length, 40):
            if np.random.randint(0, 2):
                strip[0 : width // 4, x : x + np.random.randint(20, 40), :] = 0
        return strip

    def press_image(frame: int, crash: bool = False):
        length = w - (w // 4)
        width = length // 4
        press_rect = np.ones((width, length), dtype=np.uint8)

        if crash:
            strip = crash_strip(width, length)
            strip_y = h // 2 - width // 4
        else:
            strip = np.ones((width // 4, length, shape[-1]), dtype=np.uint8)
            strip_y = h // 2 - width // 8

        top_y = h // 6 - width // 2
        bot_y = (h - h // 6) - width // 2
        center_x = (w - length) // 2

        move_dist = bot_y - h // 2
        move_rate = round(move_dist / (half))

        if frame < half:
            frame_delta = move_rate * frame
            x = center_x
        elif frame > half:
            frame_delta = move_rate * (total_frames - frame)
            # Simulate camera shaking on press impact
            if frame < (half + half // 4):
                x = np.random.randint(center_x - 20, center_x + 21)
            else:
                x = center_x
        elif frame == half:
            frame_delta = move_rate * frame
            x = np.random.randint(center_x - 20, center_x + 21)
            strip = 1

        top_y, bot_y = top_y + frame_delta, bot_y - frame_delta

        image = np.zeros(shape, dtype=np.uint8)

        assert h - (top_y + width) == (h - (h - bot_y))

        if crash:
            strip_visible = True if ((top_y + width) < strip_y + width // 2) else False
            if strip_visible:
                image[strip_y : strip_y + width // 2, x : x + length, :] = (
                    strip * strip_color
                )
        else:
            strip_visible = True if ((top_y + width) < strip_y + width // 4) else False
            if strip_visible:
                image[strip_y : strip_y + width // 4, x : x + length, :] = (
                    strip * strip_color
                )

        for n, c in enumerate(COLORS[color]):
            for y in [top_y, bot_y]:
                image[y : y + width, x : x + length, n] = press_rect * c

        label = 1 if (crash and strip_visible) else 0
        return image, label

    n = 1
    frame = 0
    while True:
        if frame > half and (n % crash_cycle == 0):
            image, label = press_image(frame, crash=True)
        else:
            image, label = press_image(frame, crash=False)
        if frame == total_frames - 1:
            n += 1
            frame = 0
        else:
            frame += 1
        yield image, label


if __name__ == "__main__":
    width, height, channels = 320, 240, 3
    frame_gen = press_cycle_gen(shape=(height, width, channels), crash_cycle=4)

    cmd = "appsrc emit-signals=true is-live=true ! videoconvert ! queue ! autovideosink"
    with GstPipeline(cmd) as pipeline:
        pipeline.set_appsrc_video_caps(
            width=width, height=height, framerate=30, format="RGB"
        )
        while pipeline:
            frame = next(frame_gen)[0]
            pipeline.push(frame)
