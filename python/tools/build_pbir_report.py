"""Generate the PBIR report definition for PowerBi/FinancialIntelligence.Report.

    ./.venv/Scripts/python.exe python/tools/build_pbir_report.py

Writes JSON only (no Power BI dependency). Pages:
  1 Executive Overview   2 Failure Analysis   3 Transaction Detail (drillthrough)
Re-running regenerates the report folder from this file (single source for layout and theme).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]            # repository root
REPORT = ROOT / 'PowerBi' / 'FinancialIntelligence.Report'
SCHEMA = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition'
W, H = 1280, 770
MEASURE_TABLE = '_Measures'   # 'Measures' is reserved in Power BI (MDX keyword)
GAP = 10

# ---------- palette: locked design direction Navy + Cyan + Teal (dark, financial analytics) ----------
# Series order checked for colour-blind separation on the navy surface (docs/test_evidence/10_palette_check.txt):
# cyan and teal are NOT adjacent (cyan-vs-teal fails CVD), amber is series 2 as in the design concept.
CYAN, AMBER, TEAL, VIOLET, CORAL, BLUE = '#22c3e6', '#f5b301', '#14b8a6', '#a78bfa', '#fb7185', '#60a5fa'
CATEGORICAL = [CYAN, AMBER, TEAL, VIOLET, CORAL, BLUE]
SURFACE, PAGE_PLANE = '#112a4d', '#0b1a33'               # visual panels / page (navy)
INK_PRIMARY, INK_SECONDARY, INK_MUTED = '#f1f5f9', '#b6c4d6', '#8a9bb4'
GRIDLINE, BASELINE = '#1e3d66', '#2c4f7c'
INSIGHT_BG, INSIGHT_INK = '#ffffff', '#0b1a33'           # white insight card, as in the concept
STATUS = {'good': '#22c55e', 'warning': '#f5b301', 'critical': '#f43f5e'}   # reserved, never a series colour

THEME = {
    'name': 'FinancialIntelligence',
    'dataColors': CATEGORICAL,                     # fixed slot order: series 1 blue, series 2 orange, ...
    'foreground': INK_PRIMARY, 'foregroundNeutralSecondary': INK_SECONDARY, 'foregroundNeutralTertiary': INK_MUTED,
    'background': SURFACE, 'backgroundLight': PAGE_PLANE, 'backgroundNeutral': GRIDLINE,
    'tableAccent': CATEGORICAL[0],
    'good': STATUS['good'], 'neutral': STATUS['warning'], 'bad': STATUS['critical'],
    'textClasses': {
        'callout': {'fontFace': 'Segoe UI Semibold', 'fontSize': 22, 'color': INK_PRIMARY},
        'title': {'fontFace': 'Segoe UI Semibold', 'fontSize': 11, 'color': INK_PRIMARY},
        'header': {'fontFace': 'Segoe UI Semibold', 'fontSize': 10, 'color': INK_SECONDARY},
        'label': {'fontFace': 'Segoe UI', 'fontSize': 10, 'color': INK_SECONDARY},
    },
    'visualStyles': {
        'page': {'*': {
            'background': [{'color': {'solid': {'color': PAGE_PLANE}}, 'transparency': 0}],
            'outspace': [{'color': {'solid': {'color': PAGE_PLANE}}, 'transparency': 0}],
        }},
        '*': {'*': {
            'background': [{'show': True, 'color': {'solid': {'color': SURFACE}}, 'transparency': 0}],
            'border': [{'show': True, 'color': {'solid': {'color': GRIDLINE}}, 'radius': 8}],
            'dropShadow': [{'show': False}],
            'title': [{'show': True, 'fontColor': {'solid': {'color': INK_PRIMARY}}, 'fontSize': 11, 'bold': True}],
            'valueAxis': [{'gridlineColor': {'solid': {'color': GRIDLINE}}, 'labelColor': {'solid': {'color': INK_MUTED}},
                           'titleColor': {'solid': {'color': INK_SECONDARY}}}],
            'categoryAxis': [{'labelColor': {'solid': {'color': INK_MUTED}}, 'titleColor': {'solid': {'color': INK_SECONDARY}}}],
            'legend': [{'labelColor': {'solid': {'color': INK_SECONDARY}}}],
            'labels': [{'color': {'solid': {'color': INK_PRIMARY}}}],
        }},
        'slicer': {'*': {
            'header': [{'fontColor': {'solid': {'color': INK_PRIMARY}}}],
            'items': [{'fontColor': {'solid': {'color': INK_PRIMARY}}, 'background': {'solid': {'color': SURFACE}}}],
            'date': [{'fontColor': {'solid': {'color': INK_PRIMARY}}, 'background': {'solid': {'color': PAGE_PLANE}}}],
        }},
        **{vt: {'*': {
            'columnHeaders': [{'backColor': {'solid': {'color': SURFACE}}, 'fontColor': {'solid': {'color': INK_SECONDARY}}}],
            'rowHeaders': [{'backColor': {'solid': {'color': SURFACE}}, 'fontColor': {'solid': {'color': INK_PRIMARY}}}],
            'values': [{'backColorPrimary': {'solid': {'color': SURFACE}}, 'backColorSecondary': {'solid': {'color': '#14305a'}},
                        'fontColorPrimary': {'solid': {'color': INK_PRIMARY}}, 'fontColorSecondary': {'solid': {'color': INK_PRIMARY}}}],
            'total': [{'backColor': {'solid': {'color': '#0f2444'}}, 'fontColor': {'solid': {'color': INK_PRIMARY}}}],
            'grid': [{'gridHorizontalColor': {'solid': {'color': GRIDLINE}}, 'outlineColor': {'solid': {'color': GRIDLINE}}}],
        }} for vt in ('tableEx', 'pivotTable')},
    },
}


# ---------- field helpers ----------
def col(entity, prop):
    return {'Column': {'Expression': {'SourceRef': {'Entity': entity}}, 'Property': prop}}


def msr(prop):
    return {'Measure': {'Expression': {'SourceRef': {'Entity': MEASURE_TABLE}}, 'Property': prop}}


def hier_level(level):
    return {'HierarchyLevel': {'Expression': {'Hierarchy': {'Expression': {'SourceRef': {'Entity': 'dim_date'}},
                                                            'Hierarchy': 'Date Hierarchy'}}, 'Level': level}}


def proj(field, active=None, label=None):
    if 'Measure' in field:
        ref = f"{MEASURE_TABLE}.{field['Measure']['Property']}"; native = field['Measure']['Property']
    elif 'Column' in field:
        ref = f"{field['Column']['Expression']['SourceRef']['Entity']}.{field['Column']['Property']}"
        native = field['Column']['Property']
    else:
        lvl = field['HierarchyLevel']['Level']
        ref = f'dim_date.Date Hierarchy.{lvl}'; native = f'Date Hierarchy {lvl}'
    p = {'field': field, 'queryRef': ref, 'nativeQueryRef': native}
    if label:
        p['displayName'] = label                  # shorter column / axis label in this visual only
    if active is not None:
        p['active'] = active
    return p


def lit(value):
    return {'expr': {'Literal': {'Value': value}}}


# Opens expanded to Month (Year > Quarter > Month shown); Day available by drilling down.
DATE_DRILL = [proj(hier_level(l), active=(l != 'Day')) for l in ('Year', 'Quarter', 'Month', 'Day')]


# ---------- visual builders ----------
def visual(name, vtype, x, y, w, h, roles, title=None, objects=None, extra=None, subtitle=None, sort_by=None,
           sort_dir='Ascending'):
    v = {'visualType': vtype,
         'query': {'queryState': {role: {'projections': projs} for role, projs in roles.items()}},
         'drillFilterOtherVisuals': True}
    if sort_by:                                   # default sort, e.g. month column -> chronological (sortByColumn)
        v['query']['sortDefinition'] = {'sort': [{'field': sort_by, 'direction': sort_dir}], 'isDefaultSort': True}
    if objects:
        v['objects'] = objects
    if title:
        v['visualContainerObjects'] = {'title': [{'properties': {'show': lit('true'), 'text': lit(f"'{title}'")}}]}
        # Without an explicit subtitle Desktop shows an auto one ("Failures by Failure reason"), which costs
        # vertical space (it pushed 2 of 7 bars into a scrollbar): hide it unless we give one.
        v['visualContainerObjects']['subTitle'] = [{'properties': (
            {'show': lit('true'), 'text': lit(f"'{subtitle}'"), 'fontSize': lit('9D'),
             'fontColor': {'solid': {'color': lit(f"'{INK_MUTED}'")}}} if subtitle else {'show': lit('false')})}]
    else:
        v['visualContainerObjects'] = {'title': [{'properties': {'show': lit('false')}}]}
    if extra:
        v.update(extra)
    return name, {'$schema': f'{SCHEMA}/visualContainer/2.14.0/schema.json', 'name': name,
                  'position': {'x': x, 'y': y, 'z': 0, 'width': w, 'height': h, 'tabOrder': 0},
                  'visual': v}


def card(name, x, y, measure, title, basis=None, w=203, h=100, font='20D', accent=None,
         bg=None, ink=INK_PRIMARY, wrap=False):
    """Classic card: one-line title, date basis as a small subtitle, the card's own category
    label hidden (no duplicate text), value in full (no 'K'). `accent` colours the card border."""
    name_, obj = visual(name, 'card', x, y, w, h, {'Values': [proj(msr(measure))]}, title, subtitle=basis,
                        objects={'labels': [{'properties': {'fontSize': lit(font), 'labelDisplayUnits': lit('1D'),
                                                            'color': {'solid': {'color': lit(f"'{ink}'")}},
                                                            **({'wordWrap': lit('true')} if wrap else {})}}],
                                 'categoryLabels': [{'properties': {'show': lit('false')}}]})
    vco = obj['visual']['visualContainerObjects']
    if accent:
        vco['border'] = [{'properties': {'show': lit('true'), 'color': {'solid': {'color': lit(f"'{accent}'")}},
                                         'width': lit('2D'), 'radius': lit('10D')}}]
    if bg:
        vco['background'] = [{'properties': {'show': lit('true'), 'color': {'solid': {'color': lit(f"'{bg}'")}},
                                             'transparency': lit('0D')}}]
        vco['title'][0]['properties']['fontColor'] = {'solid': {'color': lit(f"'{ink}'")}}
    return name_, obj


def mexpr(measure):
    """Bind a formatting property to a measure (Power BI 'fx' / field value)."""
    return {'expr': {'Measure': {'Expression': {'SourceRef': {'Entity': MEASURE_TABLE}}, 'Property': measure}}}


def kpi_tile(name, x, y, measure, title, accent, delta=None, delta_color=None, basis=None,
             w=307, h=None, font='26D'):
    """Concept-style KPI tile: icon + title, big value, and a coloured 'latest month vs prior' line.
    The line is the container subtitle bound to a text measure; its colour is bound to a colour measure."""
    h = KPI_H if h is None else h
    name_, obj = card(name, x, y, measure, title, basis, w=w, h=h, font=font, accent=accent)
    if delta:
        obj['visual']['visualContainerObjects']['subTitle'] = [{'properties': {
            'show': lit('true'), 'text': mexpr(delta), 'fontSize': lit('10D'),
            'fontColor': {'solid': {'color': mexpr(delta_color)}}}}]
    return name_, obj


def hour_mini_chart(name, x, y, w, h):
    """White 'Failure rate by hour' panel like the concept; amber bars = seeded window 02:00-03:59 ET."""
    dark = lambda c: {'solid': {'color': lit(f"'{c}'")}}
    name_, obj = visual(name, 'clusteredColumnChart', x, y, w, h,
                        {'Category': [proj(col('fact_payment_attempt', 'attempt_hour_et'), label='ET hour')],
                         'Y': [proj(msr('Failure Rate'))]},
                        'Failure rate by hour (ET)', subtitle='amber = 02:00-03:59 seeded window',
                        # Continuous (scalar) axis: all 24 hours fit without a scrollbar (categorical showed 0-9 only).
                        objects={'categoryAxis': [{'properties': {'axisType': lit("'Scalar'"), 'labelColor': dark('#52514e'),
                                                                  'showAxisTitle': lit('false')}}],
                                 'valueAxis': [{'properties': {'show': lit('false'), 'gridlineShow': lit('false')}}],
                                 'legend': [{'properties': {'show': lit('false')}}],
                                 'dataPoint': [{'properties': {'fill': {'solid': {'color': mexpr('Hour Bar Color')}}},
                                                'selector': {'data': [{'dataViewWildcard': {'matchingOption': 1}}]}}]})
    vco = obj['visual']['visualContainerObjects']
    vco['background'] = [{'properties': {'show': lit('true'), 'color': dark(INSIGHT_BG), 'transparency': lit('0D')}}]
    vco['border'] = [{'properties': {'show': lit('true'), 'color': dark(INSIGHT_BG), 'radius': lit('10D')}}]
    vco['title'][0]['properties']['fontColor'] = dark(INSIGHT_INK)
    return name_, obj


def insight_card(name, x, y, w, h):
    # Desktop cut the first (longer) text at 12pt in 250px: shorter sentence, 11pt, wider card.
    return card(name, x, y, 'Key Insight Text', '💡 Key business insight', 'computed from this data',
                w=w, h=h, font='11D', accent=AMBER, bg=INSIGHT_BG, ink=INSIGHT_INK, wrap=True)


def header(prefix, page_title, note='KPIs by ET attempt date · refund / reversal amounts by ET event date'):
    """Navy title band like the design concept: product name | page name, plus a data-honesty note."""
    para = [{'textRuns': [
                {'value': 'Financial Intelligence', 'textStyle': {'fontWeight': 'bold', 'fontSize': '16pt', 'color': INK_PRIMARY}},
                {'value': f'  |  {page_title}', 'textStyle': {'fontSize': '14pt', 'color': CYAN}}]},
            {'textRuns': [{'value': f'Synthetic USD payment data · verified against SQL · {note}',
                           'textStyle': {'fontSize': '8pt', 'color': INK_MUTED}}]}]
    return f'{prefix}_header', {
        '$schema': f'{SCHEMA}/visualContainer/2.14.0/schema.json', 'name': f'{prefix}_header',
        'position': {'x': GAP, 'y': 0, 'z': 0, 'width': 560, 'height': HEADER_H - 2, 'tabOrder': 0},
        'visual': {'visualType': 'textbox', 'objects': {'general': [{'properties': {'paragraphs': para}}]},
                   'visualContainerObjects': {'background': [{'properties': {'show': lit('false')}}],
                                              'border': [{'properties': {'show': lit('false')}}],
                                              'title': [{'properties': {'show': lit('false')}}]},
                   'drillFilterOtherVisuals': True}}


# Grid (1280 x 770): header band with slicers | 4 KPI tiles | trend + insight | detail row
HEADER_H = 72                                             # 0 .. 72
KPI_Y, KPI_H = HEADER_H + 8, 120                          # 80 .. 200
ROW2_Y, ROW2_H = KPI_Y + KPI_H + GAP, 300                 # 210 .. 510
ROW3_Y = ROW2_Y + ROW2_H + GAP                            # 520
ROW3_H = H - GAP - ROW3_Y                                 # .. 760
TILE_W = (W - 2 * GAP - 3 * GAP) // 4                     # 307: four tiles across


def tile_x(i, w=TILE_W):
    return GAP + i * (w + GAP)


def slicers(prefix):
    """Slicers sit inside the header band (right side), like the concept's top-right pills."""
    header = {'header': [{'properties': {'show': lit('true'), 'fontColor': {'solid': {'color': lit(f"'{INK_PRIMARY}'")}}}}]}
    date = visual(f'{prefix}_slicer_date', 'slicer', 580, 4, 270, 64,
                  {'Values': [proj(col('dim_date', 'full_date'), label='Date (ET)')]},
                  objects={'data': [{'properties': {'mode': lit("'Between'")}}], **header},
                  extra={'syncGroup': {'groupName': 'full_date', 'fieldChanges': True, 'filterChanges': True}})
    method = visual(f'{prefix}_slicer_method', 'slicer', 860, 4, 150, 64,
                    {'Values': [proj(col('dim_payment_method', 'payment_method_name'), label='Payment method')]},
                    objects={'data': [{'properties': {'mode': lit("'Dropdown'")}}], **header},
                    extra={'syncGroup': {'groupName': 'payment_method_name', 'fieldChanges': True, 'filterChanges': True}})
    # No container title: at 64px the title hid the value. The label text itself starts with "As of".
    asof = card(f'{prefix}_card_asof', 1020, 4, 'As-of Label', None, w=250, h=64, font='8D', wrap=True)
    return [date, method, asof]


