[![Twitter: @NorowaretaGemu](https://img.shields.io/badge/X-@NorowaretaGemu-blue.svg?style=flat)](https://x.com/NorowaretaGemu)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

<br>
<div align="center">
  <a href="https://ko-fi.com/cursedentertainment">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="ko-fi" style="width: 20%;"/>
  </a>
</div>
<br>
<div align="center">
  <img alt="Batch" src="https://img.shields.io/badge/rasberrypi-%23323330.svg?&style=for-the-badge&logo=windows&logoColor=white"/>
</div>
<div align="center">
  <img alt="Python" src="https://img.shields.io/badge/python%20-%23323330.svg?&style=for-the-badge&logo=python&logoColor=white"/>
</div>
<div align="center">
    <img alt="Git" src="https://img.shields.io/badge/git%20-%23323330.svg?&style=for-the-badge&logo=git&logoColor=white"/>
  <img alt="PowerShell" src="https://img.shields.io/badge/PowerShell-%23323330.svg?&style=for-the-badge&logo=powershell&logoColor=white"/>
  <img alt="Shell" src="https://img.shields.io/badge/Shell-%23323330.svg?&style=for-the-badge&logo=gnu-bash&logoColor=white"/>
  <img alt="Batch" src="https://img.shields.io/badge/Batch-%23323330.svg?&style=for-the-badge&logo=windows&logoColor=white"/>
</div>
<br>

# KIDA: Kinetic Interactive Drive Automaton

<div align="center">
  <img src="images/kida_robot.jpg" alt="KIDA Robot" width="600"/>
</div>

## Overview

KIDA is an advanced autonomous robot platform built on Raspberry Pi 5, featuring dual-camera vision (night vision + AI camera), Hailo-8 AI accelerator (13 TOPS), and local LLM capabilities. The robot supports voice interaction, autonomous navigation, and real-time AI inference.

## Software Stack

### Operating System
- **Recommended:** Raspberry Pi OS (Bookworm)
- **Kernel:** 6.12.62+rpt-rpi-2712

### AI & ML
| Component | Technology |
|-----------|------------|
| LLM | Ollama (DeepSeek-R1:1.5b, Gemma3:4b) |
| STT | OpenAI Whisper |
| TTS | Piper / ElevenLabs API |
| Vision | Hailo-8 AI Processor, IMX500 |

## Hardware Specifications

### Chassis & Motion
- **Chassis:** XiaoR Geek Robot Tank Chassis
- **Motor Driver:** L298N (2x)
- **Motors:** Dual DC motors with tank steering

### Computing
- **Main Board:** Raspberry Pi 5/4
- **AI Accelerator:** Hailo-8 (13 TOPS) on NVME+AI Hat
- **Storage:** NVME SSD

### Power System
- **Primary Battery:** 3x 21700 (12.6V) in series
- **Backup Battery:** 3x 18650 via Pi UPS
- **Voltage Regulator:** LM2596S (12V → 5V)
- **Power Switches:** 2x (Main + Pi)

### Sensors & Cameras
- **Camera 0:** Raspberry Pi Nightvision Camera
- **Camera 1:** Raspberry Pi AI Camera (with IMX500)
- **Ultrasonic Sensor:** 1x HC-SR04
- **Microphone:** USB Microphone

### Audio
- **Output:** Pi Speakers
- **TTS:** Piper / ElevenLabs

dtparam=rtc_bbat_vchg=3000000
sudo mount -o remount,rw /boot/firmware
sudo nano /boot/firmware/config.txt
sudo hwclock -w
sudo hwclock -v -r

cd /home/kida-01/Desktop/Kida-Robot
source venv/bin/activate
python scripts/main.py
sudo apt install pulseaudio jackd2 alsa-utils

1. Copy Splash Screen and Set Permissions
sudo cp /home/kida-01/Downloads/splash.png /usr/share/plymouth/themes/pix/splash.png
sudo chmod 644 /usr/share/plymouth/themes/pix/splash.png
sudo chown root:root /usr/share/plymouth/themes/pix/splash.png

2. Update System and Install Hailo All-in-One Package (If available)
sudo apt update
sudo apt install hailo-all

3. Verify Hailo Runtime Installation
hailortcli fw-control identify

Expected output:
Device: Hailo-8
PCIe Address: 0001:03:00.0
Firmware Version: x.x.x

4. Python Connectivity Test Script (Optional)
import subprocess

def check_hailo():
    try:
        result = subprocess.check_output(["hailortcli", "fw-control", "identify"]).decode()
        print("✅ Hailo connected:\n", result)
    except Exception as e:
        print("❌ Hailo not detected:", e)

check_hailo()

5. If HailoRT is NOT installed, Manual Build Instructions:
sudo apt update
sudo apt install -y git build-essential cmake python3-dev python3-pip
git clone https://github.com/hailo-ai/hailort.git
cd hailort
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install

git clone https://github.com/protocolbuffers/protobuf.git
cd protobuf
mkdir build && cd build
cmake ..
make -j$(nproc)
sudo make install

echo "export LD_LIBRARY_PATH=/usr/local/lib:$LD_LIBRARY_PATH" >> ~/.bashrc
source ~/.bashrc
pip install hailort
hailortcli fw-control identify

# 1. Make sure you have venv and pip installed
sudo apt update
sudo apt install python3-venv python3-pip

# 2. Create a virtual environment
python3 -m venv ~/kida-venv

# 3. Activate the environment
source ~/kida-venv/bin/activate

# 4. Install whisper inside the venv
pip install --upgrade pip
pip install git+https://github.com/openai/whisper.git

cd /home/kida-01/Desktop/Kida-Robot && python3 main.py &
sudo crontab -e
@reboot cd /home/kida-01/Desktop/Kida-Robot && python3 main.py &
ctrl+x ctrl+s

source ~/kida-venv/bin/activate
python3 /home/kida-01/Desktop/Kida-Robot/main.py
python3 /home/kida-01/Desktop/Kida-Robot/pi-chat.py

sudo nano /etc/systemd/system/kida-camera.service

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

sudo systemctl daemon-reload
sudo systemctl enable kida-camera.service
sudo systemctl start kida-camera.service

sudo systemctl status kida-camera.service
journalctl -u kida-camera.service -f

sudo fuser -v /dev/video0

ps -ef | grep -i camera

sudo -u kida-01 DISPLAY=:0 /usr/bin/python3 /home/kida-01/Desktop/Kida-Robot/scripts/camera_preview.py

ps aux | grep -E 'libcamera|picamera'
sudo kill -9 <PID>

sudo apt install -y portaudio19-dev python3-pyaudio

libcamera-hello

sudo -u kida-01 DISPLAY=:0 /usr/bin/python3 /home/kida-01/Desktop/Kida-Robot/scripts/camera_preview.py

# 1. Make sure you have venv and pip installed
sudo apt update
sudo apt install python3-venv python3-pip

# 2. Create a virtual environment
python3 -m venv ~/kida-venv

# 3. Activate the environment
source ~/kida-venv/bin/activate

# 4. Install whisper inside the venv
pip install --upgrade pip
pip install git+https://github.com/openai/whisper.git

cd /home/kida-01/Desktop/Kida-Robot && python3 main.py &
sudo crontab -e
@reboot cd /home/kida-01/Desktop/Kida-Robot && python3 main.py &
ctrl+x ctrl+s

source ~/kida-venv/bin/activate
python3 /home/kida-01/Desktop/Kida-Robot/main.py
python3 /home/kida-01/Desktop/Kida-Robot/pi-chat.py

sudo nano /etc/systemd/system/kida-camera.service


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



sudo systemctl daemon-reload
sudo systemctl enable kida-camera.service
sudo systemctl start kida-camera.service

sudo systemctl status kida-camera.service
journalctl -u kida-camera.service -f

sudo fuser -v /dev/video0

ps -ef | grep -i camera

sudo -u kida-01 DISPLAY=:0 /usr/bin/python3 /home/kida-01/Desktop/Kida-Robot/scripts/camera_preview.py

ps aux | grep -E 'libcamera|picamera'
sudo kill -9 <PID>

sudo apt install -y portaudio19-dev python3-pyaudio


libcamera-hello

sudo -u kida-01 DISPLAY=:0 /usr/bin/python3 /home/kida-01/Desktop/Kida-Robot/scripts/camera_preview.py

lsmod | grep hailo
hailortcli fw-control identify


List Cameras

rpicam-hello --list-cameras

rpicam-hello -t 0s --post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json --viewfinder-width 1920 --viewfinder-height 1080 --framerate 30

Pi AI Camera Inference

rpicam-hello --camera 1 -t 0 \
--post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json \
--viewfinder-width 1920 \
--viewfinder-height 1080 \
--framerate 30


Activate venv

cd /home/kida-01/Desktop/Kida-Robot/
source venv/bin/activate
ollama run deepseek-r1:1.5b


pip install piper-tts

(venv) kida-01@kida01:~/Desktop/Kida-Robot $ ollama pull gemma3:4b-it-qat


kida-01@kida01:~ $ hailortcli fw-control identify
[HailoRT] [error] Can't find hailort driver class. Can happen if the driver is not installed, if the kernel was updated or on some driver failure (then read driver dmesg log)
[HailoRT] [error] CHECK_SUCCESS failed with status=HAILO_DRIVER_NOT_INSTALLED(64) - Failed listing hailo devices
[HailoRT] [error] CHECK_SUCCESS failed with status=HAILO_DRIVER_NOT_INSTALLED(64)
[HailoRT] [error] CHECK_SUCCESS failed with status=HAILO_DRIVER_NOT_INSTALLED(64)
[HailoRT] [error] CHECK_SUCCESS failed with status=HAILO_DRIVER_NOT_INSTALLED(64)
[HailoRT] [error] CHECK_SUCCESS failed with status=HAILO_DRIVER_NOT_INSTALLED(64)
[HailoRT CLI] [error] CHECK_SUCCESS failed with status=HAILO_DRIVER_NOT_INSTALLED(64)
kida-01@kida01:~ $ uname -r  
6.12.62+rpt-rpi-2712
kida-01@kida01:~ $ lsmod | grep hailo 
kida-01@kida01:~ $ sudo dmesg | grep hailo 
kida-01@kida01:~ $ lspci | grep Hailo 
0001:03:00.0 Co-processor: Hailo Technologies Ltd. Hailo-8 AI Processor (rev 01)
kida-01@kida01:~ $ sudo apt update && sudo apt full-upgrade -y

sudo dpkg --configure -a
sudo apt --fix-broken install -y

lsmod | grep hailo
hailortcli fw-control identify

Step 2 — Reboot (Hailo userspace is already installed)
bashsudo reboot
Step 3 — After reboot, verify Hailo works
bashlsmod | grep hailo
hailortcli fw-control identify
If lsmod still shows nothing after the reboot, the DKMS module didn't build. In that case pin back to 4.19 which has stable kernel module support:
bash# Hold the current kernel so it stops trying to upgrade
sudo apt-mark hold linux-image-rpi-2712 linux-headers-rpi-2712

# Downgrade only the Hailo driver to 4.19
sudo apt install hailort=4.19.0 hailo-all=4.19.0 -y
sudo apt-mark hold hailort hailo-all

sudo reboot
Step 4 — After reboot confirm
bash# Should show hailo_pci
lsmod | grep hailo

# Should show device info
hailortcli fw-control identify
You should see Board Name: Hailo-8 and matching firmware/driver versions. The lspci already confirmed the hardware is seated correctly so once the module loads it should work immediately.



## Rasberry Pi 5 Robot

pip install git+https://github.com/elevenlabs/elevenlabs-python@v3

### OS:
Rasberry OS [Recommended!] (you can use any distro you choose)

### Parts:

- Robot Tank Chassis (XiaoR Geek [Recommended!])
- L298N Motor Driver
- Rasberry Pi 5/4
- Pi Speakers
- 3x 16850 Pi UPS*
- Pi NVME + AI Hat
- 1x Pi 5 Nightvision Camera (Slot 0)
- 1x Pi 5 AI Camera Camera (Slot 1)
- 2x Pi Camera Holder
- Servo Motor
- NVME
- HAILO 13 TOPS
- 1x Ultrasonic Senser
- 2 x Power Switches
- DuPont Cables
- 3x 21700 Batteries
- 3 21700 Sieries Batterholder
- 3x 16850 Batteries*
- 1 USB Microphone
- 22 AWG Wire (21700 Battery Pack to L298N)

### Electonic Schematic:

#### Motor A (Left)
L298N Pin	Function	Pi GPIO
IN1	Direction	GPIO 17
IN2	Direction	GPIO 27
ENA	Speed (PWM)	GPIO 18 (hardware PWM capable)*

#### Motor B (Right)
L298N Pin	Function	Pi GPIO
IN3	Direction	GPIO 22
IN4	Direction	GPIO 23

(11.1V)

[12V Battery Pack 3S 21700 Battery 3.7v]
 ├── + ─────────► L298N VS       (motor power input)
 ├── + ─────────► LM2596S IN+    (step-down input for Pi)
 ├── – ─────────► L298N GND
 └── – ─────────► LM2596S IN–

[LM2596S Output]
 ├── OUT+ ──────► Pi 5V (GPIO pin 2 [[Not Recommended!] Pi UPS via USB-C cable [Recommended!]])
 └── OUT– ──────► Pi GND (GPIO pin 6 or 9)

## How to Run:

### Install Requirements

Using Python directly:
pip install -r requirements.txt

Or run: 
- install_requirements.bat

<br>

~/.config/autostart

nano ~/.config/autostart/kida.desktop

[Desktop Entry]
Name=KIDA Controller
Exec=python3 /home/pi/path/to/main.py
Type=Application
X-GNOME-Autostart-enabled=true

### FFMpeg Setup (Windows)

1. Download FFMpeg  
   Visit the following link and download the latest static build:  
   https://www.gyan.dev/ffmpeg/builds/

2. Extract the Archive  
   Unzip the downloaded archive to C:\.

3. Rename and Organize  
   Rename the extracted folder to ffmpeg, and ensure the following folder structure:

C:\ffmpeg\bin
├── ffmpeg.exe
├── ffplay.exe
└── ffprobe.exe

4. Set Environment Variable (Optional for Global Access)  
   To make ffmpeg accessible system-wide:

   - Open System Properties > Environment Variables
   - Under User variables (for your PC username), find and select Path
   - Click Edit > New and paste:
     C:\ffmpeg\bin
   - Click OK to apply the changes
  
5. Test it
     Close and reopen your terminal (CMD), then type:
    ffmpeg -version
    If it prints the version info, you're good.

CRONTAB:

crontab -e

@reboot python3 /home/pi/path/to/main.py

sudo raspi-config

### Run main.py

Using Python directly:
python main.py

Using provided scripts:

Windows:
- .\run.bat
or
- .\run.ps1

Unix-like systems (Linux/macOS):
- .\run.sh

<br>

## Requirements:

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

<br>
<div align="center">
© Cursed Entertainment 2025
</div>
<br>
<div align="center">
<a href="https://cursed-entertainment.itch.io/" target="_blank">
    <img src="https://github.com/CursedPrograms/cursedentertainment/raw/main/images/logos/logo-wide-grey.png"
        alt="CursedEntertainment Logo" style="width:250px;">
</a>
</div>
<br>
<div align="center">
<a href="https://github.com/SynthWomb" target="_blank" align="center">
    <img src="https://github.com/SynthWomb/synth.womb/blob/main/logos/synthwomb07.png"
        alt="SynthWomb" style="width:200px;"/>
</a>
</div>
