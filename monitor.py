"""
메디 리서치 레이더 - 수집기
---------------------------
config.yaml 에 적힌 게시판·API·뉴스를 확인해서
  1) docs/data/items.json  ← 핸드폰 앱(웹앱)이 읽는 데이터
  2) 새 공고가 생기면 핸드폰 푸시 (ntfy)
를 만듭니다. GitHub Actions 가 3시간마다 실행하는 것이 기본이고, PC 에서 직접 돌려도 됩니다.

  python monitor.py                 # 한 번 수집
  python monitor.py --dry-run       # 저장·알림 없이 걸리는 글만 출력
  python monitor.py --only 위비티    # 특정 소스만 (이름 일부)
  python monitor.py --test          # 테스트 푸시
  python monitor.py --setup-phone   # ntfy 토픽 생성
  python monitor.py --rescore       # 수집 없이 맞춤 점수·앱 데이터·캘린더만 다시 (config 의 interests 를 고친 뒤)

시험:  python -m unittest discover -s tests   (인터넷 없이 날짜·점수·캘린더 규칙만)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import logging
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.parse
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
import yaml
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "config.yaml"
STATE_DIR = BASE / "data"
SEEN_FILE = STATE_DIR / "seen.json"
LOG_FILE = STATE_DIR / "monitor.log"
APP_DATA = BASE / "docs" / "data" / "items.json"
ICS_FILE = BASE / "docs" / "data" / "deadlines.ics"   # 핸드폰 캘린더가 구독하는 마감 일정
TOPIC_FILE = BASE / ".ntfy_topic"      # .gitignore 로 업로드 제외

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 MedRadar/2.0")
TODAY = dt.date.today()

log = logging.getLogger("med-radar")


# ================================================================== 설정 / 상태
def load_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 토픽 우선순위: GitHub 비밀값 → 이 PC의 .ntfy_topic 파일(업로드 제외) → config.yaml
    topic = os.environ.get("NTFY_TOPIC") or (
        TOPIC_FILE.read_text(encoding="utf-8").strip() if TOPIC_FILE.exists() else "")
    if topic:
        cfg.setdefault("notify", {}).setdefault("phone", {})["topic"] = topic
        cfg["notify"]["phone"]["enabled"] = True
    return cfg


def load_state() -> dict:
    st = json.loads(SEEN_FILE.read_text(encoding="utf-8")) if SEEN_FILE.exists() else {}
    st.setdefault("seen", {})          # 모든 본 글: key -> 처음 본 날짜
    st.setdefault("items", {})         # 앱에 보여줄 글: key -> 상세
    st.setdefault("initialized", [])   # 기준선을 잡은 소스
    st.setdefault("errors", {})
    return st


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    tmp = SEEN_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(SEEN_FILE)


# ================================================================== 공통 도구
RETRY_WAITS = (0, 3, 8)     # 일시 장애(503·시간 초과)는 두 번까지 다시 — 구글 뉴스가 Actions 에서 가끔 503 을 낸다
RETRY_STATUS = (429, 500, 502, 503, 504)


def fetch(url: str) -> requests.Response:
    headers = {"User-Agent": UA}
    if "api.github.com" in url and os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    last: Exception | None = None
    for wait in RETRY_WAITS:
        if wait:
            time.sleep(wait)
        try:
            r = requests.get(url, headers=headers, timeout=(8, 25))   # 연결 8초 · 응답 25초
        except (requests.ConnectionError, requests.Timeout) as e:
            last = e
            continue
        if r.status_code in RETRY_STATUS:
            last = requests.HTTPError(f"{r.status_code} Server Error for url: {url}", response=r)
            continue
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        return r
    raise last  # type: ignore[misc]


def clean(text) -> str:
    text = re.sub(r"<[^>]+>", "", str(text or ""))
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return re.sub(r"\s*\bNEW\b\s*$", "", text)


def expand_url(url: str) -> str:
    """URL 안의 {since:30} → 30일 전 날짜(YYYY-MM-DD)"""
    return re.sub(r"\{since:(\d+)\}",
                  lambda m: (TODAY - dt.timedelta(days=int(m.group(1)))).isoformat(), url)


def norm_date(s: str) -> str:
    """여러 날짜 표기를 YYYY-MM-DD 로"""
    if not s:
        return ""
    m = re.search(r"(20\d\d)[.\-/](\d{1,2})[.\-/](\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    try:
        return parsedate_to_datetime(s).astimezone().date().isoformat()
    except Exception:
        return ""


def _md(mo: int, d: int, year: int | None = None) -> str:
    try:
        y = year or TODAY.year
        day = dt.date(y, mo, d)
        if year is None and day < TODAY - dt.timedelta(days=120):
            day = dt.date(y + 1, mo, d)        # 연말에 올라온 "~1/10" 같은 경우
        return day.isoformat()
    except ValueError:
        return ""


MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_deadline(text: str) -> str:
    """제목·기간 문자열에서 마감일 추정. 못 찾으면 ''"""
    if not text:
        return ""
    t = str(text)
    if re.fullmatch(r"20\d\d-\d\d-\d\dT.*", t):                       # ISO 날짜 필드
        return t[:10]
    m = re.search(r"(?<![A-Za-z])D-(\d{1,3})\b", t)                     # 위비티 D-4 (COVID-19 제외)
    if m:
        return (TODAY + dt.timedelta(days=int(m.group(1)))).isoformat()
    m = re.search(r"'(\d\d)\.\s*(\d{1,2})\.\s*(\d{1,2})", t)            # '26.11.18.
    if m:
        return _md(int(m.group(2)), int(m.group(3)), 2000 + int(m.group(1)))
    m = re.search(r"~\s*(20\d\d)-(\d{1,2})-(\d{1,2})", t)               # 2026-11-01 ~ 2026-11-20
    if m:
        return _md(int(m.group(2)), int(m.group(3)), int(m.group(1)))
    m = re.search(r"~\s*(?:(20\d\d)[./-])?(\d{1,2})[./](\d{1,2})", t)   # ~12/4, ~11.20
    if m:
        return _md(int(m.group(2)), int(m.group(3)), int(m.group(1)) if m.group(1) else None)
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일[^,)]{0,12}(?:마감|까지)", t)  # 11월 30일까지
    if m:
        return _md(int(m.group(1)), int(m.group(2)))
    m = re.search(r"(\d{1,2})[./](\d{1,2})\.?\s*(?:\(.\))?[^,)]{0,10}(?:마감|까지)", t)
    if m:
        return _md(int(m.group(1)), int(m.group(2)))
    m = re.search(r"-\s*([A-Z][a-z]{2})\s+(\d{1,2}),\s*(20\d\d)", t)    # Nov 02 - Dec 15, 2026
    if m and m.group(1).lower() in MONTHS:
        return _md(MONTHS[m.group(1).lower()], int(m.group(2)), int(m.group(3)))
    return ""


# 본문에서 마감 읽기 — 제목에 마감이 없는 공고(연구·인턴 공고 대부분)를 '마감 임박'에 올리려는 것.
# 틀린 날짜를 사실처럼 보여 주면 안 되므로 '접수·신청·모집 기간/마감' 같은 꼬리표 바로 뒤의 날짜만 읽고,
# 읽은 값은 deadline_src="page"(앱에서 '추정')로 표시한다. 꼬리표가 없으면 읽지 않는다.
PAGE_LABEL = re.compile(
    r"(?:접수|신청|모집|지원|제출|응모|등록|참가\s*신청)\s*(?:기간|기한|마감(?:일)?|일정|일시)\s*[:：]?"
    r"|(?:마감일|마감\s*기한|신청\s*마감|접수\s*마감)\s*[:：]?"
    r"|(?:application|submission|registration)\s+deadline\s*[:：]?", re.I)
PAGE_DATE = re.compile(
    r"(?:(20\d\d)\s*[.\-/년]\s*)?(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*일?")


# 첫 날짜 바로 뒤에 '~ 다음 날짜' 가 이어지면 기간 — 요일·시각 표기는 건너뛴다: '11. 3.(월) 09:00 ~ 11. 21.'
PAGE_RANGE = re.compile(r"\.?\s*(?:\([^)]{1,4}\))?\s*(?:\d{1,2}:\d{2})?\s*(?:~|∼|〜|–|—|-|부터|to)\s*", re.I)
PAGE_STOP = re.compile(r"발표|선발 결과|교육\s*(?:기간|일시|일정)|행사\s*(?:기간|일시)|장소|문의|program\s+dates?", re.I)


def page_deadline(text: str, posted: str = "") -> str:
    """공고 본문 글에서 마감일(YYYY-MM-DD) 추정.

    꼬리표(접수기간·신청마감 …) 바로 뒤(30자 안)에서 시작하는 첫 날짜만 읽는다. 그 날짜에 '~ 날짜' 가 이어지면
    기간의 끝 날짜를, 아니면 그 날짜를 마감으로 본다. 꼬리표 뒤의 다른 항목(발표·교육 일시·문의 전화) 날짜는 읽지 않는다."""
    if not text:
        return ""
    t = re.sub(r"\s+", " ", text)
    lo = (TODAY - dt.timedelta(days=60)).isoformat()
    hi = (TODAY + dt.timedelta(days=400)).isoformat()

    def iso_of(d, year=None):
        mo, dd = int(d.group(2)), int(d.group(3))
        if not (1 <= mo <= 12 and 1 <= dd <= 31):
            return "", year
        year = int(d.group(1)) if d.group(1) else year
        return _md(mo, dd, year), year

    for m in PAGE_LABEL.finditer(t):
        win = t[m.end(): m.end() + 90]
        stop = PAGE_STOP.search(win)
        if stop:
            win = win[: stop.start()]
        d1 = PAGE_DATE.search(win)
        if not d1 or d1.start() > 30:
            continue
        end, year = iso_of(d1)
        if not end:
            continue
        r = PAGE_RANGE.match(win, d1.end())
        d2 = PAGE_DATE.match(win, r.end()) if r else None
        if d2:
            end2, _ = iso_of(d2, year)          # '2026.11.1 ~ 11.20' 의 끝 날짜는 앞 날짜의 연도를 따른다
            if end2 and end2 >= end:
                end = end2
        if lo <= end <= hi and (not posted or end >= posted):
            return end
    return ""


class SafeDict(dict):
    def __missing__(self, key):
        return ""


def flatten(obj: dict) -> SafeDict:
    """JSON 항목을 템플릿에 넣기 좋게 평탄화 (리스트는 name/title 을 쉼표로)"""
    out = SafeDict()
    for k, v in obj.items():
        if isinstance(v, list):
            out[k] = ", ".join(clean(x.get("name") or x.get("title") or "") if isinstance(x, dict)
                               else clean(x) for x in v)
        elif isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}_{k2}"] = clean(v2)
        else:
            out[k] = clean(v) if v is not None else ""
    return out


def dig(data, path: str | None):
    if not path:
        return data
    for p in path.split("."):
        data = data[p]
    return data


# ================================================================== 수집기
def scrape_html(src: dict) -> list[dict]:
    out = []
    for url in src.get("urls") or [src["url"]]:
        r = fetch(expand_url(url))
        soup = BeautifulSoup(r.text, "html.parser")
        for el in soup.select(src["item"]):
            if src.get("drop"):
                for d in el.select(src["drop"]):
                    d.decompose()
            t_el = el.select_one(src["title"]) if src.get("title") else el
            if t_el is None:
                continue
            title = clean(t_el.get("title") or t_el.get_text(" ", strip=True))
            title = re.sub(r"^(공지|NOTICE|TOP)\s+", "", title)
            title = re.sub(r"\s+20\d\d[.\-/]\d{1,2}[.\-/]\d{1,2}(\s+[\d,]+)?$", "", title)
            if len(title) < 4:
                continue
            raw = str(el)
            if src.get("id_regex"):
                m = re.search(src["id_regex"], raw)
                if not m:
                    continue
                item_id = m.group(1)
                link = src["link"].format(id=item_id)
            else:
                a = el if el.name == "a" else el.find("a", href=True)
                href = a.get("href") if a else None
                if not href or href.startswith(("javascript", "#")):
                    continue
                link = urllib.parse.urljoin(r.url, href)
                item_id = link
            date = ""
            if src.get("date"):
                d_el = el.select_one(src["date"])
                date = norm_date(d_el.get_text()) if d_el else ""
            if not date:
                date = norm_date(el.get_text(" ")) or (
                    norm_date(el.parent.get_text(" ")) if el.name == "a" and el.parent else "")
            dl_text = title
            if src.get("deadline"):
                d_el = el.select_one(src["deadline"])
                dl_text = d_el.get_text(" ") if d_el else title
            org = ""
            if src.get("org"):
                o_el = el.select_one(src["org"])
                org = clean(o_el.get_text()) if o_el else ""
            out.append({"id": item_id, "title": title, "link": link, "date": date,
                        "deadline": parse_deadline(dl_text) or parse_deadline(title), "extra": org})
    return out


def scrape_rss(url: str) -> list[dict]:
    r = fetch(url)
    soup = BeautifulSoup(r.content, "xml")
    out = []
    for it in soup.find_all(["item", "entry"]):
        title = clean(it.title.get_text() if it.title else "")
        link_el = it.find("link")
        link = (link_el.get("href") or link_el.get_text()).strip() if link_el else ""
        guid = it.find("guid") or it.find("id")
        date_el = it.find("pubDate") or it.find("updated") or it.find("published")
        date = norm_date(date_el.get_text()) if date_el else ""
        if title and link:
            out.append({"id": guid.get_text().strip() if guid else link, "title": title,
                        "link": link, "date": date, "deadline": parse_deadline(title), "extra": ""})
    return out


def scrape_google_news(src: dict) -> list[dict]:
    days = int(src.get("days", 14))
    out = []
    for q in src["queries"]:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} when:{days}d")
               + "&hl=ko&gl=KR&ceid=KR:ko")
        for it in scrape_rss(url):
            m = re.search(r"\s+-\s+([^-]+)$", it["title"])
            it["extra"] = m.group(1).strip() if m else ""            # 언론사
            it["title"] = re.sub(r"\s+-\s+[^-]+$", "", it["title"])
            it["id"] = it["title"]
            out.append(it)
    return out


def scrape_json(src: dict) -> list[dict]:
    out = []
    for url in src.get("urls") or [src["url"]]:
        data = dig(fetch(expand_url(url)).json(), src.get("items"))
        for raw in data:
            f = flatten(raw)
            if any(f.get(k, "") in v for k, v in (src.get("exclude_values") or {}).items()):
                continue
            title = clean(src.get("title", "{title}").format_map(f)).strip(" :·")
            if not title and src.get("title_fallback"):
                title = clean(src["title_fallback"].format_map(f))
            if not title:
                continue
            dl = f.get(src["deadline_field"], "") if src.get("deadline_field") else ""
            out.append({
                "id": src.get("id", "{id}").format_map(f),
                "title": title[:200],
                "link": src.get("link", "{url}").format_map(f),
                "date": norm_date(f.get(src.get("date_field", ""), "")),
                "deadline": parse_deadline(dl) or parse_deadline(title),
                "extra": clean(src.get("extra", "").format_map(f)).strip(" ·")[:160],
            })
    return out


def collect(src: dict) -> list[dict]:
    t = src.get("type", "html")
    items = {"html": scrape_html, "google_news": scrape_google_news, "json": scrape_json,
             "rss": lambda s: [x for u in (s.get("urls") or [s["url"]]) for x in scrape_rss(u)]}[t](src)
    if src.get("max_age_days"):      # 너무 오래된 글 제외 (피드에 옛 글이 섞여 있을 때)
        cut = (TODAY - dt.timedelta(days=int(src["max_age_days"]))).isoformat()
        items = [it for it in items if not it.get("date") or it["date"] >= cut]
    if src.get("only_future"):       # 마감일이 오늘 이후인 것만 (끝난 챌린지 제외)
        items = [it for it in items if it.get("deadline") and it["deadline"] >= TODAY.isoformat()]
    seen, out = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


# ================================================================== 필터
def _has(text: str, words) -> bool:
    low = text.lower()
    return any(w.lower() in low for w in words or [])


def matches(it: dict, src: dict, cfg: dict) -> bool:
    text = f"{it['title']} {it.get('extra', '')}"
    kw = cfg.get("keywords", {})
    if src.get("require") and not _has(it["title"], src["require"]):
        return False
    if _has(text, kw.get("exclude", []) + (src.get("exclude") or [])):
        return False
    if not src.get("filter", False):
        return True
    return _has(text, src.get("include") or kw.get("include", []))


def _words(title: str) -> set[str]:
    return set(re.findall(r"[0-9A-Za-z가-힣]{2,}", title))


def similar(a: str, b: str) -> bool:
    """같은 소식을 여러 언론사가 쓴 기사인지 대략 판별"""
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.5


# ================================================================== 맞춤 점수
def _hit(text_low: str, word: str) -> bool:
    """영문·숫자만 있는 말(AI, ECG, AMR)은 낱말 경계로, 한글이 섞인 말은 포함 여부로 찾는다."""
    w = word.lower().strip()
    if not w:
        return False
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+\-]*", w):
        return re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text_low) is not None
    return w in text_low


def score_item(it: dict, cfg: dict) -> tuple[int, list[str]]:
    """config 의 interests.groups 로 (점수, 걸린 묶음 이름). 한 묶음은 한 번만 센다."""
    text = f"{it.get('title', '')} {it.get('extra', '')}".lower()
    total, tags = 0, []
    for g in ((cfg.get("interests") or {}).get("groups") or []):
        if any(_hit(text, w) for w in g.get("words") or []):
            total += int(g.get("weight", 1))
            tags.append(g.get("name", ""))
    return total, tags


# ================================================================== 알림
TAGS = {"research": ["microscope"], "ai": ["robot"], "data": ["bar_chart"]}


def phone(cfg: dict, title: str, body: str, click: str | None = None,
          tags=None, app_url: str | None = None, priority: int = 4) -> None:
    p = cfg.get("notify", {}).get("phone", {})
    if not p.get("enabled") or not p.get("topic"):
        return
    payload = {"topic": p["topic"], "title": title, "message": body,
               "tags": tags or ["bell"], "priority": priority}
    if click:
        payload["click"] = click
    if app_url:
        payload["actions"] = [{"action": "view", "label": "앱에서 보기", "url": app_url}]
    try:
        requests.post(p.get("server", "https://ntfy.sh").rstrip("/"),
                      data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, timeout=15).raise_for_status()
    except Exception as e:
        log.warning("핸드폰 알림 실패: %s", e)


def toast(title: str, body: str, launch: str | None = None) -> None:
    """(선택) 윈도우 알림 - config 의 notify.pc 가 true 일 때만"""
    if os.name != "nt":
        return
    esc = lambda s: html.escape(s, quote=True)
    la = f' activationType="protocol" launch="{esc(launch)}"' if launch else ""
    xml = (f'<toast{la}><visual><binding template="ToastGeneric"><text>{esc(title)}</text>'
           f'<text>{esc(body)}</text></binding></visual></toast>')
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null\n"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null\n"
          f"$x = New-Object Windows.Data.Xml.Dom.XmlDocument\n$x.LoadXml(@'\n{xml}\n'@)\n"
          "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'\n"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                        base64.b64encode(ps.encode("utf-16-le")).decode()],
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                       timeout=30, capture_output=True)
    except Exception as e:
        log.warning("PC 알림 실패: %s", e)


def notify_new(cfg: dict, new: list[dict]) -> None:
    if not new:
        return
    n = cfg.get("notify", {})
    cats = cfg.get("categories", {})
    app_url = (cfg.get("app", {}) or {}).get("url") or None
    ins = cfg.get("interests") or {}
    min_push, star = int(ins.get("min_push", 0)), int(ins.get("star", 4))
    scored = [(score_item(it, cfg), it) for it in new if cats.get(it["category"], {}).get("push", True)]
    scored = [x for x in scored if x[0][0] >= min_push]           # '대상 아님'(음수)은 앱에만 쌓고 푸시하지 않는다
    scored.sort(key=lambda x: -x[0][0])                            # 맞춤 점수 높은 것부터(상한에 걸릴 때 먼저 나가게)
    pushable = [it for _, it in scored]
    cap = int(n.get("max_per_run", 10))
    for (sc, tags), it in scored[:cap]:
        cname = cats.get(it["category"], {}).get("name", "")
        body = it["title"]
        if it.get("deadline"):
            body += f"\n마감 {it['deadline']}" + (" (본문에서 읽음·추정)" if it.get("deadline_src") == "page" else "")
        hot = sc >= star
        if hot and tags:
            body += "\n맞춤: " + " · ".join(tags)
        phone(cfg, ("★ " if hot else "") + f"[{cname}] {it['source']}", body, it["link"],
              (["star"] if hot else []) + (TAGS.get(it["category"]) or []), app_url, priority=4 if hot else 3)
    if len(pushable) > cap:
        phone(cfg, f"새 소식 {len(pushable) - cap}건 더", "앱에서 전체를 확인하세요.",
              app_url, ["bell"])
    if n.get("pc"):
        toast(f"새 소식 {len(new)}건", " / ".join(i["title"][:25] for i in new[:3]))


def weekly_digest(cfg: dict, st: dict, now: dt.datetime) -> bool:
    """월요일 아침 첫 실행에 '이번 주 마감' 요약 푸시 한 번. 보냈으면 True."""
    d = (cfg.get("notify") or {}).get("digest") or {}
    if not d.get("enabled", True):
        return False
    week = f"{now.isocalendar()[0]}-W{now.isocalendar()[1]:02d}"
    if now.weekday() != int(d.get("weekday", 0)) or now.hour < int(d.get("hour", 7)) or st.get("digest") == week:
        return False
    st["digest"] = week
    end = (now.date() + dt.timedelta(days=7)).isoformat()
    due = sorted((it for it in st["items"].values()
                  if it.get("deadline") and now.date().isoformat() <= it["deadline"] <= end
                  and score_item(it, cfg)[0] >= 0), key=lambda x: x["deadline"])
    if not due:
        return False
    lines = [f"{it['deadline'][5:].replace('-', '/')} {it['title'][:38]}" for it in due[:6]]
    if len(due) > 6:
        lines.append(f"… 외 {len(due) - 6}건")
    phone(cfg, f"이번 주 마감 {len(due)}건", "\n".join(lines), (cfg.get("app") or {}).get("url"), ["calendar"], priority=3)
    return True


# ================================================================== 앱 데이터
def _ics_text(s: str) -> str:
    return str(s).replace("\\", "\\\\").replace(";", r"\;").replace(",", r"\,").replace("\n", r"\n")


def _ics_fold(line: str) -> str:
    """RFC 5545: 한 줄 75옥텟 이하 — 글자 경계에서 접는다."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 73:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def build_ics(items: list[dict]) -> str:
    """마감이 남은 글을 하루짜리 일정으로. 핸드폰 캘린더에서 주소를 '구독'하면 마감이 달력에 뜬다."""
    L = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//medradar//deadlines//KO", "CALSCALE:GREGORIAN",
         "METHOD:PUBLISH", "X-WR-CALNAME:메디 리서치 레이더 마감", "X-WR-TIMEZONE:Asia/Seoul",
         "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H"]
    for it in sorted(items, key=lambda x: (x["deadline"], x["id"])):
        day = dt.date.fromisoformat(it["deadline"])
        seen = re.sub(r"\D", "", it.get("first_seen", ""))[:14].ljust(14, "0")
        guess = " (추정)" if it.get("deadline_src") == "page" else ""
        L += ["BEGIN:VEVENT",
              "UID:" + hashlib.sha1(it["id"].encode("utf-8")).hexdigest()[:20] + "@medradar",
              f"DTSTAMP:{seen[:8]}T{seen[8:]}Z",
              f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
              f"DTEND;VALUE=DATE:{day + dt.timedelta(days=1):%Y%m%d}",
              "SUMMARY:" + _ics_text(f"마감{guess} · {it['title']}"),
              "DESCRIPTION:" + _ics_text(f"{it['source']}\n{it['link']}"),
              "URL:" + it["link"],
              "TRANSP:TRANSPARENT",
              "END:VEVENT"]
    L.append("END:VCALENDAR")
    return "\r\n".join(_ics_fold(x) for x in L) + "\r\n"


