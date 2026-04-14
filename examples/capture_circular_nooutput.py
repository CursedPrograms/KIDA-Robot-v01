#!/usr/bin/python3
import time

from picamera2 import Picamera2
from picamera2.encoders import H264Encoder
from picamera2.outputs import CircularOutput

# This script shows how to record video to a circular buffer and then
# open a file to start recording the output.
#
# Note that the CircularOutput2 is usually recommended now over the
# plain CircularOutput. See capture_circular_nooutput_improved.py.


picam2 = Picamera2()
fps = 30
dur = 5
vconfig = picam2.create_video_configuration(controls={'FrameRate': fps})
picam2.configure(vconfig)
encoder = H264Encoder()
output = CircularOutput(buffersize=int(fps * (dur + 0.2)), outputtofile=False)
output.fileoutput = "file.h264"
picam2.start_recording(encoder, output)
time.sleep(dur)
output.stop()
