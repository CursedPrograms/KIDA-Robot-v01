#!/bin/bash


# Camera 1
rpicam-hello --camera 1 -t 0 \
--post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json \
--viewfinder-width 1920 \
--viewfinder-height 1080 \
--framerate 30
