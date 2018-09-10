#!/usr/bin/env python

from argparse import ArgumentParser
from docopt import docopt


def main():
    parser = ArgumentParser()
    parser.add_argument('helpfile', action='store', help='File containing'
                        ' help text for an AFNI tool.')

    args = parser.parse_args()

    with open(args.helpfile, 'r') as fhandle:
        string = fhandle.read()
        afniparser = docopt(string)

    print(afniparser)


if __name__ == '__main__':
    main()
