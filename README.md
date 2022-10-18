
A re-imagining of [gstreamer-python](https://github.com/jackersson/gstreamer-python).
I was going to just work on a fork of that repo but there was so much I thought
should be changed. Some of the new features:

- Auto detect caps if in gst-launch command
- Auto detect and configure `appsink` and `appsrc` if in command
- Support for `appsink` and `appsrc` in same pipeline
- Faster `Gst.Sample` -> `ndarray`


####  Example Usage

Install with: `python -m pip install gstreasy`

Also check out the `user_code.py` script for an `appsrc` example.

##### Simple pipeline without an `appsink` element:

```python
simple_cmd = "videotestsrc num-buffers=60 ! autovideosink"
with GstPipeline(simple_cmd) as pipeline:
    print("Running simple pipeline")
```

##### Pipeline with an appsink element:

```python
appsink_cmd = "videotestsrc num-buffers=60 ! appsink emit-signals=true sync=false"
with GstPipeline(appsink_cmd) as pipeline:
    while pipeline:
        buffer = pipeline.pop()
        if buffer:
            type(buffer.data)  # np.ndarray
```

##### Pipeline using `tee` element and multiple sinks:

```python
tee_cmd = '''
    videotestsrc num-buffers=60 ! tee name=t
    t. ! queue ! video/x-raw,format=RGB,framerate=60/1
       ! appsink emit-signals=true sync=false
    t. ! queue ! video/x-raw,format=RGB,framerate=60/1
       ! jpegenc ! avimux
       ! filesink location=recording.mp4
'''
with GstPipeline(tee_cmd) as pipeline:
    while pipeline:
        buffer = pipeline.pop()
        # do whatever you want with the buffer's ndarray
    # Meanwhile recording.mp4 is being written
```

### Develop

All dev tasks can be handled with the `run.sh` script but it just wraps standard tools if you can't/don't want use it.

- `python -m pip install -e .[dev,doc]` to install deps
- `tox` to run tests for py3.7 and py3.10.
- `flake8` and `mypy` for linting
- `pdoc -d google src/gstreasy` for online docs
