"""Find what is trending in dev and AI right now and turn the best story into a reel.

Scrapes Hacker News, GitHub Trending, dev.to, Lobsters, YouTube and AI/dev blog feeds, adds how
recent posts performed, then has Claude (web search + fetch enabled) pick the story with
the most reach for this audience, verify it against its sources and write the reel.

Usage:
  python trends.py            print the scraped candidates
  python trends.py --pick     also let Claude choose and write a reel (prints it, saves nothing)

Env: YOUTUBE_API_KEY (optional, skips YouTube without it), IG_TOKEN (optional, for performance),
     CLAUDE_MODEL (optional, defaults to generate.MODEL)
"""

import html
import json
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

import generate

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/140 Safari/537.36'
MAX_AGE = timedelta(days=4)
MIN_REACH = 7

FEEDS = {
    'Anthropic': 'https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml',
    'OpenAI': 'https://openai.com/news/rss.xml',
    'Google AI': 'https://blog.google/technology/ai/rss/',
    'Hugging Face': 'https://huggingface.co/blog/feed.xml',
    'Simon Willison': 'https://simonwillison.net/atom/everything/',
    'TechCrunch AI': 'https://techcrunch.com/category/artificial-intelligence/feed/',
    'The Verge AI': 'https://www.theverge.com/rss/ai-artificial-intelligence/index.xml',
    'GitHub Blog': 'https://github.blog/feed/',
    'Vercel': 'https://vercel.com/atom',
    'Next.js': 'https://nextjs.org/feed.xml',
    'Supabase': 'https://supabase.com/rss.xml',
    'Product Hunt': 'https://www.producthunt.com/feed',
}


def get(url, **kw):
    return requests.get(url, headers={'User-Agent': UA}, timeout=25, **kw)


def age_label(when):
    if not when:
        return ''
    hours = (datetime.now(timezone.utc) - when).total_seconds() / 3600
    return f'{hours:.0f}h ago' if hours < 48 else f'{hours / 24:.0f}d ago'


def hacker_news():
    out = []
    since = int(time.time() - MAX_AGE.total_seconds())
    queries = [
        'https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=40',
        f'https://hn.algolia.com/api/v1/search?tags=story&numericFilters=created_at_i>{since},points>150&hitsPerPage=40',
    ]
    seen = set()
    for q in queries:
        for h in get(q).json()['hits']:
            if h['objectID'] in seen:
                continue
            seen.add(h['objectID'])
            when = datetime.fromtimestamp(h['created_at_i'], timezone.utc)
            out.append({'source': 'Hacker News', 'title': h['title'],
                        'url': h.get('url') or f"https://news.ycombinator.com/item?id={h['objectID']}",
                        'signal': f"{h.get('points', 0)} points, {h.get('num_comments', 0)} comments", 'when': when})
    return out


def github_trending():
    page = get('https://github.com/trending?since=daily').text
    out = []
    for block in page.split('<article class="Box-row">')[1:26]:
        repo = re.search(r'href="/([^"/]+/[^"/]+)"', block)
        desc = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', block, re.S)
        today = re.search(r'([\d,]+) stars today', block)
        if repo:
            out.append({'source': 'GitHub Trending', 'title': repo.group(1) + (
                f' - {html.unescape(re.sub("<[^>]+>", "", desc.group(1))).strip()}' if desc else ''),
                'url': f'https://github.com/{repo.group(1)}',
                'signal': f"{today.group(1)} stars today" if today else '', 'when': None})
    return out


def devto():
    out = []
    for a in get('https://dev.to/api/articles?top=3&per_page=30').json():
        out.append({'source': 'dev.to', 'title': a['title'], 'url': a['url'],
                    'signal': f"{a.get('public_reactions_count', 0)} reactions, {a.get('comments_count', 0)} comments",
                    'when': datetime.fromisoformat(a['published_at'].replace('Z', '+00:00'))})
    return out


def lobsters():
    out = []
    for s in get('https://lobste.rs/hottest.json').json()[:25]:
        out.append({'source': 'Lobsters', 'title': s['title'], 'url': s.get('url') or s['short_id_url'],
                    'signal': f"{s['score']} points, tags {', '.join(s['tags'])}",
                    'when': datetime.fromisoformat(s['created_at'])})
    return out


YOUTUBE_QUERIES = ['AI coding', 'Claude Code', 'ChatGPT developers', 'Next.js', 'web development',
                   'new AI model', 'SaaS', 'freelance developer']


