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

from svnfs.exceptions import trace_exceptions, raise_read_only_error

__all__ = ["FuseReadOnlyMixin"]


class FuseReadOnlyMixin(object):
    @trace_exceptions
    def unlink(self, path):
        raise_read_only_error("Read-only file system, can't unlink {0}".format(path))

    @trace_exceptions
    def rmdir(self, path):
        raise_read_only_error("Read-only file system, can't rmdir {0}".format(path))

    @trace_exceptions
    def symlink(self, path, path1):
        raise_read_only_error("Read-only file system, can't symlink {0}".format(path))

    @trace_exceptions
    def rename(self, path, path1):
        raise_read_only_error("Read-only file system, can't rename {0}".format(path))

    @trace_exceptions
    def link(self, path, path1):
        raise_read_only_error("Read-only file system, can't link {0}".format(path))

    @trace_exceptions
    def chmod(self, path, mode):
        raise_read_only_error("Read-only file system, can't chmod {0}".format(path))

    @trace_exceptions
    def chown(self, path, user, group):
        raise_read_only_error("Read-only file system, can't chown {0}".format(path))

    @trace_exceptions
    def truncate(self, path, size):
        raise_read_only_error("Read-only file system, can't truncate {0}".format(path))

    @trace_exceptions
    def mknod(self, path, mode, dev):
        raise_read_only_error("Read-only view, can't mknod {0}".format(path))

    @trace_exceptions
    def mkdir(self, path, mode):
        raise_read_only_error("Read-only view, can't mkdir {0}".format(path))