def app_items(st: dict, cfg: dict) -> list[dict]:
    app = cfg.get("app", {}) or {}
    keep = (TODAY - dt.timedelta(days=int(app.get("keep_days", 120)))).isoformat()
    items = []
    for key, it in st["items"].items():
        last = max(it.get("first_seen", ""), it.get("deadline") or "")
        if last >= keep:
            sc, tags = score_item(it, cfg)           # 저장하지 않고 그때그때 계산 — config 를 고치면 옛 글 점수도 바뀐다
            items.append({k: it.get(k, "") for k in
                          ("title", "link", "source", "category", "date", "deadline", "extra",
                           "first_seen", "baseline")}
                         | {"id": key, "score": sc, "tags": tags, "deadline_src": it.get("deadline_src", "")})
    items.sort(key=lambda x: (x["first_seen"], x["date"]), reverse=True)
    return items[: int(app.get("max_items", 800))]


def write_app_data(st: dict, cfg: dict) -> None:
    items = app_items(st, cfg)
    ins = cfg.get("interests") or {}
    data = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "star": int(ins.get("star", 4)),
        "categories": [{"id": k, "name": v.get("name", k)}
                       for k, v in (cfg.get("categories") or {}).items()],
        "sources": [{"name": s["name"], "category": s.get("category", "research"),
                     "error": st["errors"].get(s["name"], ""),
                     "pc_only": bool(s.get("ci_skip"))} for s in cfg.get("sources", [])],
        "items": items,
    }
    APP_DATA.parent.mkdir(parents=True, exist_ok=True)
    APP_DATA.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    due = [it for it in items if it["deadline"] and it["deadline"] >= TODAY.isoformat() and it["score"] >= 0]
    ICS_FILE.write_bytes(build_ics(due).encode("utf-8"))


