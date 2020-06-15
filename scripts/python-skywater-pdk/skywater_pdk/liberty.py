#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Copyright 2020 SkyWater PDK Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0


import argparse
import enum
import json
import os
import pathlib
import pprint
import re
import sys

from collections import defaultdict

from typing import Tuple, List, Dict

from . import sizes


class TimingType(enum.IntFlag):
    """

    >>> TimingType.parse("ff_100C_1v65")
    ('ff_100C_1v65', <TimingType.basic: 1>)

    >>> TimingType.parse("ff_100C_1v65_ccsnoise")
    ('ff_100C_1v65', <TimingType.ccsnoise: 3>)

    >>> TimingType.basic in TimingType.ccsnoise
    True

    >>> TimingType.parse("ff_100C_1v65_pwrlkg")
    ('ff_100C_1v65', <TimingType.leakage: 4>)

    >>> (TimingType.basic).describe()
    ''
    >>> (TimingType.ccsnoise).describe()
    '(with ccsnoise)'
    >>> (TimingType.leakage).describe()
    '(with power leakage)'
    >>> (TimingType.leakage | TimingType.ccsnoise).describe()
    '(with ccsnoise and power leakage)'

    >>> (TimingType.leakage | TimingType.ccsnoise).names()
    'basic, ccsnoise, leakage'

    >>> TimingType.ccsnoise.names()
    'basic, ccsnoise'
    """

    basic    = 1

    # ccsnoise files are basic files with extra 'ccsn_' values in the timing
    # data.
    ccsnoise = 2 | basic

    # leakage files are separate from the basic files
    leakage  = 4

    def names(self):
        o = []
        for t in TimingType:
            if t in self:
                o.append(t.name)
        return ", ".join(o)

    def describe(self):
        o = []
        if TimingType.ccsnoise in self:
            o.append("ccsnoise")
        if TimingType.leakage in self:
            o.append("power leakage")
        if not o:
            return ""
        return "(with "+" and ".join(o)+")"

    @property
    def file(self):
        if self == TimingType.ccsnoise:
            return "_ccsnoise"
        elif self == TimingType.leakage:
            return "_pwrlkg"
        return ""

    @classmethod
    def parse(cls, name):
        ttype = TimingType.basic
        if name.endswith("_ccsnoise"):
            name = name[:-len("_ccsnoise")]
            ttype = TimingType.ccsnoise
        elif name.endswith("_pwrlkg"):
            name = name[:-len("_pwrlkg")]
            ttype = TimingType.leakage
        return name, ttype

    @property
    def singular(self):
        return len(self.types) == 1

    @property
    def types(self):
        tt = set(t for t in TimingType if t in self)
        if TimingType.ccsnoise in tt:
            tt.remove(TimingType.basic)
        return list(tt)



def cell_corner_file(lib, cell_with_size, corner, corner_type: TimingType):
    """

    >>> cell_corner_file("sky130_fd_sc_hd", "a2111o", "ff_100C_1v65", TimingType.basic)
    'cells/a2111o/sky130_fd_sc_hd__a2111o__ff_100C_1v65.lib.json'
    >>> cell_corner_file("sky130_fd_sc_hd", "a2111o_1", "ff_100C_1v65", TimingType.basic)
    'cells/a2111o/sky130_fd_sc_hd__a2111o_1__ff_100C_1v65.lib.json'
    >>> cell_corner_file("sky130_fd_sc_hd", "a2111o_1", "ff_100C_1v65", TimingType.ccsnoise)
    'cells/a2111o/sky130_fd_sc_hd__a2111o_1__ff_100C_1v65_ccsnoise.lib.json'

    """
    assert corner_type.singular, (lib, cell_with_size, corner, corner_type, corner_type.types())

    sz = sizes.parse_size(cell_with_size)
    if sz:
        cell = cell_with_size[:-len(sz.suffix)]
    else:
        cell = cell_with_size

    fname = "cells/{cell}/{lib}__{cell_sz}__{corner}{corner_type}.lib.json".format(
        lib=lib, cell=cell, cell_sz=cell_with_size, corner=corner, corner_type=corner_type.file)
    return fname


def top_corner_file(libname, corner, corner_type: TimingType):
    """

    >>> top_corner_file("sky130_fd_sc_hd", "ff_100C_1v65", TimingType.ccsnoise)
    'timing/sky130_fd_sc_hd__ff_100C_1v65_ccsnoise.lib.json'
    >>> top_corner_file("sky130_fd_sc_hd", "ff_100C_1v65", TimingType.basic)
    'timing/sky130_fd_sc_hd__ff_100C_1v65.lib.json'

    """
    assert corner_type.singular, (libname, corner, corner_type, corner_type.types())
    return "timing/{libname}__{corner}{corner_type}.lib.json".format(
        libname=libname,
        corner=corner, corner_type=corner_type.file)


