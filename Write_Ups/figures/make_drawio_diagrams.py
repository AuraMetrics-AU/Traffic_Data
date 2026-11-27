"""Generate the project's draw.io diagrams (.drawio) from one place.

Run from the project directory:
    .venv/bin/python Write_Ups/figures/make_drawio_diagrams.py
Then export each to PNG with the draw.io desktop CLI (see export_png below, or File > Export as > PNG).
The .drawio files are the editable sources: open them in draw.io (desktop, app.diagrams.net, or the
VS Code "Draw.io Integration" extension). If you edit a diagram by hand, stop regenerating that file
here or your edits will be overwritten.
"""
from html import escape
from pathlib import Path
import shutil
import subprocess

OUT = Path(__file__).resolve().parent
INK, MUTED = '#142b3a', '#405664'


class Diagram:
    def __init__(self, name, width, height):
        self.name, self.width, self.height = name, width, height
        self.cells, self.count = [], 2

    def _id(self):
        self.count += 1
        return f'c{self.count}'

    def box(self, label, x, y, w, h, fill='#ffffff', stroke=INK, font=12, bold=False, dashed=False, parent='1',
            rounded=True, font_colour=INK, align='center', extra=''):
        cell = self._id()
        style = (f'rounded={int(rounded)};whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};'
                 f'fontSize={font};fontColor={font_colour};align={align};verticalAlign=middle;arcSize=8;'
                 f'{"fontStyle=1;" if bold else ""}{"dashed=1;dashPattern=6 4;" if dashed else ""}{extra}')
        self.cells.append(f'<mxCell id="{cell}" value="{escape(label)}" style="{style}" vertex="1" parent="{parent}">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cell

    def lane(self, title, x, y, w, h, colour, fill='#ffffff'):
        cell = self._id()
        style = (f'swimlane;rounded=1;arcSize=4;startSize=38;html=1;whiteSpace=wrap;fillColor={colour};'
                 f'swimlaneFillColor={fill};strokeColor={colour};fontColor=#ffffff;fontSize=14;fontStyle=1;'
                 f'collapsible=0;')
        self.cells.append(f'<mxCell id="{cell}" value="{escape(title)}" style="{style}" vertex="1" parent="1">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cell

    def text(self, label, x, y, w, h, font=12, colour=MUTED, bold=False, align='center', parent='1'):
        cell = self._id()
        style = (f'text;html=1;whiteSpace=wrap;align={align};verticalAlign=middle;fontSize={font};'
                 f'fontColor={colour};{"fontStyle=1;" if bold else ""}')
        self.cells.append(f'<mxCell id="{cell}" value="{escape(label)}" style="{style}" vertex="1" parent="{parent}">'
                          f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')
        return cell

    def edge(self, source, target, label='', colour=MUTED, width=1.5, dashed=False, both=False, curved=False,
             exit_=None, entry=None, font=11):
        cell = self._id()
        points = ''
        if exit_:
            points += f'exitX={exit_[0]};exitY={exit_[1]};exitDx=0;exitDy=0;'
        if entry:
            points += f'entryX={entry[0]};entryY={entry[1]};entryDx=0;entryDy=0;'
        style = (f'edgeStyle={"none" if curved else "orthogonalEdgeStyle"};rounded=1;html=1;endArrow=block;'
                 f'endFill=1;strokeColor={colour};strokeWidth={width};fontSize={font};fontColor={colour};'
                 f'labelBackgroundColor=#ffffff;{"dashed=1;" if dashed else ""}'
                 f'{"startArrow=block;startFill=1;" if both else ""}{points}')
        self.cells.append(f'<mxCell id="{cell}" value="{escape(label)}" style="{style}" edge="1" parent="1" '
                          f'source="{source}" target="{target}"><mxGeometry relative="1" as="geometry"/></mxCell>')
        return cell

    def save(self):
        body = ''.join(self.cells)
        xml = (f'<mxfile host="drawio" type="device"><diagram id="{self.name}" name="{self.name}">'
               f'<mxGraphModel dx="1600" dy="1000" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
               f'arrows="1" fold="1" page="1" pageScale="1" pageWidth="{self.width}" pageHeight="{self.height}" '
               f'background="#f6f8fa" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
               f'{body}</root></mxGraphModel></diagram></mxfile>')
        path = OUT / f'{self.name}.drawio'
        path.write_text(xml, encoding='utf-8')
        return path


# ---------------------------------------------------------------------------------------------
# 1. Analytical system architecture
# ---------------------------------------------------------------------------------------------
def architecture():
    d = Diagram('analytical_system_architecture', 2020, 1200)
    d.text('Analytical system architecture — Queensland road crash analysis (V6)', 20, 10, 1200, 34, font=22,
           colour=INK, bold=True, align='left')
    d.text('Batch analytics pipeline orchestrated by one Jupyter notebook in CRISP-ML(Q) order. Solid boxes are '
           'built; dashed boxes are planned. Labels under the arrows name the interface between layers.',
           20, 44, 1500, 24, font=13, align='left')
    layers = [
        ('1 · Data sources', '#4a729b', '#eef3f8', [
            ('Queensland crash data<br>6 CSVs · 415,407 crashes<br>+ 5 grouped tables', False),
            ('Spatial reference layers<br>roads · localities · postal<br>QPS regions · G-NAF', False),
            ('BoM rainfall station list<br>4,028 stations', False),
            ('SILO / BoM rainfall amounts', True),
            ('ABS population ·<br>TMR traffic volumes', True)]),
        ('2 · Ingestion and quality', '#007c82', '#eaf5f5', [
            ('Load and profile<br>file and key checks', False),
            ('Integration and tallies<br>year × police region', False),
            ('Recording and severity-mix<br>checks → stable window', False),
            ('Location recovery<br><i>traffic_location_recovery.py</i>', False),
            ('Rainfall join<br><i>traffic_weather.py</i>', True)]),
        ('3 · Storage and state', '#8a6d1f', '#f6f1e6', [
            ('Raw files<br>Git + Git LFS', False),
            ('Content-keyed cache<br>.cache/ · recovery snapshot<br>· road network', False),
            ('In-memory frames<br>raw · cleaned · regional_sources', False),
            ('Road-site network<br><i>traffic_road_sites.py</i><br>513k links · 251k junctions', False)]),
        ('4 · Analytics and modelling', '#76518f', '#f3eef6', [
            ('Descriptive and comparative<br>analytics (Phase 2)', False),
            ('Road-site screening<br>empirical-Bayes excess', False),
            ('Severity models and<br>adjusted odds (Phase 3)', False),
            ('Association rules<br>Apriori', False),
            ('Evaluation and reliability<br>R1–R7 (Phase 4)', False)]),
        ('5 · Data products', '#a64d25', '#f8efea', [
            ('Cleaned crash table<br>reconciliation · context CSVs', False),
            ('Tableau data V6<br>35 tables', False),
            ('Tableau workbook<br><i>build_tableau_workbook.py</i>', False),
            ('Esri map page<br>4 interactive maps', False),
            ('Release manifest ·<br>documentation set', False)]),
        ('6 · Users and decisions', '#3d7a4a', '#edf4ee', [
            ('Road-safety engineers<br>site and treatment shortlists', False),
            ('Police and response planners<br>time and place', False),
            ('Campaign teams<br>road users and restraints', False),
            ('Analysts and data scientists<br>methods and evidence', False),
            ('Decision-makers<br>model-use decision', False)]),
    ]
    lane_w, step, top, box_h, box_gap = 250, 335, 130, 78, 22
    lane_h = 38 + 5 * (box_h + box_gap) + 18
    lanes, boxes = [], {}
    for i, (title, colour, fill, items) in enumerate(layers):
        lane = d.lane(title, 20 + i * step, top, lane_w, lane_h, colour, fill)
        lanes.append(lane)
        for j, (label, planned) in enumerate(items):
            boxes[(i, j)] = d.box(label, 15, 52 + j * (box_h + box_gap), lane_w - 30, box_h, fill='#ffffff',
                                  stroke=colour, font=12, dashed=planned, parent=lane,
                                  font_colour=MUTED if planned else INK)
    interfaces = ['CSV · streamed GeoJSON ·<br>parquet · API (planned)', 'pandas DataFrames ·<br>pickle cache',
                  'cleaned frames ·<br>RoadNetwork · stable_years', 'result_* DataFrames ·<br>Folium maps · checksums',
                  'dashboards · CSV ·<br>HTML maps · documents']
    for i, label in enumerate(interfaces):
        d.edge(lanes[i], lanes[i + 1], '', colour='#5d7381', width=5, exit_=(1, 0.5), entry=(0, 0.5))
        gap_centre = 20 + i * step + lane_w + (step - lane_w) / 2
        d.text(label, gap_centre - 115, top + lane_h + 6, 230, 40, font=11)
    # Key links inside layers.
    d.edge(boxes[(1, 3)], boxes[(1, 4)], '', dashed=True)
    d.edge(boxes[(2, 0)], boxes[(2, 1)], 'build')
    d.edge(boxes[(2, 1)], boxes[(2, 2)], 'load', both=True)
    d.edge(boxes[(3, 2)], boxes[(3, 3)])
    d.edge(boxes[(3, 3)], boxes[(3, 4)], 'scores')
    d.edge(boxes[(4, 1)], boxes[(4, 2)], '.hyper')
    # Feedback loop.
    fb_from = d.text('', 20 + 5 * step + lane_w / 2, top - 30, 2, 2)
    fb_to = d.text('', 20 + lane_w / 2, top - 30, 2, 2)
    d.edge(fb_from, fb_to, 'Feedback: confirmed objectives, acceptance criteria, treated sites and new data '
                           'requests → next release', colour='#3d7a4a', dashed=True, width=2, curved=True, font=12)
    # Governance band.
    band_y = top + lane_h + 62
    band = d.lane('Control and governance (spans every layer)', 20, band_y, 5 * step + lane_w, 130, '#607d8b',
                  '#eef2f5')
    for i, label in enumerate(['Orchestrator<br>Traffic_Incidents_V6.ipynb<br>CRISP-ML(Q) phases 1–6',
                               'In-run assertions<br>tallies · preservation · totals',
                               'Reproducibility<br>seed 42 · pinned versions · manifest',
                               'Release process<br>branch · cold run · review · tag',
                               'Monitoring<br>severity mix · coverage · drift',
                               'Runners<br>Jupyter · headless · Colab']):
        d.box(label, 15 + i * step, 50, lane_w - 30, 66, fill='#ffffff', stroke='#90a4ae', font=11, parent=band)
    return d.save()


# ---------------------------------------------------------------------------------------------
# 2. Business objectives → analytical goals → analytical tasks
# ---------------------------------------------------------------------------------------------
def goals():
    tree = [
        ('BO1 Target road infrastructure<br>treatments', [
            ('AG1.1 Sites with persistent excess<br>serious crashes', ['AT1.1.1 Network, snapping,<br>empirical-Bayes ranking',
                                                                    'AT1.1.2 Persistence and<br>robustness tests']),
            ('AG1.2 Movements and settings<br>linked to fatal outcomes', ['AT1.2.1 DCA movement ranking',
                                                                         'AT1.2.2 Adjusted odds;<br>wet/dry standardisation'])]),
        ('BO2 Target enforcement and<br>incident response', [
            ('AG2.1 When and where severity is<br>highest, net of road mix', ['AT2.1.1 Day × hour, weekend<br>night, seasonality',
                                                                            'AT2.1.2 Road-mix standardisation;<br>funnel plots']),
            ('AG2.2 Behavioural factors<br>and severity', ['AT2.2.1 Matched odds<br>(year × region)',
                                                           'AT2.2.2 Pooled vs within<br>correlation'])]),
        ('BO3 Target road-user safety<br>campaigns', [
            ('AG3.1 Outcomes by protection,<br>age and road user', ['AT3.1.1 Fatalities per 100<br>casualties',
                                                                   'AT3.1.2 Seatbelt non-use<br>by gender and region']),
            ('AG3.2 Vulnerable users and<br>vehicle combinations', ['AT3.2.1 Unit flags; crash types<br>incl. cars',
                                                                   'AT3.2.2 Adjusted odds by<br>road user'])]),
        ('BO4 Decide whether severity<br>prediction can support triage', [
            ('AG4.1 Calibrated, validated<br>severity models', ['AT4.1.1 Logistic regression and<br>boosting, time split',
                                                               'AT4.1.2 Bootstrap, seeds,<br>thresholds (R1, R2, R4)']),
            ('AG4.2 Feasibility of prediction<br>before a crash', ['AT4.2.1 Feature ablation (R3)'])]),
        ('BO5 Trustworthy, reproducible,<br>accessible evidence', [
            ('AG5.1 Reconciled, quality-<br>assured crash data', ['AT5.1.1 Location recovery',
                                                                 'AT5.1.2 Tallies, recording and<br>severity-mix checks']),
            ('AG5.2 Traceable data products', ['AT5.2.1 Exports, maps, manifest',
                                              'AT5.2.2 Documentation set'])]),
        ('BO6 Understand weather and<br>environment effects', [
            ('AG6.1 Lighting, surface and<br>weather effects', ['AT6.1.1 Standardised wet/dry;<br>weather rates']),
            ('AG6.2 Rainfall exposure and<br>crash outcomes (planned)', ['AT6.2.1 Rainfall join and<br>analysis (planned)'])]),
    ]
    row_h, gap = 62, 10
    task_rows = sum(len(tasks) for _, goals_ in tree for _, tasks in goals_)
    height = 140 + task_rows * (row_h + gap) + len(tree) * 18
    d = Diagram('analytical_goals_and_tasks', 1320, int(height))
    d.text('Business objectives → analytical goals → analytical tasks', 20, 10, 900, 34, font=22, colour=INK,
           bold=True, align='left')
    for x, title, colour in [(20, 'Business objectives', '#4a729b'), (470, 'Analytical goals', '#76518f'),
                             (920, 'Analytical tasks', '#007c82')]:
        d.text(title, x, 60, 380, 30, font=15, colour=colour, bold=True)
    y = 100
    for objective, goal_list in tree:
        start = y
        goal_cells = []
        for goal, tasks in goal_list:
            goal_start = y
            task_cells = []
            for task in tasks:
                planned = 'planned' in task
                task_cells.append(d.box(task, 920, y, 380, row_h, fill='#eaf5f5', stroke='#007c82', font=12,
                                        dashed=planned))
                y += row_h + gap
            goal_y = (goal_start + y - gap) / 2 - row_h / 2
            goal_cell = d.box(goal, 470, goal_y, 380, row_h, fill='#f3eef6', stroke='#76518f', font=12,
                              dashed='planned' in goal)
            for task_cell in task_cells:
                d.edge(goal_cell, task_cell, colour='#76518f', exit_=(1, 0.5), entry=(0, 0.5))
            goal_cells.append(goal_cell)
        objective_y = (start + y - gap) / 2 - row_h / 2
        objective_cell = d.box(objective, 20, objective_y, 380, row_h, fill='#eef3f8', stroke='#4a729b', font=12,
                               bold=True)
        for goal_cell in goal_cells:
            d.edge(objective_cell, goal_cell, colour='#4a729b', exit_=(1, 0.5), entry=(0, 0.5))
        y += 18
    return d.save()


# ---------------------------------------------------------------------------------------------
# 3. Implementation components and data flow
# ---------------------------------------------------------------------------------------------
def implementation():
    d = Diagram('implementation_components', 1820, 800)
    d.text('Implementation components and data flow (V6)', 20, 10, 900, 34, font=22, colour=INK, bold=True,
           align='left')
    d.text('The notebook runs the CRISP-ML(Q) phases in order and calls modules for heavy geospatial work. Caches '
           'are content-keyed; every output is written atomically and fingerprinted in the manifest.',
           20, 44, 1700, 24, font=13, align='left')
    src = d.lane('Sources', 20, 100, 260, 560, '#4a729b', '#eef3f8')
    s_crash = d.box('Road crash locations.csv<br>415,407 × 53', 15, 55, 230, 66, stroke='#4a729b', parent=src)
    s_grouped = d.box('5 grouped CSVs<br>factors · vehicles · drivers<br>casualties · restraints', 15, 135, 230,
                      80, stroke='#4a729b', parent=src)
    s_spatial = d.box('Public spatial data/<br>roads · locality · postal<br>police · G-NAF', 15, 300, 230, 80,
                      stroke='#4a729b', parent=src)
    d.box('BoM station list (held)', 15, 395, 230, 44, stroke='#4a729b', parent=src)
    s_rain = d.box('Rainfall amounts (planned)', 15, 470, 230, 50, stroke='#4a729b', dashed=True, parent=src,
                   font_colour=MUTED)

    nb = d.lane('Traffic_Incidents_V6.ipynb — orchestrator (kernel state shared between cells)', 330, 100, 1060,
                240, '#142b3a', '#ffffff')
    phases = ['Phase 1<br>Load, profile,<br>key audit', 'Phase 2<br>Recovery, tallies,<br>recording and severity-'
              'mix checks, exploration', 'Phase 3<br>Severity models,<br>site screening,<br>rules, adjusted odds',
              'Phase 4<br>Evaluation;<br>reliability R1–R7', 'Phase 5<br>Exports, Esri page,<br>manifest',
              'Phase 6<br>Monitoring and<br>maintenance notes']
    phase_w, phase_gap = 152, 22
    phase_cells = [d.box(p, 15 + i * (phase_w + phase_gap), 60, phase_w, 150, fill='#f4f7f9', stroke='#607d8b',
                         font=12, parent=nb) for i, p in enumerate(phases)]
    for a_, b_ in zip(phase_cells, phase_cells[1:]):
        d.edge(a_, b_, colour='#607d8b', exit_=(1, 0.5), entry=(0, 0.5))

    mods = d.lane('Python modules', 330, 400, 545, 190, '#007c82', '#eaf5f5')
    module_x = [15 + i * (phase_w + phase_gap) for i in range(4)]
    m_spa = d.box('traffic_spatial_lookup.py<br>road · junction · G-NAF ·<br>polygon helpers · CLI', module_x[0], 60,
                  phase_w + 10, 100, stroke='#007c82', parent=mods, font=11)
    m_rec = d.box('traffic_location_<br>recovery.py<br>recover_locations()', module_x[1] + 5, 60, phase_w, 100,
                  stroke='#007c82', parent=mods, font=11)
    m_sit = d.box('traffic_road_sites.py<br>load_network()<br>assign_sites()', module_x[2], 60, phase_w, 100,
                  stroke='#007c82', parent=mods, font=11)
    m_wea = d.box('traffic_weather.py (planned)<br>rainfall join', 345 + module_x[1], 625, phase_w + 30, 50,
                  stroke='#007c82', dashed=True, font=11, font_colour=MUTED)
    cache = d.box('.cache/<br>location_recovery_&lt;key&gt;.pkl<br>road_network_&lt;key&gt;.pkl', 930, 440, 300,
                  110, fill='#f6f1e6', stroke='#8a6d1f')

    out = d.lane('Outputs', 1510, 100, 290, 560, '#a64d25', '#f8efea')
    d.box('Cleaned · reconciliation ·<br>context CSVs (V6)', 15, 55, 260, 66, stroke='#a64d25', parent=out)
    o_tab = d.box('Tableau data V6/<br>35 tables', 15, 135, 260, 60, stroke='#a64d25', parent=out)
    o_wb = d.box('build_tableau_workbook.py<br>→ V6 .twbx and linked .twb', 15, 215, 260, 66, stroke='#a64d25',
                 parent=out)
    d.box('Queensland Traffic V6 -<br>Esri Maps.html', 15, 300, 260, 60, stroke='#a64d25', parent=out)
    d.box('Traffic release manifest V6.json<br>SHA-256 · versions · constants', 15, 380, 260, 66, stroke='#a64d25',
          parent=out)
    d.box('Design documents (.md)<br>+ draw.io diagrams', 15, 466, 260, 60, stroke='#a64d25', parent=out)

    d.edge(s_crash, phase_cells[0], 'read_csv', exit_=(1, 0.5), entry=(0, 0.35))
    d.edge(s_grouped, phase_cells[0], exit_=(1, 0.5), entry=(0, 0.75))
    d.edge(s_spatial, m_spa, 'stream', exit_=(1, 0.5), entry=(0, 0.5))
    d.edge(s_rain, m_wea, dashed=True, exit_=(1, 0.5), entry=(0, 0.5))
    d.edge(m_spa, m_rec, 'imports', exit_=(1, 0.5), entry=(0, 0.5))
    d.edge(phase_cells[1], m_rec, 'call / return', both=True, exit_=(0.55, 1), entry=(0.5, 0))
    d.edge(phase_cells[2], m_sit, 'call / return', both=True, exit_=(0.5, 1), entry=(0.5, 0))
    d.edge(m_sit, cache, 'pickle', both=True, exit_=(1, 0.3), entry=(0, 0.3))
    d.edge(m_rec, cache, '', both=True, exit_=(0.5, 1), entry=(0.3, 1))
    d.edge(nb, out, 'Phase 5<br>atomic writes', colour='#a64d25', width=3, exit_=(1, 0.5), entry=(0, 0.215))
    d.edge(o_tab, o_wb, '.hyper')
    d.text('Run modes: Jupyter / VS Code · headless runner (jupyter_client) · Google Colab. Environment: Python 3.14.4 '
           '.venv · versions pinned in the manifest · Git + Git LFS.', 20, 730, 1700, 30, font=13, align='left')
    return d.save()


# ---------------------------------------------------------------------------------------------
# 4. Release run (sequence as swimlanes)
# ---------------------------------------------------------------------------------------------
def release_run():
    d = Diagram('release_run_sequence', 1700, 820)
    d.text('Release run — sequence of a data refresh', 20, 10, 900, 34, font=22, colour=INK, bold=True,
           align='left')
    actors = [('Analyst', '#3d7a4a'), ('Notebook', '#142b3a'), ('Location recovery', '#007c82'),
              ('Road sites', '#007c82'), ('.cache', '#8a6d1f'), ('Exports and manifest', '#a64d25'),
              ('Tableau builder', '#a64d25')]
    col_w = 230
    heads = {}
    for i, (name, colour) in enumerate(actors):
        x = 20 + i * col_w
        heads[name] = d.box(name, x + 15, 60, col_w - 30, 44, fill=colour, stroke=colour, font=13, bold=True,
                            font_colour='#ffffff')
        d.cells.append(f'<mxCell id="life{i}" value="" style="endArrow=none;dashed=1;html=1;strokeColor=#b0bec5;" '
                       f'edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                       f'<mxPoint x="{x + col_w / 2}" y="104" as="sourcePoint"/>'
                       f'<mxPoint x="{x + col_w / 2}" y="790" as="targetPoint"/></mxGeometry></mxCell>')
    steps = [
        ('Analyst', 'Notebook', '1 Run all (headless or interactive)'),
        ('Notebook', 'Notebook', '2 Load sources; check files and keys'),
        ('Notebook', 'Location recovery', '3 recover_locations(raw, layers)'),
        ('Location recovery', '.cache', '4 Look up content key'),
        ('.cache', 'Location recovery', '5 Snapshot (hit) — or recompute ~32 s and save (miss)'),
        ('Location recovery', 'Notebook', '6 cleaned, audit, validation tables'),
        ('Notebook', 'Notebook', '7 Tallies, recording and severity-mix checks (assertions)'),
        ('Notebook', 'Road sites', '8 load_network(); assign_sites()'),
        ('Road sites', '.cache', '9 Network cache'),
        ('Road sites', 'Notebook', '10 Sites'),
        ('Notebook', 'Notebook', '11 Analytics, models, screening, evaluation, R1–R7'),
        ('Notebook', 'Exports and manifest', '12 CSVs, Tableau tables, Esri page, manifest (atomic)'),
        ('Analyst', 'Tableau builder', '13 build_tableau_workbook.py'),
        ('Tableau builder', 'Exports and manifest', '14 Read tables; write .twbx'),
        ('Analyst', 'Analyst', '15 Review gates → tag → publish'),
    ]
    index = {name: i for i, (name, _) in enumerate(actors)}
    for k, (a, b, label) in enumerate(steps):
        y = 130 + k * 43
        xa, xb = 20 + index[a] * col_w + col_w / 2, 20 + index[b] * col_w + col_w / 2
        if a == b:
            d.box(label, xa - 10, y - 4, 2 * col_w - 20, 30, fill='#ffffff', stroke='#cfd8dc', font=11,
                  align='left')
            continue
        cell = d._id()
        d.cells.append(f'<mxCell id="{cell}" value="{escape(label)}" style="html=1;endArrow=block;endFill=1;'
                       f'strokeColor=#405664;fontSize=11;fontColor={INK};labelBackgroundColor=#f6f8fa;'
                       f'verticalAlign=bottom;" edge="1" parent="1"><mxGeometry relative="1" as="geometry">'
                       f'<mxPoint x="{xa}" y="{y + 18}" as="sourcePoint"/><mxPoint x="{xb}" y="{y + 18}" '
                       f'as="targetPoint"/></mxGeometry></mxCell>')
    return d.save()


# ---------------------------------------------------------------------------------------------
# 5. Timeline (Gantt) — must match Timeline_and_Milestones.md
# ---------------------------------------------------------------------------------------------
WEEKS = ['W1<br>30 Nov', 'W2<br>7 Dec', 'W3<br>14 Dec', 'Break<br>21 Dec–1 Jan', 'W4<br>4 Jan', 'W5<br>11 Jan',
         'W6<br>18 Jan', 'W7<br>25 Jan', 'W8<br>1 Feb', 'W9<br>8 Feb', 'W10<br>15 Feb', 'W11<br>22 Feb',
         'W12<br>1 Mar']
WORKSTREAMS = {'Governance': '#3d7a4a', 'Engineering': '#8a6d1f', 'Data': '#4a729b', 'Analytics': '#76518f',
               'Release': '#a64d25'}
# (id, task, workstream, first column, last column) — columns index WEEKS (3 is the break)
GANTT_TASKS = [
    ('T1', 'Confirm objectives and acceptance criteria', 'Governance', 0, 1),
    ('T2', 'V6 Tableau workbook and README', 'Release', 0, 1),
    ('T3', 'Engineering hardening (lockfile, pytest, tools/)', 'Engineering', 1, 2),
    ('T4', 'Rule redundancy filter; label cross-check', 'Analytics', 2, 2),
    ('T5', 'Rainfall source, registration, download', 'Data', 0, 5),
    ('T6', 'Rainfall join and analysis (AG6.2)', 'Analytics', 5, 6),
    ('T7', 'Site-screening refinements', 'Analytics', 4, 5),
    ('T8', 'ABS population rates', 'Data', 6, 6),
    ('T9', 'Traffic volumes (AADT) acquisition and join', 'Data', 7, 8),
    ('T10', 'Safety performance function screening', 'Analytics', 8, 9),
    ('T11', 'Docker image and scheduled run', 'Engineering', 9, 9),
    ('T12', 'V7 release run, review gates, publish', 'Release', 10, 10),
    ('T13', 'Operational-use decision workshop', 'Governance', 11, 11),
    ('T14', 'Contingency buffer', 'Governance', 12, 12),
]
# (id, label, column) — milestone at the end of that column
GANTT_MILESTONES = [('M2', 'V6 workbook + README', 1), ('M3', 'Objectives signed off', 1),
                    ('M4', 'Hardening done', 2), ('M5', 'Rainfall integrated', 6),
                    ('M6', 'Exposure-adjusted screening', 9), ('M7', 'V7 released', 10),
                    ('M8', 'Model-use decision', 11), ('M9', 'Project close', 12)]


def gantt():
    label_w, col_w, row_h, top = 420, 108, 34, 150
    d = Diagram('timeline_gantt', label_w + len(WEEKS) * col_w + 60, top + (len(GANTT_TASKS) + 4) * row_h + 170)
    d.text('Timeline — remaining work after M1 (V6 complete, 27 Nov 2026)', 20, 10, 1200, 34, font=22, colour=INK,
           bold=True, align='left')
    d.text('Completed: M0 data acquired (17 Nov) · V2–V5 iterations (19–20 Nov) · M1 V6 analysis and documentation '
           '(27 Nov). Bars show planned weeks; diamonds mark milestones at week end; the shaded column is the '
           'Christmas–New Year break.', 20, 44, 1600, 40, font=13, align='left')
    for c, week in enumerate(WEEKS):
        x = 20 + label_w + c * col_w
        fill = '#e3e8ec' if c == 3 else '#ffffff'
        d.box(week, x, top - 50, col_w, 46, fill=fill, stroke='#cfd8dc', font=11, rounded=False)
        d.box('', x, top, col_w, len(GANTT_TASKS) * row_h, fill=fill, stroke='#e3e8ec', rounded=False)
    for r, (tid, task, stream, first, last) in enumerate(GANTT_TASKS):
        y = top + r * row_h
        d.box(f'<b>{tid}</b>  {task}', 20, y, label_w, row_h, fill='#ffffff', stroke='#e3e8ec', font=12,
              rounded=False, align='left', extra='spacingLeft=8;')
        colour = WORKSTREAMS[stream]
        d.box(stream, 20 + label_w + first * col_w + 6, y + 6, (last - first + 1) * col_w - 12, row_h - 12,
              fill=colour, stroke=colour, font=10, font_colour='#ffffff',
              dashed=tid == 'T14')
    my = top + len(GANTT_TASKS) * row_h + 20
    d.text('Milestones', 20, my, label_w, 30, font=14, colour=INK, bold=True, align='left')
    for k, (mid, label, column) in enumerate(GANTT_MILESTONES):
        x = 20 + label_w + (column + 1) * col_w - 14
        yy = my + (k % 2) * 46
        d.box('', x, yy + 4, 24, 24, fill='#142b3a', stroke='#142b3a', rounded=False, extra='shape=rhombus;')
        d.text(f'<b>{mid}</b> {label}', x - 150, yy + 26, 180, 20, font=10, colour=INK, align='right')
    lx = 20
    for stream, colour in WORKSTREAMS.items():
        d.box(stream, lx, my + 110, 130, 26, fill=colour, stroke=colour, font=11, font_colour='#ffffff')
        lx += 145
    return d.save()


# ---------------------------------------------------------------------------------------------
# 6. Risk heat map — must match Risk_Management.md
# ---------------------------------------------------------------------------------------------
# (id, likelihood 1–5, impact 1–5)
RISK_POSITIONS = [
    ('RK-01', 3, 4), ('RK-02', 3, 4), ('RK-03', 3, 3), ('RK-04', 4, 3), ('RK-05', 2, 2), ('RK-06', 4, 2),
    ('RK-07', 3, 3), ('RK-08', 3, 2), ('RK-09', 5, 3), ('RK-10', 3, 1), ('RK-11', 2, 3), ('RK-12', 4, 2),
    ('RK-13', 3, 2), ('RK-14', 3, 3), ('RK-15', 2, 2), ('RK-16', 3, 2), ('RK-17', 4, 4), ('RK-18', 3, 5),
    ('RK-19', 4, 3), ('RK-20', 2, 3), ('RK-21', 4, 4), ('RK-22', 3, 3), ('RK-23', 4, 2), ('RK-24', 3, 4),
    ('RK-25', 4, 3), ('RK-26', 2, 5), ('RK-27', 3, 4), ('RK-28', 2, 3), ('RK-29', 3, 3), ('RK-30', 3, 4),
    ('RK-31', 3, 3), ('RK-32', 2, 2), ('RK-33', 1, 4),
]


def risk_matrix():
    cell, left, top = 190, 170, 130
    d = Diagram('risk_heat_map', left + 5 * cell + 60, top + 5 * cell + 150)
    d.text('Risk heat map — inherent risk before treatment (likelihood × impact)', 20, 10, 1100, 34, font=22,
           colour=INK, bold=True, align='left')
    d.text('Score = likelihood × impact. 1–4 low · 5–9 medium · 10–14 high · 15–25 critical. IDs refer to '
           'Risk_Management.md.', 20, 44, 1100, 24, font=13, align='left')

    def colour(score):
        return '#d8eadb' if score <= 4 else '#fbeec5' if score <= 9 else '#f7cfae' if score <= 14 else '#eaa79a'

    cells = {}
    for likelihood in range(1, 6):
        for impact in range(1, 6):
            x, y = left + (impact - 1) * cell, top + (5 - likelihood) * cell
            ids = [rid for rid, l, i in RISK_POSITIONS if l == likelihood and i == impact]
            label = ' · '.join(ids)
            cells[(likelihood, impact)] = d.box(label, x, y, cell, cell, fill=colour(likelihood * impact),
                                                stroke='#ffffff', font=12, rounded=False)
    for k, name in enumerate(['1 Rare', '2 Unlikely', '3 Possible', '4 Likely', '5 Almost certain']):
        d.text(name, 20, top + (4 - k) * cell, left - 30, cell, font=12, colour=INK, align='right')
    for k, name in enumerate(['1 Minor', '2 Moderate', '3 Major', '4 Severe', '5 Critical']):
        d.text(name, left + k * cell, top + 5 * cell + 6, cell, 26, font=12, colour=INK)
    d.text('<b>Likelihood</b>', 20, top - 36, left - 30, 30, font=13, colour=INK, align='right')
    d.text('<b>Impact →</b>', left, top + 5 * cell + 36, 5 * cell, 26, font=13, colour=INK)
    return d.save()


def export_png(path):
    """Export a .drawio file to PNG next to it with the draw.io desktop CLI, if available."""
    drawio = shutil.which('drawio') or '/snap/bin/drawio'
    target = path.with_suffix('.png')
    subprocess.run([drawio, '--export', '--format', 'png', '--scale', '2', '--border', '20',
                    '--output', str(target), str(path)], check=True)
    return target


if __name__ == '__main__':
    import sys
    files = [architecture(), goals(), implementation(), release_run(), gantt(), risk_matrix()]
    for path in files:
        print('Wrote', path)
    if '--png' in sys.argv:
        for path in files:
            print('Exported', export_png(path))
