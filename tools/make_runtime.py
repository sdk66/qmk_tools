"""Export a native application as an importable cross-host runtime template."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from qmk_updater.runtimes import create_runtime_archive, TARGETS

parser = argparse.ArgumentParser()
parser.add_argument("native")
parser.add_argument("--target", required=True, choices=tuple(TARGETS))
parser.add_argument("--output", required=True)
args = parser.parse_args()
create_runtime_archive(args.native, args.output, args.target)
print("Runtime template: " + str(Path(args.output).resolve()))
