#!/usr/bin/env python3
"""Generate the static site published to GitHub Pages.

    python3 tools/site.py [--out DIR]

Diagrams are laid out by graphviz at build time and inlined as SVG, so a page
ships no diagramming library at all: it is a few KB of markup that renders
before any script runs. Graphviz emits real anchors for node links, so the
graph is navigable with scripting disabled; the script only adds pan, zoom
and search on top.

Requires `dot` on PATH (Debian/Ubuntu: apt-get install graphviz).
"""

import html
import json
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

from graph import (
    ROOT,
    RELATIONS,
    Problem,
    clean,
    dot_source,
    incoming,
    is_crowded,
    load_all,
    members_of,
)

REPO = "https://github.com/kvark/aitia"
DOMAIN_NAME = "aitia.dev"

# Relation colouring.
#
# Eight fully distinct hues do not survive a colourblind-separation check when
# any two edges can end up side by side: the worst all-pairs pair measures a
# normal-vision ΔE of 7.1, far under the 15 floor. Searching the validated
# palette, four is the largest set that passes on both the light and the dark
# surface. So relations are grouped into four families that carry the colour,
# and the two members of each family are told apart by line pattern — the
# second channel — rather than by a fifth hue nobody could reliably name.
FAMILIES = {
    "supersede": ("supersedes", "#2a78d6", "#3987e5"),
    "structure": ("classifies", "#008300", "#008300"),
    "substitute": ("substitutes for", "#e87ba4", "#d55181"),
    "support": ("depends on", "#eda100", "#c98500"),
}

# rel -> (family, dashed)
RELATION_STYLE = {
    "corrects": ("supersede", False),
    "extends": ("supersede", True),
    "specializes": ("structure", False),
    "part-of": ("structure", True),
    "approximates": ("substitute", False),
    "alternative-to": ("substitute", True),
    "requires": ("support", False),
    "validates": ("support", True),
}

