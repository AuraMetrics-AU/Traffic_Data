"""Package the notebook's Tableau exports into `Queensland Traffic V5.twbx`.

Run after `Traffic_Incidents_V5.ipynb` has written `Tableau data V5/`:

    python build_tableau_workbook.py

The workbook is generated from the specifications in this file, so a change to a
sheet or dashboard is made here and the workbook is rebuilt. Each CSV file becomes
one Tableau data source, stored as a Tableau extract (.hyper) because Tableau Public
only loads workbooks whose data sources are extracts:

* `crashes` is the crash-level table behind the interactive dashboards.
* `casualties`, `restraints` and the three flag tables are the grouped sources.
* `result_*` tables hold fixed-period results calculated in the notebook.

The script needs the `tableauhyperapi` package to write the extracts. Before
writing, it checks that every field a sheet uses exists in its data source and
that every dashboard refers to a real sheet.

It writes three files:

* `Queensland Traffic V5.twbx`: packaged workbook, data included.
* `Queensland Traffic V5.twb`: the same workbook unpackaged. It reads from the
  `Tableau data V5` folder beside it.
* `Queensland Traffic V5 (direct extract).twbx`: an alternative that connects
  straight to the .hyper files, to try if the first does not load.
"""
import csv
import re
from datetime import datetime
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA_DIR = BASE / 'Tableau data V5'
EXTRACT_DIR = DATA_DIR / 'Extracts'
WORKBOOK = BASE / 'Queensland Traffic V5.twbx'
ALTERNATIVE = BASE / 'Queensland Traffic V5 (direct extract).twbx'
TWB_NAME = 'Queensland Traffic V5.twb'
USER_NS = 'http://www.tableausoftware.com/xml/user'
ET.register_namespace('user', USER_NS)
INK = '#173347'

# ----------------------------------------------------------------------------
# Data sources
# ----------------------------------------------------------------------------
# Numeric columns are measures unless listed here.
NUMERIC_DIMENSIONS = {
    'Crash ref', 'Crash year', 'Hour', 'Test year', 'Rank', 'Cell rank', 'First year', 'Last year',
    'Grid latitude', 'Grid longitude',
}
# Columns that look numeric but are labels.
TEXT_COLUMNS = {'Postcode'}
# Measures whose natural aggregate is an average. The two outcome indicators are
# blank for property-damage-only records, so their average is a share of injury crashes.
AVERAGED = {'Serious outcome', 'Fatal outcome', 'Latitude', 'Longitude'}
PERCENT_FORMAT = {'Serious outcome', 'Fatal outcome'}
GEOGRAPHIC_ROLE = {'Latitude': '[Geographical].[Latitude]', 'Longitude': '[Geographical].[Longitude]'}

CAPTIONS = {
    'crashes': 'Crashes (one row per crash)',
    'casualties': 'Road casualties (grouped)',
    'restraints': 'Restraints and helmets (grouped)',
    'crash_factors': 'Crash factors (grouped)',
    'vehicle_types': 'Vehicle types (grouped)',
    'driver_demographics': 'Driver demographics (grouped)',
    'result_region_road_mix': 'Result · region severity and road mix',
    'result_matched_odds': 'Result · matched odds ratios',
    'result_equipment_fatality_rates': 'Result · fatality rates by protection',
    'result_speed_severity_region_year': 'Result · speed and severity by region-year',
    'result_wet_dry_standardised': 'Result · wet and dry roads by lighting',
    'result_hotspots': 'Result · serious-crash hotspots',
    'result_hotspot_persistence': 'Result · hotspot persistence',
    'result_association_rules': 'Result · association rules',
    'result_model_summary': 'Result · model summary',
    'result_model_by_year': 'Result · model by test year',
    'result_model_confusion': 'Result · model confusion matrix',
    'result_model_precision_recall': 'Result · model precision and recall',
    'result_model_permutation_importance': 'Result · model permutation importance',
}

# Calculated fields: data source -> {caption: (formula, number format or None)}.
# Ratios are calculated from sums so that they stay correct under any filter.
CALCULATIONS = {
    'crashes': {
        'Fatalities per 100 injury crashes': ('100*SUM([Fatalities])/SUM([Injury crash])', 'n#,##0.00'),
    },
    'casualties': {
        'Fatalities per 100 casualties': ('100*SUM([Fatalities])/SUM([Casualties])', 'n#,##0.00'),
        'Fatal or hospitalised share': ('SUM([Fatal or hospitalised])/SUM([Casualties])', 'p0.0%'),
    },
    'restraints': {
        'Fatalities per 100 casualties': ('100*SUM([Fatalities])/SUM([Casualties])', 'n#,##0.00'),
        'Fatal or hospitalised share': ('SUM([Fatal or hospitalised])/SUM([Casualties])', 'p0.0%'),
    },
    **{name: {
        'Serious share of injury crashes': ('SUM([Serious crashes])/SUM([Injury crashes])', 'p0.0%'),
        'Fatal share of injury crashes': ('SUM([Fatal crashes])/SUM([Injury crashes])', 'p0.00%'),
    } for name in ('crash_factors', 'vehicle_types', 'driver_demographics')},
}


class Field:
    """One column of a data source, with the attributes Tableau needs to use it."""

    def __init__(self, name, datatype, role, kind, formula=None, number_format=None, internal=None):
        self.name, self.datatype, self.role, self.kind = name, datatype, role, kind
        self.formula, self.number_format = formula, number_format
        self.internal = internal or name          # calculated fields have an internal name and a caption

    def column_attributes(self):
        attributes = {'datatype': self.datatype, 'name': f'[{self.internal}]', 'role': self.role, 'type': self.kind}
        if self.formula:
            attributes['caption'] = self.name
        if self.number_format:
            attributes['default-format'] = self.number_format
        if self.name in AVERAGED:
            attributes['aggregation'] = 'Avg'
        if self.name in GEOGRAPHIC_ROLE:
            attributes['semantic-role'] = GEOGRAPHIC_ROLE[self.name]
        return attributes

    def add_column(self, parent):
        column = ET.SubElement(parent, 'column', self.column_attributes())
        if self.formula:
            ET.SubElement(column, 'calculation', {'class': 'tableau', 'formula': self.formula})
        return column


