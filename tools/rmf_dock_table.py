#!/usr/bin/env python3
"""
Emit the start-dock table the robots use to seed AMCL, derived from the nav
graph rather than typed by hand.

Why this exists
---------------
A jetracer joining the fleet needs a full pose to seed AMCL with
(`set_initial_pose: true` + `initial_pose.{x,y,yaw}`), but nothing in the RMF
pipeline carries one:

  - x, y  exist, in the RMF frame, as named vertices in the generated nav graph.
          They need the RMF->robot transform applied to reach the frame AMCL
          actually wants (the robot's `map`).
  - yaw   does not exist anywhere. A traffic-editor vertex is
          [px, py, z, name, params] -- that third field is elevation, not
          heading -- and the generated graph keeps only x/y/params. RMF has no
          use for a parking heading, so it never records one.

So yaw comes from a placement convention ("park every robot facing local
south"), and x/y come from here. Hand-copying x/y instead would rot the moment
the lab is re-SLAMmed: the 2026-07-29 remap moved origin [-4.42,-6.06] ->
[-9.43,-4.17] and the grid 192x245 -> 269x273, silently invalidating every
coordinate written down before it. Same principle as rmf_map_calib.py --
compute it, don't click it.

The transform is fitted from the `reference_coordinates` block in the fleet
config, not hardcoded, so re-running after a remap is the whole update
procedure. The fit is a full 2D similarity (rotation + uniform scale +
translation); for the jetracer lab it comes out as a pure translation, which is
what makes a single yaw convention valid in both frames at once. If a rotation
ever does appear, it is applied to yaw as well and called out in the summary --
silently keeping the RMF-frame heading would put every robot's seed off by
exactly that angle.

Start points are not chargers
-----------------------------
Which waypoints a robot may be *placed* on is a localization question -- any
vertex with a known pose will do. Which waypoint a robot *parks* on is a fleet
policy question, decided adapter-side and constrained by separation (no two
robots finishing on top of each other). Those are different lists with
different owners, so `--docks all` is the default: restricting start points to
is_charger vertices would be importing a parking constraint into a problem that
does not have one.

Usage
-----
    rmf_dock_table.py NAV_GRAPH FLEET_CONFIG [--facing south]
                      [--docks all|parking|chargers]
                      [--yaw NAME=DEG ...] [--format yaml|sh]

The nav graph is the *generated* one (build/install, not the .building.yaml):
    install/jetracer_fleet/share/jetracer_fleet/maps/jetracer/nav_graphs/0.yaml
"""

import argparse
import math
import sys

import yaml


# Placement conventions, as headings in the RMF/robot plane (y up, x east).
# "south" is the lab's own top->bottom axis: the map is axis-aligned (map.yaml
# origin carries yaw 0) and the `top` vertex sits at greater y than `bottom`,
# so map +y is the lab's north and -y its south.
FACINGS = {
    'north': math.pi / 2,
    'south': -math.pi / 2,
    'east': 0.0,
    'west': math.pi,
}


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def fit_similarity(src, dst):
    """
    Least-squares 2D similarity taking src -> dst.

    Returns (theta, scale, tx, ty, max_residual). Closed form (Umeyama in 2D):
    no numpy dependency, and an exact fit on the synthetic 4-point block
    rmf_map_calib.py emits, so the residual doubles as a check that the block
    still describes this map.
    """
    n = len(src)
    if n < 2 or len(dst) != n:
        raise ValueError('need >=2 matched point pairs, got %d/%d'
                         % (n, len(dst)))

    px = sum(p[0] for p in src) / n
    py = sum(p[1] for p in src) / n
    qx = sum(q[0] for q in dst) / n
    qy = sum(q[1] for q in dst) / n

    dot = cross = norm = 0.0
    for (sx, sy), (tx_, ty_) in zip(src, dst):
        ax, ay = sx - px, sy - py
        bx, by = tx_ - qx, ty_ - qy
        dot += ax * bx + ay * by
        cross += ax * by - ay * bx
        norm += ax * ax + ay * ay

    if norm == 0.0:
        raise ValueError('reference points are all coincident')

    theta = math.atan2(cross, dot)
    scale = math.hypot(dot, cross) / norm
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    tx = qx - scale * (cos_t * px - sin_t * py)
    ty = qy - scale * (sin_t * px + cos_t * py)

    worst = 0.0
    for (sx, sy), (tx_, ty_) in zip(src, dst):
        ex = scale * (cos_t * sx - sin_t * sy) + tx - tx_
        ey = scale * (sin_t * sx + cos_t * sy) + ty - ty_
        worst = max(worst, math.hypot(ex, ey))

    return theta, scale, tx, ty, worst


