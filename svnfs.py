#!/usr/bin/env python
#
#  Copyright (C) 2001  Jeff Epler  <jepler@unpythonic.dhs.org>
#  Copyright (C) 2005  Daniel Patterson  <danpat@danpat.net>
#  Copyright (C) 2013  Vladimir.Rutsky  <rutsky.vladimir@gmail.com>
#
#  This program can be distributed under the terms of the GNU GPL.
#  See the file COPYING.
#
#  This program was adapted from xmp.py included with the FUSE Python bindings.
#
#  This is a FUSE module using the Python bindings.  It allows you to mount
#  a local subversion repository filesystem into the host filesystem, read-only.
#  
#  TODO: - support mtime and ctime
#        - support symlinks
#        - more efficient reading of files (maybe a cache?)
#        - support following HEAD as it moves, or pegging to a revision
#          (right now, we're pegged to youngest_rev when we start)
#        - support some kind of "magic" meta syntax, i.e. "cat trunk@@log", a-la
#          clearcase MVFS
#        - mount arbitary sub-trees within the repository
#        - work out a better way to represent inodes than binascii.crc32()
#
#  USAGE:  - modify "repospath" below
#          - install and load the "fuse" kernel module 
#            (tested with Linux 2.6.10, Fuse 2.2.1)
#          - run "svnfs.py /mnt/wherever" or "fusermount /mnt/wherever ./svnfs.py"
#          - run "fusermount -u /mnt/wherever" to unmount

import fuse
fuse.fuse_python_api = (0, 2)
from fuse import Fuse
import os
from errno import *
from stat import *
import sys
import string
import binascii

import svn
import svn.repos
import svn.fs
import svn.core

# Import threading modules. TODO: Otherwise program prints on exit:
# Exception KeyError: KeyError(139848519223040,) in <module 'threading' from '/usr/lib64/python2.7/threading.pyc'> ignored
import threading


