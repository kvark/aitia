# aitia

*aitia* (αἰτία) is Greek for **cause** — the answer to "why". This is a
knowledge graph in which **the edges carry the reasons**.

Most maps of a field give you the nodes: a list of techniques, a reading list,
a citation graph. The nodes are the easy part — GGX, Adam, LayerNorm are in
every index. What is almost never written down is *why one leads to the next*:

```
GGX        ──"can't hit back-facing normals"──▶  VNDF
LayerNorm  ──"re-centring contributes nothing"──▶  RMSNorm
```

That edge is the compressed judgment a practitioner accumulates and a citation
database throws away. Collecting those is the entire point of this repository.

Today the graph covers **computer graphics** and **AI/ML**, over a small shared
foundation. Nothing in the format is specific to those; a domain earns its
place by connecting to the others, not by being added.

## Where things live

Nothing in this file is generated, and nothing generated is committed. The
repository holds only what a person wrote; everything derived from it is built
on demand and published to the site, so the two can never drift apart.

| | |
| --- | --- |
| [`nodes/`](nodes/) | the graph — one hand-written YAML file per node |
| [`clusters.yaml`](clusters.yaml) | the groupings nodes are filed under |
| [`domains.yaml`](domains.yaml) | the fields those groupings belong to |
| [`tools/`](tools/) | validation, queries, and the site generator |
| [`SCHEMA.md`](SCHEMA.md) | the node format and the relation vocabulary |
| **[aitia.dev](https://aitia.dev/)** | the rendered graph: diagrams, a page per node, search, `graph.json` |

## A node

Plain YAML. The filename is the id, so it cannot drift out of sync with the
contents.

```yaml
title: RMS Normalization
cluster: learning
year: 2019
aka: [RMSNorm]
summary: >
  Drops the mean-subtraction step and rescales by the root mean square alone.
  Matches LayerNorm's quality, which is the finding: the re-centring was
  never doing the work.
refs:
  - title: Root Mean Square Layer Normalization
    authors: Zhang, Sennrich
    year: 2019
    url: https://arxiv.org/abs/1910.07467
edges:
  - rel: corrects
    to: layer-normalization
    why: re-centring costs time and contributes nothing measurable
```

Eight relations, no free-form types: `part-of`, `specializes`, `approximates`,
`corrects`, `extends`, `requires`, `alternative-to`, `validates`.

Two rules the validator enforces. Every edge except `part-of` must say *why* —
that reason is the thing being collected, so an edge without one is not worth
having. And every node must carry at least one link out, a paper or a Wikipedia
article, so a reader can check a claim instead of trusting the summary.

## Node ids are global, deliberately

There is one flat namespace, and no per-domain prefixes. When two fields turn
out to use the same concept, that is supposed to produce **one node with edges
from both** — Monte Carlo integration is not one thing for rendering and
another for variational inference. Prefixing ids by domain would quietly
fragment exactly the connections that make a combined graph worth more than
several separate ones.

So a name collision is a prompt, not a problem: decide whether you have one
concept or two, and if two, name them apart.

## Browsing

Each cluster is one pannable, zoomable diagram. Every node gets a page with its
reasoned edges in **both** directions — what it corrects, and what corrects it —
along with its neighbourhood and its sources. The whole graph is also served as
a single [`graph.json`](https://aitia.dev/graph.json).

Edges are colour-coded by family — supersedes, classifies, substitutes for,
depends on — with the second relation in each family drawn dashed. Eight hues
would have been simpler, but eight cannot be told apart reliably under colour
vision deficiency, and four plus a line pattern can.

A cluster past a dozen nodes is drawn as a map rather than as a document. The
reasons come off the edges, which is around half of everything graphviz has to
find room for, and hovering a node writes them back along its own edges, at a
size you can read — a reason nobody can read at diagram scale is a texture, not
a sentence. The same threshold ranks the nodes by how connected each one is —
twice the edges pointing at it, plus the edges it declares — so the junctions
come forward and the twigs recede, and there is somewhere to start looking.

Nothing is hidden by either. Hovering restores a node, its edges and their far
ends; the ranking lifts wholesale once the diagram is drawn at its natural size
or larger, so one that fits your window is never ranked at all; and every reason
in the cluster is also on the page as text, under the diagram, for a reader with
no pointer or no scripting. In-degree alone would have been the obvious weight
and is the wrong one — edges are declared on the subject node, so the newest
idea in any area starts at zero, and fading the frontier first is exactly
backwards.

Layout is done by graphviz at build time and the result is inlined as SVG, so a
page carries no diagramming library: it renders before any script runs, and the
node links are real anchors that work with scripting off. Search (<kbd>/</kbd>)
highlights matches in the diagram and offers them as a jump list.

## Querying

The question a rendered mind map can never answer is "what connects these two
things?" — so that is the one the tools answer, across domains as readily as
within one:

```console
$ python3 tools/kg.py path diffusion-model svgf
Diffusion Model (diffusion-model)
  --extends-->
      (denoises repeatedly, from pure noise, to synthesise)
  Learned Denoising (neural-denoising)
  --alternative-to-->
      (learns the filter from data instead of hand-tuned weights)
  Spatiotemporal Variance-Guided Filtering (svgf)
```

```console
$ python3 tools/kg.py show vndf       # a node, with incoming and outgoing edges
$ python3 tools/kg.py search fresnel  # substring across ids, titles, summaries
$ python3 tools/kg.py stats           # counts, and anything left unconnected
```

## Contributing

Add one file to `nodes/`. You never have to edit an existing node to attach a
new one, because edges are declared on the node that owns them — so two people
working in the same area do not collide.

```console
$ python3 tools/check.py           # validate; CI runs exactly this
$ python3 tools/site.py            # build the site locally into site/
```

Building the site needs graphviz (`apt-get install graphviz`); validating and
querying do not.

An edge whose `why` could be swapped onto any other pair of nodes is not
carrying its weight. "improves on it" is not a reason; "photon count is capped
by memory, so bias never vanishes" is.
