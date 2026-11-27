"""Road-network sites for crash screening (V6 onwards).

Builds two kinds of site from the Queensland Roads and Tracks layer and assigns crashes to them:

* **Junctions.** Segment end points shared by three or more segment ends. Junction nodes
  within `JUNCTION_MERGE_M` of each other are merged, so a dual-carriageway or staggered junction
  is one site.
* **Links.** Runs of same-named segments joined end to end at points where only those two
  segments meet. A link therefore runs from junction to junction (or to a name change), which is the
  homogeneous-segment unit used in network screening.

Crashes coded with an intersection roadway feature go to the nearest junction within
`JUNCTION_SNAP_M`. Every other crash, and intersection crashes with no junction in range, go to the
nearest road segment within `LINK_SNAP_M` and take that segment's link. Unassigned crashes keep a
blank site.

Only geometry lives here. The screening statistics stay in the notebook.
"""
from dataclasses import dataclass
from gzip import open as gzip_open
import hashlib
from pathlib import Path
import pickle

import ijson
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
import shapely
from shapely import STRtree, line_merge, union_all

from traffic_spatial_lookup import FORWARD, INVERSE

JUNCTION_MERGE_M = 25
JUNCTION_SNAP_M = 40
LINK_SNAP_M = 30
NODE_GRID_M = 0.5


@dataclass
class RoadNetwork:
    names: np.ndarray            # road name per segment part
    segment_ids: np.ndarray      # source segment_id per part
    lines: np.ndarray            # shapely LineStrings in EPSG:9473 metres
    link: np.ndarray             # link number per part
    link_names: np.ndarray       # road name per link
    link_length_m: np.ndarray    # total length per link
    junction_xy: np.ndarray      # (n, 2) merged junction centres
    junction_names: list         # names of the roads meeting at each junction
    junction_arms: np.ndarray    # segment ends meeting at each junction
    node_xy: np.ndarray          # junction nodes before merging
    node_junction: np.ndarray    # merged junction for each node
    source_features: int

    _tree: STRtree | None = None

    @property
    def tree(self):
        if self._tree is None:
            self._tree = STRtree(self.lines)
        return self._tree


class _UnionFind:
    def __init__(self, size):
        self.parent = np.arange(size)

    def find(self, item):
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)

    def labels(self):
        roots = np.array([self.find(i) for i in range(len(self.parent))])
        return pd.factorize(roots)[0]


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _read_parts(path):
    names, segment_ids, coords, part_index = [], [], [], []
    count = 0
    with gzip_open(path, 'rb') as handle:
        for feature in ijson.items(handle, 'features.item', use_float=True):
            count += 1
            geometry = feature.get('geometry')
            if not geometry:
                continue
            paths = ([geometry['coordinates']] if geometry['type'] == 'LineString'
                     else geometry['coordinates'] if geometry['type'] == 'MultiLineString' else [])
            props = feature['properties']
            name = (props.get('road_name_full') or '').strip()
            for path_coords in paths:
                if len(path_coords) < 2:
                    continue
                part = len(names)
                names.append(name)
                segment_ids.append(str(props.get('segment_id')))
                coords.extend(point[:2] for point in path_coords)
                part_index.extend([part] * len(path_coords))
    return names, segment_ids, np.asarray(coords, dtype=float), np.asarray(part_index), count