def sniff_type(values):
    """Classify a CSV column as integer, real or string from its non-blank values."""
    seen = [value for value in values if value != '']
    for datatype, convert in (('integer', int), ('real', float)):
        try:
            for value in seen:
                convert(value)
            return datatype
        except ValueError:
            continue
    return 'string'


class DataSource:
    """A packaged CSV file and the fields it offers."""

    def __init__(self, key, number):
        self.key, self.file = key, f'{key}.csv'
        self.name = f'federated.qld{number:02}{key.replace("_", "")}'[:40]
        self.connection = f'textscan.qld{number:02}'
        self.caption = CAPTIONS[key]
        with (DATA_DIR / self.file).open(newline='', encoding='utf-8') as handle:
            reader = csv.reader(handle)
            header = next(reader)
            # The crash table is large. Its first rows are enough to type the columns because
            # the notebook writes every column with a single type.
            sample = [row for _, row in zip(range(20_000), reader)]
        self.fields = {}
        for position, name in enumerate(header):
            datatype = 'string' if name in TEXT_COLUMNS else sniff_type(row[position] for row in sample)
            if datatype == 'string':
                role, kind = 'dimension', 'nominal'
            elif name in NUMERIC_DIMENSIONS:
                role, kind = 'dimension', 'ordinal'
            else:
                role, kind = 'measure', 'quantitative'
            self.fields[name] = Field(name, datatype, role, kind,
                                      number_format='p0.0%' if name in PERCENT_FORMAT else None)
        self.source_columns = list(self.fields.values())
        for index, (caption, (formula, number_format)) in enumerate(CALCULATIONS.get(key, {}).items(), start=1):
            for referenced in re.findall(r'\[([^\]]+)\]', formula):
                assert referenced in self.fields, (key, caption, referenced)
            self.fields[caption] = Field(caption, 'real', 'measure', 'quantitative', formula, number_format,
                                         internal=f'Calculation_{number:02}{index:02}0000000001')

    def metadata(self, parent, table_name):
        """Describe each stored column so Tableau can map it to a field."""
        records = ET.SubElement(parent, 'metadata-records')
        remote_types = {'string': '129', 'integer': '20', 'real': '5'}
        for ordinal, field in enumerate(self.source_columns):
            record = ET.SubElement(records, 'metadata-record', {'class': 'column'})
            for tag, text in [('remote-name', field.name), ('remote-type', remote_types[field.datatype]),
                              ('local-name', f'[{field.name}]'), ('parent-name', f'[{table_name}]'),
                              ('remote-alias', field.name), ('ordinal', str(ordinal)),
                              ('local-type', field.datatype),
                              ('aggregation', 'Count' if field.datatype == 'string' else 'Sum'),
                              ('contains-null', 'true')]:
                ET.SubElement(record, tag).text = text

    def to_xml(self, parent, mode):
        """Write the data source.

        mode 'extract': a CSV connection with an enabled extract, as Tableau writes after
        Data > Extract Data. mode 'direct': a connection straight to the .hyper file.
        """
        source = ET.SubElement(parent, 'datasource', {'caption': self.caption, 'inline': 'true',
                                                      'name': self.name, 'version': '18.1'})
        connection = ET.SubElement(source, 'connection', {'class': 'federated'})
        named = ET.SubElement(ET.SubElement(connection, 'named-connections'), 'named-connection',
                              {'caption': self.caption, 'name': self.connection})
        hyper_attributes = {'authentication': 'auth-none', 'author-locale': 'en_US', 'class': 'hyper',
                            'dbname': f'Data/Extracts/{self.key}.hyper', 'default-settings': 'yes',
                            'schema': 'Extract', 'tablename': 'Extract'}
        if mode == 'direct':
            ET.SubElement(named, 'connection', hyper_attributes)
            ET.SubElement(connection, 'relation', {'connection': self.connection, 'name': 'Extract',
                                                   'table': '[Extract].[Extract]', 'type': 'table'})
            self.metadata(connection, 'Extract')
        else:
            ET.SubElement(named, 'connection', {'class': 'textscan', 'directory': 'Data', 'filename': self.file,
                                                'password': '', 'server': ''})
            relation = ET.SubElement(connection, 'relation', {
                'connection': self.connection, 'name': self.file,
                'table': f'[{self.file.replace(".", "#")}]', 'type': 'table'})
            columns = ET.SubElement(relation, 'columns', {'character-set': 'UTF-8', 'header': 'yes',
                                                          'locale': 'en_AU', 'separator': ',',
                                                          'text-qualifier': '"'})
            for ordinal, field in enumerate(self.source_columns):
                ET.SubElement(columns, 'column', {'datatype': field.datatype, 'name': field.name,
                                                  'ordinal': str(ordinal)})
            cols = ET.SubElement(connection, 'cols')
            for field in self.source_columns:
                ET.SubElement(cols, 'map', {'key': f'[{field.name}]', 'value': f'[{self.file}].[{field.name}]'})
            self.metadata(connection, self.file)
        for field in self.fields.values():
            field.add_column(source)
        if mode == 'extract':
            # The enabled extract is what Tableau queries. The CSV connection above records its origin.
            # An empty object-id marks a single-table extract, as Tableau writes it.
            extract = ET.SubElement(source, 'extract', {'object-id': '', 'count': '-1', 'enabled': 'true',
                                                        'units': 'records'})
            stored = ET.SubElement(extract, 'connection', {**hyper_attributes, 'update-time': self.built})
            ET.SubElement(stored, 'relation', {'name': 'Extract', 'table': '[Extract].[Extract]', 'type': 'table'})
            self.metadata(stored, 'Extract')

    def write_extract(self, hyper):
        """Load the CSV into a .hyper file with the column types declared in the workbook."""
        from tableauhyperapi import Connection, CreateMode, SqlType, TableDefinition, TableName, escape_string_literal

        types = {'integer': SqlType.big_int(), 'real': SqlType.double(), 'string': SqlType.text()}
        table = TableDefinition(TableName('Extract', 'Extract'), [
            TableDefinition.Column(field.name, types[field.datatype]) for field in self.source_columns])
        with (DATA_DIR / self.file).open(newline='', encoding='utf-8') as handle:
            expected_rows = sum(1 for _ in csv.reader(handle)) - 1
        path = EXTRACT_DIR / f'{self.key}.hyper'
        with Connection(hyper.endpoint, path, CreateMode.CREATE_AND_REPLACE) as connection:
            connection.catalog.create_schema('Extract')
            connection.catalog.create_table(table)
            loaded = connection.execute_command(
                f"COPY {table.table_name} FROM {escape_string_literal(str(DATA_DIR / self.file))} "
                "WITH (FORMAT CSV, HEADER, DELIMITER ',', NULL '')")
        assert loaded == expected_rows, (self.key, loaded, expected_rows)
        self.built = datetime.now().strftime('%m/%d/%Y %I:%M:%S %p')
        return path


