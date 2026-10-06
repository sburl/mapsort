#!/usr/bin/env python3
"""Build a self-contained HTML UI for reclassification review."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from payload_validation import REVIEW_TEMPLATE_REQUIRED_FIELDS, load_csv_rows
from settings import RECLASSIFICATION_REVIEW_UI_HTML

REQUIRED_COLUMNS = (
    "id",
    "name",
    "address",
    "category",
    "confidence",
    "reclassify_reasons",
    "decision_category",
    "decision_confidence",
    "notes",
)


def _load_template_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"template file not found: {path}")
    return load_csv_rows(
        path,
        f"template: {path}",
        required_fields=REVIEW_TEMPLATE_REQUIRED_FIELDS,
        strict=False,
    )


def _json_escape_rows(rows: list[dict[str, str]]) -> str:
    payload_rows = []
    for row in rows:
        payload_rows.append({key: row.get(key, "") for key in REQUIRED_COLUMNS})
    raw = json.dumps(payload_rows, ensure_ascii=False, separators=(",", ":"))
    # Prevent </script> injection when inlined in a <script> block
    return raw.replace("</", r"<\/")


def _build_html(rows: list[dict[str, str]], title: str) -> str:
    payload = _json_escape_rows(rows)
    confidence_options = ["", "high", "low", "error"]

    return f"""<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ --pad: 10px; --accent: #0b6dff; --muted: #5f6368; }}
    body {{ font-family: Inter, Arial, sans-serif; margin: 0; padding: 0; color: #111827; background: #f8fafc; }}
    main {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
    .toolbar {{ display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-bottom: 12px; }}
    .toolbar input, .toolbar button {{ padding: 8px 10px; }}
    table {{ width: 100%; border-collapse: collapse; background: white; }}
    th, td {{ border: 1px solid #e5e7eb; text-align: left; padding: 8px; vertical-align: top; }}
    th {{ background: #0f172a; color: white; position: sticky; top: 0; }}
    tr:hover td {{ background: #f1f5f9; }}
    .muted {{ color: var(--muted); font-size: 12px; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .actions button {{ margin-left: 8px; }}
  </style>
</head>
<body>
  <main>
    <h1>{html.escape(title)}</h1>
    <p class=\"muted\">Review queue generated from <strong>reclassify review template</strong>. Edit <em>Decision Category</em> and <em>Decision Confidence</em>, then export.</p>
    <div class=\"toolbar\">
      <input id=\"search\" placeholder=\"Search name, address, or reason\" />
      <button onclick=\"filterRows()\">Filter</button>
      <button onclick=\"resetFilters()\">Reset</button>
      <button onclick=\"selectUnreviewed()\">Select Unreviewed</button>
      <button onclick=\"clearDecision()\">Clear Selection</button>
      <button onclick=\"downloadCsv()\">Export decisions CSV</button>
    </div>
    <div id=\"summary\" class=\"muted\"></div>
    <table>
      <thead>
        <tr>
          <th>id</th>
          <th>name</th>
          <th>address</th>
          <th>category</th>
          <th>confidence</th>
          <th>reasons</th>
          <th>decision_category</th>
          <th>decision_confidence</th>
          <th>notes</th>
        </tr>
      </thead>
      <tbody id=\"rows\"></tbody>
    </table>
  </main>
  <script>
    const REVIEW_ROWS = {payload};
    const CONFIDENCE_OPTIONS = {confidence_options};
    let rows = [...REVIEW_ROWS];

    function escapeCsv(value) {{
      if (value === null || value === undefined) {{ return ''; }}
      const s = String(value);
      if (/[\",\n]/.test(s)) {{
        return '\"' + s.replace(/\"/g, '\"\"') + '\"';
      }}
      return s;
    }}

    function renderRows() {{
      const tbody = document.getElementById('rows');
      tbody.innerHTML = '';
      for (const row of rows) {{
        const tr = document.createElement('tr');
        const idTd = cell(row.id);
        const nameTd = cell(row.name);
        const addressTd = cell(row.address);
        const categoryTd = cell(row.category);
        const confidenceTd = cell(row.confidence);
        const reasonTd = cell(row.reclassify_reasons);
        const notesTd = cell(row.notes);

        const dcTd = document.createElement('td');
        const dcInput = document.createElement('input');
        dcInput.type = 'text';
        dcInput.value = row.decision_category || '';
        dcInput.oninput = (evt) => {{ row.decision_category = evt.target.value; updateSummary(); }};
        dcTd.appendChild(dcInput);

        const dconfTd = document.createElement('td');
        const dconfSelect = document.createElement('select');
        for (const option of CONFIDENCE_OPTIONS) {{
          const opt = document.createElement('option');
          opt.value = option;
          opt.textContent = option || '(unset)';
          if (row.decision_confidence === option) {{
            opt.selected = true;
          }}
          dconfSelect.appendChild(opt);
        }}
        dconfSelect.onchange = (evt) => {{ row.decision_confidence = evt.target.value; updateSummary(); }};
        dconfTd.appendChild(dconfSelect);

        tr.appendChild(idTd);
        tr.appendChild(nameTd);
        tr.appendChild(addressTd);
        tr.appendChild(categoryTd);
        tr.appendChild(confidenceTd);
        tr.appendChild(reasonTd);
        tr.appendChild(dcTd);
        tr.appendChild(dconfTd);
        tr.appendChild(notesTd);
        tbody.appendChild(tr);
      }}
      updateSummary();
    }}

    function updateSummary() {{
      const unreviewed = rows.filter((row) => !(row.decision_category || row.decision_confidence)).length;
      const reviewed = rows.length - unreviewed;
      document.getElementById('summary').textContent = `Rows: ${{rows.length}} | reviewed: ${{reviewed}} | unreviewed: ${{unreviewed}}`;
    }}

    function filterRows() {{
      const query = document.getElementById('search').value.trim().toLowerCase();
      const allRows = [...REVIEW_ROWS];
      if (!query) {{
        rows = allRows;
      }} else {{
        rows = allRows.filter((row) => {{
          const haystack = [row.id, row.name, row.address, row.reclassify_reasons].join(' ').toLowerCase();
          return haystack.includes(query);
        }});
      }}
      renderRows();
    }}

    function resetFilters() {{
      document.getElementById('search').value = '';
      rows = [...REVIEW_ROWS];
      renderRows();
    }}

    function selectUnreviewed() {{
      rows = REVIEW_ROWS.filter((row) => !(row.decision_category || row.decision_confidence));
      renderRows();
    }}

    function clearDecision() {{
      for (const row of REVIEW_ROWS) {{
        row.decision_category = '';
        row.decision_confidence = '';
      }}
      renderRows();
    }}

    function toCsv() {{
      const header = ['id','name','address','category','confidence','reclassify_reasons','decision_category','decision_confidence','notes'];
      const lines = [header.join(',')];
      for (const row of REVIEW_ROWS) {{
        const vals = [row.id, row.name, row.address, row.category, row.confidence, row.reclassify_reasons, row.decision_category, row.decision_confidence, row.notes];
        lines.push(vals.map(escapeCsv).join(','));
      }}
      return lines.join('\\n');
    }}

    function downloadCsv() {{
      const blob = new Blob([toCsv()], {{ type: 'text/csv;charset=utf-8;' }});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'reclassify_review_decisions.csv';
      a.click();
      URL.revokeObjectURL(url);
    }}

    function cell(value) {{
      const td = document.createElement('td');
      td.textContent = value || '';
      return td;
    }}

    document.getElementById('search').addEventListener('input', filterRows);
    renderRows();
  </script>
</body>
</html>
"""


def build_review_ui(template_path: Path, output_path: Path, *, title: str = "Reclassification Review UI") -> int:
    rows = _load_template_rows(template_path)
    # Keep all columns stable even if template misses columns.
    for row in rows:
        for key in REQUIRED_COLUMNS:
            row.setdefault(key, "")

    html_text = _build_html(rows, title=title)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return len(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a browser-review UI from a reclassify decision template."
    )
    parser.add_argument(
        "--template",
        required=True,
        help="Input review template CSV (e.g., reclassification_review_template.csv).",
    )
    parser.add_argument(
        "--output",
        default=str(RECLASSIFICATION_REVIEW_UI_HTML),
        help="Output HTML path (default: output/reclassification_review_ui.html).",
    )
    parser.add_argument(
        "--title",
        default="Reclassification Review UI",
        help="Page title and heading (default: Reclassification Review UI).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        count = build_review_ui(
            Path(args.template),
            Path(args.output),
            title=args.title,
        )
    except (FileNotFoundError, OSError, ValueError) as e:
        print(f"ERROR: {e}")
        return 2

    print(f"Built review UI ({count} rows) -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