STYLE = """
:root {
  --bg: #fbfbfa; --fg: #1a1a19; --muted: #6b6b66; --line: #e2e2dd;
  --card: #ffffff; --accent: #7a4b2a; --code: #f2f2ee;
  --node-fill: #f7f7f4; --node-line: #cfcfc7; --edge-line: #b0b0a8;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #16171a; --fg: #e6e6e3; --muted: #9a9a94; --line: #2c2e33;
    --card: #1d1f23; --accent: #d79a6a; --code: #23252a;
    --node-fill: #262930; --node-line: #3f434c; --edge-line: #565b66;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font: 16px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
.wrap { max-width: 62rem; margin: 0 auto; padding: 1.5rem 1.25rem 5rem; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
nav { border-bottom: 1px solid var(--line); margin-bottom: 1.75rem;
      padding-bottom: .75rem; font-size: .9rem; display: flex; gap: 1rem;
      align-items: center; }
nav .home { font-weight: 600; white-space: nowrap; }
h1 { font-size: 1.9rem; line-height: 1.25; margin: 0 0 .4rem; }
h2 { font-size: 1.25rem; margin: 2.5rem 0 .5rem; }
h3 { font-size: 1rem; margin: 1.75rem 0 .5rem; text-transform: uppercase;
     letter-spacing: .06em; color: var(--muted); font-weight: 600; }
.lede { color: var(--muted); margin: 0 0 1.5rem; }
.meta { color: var(--muted); font-size: .875rem; margin: 0 0 1.25rem; }
.summary { font-size: 1.05rem; margin: 0 0 1.5rem; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .9em;
       background: var(--code); padding: .1em .35em; border-radius: 3px; }
.cards { display: grid; gap: .75rem; grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr)); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 8px;
        padding: .85rem 1rem; }
.card h4 { margin: 0 0 .25rem; font-size: 1rem; }
.card p { margin: 0; color: var(--muted); font-size: .85rem; }
.edges { list-style: none; padding: 0; margin: 0; }
.edges li { padding: .55rem 0; border-top: 1px solid var(--line); }
.edges li:first-child { border-top: 0; }
.rel { display: inline-block; font-size: .72rem; text-transform: uppercase;
       letter-spacing: .07em; padding: .12em .5em; border-radius: 3px;
       background: var(--code); color: var(--muted); margin-right: .5rem;
       font-family: ui-monospace, monospace; }
.why { color: var(--muted); display: block; margin-top: .15rem; font-size: .92rem; }

/* ---- search ---- */
.find { position: relative; flex: 1; max-width: 26rem; }
#q { width: 100%; padding: .42rem .7rem; font-size: .92rem; border-radius: 6px;
     border: 1px solid var(--line); background: var(--card); color: var(--fg); }
#q:focus { outline: none; border-color: var(--accent); }
#hits { position: absolute; z-index: 20; left: 0; right: 0; top: 2.3rem;
        background: var(--card); border: 1px solid var(--line); border-radius: 7px;
        list-style: none; margin: 0; padding: .25rem; max-height: 60vh;
        overflow-y: auto; display: none; box-shadow: 0 8px 26px rgba(0,0,0,.14); }
#hits.open { display: block; }
#hits li { padding: .35rem .5rem; border-radius: 5px; cursor: pointer;
           display: flex; gap: .5rem; align-items: baseline; }
#hits li.sel, #hits li:hover { background: var(--code); }
#hits .c { color: var(--muted); font-size: .78rem; margin-left: auto; }
#hits .none { color: var(--muted); cursor: default; }
kbd { font: .72rem ui-monospace, monospace; border: 1px solid var(--line);
      border-bottom-width: 2px; border-radius: 4px; padding: 0 .3em; color: var(--muted); }

/* ---- figures ---- */
.figure { margin: .75rem 0 2rem; }
/* Break out of the text column: a 29-node graph needs the whole window. */
.figure.wide { width: min(97vw, 1700px); margin-left: calc(50% - min(48.5vw, 850px)); }
.fig-head { display: flex; align-items: center; gap: .75rem; margin-bottom: .4rem;
            font-size: .78rem; color: var(--muted); }
.fig-head .hint { flex: 1; }
.found { font-variant-numeric: tabular-nums; }
.found.on { color: var(--accent); }
.diagram { position: relative; background: var(--card); border: 1px solid var(--line);
           border-radius: 8px; padding: .75rem; overflow: auto; }
/* Only once pan/zoom is live does the box become a fixed viewport. Without it
   the svg simply sits at its natural size and the page scrolls. */
.diagram.pz { overflow: hidden; min-height: 9rem; cursor: grab;
              user-select: none; -webkit-user-select: none; touch-action: none; }
.diagram.pz.grabbing { cursor: grabbing; }
.diagram.pz svg { width: 100%; height: 100%; max-width: none; display: block; }
.diagram:fullscreen { height: 100vh; width: 100vw; margin: 0; border-radius: 0; }
.tools { display: none; gap: .25rem; }
.figure.ready .tools { display: flex; }
.tools button { font: 600 .78rem/1 ui-monospace, monospace; color: var(--muted);
                background: var(--bg); border: 1px solid var(--line);
                border-radius: 5px; padding: .35rem .5rem; cursor: pointer; }
.tools button:hover { color: var(--fg); border-color: var(--muted); }

/* ---- the graph itself ---- */
.diagram svg { font-family: Helvetica, Arial, sans-serif; }
.diagram svg .graph > polygon { fill: none; stroke: none; }
/* Descendant, not child: a node that carries a URL — which is every node —
   wraps its box in the anchor graphviz emits, so `.node > path` matched
   nothing and the boxes kept graphviz's own black stroke and empty fill. */
.diagram svg .node path, .diagram svg .node polygon {
  fill: var(--node-fill); stroke: var(--node-line); }
.diagram svg .node text { fill: var(--fg); }
.diagram svg .node a:hover path { stroke: var(--accent); stroke-width: 1.8; }
.diagram svg .node.ext path { stroke-dasharray: 5 3; fill: none; }
.diagram svg .node.focus path { stroke: var(--accent); stroke-width: 2.2; }
.diagram svg .edge > path { stroke: var(--edge-line); fill: none; }
.diagram svg .edge > polygon { fill: var(--edge-line); stroke: var(--edge-line); }
.diagram svg .edge text { fill: var(--muted); }
.diagram svg a { text-decoration: none; }
.diagram svg .node, .diagram svg .edge { transition: opacity .14s ease; }

/* ---- prominence, in diagrams crowded enough to need a reading order ----
   The tier rules below deliberately carry no element selector, so every state
   rule that does — search, and the hover class the script sets — outranks them
   without a specificity fight. Ranking is a reading order and never a filter:
   it lifts when you hover a node, and it lifts wholesale once the diagram is
   drawn at its natural size or larger, which is also the point at which the
   reason on an edge becomes readable. */
/* A peripheral node fades by its box, not by its name: the outline is what
   makes the crowding, while the name is what you are scanning for. */
.ranked .node.p0 path { opacity: .32; }
.ranked .node.p0 text { opacity: .58; }
.ranked .edge.p0 { opacity: .26; }
.ranked .edge.p1 { opacity: .78; }
/* Junctions get a second channel rather than more opacity, which they have
   already spent: a heavier border, the way the edge families use a dash. */
.ranked .node.p2 path { stroke-width: 1.9; }
.ranked.detail .node path, .ranked.detail .node text { opacity: 1; }
.ranked.detail .edge { opacity: 1; }
.ranked .node.lit path, .ranked .node.lit text { opacity: 1; }
.ranked .edge.lit { opacity: 1; }

/* The reason on an edge, put back one node at a time. Drawn by the script at
   a constant size on screen, so it reads the same however far you have
   zoomed, and over a plate of the page's own background rather than over
   whatever the layout happens to run underneath. */
.diagram svg .why rect { fill: var(--card); stroke: var(--line); }
.diagram svg .why text { fill: var(--fg); }
/* The leader back to the edge: its colour comes from the relation class the
   group carries, so it only needs quietening. */
.diagram svg .why > path { opacity: .55; }

.diagram svg .node.dim, .diagram svg .edge.dim { opacity: .12; }
.diagram svg .node.hit, .diagram svg .node.hit path, .diagram svg .node.hit text { opacity: 1; }
.diagram svg .node.hit path { stroke: var(--accent); stroke-width: 2.4; }
.diagram svg .node.hit text { font-weight: bold; }

.reasons { margin: -1rem 0 2rem; }
.reasons summary { color: var(--muted); font-size: .85rem; cursor: pointer; }
.reasons ul { margin-top: .75rem; }
.legend { list-style: none; padding: 0; margin: 0 0 .35rem; display: flex;
          flex-wrap: wrap; gap: .3rem 1.6rem; font-size: .82rem; color: var(--muted); }
.legend li { display: flex; align-items: baseline; gap: .5rem; }
.legend b { font-weight: 600; color: var(--fg); font-size: .74rem;
            text-transform: uppercase; letter-spacing: .05em; }
.legend .ln { display: inline-flex; align-items: center; gap: .35rem; }
.legend i { width: 1.5rem; border-top-width: 2.5px; display: inline-block; }
.legend-note { font-size: .78rem; color: var(--muted); margin: 0 0 1.25rem; }
.refs { list-style: none; padding: 0; }
.refs li { padding: .4rem 0; color: var(--muted); font-size: .92rem; }
.refs .t { color: var(--fg); }
.stat { display: flex; gap: 2rem; flex-wrap: wrap; margin: 0 0 2rem; }
.stat b { display: block; font-size: 1.5rem; }
.count { font-weight: 400; font-size: .8rem; color: var(--muted); }
.stat span { color: var(--muted); font-size: .8rem; text-transform: uppercase;
             letter-spacing: .06em; }
footer { margin-top: 4rem; padding-top: 1rem; border-top: 1px solid var(--line);
         color: var(--muted); font-size: .85rem; }
@media (max-width: 640px) {
  nav .repo { display: none; }
  .figure.wide { width: 100%; margin-left: 0; }
}
"""

