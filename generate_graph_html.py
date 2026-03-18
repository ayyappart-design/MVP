"""
generate_graph_html.py
────────────────────────────────────────────────────────────────────
Reads  : graph_info.py   (JSON pipeline definition)
Writes : graph_knowledge.html  (D3 interactive knowledge graph)

Usage (VS Code terminal):
  python generate_graph_html.py
  python generate_graph_html.py --input graph_info.py --output graph_knowledge.html
────────────────────────────────────────────────────────────────────
"""

import json
import argparse
import re
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════
# NODE + EDGE BUILDERS
# ═══════════════════════════════════════════════════════════════════

def build_graph(data: dict) -> tuple[list, list]:
    """Extract nodes and edges from graph_info JSON."""
    nodes = []
    edges = []
    tp_index = 0
    mlf_index = 0
    seen_mlv = {}      # mlflow param value label → node id (dedup)
    seen_tp  = {}      # property_name+value → tp id (dedup shared props)

    node_map = {n["id"]: n for n in data["nodes"]}

    # ── Experiment root node ────────────────────────────────────────
    nodes.append({
        "id": "exp_root", "type": "import", "_label": "Experiment",
        "full_id": data["experiment_id"],
    })

    # ── Experiment short-id node ────────────────────────────────────
    short_exp = data["experiment_id"][:16]
    exp_short_id = f"expid_{short_exp[:8]}"
    nodes.append({
        "id": exp_short_id, "type": "import", "_label": short_exp,
        "experiment_id": data["experiment_id"],
    })

    # ── Status / variable shared nodes ─────────────────────────────
    nodes.append({"id": "status_valid",  "type": "variable", "_label": "valid",    "field": "status",          "value": "valid"})
    nodes.append({"id": "conn_postgres", "type": "variable", "_label": "postgres", "field": "connection_type", "value": "postgres"})

    # ── Category nodes ──────────────────────────────────────────────
    nodes.append({"id": "cat_data_preprocessing", "type": "transformation_category", "_label": "data preprocessing", "category_name": "data_preprocessing"})
    nodes.append({"id": "cat_ml_algorithm",        "type": "transformation_category", "_label": "ml algorithm",       "category_name": "ml_algorithm"})

    # ── UI details shared node ──────────────────────────────────────
    nodes.append({"id": "uid_null_null", "type": "return_value", "_label": "ui sourceHandle targetHandle", "sourceHandle": None, "targetHandle": None})

    # SQL tables / schema
    sql_tables_seen  = set()
    sql_columns_seen = set()

    # ── Workflow nodes ──────────────────────────────────────────────
    for n in data["nodes"]:
        nid = n["id"]
        nm  = n["transformation_name"]
        nt  = n["transformation_type"]
        nd  = n["node_details"]

        nodes.append({
            "id": nid, "type": "workflow_node", "_label": nm,
            "transformation_type":     nt,
            "transformation_name":     nm,
            "transformation_category": n["transformation_category"],
            "status": n["status"],
            "node_count": nd["node_count"],
        })

        # class (transformation type) node
        ttype_id = f"ttype_{nt.replace(' ', '_')}"
        if not any(x["id"] == ttype_id for x in nodes):
            nodes.append({
                "id": ttype_id, "type": "class", "_label": nt,
                "category": n["transformation_category"],
            })

        # ── workflow edges ──────────────────────────────────────────
        edges.append({"type": "is_type",    "source": nid, "target": ttype_id})
        edges.append({"type": "in_category","source": nid, "target": f"cat_{n['transformation_category']}"})
        edges.append({"type": "has_status", "source": nid, "target": "status_valid"})
        edges.append({"type": "belongs_to", "source": nid, "target": exp_short_id})
        if n["connection_type"] == "postgres":
            edges.append({"type": "has_field", "source": nid, "target": "conn_postgres"})

        # ── transformation_properties ───────────────────────────────
        for prop in nd["transformation_properties"]:
            pname = prop["property_name"]
            pval  = str(prop["property_value"])
            # Clean label (remove dots for display)
            label_val = re.sub(r'\.', ' ', pval)
            key = f"{pname}||{pval}"
            if key not in seen_tp:
                tp_id = f"tp_{tp_index}"
                seen_tp[key] = tp_id
                tp_index += 1
                nodes.append({
                    "id": tp_id, "type": "parameter",
                    "_label": f"{pname} {label_val}",
                    "property_name": pname, "property_value": pval,
                })
            edges.append({"type": "has_property", "source": nid, "target": seen_tp[key]})

            # SQL table / column from Source properties
            if pname == "source_table":
                tbl_id = f"sqlt_{pval}"
                if tbl_id not in sql_tables_seen:
                    nodes.append({"id": tbl_id, "type": "sql_table", "_label": pval, "table": pval})
                    sql_tables_seen.add(tbl_id)
                edges.append({"type": "queries_table", "source": nid, "target": tbl_id})
            if pname == "schema":
                sch_id = f"schema_{pval}"
                if sch_id not in sql_tables_seen:
                    nodes.append({"id": sch_id, "type": "sql_table", "_label": pval, "schema": pval})
                    sql_tables_seen.add(sch_id)
                edges.append({"type": "has_schema", "source": nid, "target": sch_id})
            if pname == "columns":
                cols = [c.strip().strip("'\"") for c in pval.split(",") if c.strip()]
                for col in cols:
                    col_id = f"sqlc_{col}"
                    if col_id not in sql_columns_seen:
                        nodes.append({"id": col_id, "type": "sql_column", "_label": col, "column": col})
                        sql_columns_seen.add(col_id)
                    edges.append({"type": "selects_column", "source": nid, "target": col_id})

        # ── mlflow_tracking_properties ──────────────────────────────
        for ml in nd["mlflow_tracking_properties"]:
            grp    = ml["property_name"]
            params = json.loads(ml["property_value"])

            mlf_id = f"mlf_{mlf_index}"
            mlf_index += 1
            nodes.append({
                "id": mlf_id, "type": "function", "_label": grp,
                "property_name": grp, "property_value": ml["property_value"],
            })
            edges.append({"type": "tracks", "source": nid, "target": mlf_id})

            for param in params:
                mlv_id = f"mlv_{param[:25]}"
                if mlv_id not in seen_mlv:
                    seen_mlv[mlv_id] = True
                    nodes.append({
                        "id": mlv_id, "type": "argument",
                        "_label": param, "value": param, "parent_prop": grp,
                    })
                edges.append({"type": "contains", "source": mlf_id, "target": mlv_id})

    # ── Pipeline workflow edges ─────────────────────────────────────
    for e in data["edges"]:
        src = node_map[e["source_node_id"]]
        tgt = node_map[e["target_node_id"]]
        erec_id = f"erec_{e['id']}"

        edges.append({"type": "workflow_edge",
                      "source": e["source_node_id"], "target": e["target_node_id"]})

        # Edge record node (call)
        src_short = src["transformation_name"].split("_")[0]
        tgt_short = tgt["transformation_name"].split("_")[0]
        nodes.append({
            "id": erec_id, "type": "call",
            "_label": f"{src_short} to {tgt_short}",
            "edge_id": e["id"],
            "source_node_id": e["source_node_id"],
            "target_node_id": e["target_node_id"],
            "transformation_type": e["transformation_type"],
        })
        edges.append({"type": "produces", "source": e["source_node_id"], "target": erec_id})
        edges.append({"type": "produces", "source": e["target_node_id"], "target": erec_id})
        edges.append({"type": "has_ui", "source": erec_id, "target": "uid_null_null"})

    return nodes, edges


