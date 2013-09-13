# Copyright (C) 2001  Jeff Epler  <jepler@unpythonic.dhs.org>
# Copyright (C) 2005  Daniel Patterson  <danpat@danpat.net>
# Copyright (C) 2013  Vladimir Rutsky  <rutsky.vladimir@gmail.com>
#
# This file is part of svnfs.
#
# svnfs is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# svnfs is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with svnfs.  If not, see <http://www.gnu.org/licenses/>.
#
#
# This is a FUSE module using the Python bindings.  It allows you to mount
# a local subversion repository file system into the host file system, read-only.
#
# TODO: - support symlinks
#       - support following HEAD as it moves, or pegging to a revision
#         (right now, we're pegged to youngest_rev when we start) --- in all
#         revisions mode head following implemented.
#       - support some kind of "magic" meta syntax, i.e. "cat trunk@@log", a-la
#         clearcase MVFS
#       - mount arbitary sub-trees within the repository
#       - work out a better way to represent inodes than binascii.crc32()
#
# bob TODO:
#       - use logging
#       - check is current way of reporting errors (by throwing exception
#         with errno is correct)
#       - don't read whole file on first read - implement opened streams
#         storing and caching
#       - create cache in /tmp by default
#
# USAGE:
#       - install and load the "fuse" kernel module
#       - run "svnfs.py /mnt/wherever -o svnrepo=/var/lib/svn/repodir" or
#         "svnfs.py /var/lib/svn/repodir /mnt/wherever"
#       - run "fusermount -u /mnt/wherever" to unmount

# Set FUSE API version
import fuse
fuse.fuse_python_api = (0, 2)
fuse.feature_assert('has_init', 'stateful_files')


import os
import re
import sys
import pwd
import grp
import signal
import datetime
import binascii
import traceback
import functools
import stat
import errno
import inspect
import shelve
import pickle
import tempfile
import shutil

# Import threading modules. TODO: Otherwise program prints on exit:
# Exception KeyError: KeyError(139848519223040,) in <module 'threading' from '/usr/lib64/python2.7/threading.pyc'> ignored
import threading

import fuse
fuse.fuse_python_api = (0, 2)
fuse.feature_assert('has_init', 'stateful_files')
from fuse import Fuse

import svn.repos
import svn.fs
import svn.core

import synch

# Use custom LRU cache implementation because Python's version doesn't have
# timeout option


# TODO: Cache all immutable values, such as directory listings.


