def fill_page_deadlines(st: dict, cfg: dict, cap: int = 12) -> int:
    """마감이 없는 게시판 글의 본문을 열어 마감을 읽는다(실행당 cap 건, 글마다 한 번만)."""
    by_name = {s["name"]: s for s in cfg.get("sources", [])}
    done = 0
    for key, it in st["items"].items():
        if done >= cap:
            break
        src = by_name.get(it.get("source")) or {}
        if it.get("deadline") or it.get("dl_checked") or src.get("type", "html") != "html" \
                or not src.get("page_deadline", True) or it.get("category") == "data":
            continue
        if src.get("ci_skip") and os.environ.get("GITHUB_ACTIONS"):
            continue
        it["dl_checked"] = True
        done += 1
        try:
            soup = BeautifulSoup(fetch(it["link"]).text, "html.parser")
            for junk in soup(["script", "style", "nav", "header", "footer"]):
                junk.decompose()
            dl = page_deadline(soup.get_text(" ", strip=True), it.get("date", ""))
        except Exception as e:
            log.info("[본문 마감] %s 열지 못함: %s", it.get("title", "")[:30], e)
            continue
        if dl:
            it["deadline"], it["deadline_src"] = dl, "page"
            log.info("[본문 마감] %s → %s", it.get("title", "")[:40], dl)
    return done


