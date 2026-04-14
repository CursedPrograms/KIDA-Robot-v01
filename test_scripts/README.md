# Test Scripts

## Overview
This directory contains scripts designed to test parallel inference performance on multiple models using either separate processes or threads.

### 1. `launch_3_processes.sh`
- Spawns three parallel processes, each running a different model.
- **Requirements:**
  - `degirum` package
  - `degirum_tools` package
  - Hailo multi-process service (only if running on `@local`)
- **Usage:**
  ```bash
  ./launch_3_processes.sh
  ```

### 2. `threaded_inference.py`
- Spawns three threads, each running a different model.
- **Requirements:**
  - `degirum` package
  - `degirum_tools` package
- **Usage:**
  ```bash
  python threaded_inference.py
  ```

## Tips
- You can use any model from [DeGirum's Hailo Model Zoo](https://hub.degirum.com/degirum/hailo).
- Modify the `HOST_ADDRESS` variable as per your setup:
  - `@local`: For testing local hardware inference without an AIServer.
  - `localhost`: For testing local hardware inference using an AIServer.
- `ITERATIONS` is set to `2500` by default but can be adjusted.

## Notes
- These scripts are solely designed for testing parallel inference capabilities and should not be used for production applications