def table_objects():
    return {'columnHeaders': [{'properties': {'wordWrap': lit('true'), 'fontColor': {'solid': {'color': lit(f"'{INK_SECONDARY}'")}}}}],
            'values': [{'properties': {'fontColor': {'solid': {'color': lit(f"'{INK_PRIMARY}'")}}}}],
            'grid': [{'properties': {'gridHorizontalColor': {'solid': {'color': lit(f"'{GRIDLINE}'")}}}}]}


def labelled(extra_objects=None):
    o = {'labels': [{'properties': {'show': lit('true'), 'color': {'solid': {'color': lit(f"'{INK_SECONDARY}'")}}}}]}
    o.update(extra_objects or {})
    return o


# ---------- pages ----------
def page_exec():
    v = [header('ex', 'Executive Overview')] + slicers('ex')
    # Row 1: four concept KPI tiles (icon + title, value, coloured latest-month line)
    for i, (m, t, acc, d) in enumerate([
            ('Total Attempts', '💳  Total attempts', CYAN, 'Attempts'),
            ('Gross Successful Value', '💰  Gross successful value', VIOLET, 'Value'),
            ('Success Rate', '✅  Success rate', TEAL, 'Success'),
            ('Failed Count', '⚠️  Failed attempts', CORAL, 'Failed')]):
        v.append(kpi_tile(f'ex_kpi_{i}', tile_x(i), KPI_Y, m, t, acc, f'KPI Delta {d}', f'KPI Delta Color {d}'))
    # Row 2 left: volume + success-rate trend panel = two aligned charts (no dual axis)
    trend_w, half = 660, (ROW2_H - 6) // 2
    no_value_axis = {'valueAxis': [{'properties': {'show': lit('false'), 'gridlineShow': lit('false')}}],
                     'categoryAxis': [{'properties': {'concatenateLabels': lit('true')}}]}
    v.append(visual('ex_col_attempts', 'clusteredColumnChart', GAP, ROW2_Y, trend_w, half,
                    {'Category': DATE_DRILL, 'Y': [proj(msr('Total Attempts'), label='Attempts')]},
                    'Transaction volume & success-rate trend', subtitle='attempts by ET month (drill down to day)',
                    objects=labelled(no_value_axis)))
    v.append(visual('ex_line_success', 'lineChart', GAP, ROW2_Y + half + 6, trend_w, half,
                    {'Category': DATE_DRILL, 'Y': [proj(msr('Success Rate'))]},
                    'Success rate by ET month', subtitle='Success / (Success + Failed)',
                    objects=labelled({'lineStyles': [{'properties': {'showMarker': lit('true'), 'markerSize': lit('8D'),
                                                                     'strokeWidth': lit('2D')}}], **no_value_axis})))
    # Row 2 right: white insight panel + failure rate by hour (amber = seeded window)
    insight_x, insight_w = GAP + trend_w + GAP, 330
    hour_x = insight_x + insight_w + GAP
    v.append(insight_card('ex_insight', insight_x, ROW2_Y, insight_w, ROW2_H))
    v.append(hour_mini_chart('ex_hour', hour_x, ROW2_Y, W - GAP - hour_x, ROW2_H))
    # Row 3: required adjustment amounts (event date) + monthly and cohort tables
    small_h, small_w = (ROW3_H - GAP) // 2, 180
    tbl_x1 = GAP + small_w + GAP
    tbl_w = (W - GAP - tbl_x1 - GAP) // 2
    v.append(kpi_tile('ex_refund', GAP, ROW3_Y, 'Refund Amount', '↩️  Refund amount', AMBER, basis='adjustment event date',
                      w=small_w, h=small_h, font='18D'))
    v.append(kpi_tile('ex_reversal', GAP, ROW3_Y + small_h + GAP, 'Reversal Amount', '⏪  Reversal amount', BLUE,
                      basis='adjustment event date', w=small_w, h=small_h, font='18D'))
    v.append(visual('ex_tbl_monthly', 'tableEx', tbl_x1, ROW3_Y, tbl_w, ROW3_H,
                    {'Values': [proj(col('dim_date', 'Year Month'), label='Month'),
                                proj(msr('Month State'), label='State'),
                                proj(msr('Total Attempts'), label='Attempts'),
                                proj(msr('Gross Successful Value'), label='Value'),
                                proj(msr('MoM Attempts %'), label='MoM att.'),
                                proj(msr('MoM Success Rate (pp)'), label='MoM succ.')]},
                    'Monthly KPIs (MoM only for completed ET months)', objects=table_objects(),
                    sort_by=col('dim_date', 'Year Month')))
    v.append(visual('ex_tbl_cohort', 'tableEx', tbl_x1 + tbl_w + GAP, ROW3_Y, tbl_w, ROW3_H,
                    {'Values': [proj(col('dim_date', 'Year Month'), label='Cohort'),
                                proj(msr('Success Count'), label='Success'),
                                proj(msr('Refunded Txn Rate (cohort)'), label='Refund txn'),
                                proj(msr('Reversed Txn Rate (cohort)'), label='Reversal txn'),
                                proj(msr('Refund Value Rate (cohort)'), label='Refund value'),
                                proj(msr('Cohort Maturity'), label='Maturity')]},
                    'Refund / reversal rates by ORIGINAL attempt month (as-of cutoff)', objects=table_objects(),
                    sort_by=col('dim_date', 'Year Month')))
    return {'name': 'exec_overview', 'displayName': 'Executive Overview'}, v