class SvnFS(Fuse):
    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        
    def init_repo(self, repospath):
        self.fs_ptr = svn.repos.svn_repos_fs(svn.repos.svn_repos_open(svn.core.svn_dirent_canonicalize(repospath)))
        self.rev = svn.fs.youngest_rev(self.fs_ptr)
        self.root = svn.fs.revision_root(self.fs_ptr, self.rev)
        
        # TODO
        self.pool = self.taskpool = None

    def getattr(self, path):
        st = fuse.Stat()

        kind = svn.fs.check_path(self.root, path, self.taskpool)
        if kind == svn.core.svn_node_none:
            e = OSError("Nothing found at %s " % path)
            e.errno = ENOENT;
            raise e

        # TODO: CRC of some id?
        st.st_ino = svn.fs.unparse_id(svn.fs.node_id(self.root, path, self.taskpool), self.taskpool)
        st.st_ino = abs(binascii.crc32(st.st_ino))
        
        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = 1
        st.st_uid = 0
        st.st_gid = 0

        created_rev = svn.fs.node_created_rev(self.root, path, self.taskpool)
        date = svn.fs.revision_prop(self.fs_ptr, created_rev,
                                svn.core.SVN_PROP_REVISION_DATE, self.taskpool)
        # TODO: this is modification time, not creation or access
        time = svn.core.secs_from_timestr(date, self.taskpool)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time
        
        if kind == svn.core.svn_node_dir:
            st.st_mode = S_IFDIR | 0555
            st.st_size = 512
        else:
            st.st_mode = S_IFREG | 0444
            st.st_size = svn.fs.file_length(self.root, path, self.taskpool)

        return st

    # TODO: support this
    def readlink(self, path):
        e = OSError("Not supported yet, readlink on %s " % path);
        e.errno = ENOENT;
        raise e

    def __get_files_list(self, path):
        # TODO: check that directory exists first?
        return svn.fs.dir_entries(self.root, path, self.taskpool).keys()

    def getdir(self, path):
        return map(lambda x: (x, 0), self.__get_files_list(path))

    def readdir(self, path, offset):
        # TODO: offset?
        for f in  self.__get_files_list(path) + [".", ".."]:
            yield fuse.Direntry(f)

    def unlink(self, path):
        e = OSError("Read-only view, can't unlink %s " % path);
        e.errno = EROFS;
        raise e

    def rmdir(self, path):
        e = OSError("Read-only view, can't rmdir %s " % path);
        e.errno = EROFS;
        raise e

    def symlink(self, path, path1):
        e = OSError("Read-only view, can't symlink %s " % path);
        e.errno = EROFS;
        raise e

    def rename(self, path, path1):
        e = OSError("Read-only view, can't rename %s " % path);
        e.errno = EROFS;
        raise e

    def link(self, path, path1):
        e = OSError("Read-only view, can't link %s " % path);
        e.errno = EROFS;
        raise e

    def chmod(self, path, mode):
        e = OSError("Read-only view, can't chmod %s " % path);
        e.errno = EROFS;
        raise e

    def chown(self, path, user, group):
        e = OSError("Read-only view, can't chown %s " % path);
        e.errno = EROFS;
        raise e

    def truncate(self, path, size):
        e = OSError("Read-only view, can't truncate %s " % path);
        e.errno = EROFS;
        raise e

    def mknod(self, path, mode, dev):
        e = OSError("Read-only view, can't mknod %s " % path);
        e.errno = EROFS;
        raise e

    def mkdir(self, path, mode):
        e = OSError("Read-only view, can't mkdir %s " % path);
        e.errno = EROFS;
        raise e

    def utime(self, path, times):
        return os.utime(path, times)

    def open(self, path, flags):
        if ((flags & os.O_WRONLY) or (flags & os.O_RDWR) or (flags & os.O_APPEND) or \
           (flags & os.O_CREAT) or (flags & os.O_TRUNC) or (flags & os.O_TRUNC)):
            e = OSError("Read-only view, can't create %s " % path);
            e.errno = EROFS;
            raise e
        return 0
    
    def read(self, path, len, offset):
        kind = svn.fs.check_path(self.root, path, self.taskpool)
        if kind != svn.core.svn_node_file:
            e = OSError("Can't read a non-file %s" % path)
            e.errno = ENOENT;
            raise e

        stream = svn.fs.file_contents(self.root, path, self.taskpool)
        svn.core.svn_stream_read(stream, int(offset))
        return svn.core.svn_stream_read(stream, len)
    
    def write(self, path, buf, off):
        e = OSError("Read-only view, can't mkdir %s " % path);
        e.errno = EROFS;
        raise e
    
    def release(self, path, flags):
        return 0

    def statfs(self):
        st = fuse.StatVfs()
        
        st.f_bsize = 1024
        st.f_blocks = 0
        st.f_bfree = 0
        st.f_files = 0
        st.f_ffree = 0
        st.f_namelen = 80
        
        return st

    def fsync(self, path, isfsyncfile):
        return 0

if __name__ == '__main__':
    usage = "Usage: %prog svn_repository_dir mountpoint [options]"
    svnfs = SvnFS(version="%prog " + fuse.__version__, dash_s_do='setsingle', usage=usage)
    
    svnfs.parse(values=svnfs, errex=1)
    
    if svnfs.parser.fuse_args.mount_expected():
        if len(svnfs.cmdline[1]) == 0:
            sys.stderr.write("Error: Subversion repository directory not specified\n")
            sys.exit(1)
        elif len(svnfs.cmdline[1]) > 1:
            sys.stderr.write("Error: Too much positional arguments\n")
            sys.exit(1)
        else:
            repopath = os.path.abspath(svnfs.cmdline[1][0])
        
            # When FUSE daemonizes it changes CWD to root, do it manually.
            os.chdir("/")

            svnfs.init_repo(repopath)

    try:
        svnfs.main()
    except fuse.FuseError as s:
        sys.stderr.write("Fuse failed: {0}\n".format(str(s)))
