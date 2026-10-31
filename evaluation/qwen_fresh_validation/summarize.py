"""Independent process using the same frozen scorer, complete-cohort inference only."""

import argparse

from .common import module

impl = module("summarize")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, choices=range(5), required=True)
    impl.offline(parser.parse_args().index)