def page_failure():
    v = [header('fa', 'Failure Analysis', note='all KPIs by ET attempt date and ET hour')] + slicers('fa')
    tiles = [('Failed Count', '⚠️  Failed attempts', CORAL, 'attempt date', 'Failed'),
             ('Failure Rate', '📉  Failure rate', CYAN, 'Failed / (Success + Failed)', None),
             ('AUTH_TIMEOUT Rate', '⏱️  AUTH_TIMEOUT rate', AMBER, 'AUTH_TIMEOUT failures / processed', None),
             ('Aged Pending Count', '⏳  Aged pending', VIOLET, 'Pending > 24h at cutoff (flag only)', None)]
    for i, (m, t, acc, basis, d) in enumerate(tiles):
        v.append(kpi_tile(f'fa_kpi_{i}', tile_x(i), KPI_Y, m, t, acc,
                          f'KPI Delta {d}' if d else None, f'KPI Delta Color {d}' if d else None,
                          basis=None if d else basis))
    v.append(insight_card('fa_card_insight', 1010, ROW2_Y, 260, ROW2_H))
    v.append(visual('fa_col_hour', 'clusteredColumnChart', GAP, ROW2_Y, 990, ROW2_H,
                    {'Category': [proj(col('fact_payment_attempt', 'attempt_hour_et'), label='ET hour')],
                     'Y': [proj(msr('Failure Rate')), proj(msr('AUTH_TIMEOUT Rate'))]},
                    'Failure rate and AUTH_TIMEOUT rate by ET hour of attempt (0-23)',
                    objects={'categoryAxis': [{'properties': {'axisType': lit("'Categorical'")}}],
                             'legend': [{'properties': {'show': lit('true'), 'position': lit("'Top'")}}]}))
    v.append(visual('fa_bar_reason', 'clusteredBarChart', GAP, ROW3_Y, 415, ROW3_H,
                    {'Category': [proj(col('dim_failure_reason', 'failure_reason_code'), label='Failure reason')],
                     'Y': [proj(msr('Failed Count'), label='Failures')]},
                    'Failures by reason (right-click a bar > Drill through)', objects=labelled(),
                    sort_by=msr('Failed Count'), sort_dir='Descending'))
    v.append(visual('fa_matrix_reason_method', 'pivotTable', 435, ROW3_Y, 415, ROW3_H,
                    {'Rows': [proj(col('dim_failure_reason', 'failure_reason_code'), label='Failure reason')],
                     'Columns': [proj(col('dim_payment_method', 'payment_method_name'), label='Method')],
                     'Values': [proj(msr('Failed Count'), label='Failures')]},
                    'Failures: reason x payment method', objects=table_objects(),
                    sort_by=msr('Failed Count'), sort_dir='Descending'))
    v.append(visual('fa_bar_method', 'clusteredBarChart', 860, ROW3_Y, 410, ROW3_H,
                    {'Category': [proj(col('dim_payment_method', 'payment_method_name'), label='Payment method')],
                     'Y': [proj(msr('Failure Rate'))]},
                    'Failure rate by payment method', objects=labelled()))
    return {'name': 'failure_analysis', 'displayName': 'Failure Analysis'}, v


