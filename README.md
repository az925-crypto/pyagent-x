# OSINT Agent-X

> AI-powered OSINT investigation tool — CLI, Web UI, dan REST API.
> Instagram scraping · DNS/GeoIP scanning · Cross-platform username search · Agentic AI investigator

---

## Fitur

| Fitur | Deskripsi |
|-------|-----------|
| **Instagram OSINT** | Profile, followers, following, posts, comments, download media via instagrapi |
| **DNS/GeoIP Scan** | Resolve IP, MX records, GeoIP location, ASN, organisasi |
| **Cross-Platform Search** | Cek username di 7 platform: GitHub, GitLab, Reddit, TikTok, Medium, Vimeo, VK |
| **Agentic Chat Mode** | AI autonomous investigator — 50-turn loop, fungsi calling, memori jangka panjang |
| **Sandboxed Terminal** | 10 file/shell tools dengan allowlist, path guard, konfirmasi pengguna |
| **Persistent Memory** | Simpan pola investigasi (memory.json), auto-load saat investigasi baru |
| **Web UI** | Terminal-style interface dengan threat report visual |
| **REST API** | Endpoint `/api/osint/scan`, `/api/status`, `/api/admin/reload-provider` |
| **Multi AI Provider** | Gemini, OpenRouter, Zen API |

### Commands CLI

| Command | Deskripsi |
|---------|-----------|
| `ig <user>` | Instagram profile + AI analysis |
| `similar <user>` | Cross-platform username search (7 platform) |
| `scan <target>` | DNS/GeoIP scan + AI threat report |
| `followers <user>` | Instagram followers list |
| `following <user>` | Instagram following list |
| `media <user> [n]` | Instagram posts + comments |
| `download <user> [n]` | Download Instagram media |
| `chat` | Agentic AI mode (investigasi otomatis) |
| `reconnect` | Reload AI provider dari .env |
| `clear` | Clear screen |
| `exit` | Keluar |

---

## Instalasi

### Persyaratan

- Python 3.10+
- pip
- Instagram credentials (untuk fitur IG)

### Setup Cepat

```bash
# Clone
git clone https://github.com/az925-crypto/pyagent-x.git
cd pyagent-x

# Virtual environment (opsional tapi disarankan)
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Setup Termux (Proot Ubuntu)

Untuk pengguna Termux, gunakan proot-distro Ubuntu untuk kompatibilitas penuh:

```bash
# 1. Install proot-distro di Termux
pkg update && pkg upgrade
pkg install proot-distro git -y

# 2. Install Ubuntu via proot
proot-distro install ubuntu

# 3. Login ke Ubuntu
proot-distro login ubuntu

# 4. Update dan install Python
apt update && apt upgrade -y
apt install python3 python3-pip python3-venv git -y

# 5. Clone repositori
git clone https://github.com/az925-crypto/pyagent-x.git
cd pyagent-x

# 6. Install dependencies dengan --break-system-packages
pip install --break-system-packages -r requirements.txt
```

> **Catatan:** `--break-system-packages` diperlukan di Ubuntu 24.04+ karena kebijakan PEP 668. Alternatif: gunakan `python3 -m venv .venv` lalu `source .venv/bin/activate` untuk menghindari flag tersebut.

### Konfigurasi Environment

```bash
cp .env.example .env
# Edit .env — isi API key dan kredensial IG
```

**Konfigurasi `.env`:**

```
# Pilih provider: "gemini" (default), "openrouter", atau "zen"
AI_PROVIDER="gemini"
GEMINI_API_KEY="your_gemini_api_key"
GEMINI_MODEL="gemini-2.5-flash"

# IG kredensial (salah satu):
IG_USERNAME="your_ig_username"
IG_PASSWORD="your_ig_password"
# ATAU:
IG_SESSIONID="your_sessionid_from_browser"

# Opsional:
GITHUB_TOKEN="your_github_token"   # Rate limit 5000 req/jam
```

---

## Penggunaan

### CLI Mode

```bash
python3 main.py
# atau
python3 main.py --cli
```

### Web Server

```bash
python3 main.py --server
# Buka http://localhost:3000
```

Atau tentukan host/port:

```bash
PORT=8080 HOST=0.0.0.0 python3 main.py --server
```

### REST API

```bash
# Status
curl http://localhost:3000/api/status

# OSINT Scan
curl -X POST http://localhost:3000/api/osint/scan \
  -H "Content-Type: application/json" \
  -d '{"target": {"type": "domain", "value": "example.com"}}'

# Reload provider
curl -X POST http://localhost:3000/api/admin/reload-provider
```

---

## Struktur Proyek

```
pyagent-x/
├── main.py                    # Entry point (CLI / Server)
├── cli.py                     # Rich CLI dengan command system
├── cli_ui_investigation.py    # Chat/investigation UI
├── server.py                  # Flask web server + rate limiting
├── utils.py                   # Utility: GeoIP, validasi, resolvers
├── requirements.txt           # Python dependencies
├── .env.example               # Template konfigurasi
├── agent/
│   ├── provider.py            # AI provider (Gemini/OpenRouter/Zen)
│   ├── shared.py              # System prompt + stream helpers
│   ├── runtime.py             # Agent runtime (function calling loop)
│   └── memory.py              # Persistent memory (memory.json)
├── tools/
│   ├── orchestrator.py        # Tool bridge
│   ├── scan.py                # DNS/GeoIP scanner
│   ├── sherlock.py            # Cross-platform username check
│   ├── terminal.py            # Sandboxed terminal (10 tools)
│   ├── ig/
│   │   ├── _shared.py         # IG client + session management
│   │   ├── profile.py         # Profile scraper
│   │   ├── followers.py       # Followers list
│   │   ├── following.py       # Following list
│   │   ├── media.py           # Posts + comments
│   │   └── download.py        # Media download
│   └── custom/                # Custom analysis scripts
├── web/
│   └── templates/
│       └── index.html         # Web UI (terminal-style)
└── tests/
    ├── test_server.py         # 11 tests
    ├── test_terminal.py       # 63 tests
    ├── test_provider.py       # 30 tests
    ├── test_utils.py          # 15 tests
    ├── test_utils_extended.py # 11 tests
    └── test_memory.py         # 7 tests
    └── Total: 129 tests
```

---

## Testing

```bash
# Jalankan semua test
python3 -m pytest tests/ -v

# Test spesifik
python3 -m pytest tests/test_server.py -v
python3 -m pytest tests/test_terminal.py -v
```

---

## API Endpoints

| Endpoint | Method | Deskripsi |
|----------|--------|-----------|
| `/` | GET | Web UI |
| `/api/status` | GET | Status AI provider + koneksi |
| `/api/osint/scan` | POST | OSINT scan + AI analysis |
| `/api/admin/reload-provider` | POST | Reload AI provider dari .env |

**Rate limiting:** 30 request per menit per IP.
**CORS:** Hanya localhost:3000, localhost:5173.

---

## Catatan Keamanan

- `.env` tidak pernah di-commit (dilindungi `.gitignore`)
- Terminal tools memiliki sandbox dan path guard
- File terlarang (.env, .env.*) tidak bisa dibaca/ditulis/dihapus
- Perintah destruktif memerlukan konfirmasi pengguna
- Rate limiting pada API endpoints
- Session file IG disimpan di temp directory

---

## Lisensi

MIT
