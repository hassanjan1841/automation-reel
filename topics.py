"""The topic board: every day, what developers are searching for, reading and watching right now, ranked for this
account, for the writer to pick from and for the creator to see (the "Topic board" issue). Asked for on 2026-11-03:
"find more reliable sources for trends and good topics ... it will work daily".

Sources, all free and allowed (never Reddit; only what a topic is, never anyone's words, code or footage):
  - Stack Overflow: the most-viewed questions of the last year in our tags (errors people really search for)
  - YouTube: the watched channels' recent Shorts that beat their channel's usual (studies/channels.json; the
    official API, numbers only, nothing downloaded)
  - GitHub: new repositories gaining stars fast (new developer and AI tools)
  - dev.to: the week's top articles
  - Hacker News: this week's top stories
One Claude call (no tools) ranks them into up to MAX_TOPICS topics for this account, each with an angle for one of
our formats and the sources it came from; a topic citing a link that was not collected is dropped. A topic the
creator ticks in the issue is skipped for SKIP_DAYS, by the board and by the writer.

Usage:
  python topics.py              make today's board: topics.json and out/topics.md (the issue body)
  python topics.py --collect    print the collected candidates only (no Claude, nothing written)
Env: YOUTUBE_API_KEY (optional: the YouTube source), STACKEXCHANGE_KEY (optional: a higher Stack Overflow quota),
     GITHUB_TOKEN (optional: a higher GitHub search quota), CLAUDE_MODEL (optional, defaults to generate.MODEL).
     out/topic-board-issue.md, when the workflow saved the issue's current body there, gives the ticked topics.
"""

import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

import generate
import render
import trends

BOARD = render.ROOT / 'topics.json'
ISSUE_MD = render.OUT_DIR / 'topics.md'
ISSUE_NOW = render.OUT_DIR / 'topic-board-issue.md'
ISSUE_TITLE = 'Topic board'
CHANNELS = render.ROOT / 'studies' / 'channels.json'
UA = {'User-Agent': 'automation-reel topic board (github.com/hassanjan1841/automation-reel)'}
SO_TAGS = ('javascript', 'reactjs', 'next.js', 'typescript', 'node.js', 'css', 'tailwind-css', 'git', 'vite')
SO_DAYS = 365          # questions asked in the last year: recent errors with proven search demand
YT_DAYS = 14           # Shorts published in the last two weeks
YT_OUTLIER = 5         # at least this many times the channel's median views
YT_MIN_VIEWS = 5000
GH_DAYS = 14           # repositories created in the last two weeks
GH_MIN_STARS = 300
MAX_TOPICS = 10
FRESH_DAYS = 2         # the writer uses a board at most this old
SKIP_DAYS = 30         # a ticked topic stays out this long
FORMATS = ('myth', 'trick', 'explained', 'versus', 'news')


def get(url, headers=None, **kw):
    resp = requests.get(url, headers={**UA, **(headers or {})}, timeout=30, **kw)
    resp.raise_for_status()
    return resp.json()


# ---------- the sources ----------

def stack_overflow(now=None):
    """The most-viewed questions of the last year in our tags: errors and how-tos developers search for."""
    now = now or datetime.now(timezone.utc)
    since = int((now - timedelta(days=SO_DAYS)).timestamp())
    key = os.environ.get('STACKEXCHANGE_KEY', '').strip()
    out, seen = [], set()
    for tag in SO_TAGS:
        data = get('https://api.stackexchange.com/2.3/questions', params={
            'order': 'desc', 'sort': 'votes', 'tagged': tag, 'site': 'stackoverflow', 'pagesize': 15,
            'fromdate': since, **({'key': key} if key else {})})
        for q in data.get('items', []):
            if q['question_id'] in seen:
                continue
            seen.add(q['question_id'])
            out.append({'source': 'Stack Overflow', 'title': _plain(q['title']), 'url': q['link'],
                        'signal': f"{q['view_count']:,} views, {q.get('answer_count', 0)} answers, tag {tag}",
                        'weight': q['view_count']})
        time.sleep(0.2)
    return sorted(out, key=lambda c: -c['weight'])[:30]


