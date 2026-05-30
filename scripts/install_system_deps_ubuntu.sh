#!/usr/bin/env bash
set -euo pipefail

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This script is for Ubuntu/Debian systems with apt-get." >&2
  exit 1
fi

sudo apt-get update
sudo apt-get install -y \
  git \
  curl \
  wget \
  build-essential \
  v4l-utils \
  ffmpeg \
  gstreamer1.0-tools \
  gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good \
  gstreamer1.0-plugins-bad \
  gstreamer1.0-plugins-ugly \
  gstreamer1.0-libav

echo
echo "System dependencies installed."
echo "Install Miniconda/Anaconda separately if conda is not available yet."
