import os
import uuid
import plistlib
import threading
from flask import Flask, request, jsonify, send_file, send_from_directory, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

conversion_jobs = {}

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Make sure ffmpeg installed by build.sh is on PATH (for Render)
_ffmpeg_dir = '/opt/render/project/.ffmpeg'
if os.path.isdir(_ffmpeg_dir) and _ffmpeg_dir not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _ffmpeg_dir + ':' + os.environ.get('PATH', '')


def _ydl_opts(out_tmpl, hook=None):
    opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '256',
        }],
        'outtmpl': out_tmpl,
        'quiet': True,
        'no_warnings': True,
        # Bypass YouTube bot detection and improve format detection
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'web', 'mweb'],
                'skip': ['hls', 'dash']
            }
        },
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) '
                'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
            ),
        },
        'cookiefile': 'cookies.txt',
        'ignoreerrors': True,
    }
    if hook:
        opts['progress_hooks'] = [hook]
    return opts


def progress_hook(d, job_id):
    if job_id not in conversion_jobs:
        return
    if d['status'] == 'downloading':
        raw = d.get('_percent_str', '0%').replace('%', '').strip()
        try:
            conversion_jobs[job_id]['progress'] = float(raw)
            conversion_jobs[job_id]['status'] = 'downloading'
        except Exception:
            pass
    elif d['status'] == 'finished':
        conversion_jobs[job_id]['progress'] = 99
        conversion_jobs[job_id]['status'] = 'processing'


def run_conversion(url, job_id):
    out_tmpl = os.path.join(DOWNLOAD_DIR, f'{job_id}.%(ext)s')
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(out_tmpl, lambda d: progress_hook(d, job_id))) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'audio')

        mp3_path = os.path.join(DOWNLOAD_DIR, f'{job_id}.mp3')
        if not os.path.exists(mp3_path):
            raise FileNotFoundError('MP3 file not found after conversion')

        conversion_jobs[job_id].update({
            'status': 'completed', 'progress': 100,
            'title': title, 'filename': f'{job_id}.mp3', 'path': mp3_path,
        })
    except Exception as e:
        conversion_jobs[job_id].update({'status': 'error', 'error': str(e)})


# ── Async convert (for the web UI) ────────────────────────────────────────────
@app.route('/api/convert', methods=['POST'])
def convert():
    data = request.get_json(force=True)
    url = (data.get('url') or '').strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    job_id = str(uuid.uuid4())
    conversion_jobs[job_id] = {'status': 'starting', 'progress': 0, 'url': url}
    threading.Thread(target=run_conversion, args=(url, job_id), daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/status/<job_id>', methods=['GET'])
def get_status(job_id):
    job = conversion_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    return jsonify(job)


@app.route('/api/download/<job_id>', methods=['GET'])
def download_mp3(job_id):
    job = conversion_jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Job not found'}), 404
    if job.get('status') != 'completed':
        return jsonify({'error': 'Not ready', 'status': job.get('status')}), 202

    mp3_path = job.get('path')
    if not mp3_path or not os.path.exists(mp3_path):
        return jsonify({'error': 'File not found on server'}), 404

    title = job.get('title', 'audio')
    safe = ''.join(c for c in title if c.isalnum() or c in ' -_').strip()[:80]
    return send_file(mp3_path, mimetype='audio/mpeg',
                     as_attachment=True, download_name=f'{safe or "audio"}.mp3')


# ── Sync convert (for the Shortcut – waits and returns the MP3 directly) ──────
@app.route('/api/sync', methods=['POST', 'GET'])
def sync_convert():
    if request.method == 'POST':
        data = request.get_json(force=True)
        url = (data.get('url') or '').strip()
    else:
        url = (request.args.get('url') or '').strip()

    if not url:
        return jsonify({'error': 'URL is required'}), 400

    job_id = str(uuid.uuid4())
    out_tmpl = os.path.join(DOWNLOAD_DIR, f'{job_id}.%(ext)s')

    # Run synchronously (the Shortcut waits here until done)
    try:
        with yt_dlp.YoutubeDL(_ydl_opts(out_tmpl)) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'audio')

        mp3_path = os.path.join(DOWNLOAD_DIR, f'{job_id}.mp3')
        if not os.path.exists(mp3_path):
            raise FileNotFoundError('MP3 not found after conversion')

        safe = ''.join(c for c in title if c.isalnum() or c in ' -_').strip()[:80]
        return send_file(mp3_path, mimetype='audio/mpeg',
                         as_attachment=True, download_name=f'{safe or "audio"}.mp3')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── Serve the Shortcut file so user can install it in one tap ────────────────
@app.route('/get-shortcut')
def serve_shortcut():
    server_url = request.url_root.rstrip('/')

    # The extension input (shared YouTube URL) as a WFTextTokenString attachment
    ext_input = {
        'Value': {
            'attachmentsByRange': {'{0, 1}': {'Type': 'ExtensionInput'}},
            'string': '\ufffc',
        },
        'WFSerializationType': 'WFTextTokenString',
    }

    actions = [
        # 1. POST YouTube URL to our sync endpoint → gets back the MP3 file
        {
            'WFWorkflowActionIdentifier': 'is.workflow.actions.downloadurl',
            'WFWorkflowActionParameters': {
                'WFHTTPMethod': 'POST',
                'WFURL': server_url + '/api/sync',
                'WFHTTPBodyType': 'JSON',
                'WFJSONValues': {
                    'Value': {
                        'WFDictionaryFieldValueItems': [
                            {
                                'WFItemType': 0,
                                'WFKey': {
                                    'Value': {'string': 'url'},
                                    'WFSerializationType': 'WFTextTokenString',
                                },
                                'WFValue': ext_input,
                            }
                        ]
                    },
                    'WFSerializationType': 'WFDictionaryFieldValue',
                },
                'ShowResult': False,
            },
        },
        # 2. Add the returned MP3 to Apple Music Library
        {
            'WFWorkflowActionIdentifier': 'is.workflow.actions.music.addtomusic',
            'WFWorkflowActionParameters': {},
        },
    ]

    shortcut = {
        'WFWorkflowClientVersion': '1155.10',
        'WFWorkflowActions': actions,
        'WFWorkflowHasOutputFallback': False,
        'WFWorkflowIcon': {
            'WFWorkflowIconGlyphNumber': 59530,
            'WFWorkflowIconStartColor': -1672014593,
        },
        'WFWorkflowImportQuestions': [],
        'WFWorkflowInputContentItemClasses': ['WFURLContentItem'],
        'WFWorkflowMinimumClientVersion': 900,
        'WFWorkflowMinimumClientVersionString': '900',
        'WFWorkflowName': 'YT → Apple Music',
        'WFWorkflowNoInputBehavior': {
            'Name': 'WFWorkflowNoInputBehaviorAskForInput',
            'Parameters': {'Class': 'WFURLContentItem'},
        },
        'WFWorkflowOutputContentItemClasses': [],
        'WFWorkflowTypes': ['NCWidget', 'WatchKit'],
    }

    data = plistlib.dumps(shortcut, fmt=plistlib.FMT_XML)
    return Response(
        data,
        mimetype='application/vnd.apple.shortcut',
        headers={'Content-Disposition': 'attachment; filename="YT_to_Apple_Music.shortcut"'},
    )


# ── Web UI ────────────────────────────────────────────────────────────────────
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