def youtube():
    key = os.environ.get('YOUTUBE_API_KEY')
    if not key:
        return []
    after = (datetime.now(timezone.utc) - MAX_AGE).strftime('%Y-%m-%dT%H:%M:%SZ')
    ids, when = [], {}
    for q in YOUTUBE_QUERIES:
        # search costs 100 quota units; 8 queries a day stays far under the free 10,000
        res = get('https://www.googleapis.com/youtube/v3/search', params={
            'part': 'snippet', 'q': q, 'type': 'video', 'order': 'viewCount', 'publishedAfter': after,
            'relevanceLanguage': 'en', 'maxResults': 8, 'key': key}).json()
        if 'error' in res:
            raise RuntimeError(res['error'].get('message', 'YouTube error'))
        for item in res.get('items', []):
            vid = item['id']['videoId']
            if vid not in when:
                ids.append(vid)
                when[vid] = datetime.fromisoformat(item['snippet']['publishedAt'].replace('Z', '+00:00'))
    out = []
    for i in range(0, len(ids), 50):
        stats = get('https://www.googleapis.com/youtube/v3/videos', params={
            'part': 'snippet,statistics', 'id': ','.join(ids[i:i + 50]), 'key': key}).json()
        for v in stats.get('items', []):
            st = v['statistics']
            out.append({'source': 'YouTube', 'title': f"{v['snippet']['title']} ({v['snippet']['channelTitle']})",
                        'url': f"https://www.youtube.com/watch?v={v['id']}",
                        'signal': f"{int(st.get('viewCount', 0)):,} views, {int(st.get('likeCount', 0)):,} likes",
                        'when': when[v['id']], 'views': int(st.get('viewCount', 0))})
    return sorted(out, key=lambda o: -o['views'])[:30]


def parse_date(text):
    if not text:
        return None
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(text.strip().replace('Z', '+00:00'))
    except ValueError:
        return None


def feed(name, url):
    root = ET.fromstring(get(url, allow_redirects=True).content)
    out = []
    for item in root.iter():
        tag = item.tag.split('}')[-1]
        if tag not in ('item', 'entry'):
            continue
        fields = {c.tag.split('}')[-1]: c for c in item}
        title = (fields.get('title').text or '').strip() if fields.get('title') is not None else ''
        link = fields.get('link')
        href = (link.get('href') or link.text or '').strip() if link is not None else ''
        date = next((fields[k].text for k in ('pubDate', 'published', 'updated', 'date') if k in fields), None)
        when = parse_date(date)
        if title and href and when and datetime.now(timezone.utc) - when <= MAX_AGE:
            out.append({'source': name, 'title': html.unescape(title), 'url': href, 'signal': '', 'when': when})
    return out[:10]


def collect():
    items, failed = [], []
    jobs = [('Hacker News', hacker_news), ('GitHub Trending', github_trending), ('dev.to', devto),
            ('Lobsters', lobsters), ('YouTube', youtube)] + [(n, lambda n=n, u=u: feed(n, u)) for n, u in FEEDS.items()]
    for name, job in jobs:
        try:
            items += job()
        except Exception as e:  # one broken source must not stop the scan
            failed.append(f'{name} ({type(e).__name__})')
    fresh = [i for i in items if not i['when'] or datetime.now(timezone.utc) - i['when'] <= MAX_AGE]
    return fresh, failed


def performance():
    """How recent reels did, so Claude learns which topics land with this audience."""
    token = os.environ.get('IG_TOKEN')
    if not token:
        return []
    base = 'https://graph.instagram.com/v25.0'
    try:
        media = get(f'{base}/me/media', params={'fields': 'id,caption,media_type,timestamp', 'limit': 20,
                                                 'access_token': token}).json().get('data', [])
    except requests.RequestException:
        return []
    lines = []
    for m in media:
        caption = ((m.get('caption') or '').strip().splitlines() or ['(no caption)'])[0][:80]
        stats = ''
        try:
            res = get(f"{base}/{m['id']}/insights", params={
                'metric': 'views,reach,saved,shares,total_interactions' + (
                    ',ig_reels_avg_watch_time,reels_skip_rate' if m.get('media_type') == 'VIDEO' else ''),
                'access_token': token}).json()
            vals = {d['name']: d['values'][0]['value'] for d in res.get('data', [])}
            if vals:
                watch = vals.pop('ig_reels_avg_watch_time', None)
                skip = vals.pop('reels_skip_rate', None)
                stats = ', '.join(f'{k} {v}' for k, v in vals.items()) + (f', avg watch {watch / 1000:.1f}s' if watch else '') + (
                    f', {skip}% skipped in the first 3s' if skip is not None else '')
        except (requests.RequestException, KeyError, ValueError):
            pass
        lines.append(f"{m.get('timestamp', '')[:10]}  {stats or 'no insights'}: {caption}")
    return lines


OPTION = {
    'type': 'object',
    'properties': {
        'reach_score': {'type': 'integer', 'minimum': 1, 'maximum': 10},
        'reason': {'type': 'string'},
        'sources': {'type': 'array', 'items': {'type': 'string'}},
        'reel': generate.SCHEMA['properties']['reels']['items'],
    },
    'required': ['reach_score', 'reason', 'sources', 'reel'],
    'additionalProperties': False,
}
SCHEMA = {
    'type': 'object',
    'properties': {'options': {'type': 'array', 'items': OPTION}},
    'required': ['options'],
    'additionalProperties': False,
}

