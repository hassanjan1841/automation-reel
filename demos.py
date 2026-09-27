"""Real screen recordings for reels: website walkthroughs and live coding in a real VS Code (typing, running
commands in its terminal). Recorded from the browser's own high-quality screencast, with a visible cursor, click
ripples, human typing, and blurring of anything that looks private.

A point may carry:
  {"type": "walkthrough", "url": "https://zod.dev", "steps": [
      {"do": "scroll_to", "text": "Basic usage"}, {"do": "click", "text": "Basic usage"},
      {"do": "type", "into": "Search", "text": "refine"}, {"do": "wait", "seconds": 1}]}
  {"type": "ide", "files": {"user.ts": "import { z } from 'zod'\\n"}, "setup": ["npm i zod tsx"], "steps": [
      {"do": "open", "file": "user.ts"}, {"do": "type", "text": "const User = z.object({ email: z.string() })"},
      {"do": "run", "command": "npx tsx user.ts", "wait": "Error|ok"}]}

The IDE is openvscode-server (Linux; Docker on macOS) started with an empty environment, so nothing it runs can
see the pipeline's secrets; setup and run commands must start with an allowed program.

Usage: python demos.py record '<visual json>' [width height]   records to out/clips/ and prints the path
"""

import base64
import hashlib
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import render

CLIPS = render.OUT_DIR / 'clips'
TOOLS = render.ROOT / 'models' / 'tools'
MAX_STEPS = 10
DPR = 2
IDE_DPR = 1.6
# VS Code follows the browser's platform: Cmd on macOS, Ctrl on Linux.
MOD = 'Meta' if sys.platform == 'darwin' else 'Control'
DOC_END = 'Meta+ArrowDown' if sys.platform == 'darwin' else 'Control+End'
OVS_VERSION = 'v1.109.5'
ALLOWED = ('npm ', 'npx ', 'node ', 'pnpm ', 'bun ', 'python ', 'python3 ', 'pip ', 'git ', 'ls', 'cat ', 'echo ',
           'tsc', 'deno ', 'go ', 'cargo ', 'curl ')

CURSOR_JS = r"""
(() => {
  if (window.__reelCursor) return;
  const add = () => {
    const c = document.createElement('div');
    c.style.cssText = 'position:fixed;left:-50px;top:-50px;width:22px;height:28px;z-index:2147483647;' +
      'pointer-events:none;transform:translate(-3px,-2px)';
    c.innerHTML = '<svg width="22" height="28" viewBox="0 0 22 28"><path d="M2 2 L2 22 L7.5 17 L11 25 L14.5 23.5 ' +
      'L11 16 L18 16 Z" fill="#fff" stroke="#14161c" stroke-width="2" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    window.__reelCursor = c;
    document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; },
      true);
    document.addEventListener('mousedown', e => {
      const r = document.createElement('div');
      r.style.cssText = `position:fixed;left:${e.clientX - 18}px;top:${e.clientY - 18}px;width:36px;height:36px;` +
        'border-radius:50%;border:4px solid #FF6A3D;z-index:2147483646;pointer-events:none;' +
        'transition:transform 0.55s ease-out,opacity 0.55s ease-out';
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.transform = 'scale(2.6)'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 700);
    }, true);
  };
  if (document.documentElement) add(); else document.addEventListener('DOMContentLoaded', add);
})();
"""

# Floating widgets (chat bubbles, "Ask AI" buttons, cookie and announcement bars) cover what we show; hide them.
DECLUTTER_JS = r"""
(() => {
  const tidy = () => {
    if (!document.body) return;
    for (const el of document.querySelectorAll('body *')) {
      if (el === window.__reelCursor || el.dataset.reelKept) continue;
      const s = getComputedStyle(el);
      if (s.position !== 'fixed' && s.position !== 'sticky') continue;
      const r = el.getBoundingClientRect();
      const floating = s.position === 'fixed' && r.top > innerHeight * 0.45 && r.height < innerHeight * 0.5;
      const bar = /cookie|consent|banner|announce|promo|newsletter|chat|intercom|crisp|drift/i
        .test((el.id || '') + ' ' + (el.className && el.className.baseVal === undefined ? el.className : ''));
      if (floating || bar) el.style.setProperty('display', 'none', 'important');
      else el.dataset.reelKept = '1';
    }
  };
  tidy();
  setInterval(tidy, 800);
})();
"""

