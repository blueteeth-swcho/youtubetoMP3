#!/usr/bin/env bash
# Render free tier build script
set -e

# Install requirements
pip install -r requirements.txt

# Setup ffmpeg directory
FFMPEG_DIR="/opt/render/project/.ffmpeg"
mkdir -p "$FFMPEG_DIR"

# Download static ffmpeg if not present
if [ ! -f "$FFMPEG_DIR/ffmpeg" ]; then
    echo "Installing ffmpeg..."
    cd "$FFMPEG_DIR"
    # Using a simpler direct download of the binary if possible, or a standard tar
    curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o ffmpeg.tar.xz
    tar -xJf ffmpeg.tar.xz --strip-components=1
    # Ensure the binary is in the right place
    [ -f "./ffmpeg" ] || find . -name ffmpeg -exec cp {} . \;
    chmod +x ffmpeg
    echo "ffmpeg installed: $(./ffmpeg -version | head -n 1)"
    cd -
fi
