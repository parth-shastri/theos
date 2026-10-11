#!/usr/bin/env python3
"""Build a report-style PDF from one Markdown file.

Usage:
    uv run --with markdown python build_doc.py doc.md --out doc.pdf [--html doc.html]

Without uv:  pip install markdown  &&  python3 build_doc.py doc.md --out doc.pdf

The Markdown file may contain, beyond ordinary Markdown:
  * front matter (eyebrow, title, meta, badge) between two `---` lines at the top
  * ```flow blocks of raw HTML that draw a box-and-arrow diagram (see references/flow-diagrams.md)
  * <!--include: path.html--> to pull a flow diagram from a separate file
  * ```mermaid blocks that hold a sequenceDiagram (see references/sequence-diagrams.md)
  * !!! note "Title" / !!! warning "Title" callouts with an indented body
"""
# /// script
# requires-python = ">=3.10"
# dependencies = ["markdown>=3.11,<4"]
# ///

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    import markdown
except ImportError:
    sys.exit('The "markdown" package is missing. Run with: uv run --with markdown python build_doc.py ...')

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..', 'assets')


# ---------- front matter ----------

def front_matter(src):
    m = re.match(r'---\n(.*?)\n---\n', src, flags=re.S)
    if not m:
        return {}, src
    fm = {}
    for line in m.group(1).splitlines():
        if ':' in line:
            k, v = line.split(':', 1)
            fm[k.strip()] = v.strip()
    return fm, src[m.end():]


def cover(fm):
    if not fm.get('title'):
        return ''
    parts = ['<header class="cover">']
    if fm.get('eyebrow'):
        parts.append(f'<div class="eyebrow">{html.escape(fm["eyebrow"])}</div>')
    parts.append(f'<h1>{html.escape(fm["title"])}</h1>')
    meta = []
    for pair in filter(None, (p.strip() for p in fm.get('meta', '').split('|'))):
        k, _, v = pair.partition('=')
        meta.append(f'<span><b>{html.escape(k.strip())}</b> {html.escape(v.strip())}</span>')
    if fm.get('badge'):
        meta.append(f'<span class="badge">{html.escape(fm["badge"])}</span>')
    if meta:
        parts.append(f'<div class="meta">{"".join(meta)}</div>')
    parts.append('</header>')
    return ''.join(parts)


# ---------- sequence diagrams ----------

def esc(t):
    return html.escape(t.strip())


def sequence(src):
    parts, order, primary, external = {}, [], set(), set()
    for line in src.splitlines():
        line = line.strip()
        m = re.match(r'%%\s*(primary|external)\s*:\s*(.*)$', line)
        if m:
            names = {n.strip() for n in m.group(2).split(',') if n.strip()}
            (primary if m.group(1) == 'primary' else external).update(names)
            continue
        m = re.match(r'(participant|actor)\s+(\w+)(?:\s+as\s+(.*))?$', line)
        if m:
            order.append(m.group(2))
            parts[m.group(2)] = m.group(3) or m.group(2)
            if m.group(1) == 'actor':
                external.add(m.group(2))
    if not order:
        raise ValueError('A sequence diagram needs participant or actor lines.')
    n = len(order)
    col = {p: i for i, p in enumerate(order)}
    cx = lambda p: (col[p] + 0.5) * 100 / n

    out, depth, num = [], 0, 0
    for raw in src.splitlines():
        line = raw.strip()
        if not line or line.startswith(('sequenceDiagram', 'autonumber', 'participant', 'actor', '%%')):
            continue
        m = re.match(r'(loop|alt|opt|par|critical|break)\s*(.*)$', line)
        if m:
            depth += 1
            out.append(f'<div class="frame" style="--d:{depth - 1}"><div class="ftag">'
                       f'<em>{m.group(1)}</em>{esc(m.group(2))}</div>')
            continue
        m = re.match(r'(else|and)\s*(.*)$', line)
        if m:
            out.append(f'<div class="felse"><div class="ftag"><em>{m.group(1)}</em>{esc(m.group(2))}</div></div>')
            continue
        if line == 'end':
            depth -= 1
            out.append('</div>')
            continue
        m = re.match(r'Note (?:over|left of|right of) ([\w, ]+):\s*(.*)$', line)
        if m:
            ps = [p.strip() for p in m.group(1).split(',')]
            lo, hi = min(cx(p) for p in ps), max(cx(p) for p in ps)
            half = 50 / n
            left, right = max(lo - half + 1, 0.5), min(hi + half - 1, 99.5)
            if right - left < 40:
                c = (left + right) / 2
                left, right = max(c - 20, 0.5), min(c + 20, 99.5)
            out.append(f'<div class="srow"><div class="note" style="margin-left:{left:.2f}%;'
                       f'width:{right - left:.2f}%">{esc(m.group(2))}</div></div>')
            continue
        m = re.match(r'(\w+)\s*(-->>|->>|-->|->|--x|-x|--\)|-\))\s*([+-]?)(\w+)\s*:\s*(.*)$', line)
        if not m:
            raise ValueError(f'Unsupported sequence line: {line}')
        a, arrow, _, b, text = m.groups()
        num += 1
        dashed = ' dashed' if arrow.startswith('--') else ''
        badge = f'<i class="num">{num}</i>'
        if a == b:
            x = cx(a)
            flip = x > 62
            pos = f'margin-right:{100 - x + 3:.2f}%' if flip else f'margin-left:{x + 3:.2f}%'
            out.append(f'<div class="srow selfrow"><div class="loop{dashed}{" flip" if flip else ""}" '
                       f'style="left:{x:.2f}%"></div><div class="lbl self{" flip" if flip else ""}" '
                       f'style="{pos}">{badge}{esc(text)}</div></div>')
            continue
        xa, xb = cx(a), cx(b)
        lo, hi = min(xa, xb), max(xa, xb)
        w = min(max(hi - lo, 34), 52)
        left = min(max((lo + hi) / 2 - w / 2, 0), 100 - w)
        out.append(f'<div class="srow"><div class="lbl" style="margin-left:{left:.2f}%;width:{w:.2f}%">{badge}{esc(text)}</div>'
                   f'<div class="arrow {"r" if xb > xa else "l"}{dashed}" style="left:{lo:.2f}%;width:{hi - lo:.2f}%"></div></div>')
    if depth != 0:
        raise ValueError('A loop, alt, or opt block in a sequence diagram has no matching end.')

    heads = ''.join(
        f'<div class="phead {"primary" if p in primary else "ext" if p in external else ""}" '
        f'style="left:{cx(p):.2f}%;width:{100 / n - 1.6:.2f}%">{esc(parts[p])}</div>' for p in order)
    lifelines = ''.join(f'<div class="life" style="left:{cx(p):.2f}%"></div>' for p in order)
    return (f'<div class="fig seq"><div class="sheads">{heads}</div>'
            f'<div class="sbody">{lifelines}{"".join(out)}</div></div>')


