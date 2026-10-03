# 🎯 AI Interview Preparation Coach

A full-stack web app that runs realistic mock interviews, scores every answer, gives feedback
(strengths, improvements, model answer) and tracks your progress over time.

## Features
- **Login / registration** with JWT authentication and hashed passwords
- **Mock interviews** - choose a role (Software Engineer, Web Developer, Data Analyst or any custom role),
  a round (**Technical, Behavioral, HR, System Design**), difficulty and number of questions
- **Instant feedback** after every answer: score /10, what went well, how to improve, model answer
- **Voice answers** - speak instead of typing (browser speech recognition, works in Chrome/Edge)
- Timer per question, skip, resume unfinished sessions, end early
- **Dashboard** - interviews completed, average and best score, day streak, minutes practiced,
  score-progress chart and performance by round
- Practice history with full question-by-question review
- Interview tips (STAR method, delivery, checklist), dark mode, responsive design

## Two modes
| Mode | When | What you get |
|---|---|---|
| **AI mode** | `ANTHROPIC_API_KEY` is set | Questions generated for your exact role and level, and answers evaluated by Claude |
| **Offline coach** | no key (default) | Curated question bank + built-in scoring (depth, key-point coverage, STAR structure, reasoning, filler words). Works with no internet and no cost |

If the AI service is unreachable, the app automatically falls back to the offline coach, so it never breaks.

## Run it in VS Code
1. Install **Python 3.9+** (tick *Add python.exe to PATH*), unzip the project and open the folder that contains `app.py` in VS Code (`File -> Open Folder`).
2. In the terminal:
   ```powershell
   python -m pip install Flask
   python app.py
   ```
3. Open **http://localhost:5000**, click *Create one*, register and start practicing.

### Turn on AI mode (optional)
Get an API key from https://console.anthropic.com and set it **before** starting the server:
```powershell
# Windows PowerShell
$env:ANTHROPIC_API_KEY="your-key-here"
python app.py
```
```bash
# macOS / Linux
export ANTHROPIC_API_KEY=your-key-here && python app.py
```
The header badge shows **AI mode** when it is active. API usage is billed to your key, so the app limits each user to
30 new sessions per day (`DAILY_SESSION_LIMIT`). Never put the key in front-end code or commit it to GitHub.

## Configuration (environment variables)
| Variable | Purpose | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | enables AI mode | none |
| `AI_MODEL` | model used in AI mode | `claude-sonnet-5-5` |
| `SECRET_KEY` | signs login tokens (set a long random value in production) | auto-generated |
| `DAILY_SESSION_LIMIT` | new sessions per user per day | 30 |
| `DATA_DIR` | where the SQLite database is stored | `./data` |
| `PORT` | server port | 5000 |

## Project structure
```
ai-interview-coach/
  app.py            Flask REST API: auth, sessions, answers, stats
  coach.py          question bank, offline scoring engine, Claude integration
  static/           index.html, style.css, app.js (single-page front-end)
  test_app.py       automated tests (python test_app.py)
  requirements.txt  Procfile  Dockerfile
  data/             created on first run (coach.db)
```

## Database
`users` / `sessions` (role, round, level, status, average score) / `answers` (question, your answer, score, strengths, improvements, model answer, time spent)

## REST API (all except auth need `Authorization: Bearer <token>`)
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/auth/register`, `/api/auth/login` | Create account / get token |
| GET | `/api/config` | Roles, rounds, levels, AI on/off |
| POST | `/api/sessions` | Start an interview `{role, custom_role, itype, level, count}` |
| GET | `/api/sessions`, `/api/sessions/<id>` | History / one session |
| POST | `/api/sessions/<id>/answer` | Submit answer `{idx, answer, seconds}` and get feedback |
| POST | `/api/sessions/<id>/finish` | End early and score answered questions |
| DELETE | `/api/sessions/<id>` | Delete a session |
| GET | `/api/stats` | Dashboard statistics |

## Deploying to the internet
Use a host that can run Python/Docker and keeps a persistent disk for `DATA_DIR` (the SQLite file).
```bash
pip install gunicorn
SECRET_KEY=<long-random> ANTHROPIC_API_KEY=<key> gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:8000
```
Or with Docker: `docker build -t coach .` then
`docker run -d -p 80:8000 -v coach-data:/data -e SECRET_KEY=... -e ANTHROPIC_API_KEY=... coach`.
On Render: create a *Web Service* from your GitHub repo (start command from `Procfile`) and attach a disk mounted at `/var/data` with `DATA_DIR=/var/data`.
AI mode needs outbound internet access to `api.anthropic.com`; check that your host allows it. Keep `FLASK_DEBUG=0` and use HTTPS.

## Security notes
Passwords are hashed (PBKDF2); tokens expire after 7 days; login attempts are rate-limited; every session is checked against its
owner; reference answers are never sent to the browser before you answer; candidate answers are wrapped as untrusted data in AI prompts;
all output is HTML-escaped.
