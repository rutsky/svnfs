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

import os

from svnfs.exceptions import raise_read_only_error, trace_exceptions


__all__ = ["SvnFSAllRevisionsFile", "SvnFSSingleRevisionFile"]


def is_write_mode(flags):
    return ((flags & os.O_WRONLY) or
            (flags & os.O_RDWR) or
            (flags & os.O_APPEND) or
            (flags & os.O_CREAT) or
            (flags & os.O_TRUNC))


class SvnFSFileBase(object):
    def __init__(self, full_path, flags, rev, svn_path, pool):
        super(SvnFSFileBase, self).__init__()

        # TODO: not sure is this needed and what it does
        self.keep = True
        self.keep_cache = True
        self.direct_io = False

        if is_write_mode(flags):
            raise_read_only_error(
                "Read-only file system. Can't create '{0}'".format(full_path))

        # Revision and subversion path in revision must exists
        
        self.rev = rev
        self.path = svn_path
        self.node_revision_id = self.svnfs.svnfs_node_revision_id(rev, svn_path, pool)

    @trace_exceptions
    def read(self, length, offset):
        pool = svn.core.Pool(get_pool())
        return self.svnfs.svnfs_read(self.rev, self.path, self.node_revision_id, length, offset, pool)

    @trace_exceptions
    def write(self, buf, offset):
        raise_read_only_error()

    @trace_exceptions
    def release(self, flags):
        pass

    @trace_exceptions
    def _fflush(self):
        pass

    @trace_exceptions
    def fsync(self, isfsyncfile):
        pass

    @trace_exceptions
    def flush(self):
        pass

    @trace_exceptions
    def fgetattr(self):
        return self.svnfs.svnfs_getattr(self.rev, self.path)

    @trace_exceptions
    def ftruncate(self, length):
        raise_read_only_error()

    @trace_exceptions
    def lock(self, cmd, owner, **kw):
        return -errno.EOPNOTSUPP


class SvnFSAllRevisionsFile(SvnFSFileBase):
    @trace_exceptions
    def __init__(self, path, flags, *mode):
        super(SvnFSAllRevisionsFile, self).__init__(path, flags, *mode)

        m = file_re.match(path)
        if not m:
            raise_no_such_entry_error("Path not found: {0}".format(path))

        pool = svn.core.Pool(get_pool())
        rev = self.svnfs.svnfs_get_rev(m.group(1))
        if rev > self.svnfs.svnfs_youngest_rev():
            raise_no_such_entry_error("Nonexistent (yet) revision {0}".format(rev))

        svn_path = m.group(2)

        if not self.svnfs.svnfs_file_exists(rev, svn_path, pool):
            raise_no_such_entry_error("Path not found in {0} revision: {1}".format(rev, svn_path))

        self.svnfs_init(rev, svn_path, pool)


class SvnFSSingleRevisionFile(SvnFSFileBase):
    @trace_exceptions
    def __init__(self, path, flags, *mode):
        super(SvnFSSingleRevisionFile, self).__init__(path, flags, *mode)

        pool = svn.core.Pool(get_pool())

        if not self.svnfs.svnfs_file_exists(self.svnfs.rev, path, pool):
            raise_no_such_entry_error("Path not found in {0} revision: {1}".format(self.svnfs.rev, path))

        self.svnfs_init(self.svnfs.rev, path, pool)
