import yt_dlp
import sys

def download_audio(url):
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': '%(title)s.%(ext)s',
        'noplaylist': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        print(f"[*] Starting download...")
        ydl.download([url])
        print("[+] Download complete!")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        download_audio(sys.argv[1])
    else:
        print("[!] No URL provided.")
