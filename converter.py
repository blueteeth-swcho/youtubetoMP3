import os
import yt_dlp
import sys

def download_mp3(url, save_path=None):
    if not save_path:
        save_path = os.getcwd()
    
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    print(f"[*] Starting download: {url}")
    print(f"[*] Saving to: {save_path}")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'outtmpl': os.path.join(save_path, '%(title)s.%(ext)s'),
        'logger': None,
        'progress_hooks': [lambda d: print(f"    - {d['_percent_str']} of {d.get('_total_bytes_str', 'unknown')}", end='\r') if d['status'] == 'downloading' else None],
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        print("\n[+] Success! File saved as MP3.")
    except Exception as e:
        print(f"\n[!] Error: {e}")

if __name__ == "__main__":
    print("-" * 30)
    print(" YouTube to MP3 Converter")
    print("-" * 30)
    
    video_url = input("YouTube URL: ").strip()
    if not video_url:
        print("[!] URL is required.")
        sys.exit(1)
        
    path = input("저장 경로 (기본값: 현재 폴더): ").strip()
    
    download_mp3(video_url, path if path else None)