MASK_JS = r"""
(() => {
  const secret = /([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})|(\b(sk|pk|rk|sb|ghp|gho|xox[abp]|eyJ)[A-Za-z0-9_\-.]{12,})/;
  const blur = el => { el.style.filter = 'blur(7px)'; el.dataset.reelMasked = '1'; };
  const scan = () => {
    if (!document.body) return;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (secret.test(n.textContent) && n.parentElement && !n.parentElement.dataset.reelMasked) blur(n.parentElement);
    }
    document.querySelectorAll('input[type=password], input[type=email]').forEach(el => el.dataset.reelMasked || blur(el));
  };
  scan();
  new MutationObserver(scan).observe(document.documentElement, {subtree: true, childList: true, characterData: true});
})();
"""

# VS Code settings for footage: nothing distracting, nothing that rewrites what is typed.
IDE_SETTINGS = {
    'workbench.startupEditor': 'none', 'workbench.tips.enabled': False, 'telemetry.telemetryLevel': 'off',
    'workbench.activityBar.location': 'hidden', 'workbench.statusBar.visible': False, 'breadcrumbs.enabled': False,
    'editor.minimap.enabled': False, 'workbench.layoutControl.enabled': False, 'window.commandCenter': False,
    'extensions.ignoreRecommendations': True, 'workbench.enableExperiments': False, 'update.mode': 'none',
    'workbench.colorTheme': 'Default Dark Modern', 'editor.fontSize': 15, 'editor.lineHeight': 24,
    'terminal.integrated.fontSize': 14, 'editor.fontFamily': "'JetBrains Mono', Menlo, monospace",
    'editor.autoClosingBrackets': 'never', 'editor.autoClosingQuotes': 'never', 'editor.autoIndent': 'none',
    'editor.formatOnType': False, 'editor.quickSuggestions': {'other': False, 'comments': False, 'strings': False},
    'editor.suggestOnTriggerCharacters': False, 'editor.parameterHints.enabled': False, 'editor.hover.enabled': False,
    'editor.lightbulb.enabled': 'off', 'editor.wordBasedSuggestions': 'off', 'editor.acceptSuggestionOnEnter': 'off',
    'editor.renderWhitespace': 'none', 'editor.glyphMargin': False, 'editor.folding': False,
    'editor.stickyScroll.enabled': False, 'editor.cursorBlinking': 'smooth', 'files.autoSave': 'afterDelay',
    'workbench.editor.showTabs': 'single', 'chat.commandCenter.enabled': False, 'git.enabled': False,
    'terminal.integrated.enablePersistentSessions': False, 'security.workspace.trust.enabled': False,
    'terminal.integrated.showExitAlert': False, 'window.title': ' ', 'workbench.tree.renderIndentGuides': 'none',
    'terminal.integrated.tabs.enabled': False, 'terminal.integrated.defaultProfile.linux': 'bash',
    'terminal.integrated.profiles.linux': {'bash': {'path': 'bash', 'args': ['--norc', '--noprofile']}},
    'terminal.integrated.env.linux': {'PS1': '$ '}, 'terminal.integrated.cursorBlinking': True,
    'chat.disableAIFeatures': True, 'workbench.secondarySideBar.defaultVisibility': 'hidden',
    'workbench.welcomePage.walkthroughs.openOnInstall': False, 'workbench.editor.empty.hint': 'hidden',
    'editor.wordWrap': 'on', 'editor.scrollBeyondLastLine': False, 'workbench.panel.defaultLocation': 'bottom',
}


# ---------- recording ----------

