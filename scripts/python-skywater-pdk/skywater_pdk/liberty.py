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
import sys

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

    >>> TimingType.basic in TimingType.leakage
    False
    """

    basic    = 1

    # ccsnoise files are basic files with extra 'ccsn_' values in the timing
    # data.
    ccsnoise = 2 | basic

    # leakage files are separate from the basic files
    leakage  = 4

    def describe(self):
        if self == TimingType.ccsnoise:
            return "(with ccsnoise)"
        elif self == TimingType.leakage:
            return "(with power leakage)"
        return ""

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


def corner_file(lib, cell_with_size, corner, corner_type: TimingType):
    sz = sizes.parse_size(cell_with_size)
    if sz:
        cell = cell_with_size[:-len(sz.suffix)]
    else:
        cell = cell_with_size

    fname = "cells/{cell}/{lib}__{cell_sz}__{corner}{corner_type}.lib.json".format(
        lib=lib, cell=cell, cell_sz=cell_with_size, corner=corner, corner_type=corner_type.file)
    return fname


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

        fname, fext = str(p.name).split('.', 1)

        libname, cellname, corner = fname.split("__")
        if libname0 is None:
            libname0 = libname
        assert libname0 == libname, (libname0, libname)

        corner_name, corner_type = TimingType.parse(corner)

        cells.add(cellname)

        if corner_name in corners:
            if corner_type == TimingType.basic:
                continue
            if corner_type == corners[corner_name]:
                continue
            assert corners[corner_name] == TimingType.basic, (corner, corners[corner_name], corner_type)

        corners[corner_name] = corner_type

    assert corners, library_dir
    assert cells, library_dir
    assert libname0, library_dir

    cells = list(sorted(cells))

    # Sanity check to make sure the corner exists for all cells.
    for cell_with_size in cells:
        for corner in sorted(corners):
            fname = corner_file(libname0, cell_with_size, corner, corners[corner])
            fpath = os.path.join(library_dir, fname)
            assert os.path.exists(fpath), fpath

    return libname0, corners, cells


def generate(output_path, library_dir, lib, corner, corner_type, cells, ccsnoise=False, leakage=False):

    output = []
    for cell_with_size in cells:
        fname = corner_file(lib, cell_with_size, corner, corner_type)
        fpath = os.path.join(library_dir, fname)
        assert os.path.exists(fpath), fpath

        print(fpath)
        with open(fpath) as f:
            cell_data = json.load(f)

        # Remove the ccsnoise if it exists
        if not ccsnoise:
            for k, v in cell_data.items():
                if not k.startswith("pin "):
                    continue

                pin_data = cell_data[k]

                if "input_voltage" in pin_data:
                    del pin_data["input_voltage"]

                if "timing" not in pin_data:
                    continue
                pin_timing = cell_data[k]["timing"]

                for t in pin_timing:
                    ccsn_keys = set()
                    for k in t:
                        if not k.startswith("ccsn_"):
                            continue
                        ccsn_keys.add(k)

                    for k in ccsn_keys:
                        del t[k]

        output.extend(liberty_dict("cell", "%s__%s" % (lib, cell_with_size), cell_data, 1))
        break
    print("\n".join(output))



INDENT="    "

# complex attribute -- (x,b)


def liberty_list(l):
    return ", ".join("%f" % f for f in l)


def liberty_dict(dtype, dvalue, data, i=0):
    assert isinstance(data, dict), (dtype, dvalue, data)
    o = []
    if dvalue:
        dvalue = '"%s"' % dvalue
    o.append('%s%s (%s) {' % (INDENT*i, dtype, dvalue))
    i_n = i+1
    for k, v in sorted(data.items()):

        if " " in k:
            ktype, kvalue = k.split(" ", 1)
        else:
            ktype = k
            kvalue = ""

        if isinstance(v, dict):
            assert isinstance(v, dict), (dtype, dvalue, k, v)
            o.extend(liberty_dict(ktype, kvalue, v, i_n))

        elif isinstance(v, list):
            assert len(v) > 0, (dtype, dvalue, k, v)
            if isinstance(v[0], dict):
                def k(o):
                    return o.items()

                for l in sorted(v, key=k):
                    o.extend(liberty_dict(ktype, kvalue, l, i_n))
            elif isinstance(v[0], list):
                o.append('%s%s(' % (INDENT*i_n, k))
                for l in v:
                    o.append('%s"%s", \\' % (INDENT*(i_n+1), liberty_list(l)))
                o[-1] = o[-1][:-3] + ');'
            else:
                o.append('%s%s("%s");' % (INDENT*i_n, k, liberty_list(v)))
        else:
            if isinstance(v, str):
                v = '"%s"' % v
            o.append("%s%s : %s;" % (INDENT*i_n, k, v))

    o.append("%s}" % (INDENT*i))
    return o



def liberty(data, i=0):
    if isinstance(data, dict):
        return liberty_dict
        o = []
        for k, v in data.items():
            if " " in k:
                ktype, kvalue = k.split(" ", 1)
                o.append("%s%s (%s) {" % (" "*i, ktype, kvalue))
                o.extend(liberty(data, i+1))
                o.append("%s}" % (" "*i))
                continue

            assert not isinstance(v, dict), (repr(k), repr(v))
            if isinstance(v, list):
                if isinstance(v[0], dict):

                    vs = str(v)
            else:
                vs = ": %s" % v

            o.append("%s%s %s;" % (" "*i, k, vs))
        return o
    elif isinstance(data, list):
        o = []


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
        return retcode

    print(args)

    for corner in args.corner:
        corner_type = corners[corner]
        if args.ccsnoise and corner_type != TimingType.ccsnoise:
            print("Corner", corner, "doesn't support ccsnoise.")
            return 1
        if args.leakage and corner_type != TimingType.leakage:
            print("Corner", corner, "doesn't support power leakage.")
            return 1

        generate(
            "{}__{}.lib".format(lib, corner),
            libdir, lib,
            corner, corner_type,
            cells,
            ccsnoise=args.ccsnoise, leakage=args.leakage,
        )
    return 0


if __name__ == "__main__":
    import doctest
    doctest.testmod()

    sys.exit(main())
