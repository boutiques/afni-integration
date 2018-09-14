# -*- coding: utf-8 -*-

__version__ = '0.1'

NAME = 'afnihelp'
MAINTAINER = 'Team AFNIHelp'
EMAIL = 'afnihelp@afnihelp.com'
VERSION = __version__
LICENSE = 'MIT'
DESCRIPTION = """\
Some tools for parsing AFNI help and generating boutiques descriptors\
"""
LONG_DESCRIPTION = 'README.md'
LONG_DESCRIPTION_CONTENT_TYPE = 'text/x-md'
URL = 'https://github.com/boutiques/{name}'.format(name=NAME)
DOWNLOAD_URL = ('http://github.com/boutiques/{name}/archive/{ver}.tar.gz'
                .format(name=NAME, ver=__version__))

INSTALL_REQUIRES = [
    'boutiques',
    'numpy'
]

TESTS_REQUIRES = [
]

EXTRAS_REQUIRES = {
}

EXTRAS_REQUIRES['all'] = list(
    set([v for deps in EXTRAS_REQUIRES.values() for v in deps])
)


PACKAGE_DATA = {
}

CLASSIFIERS = [
    'Intended Audience :: Science/Research',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python :: 3.6',
]