class Screencast:
    """Collects Chrome's screencast frames (full device-pixel JPEGs) and stitches them into a constant-rate mp4."""

    def __init__(self, page, width, height):
        self.frames, self.cdp = [], page.context.new_cdp_session(page)
        self.cdp.on('Page.screencastFrame', self.on_frame)
        self.cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 92, 'maxWidth': width,
                                              'maxHeight': height, 'everyNthFrame': 1})

    def on_frame(self, params):
        self.frames.append((params['metadata']['timestamp'], base64.b64decode(params['data'])))
        try:
            self.cdp.send('Page.screencastFrameAck', {'sessionId': params['sessionId']})
        except Exception:
            pass

    def stop(self):
        try:
            self.cdp.send('Page.stopScreencast')
        except Exception:
            pass

    def save(self, out, min_seconds=3.0):
        if len(self.frames) < 2 or self.frames[-1][0] - self.frames[0][0] < min_seconds:
            raise RuntimeError('the recording is too short; the steps probably did not run')
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            for i, (ts, data) in enumerate(self.frames):
                path = Path(tmp) / f'{i:05d}.jpg'
                path.write_bytes(data)
                nxt = self.frames[i + 1][0] if i + 1 < len(self.frames) else ts + 0.5
                lines += [f"file '{path}'", f'duration {max(0.001, nxt - ts):.4f}']
            lines.append(f"file '{Path(tmp) / f'{len(self.frames) - 1:05d}.jpg'}'")
            (Path(tmp) / 'list.txt').write_text('\n'.join(lines))
            subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(Path(tmp) / 'list.txt'),
                            '-vf', 'fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2', '-c:v', 'libx264', '-crf', '16',
                            '-pix_fmt', 'yuv420p', str(out)], check=True)


def locate(page, text, frame=None):
    """The best visible element for a piece of text: a button or link first, then inputs, then any text."""
    root = frame or page
    for loc in (root.get_by_role('button', name=text), root.get_by_role('link', name=text),
                root.get_by_placeholder(text), root.get_by_label(text), root.get_by_text(text)):
        try:
            el = loc.first
            el.wait_for(state='visible', timeout=2500)
            return el
        except Exception:
            continue
    raise RuntimeError(f'nothing on the page matches "{text}"')


def centre(el):
    box = el.bounding_box()
    return box['x'] + box['width'] / 2, box['y'] + box['height'] / 2


def smooth_scroll_to(page, el, height):
    for _ in range(80):
        box = el.bounding_box()
        if not box:
            break
        delta = box['y'] - height / 3
        if abs(delta) < 30:
            break
        page.mouse.wheel(0, max(-120, min(120, delta)))
        page.wait_for_timeout(30)


def browser_context(p, width, height, mobile=True, dpr=DPR):
    # Without the forced scale factor the headless screencast sends CSS-pixel frames (half resolution at DPR 2).
    browser = p.chromium.launch(args=['--disable-blink-features=AutomationControlled',
                                      f'--force-device-scale-factor={dpr}'])
    ctx = browser.new_context(viewport={'width': width, 'height': height}, device_scale_factor=dpr,
                              is_mobile=mobile, color_scheme='dark' if not mobile else 'light')
    ctx.add_init_script(CURSOR_JS)
    ctx.add_init_script(f'document.addEventListener("DOMContentLoaded", () => {{ {MASK_JS} }});')
    return browser, ctx


def cache_path(spec, size):
    key = hashlib.sha1(json.dumps({**spec, 'size': size, 'v': 11}, sort_keys=True).encode()).hexdigest()[:16]
    CLIPS.mkdir(parents=True, exist_ok=True)
    return CLIPS / f'{key}.mp4'