def youtube_outliers(now=None):
    """Recent Shorts of the watched channels that got far more views than their channel usually does."""
    key = os.environ.get('YOUTUBE_API_KEY', '').strip()
    if not key or not CHANNELS.exists():
        return []
    now = now or datetime.now(timezone.utc)
    out = []
    for cid, meta in json.loads(CHANNELS.read_text()).items():
        if not cid.startswith('UC'):
            continue
        # The uploads playlist (UU...) costs 1 quota unit a page; search would cost 100.
        items = get('https://www.googleapis.com/youtube/v3/playlistItems', params={
            'part': 'contentDetails', 'playlistId': 'UU' + cid[2:], 'maxResults': 30, 'key': key}).get('items', [])
        ids = [i['contentDetails']['videoId'] for i in items]
        if not ids:
            continue
        videos = get('https://www.googleapis.com/youtube/v3/videos', params={
            'part': 'snippet,statistics,contentDetails', 'id': ','.join(ids), 'key': key}).get('items', [])
        shorts = [v for v in videos if _seconds(v['contentDetails'].get('duration', '')) <= 180]
        if len(shorts) < 5:
            continue
        usual = statistics.median(int(v['statistics'].get('viewCount', 0)) for v in shorts) or 1
        for v in shorts:
            views = int(v['statistics'].get('viewCount', 0))
            when = datetime.fromisoformat(v['snippet']['publishedAt'].replace('Z', '+00:00'))
            if views >= YT_MIN_VIEWS and views >= YT_OUTLIER * usual and now - when <= timedelta(days=YT_DAYS):
                out.append({'source': 'YouTube Shorts', 'title': v['snippet']['title'],
                            'url': f"https://www.youtube.com/shorts/{v['id']}",
                            'signal': f"{views:,} views, {views / usual:.0f}x the channel's usual "
                                      f"({meta.get('title', '').strip()})", 'weight': views / usual})
    return sorted(out, key=lambda c: -c['weight'])[:20]


def github_new(now=None):
    """New repositories gaining stars fast: the developer and AI tools people are trying this week."""
    now = now or datetime.now(timezone.utc)
    token = os.environ.get('GITHUB_TOKEN', '').strip()
    data = get('https://api.github.com/search/repositories', params={
        'q': f"created:>{(now - timedelta(days=GH_DAYS)).date().isoformat()} stars:>{GH_MIN_STARS}",
        'sort': 'stars', 'order': 'desc', 'per_page': 25},
        headers={'Authorization': f'Bearer {token}'} if token else None)
    return [{'source': 'GitHub', 'title': f"{r['full_name']}: {(r.get('description') or '').strip()}"[:200],
             'url': r['html_url'], 'signal': f"{r['stargazers_count']:,} stars in under {GH_DAYS} days",
             'weight': r['stargazers_count']} for r in data.get('items', [])]


def devto_week():
    """The week's top dev.to articles: what developers are reading and arguing about."""
    return [{'source': 'dev.to', 'title': a['title'], 'url': a['url'],
             'signal': f"{a.get('public_reactions_count', 0)} reactions, {a.get('comments_count', 0)} comments, "
                       f"tags {', '.join(a.get('tag_list') or [])}",
             'weight': a.get('public_reactions_count', 0) + 3 * a.get('comments_count', 0)}
            for a in get('https://dev.to/api/articles', params={'top': 7, 'per_page': 30})]


def hacker_news():
    return [{**{k: c[k] for k in ('source', 'title', 'url', 'signal')}, 'weight': 0} for c in trends.hacker_news()][:30]


SOURCES = {'Stack Overflow': stack_overflow, 'YouTube Shorts': youtube_outliers, 'GitHub': github_new,
           'dev.to': devto_week, 'Hacker News': hacker_news}


