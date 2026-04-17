import os
import uuid
import threading
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
import yt_dlp

# Make sure ffmpeg installed by build.sh is on PATH (for Render)
_ffmpeg_dir = '/opt/render/project/.ffmpeg'
if os.path.isdir(_ffmpeg_dir) and _ffmpeg_dir not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _ffmpeg_dir + ':' + os.environ.get('PATH', '')

app = Flask(__name__)
CORS(app)

# In-memory job store
conversion_jobs = {}

# Save converted files in a temp folder relative to app
DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def progress_hook(d, job_id):
    if job_id not in conversion_jobs:
        return
    if d['status'] == 'downloading':
        raw = d.get('_percent_str', '0%').replace('%', '').strip()
        try:
            conversion_jobs[job_id]['progress'] = float(raw)
        except Exception:
            pass
    elif d['status'] == 'finished':
        conversion_jobs[job_id]['progress'] = 99
        conversion_jobs[job_id]['status'] = 'processing'


def run_conversion(url, job_id):
    out_tmpl = os.path.join(DOWNLOAD_DIR, f'{job_id}.%(ext)s')

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '256',
        }],
        'outtmpl': out_tmpl,
        'progress_hooks': [lambda d: progress_hook(d, job_id)],
        'quiet': True,
        'no_warnings': True,
        # Bypass YouTube bot detection on cloud IP by pretending to be iOS app
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'web'],
            }
        },
        'http_headers': {
            'User-Agent': (
                'com.google.ios.youtube/19.29.1 '
                '(iPhone16,2; U; CPU iOS 17_5_1 like Mac OS X;)'
            ),
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'audio')

        # Find the .mp3 file written by ffmpeg
        mp3_path = os.path.join(DOWNLOAD_DIR, f'{job_id}.mp3')
        if not os.path.exists(mp3_path):
            raise FileNotFoundError('MP3 file not found after conversion')

        conversion_jobs[job_id].update({
            'status': 'completed',
            'progress': 100,
            'title': title,
            'filename': f'{job_id}.mp3',
            'path': mp3_path,
        })

    except Exception as e:
        conversion_jobs[job_id].update({
            'status': 'error',
            'error': str(e),
        })


# ─────────────────────────────────────────────
# API: Start conversion
# POST /api/convert   body: {"url": "https://youtube.com/..."}
# ─────────────────────────────────────────────
@app.route('/api/convert', methods=['POST'])
def convert():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    job_id = str(uuid.uuid4())
    conversion_jobs[job_id] = {
        'status': 'starting',
        'progress': 0,
        'url': url,
    }

    t = threading.Thread(target=run_conversion, args=(url, job_id), daemon=True)
    t.start()

    return jsonify({'job_id': job_id})


# ─────────────────────────────────────────────
# API: Poll job status
# GET /api/status/<job_id>
# ─────────────────────────────────────────────
@app.route('/api/status/<job_id>', methods=['GET'])
def get_status(job_id):
    job = conversion_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)


# ─────────────────────────────────────────────
# API: Download the finished MP3
# GET /api/download/<job_id>
# This is what the iOS Shortcut calls to get the actual file.
# ─────────────────────────────────────────────
@app.route('/api/download/<job_id>', methods=['GET'])
def download_mp3(job_id):
    job = conversion_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if job.get('status') != 'completed':
        return jsonify({'error': 'Not ready yet', 'status': job.get('status')}), 202

    mp3_path = job.get('path')
    if not mp3_path or not os.path.exists(mp3_path):
        return jsonify({'error': 'File not found on server'}), 404

    title = job.get('title', 'audio')
    # Sanitize title for filename
    safe_title = ''.join(c for c in title if c.isalnum() or c in ' -_').strip()[:80]
    download_name = f'{safe_title}.mp3' if safe_title else 'audio.mp3'

    return send_file(
        mp3_path,
        mimetype='audio/mpeg',
        as_attachment=True,
        download_name=download_name,
    )


# ─────────────────────────────────────────────
# Serve web UI
# ─────────────────────────────────────────────
@app.route('/')
def index():
    try:
        with open(os.path.join(os.path.dirname(__file__), 'index.html'), 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return 'index.html not found', 404


@app.route('/index.css')
def css():
    return send_from_directory(os.path.dirname(__file__), 'index.css')


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f'Server running on port {port}')
    app.run(host='0.0.0.0', port=port, debug=False)