SCRIPT = r"""
(function () {
var IDX = __INDEX__, UP = "__UP__", WHY = __WHY__;

/* ---------- pan & zoom ---------- */
function setupFigure(fig) {
  var box = fig.querySelector('.diagram'), svg = box && box.querySelector('svg');
  if (!svg) return null;
  var raw = (svg.getAttribute('viewBox') || '').split(/[\s,]+/).map(Number);
  if (raw.length !== 4 || !raw[2]) return null;
  var home = raw.slice(), vb = raw.slice();

  svg.removeAttribute('width');
  svg.removeAttribute('height');
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  box.classList.add('pz');
  fig.classList.add('ready');

  var bw = 0;
  function apply() {
    svg.setAttribute('viewBox', vb.join(' '));
    /* Ranking is there to give a crowded overview somewhere to start. Once
       the drawing is at least at its natural size the reasons on the edges
       are readable and the ranking has done its job, so drop it wholesale.
       Measured against the cached width: reading it here would force a
       layout on every pointermove of a drag. */
    box.classList.toggle('detail', bw > 0 && bw / vb[2] >= 0.9);
  }
  function fit() {
    if (document.fullscreenElement === box) box.style.height = '100vh';
    else {
      var inner = box.clientWidth - 24;
      var ideal = inner * home[3] / home[2] + 24;
      box.style.height = Math.round(Math.max(150, Math.min(ideal, innerHeight * 0.86))) + 'px';
    }
    bw = box.clientWidth - 24;
    apply();
  }
  function zoom(f, cx, cy) {
    var w = vb[2] * f;
    if (w < home[2] / 60 || w > home[2] * 20) return;
    vb[0] = cx - (cx - vb[0]) * f; vb[1] = cy - (cy - vb[1]) * f;
    vb[2] = w; vb[3] = vb[3] * f; apply();
  }
  function at(e) {
    var r = svg.getBoundingClientRect();
    return [vb[0] + (e.clientX - r.left) / r.width * vb[2],
            vb[1] + (e.clientY - r.top) / r.height * vb[3]];
  }
  fit();
  addEventListener('resize', fit);
  document.addEventListener('fullscreenchange', fit);

  box.addEventListener('wheel', function (e) {
    e.preventDefault();
    var p = at(e);
    zoom(e.deltaY > 0 ? 1.15 : 1 / 1.15, p[0], p[1]);
  }, { passive: false });

  var drag = null, moved = 0;
  svg.addEventListener('pointerdown', function (e) {
    if (e.button !== 0) return;
    drag = { x: e.clientX, y: e.clientY }; moved = 0;
    box.classList.add('grabbing');
  });
  /* Tracked on window, not via setPointerCapture: capturing the pointer
     retargets the following click and would break the node links. */
  addEventListener('pointermove', function (e) {
    if (!drag) return;
    var r = svg.getBoundingClientRect();
    moved += Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y);
    vb[0] -= (e.clientX - drag.x) * vb[2] / r.width;
    vb[1] -= (e.clientY - drag.y) * vb[3] / r.height;
    drag.x = e.clientX; drag.y = e.clientY; apply();
  });
  function release() { drag = null; box.classList.remove('grabbing'); }
  addEventListener('pointerup', release);
  addEventListener('pointercancel', release);
  /* A drag that happens to end on a node must not also follow its link. */
  svg.addEventListener('click', function (e) {
    if (moved > 6) { e.stopPropagation(); e.preventDefault(); }
    moved = 0;
  }, true);

  fig.querySelectorAll('[data-act]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var a = btn.getAttribute('data-act');
      var cx = vb[0] + vb[2] / 2, cy = vb[1] + vb[3] / 2;
      if (a === 'in') zoom(1 / 1.4, cx, cy);
      else if (a === 'out') zoom(1.4, cx, cy);
      else if (a === 'reset') { vb = home.slice(); apply(); fit(); }
      else if (document.fullscreenElement) document.exitFullscreen();
      else if (box.requestFullscreen) box.requestFullscreen();
    });
  });

  return {
    svg: svg,
    /* Rendered pixels per user unit, so anything drawn into the SVG at
       runtime can be sized in screen terms. */
    scale: function () { return bw && vb[2] ? bw / vb[2] : 1; },
    frame: function (els) {
      if (!els.length) return;
      var r = svg.getBoundingClientRect();
      var x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
      els.forEach(function (el) {
        var b = el.getBoundingClientRect();
        x0 = Math.min(x0, b.left); y0 = Math.min(y0, b.top);
        x1 = Math.max(x1, b.right); y1 = Math.max(y1, b.bottom);
      });
      var tx = function (c) { return vb[0] + (c - r.left) / r.width * vb[2]; };
      var ty = function (c) { return vb[1] + (c - r.top) / r.height * vb[3]; };
      var a = tx(x0), b2 = ty(y0), c = tx(x1), d = ty(y1);
      var pad = Math.max(c - a, d - b2) * 0.4 + 30;
      vb = [a - pad, b2 - pad, (c - a) + 2 * pad, (d - b2) + 2 * pad];
      apply();
    }
  };
}

/* ---------- prominence, and the reasons ----------
   A crowded cluster is laid out without its edge labels — they are about half
   the area, and unreadable at that size anyway — so hovering a node is what
   puts them back: it brings the node, its edges and their far ends to full
   weight and writes the reason along each of those edges. Endpoints come from
   the <title> graphviz writes into every group ("a" and "a->b"), which is the
   only place the SVG records what an edge connects. */
function wrap(text, width) {
  var words = text.split(/\s+/), lines = [], line = '';
  words.forEach(function (w) {
    if (!line) line = w;
    else if ((line + ' ' + w).length <= width) line += ' ' + w;
    else { lines.push(line); line = w; }
  });
  if (line) lines.push(line);
  return lines;
}

function setupRank(box, api) {
  if (!box || !box.classList.contains('ranked')) return;
  var at = {}, adj = {};
  box.querySelectorAll('g.node').forEach(function (g) {
    var t = g.querySelector('title');
    if (t) { at[t.textContent] = g; adj[t.textContent] = []; }
  });
  box.querySelectorAll('g.edge').forEach(function (g) {
    var t = g.querySelector('title');
    var ends = t ? t.textContent.split('->') : [];
    if (ends.length !== 2) return;
    /* Which end you are hovering decides which way its label is pushed. */
    if (adj[ends[0]]) adj[ends[0]].push([g, ends[1], 1]);
    if (adj[ends[1]]) adj[ends[1]].push([g, ends[0], 0]);
  });

  var SVGNS = 'http://www.w3.org/2000/svg';
  var layer = box.querySelector('svg .graph'), lit = [], drawn = [];

  function el(name, attrs) {
    var node = document.createElementNS(SVGNS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  /* Where a label can go. Graphviz reserved no room for these — that is the
     whole point of dropping them from the layout — so each one walks its own
     edge looking for a spot that clears the node boxes and the labels already
     placed, nudging up or down at each stop before moving on. Sliding along
     the edge keeps a label attached to the edge it belongs to, which
     offsetting in some arbitrary direction would not.

     It starts two thirds of the way towards the far end rather than at the
     midpoint. Every edge being labelled meets at the node under the pointer,
     so the middle is the one place they all compete for, while the far ends
     are as spread out as the layout could make them. */
  var STOPS = [0.66, 0.74, 0.58, 0.82, 0.5, 0.9, 0.42, 0.34, 0.26];
  /* Every placement, cheapest first: a point along the edge, then a step off
     it in either axis, measured in plate sizes. Sliding along the edge is
     nearly free, since the label is still lying on the line it describes;
     stepping off costs, because that is what has to be paid back with a
     leader line. */
  var SPOTS = [];
  STOPS.forEach(function (stop, i) {
    for (var dy = -6; dy <= 6; dy += 0.6) {
      [0, -1, 1].forEach(function (dx) {
        SPOTS.push({ stop: stop, dy: dy, dx: dx,
                     cost: i + Math.abs(dy) * 2.5 + Math.abs(dx) * 2 });
      });
    }
  });
  SPOTS.sort(function (a, b) { return a.cost - b.cost; });
  var boxes = null, bounds = null, taken = [];

  function obstacles() {
    if (!boxes) {
      boxes = [];
      box.querySelectorAll('g.node').forEach(function (g) {
        boxes.push(g.getBBox());
      });
      /* The viewBox is the drawing's own extent, so a label placed past it
         is simply cut off. Taken while the group holds nothing but the
         graph — see light(), which measures before it draws. */
      bounds = layer.getBBox();
    }
    return boxes.concat(taken);
  }
  function inside(r) {
    return r.x >= bounds.x && r.y >= bounds.y &&
           r.x + r.width <= bounds.x + bounds.width &&
           r.y + r.height <= bounds.y + bounds.height;
  }
  function clashes(a, b) {
    return a.x < b.x + b.width && b.x < a.x + a.width &&
           a.y < b.y + b.height && b.y < a.y + a.height;
  }

  /* Sized against the current zoom, so a reason reads the same whether the
     cluster is fitted to the box or filling the screen. */
  function label(edge, why, forward) {
    var path = edge.querySelector('path');
    if (!path || !path.getPointAtLength) return;
    var size = 12 / (api ? api.scale() : 1), lines = wrap(why, 22);
    /* Carrying the edge's own relation class means the leader line below is
       painted by the same stylesheet rule as the edge it belongs to, dash
       pattern and all. */
    var rel = (edge.getAttribute('class') || '').split(/\s+/).filter(
      function (c) { return c.indexOf('e-') === 0; })[0];
    var g = el('g', { class: 'why' + (rel ? ' e ' + rel : '') });
    var text = el('text', {
      'text-anchor': 'middle', 'font-size': size,
      y: size * 0.35 - (lines.length - 1) * size * 0.575,
    });
    lines.forEach(function (line, i) {
      var span = el('tspan', { x: 0, dy: i ? size * 1.15 : 0 });
      span.textContent = line;
      text.appendChild(span);
    });
    g.appendChild(text);
    layer.appendChild(g);

    var b = text.getBBox(), pad = size * 0.35, len = path.getTotalLength();
    function plate(p) {
      return { x: p.x + b.x - pad, y: p.y + b.y - pad,
               width: b.width + 2 * pad, height: b.height + 2 * pad };
    }
    var start = path.getPointAtLength(len * (forward ? STOPS[0] : 1 - STOPS[0]));
    var spot = start, anchor = start, rect = plate(start);
    for (var i = 0; i < SPOTS.length; i++) {
      var s = SPOTS[i];
      var at = path.getPointAtLength(len * (forward ? s.stop : 1 - s.stop));
      var p = { x: at.x + s.dx * (b.width / 2 + pad * 3),
                y: at.y + s.dy * (b.height + 2 * pad) };
      var r = plate(p);
      if (obstacles().every(function (o) { return !clashes(r, o); }) &&
          inside(r)) {
        spot = p; anchor = at; rect = r; break;
      }
    }
    /* Nowhere clear and inside the drawing: take the cheapest spot anyway,
       but slide it back within the edges. A label that overlaps something is
       readable; one that is half outside the viewBox is not there at all. */
    var over;
    if ((over = bounds.x - rect.x) > 0) { spot.x += over; rect.x += over; }
    if ((over = rect.x + rect.width - bounds.x - bounds.width) > 0) {
      spot.x -= over; rect.x -= over;
    }
    if ((over = bounds.y - rect.y) > 0) { spot.y += over; rect.y += over; }
    if ((over = rect.y + rect.height - bounds.y - bounds.height) > 0) {
      spot.y -= over; rect.y -= over;
    }

    g.setAttribute('transform', 'translate(' + spot.x + ',' + spot.y + ')');
    g.insertBefore(el('rect', {
      x: b.x - pad, y: b.y - pad, rx: pad,
      width: b.width + 2 * pad, height: b.height + 2 * pad,
    }), text);
    /* A label pushed clear of the traffic has to say which edge it came
       from. The leader runs to the plate's centre and the plate is painted
       over it, so what shows is the part outside. */
    if (Math.hypot(spot.x - anchor.x, spot.y - anchor.y) > b.height / 2) {
      g.insertBefore(el('path', {
        d: 'M' + (anchor.x - spot.x) + ',' + (anchor.y - spot.y) + 'L0,0',
        fill: 'none',
      }), g.firstChild);
    }
    taken.push(rect);
    drawn.push(g);
  }

  function clear() {
    lit.forEach(function (e) { e.classList.remove('lit'); });
    drawn.forEach(function (g) { g.remove(); });
    lit = []; drawn = []; taken = [];
  }
  function light(id) {
    clear();
    /* Measure the drawing before adding anything to it: the first label is
       appended to the same group whose extent is being taken. */
    obstacles();
    function add(e) { if (e) { e.classList.add('lit'); lit.push(e); } }
    add(at[id]);
    (adj[id] || []).forEach(function (pair) {
      add(pair[0]); add(at[pair[1]]);
      var why = WHY[pair[0].querySelector('title').textContent];
      if (why) label(pair[0], why, pair[2]);
    });
  }
  Object.keys(at).forEach(function (id) {
    var g = at[id], a = g.querySelector('a');
    g.addEventListener('mouseenter', function () { light(id); });
    g.addEventListener('mouseleave', clear);
    if (a) {
      a.addEventListener('focus', function () { light(id); });
      a.addEventListener('blur', clear);
    }
  });
}

/* ---------- search ---------- */
var figures = [], q, list, sel = -1, shown = [];

function highlight(term) {
  figures.forEach(function (f) {
    var nodes = f.api.svg.querySelectorAll('g.node'), found = [];
    nodes.forEach(function (n) {
      var hit = term && (n.textContent || '').toLowerCase().indexOf(term) >= 0;
      n.classList.toggle('hit', !!hit);
      n.classList.toggle('dim', !!term && !hit);
      if (hit) found.push(n);
    });
    f.api.svg.querySelectorAll('g.edge').forEach(function (e) {
      e.classList.toggle('dim', !!term);
    });
    var out = f.fig.querySelector('[data-found]');
    if (out) {
      out.textContent = term ? found.length + ' of ' + nodes.length + ' shown' : '';
      out.classList.toggle('on', !!term && found.length > 0);
    }
    f.found = found;
  });
}

/* How well a node answers the term, lowest first: 0 it is called that, 1 that
   is one of the words it is called, 2 the letters appear inside one of them,
   3 only its cluster matched. Names are ranked one at a time and the best
   taken, so a node is never beaten by a longer name that happens to contain
   the same words.

   Without this, searching "reinforce" is answered by all thirty-odd nodes
   filed under the reinforcement cluster and never by REINFORCE itself, which
   is alphabetically too late to survive the cut. */
function rank(n, term) {
  var best = 3;
  n.names.forEach(function (name) {
    var at = name.indexOf(term);
    if (at < 0) return;
    var r = at === 0 ? 0 : (' -'.indexOf(name.charAt(at - 1)) < 0 ? 2 : 1);
    if (r < best) best = r;
  });
  return best;
}

function render(term) {
  shown = term
    ? IDX.filter(function (n) { return n.hay.indexOf(term) >= 0; })
         .sort(function (a, b) { return rank(a, term) - rank(b, term); })
         .slice(0, 12)
    : [];
  sel = -1;
  if (!term) { list.className = ''; list.innerHTML = ''; return; }
  list.className = 'open';
  list.innerHTML = shown.length
    ? shown.map(function (n, i) {
        return '<li data-i="' + i + '"><span>' + n[1] +
               '</span><span class="c">' + n[2] + '</span></li>';
      }).join('')
    : '<li class="none">no matches</li>';
}

function go(i) {
  if (shown[i]) location.href = UP + 'n/' + shown[i][0] + '.html';
}

function init() {
  IDX.forEach(function (n) {
    /* Every name this node goes by, kept apart for rank(). The id appears
       twice, as written and with its hyphens opened out, so that
       "deep-q-network" and "deep q network" both find it. */
    n.names = [n[0], n[0].replace(/-/g, ' '), n[1], n[3] || ''].map(
      function (s) { return s.toLowerCase(); });
    n.hay = n.names.join(' ') + ' ' + n[2];
  });

  document.querySelectorAll('.figure').forEach(function (fig) {
    var api = setupFigure(fig);
    if (api) figures.push({ fig: fig, api: api, found: [] });
    setupRank(fig.querySelector('.diagram'), api);
  });

  q = document.getElementById('q');
  list = document.getElementById('hits');
  if (!q) return;

  q.addEventListener('input', function () {
    var term = q.value.trim().toLowerCase();
    highlight(term);
    render(term);
  });
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { q.value = ''; highlight(''); render(''); q.blur(); }
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!shown.length) return;
      sel = (sel + (e.key === 'ArrowDown' ? 1 : shown.length - 1)) % shown.length;
      [].forEach.call(list.children, function (li, i) {
        li.classList.toggle('sel', i === sel);
      });
    } else if (e.key === 'Enter') {
      if (sel >= 0) { go(sel); return; }
      /* No row picked: frame what matched in the diagram instead. */
      var f = figures.filter(function (x) { return x.found.length; })[0];
      if (f) { f.api.frame(f.found); list.className = ''; }
      else if (shown.length) go(0);
    }
  });
  list.addEventListener('click', function (e) {
    var li = e.target.closest('li[data-i]');
    if (li) go(+li.getAttribute('data-i'));
  });
  document.addEventListener('click', function (e) {
    if (!e.target.closest('.find')) list.className = '';
  });
  addEventListener('keydown', function (e) {
    if (e.key === '/' && document.activeElement !== q) { e.preventDefault(); q.focus(); }
  });
}

if (document.readyState !== 'loading') init();
else document.addEventListener('DOMContentLoaded', init);
})();
"""