def collect(library_dir) -> Tuple[Dict[str, TimingType], List[str]]:
    """Collect the available timing information in corners.

    Parameters
    ----------
    library_dir: str
        Path to a library.

    Returns
    -------
    lib : str
        Library name

    corners : {str: TimingType}
        corners in the library.

    cells : list of str
        cells in the library.
    """

    if not isinstance(library_dir, pathlib.Path):
        library_dir = pathlib.Path(library_dir)

    libname0 = None

    corners = {}
    cells = set()
    for p in library_dir.rglob("*.lib.json"):
        if not p.is_file():
            continue
        if "timing" in str(p):
            continue

        fname, fext = str(p.name).split('.', 1)

        libname, cellname, corner = fname.split("__")
        if libname0 is None:
            libname0 = libname
        assert libname0 == libname, (libname0, libname)

        corner_name, corner_type = TimingType.parse(corner)

        cells.add(cellname)

        if corner_name in corners:
            corners[corner_name] |= corner_type
        else:
            corners[corner_name] = corner_type

    assert corners, library_dir
    assert cells, library_dir
    assert libname0, library_dir

    cells = list(sorted(cells))

    # Sanity check to make sure the corner exists for all cells.
    for cell_with_size in cells:
        for corner, corner_types in sorted(corners.items()):
            for corner_type in corner_types.types:
                fname = cell_corner_file(libname0, cell_with_size, corner, corner_type)
                fpath = os.path.join(library_dir, fname)
                assert os.path.exists(fpath), (fpath, corner, corner_type, corner_types)

    timing_dir = os.path.join(library_dir, "timing")
    assert os.path.exists(timing_dir), timing_dir
    for corner, corner_types in sorted(corners.items()):
        for corner_type in corner_types.types:
            fname = top_corner_file(libname0, corner, corner_type)
            fpath = os.path.join(library_dir, fname)
            assert os.path.exists(fpath), (fpath, corner, corner_type, corner_types)

    return libname0, corners, cells


def remove_ccsnoise(data):
    for k, v in list(data.items()):
        if "ccsn_" in k:
            del data[k]
            continue

        if not k.startswith("pin "):
            continue

        pin_data = data[k]

        if "input_voltage" in pin_data:
            del pin_data["input_voltage"]

        if "timing" not in pin_data:
            continue
        pin_timing = pin_data["timing"]

        for t in pin_timing:
            ccsn_keys = set()
            for k in t:
                if not k.startswith("ccsn_"):
                    continue
                ccsn_keys.add(k)

            for k in ccsn_keys:
                del t[k]



def generate(library_dir, lib, corner, ocorner_type, icorner_type, cells):
    top_fname = top_corner_file(lib, corner, ocorner_type).replace('.lib.json', '.lib')
    top_fpath = os.path.join(library_dir, top_fname)

    top_fout = open(top_fpath, "w")
    def top_write(lines):
        print("\n".join(lines), file=top_fout)

    otype_str = "({} from {})".format(ocorner_type.name, icorner_type.names())
    print("Starting to write", top_fpath, otype_str, flush=True)

    common_data = {}

    common_data_path = os.path.join(library_dir, "timing", "{}__common.lib.json".format(lib))
    assert os.path.exists(common_data_path), common_data_path
    with open(common_data_path) as f:
        d = json.load(f)
        assert isinstance(d, dict)
        for k, v in d.items():
            assert k not in common_data, (k, common_data[k])
            common_data[k] = v

    top_data_path = os.path.join(library_dir, top_corner_file(lib, corner, icorner_type))
    assert os.path.exists(top_data_path), top_data_path
    with open(top_data_path) as f:
        d = json.load(f)
        assert isinstance(d, dict)
        for k, v in d.items():
            assert k not in common_data, (k, common_data[k])
            common_data[k] = v

    # Remove the ccsnoise if it exists
    if ocorner_type != TimingType.ccsnoise:
        remove_ccsnoise(common_data)

    output = liberty_dict("library", lib+"__"+corner, common_data, 0)
    assert output[-1] == '}', output
    top_write(output[:-1])

    for cell_with_size in cells:
        fname = cell_corner_file(lib, cell_with_size, corner, icorner_type)
        fpath = os.path.join(library_dir, fname)
        assert os.path.exists(fpath), fpath

        with open(fpath) as f:
            cell_data = json.load(f)

        # Remove the ccsnoise if it exists
        if ocorner_type != TimingType.ccsnoise:
            remove_ccsnoise(cell_data)

        top_write([''])
        top_write(liberty_dict("cell", "%s__%s" % (lib, cell_with_size), cell_data, 1))

    top_write([''])
    top_write(['}'])
    top_fout.close()
    print("   Finish writing", top_fpath, flush=True)
    print("")