# ----------------------------------------------------------------------------
# Sheets
# ----------------------------------------------------------------------------
DERIVATIONS = {'sum': 'Sum', 'avg': 'Avg', 'none': 'None', 'usr': 'User'}


class Sheet:
    """One worksheet: fields on shelves and marks, plus the filters it shares with its data source."""

    def __init__(self, name, source, mark, rows=(), cols=(), color=None, size=None, text=None, detail=(),
                 tooltip=(), filters=(), sort=None, aggregate=True, labels=False):
        self.name, self.source, self.mark = name, source, mark
        self.rows, self.cols = list(rows), list(cols)
        self.color, self.size, self.text = color, size, text
        self.detail, self.tooltip, self.filters = list(detail), list(tooltip), list(filters)
        self.sort, self.aggregate, self.labels = sort, aggregate, labels or bool(text)

    def used(self):
        """Every (field, aggregation) pair the sheet refers to, in a stable order."""
        refs = [*self.rows, *self.cols, self.color, self.size, self.text, *self.detail, *self.tooltip,
                *[(name, 'none') for name in self.filters]]
        if self.sort:
            refs += [self.sort[0], self.sort[1]]
        ordered = []
        for ref in refs:
            if ref is not None and ref not in ordered:
                ordered.append(ref)
        return ordered


def ref(name, aggregation=None):
    """Shorthand for a field reference. Without an aggregation the field is used as a dimension."""
    return (name, aggregation or 'none')


def instance_name(source, reference):
    """Tableau's name for a field as used in a view, for example [sum:Crashes:qk]."""
    name, aggregation = reference
    field = source.fields[name]
    if field.formula:
        aggregation = 'usr'
    suffix = {'nominal': 'nk', 'ordinal': 'ok', 'quantitative': 'qk'}[
        field.kind if aggregation == 'none' else 'quantitative']
    return f'[{aggregation}:{field.internal}:{suffix}]'


def qualified(source, reference):
    return f'[{source.name}].{instance_name(source, reference)}'


def shelf(source, references):
    """Shelf expression: one field, or nested dimensions written as (a / (b / c))."""
    if not references:
        return None
    expression = qualified(source, references[-1])
    for reference in reversed(references[:-1]):
        expression = f'({qualified(source, reference)} / {expression})'
    return expression


def sheet_uuid(name):
    return '{' + str(uuid.uuid5(uuid.NAMESPACE_URL, f'qld-traffic-v5/{name}')).upper() + '}'


def add_dependencies(parent, source, references):
    """Declare the columns and column instances that a view or dashboard uses."""
    dependencies = ET.SubElement(parent, 'datasource-dependencies', {'datasource': source.name})
    needed = []
    for name, _ in references:
        field = source.fields[name]
        if field.formula:      # a calculation also needs the columns it reads
            for other in source.source_columns:
                if f'[{other.name}]' in field.formula and other not in needed:
                    needed.append(other)
        if field not in needed:
            needed.append(field)
    for field in needed:
        field.add_column(dependencies)
    for reference in references:
        field = source.fields[reference[0]]
        aggregation = 'usr' if field.formula else reference[1]
        kind = field.kind if aggregation == 'none' else 'quantitative'
        ET.SubElement(dependencies, 'column-instance', {
            'column': f'[{field.internal}]', 'derivation': DERIVATIONS[aggregation],
            'name': instance_name(source, reference), 'pivot': 'key', 'type': kind})


def sheet_xml(parent, sheet, sources, filter_groups):
    source = sources[sheet.source]
    worksheet = ET.SubElement(parent, 'worksheet', {'name': sheet.name})
    table = ET.SubElement(worksheet, 'table')
    view = ET.SubElement(table, 'view')
    ET.SubElement(ET.SubElement(view, 'datasources'), 'datasource', {'caption': source.caption, 'name': source.name})
    # A sheet with latitude on rows and longitude on columns is a map. Tableau draws its background
    # map only when the view itself names a map source, so declare it here as well as on the workbook.
    if sheet.rows == [LAT] and sheet.cols == [LON]:
        ET.SubElement(ET.SubElement(view, 'mapsources'), 'mapsource', {'name': 'Tableau'})
    add_dependencies(view, source, sheet.used())
    # Shared filters start with every value selected. Sheets on the same data source carry the
    # same filter-group number, so changing a filter on one sheet changes it on all of them.
    for name in sheet.filters:
        instance = instance_name(source, ref(name))
        filter_element = ET.SubElement(view, 'filter', {
            'class': 'categorical', 'column': f'[{source.name}].{instance}',
            'filter-group': str(filter_groups[(sheet.source, name)])})
        ET.SubElement(filter_element, 'groupfilter', {
            'function': 'level-members', 'level': instance,
            f'{{{USER_NS}}}ui-enumeration': 'all', f'{{{USER_NS}}}ui-marker': 'enumerate'})
    if sheet.sort:
        ET.SubElement(view, 'computed-sort', {'column': qualified(source, sheet.sort[0]), 'direction': 'DESC',
                                              'using': qualified(source, sheet.sort[1])})
    if sheet.filters:
        slices = ET.SubElement(view, 'slices')
        for name in sheet.filters:
            ET.SubElement(slices, 'column').text = qualified(source, ref(name))
    ET.SubElement(view, 'aggregation', {'value': 'true' if sheet.aggregate else 'false'})
    ET.SubElement(table, 'style')
    pane = ET.SubElement(ET.SubElement(table, 'panes'), 'pane',
                         {'id': '1', 'selection-relaxation-option': 'selection-relaxation-allow'})
    ET.SubElement(ET.SubElement(pane, 'view'), 'breakdown', {'value': 'auto'})
    ET.SubElement(pane, 'mark', {'class': sheet.mark})
    encodings = [('color', sheet.color), ('size', sheet.size), ('text', sheet.text),
                 *[('lod', item) for item in sheet.detail], *[('tooltip', item) for item in sheet.tooltip]]
    # Drop empty encodings, and tooltips that repeat a field already on colour, size or label.
    shown = {sheet.color, sheet.size, sheet.text}
    encodings = [(tag, item) for tag, item in encodings
                 if item is not None and not (tag == 'tooltip' and item in shown)]
    if encodings:
        holder = ET.SubElement(pane, 'encodings')
        for tag, item in encodings:
            ET.SubElement(holder, tag, {'column': qualified(source, item)})
    if sheet.labels:
        rule = ET.SubElement(ET.SubElement(pane, 'style'), 'style-rule', {'element': 'mark'})
        ET.SubElement(rule, 'format', {'attr': 'mark-labels-show', 'value': 'true'})
        ET.SubElement(rule, 'format', {'attr': 'mark-labels-cull', 'value': 'true'})
    ET.SubElement(table, 'rows').text = shelf(source, sheet.rows)
    ET.SubElement(table, 'cols').text = shelf(source, sheet.cols)
    ET.SubElement(worksheet, 'simple-id', {'uuid': sheet_uuid(sheet.name)})