def record_walkthrough(spec, size):
    """A website walkthrough at the card's aspect: scrolling, clicking and typing like a person."""
    out = cache_path(spec, size)
    if out.exists():
        return out
    from playwright.sync_api import sync_playwright
    w, h = size[0] // DPR, size[1] // DPR
    with sync_playwright() as p:
        browser, ctx = browser_context(p, w, h)
        page = ctx.new_page()
        try:
            resp = page.goto(spec['url'], wait_until='domcontentloaded', timeout=45000)
            if resp and resp.status >= 400:
                raise RuntimeError(f'HTTP {resp.status}')
            page.wait_for_timeout(1800)
            page.evaluate(MASK_JS)
            page.evaluate(DECLUTTER_JS)
            page.wait_for_timeout(300)
            page.mouse.move(w * 0.75, h * 0.8)
            cast = Screencast(page, size[0], size[1])
            page.wait_for_timeout(600)
            for step in spec.get('steps', [])[:MAX_STEPS]:
                web_step(page, step, h)
            page.wait_for_timeout(900)
            cast.stop()
        finally:
            ctx.close()
            browser.close()
    cast.save(out)
    return out


def web_step(page, step, height):
    kind = step.get('do')
    if kind in ('scroll_to', 'click', 'hover'):
        el = locate(page, step['text'])
        smooth_scroll_to(page, el, height)
        page.mouse.move(*centre(el), steps=22)
        if kind == 'click':
            page.wait_for_timeout(250)
            el.click()
            page.wait_for_load_state('domcontentloaded')
    elif kind == 'type':
        el = locate(page, step['into'])
        page.mouse.move(*centre(el), steps=18)
        el.click()
        el.press_sequentially(step['text'], delay=75)
        if step.get('enter'):
            el.press('Enter')
    elif kind == 'scroll':
        for _ in range(int(float(step.get('screens', 1)) * 10)):
            page.mouse.wheel(0, 90)
            page.wait_for_timeout(35)
    elif kind != 'wait':
        raise RuntimeError(f'unknown step "{kind}"')
    page.wait_for_timeout(int(1000 * float(step.get('seconds', 0.7))))


# ---------- IDE ----------

def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def allowed(command):
    c = command.strip()
    return any(c == a.strip() or c.startswith(a) for a in ALLOWED) and not any(t in c for t in ('env', 'printenv',
                                                                                              '$', '`', '>', '|', ';'))


