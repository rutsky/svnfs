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

import re
import threading
import stat
import errno
import binascii

import svn
import fuse
from repoze.lru import lru_cache

from svnfs import getattr_lru_cache_size


__all__ = ["AllRevisionsSvnFS", "SingleRevisionsSvnFS", "HeadRevisionsSvnFS"]


# TODO: move to configuration
check_new_revision_time = 3  # in seconds
getattr_lru_cache_size = 16384
getattr_rev_lru_cache_size = 16384

revision_dir_re = re.compile(r"^/(\d+|head)$")
file_re = re.compile(r"^/(\d+|head)(/.*)$")


class SvnFSBase(object):
    def __init__(self, repospath):
        self._repospath = repospath

    @property
    def _thread_pool(self):
        """Thread pool"""

        # TODO: Leaks a bit of memory with every thread.
        thread_data = threading.local()
        if not hasattr(thread_data, 'pool'):
            thread_data.pool = svn.core.Pool()
        return thread_data.pool

    @property
    def _thread_fs_ptr(self):
        """Thread Subversion opened repository file system"""

        # TODO: Leaks a bit of memory with every thread.
        thread_data = threading.local()
        if not hasattr(thread_data, 'fs_ptr'):
            pool = self._thread_pool
            canon_path = svn.core.svn_path_canonicalize(self._repospath, pool)
            repo = svn.repos.svn_repos_open(canon_path, pool)
            thread_data.fs_ptr = svn.repos.svn_repos_fs(repo)

        return thread_data.fs_ptr

    def _get_root(self, rev, pool):
        return svn.fs.revision_root(self._thread_fs_ptr, rev, pool)
    
    def node_revision_id(self, rev, path, pool):
        root = self._get_root(rev, pool)
        node_id = svn.fs.node_id(root, path, pool)
        return svn.fs.unparse_id(node_id, pool)

    @lru_cache(getattr_lru_cache_size)
    def get_svn_path_attr(self, rev, path):
        pool = svn.core.Pool(self._thread_pool)

        st = fuse.Stat()

        root = self._get_root(rev, pool)

        kind = svn.fs.check_path(root, path, pool)
        if kind == svn.core.svn_node_none:
            e = OSError("Nothing found at {0}".format(path))
            e.errno = errno.ENOENT
            raise e

        # TODO: Using CRC32 of node ID as inode
        st.st_ino = svn.fs.unparse_id(svn.fs.node_id(root, path, pool), pool)
        st.st_ino = abs(binascii.crc32(st.st_ino))

        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = 1
        st.st_uid = 0
        st.st_gid = 0

        created_rev = svn.fs.node_created_rev(root, path, pool)
        time = self.__revision_creation_time(created_rev, pool)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time

        if kind == svn.core.svn_node_dir:
            st.st_mode = stat.S_IFDIR | 0o555
            st.st_size = 512
        else:
            st.st_mode = stat.S_IFREG | 0o444
            st.st_size = svn.fs.file_length(root, path, pool)

        return st
    
    def _revision_creation_time(self, rev, pool):
        date = svn.fs.revision_prop(self._thread_fs_ptr, rev,
            svn.core.SVN_PROP_REVISION_DATE, pool)
        return svn.core.secs_from_timestr(date, pool)

    def is_file_exists(self, rev, path, pool):
        root = self._get_root(rev, pool)
        kind = svn.fs.check_path(root, path, pool)
        return kind != svn.core.svn_node_none

    @lru_cache(1, timeout=check_new_revision_time)
    def youngest_rev(self):
        pool = svn.core.Pool(self._thread_pool)
        return svn.fs.youngest_rev(self._thread_fs_ptr, pool)

    @lru_cache(1, timeout=check_new_revision_time)
    def _get_root_attr(self):
        pool = svn.core.Pool(self.pool_storage.get_pool())

        st = fuse.Stat()

        rev = self.svnfs_youngest_rev()

        st.st_ino = 0

        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = rev + 1
        st.st_uid = 0
        st.st_gid = 0

        time = self.__revision_creation_time(rev, pool)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time

        st.st_mode = stat.S_IFDIR | 0o555
        st.st_size = 512

        return st

    @lru_cache(getattr_rev_lru_cache_size)
    def _get_rev_dir_attr(self, rev):
        pool = svn.core.Pool(self.pool_storage.get_pool())

        st = fuse.Stat()

        st.st_ino = 0

        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = 1
        st.st_uid = 0
        st.st_gid = 0

        time = self.__revision_creation_time(rev, pool)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time

        st.st_mode = stat.S_IFDIR | 0o555
        st.st_size = 512

        return st

    def getattr(self, path):
        raise NotImplementedError("abstract getattr()")

    def _parse_rev(self, rev):
        if rev == 'head':
            return self.youngest_rev()
        else:
            return int(rev)
        
    def __get_files_list_svn(self, root, path, pool):
        # TODO: check that directory exists first?
        return svn.fs.dir_entries(root, path, pool).keys()

    def __get_files_list(self, path, pool):
        if self.revision == 'all':
            if path == "/":
                rev = self.svnfs_youngest_rev()
                return map(str, range(1, rev + 1))

            m = revision_dir_re.match(path)
            if m:
                rev = self.svnfs_get_rev(m.group(1))
                root = self.svnfs_get_root(rev, pool)
                return self.__get_files_list_svn(root, "/", pool)

            m = file_re.match(path)
            if m:
                rev = self.svnfs_get_rev(m.group(1))
                path = m.group(2)
                root = self.svnfs_get_root(rev, pool)
                return self.__get_files_list_svn(root, path, pool)
        else:
            root = self.svnfs_get_root(self.rev, pool)
            return self.__get_files_list_svn(root, path, pool)

        e = OSError("Nothing found at {0}".format(path))
        e.errno = errno.ENOENT
        raise e


class AllRevisionsSvnFS(SvnFSBase):
    def __init__(self, repospath):
        super(AllRevisionsSvnFS, self).__init__(repospath)

    def getattr(self, path):
        if path == "/":
            return self._get_root_attr()

        m = revision_dir_re.match(path)
        if m:
            rev = self._parse_rev(m.group(1))
            return self._get_rev_attr(rev)

        m = file_re.match(path)
        if m:
            rev = self._parse_rev(m.group(1))
            svn_path = m.group(2)
            return self._get_svn_path_attr(rev, svn_path)

        e = OSError("Nothing found at {0}".format(path))
        e.errno = errno.ENOENT
        raise e


class SingleRevisionsSvnFS(SvnFSBase):
    def __init__(self, repospath, revision):
        super(AllRevisionsSvnFS, self).__init__(repospath)
        self.revision = revision

    def getattr(self, path):
        return self.get_svn_path_attr(self.revision, path)

class HeadRevisionsSvnFS(SingleRevisionsSvnFS):
    def __init__(self, repospath):
        super(AllRevisionsSvnFS, self).__init__(repospath, None)

    @property
    def revision(self):
        return self.youngest_rev()
