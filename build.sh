#!/usr/bin/env bash
# Render free tier build script
# Install ffmpeg via static binary (no sudo needed)
set -e

pip install -r requirements.txt

# Download a static ffmpeg build if not already present
if ! command -v ffmpeg &> /dev/null; then
    echo "Installing ffmpeg..."
    mkdir -p /opt/render/project/.ffmpeg
    cd /opt/render/project/.ffmpeg
    curl -L https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz \
         -o ffmpeg.tar.xz
    tar -xf ffmpeg.tar.xz --strip-components=2 --wildcards '*/bin/ffmpeg'
    chmod +x ffmpeg
    export PATH="/opt/render/project/.ffmpeg:$PATH"
    echo "ffmpeg installed: $(./ffmpeg -version 2>&1 | head -1)"
    cd -
fi
