import os
import uuid
import plistlib
import threading
import json
from datetime import datetime
from flask import Flask, request, jsonify, send_file, send_from_directory, Response
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

conversion_jobs = {}

DOWNLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

PODCASTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'podcasts.json')

def load_podcasts():
    if os.path.exists(PODCASTS_FILE):
        try:
            with open(PODCASTS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return []
    return []

def save_podcasts(podcasts):
    with open(PODCASTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(podcasts, f, ensure_ascii=False, indent=2)

# Make sure ffmpeg installed by build.sh is on PATH (for Render)
_ffmpeg_dir = '/opt/render/project/.ffmpeg'
if os.path.isdir(_ffmpeg_dir) and _ffmpeg_dir not in os.environ.get('PATH', ''):
    os.environ['PATH'] = _ffmpeg_dir + ':' + os.environ.get('PATH', '')


def _ydl_opts(out_tmpl, hook=None):
    # Use absolute path for cookies.txt to ensure it's found on Render
    cookie_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'cookies.txt')
    
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
        # Aggressive bypass tactics
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'ios', 'android', 'mweb', 'tvhtml5'],
                'skip': ['hls', 'dash']
            }
        },
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ),
        },
        'cookiefile': cookie_path,
        'nocheckcertificate': True,
        'ignoreerrors': False,
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


# ── Podcast RSS Feed ────────────────────────────────────────────────────────
@app.route('/rss')
def rss_feed():
    server_url = request.url_root.rstrip('/')
    podcasts = load_podcasts()
    
    items_xml = ""
    if not podcasts:
        # Add a dummy welcome item if empty to avoid Apple Podcasts "Not Found" error
        items_xml = f"""
        <item>
            <title>반갑습니다! WatchStream 방송국입니다.</title>
            <enclosure url="https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3" length="0" type="audio/mpeg" />
            <guid>welcome-item</guid>
            <pubDate>{datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0900")}</pubDate>
            <itunes:summary>방송국이 성공적으로 개설되었습니다. 이제 단축어로 영상을 추가하세요!</itunes:summary>
        </item>"""
    
    for p in reversed(podcasts): # Latest first
        items_xml += f"""
        <item>
            <title><![CDATA[{p['title']}]]></title>
            <enclosure url="{server_url}/api/download_direct/{p['filename']}" length="0" type="audio/mpeg" />
            <guid>{p['id']}</guid>
            <pubDate>{p['date']}</pubDate>
            <itunes:author>My WatchStream</itunes:author>
            <itunes:summary>YouTube Audio Stream</itunes:summary>
        </item>"""

    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
    <channel>
        <title>My WatchStream</title>
        <link>{server_url}</link>
        <language>ko-kr</language>
        <itunes:author>Antigravity</itunes:author>
        <itunes:summary>YouTube to Apple Watch Streaming</itunes:summary>
        <itunes:image href="https://raw.githubusercontent.com/yt-dlp/yt-dlp/master/logo.png" />
        {items_xml}
    </channel>
    </rss>"""
    return Response(rss_xml, mimetype='application/rss+xml')


@app.route('/api/download_direct/<filename>')
def download_direct(filename):
    return send_from_directory(DOWNLOAD_DIR, filename)


# ── Add to Watch (for the Shortcut) ──────────────────────────────────────────
@app.route('/api/watch', methods=['POST', 'GET'])
def add_to_watch():
    url = (request.args.get('url') or (request.json.get('url') if request.is_json else '')).strip()
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    job_id = str(uuid.uuid4())
    out_tmpl = os.path.join(DOWNLOAD_DIR, f'{job_id}.%(ext)s')

    try:
        with yt_dlp.YoutubeDL(_ydl_opts(out_tmpl)) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'audio')

        filename = f'{job_id}.mp3'
        podcasts = load_podcasts()
        podcasts.append({
            'id': job_id,
            'title': title,
            'filename': filename,
            'date': datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0900")
        })
        save_podcasts(podcasts)
        
        return jsonify({'status': 'success', 'title': title, 'rss': request.url_root.rstrip('/') + '/rss'})
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
        # 1. Add YouTube URL to Watch RSS Feed
        {
            'WFWorkflowActionIdentifier': 'is.workflow.actions.downloadurl',
            'WFWorkflowActionParameters': {
                'WFHTTPMethod': 'POST',
                'WFURL': server_url + '/api/watch',
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
        # 2. Show success and RSS URL
        {
            'WFWorkflowActionIdentifier': 'is.workflow.actions.showresult',
            'WFWorkflowActionParameters': {
                'Text': '성공! 애플워치 팟캐스트 앱에서 확인하세요.\nRSS: ' + server_url + '/rss',
            },
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
        'WFWorkflowName': 'Add to WatchStream',
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
        headers={'Content-Disposition': 'attachment; filename="Add_to_WatchStream.shortcut"'},
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
