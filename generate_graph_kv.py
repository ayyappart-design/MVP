"""
generate_graph_kv.py
────────────────────────────────────────────────────────────────────
Reads  : graph_info.py  (JSON pipeline definition)
Writes : graph_kv.xlsx  (6-column flat key-value mapping)

Column contract  (matches graph_kv_fixed.xlsx exactly)
───────────────────────────────────────────────────────
  NODE        | NODE TYPE   | edge             | edge type                  | NODE B (VALUE)  | NODE TYPE B
  field_name  | node        | field_name       | node                       | value           | field_name
  field_name  | node_details| field_name       | node_details               | value           | field_name
  prop_name   | node_type   | prop_name        | transformation_properties  | prop_name       | property_name
  prop_name   | node_type   | prop_name        | transformation_properties  | prop_value      | property_value
  mlflow_grp  | node_type   | mlflow_grp       | mlflow_tracking_properties | mlflow_grp      | property_name
  mlflow_grp  | node_type   | mlflow_grp       | mlflow_tracking_properties | each_param      | property_value
  edge_id     | edge        | edge_field       | edge                       | edge_val        | edge_field
  edge_id     | edge_type   | sourceHandle     | ui_details                 | None            | sourceHandle

  IMPORTANT: comma-separated values (e.g. "columns" field) → one row each

Usage
─────
  pip install openpyxl
  python generate_graph_kv.py --input graph_info.py --output graph_kv.xlsx
"""

from __future__ import annotations
import json, argparse
from pathlib import Path
from typing import Any, NamedTuple
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# ── Data model ───────────────────────────────────────────────────────────────

class Row(NamedTuple):
    node:        Any
    node_type:   str
    edge:        Any
    edge_type:   Any
    node_b:      Any
    node_type_b: Any


# ── Value helpers ─────────────────────────────────────────────────────────────

def _to_str(v: Any) -> str | None:
    if v is None: return None
    s = str(v).strip()
    return s if s else None

def _split_columns(raw: str) -> list[str]:
    """
    Split a comma-separated string into individual clean values.
    Handles both quoted:   "'name', 'manufacturer_name'"  → ["name", "manufacturer_name"]
    And plain:             "True,False"                   → ["True", "False"]
    """
    parts = [p.strip().strip("'\"") for p in raw.split(",")]
    return [p for p in parts if p]   # drop empty strings

def _is_column_list(raw: str) -> bool:
    """
    Detect any comma-separated list that should be split into individual rows.
    Covers:
      - Quoted column lists  : "'name', 'manufacturer_name'"
      - Plain comma-separated: "True,False"
    Excludes JSON arrays (starts with '[') — those are handled by json.loads().
    """
    if raw.startswith("["):          # JSON array → handled separately
        return False
    return "," in raw               # any comma → split it


# ── Row extraction ────────────────────────────────────────────────────────────