# ---------- page assembly ----------

def build_html(md_path):
    src = open(md_path, encoding='utf-8').read()
    fm, src = front_matter(src)
    base = os.path.dirname(os.path.abspath(md_path))
    blocks = []

    def stash(fragment):
        blocks.append(fragment)
        return f'\n\n<!--BLOCK{len(blocks) - 1}-->\n\n'

    def mermaid(m):
        body = m.group(1)
        if not re.search(r'^\s*sequenceDiagram', body, flags=re.M):
            raise ValueError('Only Mermaid sequenceDiagram blocks are supported. '
                             'Draw flowcharts as a ```flow block (see references/flow-diagrams.md).')
        return stash(sequence(body))

    src = re.sub(r'```mermaid\n(.*?)```', mermaid, src, flags=re.S)
    src = re.sub(r'```flow\n(.*?)```', lambda m: stash(m.group(1)), src, flags=re.S)
    src = re.sub(r'<!--include:\s*(.*?)\s*-->',
                 lambda m: stash(open(os.path.join(base, m.group(1)), encoding='utf-8').read()), src)

    def callout(m):
        kind, title, body = m.group(1), m.group(2), re.sub(r'^    ', '', m.group(3), flags=re.M)
        inner = markdown.markdown(body.strip(), extensions=['sane_lists'])
        inner = re.sub(r'^<p>', f'<p><b>{html.escape(title)}</b> ', inner, count=1) if title else inner
        return stash(f'<div class="callout c-{kind}">{inner}</div>')

    src = re.sub(r'^!!! (\w+)(?: "(.*?)")?\n((?:    .*\n?|\n)+)', callout, src, flags=re.M)

    body = markdown.markdown(src, extensions=['tables', 'fenced_code', 'sane_lists'])
    for i, frag in enumerate(blocks):
        body = re.sub(rf'(<p>)?<!--BLOCK{i}-->(</p>)?', lambda _m, f=frag: f, body)

    body = re.sub(r'<h2>(\d+)\.?\s+(.*?)</h2>',
                  lambda m: f'<h2><span class="n">{int(m.group(1)):02d}</span>{m.group(2)}</h2>', body)
    body = re.sub(r'<h3>(\d+\.\d+)\.?\s+(.*?)</h3>', r'<h3><span class="n">\1</span>\2</h3>', body)
    body = body.replace('<p><strong>', '<p class="lead"><strong>')

    css = open(os.path.join(ASSETS, 'style.css'), encoding='utf-8').read()
    js = open(os.path.join(ASSETS, 'edges.js'), encoding='utf-8').read()
    title = html.escape(fm.get('title', os.path.splitext(os.path.basename(md_path))[0]))
    return (f'<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>'
            f'<style>{css}</style></head><body>{cover(fm)}{body}<script>{js}</script></body></html>')


def find_chrome():
    for c in (os.environ.get('CHROME'),
              '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
              '/Applications/Chromium.app/Contents/MacOS/Chromium',
              shutil.which('google-chrome'), shutil.which('google-chrome-stable'),
              shutil.which('chromium'), shutil.which('chromium-browser')):
        if c and os.path.exists(c):
            return c
    sys.exit('Chrome or Chromium is required. Set CHROME to its path.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('markdown')
    ap.add_argument('--out', required=True, help='PDF path to write')
    ap.add_argument('--html', help='also keep the intermediate HTML at this path')
    a = ap.parse_args()

    page = build_html(a.markdown)
    html_path = a.html or os.path.join(tempfile.mkdtemp(), 'doc.html')
    open(html_path, 'w', encoding='utf-8').write(page)
    # The virtual-time budget lets the web fonts load and edges.js draw the arrows before printing.
    subprocess.run([find_chrome(), '--headless', '--disable-gpu', '--no-pdf-header-footer',
                    '--virtual-time-budget=20000', '--run-all-compositor-stages-before-draw',
                    f'--print-to-pdf={os.path.abspath(a.out)}', 'file://' + os.path.abspath(html_path)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f'Wrote {a.out}' + (f' and {a.html}' if a.html else ''))


if __name__ == '__main__':
    main()