# ═══════════════════════════════════════════════════════════════════
# HTML GENERATOR
# ═══════════════════════════════════════════════════════════════════

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>ML Pipeline Knowledge Graph</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Syne:wght@700;800&display=swap');
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#07070f;--surface:#10101e;--border:rgba(255,255,255,0.07);
  --wf:#4a90e2;--import:#f0a500;--variable:#3ecf6e;--function:#b07ef7;
  --class:#f76e6e;--call:#4ecde4;--param:#a0a0c0;--arg:#80c0a0;
  --ret:#e0a0e0;--sqltable:#ff8c42;--sqlcol:#ffd166;--cat:#e8a838;
}}
body{{background:var(--bg);color:#e0e0f0;font-family:'IBM Plex Mono',monospace;overflow:hidden;height:100vh}}
#header{{position:fixed;top:0;left:0;right:0;z-index:300;height:50px;
  display:flex;align-items:center;justify-content:space-between;padding:0 22px;
  background:rgba(7,7,15,0.92);border-bottom:1px solid var(--border);backdrop-filter:blur(14px)}}
#header h1{{font-family:'Syne',sans-serif;font-size:16px;font-weight:800;letter-spacing:.05em;
  background:linear-gradient(100deg,#7eb8f7,#b07ef7);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
#hstats{{font-size:10px;color:#444;letter-spacing:.06em}}
#legend{{position:fixed;bottom:20px;left:20px;z-index:300;
  background:rgba(10,10,20,0.94);border:1px solid var(--border);border-radius:10px;
  padding:13px 16px;backdrop-filter:blur(8px);font-size:10px;
  display:grid;grid-template-columns:1fr 1fr;gap:0 18px}}