def esc(text):
    return html.escape(str(text), quote=True)


def relation_css():
    """Colour rules for edges and legend swatches, from one mapping."""
    out = [":root {"]
    out += [f"  --fam-{k}: {light};" for k, (_, light, _) in FAMILIES.items()]
    out.append("}")
    out.append("@media (prefers-color-scheme: dark) { :root {")
    out += [f"  --fam-{k}: {dark};" for k, (_, _, dark) in FAMILIES.items()]
    out.append("} }")
    for rel, (family, dashed) in RELATION_STYLE.items():
        var = f"var(--fam-{family})"
        out.append(f".diagram svg .e-{rel} > path {{ stroke: {var};"
                   + (" stroke-dasharray: 7 5;" if dashed else "") + " }")
        out.append(
            f".diagram svg .e-{rel} > polygon {{ fill: {var}; stroke: {var}; }}"
        )
        border = "dashed" if dashed else "solid"
        out.append(f".legend .r-{rel} {{ border-top-color: {var}; "
                   f"border-top-style: {border}; }}")
        # Tie the chips on a node page back to the colours in the diagram.
        out.append(f".rel.k-{rel} {{ border-left: 3px solid {var}; }}")
    return "\n".join(out)


def legend():
    items = []
    for family, (reads, _, _) in FAMILIES.items():
        members = [r for r, (f, _) in RELATION_STYLE.items() if f == family]
        names = " · ".join(
            f'<span class="ln"><i class="r-{r}"></i>{esc(r)}</span>' for r in members
        )
        items.append(f"<li><b>{esc(reads)}</b>{names}</li>")
    return (
        '<ul class="legend">' + "".join(items) + "</ul>"
        '<p class="legend-note">Colour is the family; a dashed line is the second '
        "member of it.</p>"
    )


