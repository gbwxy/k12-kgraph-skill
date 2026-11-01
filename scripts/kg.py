#!/usr/bin/env python3
"""K12-KGraph query CLI — stdlib only.

Usage:
  kg.py [--data DIR|FILE] COMMAND [ARGS]

Commands:
  stats                          node/edge counts by label and type
  find KEYWORD [--label L]       search nodes by name/aliases/definition/stem
  show ID                        node details + grouped relations
  prereq ID [--transitive] [--depth N]
                                 prerequisite chain + suggested learning order
  path FROM TO                   prerequisite path (FROM is ancestor of TO)
  locate ID                      textbook location (appears_in / is_part_of)
  exercises ID                   exercises testing this concept/skill
  neighbors ID                   is_a / relates_to / leads_to neighbors
  check-cycles [--all]           cycle report on prerequisites_for & is_a

Data resolution order: --data flag, $K12KGRAPH_DATA, ~/.cache/k12-kgraph.
A directory is scanned (depth<=3) for JSON files holding nodes/edges;
files are merged (subject-level properties override global ones).
"""
import argparse
import json
import os
import sys
from collections import defaultdict, deque

NODE_LABELS = {"Book", "Chapter", "Section", "Concept", "Skill", "Experiment", "Exercise"}
EDGE_TYPES = {"is_a", "prerequisites_for", "relates_to", "verifies",
              "tests_concept", "tests_skill", "appears_in", "is_part_of", "leads_to"}
PREREQ_TYPES = {"prerequisites_for", "leads_to"}


def err(msg):
    print(f"error: {msg}", file=sys.stderr)


def resolve_data(explicit):
    for cand in (explicit, os.environ.get("K12KGRAPH_DATA"),
                 os.path.expanduser("~/.cache/k12-kgraph")):
        if cand and os.path.exists(cand):
            return cand
    return None


def iter_json_files(root):
    if os.path.isfile(root):
        yield root
        return
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        if dirpath.count(os.sep) - base_depth > 3:
            dirnames.clear()
            continue
        for fn in sorted(filenames):
            if fn.endswith(".json"):
                yield os.path.join(dirpath, fn)


