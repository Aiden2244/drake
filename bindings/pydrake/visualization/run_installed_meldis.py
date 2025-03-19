#!/usr/bin/env python3

"""
Runs Meldis from an install tree.
"""

from os.path import isdir, join, dirname, realpath, exists
import sys


def main():
    print(f"\nDEBUG: in file run_installed_meldis.py")
    # Ensure that we can import pydrake, accommodating symlinks.
    prefix_dir = dirname(dirname(realpath(__file__)))
    print(f"DEBUG: prefix_dir = {prefix_dir}")
    
    assert isdir(join(prefix_dir, "bin")), f"Bad location: {prefix_dir}"
    print(f"DEBUG: assertion passed")
    
    # version = f"{sys.version_info.major}.{sys.version_info.minor}"
    version = "3.12"
    print(f"DEBUG: version = {version}")
    
    site_dir = join(prefix_dir, f"lib/python{version}/site-packages")
    print(f"DEBUG: site_dir = {site_dir}")
    print(f"DEBUG: site_dir exists = {exists(site_dir)}")
    
    print(f"DEBUG: python interpreter in run_install_meldis = {sys.executable}")
    sys.path.insert(0, site_dir)

    # Execute the imported main.
    # from pydrake.visualization.meldis import _main
    # _main()


assert __name__ == "__main__"
main()