def render_svg(dot_text):
    """Lay out with graphviz and return inlineable SVG."""
    try:
        done = subprocess.run(
            ["dot", "-Tsvg"], input=dot_text, capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        raise Problem("graphviz not found; install it (apt-get install graphviz)")
    except subprocess.CalledProcessError as exc:
        raise Problem(f"graphviz failed: {exc.stderr.strip()}")
    svg = done.stdout
    return svg[svg.index("<svg"):]


def fig(svg, wide=False, ranked=False):
    cls = "figure wide" if wide else "figure"
    box = "diagram ranked" if ranked else "diagram"
    hint = "Drag to pan · scroll to zoom · click a node to open it"
    if ranked:
        # Both halves of the arrangement need saying, or a diagram with no
        # reasons on it and half of it faint reads as broken rather than as
        # ranked — worse than not ranking it at all.
        hint += " · hover one for the reasons on its edges, and to bring it forward"
    # Controls sit above the box, not floating inside it, where they used to
    # cover whichever node the layout happened to put in the corner.
    return (
        f'<div class="{cls}">'
        '<div class="fig-head">'
        f'<span class="hint">{hint}</span>'
        '<span class="found" data-found></span>'
        '<div class="tools">'
        '<button data-act="out" title="Zoom out">&minus;</button>'
        '<button data-act="in" title="Zoom in">+</button>'
        '<button data-act="reset" title="Reset view">reset</button>'
        '<button data-act="full" title="Fullscreen">&#9974;</button>'
        "</div></div>"
        f'<div class="{box}">{svg}</div></div>'
    )


def page(title, body, depth, index, why="{}"):
    up = "../" * depth
    script = (SCRIPT.replace("__INDEX__", index).replace("__UP__", up)
              .replace("__WHY__", why))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<link rel="stylesheet" href="{up}style.css">
</head>
<body>
<div class="wrap">
<nav>
  <a class="home" href="{up}index.html">aitia</a>
  <div class="find">
    <input id="q" type="search" placeholder="Search nodes — press /"
           autocomplete="off" spellcheck="false" aria-label="Search nodes">
    <ul id="hits"></ul>
  </div>
  <a class="repo" href="{REPO}">source</a>
</nav>
{body}
<footer>
Laid out by graphviz from <code>nodes/*.yaml</code>. The YAML files are the
canonical form — this site is a view of them.
</footer>
</div>
<script>{script}</script>
</body>
</html>
"""


def node_link(nid, nodes, depth):
    up = "../" * depth
    return f'<a href="{up}n/{nid}.html">{esc(nodes[nid]["title"])}</a>'


def render_refs(node):
    refs = node.get("refs") or []
    wiki = node.get("wikipedia")
    if not refs and not wiki:
        return ""
    items = []
    for ref in refs:
        bits = [f'<span class="t">{esc(ref["title"])}</span>']
        if ref.get("authors"):
            bits.append(esc(ref["authors"]))
        if ref.get("year"):
            bits.append(esc(ref["year"]))
        line = " — ".join(bits)
        if ref.get("url"):
            line += f' · <a href="{esc(ref["url"])}">link</a>'
        items.append(f"<li>{line}</li>")
    if wiki:
        article = urllib.parse.unquote(wiki.rsplit("/", 1)[-1]).replace("_", " ")
        items.append(
            f'<li>Background — <a href="{esc(wiki)}">{esc(article)}</a> on Wikipedia</li>'
        )
    return f'<h3>References</h3><ul class="refs">{"".join(items)}</ul>'


def edge_items(rows):
    return "".join(
        f'<li><span class="rel k-{esc(rel)}">{esc(rel)}</span>{text}'
        + (f'<span class="why">{esc(why)}</span>' if why else "")
        + "</li>"
        for rel, text, why in rows
    )


def render_node(nid, nodes, clusters, domains, backlinks, index):
    node = nodes[nid]
    titles = {c["id"]: c["title"] for c in clusters}
    domains_by_cluster = {c["id"]: c["domain"] for c in clusters}

    meta = [f'<a href="../c/{node["cluster"]}.html">'
            f'{esc(titles.get(node["cluster"], node["cluster"]))}</a>']
    did = domains_by_cluster.get(node["cluster"])
    dom = next((d for d in domains if d["id"] == did), None)
    if dom:
        meta.insert(0, f'<a href="../index.html#{esc(did)}">{esc(dom["title"])}</a>')
    if node.get("year"):
        meta.append(esc(node["year"]))
    if node.get("aka"):
        meta.append("also: " + esc(", ".join(node["aka"])))

    out = [
        f"<h1>{esc(node['title'])}</h1>",
        f'<p class="meta">{" · ".join(meta)} · '
        f'<a href="{REPO}/blob/main/nodes/{nid}.yaml"><code>{nid}.yaml</code></a></p>',
        f'<p class="summary">{esc(clean(node["summary"]))}</p>',
    ]

    neighbours = {nid}
    neighbours.update(e["to"] for e in node.get("edges") or [] if e.get("to") in nodes)
    neighbours.update(src for src, _ in backlinks[nid])
    if len(neighbours) > 1:
        out.append(legend())
        out.append(fig(render_svg(dot_source(
            nodes, neighbours, url=lambda n: f"../n/{n}.html", focus=nid,
        ))))

    outgoing = [
        (e["rel"], f'{RELATIONS[e["rel"]][0]} {node_link(e["to"], nodes, 1)}', e.get("why"))
        for e in node.get("edges") or []
        if e["to"] in nodes
    ]
    if outgoing:
        out.append(f'<h3>This node</h3><ul class="edges">{edge_items(outgoing)}</ul>')

    inbound = [
        (e["rel"], f'{node_link(src, nodes, 1)} {RELATIONS[e["rel"]][0]} this', e.get("why"))
        for src, e in backlinks[nid]
    ]
    if inbound:
        out.append(f'<h3>Referenced by</h3><ul class="edges">{edge_items(inbound)}</ul>')

    out.append(render_refs(node))
    return page(node["title"], "\n".join(out), 1, index)


def cluster_edges(nodes, members):
    """Every edge the cluster's diagram draws, in reading order."""
    return [
        (nid, edge)
        for nid in sorted(members, key=lambda n: nodes[n]["title"].lower())
        for edge in nodes[nid].get("edges") or []
        if edge.get("to") in nodes
    ]


def render_cluster(cluster, nodes, domains, index):
    cid, title, blurb = cluster["id"], cluster["title"], cluster["blurb"]
    dom = next(d for d in domains if d["id"] == cluster["domain"])
    members = members_of(nodes, cid)
    # One decision, two consequences: a diagram crowded enough to want a
    # reading order is also too crowded to carry its reasons inline.
    ranked = is_crowded(nodes, members)
    svg = render_svg(dot_source(
        nodes, members, url=lambda n: f"../n/{n}.html",
        ranked=ranked, labels=not ranked))
    cards = "".join(
        f'<div class="card"><h4>{node_link(nid, nodes, 1)}</h4>'
        f'<p>{esc(clean(nodes[nid]["summary"], 150))}'
        f'{esc(" · " + str(nodes[nid]["year"]) if nodes[nid].get("year") else "")}</p></div>'
        for nid in sorted(members, key=lambda n: (nodes[n].get("year") or 9999, n))
    )
    drawn = cluster_edges(nodes, members)
    reasons = ""
    if ranked:
        # The diagram gives its reasons up on hover, which is no use to a
        # reader without a pointer or without scripting, so the same text is
        # on the page as text. Folded away: the node cards are what most
        # people came for.
        rows = [
            (edge["rel"],
             f'{node_link(src, nodes, 1)} {RELATIONS[edge["rel"]][0]} '
             f'{node_link(edge["to"], nodes, 1)}',
             edge.get("why"))
            for src, edge in drawn
        ]
        reasons = (
            f'<details class="reasons"><summary>The {len(rows)} reasons on '
            f"these edges, as text</summary>"
            f'<ul class="edges">{edge_items(rows)}</ul></details>'
        )

    body = (
        f'<p class="meta"><a href="../index.html#{esc(dom["id"])}">'
        f'{esc(dom["title"])}</a></p>'
        f"<h1>{esc(title)}</h1>"
        f'<p class="lede">{esc(blurb)}</p>'
        f"{legend()}"
        f"{fig(svg, wide=True, ranked=ranked)}"
        f"{reasons}"
        f'<h2>{len(members)} nodes</h2><div class="cards">{cards}</div>'
    )
    why = json.dumps(
        {f'{src}->{edge["to"]}': clean(edge["why"]) for src, edge in drawn
         if edge.get("why")},
        separators=(",", ":"),
    ) if ranked else "{}"
    return page(title, body, 1, index, why)


def render_index(nodes, clusters, domains, index):
    edge_count = sum(len(n.get("edges") or []) for n in nodes.values())
    ref_count = sum(len(n.get("refs") or []) for n in nodes.values())

    sections = []
    for dom in domains:
        mine = [c for c in clusters
                if c["domain"] == dom["id"] and members_of(nodes, c["id"])]
        if not mine:
            continue
        count = sum(len(members_of(nodes, c["id"])) for c in mine)
        cards = "".join(
            f'<div class="card"><h4><a href="c/{c["id"]}.html">{esc(c["title"])}</a></h4>'
            f'<p>{esc(c["blurb"])} — {len(members_of(nodes, c["id"]))} nodes</p></div>'
            for c in mine
        )
        sections.append(
            f'<h2 id="{esc(dom["id"])}">{esc(dom["title"])} '
            f'<span class="count">{count} nodes</span></h2>'
            f'<p class="lede">{esc(dom["blurb"])}</p>'
            f'<div class="cards">{cards}</div>'
        )
    cards = "".join(sections)
    legend_rows = "".join(
        f'<li><span class="rel k-{esc(rel)}">{esc(rel)}</span>{esc(reads)} the target'
        + ("" if required else " <em>(no reason required)</em>")
        + "</li>"
        for rel, (reads, required) in RELATIONS.items()
    )

    body = f"""
<h1>aitia</h1>
<p class="lede"><em>aitia</em> (αἰτία) is Greek for <em>cause</em> — the answer to
"why". A knowledge graph in which the edges carry the reasons: most maps of a
field give you the nodes, but what is almost never written down is why one idea
leads to the next. Press <kbd>/</kbd> to search.</p>

<div class="stat">
  <div><b>{len(nodes)}</b><span>nodes</span></div>
  <div><b>{edge_count}</b><span>typed edges</span></div>
  <div><b>{ref_count}</b><span>references</span></div>
  <div><b>{len(domains)}</b><span>domains</span></div>
</div>

{cards}

<h2>Relations</h2>
<p class="lede">A closed vocabulary. Every edge but <code>part-of</code> must say
why — an edge without a reason is rejected by CI.</p>
<ul class="edges">{legend_rows}</ul>
"""
    return page("aitia — a knowledge graph of reasons", body, 0, index)


def main():
    argv = sys.argv[1:]
    out_dir = ROOT / "site"
    if "--out" in argv:
        out_dir = Path(argv[argv.index("--out") + 1]).resolve()

    try:
        nodes, clusters, domains = load_all()
    except Problem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Compact search index, inlined on every page. The haystack is built in the
    # browser rather than shipped: it is the same text again, times 174 pages.
    index = json.dumps([
        [nid, node["title"], node["cluster"]]
        + ([" ".join(node["aka"])] if node.get("aka") else [])
        for nid, node in sorted(nodes.items())
    ], separators=(",", ":"))

    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "n").mkdir(parents=True)
    (out_dir / "c").mkdir(parents=True)

    backlinks = incoming(nodes)

    try:
        (out_dir / "style.css").write_text(STYLE.strip() + "\n" + relation_css() + "\n")
        (out_dir / ".nojekyll").write_text("")
        # Pages reads the custom domain from this file in the artifact. The
        # output directory is rebuilt from scratch every run, so it has to be
        # emitted here or the domain silently reverts on the next deploy.
        (out_dir / "CNAME").write_text(DOMAIN_NAME + "\n")
        (out_dir / "index.html").write_text(
            render_index(nodes, clusters, domains, index))

        for cluster in clusters:
            if members_of(nodes, cluster["id"]):
                (out_dir / "c" / f"{cluster['id']}.html").write_text(
                    render_cluster(cluster, nodes, domains, index)
                )

        for nid in nodes:
            (out_dir / "n" / f"{nid}.html").write_text(
                render_node(nid, nodes, clusters, domains, backlinks, index)
            )
    except Problem as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # The whole graph as one file, for anyone who wants to query it elsewhere.
    (out_dir / "graph.json").write_text(json.dumps({
        "nodes": {
            nid: {k: v for k, v in node.items() if not k.startswith("_")}
            for nid, node in sorted(nodes.items())
        },
        "domains": domains,
        "clusters": clusters,
        "relations": {r: reads for r, (reads, _) in RELATIONS.items()},
    }, indent=2))

    pages = 1 + len(nodes) + sum(1 for c in clusters if members_of(nodes, c["id"]))
    print(f"ok: {pages} pages -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
