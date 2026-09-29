"""Catch-up scheduler: GitHub drops many scheduled runs (the Daily reel's three crons fired twice in three days),
so this decides what should be running right now and starts it with workflow_dispatch.

  Daily reel: each slot owns a window from its start (11:07, 15:07, 19:07 UTC) to the next slot's start (or
  midnight). Inside a slot's window, if that slot has not posted today and no Daily reel run is queued or
  running, start one for that slot (it waits for the post time itself, or posts right away when late). A slot
  whose window has passed is skipped, never posted late on top of the next one.
  Weekly: on Sunday from 10:00 UTC, if no Weekly run has started today, start one (it posts the carousel).
  Learning: on each day in LEARN_DAYS (every day by default) from 06:00 UTC, if no Learning run has started today,
  start learn.yml.
  Study: on Sunday from 08:00 UTC, if no scheduled or hand-started Study videos run has started today, start
  study.yml with auto (the weekly study of other creators; runs from "study" issues do not count).

Safe to run as often as you like: it only starts what is missing, and publish.py itself never posts a slot twice.
Runs from scheduler.yml (every 10 minutes when GitHub delivers it) and from any outside trigger that dispatches
scheduler.yml. Standard library only; uses the gh CLI.

Env: GH_TOKEN (Actions write), GITHUB_REPOSITORY, LEARN_DAYS (days the learning loop runs: empty or "daily" for
     every day, or day names such as "sun,wed")
Usage: python scheduler.py          start whatever is due
       python scheduler.py --dry    only print the decision
"""

import json
import os
import subprocess
import sys
from datetime import datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
QUEUE = ROOT / 'reels.json'
# When each slot's run starts (UTC); the post times (12:00, 16:00, 20:00) are set in daily-reel.yml.
SLOT_STARTS = {1: time(11, 7), 2: time(15, 7), 3: time(19, 7)}
WEEKLY_START = time(10, 0)  # Sundays
STUDY_START = time(8, 0)    # Sundays: the weekly study of other creators (study.yml)
LEARN_START = time(6, 0)    # 11 AM Pakistan; yesterday's reels are a day old by then
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
ACTIVE = ('queued', 'in_progress', 'waiting', 'requested', 'pending')
MAX_ATTEMPTS = 2  # runs started in one slot's window; a slot that keeps failing is left for a person to look at


def slot_of(reel):
    """Which of the day's slots a posted reel filled: recorded since slots were tracked, else from the post hour."""
    if reel.get('slot'):
        return int(reel['slot'])
    hour = datetime.fromisoformat(reel['posted_at']).astimezone(timezone.utc).hour
    return 1 if hour < 14 else 2 if hour < 18 else 3


def posted_slots(reels, day):
    """The slots already posted on this UTC date."""
    return {slot_of(r) for r in reels if (r.get('posted_at') or '').startswith(day.isoformat())}


def window(now):
    """The slot whose window contains this moment, or None before the first slot of the day."""
    current = None
    for slot, start in sorted(SLOT_STARTS.items()):
        if now.time() >= start:
            current = slot
    return current


def started_in_window(now, daily_runs):
    """Daily reel runs created since the current slot's window opened today."""
    slot = window(now)
    if slot is None:
        return 0
    opened = datetime.combine(now.date(), SLOT_STARTS[slot], timezone.utc)
    return sum(1 for r in daily_runs if datetime.fromisoformat(r['createdAt'].replace('Z', '+00:00')) >= opened)


def due_reel(now, reels, daily_runs):
    """The slot to start now, or None: its window is open, it has not posted today, nothing is running, and it has
    not already been tried MAX_ATTEMPTS times in this window."""
    slot = window(now)
    busy = any(r['status'] in ACTIVE for r in daily_runs)
    if slot is None or busy or slot in posted_slots(reels, now.date()):
        return None
    if started_in_window(now, daily_runs) >= MAX_ATTEMPTS:
        print(f'Slot {slot} was already tried {MAX_ATTEMPTS} times in its window; not starting it again')
        return None
    return slot


def due_weekly(now, weekly_runs_today):
    return now.weekday() == 6 and now.time() >= WEEKLY_START and not weekly_runs_today


def due_study(now, study_runs_today):
    """The Sunday study, when no scheduled or started-by-hand run happened today (issue runs do not count)."""
    return now.weekday() == 6 and now.time() >= STUDY_START and not [r for r in study_runs_today if r.get('event') != 'issues']


def learn_days(value):
    """The weekdays (0 is Monday) the learning loop runs on, from LEARN_DAYS."""
    names = [d.strip().lower()[:3] for d in (value or '').replace(' ', ',').split(',') if d.strip()]
    if not names or names == ['dai']:
        return set(range(7))
    unknown = [n for n in names if n not in DAYS]
    if unknown:
        raise SystemExit(f'LEARN_DAYS has unknown days: {", ".join(unknown)} (use e.g. "daily" or "sun,wed")')
    return {DAYS.index(n) for n in names}


def due_learn(now, learn_runs_today, days):
    return now.weekday() in days and now.time() >= LEARN_START and not learn_runs_today


def gh(*args):
    return subprocess.run(['gh', *args], capture_output=True, text=True, check=True).stdout


def runs(workflow):
    """Recent runs of a workflow: [{'status', 'createdAt', 'event'}]."""
    return json.loads(gh('run', 'list', '--workflow', workflow, '--limit', '20', '--json', 'status,createdAt,event'))


def main():
    dry = '--dry' in sys.argv
    now = datetime.now(timezone.utc)
    reels = json.loads(QUEUE.read_text())
    daily = runs('daily-reel.yml')
    print(f"{now:%Y-%m-%d %H:%M} UTC: window slot {window(now)}, posted today {sorted(posted_slots(reels, now.date()))}, "
          f"daily runs active: {sum(r['status'] in ACTIVE for r in daily)}, started in this window: "
          f"{started_in_window(now, daily)}")
    slot = due_reel(now, reels, daily)
    if slot:
        print(f'Starting Daily reel for slot {slot}')
        if not dry:
            gh('workflow', 'run', 'daily-reel.yml', '-f', 'dry_run=false', '-f', f'slot={slot}')
    weekly_today = [r for r in runs('weekly.yml') if r['createdAt'][:10] == now.date().isoformat()]
    if due_weekly(now, weekly_today):
        print('Starting Weekly (the Sunday schedule did not run)')
        if not dry:
            gh('workflow', 'run', 'weekly.yml', '-f', 'post_carousel=true')
    learn_today = [r for r in runs('learn.yml') if r['createdAt'][:10] == now.date().isoformat()]
    learn = due_learn(now, learn_today, learn_days(os.environ.get('LEARN_DAYS')))
    if learn:
        print('Starting Learning (today\'s analysis)')
        if not dry:
            gh('workflow', 'run', 'learn.yml')
    study_today = [r for r in runs('study.yml') if r['createdAt'][:10] == now.date().isoformat()] \
        if now.weekday() == 6 else []
    study = due_study(now, study_today)
    if study:
        print('Starting the weekly study of other creators')
        if not dry:
            gh('workflow', 'run', 'study.yml', '-f', 'auto=true')
    if not slot and not due_weekly(now, weekly_today) and not learn and not study:
        print('Nothing to start')


if __name__ == '__main__':
    main()
