"""Loading, validation and diagram rendering for the node graph.

Shared by check.py (validation), kg.py (queries) and site.py (the site) so
the schema lives in exactly one place.
"""

import re
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
NODES_DIR = ROOT / "nodes"
CLUSTERS_FILE = ROOT / "clusters.yaml"
DOMAINS_FILE = ROOT / "domains.yaml"

# rel -> (reads-as, why-required)
RELATIONS = {
    "part-of": ("is a subtopic of", False),
    "specializes": ("is a specific case of", True),
    "approximates": ("is a cheaper stand-in for", True),
    "corrects": ("fixes a defect in", True),
    "extends": ("adds capability to", True),
    "requires": ("does not work without", True),
    "alternative-to": ("is a competing approach to", True),
    "validates": ("is a test for", True),
}

# Prominence, used only by diagrams big enough to need a reading order.
#
# Past a couple of dozen nodes every box carries the same weight and there is
# nowhere for the eye to start. Ranking by how connected a node is gives that
# start back: the junctions you navigate by come forward, the twigs recede.
# Nothing is removed — the site lifts the ranking on hover and on zoom — so
# this is a reading order, not a filter.
#
# In-degree alone would be the wrong measure. Edges are declared on the
# subject node, so the newest node in any area has an in-degree of zero by
# construction, and ranking on it would fade exactly the frontier of the
# graph. Out-degree counts too, at half weight: being built on is a stronger
# claim than building on something, but it is not the only one.
RANK_CUTS = (2, 6)      # weighted degree: <= 2 recedes, > 6 is a junction
RANK_MIN_DRAWN = 12     # below this a diagram is not crowded; rank nothing

REQUIRED_FIELDS = ("title", "cluster", "summary")
KNOWN_FIELDS = REQUIRED_FIELDS + ("year", "aka", "tags", "wikipedia", "refs", "edges")


class Problem(Exception):
    pass


def load_domains():
    return [
        {"id": d["id"], "title": d["title"], "blurb": (d.get("blurb") or "").strip()}
        for d in yaml.safe_load(DOMAINS_FILE.read_text())
    ]


def load_clusters():
    return [
        {"id": c["id"], "domain": c["domain"], "title": c["title"],
         "blurb": (c.get("blurb") or "").strip()}
        for c in yaml.safe_load(CLUSTERS_FILE.read_text())
    ]


def load_nodes():
    nodes = {}
    for path in sorted(NODES_DIR.glob("*.yaml")):
        node = yaml.safe_load(path.read_text())
        if not isinstance(node, dict):
            raise Problem(f"{path.name}: file is not a YAML mapping")
        node["id"] = path.stem
        node["_path"] = path.name
        nodes[path.stem] = node
    if not nodes:
        raise Problem("no nodes found in nodes/")
    return nodes


def validate(nodes, clusters, domains):
    errors = []
    cluster_ids = {c["id"] for c in clusters}
    domain_ids = {d["id"] for d in domains}

    for cluster in clusters:
        if cluster["domain"] not in domain_ids:
            errors.append(
                f"clusters.yaml: cluster '{cluster['id']}' names unknown "
                f"domain '{cluster['domain']}'"
            )

    for nid, node in sorted(nodes.items()):
        where = node["_path"]

        for field in REQUIRED_FIELDS:
            if not node.get(field):
                errors.append(f"{where}: missing required field '{field}'")

        for field in node:
            if field not in KNOWN_FIELDS and not field.startswith("_") and field != "id":
                errors.append(f"{where}: unknown field '{field}'")

        cluster = node.get("cluster")
        if cluster and cluster not in cluster_ids:
            errors.append(f"{where}: cluster '{cluster}' is not in clusters.yaml")

        for ref in node.get("refs") or []:
            if not ref.get("title"):
                errors.append(f"{where}: a ref has no title")

        # Every node has to be anchored to something outside this repo, so a
        # reader can check the claim rather than take the summary on trust.
        if not anchors(node):
            errors.append(
                f"{where}: no anchor — needs a 'wikipedia' link or a ref with a url"
            )

        seen = set()
        for edge in node.get("edges") or []:
            rel, to = edge.get("rel"), edge.get("to")
            if rel not in RELATIONS:
                errors.append(
                    f"{where}: unknown relation '{rel}' "
                    f"(allowed: {', '.join(sorted(RELATIONS))})"
                )
                continue
            if not to:
                errors.append(f"{where}: edge '{rel}' has no target")
                continue
            if to == nid:
                errors.append(f"{where}: edge '{rel}' points at itself")
            elif to not in nodes:
                errors.append(f"{where}: edge '{rel}' points at unknown node '{to}'")
            if (rel, to) in seen:
                errors.append(f"{where}: duplicate edge '{rel} -> {to}'")
            seen.add((rel, to))
            if RELATIONS[rel][1] and not edge.get("why"):
                errors.append(f"{where}: edge '{rel} -> {to}' needs a 'why'")

    return errors


def load_all():
    """Load and validate, raising Problem with every error found."""
    domains = load_domains()
    clusters = load_clusters()
    nodes = load_nodes()
    errors = validate(nodes, clusters, domains)
    if errors:
        raise Problem(
            f"{len(errors)} problem(s):\n  " + "\n  ".join(errors)
        )
    return nodes, clusters, domains


