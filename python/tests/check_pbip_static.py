"""Static checks for the Power BI project (.pbip) (no Power BI needed).

    ./.venv/Scripts/python.exe python/tests/check_pbip_static.py

Checks: every JSON file parses; TMDL uses tab indentation; every table/column/measure/hierarchy
level referenced by a report visual or drillthrough filter exists in the TMDL model; every [Measure]
referenced inside DAX exists; relationships point at real columns. It does NOT prove Power BI Desktop
will open the project (that needs Desktop) - see docs for what remains NOT TESTED.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / 'PowerBi'
MODEL = ROOT / 'FinancialIntelligence.SemanticModel' / 'definition'
REPORT = ROOT / 'FinancialIntelligence.Report'
fails: list[str] = []
passes = 0


def ok(cond: bool, msg: str) -> None:
    global passes
    if cond:
        passes += 1
    else:
        fails.append(msg)
        print('FAIL', msg)


def unq(name: str) -> str:
    return name[1:-1].replace("''", "'") if name.startswith("'") else name


# ---- parse TMDL (enough structure for reference checks) ----
tables: dict[str, dict] = {}
for f in sorted((MODEL / 'tables').glob('*.tmdl')):
    text = f.read_text(encoding='utf-8')
    ok(not re.search(r'(?m)^ +\S', text), f'{f.name}: space-indented line (TMDL needs tabs)')
    t = re.search(r'(?m)^table (.+)$', text).group(1).strip()
    cols = {unq(m.group(1).strip()) for m in re.finditer(r"(?m)^\tcolumn ('(?:[^']|'')+'|\S+)", text)}
    meas = {unq(m.group(1).strip()) for m in re.finditer(r"(?m)^\tmeasure ('(?:[^']|'')+'|\S+)", text)}
    levels = {}
    for h in re.finditer(r"(?m)^\thierarchy ('(?:[^']|'')+'|\S+)\n((?:\t\t.*\n|\n)+)", text):
        levels[unq(h.group(1))] = {m.group(1).strip() for m in re.finditer(r'(?m)^\t\tlevel (.+)$', h.group(2))}
        for c in re.finditer(r'(?m)^\t\t\tcolumn: (.+)$', h.group(2)):
            ok(unq(c.group(1).strip()) in cols, f'{t}: hierarchy column {c.group(1)} missing')
    for s in re.finditer(r'(?m)^\t\tsortByColumn: (.+)$', text):
        ok(unq(s.group(1).strip()) in cols, f'{t}: sortByColumn {s.group(1)} missing')
    dax_text = text.split('\tpartition ')[0]     # partitions hold Power Query M, not DAX
    tables[t] = {'columns': cols, 'measures': meas, 'hierarchies': levels, 'text': dax_text}
all_measures = {m for t in tables.values() for m in t['measures']}

# Power BI Desktop refuses reserved table names, e.g. "Unsupported Table name "Measures" has been found
# in data model schema." ('Measures' is an MDX keyword.)
RESERVED_TABLE_NAMES = {'measures'}
for t in tables:
    ok(t.lower() not in RESERVED_TABLE_NAMES, f'table name "{t}" is reserved in Power BI')
print(f'Model: {len(tables)} tables, {len(all_measures)} measures')

# ---- '///' becomes the next object's `description`; only some TOM objects have one ----
# (Power BI Desktop error otherwise: "Property 'description' is unknown and is not expected ...")
DESCRIBABLE = {'table', 'column', 'measure', 'expression', 'hierarchy', 'level', 'partition'}
for f in sorted(MODEL.rglob('*.tmdl')):
    lines = f.read_text(encoding='utf-8').splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith('///'):
            nxt = next((l for l in lines[i + 1:] if not l.lstrip().startswith('///')), '')
            kw = nxt.strip().split(' ')[0] if nxt.strip() else '<end of file>'
            ok(kw in DESCRIBABLE, f'{f.name}:{i + 1}: /// description before "{kw}", which has no description property')

model_refs = set(re.findall(r'(?m)^ref table (.+)$', (MODEL / 'model.tmdl').read_text(encoding='utf-8')))
ok(model_refs == set(tables), f'model.tmdl ref tables {model_refs} != table files {set(tables)}')

# ---- relationships ----
for m in re.finditer(r'(?m)^\t(fromColumn|toColumn): (\w+)\.(\w+)$', (MODEL / 'relationships.tmdl').read_text(encoding='utf-8')):
    ok(m.group(2) in tables and m.group(3) in tables[m.group(2)]['columns'], f'relationship column {m.group(2)}.{m.group(3)} missing')

# ---- DAX references inside measures / calculated columns ----
for tname, t in tables.items():
    for ref in re.findall(r"(?<![\w'\]])\[([^\]]+)\]", t['text']):
        if ref == 'Value':      # calculated-table sourceColumn
            continue
        ok(ref in all_measures or ref in t['columns'], f'{tname}: DAX reference [{ref}] is not a measure/column')
    for tbl, c in re.findall(r"\b(\w+)\[([^\]]+)\]", t['text']):
        if tbl in tables:
            ok(c in tables[tbl]['columns'], f'{tname}: DAX reference {tbl}[{c}] missing')

# ---- report JSON ----
def walk(node):
    if isinstance(node, dict):
        if 'Measure' in node and 'Property' in node['Measure']:
            e = node['Measure']['Expression']['SourceRef']['Entity']
            ok(e in tables and node['Measure']['Property'] in tables[e]['measures'], f"measure {e}.{node['Measure']['Property']} missing")
        if 'Column' in node and 'Property' in node['Column']:
            e = node['Column']['Expression']['SourceRef']['Entity']
            ok(e in tables and node['Column']['Property'] in tables[e]['columns'], f"column {e}.{node['Column']['Property']} missing")
        if 'HierarchyLevel' in node:
            h = node['HierarchyLevel']['Expression']['Hierarchy']
            e = h['Expression']['SourceRef']['Entity']
            ok(e in tables and node['HierarchyLevel']['Level'] in tables[e]['hierarchies'].get(h['Hierarchy'], set()),
               f"hierarchy level {e}.{h['Hierarchy']}.{node['HierarchyLevel']['Level']} missing")
        for v in node.values():
            walk(v)
    elif isinstance(node, list):
        for v in node:
            walk(v)


json_files = list(REPORT.rglob('*.json')) + list(REPORT.rglob('*.pbir')) + list(REPORT.rglob('.platform')) + \
    [ROOT / 'FinancialIntelligence.pbip', ROOT / 'FinancialIntelligence.SemanticModel' / 'definition.pbism']
for f in json_files:
    try:
        walk(json.loads(f.read_text(encoding='utf-8')))
        ok(True, '')
    except json.JSONDecodeError as exc:
        ok(False, f'{f}: invalid JSON {exc}')

pages = json.loads((REPORT / 'definition' / 'pages' / 'pages.json').read_text(encoding='utf-8'))
for p in pages['pageOrder']:
    ok((REPORT / 'definition' / 'pages' / p / 'page.json').exists(), f'page {p} missing page.json')
for folder in (REPORT / 'definition' / 'pages').glob('*/visuals/*'):
    ok((folder / 'visual.json').exists(), f'{folder}: visual folder without visual.json (stale; OneDrive can keep empty folders)')
names = [json.loads(v.read_text(encoding='utf-8'))['name'] for v in REPORT.rglob('visual.json')]
ok(len(names) == len(set(names)), 'duplicate visual names')
for v in REPORT.rglob('visual.json'):
    obj = json.loads(v.read_text(encoding='utf-8'))
    ok(obj['name'] == v.parent.name, f'{v}: name != folder')
    page = json.loads((v.parents[2] / 'page.json').read_text(encoding='utf-8'))
    pos = obj['position']
    ok(pos['x'] >= 0 and pos['y'] >= 0 and pos['x'] + pos['width'] <= page['width']
       and pos['y'] + pos['height'] <= page['height'], f"{obj['name']} outside {page['width']}x{page['height']} page")

print(f'\nSUMMARY: {passes} checks passed, {len(fails)} failed; {len(names)} visuals, {len(json_files)} JSON files')
sys.exit(1 if fails else 0)