INDENT="    "

# complex attribute -- (x,b)

RE_LIBERTY_LIST = re.compile("(.*)_([0-9]+)")

def liberty_sort(k):
    """

    >>> liberty_sort("variable_1")
    (1, 'variable')
    >>> liberty_sort("index_3")
    (3, 'index')
    >>> liberty_sort("values") # doctest: +ELLIPSIS
    (inf, 'values')

    """
    m = RE_LIBERTY_LIST.match(k)
    if m:
        k, n = m.group(1), m.group(2)
        n = int(n)
    else:
        n = float('inf')
    return n, k


def is_liberty_list(k):
    """

    >>> is_liberty_list("variable_1")
    True
    >>> is_liberty_list("index_3")
    True
    >>> is_liberty_list("values")
    True
    """
    m = RE_LIBERTY_LIST.match(k)
    if m:
        k, n = m.group(1), m.group(2)

    return k in ('variable', 'index', 'values')


def liberty_float(f):
    """

    >>> liberty_float(1.9208818e-02)
    '0.0192088180'

    >>> liberty_float(1.5)
    '1.5000000000'

    >>> liberty_float(1e20)
    '1.000000e+20'

    >>> liberty_float(1)
    '1.0000000000'

    """
    WIDTH = len(str(0.0083333333))

    s = json.dumps(f)
    if 'e' in s:
        a, b = s.split('e')
        if '.' not in a:
            a += '.'
        while len(a)+len(b)+1 < WIDTH:
            a += '0'
        s = "%se%s" % (a, b)
    elif '.' in s:
        while len(s) < WIDTH:
            s += '0'
    else:
        if len(s) < WIDTH:
            s += '.'
        while len(s) < WIDTH:
            s += '0'
    return s


def liberty_composite(i, k, v):
    """

    >>> def pl(l):
    ...     print("\\n".join(l))

    >>> pl(liberty_composite(0, "capacitive_load_unit", [1.0, "pf"]))
    capacitive_load_unit(1.0000000000, "pf");

    >>> pl(liberty_composite(0, "voltage_map", [("vpwr", 1.95), ("vss", 0.0)]))
    voltage_map("vpwr", 1.9500000000);
    voltage_map("vss", 0.0000000000);

    """
    if isinstance(v, tuple):
        v = list(v)
    assert isinstance(v, list), (k, v)

    if isinstance(v[0], (list, tuple)):
        o = []
        for l in v:
            o.extend(liberty_composite(i, k, l))
        return o

    o = []
    for l in v:
        if isinstance(l, (float, int)):
            o.append(liberty_float(l))
        elif isinstance(l, str):
            assert '"' not in l, (k, v)
            o.append('"%s"' % l)
        else:
            raise ValueError("%s - %r (%r)" % (k, l, v))

    return ["%s%s(%s);" % (INDENT*i, k, ", ".join(o))]


def liberty_join(l):
    """

    >>> l = [5, 1.0, 10]
    >>> liberty_join(l)(l)
    '5.0000000000, 1.0000000000, 10.000000000'

    >>> l = [1, 5, 8]
    >>> liberty_join(l)(l)
    '1, 5, 8'

    """
    d = defaultdict(lambda: 0)

    for i in l:
        d[type(i)] += 1

    def types(l):
        return [(i, type(i)) for i in l]

    if d[float] > 0:
        assert (d[float]+d[int]) == len(l), (d, types(l))
        def join(l):
            return ", ".join(liberty_float(f) for f in l)
        return join

    elif d[int] > 0:
        assert d[int] == len(l), (d, types(l))
        def join(l):
            return ", ".join(str(f) for f in l)
        return join

    raise ValueError("Invalid value: %r" % types(l))