def build_network(roads_path):
    names, segment_ids, lonlat, part_index, count = _read_parts(roads_path)
    x, y = FORWARD(lonlat[:, 0], lonlat[:, 1])
    xy = np.column_stack([x, y])
    lines = shapely.linestrings(xy, indices=part_index)
    names = np.asarray(names, dtype=object)

    # End points of every part, snapped to a fine grid so touching ends share one node.
    starts = np.r_[0, np.flatnonzero(np.diff(part_index)) + 1]
    ends = np.r_[starts[1:] - 1, len(part_index) - 1]
    end_xy = np.vstack([xy[starts], xy[ends]])
    end_part = np.r_[np.arange(len(starts)), np.arange(len(starts))]
    keys = np.round(end_xy / NODE_GRID_M).astype(np.int64)
    node, unique_index = np.unique(keys, axis=0, return_inverse=True)
    node_of_end = unique_index.ravel()
    degree = np.bincount(node_of_end)

    # Links: join two same-named parts where only they meet.
    links = _UnionFind(len(starts))
    order = np.argsort(node_of_end, kind='stable')
    sorted_nodes = node_of_end[order]
    boundaries = np.r_[0, np.flatnonzero(np.diff(sorted_nodes)) + 1, len(order)]
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        if right - left != 2:
            continue
        a, b = end_part[order[left]], end_part[order[left + 1]]
        if a != b and names[a] and names[a].casefold() == names[b].casefold():
            links.union(a, b)
    link = links.labels()
    lengths = shapely.length(lines)
    link_length = np.bincount(link, weights=lengths)
    link_names = pd.Series(names).groupby(link).first().to_numpy()

    # Junctions: nodes where three or more part ends meet, merged when close together.
    junction_nodes = np.flatnonzero(degree >= 3)
    node_xy = node[junction_nodes] * NODE_GRID_M
    merge = _UnionFind(len(junction_nodes))
    for a, b in cKDTree(node_xy).query_pairs(JUNCTION_MERGE_M):
        merge.union(a, b)
    node_junction = merge.labels()
    junction_xy = np.column_stack([
        np.bincount(node_junction, weights=node_xy[:, i]) / np.bincount(node_junction) for i in range(2)
    ])
    junction_arms = np.bincount(node_junction, weights=degree[junction_nodes]).astype(int)
    position = {node_id: i for i, node_id in enumerate(junction_nodes)}
    junction_road_names = [dict() for _ in range(len(junction_xy))]
    for end, node_id in enumerate(node_of_end):
        i = position.get(node_id)
        if i is not None and names[end_part[end]]:
            counter = junction_road_names[node_junction[i]]
            label = names[end_part[end]]
            counter[label] = counter.get(label, 0) + 1
    junction_names = [' / '.join(sorted(counter, key=lambda name: (-counter[name], name))[:3])
                      for counter in junction_road_names]
    return RoadNetwork(
        names=names, segment_ids=np.asarray(segment_ids, dtype=object), lines=lines, link=link,
        link_names=link_names, link_length_m=link_length, junction_xy=junction_xy,
        junction_names=junction_names, junction_arms=junction_arms, node_xy=node_xy,
        node_junction=node_junction, source_features=count,
    )


def load_network(roads_path, cache_dir=None):
    """Build the junction and link network, reusing a cached copy when the inputs are unchanged."""
    roads_path = Path(roads_path)
    cache_file = None
    if cache_dir is not None:
        key = hashlib.sha256((_digest(roads_path) + _digest(__file__)).encode()).hexdigest()[:20]
        cache_file = Path(cache_dir) / f'road_network_{key}.pkl'
        if cache_file.is_file():
            with cache_file.open('rb') as stream:
                return pickle.load(stream)
    network = build_network(roads_path)
    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            pickle.dump(network, stream)
        temporary.replace(cache_file)
    return network


def assign_sites(network, longitude, latitude, at_intersection):
    """Site for each crash point: junction for intersection crashes in range, otherwise the nearest link.

    Returns a DataFrame aligned to the inputs with `Site`, `Site type`, `Site number` and `Snap distance (m)`.
    """
    longitude, latitude = np.asarray(longitude, float), np.asarray(latitude, float)
    at_intersection = np.asarray(at_intersection, bool)
    x, y = FORWARD(longitude, latitude)
    xy = np.column_stack([x, y])
    site_type = np.full(len(xy), None, dtype=object)
    site_number = np.full(len(xy), -1)
    distance = np.full(len(xy), np.nan)

    if len(network.node_xy):
        node_distance, node = cKDTree(network.node_xy).query(xy[at_intersection],
                                                             distance_upper_bound=JUNCTION_SNAP_M)
        found = np.isfinite(node_distance)
        rows = np.flatnonzero(at_intersection)[found]
        site_type[rows] = 'Junction'
        site_number[rows] = network.node_junction[node[found]]
        distance[rows] = node_distance[found]

    remaining = np.flatnonzero(site_type == None)  # noqa: E711 - object array comparison
    points = shapely.points(xy[remaining])
    (point_index, part_index), part_distance = network.tree.query_nearest(
        points, max_distance=LINK_SNAP_M, return_distance=True, all_matches=False)
    rows = remaining[point_index]
    site_type[rows] = 'Link'
    site_number[rows] = network.link[part_index]
    distance[rows] = part_distance

    site = pd.Series(site_type).map({'Junction': 'J', 'Link': 'L'}) + pd.Series(site_number).astype(str)
    return pd.DataFrame({
        'Site': site.where(pd.Series(site_type).notna()),
        'Site type': site_type,
        'Site number': site_number,
        'Snap distance (m)': distance.round(1),
    })


def site_label(network, site_type, site_number):
    if site_type == 'Junction':
        return network.junction_names[site_number] or 'Unnamed junction'
    return network.link_names[site_number] or 'Unnamed road'


def site_geometry_lonlat(network, site_type, site_number, tolerance_m=5):
    """Site location in longitude/latitude: a point for a junction, a simplified line for a link."""
    if site_type == 'Junction':
        x, y = network.junction_xy[site_number]
        return shapely.points(*INVERSE(x, y))
    merged = line_merge(union_all(network.lines[network.link == site_number])).simplify(tolerance_m)
    return shapely.transform(merged, lambda coords: np.column_stack(INVERSE(coords[:, 0], coords[:, 1])))
