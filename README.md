# Fan Controller for Server Hardware

This repository contains a Python script to control the cooling fans of a server based on temperature readings from CPU and motherboard (MB) sensors. It uses the IPMI tool to interact with server hardware and adjust fan speeds dynamically. The goal is to maintain optimal temperature ranges for the CPU and motherboard, reducing fan noise when temperatures are stable, and ramping up the fan speeds when temperatures increase beyond desired levels.

## Features

- **PID Control for CPU and MB Temperatures**: Uses a Proportional-Integral-Derivative (PID) controller to adjust fan speeds based on temperature readings from the CPU and motherboard.
- **Hysteresis for Fan Activation**: Avoids constant fan switching by using hysteresis logic for both CPU and MB temperature.
- **Dynamic Fan Speed Adjustment**: Fans speed is dynamically adjusted based on temperature thresholds and PID outputs.
- **Logging**: Logs temperature and fan speed changes for easy monitoring.
- **IPMI Integration**: Uses `ipmitool` to set fan speeds via the IPMI interface.

## Requirements

- Python 3.x
- `PID` library (can be installed via `pip install pid`)
- `ipmitool` installed and accessible via the command line
- Access to IPMI interface for fan control
- A Linux-based system for running the script (or compatible OS)

## Setup Instructions

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yourusername/fan-controller.git
   cd fan-controller