SYSTEM = generate.SYSTEM.replace(
    '- Evergreen only. No news, release dates, version numbers, prices or anything that goes stale.\n',
    '') + """

You are also the account's editor. Each day you decide whether today's reel should cover something
happening right now in AI and web development, and if so, which story will reach the most developers,
freelancers and indie SaaS builders on Instagram.

How to choose:
- Prefer news with broad developer impact: major model releases, big tool or framework launches,
  pricing or policy changes that affect how people build, and breakout open source projects.
- Strong signals: many sources covering it, high Hacker News points, fast GitHub stars, official announcements.
- Angle it for practitioners: what changed, why it matters for their work, one practical takeaway.
- Skip gossip, funding rounds, lawsuits, politics and drama unless they change how developers work.
- Do not repeat a topic that was already posted recently.

Real voices (only when allowed this week, see the prompt):
- When a story is about how developers are reacting to or using something, up to 2 points may show a real
  public post as a "quote" visual: author, handle, platform (X, Hacker News, GitHub, Bluesky, Threads,
  LinkedIn, Mastodon, YouTube or Blog), its url, and the text copied exactly (shorten only with "..." at
  the ends, never change words). Pick posts from developers, founders and companies; never mock a private
  person. The voiceover adds the creator's own take on each; a reel is never just a list of quotes.

Verification is mandatory:
- Use WebSearch and WebFetch to read the primary source (official blog, docs, changelog or repo) before writing.
- Every fact on the slides must be supported by a page you fetched. Put those URLs in "sources", primary source first.
- Check whether the story has moved on since it was published (a fix, a reversal, an official reply) and write
  the reel as things stand today. Never say something is still broken or unfixed without a current source.
- Report what happened without guessing at motives: no "hid", "secretly" or "quietly" about a real company
  unless a source shows intent.
- Return up to 3 options: the strongest distinct stories you could verify, best first, each a complete reel.
- Return an empty list if nothing today beats a good evergreen tip.
- reach_score is your honest estimate from 1 to 10 of how well the reel will spread compared with a typical evergreen tip.
- Count words carefully: hook 5 to 8, point titles max 4, point bodies max 16, voiceover 40 to 55 in total. Over-long reels are thrown away."""


def claude(prompt, system, schema, model=None):
    proc = subprocess.run(
        ['claude', '-p', prompt, '--model', model or os.environ.get('CLAUDE_MODEL', generate.MODEL),
         '--system-prompt', system, '--tools', 'WebSearch', 'WebFetch', '--allowedTools', 'WebSearch', 'WebFetch',
         '--setting-sources', '', '--no-session-persistence', '--output-format', 'json',
         '--json-schema', json.dumps(schema)],
        capture_output=True, text=True, timeout=1200, stdin=subprocess.DEVNULL,
    )
    if proc.returncode != 0:
        raise RuntimeError(f'claude exited {proc.returncode}: {proc.stderr.strip()[-400:]}')
    result = json.loads(proc.stdout)
    if result.get('is_error') or not result.get('structured_output'):
        raise RuntimeError(f"claude returned no structured output: {str(result.get('result'))[:300]}")
    return result['structured_output']