def extract_rows(data: dict) -> list[Row]:
    rows: list[Row] = []

    # ── ROOT ─────────────────────────────────────────────────────────────────
    rows.append(Row(
        "experiment_id", "node",
        "experiment_id", "root",
        data["experiment_id"], "experiment_id",
    ))

    # ── NODES ─────────────────────────────────────────────────────────────────
    for node in data["nodes"]:
        nd = node["node_details"]

        # node-level keys  →  node_type = "node"
        for f in ("id","type","transformation_type","transformation_name",
                  "status","connection_type","transformation_category"):
            rows.append(Row(f, "node", f, "node", _to_str(node[f]), f))

        # node_details keys  →  node_type = "node_details"
        for f in ("experiment_id","type","transformation_type","transformation_name",
                  "status","transformation_category","node_count","node_id","description"):
            val = nd[f]
            if f == "description" and not str(val or "").strip():
                val = "(empty)"
            rows.append(Row(f, "node_details", f, "node_details", _to_str(val), f))

        # transformation_properties  →  node_type = "node_type"
        for prop in nd["transformation_properties"]:
            pname = prop["property_name"]
            pval  = prop["property_value"]

            # property_name row
            rows.append(Row(pname, "node_type", pname,
                            "transformation_properties", pname, "property_name"))

            # property_value row(s): split comma-separated lists into individual rows
            raw = str(pval) if pval is not None else ""
            if _is_column_list(raw):
                for item in _split_columns(raw):
                    rows.append(Row(pname, "node_type", pname,
                                    "transformation_properties", item, "property_value"))
            else:
                rows.append(Row(pname, "node_type", pname,
                                "transformation_properties", _to_str(pval), "property_value"))

        # mlflow_tracking_properties  →  node_type = "node_type"
        for mlf in nd["mlflow_tracking_properties"]:
            grp    = mlf["property_name"]
            params = json.loads(mlf["property_value"])   # JSON array

            # group name row  (property_name echo)
            rows.append(Row(grp, "node_type", grp,
                            "mlflow_tracking_properties", grp, "property_name"))

            # one row per param  (each exploded individually)
            for param in params:
                rows.append(Row(grp, "node_type", grp,
                                "mlflow_tracking_properties", param, "property_value"))

    # ── EDGES ─────────────────────────────────────────────────────────────────
    node_name_map = {n["id"]: n["transformation_name"] for n in data["nodes"]}

    for edge in data["edges"]:
        eid      = edge["id"]
        src_name = node_name_map.get(edge["source_node_id"], edge["source_node_id"])
        tgt_name = node_name_map.get(edge["target_node_id"], edge["target_node_id"])

        # edge identity fields  →  node_type = "edge"
        for field, val in (
            ("id",                  eid),
            ("source_node_id",      edge["source_node_id"]),
            ("source_node_name",    src_name),
            ("target_node_id",      edge["target_node_id"]),
            ("target_node_name",    tgt_name),
            ("transformation_type", edge["transformation_type"]),
        ):
            rows.append(Row(eid, "edge", field, "edge", _to_str(val), field))

        # ui_details  →  node_type = "edge_type"
        for field in ("sourceHandle", "targetHandle"):
            rows.append(Row(eid, "edge_type", field, "ui_details",
                            _to_str(edge["ui_details"][field]), field))

    return rows


# ── Styling ───────────────────────────────────────────────────────────────────

_THIN   = Side(style="thin", color="C8D0DC")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

_PALETTE = {
    "root":         ("0D3B66","D0E4F7","EAF3FB"),
    "node":         ("1A4A8A","D6E8FA","EBF3FB"),
    "node_details": ("145A32","D5F0E3","EBF8F2"),
    "node_type":    ("7D6608","FEF3CD","FEF9E7"),
    "edge":         ("7B241C","FADBD8","FDEDEC"),
    "edge_type":    ("4D4D4D","EBEBEB","F5F5F5"),
}

_COLS = [
    ("NODE",          36), ("NODE TYPE",   16),
    ("edge",          30), ("edge type",   30),
    ("NODE B (VALUE)",50), ("NODE TYPE B", 26),
]

def _fill(c):  return PatternFill("solid", start_color=c, fgColor=c)
def _font(bold=False, italic=False, size=9, color="000000"):
    return Font(name="Arial", bold=bold, italic=italic, size=size, color=color)
def _al(h="left", wrap=False):
    return Alignment(horizontal=h, vertical="center", wrap_text=wrap)


# ── Excel writer ──────────────────────────────────────────────────────────────