# ================================================================== 실행
def run(args) -> int:
    cfg = load_config()
    st = load_state()
    now = dt.datetime.now().isoformat(timespec="seconds")
    new_items: list[dict] = []

    for src in cfg.get("sources", []):
        name = src["name"]
        if args.only and args.only not in name:
            continue
        if src.get("ci_skip") and os.environ.get("GITHUB_ACTIONS"):
            st["errors"].pop(name, None)      # 해외 서버를 막는 사이트 — Actions 에서는 건너뛴다(PC 에서만 확인)
            continue
        cat = src.get("category", "research")
        try:
            items = collect(src)
        except Exception as e:
            log.error("[%s] 수집 실패: %s", name, e)
            st["errors"][name] = f"{now[:16]} {type(e).__name__}: {str(e)[:120]}"
            continue
        st["errors"].pop(name, None)
        if not items:
            log.warning("[%s] 0건 - 사이트 구조가 바뀌었을 수 있음", name)
            st["errors"][name] = f"{now[:16]} 글 0건 - 사이트 구조 변경 의심"
        first_time = name not in st["initialized"]
        is_news = src.get("type") == "google_news"
        recent = [v["title"] for v in st["items"].values() if is_news and v["source"] == name
                  and v.get("first_seen", "") >= (TODAY - dt.timedelta(days=21)).isoformat()]
        hit = 0
        for it in items:
            ok = matches(it, src, cfg)
            if ok and is_news:
                if any(similar(it["title"], t) for t in recent):
                    ok = False                     # 같은 소식의 다른 기사
                else:
                    recent.append(it["title"])
            if args.dry_run:
                if ok:
                    hit += 1
                    dl = f" (마감 {it['deadline']})" if it["deadline"] else ""
                    print(f"  {it['date'] or '':>10}  {it['title'][:72]}{dl}")
                continue
            key = f"{name}::{it['id']}"
            if key in st["seen"]:
                continue
            st["seen"][key] = now[:10]
            if not ok:
                continue
            baseline = first_time and not args.notify_existing
            if baseline and not src.get("show_baseline", True):
                continue
            rec = {**it, "source": name, "category": cat, "first_seen": now, "baseline": baseline}
            st["items"][key] = rec
            if not baseline:
                new_items.append(rec)
        if args.dry_run:
            print(f"[{name}] 전체 {len(items)}건 중 일치 {hit}건\n")
        else:
            if first_time:
                st["initialized"].append(name)
            log.info("[%s] %d건 확인", name, len(items))

    if args.dry_run:
        return 0
    if not args.only:
        fill_page_deadlines(st, cfg)          # 새 글 포함 — 푸시 전에 읽어 알림에 마감이 실리게
    digest = weekly_digest(cfg, st, dt.datetime.now())
    save_state(st)
    write_app_data(st, cfg)
    notify_new(cfg, new_items)
    if digest:
        log.info("주간 마감 요약을 보냈습니다")
    log.info("새 소식 %d건", len(new_items))
    for it in new_items:
        log.info("  NEW [%s] %s  %s", it["source"], it["title"], it["link"])
    return 0