def collect():
    """Every source's candidates; a source that fails is reported and left out, the others still count."""
    out, failed = [], []
    for name, fetch in SOURCES.items():
        try:
            found = fetch()
            print(f'{name}: {len(found)}')
            out += found
        except Exception as e:  # a source being down never stops the board
            print(f'{name} unavailable ({type(e).__name__}: {str(e)[:150]})')
            failed.append(name)
    return out, failed


def _plain(text):
    import html
    return html.unescape(text or '').strip()


def _seconds(duration):
    """ISO 8601 durations as the YouTube API gives them (PT1M5S) in seconds."""
    m = re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration or '')
    if not m:
        return 10 ** 6
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


# ---------- ranking ----------

SYSTEM = """You pick topics for a faceless developer Instagram and YouTube Shorts account (web development and AI
coding tools; its own numbers say myths about famous basics and practical AI-coding-tool reels work, under 20
seconds). You get today's candidates from Stack Overflow (questions developers search for), YouTube Shorts that beat
their channel's usual, new GitHub repositories gaining stars, dev.to's week and Hacker News.

Pick up to %d topics this account could make a strong, honest reel about soon, best first. A topic seen in more than
one source, or with a strong signal, ranks higher. For each: the topic in a few plain words; an angle in one sentence
for one of our formats (myth: a belief most developers hold that real code disproves; trick: a shortcut or setting;
explained: a small story, problem first, then the fix; versus: two real options compared; news: a dated release or
event, only from its official source); why, citing the numbers from the candidates; the candidate URLs it came from
(only URLs given below); and official: the official docs or release page where every fact for the reel must come
from (empty if you are not sure it exists).

Rules: a topic is an idea, never a copy: no one's script, title, code or video is reused. Skip anything that needs
facts we cannot check on an official page, anything about gambling, betting, interest, adult content or deceptive
tools, politics, people's deaths, and anything in the skip list. Skip topics this account already covered (its
recent hooks are listed)."""

SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['topics'],
    'properties': {'topics': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False,
        'required': ['topic', 'format', 'angle', 'why', 'sources', 'official'],
        'properties': {'topic': {'type': 'string'}, 'format': {'type': 'string', 'enum': list(FORMATS)},
                       'angle': {'type': 'string'}, 'why': {'type': 'string'},
                       'sources': {'type': 'array', 'items': {'type': 'string'}},
                       'official': {'type': 'string'}}}}},
}


def ask_claude(prompt):
    proc = subprocess.run(
        ['claude', '-p', prompt, '--model', os.environ.get('CLAUDE_MODEL') or generate.MODEL,
         '--system-prompt', SYSTEM % MAX_TOPICS, '--tools', '', '--setting-sources', '', '--no-session-persistence',
         '--output-format', 'json', '--json-schema', json.dumps(SCHEMA)],
        capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
    if proc.returncode != 0:
        raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-300:]}')
    result = json.loads(proc.stdout)
    if result.get('is_error') or not result.get('structured_output'):
        raise RuntimeError(f"claude returned no structured output: {str(result.get('result'))[:300]}")
    return result['structured_output']['topics']


def rank(candidates, recent_hooks, skipped):
    """Claude's ranked topics, keeping only those whose sources are all collected candidates (nothing invented)."""
    listing = '\n'.join(f"- [{c['source']}] {c['title']} | {c['signal']} | {c['url']}" for c in candidates)
    prompt = (f'Candidates ({len(candidates)}):\n{listing}\n\nSkip list (the creator ticked these): '
              + (', '.join(skipped) or 'none') + '\n\nThis account\'s recent hooks:\n'
              + '\n'.join(f'- {h}' for h in recent_hooks))
    known = {c['url'] for c in candidates}
    kept = []
    for t in ask_claude(prompt):
        if not t.get('sources') or any(u not in known for u in t['sources']):
            print(f"  dropped {t.get('topic')!r}: it cites a link that was not collected")
            continue
        if t['topic'].strip().lower() in {s.lower() for s in skipped}:
            continue
        kept.append({k: (v.strip() if isinstance(v, str) else v) for k, v in t.items()})
    return kept[:MAX_TOPICS]


