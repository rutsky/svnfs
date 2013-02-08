#!/usr/bin/python2.3
#
#  Copyright (C) 2001  Jeff Epler  <jepler@unpythonic.dhs.org>
#  Copyright (C) 2005  Daniel Patterson  <danpat@danpat.net>
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

from fuse import Fuse
import os
from errno import *
from stat import *
import sys
import string
import binascii

from svn import fs, core, repos

import thread
class svnfs(Fuse):

    repospath = "/home/danpat/repos"

    def __init__(self, pool, *args, **kw):
    
        Fuse.__init__(self, *args, **kw)
    
        self.pool = pool
        self.taskpool = core.svn_pool_create(pool)
        self.fs_ptr = repos.svn_repos_fs(repos.svn_repos_open(svnfs.repospath, pool))
        self.rev = fs.youngest_rev(self.fs_ptr, pool)
        self.root = fs.revision_root(self.fs_ptr, self.rev, pool)
        
	self.multithreaded = 1;
	self.main()

    def mythread(self):
        """
        The beauty of the FUSE python implementation is that with the python interp
        running in foreground, you can have threads
        """    
        print "mythread: started"
        #while 1:
        #    time.sleep(120)
        #    print "mythread: ticking"
    
    flags = 1
    
    def getattr(self, path):
        mode = 0444
        size = 0

        kind = fs.check_path(self.root, path, self.taskpool)
        if kind == core.svn_node_none:
          e = OSError("Nothing found at %s " % path);
          e.errno = ENOENT;
          raise e
        elif kind == core.svn_node_dir:
          mode = mode | 0111
          mode = mode | 0040000
          size = 512
        else:
          mode = mode | 0100000
          size = fs.file_length(self.root, path, self.taskpool)          

        inode = fs.unparse_id(fs.node_id(self.root, path, self.taskpool), self.taskpool)
        inode = binascii.crc32(inode) 
        size = 0
        dev = 0
        nlink = 1
        uid = 0
        gid = 0

        created_rev = fs.node_created_rev(self.root, path, self.taskpool)
        date = fs.revision_prop(self.fs_ptr, created_rev, 
                                core.SVN_PROP_REVISION_DATE, self.taskpool)
        mtime = 0
        ctime = 0
        atime = 0
        kind = fs.check_path(self.root, path, self.taskpool)
        if kind == core.svn_node_dir:
          mode = mode | 0111
          mode = mode | 0040000
          size = 512
        else:
          mode = mode | 0100000
          size = fs.file_length(self.root, path, self.taskpool)          

        return (mode, inode, dev, nlink, uid, gid, size, atime, mtime, ctime)


    # TODO: support this
    def readlink(self, path):
        e = OSError("Not supported yet, readlink on %s " % path);
        e.errno = ENOENT;
        raise e

    def getdir(self, path):
        entries = fs.dir_entries(self.root, path, self.taskpool)
    	return map(lambda x: (x,0), entries.keys())

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
        kind = fs.check_path(self.root, path, self.taskpool)
        if kind != core.svn_node_file:
          e = OSError("Can't read a non-file %s" % path)
          e.errno = ENOENT;
          raise e

        stream = fs.file_contents(self.root, path, self.taskpool)
        core.svn_stream_read(stream, int(offset))
        return core.svn_stream_read(stream, len)
    
    def write(self, path, buf, off):
        e = OSError("Read-only view, can't mkdir %s " % path);
        e.errno = EROFS;
        raise e
    
    def release(self, path, flags):
        return 0

    def statfs(self):
        blocks_size = 1024
        blocks = 0
        blocks_free = 0
        files = 0
        files_free = 0
        namelen = 80
        return (blocks_size, blocks, blocks_free, files, files_free, namelen)

    def fsync(self, path, isfsyncfile):
        return 0
    
if __name__ == '__main__':

        core.run_app(svnfs, sys.argv)