def incoming(nodes):
    """nid -> [(source_id, edge)], in stable order."""
    result = {nid: [] for nid in nodes}
    for src, node in sorted(nodes.items()):
        for edge in node.get("edges") or []:
            if edge.get("to") in result:
                result[edge["to"]].append((src, edge))
    return result


def is_crowded(nodes, members):
    """Whether a diagram of `members` is dense enough to want a reading order.

    Counts what will actually be drawn: the members plus the out-of-cluster
    nodes they point at.
    """
    drawn = set(members)
    for nid in members:
        for edge in nodes[nid].get("edges") or []:
            if edge.get("to") in nodes:
                drawn.add(edge["to"])
    return len(drawn) >= RANK_MIN_DRAWN


def prominence(nodes):
    """nid -> 0 (peripheral), 1 (ordinary), 2 (junction).

    Scored over the whole graph rather than per diagram, so a node carries the
    same weight on every page it appears on.
    """
    back = incoming(nodes)
    tiers = {}
    for nid, node in nodes.items():
        out = sum(1 for e in node.get("edges") or [] if e.get("to") in nodes)
        score = 2 * len(back[nid]) + out
        low, high = RANK_CUTS
        tiers[nid] = 0 if score <= low else 2 if score > high else 1
    return tiers


def members_of(nodes, cluster_id):
    return sorted(nid for nid, n in nodes.items() if n.get("cluster") == cluster_id)


def clusters_of(clusters, domain_id):
    return [c for c in clusters if c["domain"] == domain_id]


def domain_of(clusters, cluster_id):
    for cluster in clusters:
        if cluster["id"] == cluster_id:
            return cluster["domain"]
    return None


def clean(text, limit=None):
    """Flatten to a single line, optionally truncated."""
    text = re.sub(r"\s+", " ", str(text)).strip().replace('"', "").replace("|", "/")
    if limit and len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def dot_label(text, width):
    """Wrap for a DOT label. \\n is a centred line break in DOT."""
    body = " ".join(str(text).split()).replace("\\", "").replace('"', "'")
    return "\\n".join(textwrap.wrap(body, width)) or body


def dot_source(nodes, members, url=None, focus=None, rankdir="LR", ranked=False,
               labels=True):
    """Graphviz DOT for `members` plus any nodes they link to.

    No colours are emitted. Every node and edge carries a class instead, so the
    page's own stylesheet paints them and one SVG serves both light and dark.

    `url` maps a node id to a link target; graphviz turns that into a real
    anchor, so clicking a node works with scripting disabled.
    `focus` keeps only edges touching that node, so a neighbourhood view does
    not also draw every unrelated edge its neighbours happen to have.
    `ranked` adds a prominence class to each node and edge. Whether a diagram
    wants one is the caller's call — see is_crowded. A focused neighbourhood
    never asks for it: everything drawn there is a neighbour of the node being
    read, so nothing in it is peripheral.
    `labels` writes the reason onto each edge. Dropping it is what makes a
    crowded diagram fit: the reasons are around half the area graphviz has to
    lay out, and at that size they are a texture rather than something anyone
    reads. The site puts them back on hover, one node's worth at a time.
    """
    members = set(members)
    edges, external = [], set()

    for nid in sorted(members):
        for edge in nodes[nid].get("edges") or []:
            to = edge.get("to")
            if to not in nodes:
                continue
            if focus and focus not in (nid, to):
                continue
            if to not in members:
                external.add(to)
            edges.append((nid, edge, to))

    # An edge is only as prominent as its fainter end, so a peripheral node
    # takes its edges down with it.
    tiers = prominence(nodes) if ranked else None

    out = [
        "digraph G {",
        f"  rankdir={rankdir};",
        '  bgcolor="transparent";',
        "  nodesep=0.30; ranksep=0.90; splines=spline; pad=0.15;",
        '  node [shape=box, style="rounded", fontname="Helvetica", fontsize=11,'
        ' margin="0.17,0.10", height=0.36, penwidth=1.0];',
        '  edge [fontname="Helvetica", fontsize=9, arrowsize=0.65, penwidth=1.2];',
    ]

    for nid in sorted(members) + sorted(external):
        classes = ["n"]
        if nid in external:
            classes.append("ext")
        if nid == focus:
            classes.append("focus")
        if tiers:
            classes.append(f"p{tiers[nid]}")
        attrs = [
            f'label="{dot_label(nodes[nid]["title"], 21)}"',
            f'class="{" ".join(classes)}"',
        ]
        target = url(nid) if url else None
        if target:
            attrs += [f'URL="{target}"', 'target="_self"']
        out.append(f'  "{nid}" [{", ".join(attrs)}];')

    for src, edge, dst in edges:
        rank = f" p{min(tiers[src], tiers[dst])}" if tiers else ""
        attrs = [f'class="e e-{edge["rel"]}{rank}"']
        if labels and edge.get("why"):
            attrs.append(f'label="{dot_label(edge["why"], 26)}"')
        out.append(f'  "{src}" -> "{dst}" [{", ".join(attrs)}];')

    out.append("}")
    return "\n".join(out)


def anchors(node):
    """Every external link for a node: primary sources first, then background."""
    urls = [r["url"] for r in node.get("refs") or [] if r.get("url")]
    if node.get("wikipedia"):
        urls.append(node["wikipedia"])
    return urls


def primary_url(node):
    """The best single link for a node: a source if it has one, else background."""
    found = anchors(node)
    return found[0] if found else None
