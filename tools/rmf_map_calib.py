#!/usr/bin/env python3
"""
Calibration helpers for re-mapping the lab.

Two jobs, both of which otherwise mean clicking points in a GUI and hoping:

  calib   Derive the `measurements:` scale entry and the `reference_coordinates`
          block for jetracer_fleet_config.yaml, analytically, from the new
          map.yaml + the drawing's pixel height.

  remap   Carry the vertices/lanes/walls of an existing .building.yaml over to a
          new drawing, given two landmarks you can identify in both images.
          Saves re-placing every vertex by hand when only part of the lab moved.

Both assume the traffic-editor drawing PNG is a pixel-identical conversion of
the occupancy PGM (same width/height, no scaling, no flip). `calib --check`
verifies that for you. If it isn't true, everything below is wrong -- redo the
conversion rather than fudging numbers.

Coordinate conventions this encodes (verified against the existing jetracer map,
residuals < 1px on 3 of 4 recorded points):

  traffic editor (coordinate_system: reference_image), pixel (px, py) from
  top-left, y down:
      x_rmf =  px * scale
      y_rmf = -py * scale

  ROS map_server, same pixel:
      x_robot = origin_x + px * res
      y_robot = origin_y + (H - py) * res

  so when scale == res (drawing == grid), the RMF->robot transform is a pure
  translation:
      x_robot = x_rmf + origin_x
      y_robot = y_rmf + (H * res + origin_y)
"""

import argparse
import math
import re
import sys

import yaml


def read_pgm_size(path):
    """Width/height from a binary (P5) or ASCII (P2) PGM header."""
    with open(path, 'rb') as f:
        head = f.read(128)
    tokens = re.findall(rb'\S+', re.sub(rb'#[^\n]*', b'', head))
    if not tokens or tokens[0] not in (b'P5', b'P2'):
        raise ValueError('%s is not a PGM (magic %r)' % (path, tokens[:1]))
    return int(tokens[1]), int(tokens[2])