def start_ide(workspace, port):
    """openvscode-server on localhost with an empty environment. Returns the process (or container id)."""
    data = Path(workspace).parent / 'ovs-data'
    # The server reads machine settings from <server-data-dir>/data/Machine/settings.json.
    (data / 'data' / 'Machine').mkdir(parents=True, exist_ok=True)
    (data / 'data' / 'Machine' / 'settings.json').write_text(json.dumps(IDE_SETTINGS))
    (Path(workspace) / '.vscode').mkdir(exist_ok=True)
    (Path(workspace) / '.vscode' / 'settings.json').write_text(json.dumps(IDE_SETTINGS))
    clean = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(data), 'TERM': 'xterm-256color',
             'PS1': '$ ', 'LANG': 'C.UTF-8'}
    if platform.system() == 'Linux':
        server = ensure_ovs()
        return subprocess.Popen([str(server), '--host', '127.0.0.1', '--port', str(port), '--without-connection-token',
                                 '--server-data-dir', str(data), '--user-data-dir', str(data / 'user'),
                                 '--default-folder', str(workspace)], env=clean,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # macOS: the Linux build in Docker, with the workspace mounted.
    return subprocess.Popen(['docker', 'run', '--rm', '-p', f'127.0.0.1:{port}:3000', '-v', f'{workspace}:/home/workspace',
                             '-v', f'{data}/data/Machine/settings.json:/home/.openvscode-server/data/Machine/settings.json',
                             '--entrypoint', '', 'gitpod/openvscode-server:latest', 'sh', '-c',
                             'exec ${OPENVSCODE_SERVER_ROOT}/bin/openvscode-server --host 0.0.0.0 --port 3000 '
                             '--without-connection-token --default-folder /home/workspace'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ensure_ovs():
    root = TOOLS / f'openvscode-server-{OVS_VERSION}-linux-x64'
    if not root.exists():
        TOOLS.mkdir(parents=True, exist_ok=True)
        tar = TOOLS / 'ovs.tar.gz'
        urllib.request.urlretrieve('https://github.com/gitpod-io/openvscode-server/releases/download/'
                                   f'openvscode-server-{OVS_VERSION}/openvscode-server-{OVS_VERSION}-linux-x64.tar.gz', tar)
        subprocess.run(['tar', '-xzf', str(tar), '-C', str(TOOLS)], check=True)
        tar.unlink()
    return root / 'bin' / 'openvscode-server'


def wait_up(port, timeout=90):
    t = time.time()
    while time.time() - t < timeout:
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=3)
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError('the IDE did not start')


def record_ide(spec, size):
    """Live coding in a real VS Code: open files, type code at a human pace, run commands in its terminal."""
    out = cache_path(spec, size)
    if out.exists():
        return out
    for cmd in spec.get('setup', []) + [s['command'] for s in spec.get('steps', []) if s.get('do') == 'run']:
        if not allowed(cmd):
            raise RuntimeError(f'command not allowed on camera: {cmd!r}')
    from playwright.sync_api import sync_playwright
    port = free_port()
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp) / 'workspace'
        ws.mkdir()
        for name, content in spec.get('files', {}).items():
            path = ws / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        clean = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': tmp}
        for cmd in spec.get('setup', []):
            subprocess.run(cmd, shell=True, cwd=ws, env=clean, timeout=240, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        server = start_ide(ws, port)
        try:
            wait_up(port)
            # A little less zoom than websites, so a whole snippet and the terminal fit, still readable.
            w, h = round(size[0] / IDE_DPR), round(size[1] / IDE_DPR)
            with sync_playwright() as p:
                browser, ctx = browser_context(p, w, h, mobile=False, dpr=IDE_DPR)
                page = ctx.new_page()
                page.goto(f'http://127.0.0.1:{port}/?folder=/home/workspace' if platform.system() != 'Linux'
                          else f'http://127.0.0.1:{port}/?folder={ws}', wait_until='domcontentloaded')
                page.locator('.monaco-workbench').wait_for(timeout=60000)
                page.wait_for_timeout(2500)
                prime_ide(page)
                tidy_ide(page)
                cast = Screencast(page, size[0], size[1])
                page.wait_for_timeout(500)
                for step in spec.get('steps', [])[:MAX_STEPS]:
                    ide_step(page, step)
                page.wait_for_timeout(1000)
                cast.stop()
                ctx.close()
                browser.close()
            cast.save(out)
        finally:
            server.terminate()
            if platform.system() != 'Linux':
                subprocess.run('docker ps -q --filter ancestor=gitpod/openvscode-server:latest | xargs -r docker kill',
                               shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out


def prime_ide(page):
    """Apply IDE_SETTINGS as user settings (the web build keeps them in the browser, so files on disk are not
    enough), then reload into a clean window. Happens before recording starts."""
    accept_trust(page)
    palette(page, 'Preferences: Open User Settings (JSON)')
    page.wait_for_timeout(1500)
    page.locator('.editor-group-container .monaco-editor .view-lines').first.click()
    page.keyboard.press(f'{MOD}+a')
    page.keyboard.insert_text(json.dumps(IDE_SETTINGS, indent=1))
    page.keyboard.press(f'{MOD}+s')
    page.wait_for_timeout(800)
    palette(page, 'View: Close All Editors')
    page.wait_for_timeout(500)
    page.reload(wait_until='domcontentloaded')
    page.locator('.monaco-workbench').wait_for(timeout=60000)
    page.wait_for_timeout(2500)
    accept_trust(page)
    for command in ('View: Close Primary Side Bar', 'View: Close Panel', 'View: Close All Editors'):
        palette(page, command)
        page.wait_for_timeout(400)
    hide_aux_bar(page)


def hide_aux_bar(page):
    """The secondary side bar (empty 'Drag a view here' area) has no reliable command name across versions;
    toggle it off with its shortcut while it is visible."""
    for _ in range(2):
        aux = page.locator('.part.auxiliarybar')
        if aux.count() and aux.first.is_visible():
            page.keyboard.press(f'{MOD}+Alt+b')
            page.wait_for_timeout(500)


def accept_trust(page):
    for _ in range(3):
        trust = page.get_by_role('button', name='Yes, I trust the authors')
        if trust.count() and trust.first.is_visible():
            trust.first.click()
            page.wait_for_timeout(800)


def tidy_ide(page):
    """Accept the workspace trust prompt (our own throwaway folder), then close the side bar so the editor
    fills the frame."""
    accept_trust(page)
    hide_aux_bar(page)
    page.keyboard.press('Escape')


def palette(page, text):
    page.keyboard.press(f'{MOD}+Shift+P')
    page.wait_for_timeout(300)
    page.keyboard.type(text, delay=20)
    page.wait_for_timeout(300)
    page.keyboard.press('Enter')


def ide_step(page, step):
    kind = step.get('do')
    if kind == 'open':
        page.keyboard.press(f'{MOD}+p')
        page.wait_for_timeout(350)
        page.keyboard.type(step['file'], delay=35)
        page.wait_for_timeout(400)
        page.keyboard.press('Enter')
        page.wait_for_timeout(700)
        if step.get('line'):
            page.keyboard.press('Control+g')
            page.keyboard.type(str(step['line']), delay=40)
            page.keyboard.press('Enter')
        else:
            page.keyboard.press(DOC_END)
    elif kind == 'type':
        # The code editor itself, not the chat or search boxes that are also Monaco editors.
        page.locator('.editor-group-container .monaco-editor .view-lines').first.click()
        page.keyboard.press(DOC_END)
        for i, line in enumerate(step['text'].split('\n')):
            if i:
                page.keyboard.press('Enter')
                page.keyboard.press('Home')
            page.keyboard.type(line, delay=int(step.get('delay', 55)))
    elif kind == 'run':
        # Focus (not toggle) the terminal, then click into it so the keystrokes land there.
        palette(page, 'Terminal: Focus Terminal')
        # Type only once the shell has printed its prompt, or the first keys are lost.
        rows = page.locator('.xterm-rows').last
        for _ in range(40):
            if '$' in (rows.inner_text() if rows.count() else ''):
                break
            page.wait_for_timeout(250)
        # A freshly created terminal does not keep focus; focus it again now that it exists.
        palette(page, 'Terminal: Focus Terminal')
        page.wait_for_timeout(600)
        page.keyboard.type(step['command'], delay=45)
        page.keyboard.press('Enter')
        if step['command'].split()[0] not in rows.inner_text():
            raise RuntimeError('the command did not reach the terminal')
        deadline = time.time() + float(step.get('timeout', 25))
        while time.time() < deadline:
            page.wait_for_timeout(500)
            if step.get('wait') and page.locator('.xterm-rows').filter(has_text=__import__('re').compile(step['wait'])).count():
                break
    elif kind == 'save':
        page.keyboard.press(f'{MOD}+s')
    elif kind != 'wait':
        raise RuntimeError(f'unknown IDE step "{kind}"')
    page.wait_for_timeout(int(1000 * float(step.get('seconds', 0.6))))


def record(spec, size=(980, 620)):
    size = (round(size[0] / 2) * 2, round(size[1] / 2) * 2)
    kind = spec.get('type')
    if kind == 'walkthrough':
        return record_walkthrough(spec, size)
    if kind == 'ide':
        return record_ide(spec, size)
    raise RuntimeError(f'not a recordable visual: {kind}')


def main():
    if len(sys.argv) not in (3, 5) or sys.argv[1] != 'record':
        raise SystemExit(__doc__)
    size = (int(sys.argv[3]), int(sys.argv[4])) if len(sys.argv) == 5 else (980, 620)
    print(record(json.loads(sys.argv[2]), size))


if __name__ == '__main__':
    main()