def page_detail():
    v = [header('dt', 'Transaction Detail (drill-through)', note='rows behind the selected method / failure reason')]
    for i, (m, t, acc, basis) in enumerate([
            ('Total Attempts', '💳  Attempts', CYAN, 'in drill-through selection'),
            ('Failed Count', '⚠️  Failed attempts', CORAL, 'in drill-through selection'),
            ('Attempted Value', '💵  Attempted value', VIOLET, 'all statuses; not Transaction Value')]):
        v.append(kpi_tile(f'dt_kpi_{i}', GAP + i * 420, KPI_Y, m, t, acc, basis=basis, w=410))
    v.append(visual('dt_tbl', 'tableEx', GAP, ROW2_Y, 1260, H - GAP - ROW2_Y,
                    {'Values': [proj(col('fact_payment_attempt', 'transaction_id'), label='Transaction'),
                                proj(col('fact_payment_attempt', 'attempt_timestamp_utc'), label='Attempt (UTC)'),
                                proj(col('fact_payment_attempt', 'attempt_hour_et'), label='ET hour'),
                                proj(col('fact_payment_attempt', 'status'), label='Status'),
                                proj(col('dim_payment_method', 'payment_method_name'), label='Method'),
                                proj(col('dim_failure_reason', 'failure_reason_code'), label='Failure reason'),
                                proj(col('fact_payment_attempt', 'merchant_id'), label='Merchant'),
                                proj(msr('Attempted Value'), label='Amount')]},
                    'Attempts behind the selected payment method / failure reason', objects=table_objects()))
    drill_fields = [('dt_f_method', col('dim_payment_method', 'payment_method_name')),
                    ('dt_f_reason', col('dim_failure_reason', 'failure_reason_code'))]
    page = {'name': 'transaction_detail', 'displayName': 'Transaction Detail',
            'type': 'Drillthrough',
            'filterConfig': {'filters': [{'name': n, 'field': f, 'type': 'Categorical', 'howCreated': 'Drillthrough'}
                                         for n, f in drill_fields]},
            'pageBinding': {'name': 'dt_binding', 'type': 'Drillthrough', 'referenceScope': 'Default',
                            'parameters': [{'name': f'{n}_p', 'boundFilter': n, 'fieldExpr': f} for n, f in drill_fields]}}
    return page, v


