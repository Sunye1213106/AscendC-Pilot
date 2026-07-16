from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

if __package__ in (None, ""):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

from understand_operator._operator.artifacts import existing_operator_root, safe_op_name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render a local HTML viewer for Phase1 dual graphs.")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root")
    parser.add_argument("--op-name", help="Operator name")
    args = parser.parse_args(argv)

    if yaml is None:
        print("PyYAML is required", file=sys.stderr)
        return 2
    repo_root = Path(args.repo).resolve()
    op_name = safe_op_name(args.op_name, repo_root)
    uo_root = existing_operator_root(repo_root, op_name)
    graph_dir = uo_root / "graph"
    host = _read_yaml(graph_dir / "host_tiling_graph.yaml")
    kernel = _read_yaml(graph_dir / "kernel_execution_graph.yaml")
    comparison = _read_yaml(graph_dir / "graph_comparison.yaml")
    issues = _read_yaml(graph_dir / "graph_issues.yaml")
    if not host or not kernel:
        print(f"Missing Phase1 graph YAML under {graph_dir}", file=sys.stderr)
        return 2

    payload = {
        "op_name": op_name,
        "project_root": str(repo_root).replace("\\", "/"),
        "host": _graph_payload(host),
        "kernel": _graph_payload(kernel),
        "comparison": comparison,
        "issues": issues.get("issues") or [],
        "source_graph": host.get("source_graph") or kernel.get("source_graph") or {},
    }
    out = graph_dir / "phase1_graph_view.html"
    out.write_text(_render_html(payload), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _graph_payload(graph: dict[str, Any]) -> dict[str, Any]:
    raw_roots = {str(item) for item in graph.get("roots") or []}
    raw_sinks = {str(item) for item in graph.get("sinks") or []}
    nodes = []
    roots: list[str] = []
    sinks: list[str] = []
    for node in graph.get("nodes") or []:
        semantic_id = str(node.get("id") or "")
        source_nodes = [str(item) for item in node.get("source_nodes") or []]
        if any(item in raw_roots for item in source_nodes):
            roots.append(semantic_id)
        if any(item in raw_sinks for item in source_nodes):
            sinks.append(semantic_id)
        nodes.append(
            {
                "id": semantic_id,
                "label": str(node.get("label") or node.get("semantic_type") or ""),
                "semantic_type": str(node.get("semantic_type") or "unknown"),
                "path": str((node.get("source_locator") or {}).get("path") or ""),
                "lines": str((node.get("source_locator") or {}).get("lines") or ""),
                "symbol": str((node.get("source_locator") or {}).get("symbol") or ""),
                "path_membership": list(node.get("path_membership") or []),
                "source_nodes": source_nodes,
            }
        )
    edges = [
        {
            "id": str(edge.get("id") or ""),
            "source": str(edge.get("source") or ""),
            "target": str(edge.get("target") or ""),
            "relation": str(edge.get("relation") or "relates_to"),
            "origin": str(edge.get("edge_origin") or ""),
            "path_membership": list(edge.get("path_membership") or []),
        }
        for edge in graph.get("edges") or []
    ]
    return {
        "graph_type": str(graph.get("graph_type") or ""),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "roots": roots,
        "sinks": sinks,
        "nodes": nodes,
        "edges": edges,
    }


def _render_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{payload["op_name"]} Phase1 双子图</title>
  <script src="https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
  <script src="https://unpkg.com/dagre@0.8.5/dist/dagre.min.js"></script>
  <script src="https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js"></script>
  <style>
    :root {{
      --bg: #f5f1e8;
      --panel: #fffaf2;
      --panel-strong: #fff;
      --ink: #1f2937;
      --muted: #6b7280;
      --line: #d6c7af;
      --accent: #c2410c;
      --accent-2: #0369a1;
      --accent-3: #166534;
      --shadow: 0 10px 30px rgba(80, 55, 20, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(194,65,12,0.08), transparent 30%),
        radial-gradient(circle at top right, rgba(3,105,161,0.1), transparent 28%),
        linear-gradient(180deg, #fbf7f1, var(--bg));
    }}
    .app {{
      display: grid;
      grid-template-columns: 360px 1fr;
      min-height: 100vh;
      gap: 16px;
      padding: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }}
    .sidebar {{
      padding: 18px;
      display: flex;
      flex-direction: column;
      gap: 16px;
      overflow: auto;
    }}
    .main {{
      display: grid;
      grid-template-rows: auto 1fr;
      gap: 16px;
      min-width: 0;
    }}
    .header {{
      padding: 18px;
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: flex-start;
    }}
    h1, h2, h3, p {{ margin: 0; }}
    h1 {{ font-size: 24px; }}
    h2 {{ font-size: 15px; margin-bottom: 10px; }}
    .muted {{ color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .stat {{
      padding: 12px;
      background: var(--panel-strong);
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    .stat strong {{
      display: block;
      font-size: 20px;
      margin-bottom: 4px;
    }}
    .tabs {{
      display: inline-flex;
      gap: 8px;
      background: rgba(214,199,175,0.35);
      padding: 6px;
      border-radius: 8px;
    }}
    .tab {{
      border: 0;
      background: transparent;
      color: var(--ink);
      padding: 10px 14px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
    }}
    .tab.active {{
      background: var(--panel-strong);
      box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    }}
    .toolbar {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    input, select, button {{
      font: inherit;
      border-radius: 6px;
      border: 1px solid var(--line);
      padding: 9px 10px;
      background: var(--panel-strong);
      color: var(--ink);
    }}
    button {{
      cursor: pointer;
    }}
    button.primary {{
      background: var(--accent);
      color: #fff;
      border-color: var(--accent);
    }}
    .canvas-wrap {{
      min-height: 0;
      padding: 0;
      overflow: hidden;
    }}
    .canvas {{
      width: 100%;
      height: calc(100vh - 140px);
      min-height: 640px;
      border-radius: 8px;
      background:
        linear-gradient(90deg, rgba(214,199,175,0.14) 1px, transparent 1px),
        linear-gradient(0deg, rgba(214,199,175,0.14) 1px, transparent 1px),
        #fffdf9;
      background-size: 24px 24px;
    }}
    .list {{
      display: grid;
      gap: 8px;
      max-height: 220px;
      overflow: auto;
    }}
    .chip {{
      display: inline-flex;
      align-items: center;
      padding: 5px 8px;
      border-radius: 999px;
      font-size: 12px;
      margin: 0 6px 6px 0;
      background: #f1e5d4;
      border: 1px solid #e5caa7;
    }}
    .issue {{
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid #efc9b3;
      background: #fff1e8;
      font-size: 13px;
      line-height: 1.45;
    }}
    .node-card {{
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel-strong);
      font-size: 13px;
      line-height: 1.45;
    }}
    .node-card strong {{
      display: block;
      margin-bottom: 4px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    a.buttonlike {{
      text-decoration: none;
      color: var(--ink);
      border: 1px solid var(--line);
      background: var(--panel-strong);
      padding: 9px 10px;
      border-radius: 6px;
    }}
    @media (max-width: 1100px) {{
      .app {{
        grid-template-columns: 1fr;
      }}
      .canvas {{
        height: 70vh;
        min-height: 520px;
      }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside class="panel sidebar">
      <div>
        <h1>{payload["op_name"]}</h1>
        <p class="muted">Phase1 双子图可视化。数据来自裁剪后的 `host_tiling_graph.yaml` 与 `kernel_execution_graph.yaml`，并保留当前 CBM 项目与数据库信息。</p>
      </div>
      <div class="stats">
        <div class="stat"><strong id="rawNodes">-</strong><span class="muted">原始候选节点</span></div>
        <div class="stat"><strong id="rawEdges">-</strong><span class="muted">原始候选边</span></div>
        <div class="stat"><strong id="graphNodes">-</strong><span class="muted">当前图节点</span></div>
        <div class="stat"><strong id="graphEdges">-</strong><span class="muted">当前图边</span></div>
      </div>
      <div>
        <h2>CBM 信息</h2>
        <p class="muted" id="cbmInfo"></p>
      </div>
      <div>
        <h2>问题与降级</h2>
        <div class="list" id="issues"></div>
      </div>
      <div>
        <h2>当前图语义类型</h2>
        <div id="semanticLegend"></div>
      </div>
      <div>
        <h2>选中节点</h2>
        <div class="list" id="selection"><div class="muted">点击图中的节点后，这里会显示路径、语义类型和来源位置。</div></div>
      </div>
    </aside>
    <main class="main">
      <section class="panel header">
        <div>
          <div class="tabs">
            <button class="tab active" data-tab="host">Host / Tiling 子图</button>
            <button class="tab" data-tab="kernel">Kernel 执行子图</button>
          </div>
          <p class="muted" id="graphHint" style="margin-top:10px;"></p>
        </div>
        <div class="toolbar">
          <input id="search" type="text" placeholder="搜索 label / symbol / path">
          <select id="semanticFilter">
            <option value="">全部语义类型</option>
          </select>
          <button id="fitBtn">适配视图</button>
          <button id="rootsBtn">只高亮 roots</button>
          <button id="clearBtn">清除高亮</button>
        </div>
      </section>
      <section class="panel canvas-wrap">
        <div id="cy" class="canvas"></div>
      </section>
    </main>
  </div>
  <script>
    const payload = {data};
    cytoscape.use(cytoscapeDagre);

    const colorBySemantic = {{
      input: "#0369a1",
      optional_input: "#0f766e",
      attribute: "#b45309",
      platform_property: "#7c3aed",
      tiling_key: "#c2410c",
      tiling_data: "#166534",
      tiling_data_field: "#15803d",
      tiling_data_write: "#15803d",
      block_dim: "#9a3412",
      workspace: "#be123c",
      kernel_dispatch: "#1d4ed8",
      kernel_entry: "#4338ca",
      output: "#0f766e",
      copy_in: "#0284c7",
      copy_out: "#0d9488",
      compute: "#7c2d12",
      predicate: "#6d28d9",
      derived_variable: "#475569",
      kernel_variable: "#334155",
      function: "#64748b",
      kernel_function: "#64748b"
    }};

    const state = {{
      current: "host",
      mode: "",
      cy: null
    }};

    function currentGraph() {{
      return state.current === "host" ? payload.host : payload.kernel;
    }}

    function semanticColor(kind) {{
      return colorBySemantic[kind] || "#6b7280";
    }}

    function elementsFor(graph) {{
      const nodeSet = new Set();
      const nodes = graph.nodes.map((node) => {{
        nodeSet.add(node.id);
        return {{
          data: {{
            id: node.id,
            label: node.label,
            semantic_type: node.semantic_type,
            path: node.path,
            lines: node.lines,
            symbol: node.symbol,
            path_membership: node.path_membership || [],
            is_root: graph.roots.includes(node.source_nodes?.[0]) || graph.roots.includes(node.id),
            is_sink: graph.sinks.includes(node.source_nodes?.[0]) || graph.sinks.includes(node.id)
          }}
        }};
      }});
      const edges = graph.edges
        .filter((edge) => nodeSet.has(edge.source) && nodeSet.has(edge.target))
        .map((edge) => ({{
          data: {{
            id: edge.id,
            source: edge.source,
            target: edge.target,
            relation: edge.relation,
            origin: edge.origin,
            path_membership: edge.path_membership || []
          }}
        }}));
      return nodes.concat(edges);
    }}

    function renderGraph() {{
      const graph = currentGraph();
      document.getElementById("graphHint").textContent =
        `${{graph.graph_type}} | nodes=${{graph.node_count}} | edges=${{graph.edge_count}}`;
      document.getElementById("graphNodes").textContent = graph.node_count;
      document.getElementById("graphEdges").textContent = graph.edge_count;
      document.getElementById("rawNodes").textContent = payload.comparison.raw_candidate_graph.nodes;
      document.getElementById("rawEdges").textContent = payload.comparison.raw_candidate_graph.edges;

      const semanticTypes = Array.from(new Set(graph.nodes.map((n) => n.semantic_type))).sort();
      const filter = document.getElementById("semanticFilter");
      const prev = filter.value;
      filter.innerHTML = '<option value="">全部语义类型</option>' +
        semanticTypes.map((kind) => `<option value="${{kind}}">${{kind}}</option>`).join("");
      filter.value = semanticTypes.includes(prev) ? prev : "";

      if (state.cy) {{
        state.cy.destroy();
      }}
      state.cy = cytoscape({{
        container: document.getElementById("cy"),
        elements: elementsFor(graph),
        layout: {{
          name: "dagre",
          rankDir: state.current === "host" ? "LR" : "TB",
          nodeSep: 36,
          edgeSep: 12,
          rankSep: 70
        }},
        style: [
          {{
            selector: "node",
            style: {{
              "background-color": (ele) => semanticColor(ele.data("semantic_type")),
              "label": "data(label)",
              "color": "#111827",
              "font-size": 10,
              "text-wrap": "wrap",
              "text-max-width": 90,
              "text-valign": "center",
              "text-halign": "center",
              "width": 34,
              "height": 34,
              "border-width": 2,
              "border-color": "#fff7ed"
            }}
          }},
          {{
            selector: "edge",
            style: {{
              "curve-style": "bezier",
              "width": 1.4,
              "line-color": "#94a3b8",
              "target-arrow-color": "#94a3b8",
              "target-arrow-shape": "triangle",
              "arrow-scale": 0.8
            }}
          }},
          {{
            selector: ".dim",
            style: {{
              "opacity": 0.12
            }}
          }},
          {{
            selector: ".focus",
            style: {{
              "opacity": 1,
              "border-color": "#111827",
              "border-width": 3
            }}
          }},
          {{
            selector: ".root",
            style: {{
              "shape": "round-rectangle"
            }}
          }},
          {{
            selector: ".sink",
            style: {{
              "shape": "diamond"
            }}
          }}
        ]
      }});

      state.cy.nodes().forEach((node) => {{
        if (graph.roots.includes(node.id())) node.addClass("root");
        if (graph.sinks.includes(node.id())) node.addClass("sink");
      }});

      state.cy.on("tap", "node", (evt) => {{
        highlightNeighborhood(evt.target);
        renderSelection(evt.target.data());
      }});

      state.cy.fit(undefined, 30);
      renderLegend(semanticTypes);
    }}

    function renderLegend(semanticTypes) {{
      const host = semanticTypes.map((kind) =>
        `<span class="chip" style="border-color:${{semanticColor(kind)}}33;background:${{semanticColor(kind)}}14;">${{kind}}</span>`
      ).join("");
      document.getElementById("semanticLegend").innerHTML = host || '<span class="muted">无</span>';
    }}

    function renderSelection(data) {{
      const root = document.getElementById("selection");
      root.innerHTML = `
        <div class="node-card">
          <strong>${{data.label}}</strong>
          <div>semantic_type: ${{data.semantic_type}}</div>
          <div>symbol: ${{data.symbol || "-"}}</div>
          <div>path: ${{data.path || "-"}}</div>
          <div>lines: ${{data.lines || "-"}}</div>
        </div>
      `;
    }}

    function highlightNeighborhood(node) {{
      const neighborhood = node.closedNeighborhood().union(node.predecessors()).union(node.successors());
      state.cy.elements().addClass("dim").removeClass("focus");
      neighborhood.removeClass("dim").addClass("focus");
    }}

    function clearHighlight() {{
      state.cy.elements().removeClass("dim").removeClass("focus");
    }}

    function filterGraph() {{
      const q = document.getElementById("search").value.trim().toLowerCase();
      const semantic = document.getElementById("semanticFilter").value;
      state.cy.elements().removeClass("dim");
      state.cy.nodes().forEach((node) => {{
        const hitText = [node.data("label"), node.data("symbol"), node.data("path")].join(" ").toLowerCase();
        const textOk = !q || hitText.includes(q);
        const semanticOk = !semantic || node.data("semantic_type") === semantic;
        if (!textOk || !semanticOk) {{
          node.addClass("dim");
          node.connectedEdges().addClass("dim");
        }}
      }});
    }}

    function showRootsOnly() {{
      clearHighlight();
      state.cy.elements().addClass("dim");
      currentGraph().roots.forEach((id) => {{
        const node = state.cy.getElementById(id);
        node.removeClass("dim").addClass("focus");
        node.connectedEdges().removeClass("dim");
      }});
    }}

    function bindUi() {{
      document.querySelectorAll(".tab").forEach((button) => {{
        button.addEventListener("click", () => {{
          document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
          button.classList.add("active");
          state.current = button.dataset.tab;
          renderGraph();
        }});
      }});
      document.getElementById("search").addEventListener("input", filterGraph);
      document.getElementById("semanticFilter").addEventListener("change", filterGraph);
      document.getElementById("fitBtn").addEventListener("click", () => state.cy.fit(undefined, 30));
      document.getElementById("clearBtn").addEventListener("click", clearHighlight);
      document.getElementById("rootsBtn").addEventListener("click", showRootsOnly);
    }}

    function renderMeta() {{
      const source = payload.source_graph || {{}};
      document.getElementById("cbmInfo").innerHTML = [
        `project: ${{source.cbm_project || "-"}}`,
        `db: ${{source.db_path || "-"}}`,
        `selection: ${{source.selection || "-"}}`,
        source.edge_read_fallback ? `edge fallback: ${{source.edge_read_fallback}}` : ""
      ].filter(Boolean).join("<br>");
      const issues = payload.issues || [];
      document.getElementById("issues").innerHTML = issues.length
        ? issues.map((item) => `<div class="issue"><strong>${{item.issue}}</strong><br>${{item.reason || ""}}<br>${{item.action || ""}}</div>`).join("")
        : '<div class="muted">无额外问题</div>';
    }}

    bindUi();
    renderMeta();
    renderGraph();
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    raise SystemExit(main())