# Shorthand used in the sheet list below.
INJURY = ref('Injury crash', 'sum')
SERIOUS = ref('Serious outcome', 'avg')
FATAL = ref('Fatal outcome', 'avg')
LAT, LON = ref('Latitude', 'avg'), ref('Longitude', 'avg')
CRASH_FILTERS = ['Crash year', 'Police region', 'Remoteness area', 'Speed zone', 'Severity']
CASUALTY_FILTERS = ['Crash year', 'Police region']
PER_100 = ref('Fatalities per 100 casualties')
FLAG_SHARE = ref('Serious share of injury crashes')


def crash_bar(name, dimension, measure, **options):
    """Horizontal bar of a crash measure by one dimension, largest first."""
    return Sheet(name, 'crashes', 'Bar', rows=[ref(dimension)], cols=[measure],
                 sort=(ref(dimension), measure), filters=CRASH_FILTERS,
                 tooltip=[item for item in (INJURY, SERIOUS, FATAL) if item != measure], **options)


def flag_bar(name, source, flag):
    """Serious share of injury crashes with and without one recorded flag."""
    return Sheet(name, source, 'Bar', rows=[ref(flag)], cols=[FLAG_SHARE], color=ref(flag), text=FLAG_SHARE,
                 tooltip=[ref('Injury crashes', 'sum'), ref('Fatal share of injury crashes')],
                 filters=CASUALTY_FILTERS)