def read_png_size(path):
    with open(path, 'rb') as f:
        head = f.read(24)
    if head[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('%s is not a PNG' % path)
    return (int.from_bytes(head[16:20], 'big'), int.from_bytes(head[20:24], 'big'))


def load_map_yaml(path):
    with open(path) as f:
        m = yaml.safe_load(f)
    return m['resolution'], m['origin'][0], m['origin'][1], m['image']


def cmd_calib(args):
    res, ox, oy, image = load_map_yaml(args.map_yaml)
    pgm_w, pgm_h = read_pgm_size(args.pgm)
    print('map.yaml     : resolution=%.4f m/px  origin=[%.4f, %.4f]  image=%s'
          % (res, ox, oy, image))
    print('occupancy pgm: %d x %d px' % (pgm_w, pgm_h))

    if args.png:
        png_w, png_h = read_png_size(args.png)
        print('drawing png  : %d x %d px' % (png_w, png_h))
        if (png_w, png_h) != (pgm_w, pgm_h):
            print('\nFATAL: drawing PNG is %dx%d but the grid is %dx%d.' %
                  (png_w, png_h, pgm_w, pgm_h))
            print('Redo the conversion losslessly and without resizing:')
            print('  magick %s %s' % (args.pgm, args.png))
            return 1
        print('             -> pixel-identical, scale is exactly %.4f m/px' % res)

    H = pgm_h

    print('\n--- measurements: (paste into levels.L1, replacing the existing entry) ---')
    print('# scale anchor between two vertices; recompute whenever either moves.')
    if args.measure:
        (ax, ay), (bx, by) = args.measure[:2], args.measure[2:]
        d_px = math.hypot(bx - ax, by - ay)
        print('    measurements:')
        print('      - [%d, %d, {distance: [3, %.4f]}]'
              % (args.measure_ids[0], args.measure_ids[1], d_px * res))
        print('# from pixel distance %.4f px x %.4f m/px' % (d_px, res))
    else:
        print('# rerun with --measure PX0 PY0 PX1 PY1 (pixel coords of the two')
        print('# vertices you want to anchor on, straight out of the new')
        print('# .building.yaml) to have this computed for you.')

    cx, cy = ox, H * res + oy
    print('\n--- reference_coordinates: (replace the block in jetracer_fleet_config.yaml) ---')
    print('# Derived analytically, not clicked. RMF->robot is a pure translation')
    print('# of (%+.4f, %+.4f) because the drawing and the grid are the same pixels.' % (cx, cy))
    print('# Points below are synthetic but exact -- spread across the map so the')
    print('# affine fit is well conditioned.')

    # Corners inset by 15% so the points sit inside the mapped region.
    W = pgm_w
    insets = [(0.15, 0.15), (0.85, 0.15), (0.85, 0.85), (0.15, 0.85)]
    pairs = []
    for fx, fy in insets:
        px, py = W * fx, H * fy
        x_rmf, y_rmf = px * res, -py * res
        pairs.append(((x_rmf, y_rmf), (x_rmf + cx, y_rmf + cy)))

    print('reference_coordinates:')
    print('  L1:')
    print('    rmf: [[%.4f, %.4f],' % pairs[0][0])
    for p, _ in pairs[1:-1]:
        print('          [%.4f, %.4f],' % p)
    print('          [%.4f, %.4f]]' % pairs[-1][0])
    print('    robot: [[%.4f, %.4f],' % pairs[0][1])
    for _, p in pairs[1:-1]:
        print('            [%.4f, %.4f],' % p)
    print('            [%.4f, %.4f]]' % pairs[-1][1])

    print('\n--- spot check (do this once, in RViz, before trusting the above) ---')
    print('Drive a robot to a recognisable spot. Read its map-frame pose, then:')
    print('  x_rmf = x_robot - (%.4f)' % cx)
    print('  y_rmf = y_robot - (%.4f)' % cy)
    print('and confirm that RMF point lands where you expect on the building map.')
    print('Within ~10cm is fine; a rotation or a >0.5m offset means the drawing')
    print('is not the grid and you should re-check the conversion.')
    return 0


def cmd_remap(args):
    """Move an existing building.yaml onto a new drawing via two landmarks."""
    (ax0, ay0), (bx0, by0) = args.old[:2], args.old[2:]
    (ax1, ay1), (bx1, by1) = args.new[:2], args.new[2:]

    dx0, dy0 = bx0 - ax0, by0 - ay0
    dx1, dy1 = bx1 - ax1, by1 - ay1
    len0, len1 = math.hypot(dx0, dy0), math.hypot(dx1, dy1)
    if len0 == 0 or len1 == 0:
        print('FATAL: the two landmarks must be distinct points.')
        return 1

    s = len1 / len0
    theta = math.atan2(dy1, dx1) - math.atan2(dy0, dx0)
    cos_t, sin_t = math.cos(theta) * s, math.sin(theta) * s
    tx = ax1 - (cos_t * ax0 - sin_t * ay0)
    ty = ay1 - (sin_t * ax0 + cos_t * ay0)

    print('similarity transform: scale=%.5f  rotation=%.3f deg  translation=(%.2f, %.2f) px'
          % (s, math.degrees(theta), tx, ty))
    if abs(s - 1.0) > 0.02:
        print('NOTE: scale is %.1f%% off unity -- expected ~1.0 if both maps were'
              % ((s - 1) * 100))
        print('      built at the same resolution. Double-check your landmarks.')
    if abs(math.degrees(theta)) > 2.0:
        print('NOTE: %.1f deg of rotation between the maps. Real (SLAM start pose'
              % math.degrees(theta))
        print('      differed) but worth confirming you picked matching landmarks.')

    with open(args.building_yaml) as f:
        doc = yaml.safe_load(f)

    for level_name, level in doc.get('levels', {}).items():
        moved = 0
        for v in level.get('vertices', []):
            px, py = float(v[0]), float(v[1])
            v[0] = cos_t * px - sin_t * py + tx
            v[1] = sin_t * px + cos_t * py + ty
            moved += 1
        print('  level %s: %d vertices remapped' % (level_name, moved))

    with open(args.out, 'w') as f:
        yaml.safe_dump(doc, f, default_flow_style=None, sort_keys=True)

    print('\nwrote %s' % args.out)
    print('NEXT, and do not skip these:')
    print('  1. Open it in rmf_traffic_editor over the NEW drawing and eyeball it.')
    print('     Vertices in parts of the lab that physically moved will be wrong --')
    print('     this transform only fixes the map-origin change, not real layout')
    print('     changes. Drag those by hand.')
    print('  2. Re-run `calib --measure` with two of the new vertex positions and')
    print('     replace the measurements: entry. It is stale now.')
    print('  3. Confirm every waypoint name the fleet config references still')
    print('     exists (inventory, diamond, door, top, bottom).')
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)

    c = sub.add_parser('calib', help='derive measurements + reference_coordinates')
    c.add_argument('map_yaml', help='the new nav2 map yaml')
    c.add_argument('pgm', help='the new occupancy grid pgm')
    c.add_argument('--png', help='the traffic-editor drawing, to verify it matches')
    c.add_argument('--measure', nargs=4, type=float, metavar=('PX0', 'PY0', 'PX1', 'PY1'),
                   help='pixel coords of two vertices to anchor the scale on')
    c.add_argument('--measure-ids', nargs=2, type=int, default=[0, 1],
                   metavar=('ID0', 'ID1'), help='their vertex indices (default 0 1)')
    c.set_defaults(func=cmd_calib)

    r = sub.add_parser('remap', help='carry an old building.yaml onto a new drawing')
    r.add_argument('building_yaml', help='the existing .building.yaml')
    r.add_argument('--old', nargs=4, type=float, required=True,
                   metavar=('AX', 'AY', 'BX', 'BY'),
                   help='two landmark pixel coords in the OLD drawing')
    r.add_argument('--new', nargs=4, type=float, required=True,
                   metavar=('AX', 'AY', 'BX', 'BY'),
                   help='the same two landmarks in the NEW drawing')
    r.add_argument('-o', '--out', required=True, help='output .building.yaml')
    r.set_defaults(func=cmd_remap)

    args = p.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
