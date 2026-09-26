"""Pronunciation regression test.

  python test_voice.py           text rules and matching only (fast, no models)
  python test_voice.py --audio   also speak every sentence and listen back with Whisper
"""

import sys

import voice

SPEAKABLE = [
    ('half the price of GPT-5.6 Luna', 'half the price of GPT-5 point 6 Luna'),
    ('Edge runtime and 15.x untouched', 'Edge runtime and 15 point x untouched'),
    ('Luna costs $0.10 per million', 'Luna costs 10 cents per million'),
    ('Input dropped to $4, a 20% cut', 'Input dropped to 4 dollars, a 20 percent cut'),
    ('Upgrade to 16.3.6 now', 'Upgrade to 16 point 3 point 6 now'),
]

MISHEARD = [
    ('Redis caches the hot data.', 'Redis cashes the hot data.', []),
    ('Supabase runs on Postgres.', 'Super Bass runs on PostgreSQL.', ['Postgres', 'Supabase']),
    ('Put secrets in your .env file.', 'Put secrets in your .n file.', ['.env']),
    ('Drizzle and Prisma are both ORMs.', 'Drizzle and Prisma are both ORM.', []),
    ('Deploy your Next.js app to Vercel.', 'Deploy your next JS app to Vercel.', []),
    ('GPT-5.6 costs $0.10 per million.', 'GPT 5.6 costs 10 cents per million.', []),
]

SENTENCES = """Anthropic just released Claude Opus.
Supabase runs on Postgres.
Deploy your Next.js app to Vercel.
TypeScript catches bugs before users do.
Most SaaS founders never validate the idea.
I found my first client on Upwork.
The API returns JSON.
Store your JWT in an httpOnly cookie.
Use OAuth instead of rolling your own login.
Run npm install and then npx prisma migrate.
Drizzle and Prisma are both ORMs.
Tailwind makes CSS faster to write.
Stripe webhooks can arrive twice.
Kubernetes is overkill for your MVP.
Your useEffect is fetching data twice.
RAG gives an LLM your own documents.
Cursor and GitHub Copilot write code for you.
Nginx sits in front of your Node server.
Redis caches the hot data.
GPT-5.6 costs $0.10 per million tokens.
Put secrets in your .env file.
A CRUD app is where everyone starts.
Webhooks, cron jobs and queues.
Row Level Security in Supabase.
Zod validates the request body.
React Server Components render on the server.
SQL injection is still common.""".splitlines()

# Said correctly, but Whisper cannot spell them back ("Vite" is heard as "Veet").
KNOWN = {'Vite', 'Nginx'}


def main():
    failures = []
    for text, want in SPEAKABLE:
        got = voice.speakable(text)
        if got != want:
            failures.append(f'speakable({text!r}) = {got!r}, want {want!r}')
    for written, heard, want in MISHEARD:
        got = voice.misheard(written, heard)
        if got != want:
            failures.append(f'misheard({written!r}, {heard!r}) = {got}, want {want}')

    if '--audio' in sys.argv:
        engine = voice.Engine()
        for line in SENTENCES:
            heard = voice.transcribe(engine.say(voice.speakable(line)))
            bad = set(voice.misheard(line, heard)) - KNOWN
            if bad:
                failures.append(f'{sorted(bad)} misheard in {line!r} -> {heard.strip()!r}')

    for f in failures:
        print('FAIL', f)
    print(f'{len(failures)} failures')
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
