# gstreasy

A re-imagining of [gstreamer-python](https://github.com/jackersson/gstreamer-python).


### TODO
- Fix tests
- Get tox working
- cleanup docs
- publish on PyPI

### Goals
- Easier installation (PyPI)
- Dependency install scripts for `apt` and `dnf` distros
- Better support for pipelines with `tee` elements
- Optimised hot paths and caching for performance
- Auto detection of Caps
- Optional use of the GstContext
    - Use if you want to run multiple pipelines
    - Auto enter/exit if only running one pipeline
- Detailed documentation
- Easy assign callbacks on the message bus
- Examples/Recipes/Preconfigured pipelines for common tasks
    - Splitmuxsink with callbacks
    - Live stream webcam to browser
    - AppSink and record


####  Example Usage

##### Simple pipeline without an `appsink` element:

```python
simple_cmd = "videotestsrc num-buffers=60 ! autovideosink"
with GstPipeline(simple_cmd) as pipeline:
    print("Running simple pipeline")
```

##### Pipeline with an appsink element:

```python
appsink_cmd = "videotestsrc num-buffers=60 ! `appsink` emit-signals=true sync=false"
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
       ! videoconvert
       ! x264enc tune=zerolatency
       ! mp4mux
       ! filesink location=recording.mp4
'''
with GstPipeline(tee_cmd) as pipeline:
    while pipeline:
        buffer = pipeline.pop()
    # Meanwhile recording.mp4 is being written
```
