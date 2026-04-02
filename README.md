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

# KIDA: Kinetic Interactive Drive Automaton

<div align="center">
  <img src="/images/background.jpeg" alt="KIDA Robot" width="600"/>
</div>

## Overview

KIDA is an advanced autonomous robot platform built on Raspberry Pi 5, featuring dual-camera vision (night vision + AI camera), a Hailo-8 AI accelerator (13 TOPS), and local LLM capabilities. The robot supports voice interaction, autonomous navigation, and real-time AI inference.

---

<div align="center">
  <img src="/images/demo/KIDA001.jpg" alt="KIDA Robot" width="600"/>
</div>

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

### Python Requirements
```
playsound
openai-whisper
sounddevice
numpy
whisper
SpeechRecognition
pygame
requests
elevenlabs==0.2.26
torch
torchaudio
```

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
