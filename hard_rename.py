"""
Renames file(s) on the convention of (vehicletype)_(vehiclename)_(oldfilename).bag.
With this naming convention, renaming will not occur in process_bags.py/file upload,
so only use this if you think you are more qualified to identify the source platform
than the automated process, which would examine its rostopics and parent directories.
"""

#!/usr/bin/env python3

from pathlib import Path
from argparse import ArgumentParser

# configuration from command-line args
parser = ArgumentParser()
parser.add_argument(
    "-t",
    "--type",
    help="vehicle/platform type. current options: remus, buoy",
)
parser.add_argument(
    "-n",
    "--name",
    nargs="?",
    help="vehicle name. remuses: shadow, casper, bullwinkle; buoys: sugar, skipper",
)
args = vars(parser.parse_args())

PLATFORM_TYPE = args["type"]
PLATFORM_NAME = args["name"]


def hard_rename():
    """
    Renames file(s) on the convention of (vehicletype)_(vehiclename)_(oldfilename).bag.
    """
    thisdir = Path.cwd()
    files = thisdir.glob("*.bag")
    for file in files:
        file.rename(f"{PLATFORM_TYPE}_{PLATFORM_NAME}_{file.name}")


if __name__ == "__main__":
    hard_rename()