SHEETS = [
    # --- Overview: crash-level, all filters apply -------------------------------------------
    Sheet('Recorded crashes by year and record type', 'crashes', 'Bar', rows=[ref('Crashes', 'sum')],
          cols=[ref('Crash year')], color=ref('Record type'), filters=CRASH_FILTERS),
    Sheet('Injury crashes by year and severity', 'crashes', 'Bar', rows=[INJURY], cols=[ref('Crash year')],
          color=ref('Severity'), filters=CRASH_FILTERS),
    Sheet('Serious share of injury crashes by year', 'crashes', 'Line', rows=[SERIOUS], cols=[ref('Crash year')],
          tooltip=[INJURY], filters=CRASH_FILTERS),
    Sheet('Fatal share of injury crashes by year', 'crashes', 'Line', rows=[FATAL], cols=[ref('Crash year')],
          tooltip=[INJURY, ref('Fatalities', 'sum')], filters=CRASH_FILTERS),
    crash_bar('Injury crashes by police region', 'Police region', INJURY, color=SERIOUS),
    # --- When -------------------------------------------------------------------------------
    Sheet('Serious share by day and hour', 'crashes', 'Square', rows=[ref('Day of week')], cols=[ref('Hour')],
          color=SERIOUS, text=SERIOUS, tooltip=[INJURY, FATAL], filters=CRASH_FILTERS),
    Sheet('Injury crashes by month', 'crashes', 'Bar', rows=[INJURY], cols=[ref('Month')], color=SERIOUS,
          filters=CRASH_FILTERS),
    Sheet('Injury crashes by hour and severity', 'crashes', 'Bar', rows=[INJURY], cols=[ref('Hour')],
          color=ref('Severity'), filters=CRASH_FILTERS),
    Sheet('Serious share by time band and weekend', 'crashes', 'Square', rows=[ref('Time band')],
          cols=[ref('Weekend')], color=SERIOUS, text=SERIOUS, tooltip=[INJURY, FATAL], filters=CRASH_FILTERS),
    # --- Where ------------------------------------------------------------------------------
    Sheet('Crash map (about 1 km grid)', 'crashes', 'Circle', rows=[LAT], cols=[LON], size=INJURY, color=SERIOUS,
          detail=[ref('Grid latitude'), ref('Grid longitude')], tooltip=[FATAL, ref('Fatalities', 'sum')],
          filters=CRASH_FILTERS),
    Sheet('Crash points (every crash)', 'crashes', 'Circle', rows=[LAT], cols=[LON], color=ref('Severity'),
          detail=[ref('Crash ref')], tooltip=[ref('Street'), ref('Suburb'), ref('Crash nature'),
                                              ref('Coordinate method')], filters=CRASH_FILTERS),
    Sheet('Serious share by remoteness and speed zone', 'crashes', 'Square', rows=[ref('Remoteness area')],
          cols=[ref('Speed zone')], color=SERIOUS, text=SERIOUS, tooltip=[INJURY, FATAL], filters=CRASH_FILTERS),
    crash_bar('Injury crashes by suburb', 'Suburb', INJURY, color=SERIOUS),
    crash_bar('Injury crashes by local government area', 'Local government area', INJURY, color=SERIOUS),
    # --- Road and crash type ----------------------------------------------------------------
    crash_bar('Injury crashes by crash nature', 'Crash nature', INJURY, color=SERIOUS),
    crash_bar('Fatal share by movement group', 'Movement group', FATAL),
    crash_bar('Serious share by roadway feature', 'Roadway feature', SERIOUS),
    crash_bar('Serious share by lighting', 'Lighting', SERIOUS),
    crash_bar('Serious share by horizontal alignment', 'Horizontal alignment', SERIOUS),
    crash_bar('Serious share by traffic control', 'Traffic control', SERIOUS),
    crash_bar('Serious share by controlling authority', 'Controlling authority', SERIOUS),
    crash_bar('Fatalities per 100 injury crashes by weather', 'Weather', ref('Fatalities per 100 injury crashes')),
    # --- Who: grouped casualty sources ------------------------------------------------------
    Sheet('Casualties by year and severity', 'casualties', 'Line', rows=[ref('Casualties', 'sum')],
          cols=[ref('Crash year')], color=ref('Casualty severity'), filters=CASUALTY_FILTERS),
    Sheet('Fatalities per 100 casualties by age and road user', 'casualties', 'Square', rows=[ref('Age group')],
          cols=[ref('Road user')], color=PER_100, text=PER_100,
          tooltip=[ref('Casualties', 'sum'), ref('Fatalities', 'sum')], filters=CASUALTY_FILTERS),
    Sheet('Fatalities per 100 casualties by protection', 'restraints', 'Bar',
          rows=[ref('Road user'), ref('Restraint or helmet use')], cols=[PER_100], text=PER_100,
          tooltip=[ref('Casualties', 'sum'), ref('Fatalities', 'sum')], filters=CASUALTY_FILTERS),
    flag_bar('Serious share with recorded speed', 'crash_factors', 'Driver Speed'),
    flag_bar('Serious share with drink driving', 'crash_factors', 'Drink Driving'),
    flag_bar('Serious share with a motorcycle or moped', 'vehicle_types', 'Motorcycle Moped'),
    flag_bar('Serious share with a young driver', 'driver_demographics', 'Young Driver 16–24'),
    # --- Like for like: fixed-period notebook results ---------------------------------------
    Sheet('Region severity and road mix 2020–2024', 'result_region_road_mix', 'Bar', rows=[ref('Police region')],
          cols=[ref('Recorded share (%)', 'avg')], color=ref('Recorded ÷ expected', 'avg'),
          text=ref('Recorded ÷ expected', 'avg'),
          tooltip=[ref('Expected share from road mix (%)', 'avg'), ref('Ratio 95% low', 'avg'),
                   ref('Ratio 95% high', 'avg'), ref('Injury crashes', 'sum')],
          sort=(ref('Police region'), ref('Recorded share (%)', 'avg'))),
    Sheet('Matched odds of a serious outcome 2020–2024', 'result_matched_odds', 'Circle', rows=[ref('Flag')],
          cols=[ref('Matched-region/year odds ratio', 'avg')], text=ref('Matched-region/year odds ratio', 'avg'),
          tooltip=[ref('95% low', 'avg'), ref('95% high', 'avg'), ref('Pooled odds ratio', 'avg'),
                   ref('Crashes with flag', 'sum')],
          sort=(ref('Flag'), ref('Matched-region/year odds ratio', 'avg'))),
    Sheet('Fatality rates by protection 2015–2024', 'result_equipment_fatality_rates', 'Circle',
          rows=[ref('Road user'), ref('Restraint or helmet use')],
          cols=[ref('Fatalities per 100 casualties', 'avg')], text=ref('Fatalities per 100 casualties', 'avg'),
          tooltip=[ref('95% low', 'avg'), ref('95% high', 'avg'), ref('Casualties', 'sum'),
                   ref('Fatalities', 'sum')]),
    Sheet('Speed and severity, region-years pooled', 'result_speed_severity_region_year', 'Circle',
          rows=[ref('Serious share (%)', 'avg')], cols=[ref('Speed involvement (%)', 'avg')],
          color=ref('Police region'), detail=[ref('Crash year')]),
    Sheet('Speed and severity within region and year', 'result_speed_severity_region_year', 'Circle',
          rows=[ref('Serious share deviation (pp)', 'avg')], cols=[ref('Speed deviation (pp)', 'avg')],
          color=ref('Police region'), detail=[ref('Crash year')]),
    Sheet('Wet and dry roads by lighting 2020–2024', 'result_wet_dry_standardised', 'Square',
          rows=[ref('Lighting')], cols=[ref('Road surface')],
          color=ref('Fatal or hospitalisation share (%)', 'avg'),
          text=ref('Fatal or hospitalisation share (%)', 'avg')),
    Sheet('Conditions associated with serious outcomes', 'result_association_rules', 'Bar',
          rows=[ref('Conditions')], cols=[ref('Lift', 'avg')], color=ref('Serious share', 'avg'),
          tooltip=[ref('Serious crashes', 'sum'), ref('Support', 'avg')],
          sort=(ref('Conditions'), ref('Lift', 'avg'))),
    # --- Hotspots ---------------------------------------------------------------------------
    Sheet('Serious-crash hotspot map 2011–2024', 'result_hotspots', 'Circle', rows=[LAT], cols=[LON],
          size=ref('Serious crashes', 'sum'), color=ref('Fatal crashes', 'sum'), detail=[ref('Rank')],
          tooltip=[ref('Main street'), ref('Intersecting street'), ref('Suburb'), ref('Extent (m)', 'avg')]),
    Sheet('Serious-crash hotspot list 2011–2024', 'result_hotspots', 'Bar',
          rows=[ref('Rank'), ref('Suburb'), ref('Main street')], cols=[ref('Serious crashes', 'sum')],
          color=ref('Fatal crashes', 'sum'), tooltip=[ref('Intersecting street'), ref('Police region')]),
    Sheet('Do the top 100 grid cells stay on top', 'result_hotspot_persistence', 'Circle',
          rows=[ref('Serious crashes 2020–2024', 'avg')], cols=[ref('Serious crashes 2015–2019', 'avg')],
          detail=[ref('Cell rank')]),
    # --- Model evaluation -------------------------------------------------------------------
    Sheet('Model summary', 'result_model_summary', 'Bar', rows=[ref('Model')],
          cols=[ref('Fatal average precision', 'avg')], text=ref('Fatal average precision', 'avg'),
          tooltip=[ref('Accuracy', 'avg'), ref('Macro F1', 'avg'), ref('Fatal recall', 'avg'),
                   ref('Fatal precision', 'avg')]),
    *[Sheet(name, 'result_model_by_year', 'Square', rows=[ref('Model')], cols=[ref('Test period')],
            color=ref(measure, aggregation), text=ref(measure, aggregation),
            tooltip=[ref('Test crashes', 'sum'), ref('Actual fatal crashes', 'sum')])
      for name, measure, aggregation in [
          ('Fatal recall by test year', 'Fatal recall (%)', 'avg'),
          ('Fatal precision by test year', 'Fatal precision (%)', 'avg'),
          ('Missed fatal crashes by test year', 'Missed fatal crashes', 'sum'),
          ('False fatal alerts by test year', 'False fatal alerts', 'sum')]],
    Sheet('Model confusion matrix', 'result_model_confusion', 'Square',
          rows=[ref('Model'), ref('Actual severity')], cols=[ref('Predicted severity')],
          color=ref('Share of actual', 'avg'), text=ref('Share of actual', 'avg'),
          tooltip=[ref('Crashes', 'sum')]),
    Sheet('Fatal precision and recall', 'result_model_precision_recall', 'Circle',
          rows=[ref('Fatal precision', 'avg')], cols=[ref('Fatal recall', 'avg')], color=ref('Model'),
          aggregate=False),
    Sheet('Model permutation importance', 'result_model_permutation_importance', 'Bar',
          rows=[ref('Input field')], cols=[ref('Mean drop in fatal average precision', 'avg')],
          tooltip=[ref('Standard deviation', 'avg')],
          sort=(ref('Input field'), ref('Mean drop in fatal average precision', 'avg'))),
]