#legend h3{{grid-column:1/-1;font-family:'Syne',sans-serif;font-size:9px;
  letter-spacing:.14em;text-transform:uppercase;color:#444;margin-bottom:8px}}
.lr{{display:flex;align-items:center;gap:7px;margin-bottom:5px;color:#888}}
.ld{{width:10px;height:10px;border-radius:2px;flex-shrink:0}}
#panel{{position:fixed;top:50px;right:0;z-index:300;width:310px;
  height:calc(100vh - 50px);background:rgba(10,10,20,0.97);
  border-left:1px solid var(--border);transform:translateX(100%);
  transition:transform .28s cubic-bezier(.4,0,.2,1);display:flex;flex-direction:column;overflow:hidden}}
#panel.open{{transform:translateX(0)}}
#panel-head{{padding:16px 18px 12px;border-bottom:1px solid var(--border);flex-shrink:0}}
#panel-name{{font-family:'Syne',sans-serif;font-size:14px;font-weight:700;color:#fff;word-break:break-all;margin-bottom:4px}}
.pbadge{{display:inline-block;padding:2px 8px;border-radius:4px;font-size:9px;letter-spacing:.1em;text-transform:uppercase;font-weight:600;margin-bottom:8px}}
#panel-meta{{font-size:9px;color:#444;line-height:1.8;word-break:break-all}}
#panel-body{{flex:1;overflow-y:auto;padding:12px 18px 20px}}
.psec-title{{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:#444;margin:12px 0 6px}}
.pitem{{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:6px;
  background:rgba(255,255,255,0.04);margin-bottom:3px;font-size:10px;color:#bbb;
  cursor:pointer;word-break:break-all;transition:background .15s}}
.pitem:hover{{background:rgba(255,255,255,0.1)}}
.pdot{{width:7px;height:7px;border-radius:1px;flex-shrink:0}}
.pedge-type{{margin-left:auto;font-size:8px;color:#444;white-space:nowrap;flex-shrink:0;padding-left:4px}}
#hint{{position:fixed;bottom:20px;right:20px;z-index:300;
  font-size:10px;color:#333;letter-spacing:.05em;text-align:right;line-height:2;pointer-events:none}}
.row-label{{font-family:'Syne',sans-serif;font-size:9px;letter-spacing:.14em;text-transform:uppercase;fill:#1e1e32;dominant-baseline:middle}}
.edge{{fill:none}}
.node-shape{{cursor:pointer}}
.nlabel{{pointer-events:none;font-family:'IBM Plex Mono',monospace;font-size:9px;fill:#999}}
.nlabel.wf{{font-family:'Syne',sans-serif;font-size:11px;font-weight:700;fill:#fff}}
.dimmed{{opacity:0.04!important}}
</style>
</head>
<body>
<div id="header">
  <h1>ML Pipeline · Knowledge Graph</h1>
  <div id="hstats"></div>
</div>
<div id="legend">
  <h3>Node Types</h3>
  <div class="lr"><div class="ld" style="background:var(--wf);border-radius:3px"></div>Pipeline Step</div>
  <div class="lr"><div class="ld" style="background:var(--import);border-radius:50%"></div>Experiment</div>
  <div class="lr"><div class="ld" style="background:var(--variable);transform:rotate(45deg)"></div>Variable</div>
  <div class="lr"><div class="ld" style="background:var(--function)"></div>MLflow Property</div>
  <div class="lr"><div class="ld" style="background:var(--class);border-radius:50%"></div>Step Type</div>
  <div class="lr"><div class="ld" style="background:var(--cat)"></div>Category</div>
  <div class="lr"><div class="ld" style="background:var(--call);border-radius:50%"></div>Edge Record</div>
  <div class="lr"><div class="ld" style="background:var(--sqltable)"></div>SQL Table</div>
  <div class="lr"><div class="ld" style="background:var(--sqlcol);border-radius:50%"></div>SQL Column</div>
  <div class="lr"><div class="ld" style="background:var(--param)"></div>Transform Prop</div>
  <div class="lr"><div class="ld" style="background:var(--arg)"></div>MLflow Value</div>
  <div class="lr"><div class="ld" style="background:var(--ret)"></div>UI Details</div>
</div>
<div id="panel">
  <div id="panel-head">
    <div id="panel-name"></div>
    <div id="panel-badge" class="pbadge"></div>
    <div id="panel-meta"></div>
  </div>
  <div id="panel-body"></div>
</div>
<div id="hint">Click any node to inspect<br>Scroll to zoom · Drag to pan<br>Click bg to reset</div>
<svg id="g"></svg>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const NODES = {nodes_json};
const EDGES = {edges_json};

function css(v){{return getComputedStyle(document.documentElement).getPropertyValue(v).trim()}}
const COLOR={{
  workflow_node:css('--wf'), import:css('--import'), variable:css('--variable'),
  function:css('--function'), class:css('--class'), call:css('--call'),
  parameter:css('--param'), argument:css('--arg'), return_value:css('--ret'),
  sql_table:css('--sqltable'), sql_column:css('--sqlcol'), transformation_category:css('--cat'),
}};

const NBI = Object.fromEntries(NODES.map(n => [n.id, n]));
const svg = d3.select('#g')
  .attr('width','100%').attr('height','100%')
  .style('position','fixed').style('top','50px').style('left',0)
  .style('width','100%').style('height','calc(100vh - 50px)');

document.getElementById('hstats').textContent = `${{NODES.length}} nodes · ${{EDGES.length}} edges`;

const W = () => window.innerWidth, H = () => window.innerHeight - 50;

// Arrow markers
const defs = svg.append('defs');
Object.entries(COLOR).forEach(([t, col]) => {{
  defs.append('marker').attr('id',`arr_${{t}}`).attr('viewBox','0 -3 8 6')
    .attr('refX',18).attr('refY',0).attr('markerWidth',5).attr('markerHeight',5).attr('orient','auto')
    .append('path').attr('d','M0,-3L8,0L0,3').attr('fill',col).attr('opacity',0.6);
}});

const g = svg.append('g');
const zoom = d3.zoom().scaleExtent([0.05,4]).on('zoom', e => g.attr('transform',e.transform));
svg.call(zoom);

// ── Layout: row-based positioning ─────────────────────────────────
const ROW_TYPE = {{
  import: 0, workflow_node: 1, call: 2, class: 3,
  transformation_category: 4, variable: 5, parameter: 6,
  function: 7, argument: 8, sql_table: 9, sql_column: 10, return_value: 11,
}};
const ROW_H = 110, START_Y = 60;
const byRow = {{}};
NODES.forEach(n => {{
  const r = ROW_TYPE[n.type] ?? 6;
  (byRow[r] = byRow[r]||[]).push(n);
}});
Object.entries(byRow).forEach(([r, ns]) => {{
  ns.forEach((n, i) => {{
    const total = ns.length, gapX = Math.max(80, Math.min(180, (W()-60)/total));
    n.fx = 30 + i * gapX + gapX/2;
    n.fy = START_Y + parseInt(r) * ROW_H;
  }});
}});

// Row labels
const rowNames = {{
  0:'Import/Experiment', 1:'Pipeline Steps', 2:'Edge Records',
  3:'Step Types', 4:'Categories', 5:'Variables',
  6:'Transform Properties', 7:'MLflow Groups', 8:'MLflow Values',
  9:'SQL Tables', 10:'SQL Columns', 11:'UI Details',
}};
Object.entries(byRow).forEach(([r, ns]) => {{
  if(!ns.length) return;
  const y = START_Y + parseInt(r)*ROW_H;
  g.append('text').attr('class','row-label').attr('x',8).attr('y',y-12).text(rowNames[r]||'');
  g.append('line').attr('x1',0).attr('x2',W()*3).attr('y1',y-20).attr('y2',y-20)
    .attr('stroke','rgba(255,255,255,0.03)').attr('stroke-width',1);
}});

const sim = d3.forceSimulation(NODES)
  .force('link', d3.forceLink(EDGES).id(d=>d.id).distance(90).strength(0.15))
  .force('charge', d3.forceManyBody().strength(-120))
  .force('x', d3.forceX(n => n.fx||W()/2).strength(n => n.fx ? 1 : 0.05))
  .force('y', d3.forceY(n => n.fy||H()/2).strength(n => n.fy ? 1 : 0.05))
  .alphaDecay(0.03);

// Links
const link = g.append('g').selectAll('line')
  .data(EDGES).join('line').attr('class','edge')
  .attr('stroke', d => COLOR[NBI[d.source.id||d.source]?.type] || '#333')
  .attr('stroke-width', d => d.type==='workflow_edge' ? 2 : 0.8)
  .attr('stroke-opacity', d => d.type==='workflow_edge' ? 0.9 : 0.35)
  .attr('marker-end', d => `url(#arr_${{NBI[d.source.id||d.source]?.type}})`);

// Nodes
const SZ = {{workflow_node:14, import:11, call:8, class:8, transformation_category:10,
             variable:7, parameter:5, function:9, argument:5, sql_table:9, sql_column:7, return_value:6}};

const nodeG = g.append('g').selectAll('g').data(NODES).join('g')
  .attr('class','node-shape')
  .call(d3.drag().on('start',dragStart).on('drag',dragged).on('end',dragEnd))
  .on('click', (ev, d) => {{ ev.stopPropagation(); highlight(d); showPanel(d); }});

// Shape per type
nodeG.each(function(d) {{
  const sel = d3.select(this), col = COLOR[d.type]||'#666', sz = SZ[d.type]||6;
  if (d.type === 'workflow_node')
    sel.append('rect').attr('x',-sz).attr('y',-sz).attr('width',sz*2).attr('height',sz*2)
      .attr('rx',3).attr('fill',col+'33').attr('stroke',col).attr('stroke-width',1.5);
  else if (['variable','sql_column'].includes(d.type))
    sel.append('polygon').attr('points',`0,${{-sz}} ${{sz}},0 0,${{sz}} ${{-sz}},0`)
      .attr('fill',col+'33').attr('stroke',col).attr('stroke-width',1);
  else if (['import','call'].includes(d.type))
    sel.append('circle').attr('r',sz).attr('fill',col+'33').attr('stroke',col).attr('stroke-width',1);
  else
    sel.append('rect').attr('x',-sz).attr('y',-sz/1.5).attr('width',sz*2).attr('height',sz*1.3)
      .attr('rx',2).attr('fill',col+'33').attr('stroke',col).attr('stroke-width',0.8);
}});

// Labels
nodeG.append('text').attr('class', d => 'nlabel' + (d.type==='workflow_node' ? ' wf' : ''))
  .attr('dy', d => (SZ[d.type]||6) + 11).attr('text-anchor','middle')
  .text(d => d._label.length > 22 ? d._label.slice(0,20)+'…' : d._label);

sim.on('tick', () => {{
  link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
      .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
  nodeG.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
}});

function dragStart(e,d){{ if(!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; }}
function dragged(e,d){{ d.fx=e.x; d.fy=e.y; }}
function dragEnd(e,d){{ if(!e.active) sim.alphaTarget(0); }}

// Highlight
function highlight(d) {{
  const connected = new Set([d.id]);
  EDGES.forEach(e => {{
    const s = e.source.id||e.source, t = e.target.id||e.target;
    if(s===d.id) connected.add(t);
    if(t===d.id) connected.add(s);
  }});
  nodeG.classed('dimmed', n => !connected.has(n.id));
  link.classed('dimmed', e => !connected.has(e.source.id||e.source) && !connected.has(e.target.id||e.target));
}}

svg.on('click', () => {{
  nodeG.classed('dimmed', false);
  link.classed('dimmed', false);
  document.getElementById('panel').classList.remove('open');
}});

// Side panel
function showPanel(d) {{
  const panel = document.getElementById('panel');
  const col = COLOR[d.type]||'#666';
  document.getElementById('panel-name').textContent = d._label;
  const badge = document.getElementById('panel-badge');
  badge.textContent = d.type.replace(/_/g,' ');
  badge.style.cssText = `background:${{col}}33;color:${{col}};border:1px solid ${{col}}44`;

  // Meta
  const skip = new Set(['id','type','_label']);
  const meta = Object.entries(d).filter(([k])=>!skip.has(k))
    .map(([k,v]) => `${{k}}: ${{v}}`).join('<br>');
  document.getElementById('panel-meta').innerHTML = meta || '';

  // Connected nodes
  const body = document.getElementById('panel-body');
  body.innerHTML = '';
  const byType = {{}};
  EDGES.forEach(e => {{
    const s = e.source.id||e.source, t = e.target.id||e.target;
    let peer = null, edgeType = e.type;
    if(s===d.id) peer = NBI[t];
    else if(t===d.id) peer = NBI[s];
    if(peer) {{
      (byType[edgeType]=byType[edgeType]||[]).push(peer);
    }}
  }});
  Object.entries(byType).forEach(([etype, peers]) => {{
    const title = document.createElement('div');
    title.className = 'psec-title'; title.textContent = etype.replace(/_/g,' ');
    body.appendChild(title);
    peers.forEach(peer => {{
      const item = document.createElement('div');
      item.className = 'pitem';
      const pcol = COLOR[peer.type]||'#666';
      item.innerHTML = `<div class="pdot" style="background:${{pcol}}"></div>${{peer._label}}<div class="pedge-type">${{peer.type.replace(/_/g,' ')}}</div>`;
      item.onclick = e => {{ e.stopPropagation(); highlight(peer); showPanel(peer); }};
      body.appendChild(item);
    }});
  }});

  panel.classList.add('open');
}}

// Initial zoom
setTimeout(() => {{
  svg.call(zoom.transform, d3.zoomIdentity.translate(40,10).scale(0.55));
}}, 300);
</script>
</body>
</html>
"""


def generate_html(data: dict, output_path: Path) -> None:
    nodes, edges = build_graph(data)
    nodes_json = json.dumps(nodes, ensure_ascii=False)
    edges_json = json.dumps(edges, ensure_ascii=False)
    html = HTML_TEMPLATE.format(nodes_json=nodes_json, edges_json=edges_json)
    output_path.write_text(html, encoding="utf-8")
    print(f"[OK] HTML saved  → {output_path}  ({len(nodes)} nodes, {len(edges)} edges)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate knowledge graph HTML from graph_info.py")
    ap.add_argument("--input",  default="graph_info.py",       help="JSON input file")
    ap.add_argument("--output", default="graph_knowledge.html",help="HTML output file")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise FileNotFoundError(f"Input not found: {src}")

    print(f"[..] Reading {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    print(f"[..] Nodes: {len(data['nodes'])}  |  Edges: {len(data['edges'])}")
    generate_html(data, Path(args.output))


if __name__ == "__main__":
    main()
