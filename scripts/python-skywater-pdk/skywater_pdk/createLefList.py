import glob
import os
import argparse


parser = argparse.ArgumentParser(
    description='Merges lefs together')
parser.add_argument('--inputFolder', '-i', required=True,
                    help='Input Folder', nargs='+')
args = parser.parse_args()

path = args.inputFolder[0]
lefs = glob.glob(path + "cells/*/*.lef")
f_lefs = []

for lef in lefs:
    if lef[-9::] != "magic.lef":
        f_lefs.append(lef)

assert len(f_lefs) != 0

with open(path + "lef/leflist.mk", "w") as f:
    cell_header = "export CELL_LEFS=\""
    
    f.write(cell_header + f_lefs[0] + " \\\n")
    for lef in f_lefs[1::]:
        f.write(" "*len(cell_header) + lef)
        if lef != f_lefs[-1]:
            f.write(" \\\n")
    f.write("\"")