def setup_phone() -> None:
    if TOPIC_FILE.exists() and TOPIC_FILE.read_text(encoding="utf-8").strip():
        topic = TOPIC_FILE.read_text(encoding="utf-8").strip()
        print("이미 토픽이 있습니다.")
    else:
        topic = "medradar-" + secrets.token_hex(8)
        TOPIC_FILE.write_text(topic, encoding="utf-8")
        print("새 토픽을 만들어 .ntfy_topic 파일에 저장했습니다 (GitHub 에는 올라가지 않음).")
    print(f"""
  토픽 이름:  {topic}

  1) 핸드폰에 'ntfy' 앱 설치 → + 버튼 → 위 토픽 이름으로 구독
  2) GitHub 저장소 Settings → Secrets and variables → Actions → NTFY_TOPIC 에 같은 값 저장
  3) python monitor.py --test  → 핸드폰에 알림이 오면 연결 완료
  ※ 토픽 이름을 아는 사람은 누구나 알림을 볼 수 있으니 비밀번호처럼 다루세요.
""")


def main() -> int:
    STATE_DIR.mkdir(exist_ok=True)
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stdout:
        handlers.append(logging.StreamHandler())
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=handlers)
    ap = argparse.ArgumentParser(description="메디 리서치 레이더 수집기")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", help="이름에 이 글자가 들어간 소스만")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--setup-phone", action="store_true")
    ap.add_argument("--notify-existing", action="store_true")
    ap.add_argument("--rescore", action="store_true", help="수집 없이 앱 데이터·캘린더만 다시 만든다")
    args = ap.parse_args()
    if args.rescore:
        cfg, st = load_config(), load_state()
        write_app_data(st, cfg)
        items = app_items(st, cfg)
        star = int((cfg.get("interests") or {}).get("star", 4))
        print(f"{len(items)}건 · 맞춤(★ {star}점 이상) {sum(i['score'] >= star for i in items)}건 · "
              f"대상 아님(음수) {sum(i['score'] < 0 for i in items)}건")
        return 0
    if args.setup_phone:
        setup_phone()
        return 0
    if args.test:
        cfg = load_config()
        phone(cfg, "메디 리서치 레이더", "핸드폰 알림 테스트입니다. 정상 작동 중!",
              (cfg.get("app") or {}).get("url"), ["white_check_mark"])
        if cfg.get("notify", {}).get("pc"):
            toast("메디 리서치 레이더", "PC 알림 테스트")
        print("테스트 알림을 보냈습니다.")
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