# ----------------------------------------------------------------------------
# Dashboards
# ----------------------------------------------------------------------------
# Each dashboard: title, note, sheets laid out on a grid, the sheet that owns its quick filters,
# and whether clicking a mark filters the other sheets (only where all sheets share a data source).
FILTER_NOTE = ('Use the filters on the right. Click a mark to filter the other charts, and click it again to clear. '
               'Shares are of recorded injury crashes, so they describe severity, not the risk of crashing.')
DASHBOARDS = [
    dict(name='Start here', title='Queensland traffic crashes  ·  V5',
         note='Property-damage-only crashes are recorded to 2010 only, so the charts count injury crashes. '
              '2025 is a partial year. ' + FILTER_NOTE,
         grid=[['Recorded crashes by year and record type', 'Injury crashes by year and severity'],
               ['Serious share of injury crashes by year', 'Injury crashes by police region']],
         filters=('Injury crashes by year and severity', 'crashes', CRASH_FILTERS), action=True),
    dict(name='When', title='When crashes happen and when they are most severe',
         note='Colour and labels show the share of injury crashes that were fatal or led to hospitalisation. '
              + FILTER_NOTE,
         grid=[['Serious share by day and hour', 'Serious share by day and hour'],
               ['Injury crashes by month', 'Injury crashes by hour and severity']],
         filters=('Serious share by day and hour', 'crashes', CRASH_FILTERS), action=True),
    dict(name='Where', title='Where crashes happen',
         note='The map groups crashes into cells of about 1 km. Size shows injury crashes and colour shows the '
              'serious share. Open the sheet "Crash points (every crash)" for individual crashes. ' + FILTER_NOTE,
         grid=[['Crash map (about 1 km grid)', 'Serious share by remoteness and speed zone'],
               ['Crash map (about 1 km grid)', 'Injury crashes by local government area']],
         filters=('Crash map (about 1 km grid)', 'crashes', CRASH_FILTERS), action=True),
    dict(name='Road and crash type', title='Road setting, crash type and severity',
         note=FILTER_NOTE,
         grid=[['Injury crashes by crash nature', 'Fatal share by movement group'],
               ['Serious share by roadway feature', 'Serious share by lighting']],
         filters=('Injury crashes by crash nature', 'crashes', CRASH_FILTERS), action=True),
    dict(name='Who', title='Casualties, protection and recorded flags',
         note='These charts use the grouped source files, which share only crash year and police region with the '
              'crash table. The two filters apply to the casualty charts. Rates are fatalities per 100 recorded '
              'casualties. Uninjured people are not in the data.',
         grid=[['Casualties by year and severity', 'Fatalities per 100 casualties by age and road user'],
               ['Fatalities per 100 casualties by protection', 'Serious share with a young driver']],
         filters=('Casualties by year and severity', 'casualties', CASUALTY_FILTERS), action=False),
    dict(name='Like for like', title='Comparisons that allow for differences in mix  ·  fixed periods',
         note='Calculated in the notebook for 2020–2024 and unaffected by filters. Recorded ÷ expected compares each '
              "region's serious crashes with the number its mix of remoteness and speed zone predicts. Odds ratios "
              'compare crashes within the same year and police region. Hover for 95% intervals.',
         grid=[['Region severity and road mix 2020–2024', 'Matched odds of a serious outcome 2020–2024'],
               ['Speed and severity, region-years pooled', 'Speed and severity within region and year']],
         filters=None, action=False),
    dict(name='Hotspots', title='Serious-crash hotspots  ·  2011–2024',
         note='A hotspot has at least ten fatal or hospitalisation crashes, each within 50 m of another. Counts '
              'reflect traffic volume as well as risk. The scatter follows the 100 grid cells with the most serious '
              'crashes in 2015–2019 into 2020–2024: most record fewer, so expect a fall at any site chosen for a '
              'high count.',
         grid=[['Serious-crash hotspot map 2011–2024', 'Serious-crash hotspot list 2011–2024'],
               ['Serious-crash hotspot map 2011–2024', 'Do the top 100 grid cells stay on top']],
         filters=None, action=False),
    dict(name='Model evaluation', title='Severity models on held-out crashes  ·  2023–2025',
         note='Each cell is one model and test year. Precision is blank when a model made no fatal predictions. '
              'The partial 2025 release covers fewer months. About 1.9% of test crashes were fatal, which is the '
              'precision a random ranking would achieve.',
         grid=[['Fatal recall by test year', 'Fatal precision by test year', 'False fatal alerts by test year'],
               ['Fatal precision and recall', 'Model confusion matrix', 'Model permutation importance']],
         filters=None, action=False),
]
WIDTH, HEIGHT = 1400, 880