def quotes_allowed(reels, days=6):
    """Real posts at most once a week: Instagram reduces reach for accounts that repost others often."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return not any(r.get('posted_at') and datetime.fromisoformat(r['posted_at']) > since
                   and any(v.get('type') == 'quote' for p in r['points'] for v in p.get('visual') or [])
                   for r in reels)


def pick(reels, candidates, perf, model=None):
    recent = [r['hook'] for r in reels if r.get('posted_at')][-30:]
    lines = [f"- [{c['source']}] {c['title']} | {c['url']} | {c['signal']} {age_label(c['when'])}".strip()
             for c in candidates]
    prompt = (
        f"Today is {datetime.now(timezone.utc):%A %d %B %Y}.\n"
        + ('Quote visuals of real posts are allowed today.\n\n' if quotes_allowed(reels)
           else 'Quote visuals are NOT allowed today (one was used this week).\n\n')
        + generate.three_d_note() + '\n\n'
        + f"Trending items scraped in the last few days ({len(lines)}):\n" + '\n'.join(lines)
        + '\n\nRecently posted hooks (do not repeat these topics):\n' + '\n'.join(f'- {h}' for h in recent)
        + ('\n\nHow recent posts performed:\n' + '\n'.join(perf) if perf else '')
        + ('\n\nRules learned from this account\'s own results:\n' + generate.learned() if generate.learned() else '')
        + '\n\nSearch further if the list misses something big today, verify the best stories, and write up to 3 ranked reels.'
    )
    return claude(prompt, SYSTEM, SCHEMA, model)


CHECK_SCHEMA = {
    'type': 'object',
    'properties': {
        'verdict': {'type': 'string', 'enum': ['pass', 'fix', 'reject']},
        'problems': {'type': 'array', 'items': {'type': 'string'}},
        'reel': generate.SCHEMA['properties']['reels']['items'],
    },
    'required': ['verdict', 'problems', 'reel'],
    'additionalProperties': False,
}

CHECK_SYSTEM = """You are a strict fact-checker for short Instagram reels about software and AI.
Open every source URL with WebFetch and search for confirmation where needed. Check every claim on the
slides, in the voiceover and in the caption: names, versions, numbers, dates, prices, commands and what a product does.
- pass: every claim is supported by a page you read. Return the reel unchanged.
- Stories move on after they are published. Always search for newer developments after the source's date:
  fixes, patches, changelog entries, reversals, corrections, official replies. Prefer the official source
  (changelog, docs, the company's own post) over a blog about it.
- A claim that something is still broken, unfixed, ongoing, "no fix yet" or "right now" must be confirmed as
  still true today from a current source; if a later fix or change exists, the reel must say so (fix) or,
  if the whole point no longer holds, reject.
- Quote visuals: open each url and confirm the text is the author's exact words and the author, handle and
  platform are right. Fix a small copying error; reject the reel if a quote cannot be found or is misattributed.
- Describe what happened, not motives: words like "hid", "secretly", "quietly" or "sneaky" about a real
  company or person are only allowed when a source shows it was deliberate; otherwise reword neutrally (fix).
- fix: small wording or number errors you can correct from the sources. Return the corrected reel,
  keeping the same format and word limits (hook 5 to 8 words, titles max 4, bodies max 16).
- reject: the main claim is wrong, unsupported, or already outdated.
List each problem you found, even when fixed."""


def fact_check(reel, sources):
    prompt = ('Fact-check this reel against its sources.\n\nSources:\n' + '\n'.join(sources)
              + '\n\nReel:\n' + json.dumps(reel, indent=2, ensure_ascii=False))
    return claude(prompt, CHECK_SYSTEM, CHECK_SCHEMA)


def timely_reel(reels, perf=None):
    """A verified timely reel dict, or None to fall back to an evergreen reel."""
    candidates, failed = collect()
    print(f'Trend scan: {len(candidates)} fresh items' + (f', unavailable: {", ".join(failed)}' if failed else ''))
    if len(candidates) < 10:
        print('Too few sources answered, writing an evergreen reel')
        return None
    options = sorted(pick(reels, candidates, performance() if perf is None else perf)['options'], key=lambda o: -o['reach_score'])
    used = {u for r in reels for u in r.get('sources', [])}
    hooks = {generate.norm(r['hook']) for r in reels}
    for i, option in enumerate(options, 1):
        reel, sources = generate.tidy(option['reel']), [s for s in option['sources'] if s.startswith('http')]
        print(f"Option {i}: reach {option['reach_score']}/10, {reel['hook']!r}. {option['reason']}")
        errors = generate.validate(reel)
        if errors and option['reach_score'] >= MIN_REACH and sources:
            fixed = generate.repair(reel, errors)
            if fixed:
                reel, errors = fixed, []
        if option['reach_score'] < MIN_REACH:
            errors.append(f'reach below {MIN_REACH}')
        if not sources:
            errors.append('no sources')
        elif sources[0] in used:
            errors.append('story already posted')
        if generate.norm(reel['hook']) in hooks:
            errors.append('duplicate hook')
        if errors:
            print('  rejected: ' + '; '.join(errors))
            continue
        check = fact_check(reel, sources)
        print(f"  fact-check: {check['verdict']}" + (f" ({'; '.join(check['problems'])[:300]})" if check['problems'] else ''))
        if check['verdict'] == 'reject':
            continue
        reel = generate.tidy(check['reel'])
        errors = generate.validate(reel)
        if errors:
            fixed = generate.repair(reel, errors)
            if fixed:
                reel, errors = fixed, []
        if errors:
            print('  rejected after fact-check: ' + '; '.join(errors))
            continue
        return {**reel, 'pillar': 'timely', 'sources': sources}
    print('No timely option passed, writing an evergreen reel')
    return None


def main():
    candidates, failed = collect()
    for c in sorted(candidates, key=lambda c: c['source']):
        print(f"[{c['source']}] {c['title'][:90]}  {c['signal']} {age_label(c['when'])}")
    print(f'\n{len(candidates)} items; unavailable: {failed or "none"}')
    if '--pick' in sys.argv:
        reels = json.loads(generate.render.QUEUE.read_text())
        print(json.dumps(pick(reels, candidates, performance()), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