def apply(theta, scale, tx, ty, x, y):
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return (scale * (cos_t * x - sin_t * y) + tx,
            scale * (sin_t * x + cos_t * y) + ty)


SELECTORS = {
    'all': None,                     # every named vertex
    'parking': 'is_parking_spot',
    'chargers': 'is_charger',
}


def collect_docks(nav_graph, level, select):
    """
    Named vertices eligible as start docks, plus the graph's lane adjacency.

    Returns (level, docks, neighbours) where docks is [(name, index, x, y)] in
    graph order and neighbours maps vertex index -> set of connected indices.
    The adjacency is only used to report departure cost; it does not affect
    which vertices qualify.
    """
    levels = nav_graph.get('levels', {})
    if level is None:
        if len(levels) != 1:
            raise ValueError('nav graph has levels %s -- pass --level'
                             % sorted(levels))
        level = next(iter(levels))
    elif level not in levels:
        raise ValueError('no level %r in nav graph (have %s)'
                         % (level, sorted(levels)))

    key = SELECTORS[select]
    docks = []
    for index, vertex in enumerate(levels[level]['vertices']):
        x, y, params = vertex[0], vertex[1], (vertex[2] or {})
        name = params.get('name', '')
        # An unnamed vertex cannot be a dock: there is nothing for the robot's
        # RMF_START_DOCK to reference it by.
        if name and (key is None or params.get(key)):
            docks.append((name, index, x, y))
    if not docks:
        raise ValueError('no named vertices on level %r match --docks %s'
                         % (level, select))

    neighbours = {}
    for lane in levels[level].get('lanes', []):
        a, b = lane[0], lane[1]
        neighbours.setdefault(a, set()).add(b)
        neighbours.setdefault(b, set()).add(a)
    return level, docks, neighbours


def departure_turn(yaw, origin, targets):
    """
    Smallest heading change from `yaw` onto any outgoing lane, in degrees.

    The jetracer is Ackermann (minimum_turning_radius 0.50 m), so it cannot
    pivot in place to leave a dock -- a large value here means the first move
    after boot is a multi-point or wide-arc manoeuvre, in a spot that may be
    against a wall. Reported so an awkward dock is visible before a robot is
    parked on it, not discovered during a demo.

    Returns None for a vertex with no lanes (unreachable, so nothing to face).
    """
    best = None
    ox, oy = origin
    for tx, ty in targets:
        bearing = math.atan2(ty - oy, tx - ox)
        delta = abs(math.degrees(math.atan2(math.sin(bearing - yaw),
                                            math.cos(bearing - yaw))))
        if best is None or delta < best:
            best = delta
    return best