# ---------- the board: topics.json, the issue, the creator's ticks ----------

def load():
    return json.loads(BOARD.read_text()) if BOARD.exists() else {}


def ticked(issue_text):
    """Topic names the creator ticked in the issue ("- [x] **name** ..."): skip them."""
    return [m.group(1).strip() for m in re.finditer(r'^\s*[-*] \[[xX]\] \*\*(.+?)\*\*', issue_text or '', re.M)]


def skip_list(board, issue_text, today):
    """Ticked topics, kept SKIP_DAYS from the day they were first ticked."""
    keep = {s['topic']: s['since'] for s in board.get('skipped', [])
            if date.fromisoformat(s['since']) >= today - timedelta(days=SKIP_DAYS)}
    for name in ticked(issue_text):
        keep.setdefault(name, today.isoformat())
    return [{'topic': k, 'since': v} for k, v in sorted(keep.items())]


def markdown(board):
    lines = [f"## Topic board, {board['date']}", '',
             'What developers are searching for, reading and watching right now, ranked for this account. The '
             'writer picks from it (only the topic: every fact comes from official pages, nothing is copied). '
             f'**Tick a box to skip that topic** for {SKIP_DAYS} days.', '']
    for t in board['topics']:
        links = ', '.join(f'[{_label(u)}]({u})' for u in t['sources'])
        official = f" · official: {t['official']}" if t.get('official') else ''
        lines.append(f"- [ ] **{t['topic']}** ({t['format']}): {t['angle']}  \n  _{t['why']}_ ({links}){official}")
    if board.get('failed'):
        lines += ['', f"Unavailable today: {', '.join(board['failed'])}."]
    if board.get('skipped'):
        lines += ['', 'Skipped: ' + ', '.join(s['topic'] for s in board['skipped'])]
    return '\n'.join(lines) + '\n'


def _label(url):
    return {'stackoverflow.com': 'Stack Overflow', 'youtube.com': 'YouTube', 'github.com': 'GitHub',
            'dev.to': 'dev.to', 'news.ycombinator.com': 'HN'}.get(
        re.sub(r'^www\.', '', url.split('/')[2]) if '//' in url else url, 'link')


def fresh(today=None):
    """Today's usable topics for the writer: a board at most FRESH_DAYS old, without skipped topics."""
    board = load()
    today = today or datetime.now(timezone.utc).date()
    if not board.get('date') or date.fromisoformat(board['date']) < today - timedelta(days=FRESH_DAYS):
        return []
    skipped = {s['topic'].lower() for s in board.get('skipped', [])}
    return [t for t in board.get('topics', []) if t['topic'].lower() not in skipped]


def main():
    args = sys.argv[1:]
    candidates, failed = collect()
    if '--collect' in args:
        for c in candidates:
            print(f"[{c['source']}] {c['title'][:90]} | {c['signal']}")
        return
    if not candidates:
        raise SystemExit('No source answered today; the board stays as it was')
    today = datetime.now(timezone.utc).date()
    board = load()
    skipped = skip_list(board, ISSUE_NOW.read_text() if ISSUE_NOW.exists() else '', today)
    reels = json.loads(render.QUEUE.read_text())
    hooks = [r['hook'].replace('*', '') for r in reels[-40:] if r.get('hook')]
    topics = rank(candidates, hooks, [s['topic'] for s in skipped])
    if not topics:
        raise SystemExit('Claude kept no topic; the board stays as it was')
    board = {'date': today.isoformat(), 'topics': topics, 'skipped': skipped, 'failed': failed}
    BOARD.write_text(json.dumps(board, indent=2, ensure_ascii=False) + '\n')
    render.OUT_DIR.mkdir(exist_ok=True)
    ISSUE_MD.write_text(markdown(board))
    print(f'{len(topics)} topics on the board:')
    for t in topics:
        print(f"  {t['topic']} ({t['format']})")


if __name__ == '__main__':
    main()
