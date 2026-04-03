#!/bin/bash
sudo apt update
sudo apt install -y git curl ffmpeg libportaudio2 \
    build-essential python3.13-dev gfortran libblas-dev liblapack-dev
sudo curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="/usr/local/bin" INSTALLER_NO_MODIFY_PATH=1 sudo -E sh
#source $HOME/.local/share/../bin/env
uv venv --python 3.13
source .venv/bin/activate
uv init --bare
uv python pin 3.13
uv add ephem sounddevice "numpy<2" noise