def parse_yaw_overrides(items):
    out = {}
    for item in items or []:
        if '=' not in item:
            raise ValueError('--yaw wants NAME=DEGREES, got %r' % item)
        name, _, value = item.partition('=')
        out[name.strip()] = math.radians(float(value))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Generate the AMCL start-dock table from the RMF nav graph')
    parser.add_argument('nav_graph', help='generated nav_graphs/0.yaml')
    parser.add_argument('fleet_config',
                        help='fleet config yaml holding reference_coordinates')
    parser.add_argument('--level', default=None,
                        help='level name (default: the only one)')
    parser.add_argument('--facing', default='south',
                        help='placement convention for every dock: %s, or a '
                             'heading in degrees (default: south)'
                             % '/'.join(FACINGS))
    parser.add_argument('--yaw', action='append', metavar='NAME=DEG',
                        help='override one dock, e.g. --yaw operator=0. '
                             'Repeatable.')
    parser.add_argument('--docks', default='all', choices=sorted(SELECTORS),
                        help='which named vertices qualify as start points. '
                             'Placement is a localization question, not a '
                             'parking one, so the default is all (default: all)')
    parser.add_argument('--format', default='yaml', choices=('yaml', 'sh'),
                        help='yaml for the robot image, sh to source (default: '
                             'yaml)')
    args = parser.parse_args(argv)

    if args.facing in FACINGS:
        default_yaw = FACINGS[args.facing]
    else:
        try:
            default_yaw = math.radians(float(args.facing))
        except ValueError:
            parser.error('--facing wants %s or a number of degrees, got %r'
                         % ('/'.join(FACINGS), args.facing))

    nav_graph = load_yaml(args.nav_graph)
    fleet_config = load_yaml(args.fleet_config)
    overrides = parse_yaw_overrides(args.yaw)

    refs = fleet_config.get('reference_coordinates')
    if not refs:
        raise SystemExit('%s has no reference_coordinates block'
                         % args.fleet_config)

    level, docks, neighbours = collect_docks(nav_graph, args.level, args.docks)
    if level not in refs:
        raise SystemExit('reference_coordinates has no entry for level %r '
                         '(have %s)' % (level, sorted(refs)))

    unknown = set(overrides) - {name for name, _, _, _ in docks}
    if unknown:
        raise SystemExit('--yaw names no such dock: %s' % ', '.join(sorted(unknown)))

    theta, scale, tx, ty, residual = fit_similarity(refs[level]['rmf'],
                                                    refs[level]['robot'])

    # Every vertex, not just the dock ones: a dock's neighbours may themselves
    # be ineligible as start points but still define where its lanes lead.
    # Transformed first, so bearings come out in the robot frame the yaw
    # convention is stated in -- a non-zero fitted rotation is carried for free
    # rather than needing to be added back onto each heading.
    positions = {i: apply(theta, scale, tx, ty, v[0], v[1])
                 for i, v in enumerate(nav_graph['levels'][level]['vertices'])}

    rows = []
    for name, index, rx, ry in docks:
        x, y = apply(theta, scale, tx, ty, rx, ry)
        yaw = overrides.get(name, default_yaw)
        turn = departure_turn(yaw, (x, y),
                              [positions[n] for n in neighbours.get(index, ())])
        rows.append((name, x, y, yaw, name in overrides, turn))

    print('# GENERATED by tools/rmf_dock_table.py -- do not edit by hand.')
    print('# Re-run after any re-SLAM or nav graph change.')
    print('#   nav graph : %s' % args.nav_graph)
    print('#   transform : rotation %+.4f deg, scale %.6f, translation '
          '[%+.4f, %+.4f]' % (math.degrees(theta), scale, tx, ty))
    print('#   fit residual: %.4f m over %d reference points'
          % (residual, len(refs[level]['rmf'])))
    print('#   placement : %s (%+.4f rad) unless overridden'
          % (args.facing, default_yaw))

    if abs(math.degrees(theta)) > 0.5 or abs(scale - 1.0) > 0.01:
        print('#   NOTE: this is not a pure translation, so a heading in the '
              'RMF frame is')
        print('#         NOT the same heading in the robot frame. The rotation '
              'above is')
        print('#         already applied to every yaw below.')

    if args.format == 'sh':
        for name, x, y, yaw, _, _ in rows:
            key = name.upper().replace('-', '_')
            print('DOCK_%s="%.4f %.4f %.4f"' % (key, x, y, yaw))
    else:
        print('#')
        print('# "departure turn" is the smallest heading change from the '
              'seeded yaw onto')
        print('# an outgoing lane. The chassis is Ackermann and cannot pivot '
              'in place, so')
        print('# a large value means an awkward first move out of that dock -- '
              'prefer a')
        print('# low one, or override that dock\'s yaw.')
        print('docks:')
        for name, x, y, yaw, overridden, turn in rows:
            notes = ['override'] if overridden else []
            notes.append('no lanes' if turn is None
                         else 'departure turn %3.0f deg' % turn)
            print('  %-10s {x: %8.4f, y: %8.4f, yaw: %7.4f}  # %s'
                  % (name + ':', x, y, yaw, ', '.join(notes)))

    turning = [(t, n) for n, _, _, _, _, t in rows if t is not None]
    print('# %d dock(s) on level %s' % (len(rows), level), file=sys.stderr)
    if turning:
        worst, worst_name = max(turning)
        print('# worst departure: %s at %.0f deg' % (worst_name, worst),
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