def load_raw(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        err(f"skip {path}: {e}")
        return None


def split_records(obj):
    """Return (nodes, edges) record lists from one JSON file's shape."""
    if isinstance(obj, dict) and ("nodes" in obj or "edges" in obj):
        return obj.get("nodes") or [], obj.get("edges") or []
    if isinstance(obj, list) and obj:
        head = obj[0]
        if isinstance(head, dict) and ("source" in head or "target" in head) and "id" not in head:
            return [], obj
        return obj, []
    return [], []


def norm_node(n):
    nid = n.get("id") or n.get("node_id")
    label = n.get("label") or ""
    if label not in NODE_LABELS:
        t = n.get("type") or n.get("node_type") or ""
        label = t if t in NODE_LABELS else label
    name = n.get("name") or n.get("title") or n.get("stem") or ""
    props = dict(n.get("properties") or {})
    for k, v in n.items():
        if k not in ("id", "node_id", "label", "type", "node_type", "name", "title", "properties") \
                and k not in props:
            props[k] = v
    return {"id": nid, "label": label, "name": name, "props": props}


def norm_edge(e):
    src = e.get("source") or e.get("from") or e.get("head")
    tgt = e.get("target") or e.get("to") or e.get("tail")
    et = e.get("type") or e.get("relation") or e.get("label") or ""
    props = dict(e.get("properties") or {})
    for k in ("evidence", "relations"):
        if k in e and k not in props:
            props[k] = e[k]
    names = {"source_name": e.get("source_name") or e.get("source_stem") or "",
             "target_name": e.get("target_name") or ""}
    return {"source": src, "target": tgt, "type": et, "props": props, "names": names}


class Graph:
    def __init__(self):
        self.nodes = {}
        self.edges = []            # normalized edge dicts
        self.out = defaultdict(list)   # id -> [(etype, target)]
        self.inn = defaultdict(list)   # id -> [(etype, source)]

    def add_node(self, n):
        if not n["id"]:
            return
        old = self.nodes.get(n["id"])
        if old is None:
            self.nodes[n["id"]] = n
        else:  # richer properties win
            merged = dict(old["props"])
            merged.update({k: v for k, v in n["props"].items() if v not in (None, "", [])})
            old["props"].update(merged)
            if not old["name"]:
                old["name"] = n["name"]
            if not old["label"]:
                old["label"] = n["label"]

    def add_edge(self, e):
        if not (e["source"] and e["target"]):
            return
        key = (e["source"], e["type"], e["target"])
        if any((x["source"], x["type"], x["target"]) == key for x in self.edges):
            return
        self.edges.append(e)
        self.out[e["source"]].append((e["type"], e["target"]))
        self.inn[e["target"]].append((e["type"], e["source"]))

    # ---------- lookup helpers ----------
    def name_of(self, nid):
        n = self.nodes.get(nid)
        return n["name"] if n else "?"

    def fmt(self, nid):
        return f"{nid}({self.name_of(nid)})" if self.name_of(nid) != "?" else nid

    def edge_props(self, src, et, tgt):
        for x in self.edges:
            if (x["source"], x["type"], x["target"]) == (src, et, tgt):
                return x["props"]
        return {}

    def find_nodes(self, keyword, label=None, limit=20):
        kw = keyword.lower()
        hits = []
        for n in self.nodes.values():
            if label and n["label"] != label:
                continue
            hay = " ".join([n["name"], str(n["props"].get("aliases", "")),
                            str(n["props"].get("definition", "")),
                            str(n["props"].get("description", "")),
                            str(n["props"].get("stem", ""))]).lower()
            if kw in hay:
                hits.append(n)
        hits.sort(key=lambda n: (n["label"] != "Concept", n["id"]))
        return hits[:limit]


def load_graph(data_path):
    g = Graph()
    files = list(iter_json_files(data_path))
    if not files:
        err(f"no JSON files under {data_path}")
        sys.exit(2)
    for path in files:
        raw = load_raw(path)
        if raw is None:
            continue
        nodes, edges = split_records(raw)
        if not nodes and not edges:
            continue  # e.g. manifest.json
        for n in nodes:
            if isinstance(n, dict):
                g.add_node(norm_node(n))
        for e in edges:
            if not isinstance(e, dict):
                continue
            if "target_name_to_ids" in e and not e.get("target"):
                base = {k: v for k, v in e.items() if k != "target_name_to_ids"}
                for item in e["target_name_to_ids"] or []:
                    sub = dict(base)
                    sub["target"] = item.get("target")
                    sub["target_name"] = item.get("target_name")
                    g.add_edge(norm_edge(sub))
            else:
                g.add_edge(norm_edge(e))
    return g, files


def topo_order(g, ids):
    """Topological order of `ids` under prerequisites edges; breaks cycles with a warning."""
    idset = set(ids)
    prereq_edges = defaultdict(list)
    for e in g.edges:
        if e["type"] in PREREQ_TYPES and e["source"] in idset and e["target"] in idset:
            prereq_edges[e["source"]].append(e["target"])
    order, state, cycles = [], {}, []

    def dfs(u, stack):
        state[u] = 1
        for v in sorted(prereq_edges.get(u, [])):
            if state.get(v) == 1:
                cycles.append(stack[stack.index(v):] + [v])
                continue  # break the back edge
            if state.get(v) is None:
                dfs(v, stack + [v])
        state[u] = 2
        order.append(u)

    for u in sorted(idset):
        if state.get(u) is None:
            dfs(u, [u])
    order.reverse()
    return order, cycles


def ancestors_prereq(g, nid, depth=None):
    """All transitive prerequisites of nid (excluding nid)."""
    seen, q = set(), deque([(nid, 0)])
    while q:
        cur, d = q.popleft()
        if depth is not None and d >= depth:
            continue
        for et, src in g.inn.get(cur, []):
            if et in PREREQ_TYPES and src not in seen:
                seen.add(src)
                q.append((src, d + 1))
    return seen


# ---------- commands ----------
def cmd_stats(g, args):
    labels = defaultdict(int)
    for n in g.nodes.values():
        labels[n["label"] or "?"] += 1
    etypes = defaultdict(int)
    for e in g.edges:
        etypes[e["type"] or "?"] += 1
    print(f"nodes: {len(g.nodes)}")
    for k in sorted(labels, key=lambda x: -labels[x]):
        print(f"  {k or '(unknown)'}: {labels[k]}")
    print(f"edges: {len(g.edges)}")
    for k in sorted(etypes, key=lambda x: -etypes[x]):
        print(f"  {k or '(unknown)'}: {etypes[k]}")


def cmd_find(g, args):
    hits = g.find_nodes(args.keyword, label=args.label, limit=args.limit)
    if not hits:
        print(f"no node matches '{args.keyword}' (try shorter keyword or `stats`)")
        return
    for n in hits:
        imp = n["props"].get("importance", "")
        print(f"{n['id']} | {n['label']} | {n['name']} | importance={imp}")
    print(f"({len(hits)} hits) use `show <id>` for details")


def cmd_show(g, args):
    n = g.nodes.get(args.id)
    if not n:
        err(f"unknown id {args.id}; try `find`")
        sys.exit(1)
    print(f"node: {n['id']} | label={n['label']} | name={n['name']}")
    for k, v in n["props"].items():
        if v not in (None, "", [], {}):
            s = str(v).replace("\n", " ")
            print(f"  {k}: {s[:200]}")
    print("relations:")
    rows = []
    for et, tgt in g.out.get(args.id, []):
        rows.append(f"  {et} -> {g.fmt(tgt)}")
    for et, src in g.inn.get(args.id, []):
        rows.append(f"  {et} <- {g.fmt(src)}")
    for r in sorted(rows)[:40]:
        print(r)
    if len(rows) > 40:
        print(f"  ... {len(rows) - 40} more")


def cmd_prereq(g, args):
    if args.id not in g.nodes:
        err(f"unknown id {args.id}")
        sys.exit(1)
    direct = [(src, g.edge_props(src, et, args.id))
              for et, src in g.inn.get(args.id, []) if et in PREREQ_TYPES]
    print(f"target: {g.fmt(args.id)}")
    print(f"direct_prerequisites: {len(direct)}")
    for src, props in sorted(direct):
        ev = str(props.get("evidence", ""))[:80]
        print(f"  {g.fmt(src)}" + (f" | evidence: {ev}" if ev else ""))
    if not args.transitive:
        print("(use --transitive for the full chain + suggested learning order)")
        return
    anc = ancestors_prereq(g, args.id, depth=args.depth)
    print(f"transitive_prerequisites: {len(anc)}")
    order, cycles = topo_order(g, anc | {args.id})
    if cycles:
        print(f"warning: {len(cycles)} cycle(s) broken for ordering (see `check-cycles`):")
        for c in cycles[:3]:
            print("  " + " -> ".join(c))
    print("suggested_learning_order:")
    for i, nid in enumerate(order, 1):
        if nid == args.id:
            print(f"  {i}. {g.fmt(nid)}  <- target")
        else:
            print(f"  {i}. {g.fmt(nid)}")


def cmd_path(g, args):
    if args.src not in g.nodes or args.dst not in g.nodes:
        err("unknown id")
        sys.exit(1)
    prev = {args.src: None}
    q = deque([args.src])
    while q:
        cur = q.popleft()
        if cur == args.dst:
            break
        for et, tgt in g.out.get(cur, []):
            if et in PREREQ_TYPES and tgt not in prev:
                prev[tgt] = (cur, et)
                q.append(tgt)
    if args.dst not in prev:
        rev = args.src in {t for et, t in g.out.get(args.dst, []) if et in PREREQ_TYPES}
        print(f"no prerequisite path {args.src} -> {args.dst}")
        if rev:
            print("note: the edge points the other way; try `path <dst> <src>`")
        return
    chain, cur = [], args.dst
    while cur is not None:
        chain.append(cur)
        cur = prev[cur][0] if prev[cur] else None
    chain.reverse()
    print("prerequisite_path:")
    for i, nid in enumerate(chain):
        print(f"  {i + 1}. {g.fmt(nid)}")


def cmd_locate(g, args):
    if args.id not in g.nodes:
        err(f"unknown id {args.id}")
        sys.exit(1)
    locs = [tgt for et, tgt in g.out.get(args.id, []) if et in ("appears_in", "is_part_of")]
    if not locs:
        # maybe the node is itself a chapter/section — walk upward
        locs = [tgt for et, tgt in g.out.get(args.id, []) if et == "is_part_of"]
    if not locs:
        print(f"no appears_in/is_part_of edge for {args.id} (global_KG may omit locations)")
        return
    print(f"locations of {g.fmt(args.id)}:")
    for loc in locs:
        chain = [loc]
        cur = loc
        for _ in range(5):
            ups = [t for et, t in g.out.get(cur, []) if et == "is_part_of"]
            if not ups:
                break
            cur = ups[0]
            chain.append(cur)
        print("  " + " < ".join(g.fmt(x) for x in chain))


def cmd_exercises(g, args):
    if args.id not in g.nodes:
        err(f"unknown id {args.id}")
        sys.exit(1)
    exs = [(et, src) for et, src in g.inn.get(args.id, []) if et in ("tests_concept", "tests_skill")]
    if not exs:
        print(f"no exercise tests {args.id} (math concepts have few exercises; try afterclass_exercises files)")
        return
    print(f"exercises testing {g.fmt(args.id)}: {len(exs)}")
    for et, src in sorted(exs):
        n = g.nodes.get(src)
        if not n:
            continue
        stem = str(n["props"].get("stem") or n["name"]).replace("\n", " ")[:80]
        ans = str(n["props"].get("answer", ""))[:40]
        diff = n["props"].get("difficulty", "")
        print(f"  [{et}] {src} | difficulty={diff} | {stem}" + (f" | answer: {ans}" if ans else ""))


def cmd_neighbors(g, args):
    if args.id not in g.nodes:
        err(f"unknown id {args.id}")
        sys.exit(1)
    for et in ("is_a", "relates_to", "leads_to"):
        outs = [t for e, t in g.out.get(args.id, []) if e == et]
        ins = [s for e, s in g.inn.get(args.id, []) if e == et]
        if et == "is_a":
            print(f"is_a parents: {', '.join(g.fmt(x) for x in outs) or '-'}")
            print(f"is_a children: {', '.join(g.fmt(x) for x in ins) or '-'}")
        else:
            both = sorted(set(outs) | set(ins))
            rels = []
            for x in both:
                p = g.edge_props(args.id, et, x) or g.edge_props(x, et, args.id)
                note = str(p.get("relations", ""))[:60]
                rels.append(g.fmt(x) + (f" | {note}" if note else ""))
            print(f"{et}: " + ("; ".join(rels) or "-"))


def cmd_check_cycles(g, args):
    types = EDGE_TYPES if args.all else PREREQ_TYPES | {"is_a"}
    found = 0
    for et in sorted(types):
        adj = defaultdict(list)
        for e in g.edges:
            if e["type"] == et:
                adj[e["source"]].append(e["target"])
        state, cycles = {}, []

        def dfs(u, stack):
            state[u] = 1
            for v in sorted(adj.get(u, [])):
                if state.get(v) == 1:
                    cycles.append(stack[stack.index(v):] + [v])
                elif state.get(v) is None:
                    dfs(v, stack + [v])
            state[u] = 2

        for u in sorted(adj):
            if state.get(u) is None:
                dfs(u, [u])
        if cycles:
            found += len(cycles)
            print(f"[{et}] {len(cycles)} cycle(s):")
            for c in cycles[:10]:
                print("  " + " -> ".join(c))
        else:
            print(f"[{et}] acyclic")
    if found:
        print(f"total: {found} cycle(s). Known upstream issue: haolpku/K12-KGraph#8 — break cycles before topological use.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", help="data dir or single JSON file")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("stats")
    p = sub.add_parser("find")
    p.add_argument("keyword")
    p.add_argument("--label")
    p.add_argument("--limit", type=int, default=20)
    p = sub.add_parser("show")
    p.add_argument("id")
    p = sub.add_parser("prereq")
    p.add_argument("id")
    p.add_argument("--transitive", action="store_true")
    p.add_argument("--depth", type=int)
    p = sub.add_parser("path")
    p.add_argument("src")
    p.add_argument("dst")
    p = sub.add_parser("locate")
    p.add_argument("id")
    p = sub.add_parser("exercises")
    p.add_argument("id")
    p = sub.add_parser("neighbors")
    p.add_argument("id")
    p = sub.add_parser("check-cycles")
    p.add_argument("--all", action="store_true")

    args = ap.parse_args()
    data = resolve_data(args.data)
    if not data:
        err("no data found. Run `bash scripts/fetch_data.sh core` or pass --data PATH "
            "(repo demo file also works: --data demo/kg/math_7a_rjb.json)")
        sys.exit(2)
    g, files = load_graph(data)
    if not g.nodes:
        err(f"no nodes loaded from {data}")
        sys.exit(2)
    print(f"# loaded {len(g.nodes)} nodes / {len(g.edges)} edges from {data} ({len(files)} json files)",
          file=sys.stderr)
    {"stats": cmd_stats, "find": cmd_find, "show": cmd_show, "prereq": cmd_prereq,
     "path": cmd_path, "locate": cmd_locate, "exercises": cmd_exercises,
     "neighbors": cmd_neighbors, "check-cycles": cmd_check_cycles}[args.cmd](g, args)


if __name__ == "__main__":
    main()