# Built-in Power BI base theme, same one Desktop 2.159 writes (copied once from a Desktop-saved report).
BASE_THEME = 'Fluent2-CY26SU10'
THEME_FILE = Path(__file__).resolve().parent / 'resources' / f'{BASE_THEME}.json'
CUSTOM_THEME = 'FinancialIntelligence.json'
VERSION_AT_IMPORT = {'visual': '2.14.0', 'report': '3.4.0', 'page': '2.3.1'}

WRITTEN: set[Path] = set()


def write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + '\n', encoding='utf-8')
    WRITTEN.add(path.resolve())


def remove_stale() -> None:
    """Overwrite-in-place + delete only stale generated files (OneDrive can lock folders, so no rmtree)."""
    d = REPORT / 'definition'
    for f in d.rglob('*.json'):
        if f.resolve() not in WRITTEN:
            f.unlink()
    for folder in sorted((p for p in d.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        try:
            folder.rmdir()                                # only succeeds when empty
        except OSError:
            pass


def main() -> None:
    write(REPORT / 'definition.pbir', {
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/1.0.0/schema.json',
        'version': '4.0', 'datasetReference': {'byPath': {'path': '../FinancialIntelligence.SemanticModel'}}})
    write(REPORT / '.platform', {
        '$schema': 'https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json',
        'metadata': {'type': 'Report', 'displayName': 'FinancialIntelligence'},
        'config': {'version': '2.0', 'logicalId': 'a0905170-201b-4a73-84ee-a089fcea82f0'}})
    d = REPORT / 'definition'
    write(d / 'version.json', {'$schema': f'{SCHEMA}/versionMetadata/1.0.0/schema.json', 'version': '2.0.0'})
    write(d / 'report.json', {
        '$schema': f'{SCHEMA}/report/3.3.0/schema.json',
        'themeCollection': {
            'baseTheme': {'name': BASE_THEME, 'reportVersionAtImport': VERSION_AT_IMPORT, 'type': 'SharedResources'},
            'customTheme': {'name': CUSTOM_THEME, 'reportVersionAtImport': VERSION_AT_IMPORT, 'type': 'RegisteredResources'}},
        'resourcePackages': [
            {'name': 'SharedResources', 'type': 'SharedResources',
             'items': [{'name': BASE_THEME, 'path': f'BaseThemes/{BASE_THEME}.json', 'type': 'BaseTheme'}]},
            {'name': 'RegisteredResources', 'type': 'RegisteredResources',
             'items': [{'name': CUSTOM_THEME, 'path': CUSTOM_THEME, 'type': 'CustomTheme'}]}],
        'settings': {'useStylableVisualContainerHeader': True, 'exportDataMode': 'AllowSummarized',
                     'defaultDrillFilterOtherVisuals': True, 'allowChangeFilterTypes': True,
                     'useEnhancedTooltips': True, 'useDefaultAggregateDisplayName': True}})
    theme_dst = REPORT / 'StaticResources' / 'SharedResources' / 'BaseThemes' / f'{BASE_THEME}.json'
    theme_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(THEME_FILE, theme_dst)
    custom = REPORT / 'StaticResources' / 'RegisteredResources' / CUSTOM_THEME
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text(json.dumps(THEME, indent=2) + '\n', encoding='utf-8')
    pages = [page_exec(), page_failure(), page_detail()]
    write(d / 'pages' / 'pages.json', {'$schema': f'{SCHEMA}/pagesMetadata/1.1.0/schema.json',
                                       'pageOrder': [p['name'] for p, _ in pages], 'activePageName': 'exec_overview'})
    n_vis = 0
    for meta, visuals in pages:
        page = {'$schema': f'{SCHEMA}/page/2.1.0/schema.json', **meta,
                'displayOption': 'FitToPage', 'height': H, 'width': W}
        write(d / 'pages' / meta['name'] / 'page.json', page)
        for i, (vname, vobj) in enumerate(visuals):
            vobj['position']['tabOrder'] = i
            write(d / 'pages' / meta['name'] / 'visuals' / vname / 'visual.json', vobj)
            n_vis += 1
    remove_stale()
    print(f'Wrote {len(pages)} pages, {n_vis} visuals + theme to {REPORT}')


if __name__ == '__main__':
    main()