def grid_zones(grid, left, top, width, height, gap=600):
    """Turn a grid of sheet names into zones. A name repeated in adjacent cells spans them."""
    rows, columns = len(grid), len(grid[0])
    cell_w, cell_h = (width - gap * (columns - 1)) / columns, (height - gap * (rows - 1)) / rows
    spans = {}
    for r, row in enumerate(grid):
        for c, name in enumerate(row):
            r0, c0, r1, c1 = spans.get(name, (r, c, r, c))
            spans[name] = (min(r0, r), min(c0, c), max(r1, r), max(c1, c))
    for name, (r0, c0, r1, c1) in spans.items():
        yield name, (round(left + c0 * (cell_w + gap)), round(top + r0 * (cell_h + gap)),
                     round((c1 - c0 + 1) * cell_w + (c1 - c0) * gap), round((r1 - r0 + 1) * cell_h + (r1 - r0) * gap))


def dashboard_xml(parent, spec, sources, zone_ids):
    dashboard = ET.SubElement(parent, 'dashboard', {'name': spec['name']})
    ET.SubElement(dashboard, 'size', {'sizing-mode': 'fixed', 'minwidth': str(WIDTH), 'maxwidth': str(WIDTH),
                                      'minheight': str(HEIGHT), 'maxheight': str(HEIGHT)})
    holder = ET.SubElement(dashboard, 'datasources')
    if spec['filters']:
        _, source_key, names = spec['filters']
        source = sources[source_key]
        ET.SubElement(holder, 'datasource', {'caption': source.caption, 'name': source.name})
        add_dependencies(dashboard, source, [ref(name) for name in names])
    root = ET.SubElement(ET.SubElement(dashboard, 'zones'), 'zone', {
        'x': '0', 'y': '0', 'w': '100000', 'h': '100000', 'id': str(next(zone_ids)),
        'type-v2': 'layout-basic', 'layout-strategy-id': 'free-form'})

    def zone(x, y, w, h, **attributes):
        return ET.SubElement(root, 'zone', {'x': str(x), 'y': str(y), 'w': str(w), 'h': str(h),
                                            'id': str(next(zone_ids)), **attributes})

    def text_zone(x, y, w, h, text, size, bold):
        run = ET.SubElement(ET.SubElement(zone(x, y, w, h, **{'type-v2': 'text'}), 'formatted-text'), 'run',
                            {'fontsize': str(size), 'bold': 'true' if bold else 'false', 'fontcolor': INK})
        run.text = text

    text_zone(1200, 1000, 97000, 4600, spec['title'], 19, True)
    text_zone(1200, 5800, 97000, 7200, spec['note'], 10, False)
    chart_width = 82500 if spec['filters'] else 97600
    for name, (x, y, w, h) in grid_zones(spec['grid'], 1200, 13600, chart_width, 85200):
        zone(x, y, w, h, name=name, **{'show-title': 'true'})
    if spec['filters']:
        owner, source_key, names = spec['filters']
        source = sources[source_key]
        for position, name in enumerate(names):
            zone(84600, 13600 + position * 9000, 14200, 8400, name=owner, mode='checkdropdown',
                 param=qualified(source, ref(name)), **{'type-v2': 'filter'})
    ET.SubElement(dashboard, 'simple-id', {'uuid': sheet_uuid('dashboard/' + spec['name'])})


# ----------------------------------------------------------------------------
# Workbook assembly
# ----------------------------------------------------------------------------
def worksheet_window(parent, name):
    window = ET.SubElement(parent, 'window', {'name': name, 'class': 'worksheet'})
    cards = ET.SubElement(window, 'cards')
    left = ET.SubElement(ET.SubElement(cards, 'edge', {'name': 'left'}), 'strip', {'size': '185'})
    for card in ('pages', 'filters', 'marks'):
        ET.SubElement(left, 'card', {'type': card})
    top = ET.SubElement(cards, 'edge', {'name': 'top'})
    for card, size in (('columns', '2147483647'), ('rows', '2147483647'), ('title', '30')):
        ET.SubElement(ET.SubElement(top, 'strip', {'size': size}), 'card', {'type': card})
    ET.SubElement(ET.SubElement(window, 'viewpoint'), 'zoom', {'type': 'entire-view'})
    ET.SubElement(window, 'simple-id', {'uuid': sheet_uuid(name)})