def liberty_list(i, k, v):
    o = []
    if isinstance(v[0], list):
        o.append('%s%s(' % (INDENT*i, k))
        join = liberty_join(v[0])
        for l in v:
            o.append('%s"%s", \\' % (INDENT*(i+1), join(l)))

        o[1] = o[0]+o[1]
        o.pop(0)

        o[-1] = o[-1][:-3] + ');'
    else:
        join = liberty_join(v)
        o.append('%s%s("%s");' % (INDENT*i, k, join(v)))

    return o


def liberty_dict(dtype, dvalue, data, i=0):
    assert isinstance(data, dict), (dtype, dvalue, data)
    o = []
    if dvalue:
        dvalue = '"%s"' % dvalue
    o.append('%s%s (%s) {' % (INDENT*i, dtype, dvalue))

    i_n = i+1

    # Output the attribute defines first
    if 'define' in data:
        for d in sorted(data['define'], key=lambda d: d['group_name']+'.'+d['attribute_name']):
            o.append('%sdefine(%s,%s,%s);' % (INDENT*i_n, d['attribute_name'], d['group_name'], d['attribute_type']))
        o.append('')

        del data['define']

    # Output all the attributes
    def attr_sort_key(a):
        k, v = a
        if " " in k:
            ktype, kvalue = k.split(" ", 1)
        else:
            ktype = k
            kvalue = ""

        if ktype == "comp_attribute":
            ktype = kvalue
            kvalue = None

        kn, ktype = liberty_sort(ktype)

        return (kn, ktype, kvalue)

    for k, v in sorted(data.items(), key=attr_sort_key):

        if " " in k:
            ktype, kvalue = k.split(" ", 1)
        else:
            ktype = k
            kvalue = ""

        if ktype == "comp_attribute":
            assert isinstance(v, list), (k, v)
            o.extend(liberty_composite(i_n, kvalue, v))

        elif isinstance(v, dict):
            assert isinstance(v, dict), (dtype, dvalue, k, v)
            o.extend(liberty_dict(ktype, kvalue, v, i_n))

        elif isinstance(v, list):
            assert len(v) > 0, (dtype, dvalue, k, v)
            if isinstance(v[0], dict):
                def k(o):
                    return o.items()

                for l in sorted(v, key=k):
                    o.extend(liberty_dict(ktype, kvalue, l, i_n))

            elif is_liberty_list(k):
                o.extend(liberty_list(i_n, k, v))

            else:
                raise ValueError("Unknown %s: %r" % (k, v))
        else:
            if isinstance(v, str):
                v = '"%s"' % v
            elif isinstance(v, (float,int)):
                v = liberty_float(v)
            o.append("%s%s : %s;" % (INDENT*i_n, k, v))

    o.append("%s}" % (INDENT*i))
    return o




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
            "library_path",
            help="Path to the library.",
            type=pathlib.Path,
            nargs=1)
    parser.add_argument(
            "corner",
            help="Corner to write output for.",
            default=None,
            nargs='*')

    parser.add_argument(
            "--ccsnoise",
            help="Include ccsnoise in file output.",
            action='store_true',
            default=False)
    parser.add_argument(
            "--leakage",
            help="Include power leakage in file output.",
            action='store_true',
            default=False)

    args = parser.parse_args()

    libdir = args.library_path[0]

    retcode = 0

    lib, corners, cells = collect(libdir)

    if args.ccsnoise:
        output_corner_type = TimingType.ccsnoise
    elif args.leakage:
        output_corner_type = TimingType.leakage
    else:
        output_corner_type = TimingType.basic

    if args.corner == ['all']:
        args.corner = list(sorted(k for k, v in corners.items() if output_corner_type in v))

    if args.corner:
        for acorner in args.corner:
            if acorner in corners:
                continue
            print()
            print("Unknown corner:", acorner)
            retcode = 1
        if retcode != 0:
            args.corner.clear()

    if not args.corner:
        print()
        print("Available corners:")
        for k, v in sorted(corners.items()):
            print("  -", k, v.describe())
        print()
        return retcode

    for corner in args.corner:
        input_corner_type = corners[corner]
        if output_corner_type not in input_corner_type:
            print("Corner", corner, "doesn't support", output_corner_type, "(only {})".format(input_corner_type))
            return 1

        if output_corner_type == TimingType.basic and TimingType.ccsnoise in input_corner_type:
            input_corner_type = TimingType.ccsnoise
        else:
            input_corner_type = output_corner_type

        generate(
            libdir, lib,
            corner, output_corner_type, input_corner_type,
            cells,
        )
    return 0


if __name__ == "__main__":
    import doctest
    doctest.testmod()

    sys.exit(main())