def write_excel(rows: list[Row], output_path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Graph KV"
    ws.sheet_view.showGridLines = False

    # Banner
    last = get_column_letter(len(_COLS))
    ws.merge_cells(f"A1:{last}1")
    b = ws["A1"]
    b.value     = f"graph_info.py  —  KV Mapping  ({len(rows)} rows)"
    b.font      = _font(bold=True, size=11, color="FFFFFF")
    b.fill      = _fill("0D1B2A")
    b.alignment = _al("left")
    ws.row_dimensions[1].height = 26

    # Header row
    ws.row_dimensions[2].height = 22
    for i, (label, width) in enumerate(_COLS, 1):
        c = ws.cell(row=2, column=i, value=label)
        c.font      = _font(bold=True, size=10, color="FFFFFF")
        c.fill      = _fill("1F3864")
        c.alignment = _al("center")
        c.border    = _BORDER
        ws.column_dimensions[get_column_letter(i)].width = width

    er = 3
    prev_node_name  = None   # track current node for node-name dividers
    prev_edge_id    = None   # track current edge_id for edge dividers

    for row in rows:
        badge, even_bg, odd_bg = _PALETTE.get(row.node_type, ("555555","F5F5F5","FFFFFF"))

        # ── Per-node divider (node / node_details / node_type sections) ───
        if row.node_type in ("node", "node_details", "node_type"):
            # Determine the node name from node_b when field=transformation_name
            if row.edge == "transformation_name" and row.node_type == "node":
                node_name = row.node_b
                if node_name != prev_node_name:
                    ws.merge_cells(f"A{er}:{last}{er}")
                    d = ws.cell(row=er, column=1, value=f"  ▶  {node_name}")
                    d.font      = _font(bold=True, size=10, color="FFFFFF")
                    d.fill      = _fill("1A4A8A")
                    d.alignment = _al("left")
                    ws.row_dimensions[er].height = 17
                    er += 1
                    prev_node_name = node_name

        # ── Per-edge divider ───────────────────────────────────────────────
        elif row.node_type == "edge":
            if row.node != prev_edge_id:
                ws.merge_cells(f"A{er}:{last}{er}")
                d = ws.cell(row=er, column=1,
                            value=f"  ▶  NODE TYPE = EDGE")
                d.font      = _font(bold=True, size=10, color="FFFFFF")
                d.fill      = _fill("7B241C")
                d.alignment = _al("left")
                ws.row_dimensions[er].height = 17
                er += 1
                prev_edge_id = row.node

        elif row.node_type == "edge_type":
            # edge_type divider: emit once per edge switch
            if row.node != prev_edge_id:
                ws.merge_cells(f"A{er}:{last}{er}")
                d = ws.cell(row=er, column=1,
                            value=f"  ▶  NODE TYPE = EDGE_TYPE")
                d.font      = _font(bold=True, size=10, color="FFFFFF")
                d.fill      = _fill("4D4D4D")
                d.alignment = _al("left")
                ws.row_dimensions[er].height = 17
                er += 1
                prev_edge_id = row.node

        # ── Data row ───────────────────────────────────────────────────────
        ws.row_dimensions[er].height = 15
        bg = even_bg if er % 2 == 0 else odd_bg

        for ci, val in enumerate(row, 1):
            c = ws.cell(row=er, column=ci,
                        value=val if str(val) not in ("None","null","") else None)
            c.border = _BORDER
            if ci == 2:   # NODE TYPE badge
                c.font = _font(bold=True, size=8, color="FFFFFF"); c.fill = _fill(badge); c.alignment = _al("center")
            elif ci == 4: # edge type badge
                c.font = _font(bold=True, size=8, color="FFFFFF"); c.fill = _fill(badge); c.alignment = _al("center")
            elif ci == 5: # NODE B value — bold
                c.font = _font(bold=True, size=9); c.fill = _fill("FFFFFF" if er%2==0 else "FAFAFA"); c.alignment = _al(wrap=True)
            elif ci == 6: # NODE TYPE B — italic grey
                c.font = _font(italic=True, size=8, color="666666"); c.fill = _fill("F0F0F0" if er%2==0 else "F8F8F8"); c.alignment = _al("center")
            else:
                c.font = _font(size=9); c.fill = _fill(bg); c.alignment = _al()

        er += 1

    ws.freeze_panes  = "A3"
    ws.auto_filter.ref = f"A2:{last}2"
    ws.sheet_properties.tabColor = "1F3864"
    wb.save(output_path)
    print(f"[OK] Saved → {output_path}  ({len(rows)} rows)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",  default="graph_info.py",  help="JSON source file")
    ap.add_argument("--output", default="graph_kv.xlsx",  help="Output Excel file")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        raise FileNotFoundError(src)

    print(f"[..] Reading {src}")
    data = json.loads(src.read_text(encoding="utf-8"))
    print(f"[..] {len(data['nodes'])} nodes  |  {len(data['edges'])} edges")

    rows = extract_rows(data)
    print(f"[..] {len(rows)} rows extracted")

    write_excel(rows, Path(args.output))


if __name__ == "__main__":
    main()
