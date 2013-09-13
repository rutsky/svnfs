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

import os
import signal

import fuse
import svn

from svnfs.fuse_utils import FuseReadOnlyMixin
from svnfs.exceptions import trace_exceptions
from svnfs.daemon_utils import redirect_output


__all__ = ["SvnFS"]


class SvnFS(fuse.Fuse, FuseReadOnlyMixin):

    # TODO: pass options such as pool_storage as arguments
    def __init__(self, *args, **kw):
        fuse.Fuse.__init__(self, *args, **kw)

        self.repospath = None
        self.revision = None

        self.uid = None
        self.gid = None

        self.logfile = None
        self.send_sigstop = None
        self.cache_dir = None
        
        self.pool_storage = None

    # TODO: exceptions here not handled properly, so output them manually
    @trace_exceptions
    def fsinit(self):
        try:
            # Redirect output to log file (in privileged mode)
            if self.logfile is not None:
                redirect_output(self.logfile)

            # Drop privileges
            if self.gid is not None:
                os.setgid(self.gid)
            if self.uid is not None:
                os.setuid(self.uid)

        finally:
            if self.send_sigstop:
                os.kill(os.getpid(), signal.SIGSTOP)

    def init_repo(self, file_class):
        # Called from main thread before daemonizing.
        assert self.repospath is not None

        pool = self.pool_storage.get_pool()

        # Try to open repository
        svn.repos.svn_repos_fs(
            svn.repos.svn_repos_open(
                svn.core.svn_path_canonicalize(self.repospath, pool), pool))

        if self.revision != 'all':
            if self.revision == 'head':
                self.rev = self.svnfs_youngest_rev()
            else:
                self.rev = self.revision
            self.file_class = SvnFSSingleRevisionFile
        else:
            self.file_class = SvnFSAllRevisionsFile
        self.file_class.svnfs = self

        self.files_cache = FilesCache(self.cache_dir)

        self.fs_ptrs = {}


    # TODO?
    #def access(self, path, mode):
    #    if not os.access("." + path, mode):
    #        return -EACCES



    # TODO: support this
    @trace_exceptions
    def readlink(self, path):
        e = OSError("Not supported yet, readlink on {0}".format(path))
        e.errno = errno.ENOENT
        raise e


    @trace_exceptions
    def getdir(self, path):
        pool = svn.core.Pool(self.pool_storage.get_pool())
        return map(lambda x: (x, 0), self.__get_files_list(path, pool))

    @trace_exceptions
    def readdir(self, path, offset):
        # TODO: offset?

        pool = svn.core.Pool(self.pool_storage.get_pool())

        if path == '/':
            yield fuse.Direntry('head')

        for f in  self.__get_files_list(path, pool) + [".", ".."]:
            yield fuse.Direntry(f)

    @trace_exceptions
    def utime(self, path, times):
        return os.utime(path, times)

    def svnfs_read(self, rev, path, node_revision_id, length, offset, pool):
        cache_file = self.files_cache.get_file_path(node_revision_id)

        if not cache_file:
            # File not cached - get it and cache it
            src_stream = svn.fs.file_contents(self.svnfs_get_root(rev, pool), path, pool)
            with tempfile.NamedTemporaryFile(dir=self.files_cache.cache_temp_dir, delete=False) as destf:
                temp_file_name = destf.name

                bs = 4096 * 1024
                while True:
                    block = svn.core.svn_stream_read(src_stream, bs)
                    if len(block) == 0:
                        break
                    destf.write(block)

            svn.core.svn_stream_close(src_stream)

            cache_file = self.files_cache.put_file(node_revision_id, temp_file_name)

        # File contents already cached
        with open(cache_file, "rb") as f:
            f.seek(offset)
            return f.read(length)

    @trace_exceptions
    def statfs(self):
        st = fuse.StatVfs()

        st.f_bsize = 1024
        st.f_blocks = 0
        st.f_bfree = 0
        st.f_files = 0
        st.f_ffree = 0
        st.f_namelen = 80 # TODO

        return st
