[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>

<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
  <img alt="PowerShell" src="https://img.shields.io/badge/PowerShell-%23323330.svg?&style=for-the-badge&logo=powershell&logoColor=white"/>
  <img alt="Batch" src="https://img.shields.io/badge/Batch-%23323330.svg?&style=for-the-badge&logo=windows&logoColor=white"/>
  <img alt="RaspberryPi" src="https://img.shields.io/badge/rasberrypi-%23323330.svg?&style=for-the-badge&logo=raspberrypi&logoColor=white"/>
</div>

---


<div align="center">
  <img src="/images/demo/kida.jpg" alt="KIDA Robot" width="600"/>
</div>

# KIDA: Kinetic Interactive Drive Automaton

- [KIDA-Robot-v00](https://github.com/CursedPrograms/KIDA-Robot-v00)
- [WHIP-Robot-v00](https://github.com/CursedPrograms/WHIP-Robot-v00)
- [NORA-Robot-v00](https://github.com/CursedPrograms/NORA-Robot-v00)
- [DREAM](https://github.com/CursedPrograms/DREAM)
- [RIFT](https://github.com/CursedPrograms/RIFT)

<div align="center">
  <img src="/images/background.jpeg" alt="KIDA Robot" width="600"/>
</div>

## Overview

KIDA is an advanced autonomous robot platform built on Raspberry Pi 5, featuring dual-camera vision (night vision + AI camera), a Hailo-8 AI accelerator (13 TOPS), and local LLM capabilities. The robot supports voice interaction, autonomous navigation, and real-time AI inference.

---

<div align="center">
  <img src="/images/demo/KIDA001.jpg" alt="KIDA Robot" width="600"/>
</div>

### Prerequisite Software
- [Raspberry Pi OS](https://www.raspberrypi.com/software/operating-systems/)
- [Arduino IDE](https://docs.arduino.cc/software/ide/)

## Hardware Specifications

### Computing
| Component | Details |
|-----------|---------|
| Main Board | Raspberry Pi 5 / 4 |
| AI Accelerator | Hailo-8 (13 TOPS) via NVMe + AI Hat |
| Storage | NVMe SSD |

### Chassis & Motion
| Component | Details |
|-----------|---------|
| Chassis | XiaoR Geek Robot Tank Chassis |
| Motor Driver | L298N × 2 |
| Motors | Dual DC motors with tank steering |

### Power System
| Component | Details |
|-----------|---------|
| Primary Battery | 3× 21700 (12.6V in series) |
| Backup Battery | 3× 18650 via Pi UPS |
| Voltage Regulator | LM2596S (12V → 5V) |
| Power Switches | 2× (Main + Pi) |

### Sensors & Cameras
| Component | Details |
|-----------|---------|
| Camera 0 | Raspberry Pi Night Vision Camera |
| Camera 1 | Raspberry Pi AI Camera (IMX500) |
| Ultrasonic Sensor | HC-SR04 |
| Microphone | USB Microphone |

### Audio
| Component | Details |
|-----------|---------|
| Output | Pi Speakers |
| TTS | Piper / ElevenLabs |

---

## Software Stack

### Operating System
- **Recommended:** Raspberry Pi OS (Bookworm)
- **Kernel:** `6.12.62+rpt-rpi-2712`

### AI & ML
| Component | Technology |
|-----------|------------|
| LLM | Ollama (DeepSeek-R1:1.5b, Gemma3:4b) |
| STT | OpenAI Whisper |
| TTS | Piper / ElevenLabs API |
| Vision | Hailo-8 AI Processor, IMX500 |

---

## GPIO / Wiring Reference

### Motor A (Left)
| L298N Pin | Function | Pi GPIO |
|-----------|----------|---------|
| IN1 | Direction | GPIO 17 |
| IN2 | Direction | GPIO 27 |
| ENA | Speed (PWM) | GPIO 18 (hardware PWM) |

### Motor B (Right)
| L298N Pin | Function | Pi GPIO |
|-----------|----------|---------|
| IN3 | Direction | GPIO 22 |
| IN4 | Direction | GPIO 23 |

### Power Schematic
```
[12V Battery Pack — 3S 21700 @ 3.7V each]
 ├── + ─────────► L298N VS        (motor power input)
 ├── + ─────────► LM2596S IN+     (step-down input for Pi)
 ├── – ─────────► L298N GND
 └── – ─────────► LM2596S IN–

[LM2596S Output]
 ├── OUT+ ──────► Pi 5V  (GPIO pin 2 — or Pi UPS via USB-C [Recommended])
 └── OUT– ──────► Pi GND (GPIO pin 6 or 9)
```

---

## Installation

```bash
from facenet_pytorch import InceptionResnetV1

# For a model pretrained on VGGFace2
model = InceptionResnetV1(pretrained='vggface2').eval()

# For a model pretrained on CASIA-Webface
model = InceptionResnetV1(pretrained='casia-webface').eval()

# For an untrained model with 100 classes
model = InceptionResnetV1(num_classes=100).eval()

# For an untrained 1001-class classifier
model = InceptionResnetV1(classify=True, num_classes=1001).eval()
```

### 1. Clone & Set Up Python Environment

```bash
sudo apt update
sudo apt install python3-venv python3-pip

python3 -m venv ~/kida-venv
source ~/kida-venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Install OpenAI Whisper

```bash
pip install git+https://github.com/openai/whisper.git
```

### 3. Install Audio Dependencies

```bash
sudo apt install pulseaudio jackd2 alsa-utils portaudio19-dev python3-pyaudio
```
```bash
sudo apt install imx500-models
```

Using pip
opencv_transforms is available as a pip package:

pip install opencv_transforms
Using UV (recommended for development)
This project now uses UV for dependency management. To install for development:

Install UV if you haven't already:
curl -LsSf https://astral.sh/uv/install.sh | sh
Clone the repository and install dependencies:
git clone https://github.com/jbohnslav/opencv_transforms.git
cd opencv_transforms
uv sync --all-extras  # This installs all dependencies including dev dependencies
Run commands in the UV environment:
uv run python your_script.py
# or activate the virtual environment
source .venv/bin/activate  # On Unix/macOS
# or
.venv\Scripts\activate  # On Windows
Usage
Breaking change! Please note the import syntax!

from opencv_transforms import transforms
From here, almost everything should work exactly as the original transforms.
Example: Image resizing
import numpy as np
image = np.random.randint(low=0, high=255, size=(1024, 2048, 3))
resize = transforms.Resize(size=(256,256))
image = resize(image)
Should be 1.5 to 10 times faster than PIL. See benchmarks

```bash
# Basic debugging
from opencv_transforms.debug import utils
result = utils.compare_contrast_outputs(image, contrast_factor=0.5)

# Create test summary across multiple contrast factors
summary = utils.create_contrast_test_summary(image)

# Analyze PIL precision issues
utils.analyze_pil_precision_issue(image)
```

```bash

from facenet_pytorch import MTCNN, InceptionResnetV1

# If required, create a face detection pipeline using MTCNN:
mtcnn = MTCNN(image_size=<image_size>, margin=<margin>)

# Create an inception resnet (in eval mode):
resnet = InceptionResnetV1(pretrained='vggface2').eval()

apt-get update
apt-get install -y libsm6 libxext6 libxrender-dev
pip install opencv-python
```

```bash

apt-get update
apt-get install -y libsm6 libxext6 libxrender-dev
pip install opencv-contrib-python
pip install opencv_transforms
pip install opencv-python
pip install facenet-pytorch
pip install piper-tts

sudo apt install pulseaudio jackd2 alsa-utils portaudio19-dev python3-pyaudio

https://download.pytorch.org/whl/cpu/torch-1.0.1.post2-cp36-cp36m-linux_x86_64.whl
https://download.pytorch.org/whl/cpu/torch-1.0.1.post2-cp37-cp37m-linux_x86_64.whl

```

docker run --rm -p 8888:8888
    -v ./facenet-pytorch:/home/jovyan timesler/jupyter-dl-gpu \
    -v <path to data>:/home/jovyan/data
    pip install facenet-pytorch && jupyter lab 

### 4. Install Piper TTS

```bash
pip install piper-tts
```

### 5. Install ElevenLabs (optional)

```bash
pip install git+https://github.com/elevenlabs/elevenlabs-python@v3
```

### 6. Install & Set Up Hailo

```bash
sudo apt update
sudo apt install hailo-all
```

Verify the installation:
```bash
hailortcli fw-control identify
```

Expected output:
```
Device: Hailo-8
PCIe Address: 0001:03:00.0
Firmware Version: x.x.x
```

> **Troubleshooting:** If the driver is not detected after install, a DKMS module may have failed to build. Pin back to version 4.19 which has stable kernel module support:
> ```bash
> sudo apt-mark hold linux-image-rpi-2712 linux-headers-rpi-2712
> sudo apt install hailort=4.19.0 hailo-all=4.19.0 -y
> sudo apt-mark hold hailort hailo-all
> sudo reboot
> ```

#### Manual Hailo Build (if package unavailable)
```bash
sudo apt install -y git build-essential cmake python3-dev python3-pip

git clone https://github.com/hailo-ai/hailort.git
cd hailort && mkdir build && cd build
cmake .. && make -j$(nproc) && sudo make install

echo "export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH" >> ~/.bashrc
source ~/.bashrc
pip install hailort
```

---

## Running KIDA

### Activate the virtual environment
```bash
cd /home/kida-01/Desktop/Kida-Robot
source venv/bin/activate
```

### Run the main script
```bash
python scripts/main.py
```

### Run LLM
```bash
ollama run deepseek-r1:1.5b
# or
ollama pull gemma3:4b-it-qat
```

### Test cameras
```bash
rpicam-hello --list-cameras

# AI Camera inference (camera slot 1)
rpicam-hello --camera 1 -t 0 \
  --post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json \
  --viewfinder-width 1920 \
  --viewfinder-height 1080 \
  --framerate 30
```

---

## Autostart on Boot

### Option A: systemd service (recommended)

```bash
sudo nano /etc/systemd/system/kida.service
```

```ini
[Unit]
Description=KIDA Main Controller
After=graphical.target

[Service]
User=kida-01
WorkingDirectory=/home/kida-01/Desktop/Kida-Robot
ExecStart=/home/kida-01/kida-venv/bin/python scripts/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable kida.service
sudo systemctl start kida.service
```

### Option B: Camera preview service

```bash
sudo nano /etc/systemd/system/kida-camera.service
```

```ini
[Unit]
Description=KIDA Camera Live Preview
After=graphical.target

[Service]
User=kida-01
Environment=DISPLAY=:0
ExecStart=/usr/bin/python3 /home/kida-01/Desktop/Kida-Robot/scripts/camera_preview.py
Restart=always
RestartSec=5

[Install]
WantedBy=graphical.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable kida-camera.service
sudo systemctl start kida-camera.service
```

Check status / logs:
```bash
sudo systemctl status kida-camera.service
journalctl -u kida-camera.service -f
```

### Option C: crontab

```bash
crontab -e
# Add:
@reboot cd /home/kida-01/Desktop/Kida-Robot && python3 main.py &
```

### Option D: Desktop autostart

```bash
mkdir -p ~/.config/autostart
nano ~/.config/autostart/kida.desktop
```

```ini
[Desktop Entry]
Name=KIDA Controller
Exec=python3 /home/kida-01/Desktop/Kida-Robot/main.py
Type=Application
X-GNOME-Autostart-enabled=true
```

---

## RTC Setup

```bash
dtparam=rtc_bbat_vchg=3000000
sudo mount -o remount,rw /boot/firmware
sudo nano /boot/firmware/config.txt
sudo hwclock -w
sudo hwclock -v -r
```

---

## FFmpeg Setup (Windows)

1. Download the latest static build from: https://www.gyan.dev/ffmpeg/builds/
2. Extract and rename the folder to `ffmpeg`, placed at `C:\ffmpeg`
3. Ensure this structure exists:
   ```
   C:\ffmpeg\bin\
   ├── ffmpeg.exe
   ├── ffplay.exe
   └── ffprobe.exe
   ```
4. Add `C:\ffmpeg\bin` to your system `PATH` via **System Properties → Environment Variables**
5. Verify: open a new terminal and run `ffmpeg -version`

---

## Diagnostics

```bash
# Check Hailo kernel module
lsmod | grep hailo

# Identify Hailo device
hailortcli fw-control identify

# Check PCI devices
lspci | grep Hailo

# Kill conflicting camera processes
ps aux | grep -E 'libcamera|picamera'
sudo kill -9 <PID>

# Check which process is using the camera
sudo fuser -v /dev/video0

# Kernel version
uname -r
```

---

<div align="center">
  <img src="/images/demo/KIDA002.jpg" alt="KIDA Robot" width="600"/>
</div>
<br>
<div align="center">© Cursed Entertainment 2026</div>

<br>

<div align="center">
  <a href="https://cursed-entertainment.itch.io/" target="_blank">
    <img src="https://github.com/CursedPrograms/cursedentertainment/raw/main/images/logos/logo-wide-grey.png" alt="CursedEntertainment Logo" style="width:250px;">
  </a>
</div>

<br>

<div align="center">
  <a href="https://github.com/SynthWomb" target="_blank">
    <img src="https://github.com/SynthWomb/synth.womb/blob/main/logos/synthwomb07.png" alt="SynthWomb" style="width:200px;"/>
  </a>
</div>
