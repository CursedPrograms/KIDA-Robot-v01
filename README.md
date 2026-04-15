[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>
<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
  <img alt="C++" src="https://img.shields.io/badge/c++%20-%23323330.svg?&style=for-the-badge&logo=c%2B%2B&logoColor=white"/>
</div>
<div align="center">
      <img alt="Arduino" src="https://img.shields.io/badge/-Arduino-323330?style=for-the-badge&logo=arduino&logoColor=white"/>
  <img alt="RaspberryPi" src="https://img.shields.io/badge/rasberrypi-%23323330.svg?&style=for-the-badge&logo=raspberrypi&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
      <img alt="Git" src="https://img.shields.io/badge/git%20-%23323330.svg?&style=for-the-badge&logo=git&logoColor=white"/>
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

---

<div align="center">
  <img src="/images/background.jpeg" alt="KIDA Robot" width="600"/>
</div>

## 📖 Overview

<details>
<summary><b>View Overview</b></summary>

KIDA represents the pinnacle of the RIFT fleet. Built on the **Raspberry Pi 5**, it leverages the **Hailo-8L** AI accelerator to perform high-speed neural processing at the edge. With a dual-camera setup for multi-spectrum vision and local LLM integration, KIDA is designed for sophisticated human-robot interaction and autonomous decision-making without relying on the cloud.

Core Features
- [x] Neural Edge Processing: 13 TOPS of AI compute via Hailo-8L for real-time object detection and tracking.
- [x] Hybrid Dual-Vision: Simultaneous processing of Night Vision and 4K AI camera feeds for 24/7 situational awareness.
- [x] Local LLM Integration: Privacy-focused voice interaction and logic processing running entirely on-device.
- [x] Autonomous Navigation: Advanced SLAM and obstacle avoidance powered by high-speed Raspberry Pi 5 architecture.

</details>

---

<div align="center">
  <img src="/images/demo/KIDA001.jpg" alt="KIDA Robot" width="600"/>
</div>

## Prerequisites

<details>
<summary><b>View Prerequisites</b></summary>

### Software
- [Arduino IDE](https://docs.arduino.cc/software/ide/)
- [Raspberry Pi OS](https://www.raspberrypi.com/software/operating-systems/)
### Operating System
- **Recommended:** Raspberry Pi OS (Bookworm)
- **Kernel:** `6.12.62+rpt-rpi-2712`

## Hardware

### Compute
| **Component** | **Details** |
|-----------|---------|
| Main Board | Raspberry Pi 5 (4GB) |
| PCI-E Board | NVMe + AI Hat |
| AI Accelerator | Hailo-8 (13 TOPS) via NVMe + AI Hat |
| Storage | NVMe SSD |
| I2C | Custom |

### Microcontrollers
| **Component** | **Details** |
|-----------|---------|
| Microcontroller 0 | RGBduino Jenny | Dev0 |
| Microcontroller 1 | Arduino UNO | Dev1 |

### Chassis & Motion
| **Component** | **Details** |
|-----------|---------|
| Chassis | Robot Tank Chassis |
| Motor Driver | L298N |
| Motors | 2× 12v DC Motors |

### User Controllers
| **Component** | **Details** |
|-----------|---------|
| Interface | PC, Android, iPhone |
| Controller | Wireless Keyboard, IR remote |

### Power System
| **Component** | **Details** |
|-----------|---------|
| Motor Battery | 3s 21700 (12.6V in series) |
| Compute Battery | 3s 18650 via Pi UPS |
| Realtime Battery | CR2032 |
| Voltage Regulator | LM2596S (12V → 11.5V) |
| Power Switches | 4× (Main + UPS), 2× MOSFET SWITCHES|

### Cameras
| **Component** | **Details** |
|-----------|---------|
| Camera 0 | Raspberry Pi Night Vision Camera |
| Camera 1 | Raspberry Pi AI Camera (IMX500) |

### Sensors
| **Component** | **Details** |
|-----------|---------|
| Ultrasonic Sensors | HC-SR04 × 2 (one mounted on servo for scanning) |
| Line Follower | 3-Channel Line Tracking Sensor |
| Switch Sensor | Ball Switch (Impact Detection) |
| Infrared | IR Receiver Module |
| UV Sensor | UV Light Sensor Module |
| Light Sensor | Photoresistor (LDR) |
| ToF Sensor | Time-of-Flight Laser Distance Sensor |
| PIR Sensor | Passive Infrared Motion Sensor |

### Audio
| **Component** | **Details** |
|-----------|---------|
| Output | Pi Speakers |
| Input | USB Microphone |

</details>

# Schematics
## ⚡ Technical Pinouts

<details>
<summary><b>View Power Distribution Wiring</b></summary>

### Power Schematic
```
3S 21700 BATTERIES ──────► LM2596S INPUT 11.5V ──────► LM2596S Output 11.5V
LM2596S Output 11.5V:
├── + ──────► L298N +
├── – ──────► L298N - ─────────► ARDUINO (DEV0) GND
├── + ──────► MOSFET switch ─────────► (12V) FRONT LIGHTS +
├── + ──────► MOSFET switch ─────────► (12V)BACK LIGHTS +
├── – ──────► MOSFET switch ─────────► FRONT LIGHTS -
└── – ──────► MOSFET switch ─────────► BACK LIGHTS -  
```
```
3S 18650 BATTERY UPS ──────► USB-C OUTPUT ──────► RASPBERRY PI
    ├──► POWER BUTTON
    └──► CHARGING PORT
```
```

UPS:
├── I2C ─────► Raspberry Pi I2C BUS
├── 3.3V ────► BREADBOARD (3.3V rail)
├── 5V ──────► SERVO POWER
└── 5V ──────► BREADBOARD (5V rail)
```
</details>

<details>
<summary><b>View Power Raspberry Pi Wiring</b></summary>

```
RASPBERRY PI:
├──► NVMe + AI HAT (PCIe)
│     └──► NVMe SSD + HAILO-8L
│
├──► ARDUINO (DEV0, DEV1) via USB
├──► Camera 0 ─────► Night Vision Camera
├──► Camera 1 ─────► AI Camera (IMX500)
├──► SPEAKER HAT (USB)
│
├──► USB HUB:
│     ├── MIC (USB)
│     └── WIRELESS KEYBOARD (USB)
│
└──► GPIO:
      └──► I2C BUS
            ├── SDA → Pin 3
            └── SCL → Pin 5
```
</details>

<details>
<summary><b>View Power Arduino 0 Wiring</b></summary>

### **ARDUINO (DEV0):**
#### Libraries:
```
Adafruit_VL53L0X.h
Servo.h
Adafruit_NeoPixel.h
avr/power.h
Wire.h
```
```
POWER:
├── 5V ──────► From Raspberry Pi (USB)
└── GND ─────► Common GND (L298N, USB, modules)

INPUT / OUTPUT:
├── D2  ─────► BUTTON
├── D8  ─────► BUZZER

SERVO:
├── D10 ─────► SERVO SIGNAL
├── 5V  ─────► SERVO VCC (external 5V from UPS)
└── GND ─────► SERVO GND

ULTRASONIC SENSORS:
├── US0 (FIXED)
│   ├── A1 ─────► TRIG
│   └── A0 ─────► ECHO
│
└── US1 (SERVO-MOUNTED)
    ├── A2 ─────► TRIG
    └── A3 ─────► ECHO

MOTOR DRIVER (L298N):
├── D6  ─────► RIGHT MOTOR PWM
├── D7  ─────► RIGHT DIR1
├── D9  ─────► RIGHT DIR2
│
├── D3  ─────► LEFT MOTOR PWM
├── D4  ─────► LEFT DIR1
└── D5  ─────► LEFT DIR2

LED STRIPS (NEOPIXEL):
├── D13 ─────► STRIP 1 DATA
└── D12 ─────► STRIP 2 DATA

VL53L0X:
├── VCC ─────► 5V
├── GND ─────► GND
├── SDA ─────► A4
└── SCL ─────► A5
```

</details>

<details>
<summary><b>View Power Arduino 1 Wiring</b></summary>

### **ARDUINO (DEV1):**
#### Libraries:
```
IRremote.h
```
```
POWER:
├── 5V ──────► From Raspberry Pi (USB)
└── GND ─────► Common GND (USB, modules)

IR REMOTE:
├── D5 ──────► IR RECEIVER SIGNAL
├── 5V ──────► IR RECEIVER VCC
└── GND ─────► IR RECEIVER GND

LIGHTS:
├── D2 ──────► FRONT LIGHT (+ via MOSFET)
└── D3 ──────► BACK LIGHT (+ via MOSFET)

SENSORS (ANALOG):
├── A0 ──────► METAL SENSOR
├── A1 ──────► PHOTORESISTOR (LIGHT SENSOR)
├── A2 ──────► UV SENSOR
└── A3 ──────► BALL SWITCH (digital read but on analog pin)

SENSORS (DIGITAL):
├── D4  ─────► PIR MOTION SENSOR
├── D8  ─────► LINE FOLLOWER LEFT
├── D10 ─────► LINE FOLLOWER MID
└── D9  ─────► LINE FOLLOWER RIGHT
```

</details>

> [!TIP]
> **Pro-Tip:** Make sure all modules share a common ground (GND) for stable operation.

---
## 🌐 Connectivity & Controls

<details>
<summary><b>Connectivity & Controls</b></summary>

### Network Configuration
| Parameter | Value |
| :--- | :--- |
| **SSID** | `NORA` |
| **Password** | `12345678` |

### RIFT Integration
To connect via [RIFT](https://github.com/CursedPrograms/RIFT), ensure KIDA01 is active on:
* `localhost:5004`

</details>

---

## Installation

### MX500 AI Camera

<details>
<summary><b>View MX500 AI Camera Setup</b></summary>

```bash
sudo apt update && sudo apt full-upgrade
```
```bash
sudo apt install imx500-models
```
```bash
rpicam-hello --list-cameras
```
#### AI Camera Object Detection (Realtime)
```bash
rpicam-hello --camera 1 -t 0 \
  --post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json \
  --viewfinder-width 1920 \
  --viewfinder-height 1080 \
  --framerate 30
```
#### AI Camera Object Detection (Video)
```bash
rpicam-vid --camera 1 -t 10s -o output.264 
--post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json 
--width 1920 
--height 1080 
--framerate 30
```

#### AI Camera Pose Estimation (Realtime)

```bash
rpicam-hello --camera 1 -t 0s 
--post-process-file /usr/share/rpi-camera-assets/imx500_posenet.json 
--viewfinder-width 1920 
--viewfinder-height 1080 
--framerate 30
```
#### Picamera2

```bash
sudo apt install python3-opencv python3-munkres
```
```bash
python imx500_object_detection_demo.py --model /usr/share/imx500-models/imx500_network_ssd_mobilenetv2_fpnlite_320x320_pp.rpk
```
```bash
python imx500_pose_estimation_higherhrnet_demo.py
```

#### Documentation
https://www.raspberrypi.com/documentation/accessories/ai-camera.html
https://github.com/raspberrypi/picamera2/tree/main/examples/imx500


</details>

---
### Install Ollama

<details>
<summary><b>View Ollama Setup</b></summary>

```bash
sudo snap install ollama
ollama --version
```

#### Pull Ollama Model

```bash
ollama pull gemma3:4b-it-qat
```
#### Run Ollama Model
```bash
ollama run deepseek-r1:1.5b
```

</details>

---
### Environment Setup

<details>
<summary><b>View Environment Setup</b></summary>

```bash
sudo apt update
sudo apt install python3-venv python3-pip

python3 -m venv ~/kida-venv
source ~/kida-venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

</details>

---
### Install OpenAI Whisper

<details>
<summary><b>View Whisper Setup</b></summary>

```bash
pip install git+https://github.com/openai/whisper.git
```

```bash
python3 -c "import whisper; whisper.load_model('large')"
python3 -c "import whisper; whisper.load_model('tiny')"
```

</details>

---
### Install Audio Dependencies

<details>
<summary><b>View Audio Setup</b></summary>

```bash
sudo apt install ffmpeg alsa-utils -y pulseaudio jackd2 alsa-utils portaudio19-dev python3-pyaudio
```

</details>

---
### Install Piper TTS

<details>
<summary><b>View Piper Setup</b></summary>

```bash
pip install piper-tts
```
#### Download Voices

```bash
mkdir -p ~/voices/

# Amy (medium) — recommended
wget "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx?download=true" -O en_US-amy-medium.onnx
wget "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json?download=true" -O en_US-amy-medium.onnx.json
``` 

#### Test Piper

```bash
echo "Hello, I am your voice assistant." | \
piper --model voices/en_US-amy-medium.onnx \
--output_raw | aplay -D plughw:2,0 -r 22050 -f S16_LE -t raw -
```

#### Install Piper binary (Not Needed)

```bash
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz
tar xzf piper_linux_x86_64.tar.gz
sudo mv piper/piper /usr/local/bin/
```

</details>

---
### Install ElevenLabs (optional)

<details>
<summary><b>View ElevenLabs Setup</b></summary>

```bash
pip install git+https://github.com/elevenlabs/elevenlabs-python@v3
```

</details>

---
### Install & Set Up Hailo

<details>
<summary><b>View Hailo8l Setup</b></summary>

```bash
sudo apt update
sudo apt install hailo-all
```
### Test Hailo
- Verify the installation:
```bash
hailortcli fw-control identify
```
- Expected output:
```
Device: Hailo-8l
PCIe Address: 0001:03:00.0
Firmware Version: x.x.x
```

**Troubleshooting:** 
- If the driver is not detected after install, a DKMS module may have failed to build. Pin back to version 4.19 which has stable kernel module support:
```bash
sudo apt-mark hold linux-image-rpi-2712 linux-headers-rpi-2712
sudo apt install hailort=4.19.0 hailo-all=4.19.0 -y
sudo apt-mark hold hailort hailo-all
sudo reboot
```

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

</details>

---

```bash

apt-get update
apt-get install -y libsm6 libxext6 libxrender-dev
pip install opencv-contrib-python
pip install opencv_transforms
pip install opencv-python
pip install facenet-pytorch
pip install piper-tts
pip install git+https://github.com/openai/whisper.git
sudo apt install pulseaudio jackd2 alsa-utils portaudio19-dev python3-pyaudio imx500-models

https://download.pytorch.org/whl/cpu/torch-1.0.1.post2-cp36-cp36m-linux_x86_64.whl
https://download.pytorch.org/whl/cpu/torch-1.0.1.post2-cp37-cp37m-linux_x86_64.whl

```

---

#### InceptionResnetV1

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

#### Pre-processing
```bash
# Basic debugging
from opencv_transforms.debug import utils
result = utils.compare_contrast_outputs(image, contrast_factor=0.5)

# Create test summary across multiple contrast factors
summary = utils.create_contrast_test_summary(image)

# Analyze PIL precision issues
utils.analyze_pil_precision_issue(image)
```
#### Detection Pipeline

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
/boot/firmware/config.txt

- Enable PCIe Gen 3 speeds for the Hailo Hat
dtparam=pciex1_gen=3

---

### Autostart on Boot

#### Option A: systemd service (recommended)

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
---
#### Option B: Camera preview service

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
---
#### Option C: crontab

```bash
crontab -e
# Add:
@reboot cd /home/kida-01/Desktop/Kida-Robot && python3 main.py &
```
---
#### Option D: Desktop autostart

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

### RTC Setup

```bash
dtparam=rtc_bbat_vchg=3000000
sudo mount -o remount,rw /boot/firmware
sudo nano /boot/firmware/config.txt
sudo hwclock -w
sudo hwclock -v -r
```

---

### Diagnostics

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