def workbook_xml(sources, mode):
    """Check the specifications and return the workbook XML for one data-source mode."""
    tables = sorted(path.stem for path in DATA_DIR.glob('*.csv'))
    assert set(tables) == set(CAPTIONS), set(tables) ^ set(CAPTIONS)
    # ---- consistency checks before anything is written ----
    sheet_names = [sheet.name for sheet in SHEETS]
    assert len(set(sheet_names)) == len(sheet_names), 'duplicate sheet name'
    for sheet in SHEETS:
        for name, aggregation in sheet.used():
            field = sources[sheet.source].fields.get(name)
            assert field is not None, f'{sheet.name}: no field "{name}" in {sheet.source}'
            assert aggregation == 'none' or field.role == 'measure', f'{sheet.name}: "{name}" is not a measure'
            assert aggregation != 'none' or field.role == 'dimension' or field.formula, \
                f'{sheet.name}: measure "{name}" needs an aggregation'
    for spec in DASHBOARDS:
        placed = {name for row in spec['grid'] for name in row}
        assert placed <= set(sheet_names), (spec['name'], placed - set(sheet_names))
        assert spec['name'] not in sheet_names
        if spec['filters']:
            owner, source_key, names = spec['filters']
            owner_sheet = SHEETS[sheet_names.index(owner)]
            assert owner in placed and owner_sheet.source == source_key and set(names) <= set(owner_sheet.filters)
        if spec['action']:
            assert len({SHEETS[sheet_names.index(name)].source for name in placed}) == 1, spec['name']

    # One filter-group number per (data source, field), shared by every sheet that carries it.
    filter_groups = {}
    for sheet in SHEETS:
        for name in sheet.filters:
            filter_groups.setdefault((sheet.source, name), len(filter_groups) + 2)

    workbook = ET.Element('workbook', {'original-version': '18.1', 'source-build': '2026.1.0 (20261.26.0310.1200)',
                                       'source-platform': 'win', 'version': '18.1'})
    manifest = ET.SubElement(workbook, 'document-format-change-manifest')
    for feature in ('SheetIdentifierTracking', 'SortTagCleanup', 'WindowsPersistSimpleIdentifiers'):
        ET.SubElement(manifest, feature)
    ET.SubElement(workbook, 'preferences')
    ET.SubElement(workbook, 'style')      # Tableau's loader expects this element, even when empty
    holder = ET.SubElement(workbook, 'datasources')
    for source in sources.values():
        source.to_xml(holder, mode)
    # The maps use Tableau's own background map with the latitude and longitude fields.
    ET.SubElement(ET.SubElement(workbook, 'mapsources'), 'mapsource', {'name': 'Tableau'})
    actions = ET.SubElement(workbook, 'actions')
    for number, spec in enumerate([spec for spec in DASHBOARDS if spec['action']], start=1):
        action = ET.SubElement(actions, 'action', {'caption': f'Filter {spec["name"]} by selected mark',
                                                   'name': f'[Action{number}]'})
        ET.SubElement(action, 'activation', {'auto-clear': 'true', 'type': 'on-select'})
        ET.SubElement(action, 'source', {'dashboard': spec['name'], 'type': 'sheet'})
        command = ET.SubElement(action, 'command', {'command': 'tsc:tsl-filter'})
        ET.SubElement(command, 'param', {'name': 'special-fields', 'value': 'all'})
        ET.SubElement(command, 'param', {'name': 'target', 'value': spec['name']})
    worksheets = ET.SubElement(workbook, 'worksheets')
    for sheet in SHEETS:
        sheet_xml(worksheets, sheet, sources, filter_groups)
    dashboards = ET.SubElement(workbook, 'dashboards')
    zone_ids = iter(range(1, 10_000))
    for spec in DASHBOARDS:
        dashboard_xml(dashboards, spec, sources, zone_ids)
    windows = ET.SubElement(workbook, 'windows', {'source-height': '30'})
    for position, spec in enumerate(DASHBOARDS):
        window = ET.SubElement(windows, 'window', {'name': spec['name'], 'class': 'dashboard',
                                                   **({'maximized': 'true'} if position == 0 else {})})
        viewpoints = ET.SubElement(window, 'viewpoints')
        for name in dict.fromkeys(name for row in spec['grid'] for name in row):
            ET.SubElement(ET.SubElement(viewpoints, 'viewpoint', {'name': name}), 'zoom', {'type': 'entire-view'})
        ET.SubElement(window, 'active', {'id': '-1'})
        ET.SubElement(window, 'simple-id', {'uuid': sheet_uuid('dashboard/' + spec['name'])})
    for sheet in SHEETS:
        worksheet_window(windows, sheet.name)
    # No <explain-data> element: older Tableau versions reject it when loading the workbook.

    ET.indent(workbook, space='  ')
    xml_text = "<?xml version='1.0' encoding='utf-8'?>\n" + ET.tostring(workbook, encoding='unicode') + '\n'
    ET.fromstring(xml_text.encode('utf-8'))      # the written text must parse

    return xml_text


def package(destination, xml_text, sources, include_csv):
    """Zip the workbook and its data. Write beside the destination first so a failed build keeps the old file."""
    temporary = destination.with_suffix('.twbx.tmp')
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(TWB_NAME, xml_text)
        for source in sources.values():
            archive.write(EXTRACT_DIR / f'{source.key}.hyper', f'Data/Extracts/{source.key}.hyper')
            if include_csv:
                archive.write(DATA_DIR / source.file, f'Data/{source.file}')
    temporary.replace(destination)
    print(f'Wrote {destination.name}: {len(sources)} data sources, {len(SHEETS)} sheets, '
          f'{len(DASHBOARDS)} dashboards, {destination.stat().st_size / 1e6:.1f} MB.')


def build():
    from tableauhyperapi import HyperProcess, Telemetry

    sources = {key: DataSource(key, number) for number, key in enumerate(CAPTIONS, start=1)}
    # Build one extract per table. The same .hyper files serve all three workbook files.
    EXTRACT_DIR.mkdir(exist_ok=True)
    with HyperProcess(Telemetry.DO_NOT_SEND_USAGE_DATA_TO_TABLEAU, parameters={'log_config': ''}) as hyper:
        for source in sources.values():
            source.write_extract(hyper)
    print(f'Wrote {len(sources)} extracts to {EXTRACT_DIR.relative_to(BASE)}/.')

    # Main workbook: each CSV source carries an enabled extract.
    xml_text = workbook_xml(sources, 'extract')
    package(WORKBOOK, xml_text, sources, include_csv=True)

    # Unpackaged copy of the same workbook. It reads from the `Tableau data V5` folder beside it,
    # so the two must stay together.
    replacements = {'directory="Data"': f'directory="{DATA_DIR.name}"',
                    'dbname="Data/Extracts/': f'dbname="{DATA_DIR.name}/Extracts/'}
    standalone_text = xml_text
    for packaged, unpackaged in replacements.items():
        assert standalone_text.count(packaged) == len(sources), packaged
        standalone_text = standalone_text.replace(packaged, unpackaged)
    standalone = BASE / TWB_NAME
    temporary = standalone.with_suffix('.twb.tmp')
    temporary.write_text(standalone_text, encoding='utf-8')
    temporary.replace(standalone)
    print(f'Wrote {standalone.name}: reads its data from {DATA_DIR.name}/.')

    # Alternative workbook that connects straight to the extracts, without the CSV connection.
    package(ALTERNATIVE, workbook_xml(sources, 'direct'), sources, include_csv=False)


if __name__ == '__main__':
    build()
