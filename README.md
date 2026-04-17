# YT → MP3 (개인 전용 서버)

## 전체 흐름

```
[유튜브 앱] → URL 복사
     ↓
[Safari에서 이 웹사이트 열기] → 붙여넣기 → MP3 변환 시작
     ↓ (서버가 yt-dlp로 변환)
[MP3 다운로드] → 파일 앱 → 음악 앱 공유
     ↓
[Apple Music + Apple Watch에서 재생] ✅
```

---

## 서버 배포 방법 (Railway - 무료, 5분 설정)

### 1. GitHub에 올리기
```bash
cd /Users/swcho/Documents/youtubetoMP3
git init
git add .
git commit -m "initial"
# GitHub에서 새 레포 만들고:
git remote add origin https://github.com/[아이디]/[레포이름].git
git push -u origin main
```

### 2. Railway 배포
1. [railway.app](https://railway.app) 접속 → GitHub 로그인
2. **"New Project"** → **"Deploy from GitHub repo"** 선택
3. 방금 만든 레포 선택
4. 자동으로 빌드/배포됨 (약 2-3분)
5. **Settings → Domains → Generate Domain**으로 공개 URL 발급

> ffmpeg는 Railway의 Nixpacks가 자동 설치합니다.

### 3. 아이폰에서 앱처럼 쓰기
1. Safari에서 발급받은 URL 접속 (예: `https://yt-mp3-xxxx.up.railway.app`)
2. 공유 아이콘 → **홈 화면에 추가**
3. 이제 아이콘 탭 → URL 붙여넣기 → 변환 → 다운로드 → 음악 앱 추가

---

## 로컬 테스트 (맥)
```bash
pip3 install -r requirements.txt
python3 app.py
# → http://localhost:5001
```

---

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/convert` | 변환 시작. Body: `{"url": "..."}` → `{"job_id": "..."}` |
| GET  | `/api/status/<job_id>` | 상태 폴링. `status`: starting / downloading / processing / completed / error |
| GET  | `/api/download/<job_id>` | 완성된 MP3 파일 다운로드 |
