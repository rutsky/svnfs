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
#  TODO: - support symlinks
#        - more efficient reading of files (maybe a cache?)
#        - support following HEAD as it moves, or pegging to a revision
#          (right now, we're pegged to youngest_rev when we start)
#        - support some kind of "magic" meta syntax, i.e. "cat trunk@@log", a-la
#          clearcase MVFS
#        - mount arbitary sub-trees within the repository
#        - work out a better way to represent inodes than binascii.crc32()
#
#  bob TODO:
#        - try use statefull files as in xmp.py example
#        - write tests
#        - use logging
#
#  USAGE:  - install and load the "fuse" kernel module 
#          - run "svnfs.py /mnt/wherever -o svnrepo=/var/lib/svn/repodir" or
#            "svnfs.py /var/lib/svn/repodir /mnt/wherever"
#          - run "fusermount -u /mnt/wherever" to unmount

import os
import re
import sys
import pwd
import grp
import datetime
import binascii
import traceback
import functools
import stat
import errno

try:
    from collections import OrderedDict
except ImportError:
    from OrderedDict import OrderedDict

# Import threading modules. TODO: Otherwise program prints on exit:
# Exception KeyError: KeyError(139848519223040,) in <module 'threading' from '/usr/lib64/python2.7/threading.pyc'> ignored
import threading

import fuse
fuse.fuse_python_api = (0, 2)
fuse.feature_assert('has_init')
from fuse import Fuse

import svn.repos
import svn.fs
import svn.core


class LimitedSizeDict(OrderedDict):
    """http://stackoverflow.com/questions/2437617/limiting-the-size-of-a-python-dictionary"""
    def __init__(self, *args, **kwds):
        self.size_limit = kwds.pop("size_limit", None)
        OrderedDict.__init__(self, *args, **kwds)
        self._check_size_limit()

    def __setitem__(self, key, value):
        OrderedDict.__setitem__(self, key, value)
        self._check_size_limit()

    def _check_size_limit(self):
        if self.size_limit is not None:
            while len(self) > self.size_limit:
                self.popitem(last=False)


def redirect_output(output_file):
    # Flush output before setting redirection
    sys.stdout.flush()
    sys.stderr.flush()
    
    # Redirect stdout and stderr to log file
    log_fd = os.open(output_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)


def print_caught_exception(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except:
            sys.stderr.write("print_caught_exception():\n")
            traceback.print_exc(None, sys.stderr)
            sys.stderr.flush()
            raise
    return wrapper


class SvnFS(Fuse):
    revision_dir_re = re.compile(r"^/(\d+)$")
    file_re = re.compile(r"^/(\d+)(/.*)$")

    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)
        
        self.repospath = None
        self.revision = None
        
        self.uid = None
        self.gid = None
        self.logfile = None
    
    # TODO: exceptions here not handled properly, so output them manually
    @print_caught_exception
    def fsinit(self):
        # Called only in daemon mode?
    
        # Redirect output to log file (in privileged mode)
        if self.logfile is not None:
            redirect_output(self.logfile)

        # Drop privileges
        if self.gid is not None:
            os.setgid(self.gid)
        if self.uid is not None:
            os.setuid(self.uid)

    def init_repo(self):
        assert self.repospath is not None
    
        self.fs_ptr = svn.repos.svn_repos_fs(svn.repos.svn_repos_open(svn.core.svn_path_canonicalize(self.repospath)))
        
        # revision -> revision_root object
        self.roots = {}
        
        if self.revision != 'all':
            self.rev = svn.fs.youngest_rev(self.fs_ptr) if self.revision == 'head' else svnfs.revision

        # revision -> time
        self.revision_creation_time_cache = {}
        
        # (rev, path) -> [stream, offset, lock]
        self.file_stream_cache = LimitedSizeDict(size_limit=100)
        
    def __get_file_stream(self, rev, path):
        return self.file_stream_cache.setdefault((rev, path),
            [svn.fs.file_contents(self.__get_root(rev), path), 
             0,
             threading.RLock()])
    
    def __revision_creation_time_impl(self, rev):
        date = svn.fs.revision_prop(self.fs_ptr, rev,
            svn.core.SVN_PROP_REVISION_DATE)
        return svn.core.secs_from_timestr(date)

    def __revision_creation_time(self, rev):
        return self.revision_creation_time_cache.setdefault(rev, self.__revision_creation_time_impl(rev))
    
    def __get_root(self, rev):
        return self.roots.setdefault(rev, svn.fs.revision_root(self.fs_ptr, rev))

    def __getattr_svn(self, root, path):
        st = fuse.Stat()

        kind = svn.fs.check_path(root, path)
        if kind == svn.core.svn_node_none:
            e = OSError("Nothing found at %s " % path)
            e.errno = errno.ENOENT
            raise e

        # TODO: CRC of some id?
        st.st_ino = svn.fs.unparse_id(svn.fs.node_id(root, path))
        st.st_ino = abs(binascii.crc32(st.st_ino))
        
        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = 1
        st.st_uid = 0
        st.st_gid = 0

        created_rev = svn.fs.node_created_rev(root, path)
        time = self.__revision_creation_time(created_rev)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time
        
        if kind == svn.core.svn_node_dir:
            st.st_mode = stat.S_IFDIR | 0555
            st.st_size = 512
        else:
            st.st_mode = stat.S_IFREG | 0444
            st.st_size = svn.fs.file_length(root, path)

        return st
        
    def __getattr_root(self):
        st = fuse.Stat()
        
        rev = svn.fs.youngest_rev(self.fs_ptr)

        st.st_ino = 0
        
        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = rev + 1
        st.st_uid = 0
        st.st_gid = 0

        time = self.__revision_creation_time(rev)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time
        
        st.st_mode = stat.S_IFDIR | 0555
        st.st_size = 512

        return st

    def __getattr_rev(self, rev):
        st = fuse.Stat()
        
        st.st_ino = 0
        
        st.st_size = 0
        st.st_dev = 0
        st.st_nlink = 1
        st.st_uid = 0
        st.st_gid = 0

        time = self.__revision_creation_time(rev)
        st.st_mtime = time
        st.st_ctime = time
        st.st_atime = time
        
        st.st_mode = stat.S_IFDIR | 0555
        st.st_size = 512

        return st
    
    def getattr(self, path):
        if self.revision == 'all':
            if path == "/":
                return self.__getattr_root()
            
            m = self.revision_dir_re.match(path)
            if m:
                return self.__getattr_rev(int(m.group(1)))
        
            m = self.file_re.match(path)
            if m:
                return self.__getattr_svn(self.__get_root(int(m.group(1))), m.group(2))
        else:
            return self.__getattr_svn(self.__get_root(self.rev), path)
        
        e = OSError("Nothing found at %s " % path)
        e.errno = errno.ENOENT
        raise e

    # TODO: support this
    @print_caught_exception
    def readlink(self, path):
        e = OSError("Not supported yet, readlink on %s " % path)
        e.errno = errno.ENOENT
        raise e

    def __get_files_list_svn(self, root, path):
        # TODO: check that directory exists first?
        return svn.fs.dir_entries(root, path).keys()

    def __get_files_list(self, path):
        if self.revision == 'all':
            if path == "/":
                rev = svn.fs.youngest_rev(self.fs_ptr)
                return map(str, range(1, rev + 1))

            m = self.revision_dir_re.match(path)
            if m:
                return self.__get_files_list_svn(self.__get_root(int(m.group(1))), "/")
            
            m = self.file_re.match(path)
            if m:
                return self.__get_files_list_svn(self.__get_root(int(m.group(1))), m.group(2))
        else:
            return self.__get_files_list_svn(self.__get_root(self.rev), path)

        e = OSError("Nothing found at %s " % path)
        e.errno = errno.ENOENT
        raise e

    @print_caught_exception
    def getdir(self, path):
        return map(lambda x: (x, 0), self.__get_files_list(path))

    @print_caught_exception
    def readdir(self, path, offset):
        # TODO: offset?
        for f in  self.__get_files_list(path) + [".", ".."]:
            yield fuse.Direntry(f)

    @print_caught_exception
    def unlink(self, path):
        e = OSError("Read-only view, can't unlink %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def rmdir(self, path):
        e = OSError("Read-only view, can't rmdir %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def symlink(self, path, path1):
        e = OSError("Read-only view, can't symlink %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def rename(self, path, path1):
        e = OSError("Read-only view, can't rename %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def link(self, path, path1):
        e = OSError("Read-only view, can't link %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def chmod(self, path, mode):
        e = OSError("Read-only view, can't chmod %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def chown(self, path, user, group):
        e = OSError("Read-only view, can't chown %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def truncate(self, path, size):
        e = OSError("Read-only view, can't truncate %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def mknod(self, path, mode, dev):
        e = OSError("Read-only view, can't mknod %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def mkdir(self, path, mode):
        e = OSError("Read-only view, can't mkdir %s " % path)
        e.errno = errno.EROFS
        raise e

    @print_caught_exception
    def utime(self, path, times):
        return os.utime(path, times)

    @print_caught_exception
    def open(self, path, flags):
        # TODO: check existence?
        if ((flags & os.O_WRONLY) or (flags & os.O_RDWR) or (flags & os.O_APPEND) or \
           (flags & os.O_CREAT) or (flags & os.O_TRUNC) or (flags & os.O_TRUNC)):
            e = OSError("Read-only view, can't create %s " % path)
            e.errno = errno.EROFS
            raise e

        return 0
    
    def __read_svn(self, rev, path, length, offset):
        root = self.__get_root(rev)
        kind = svn.fs.check_path(root, path)
        if kind != svn.core.svn_node_file:
            e = OSError("Can't read a non-file %s" % path)
            e.errno = errno.ENOENT
            raise e

        stream_offset_lock = self.__get_file_stream(rev, path)
        with stream_offset_lock[2]:
            if stream_offset_lock[1] > offset:
                # TODO: log
                sys.stdout.write("Cache miss for r{0} '{1}' offset={2} length={3}\n".format(rev, path, offset, length))
                sys.stdout.flush()

                stream_offset_lock[0] = svn.fs.file_contents(root, path)
                stream_offset_lock[1] = 0
            
            seek_cur = int(offset) - stream_offset_lock[1]
            if seek_cur > 0:
                # Skip not needed
                svn.core.svn_stream_read(stream_offset_lock[0], seek_cur)
            data = svn.core.svn_stream_read(stream_offset_lock[0], length)
            
            stream_offset_lock[1] += seek_cur + length
            
            return data

    @print_caught_exception
    def read(self, path, length, offset):
        if self.revision == 'all':
            m = self.file_re.match(path)
            if m:
                return self.__read_svn(int(m.group(1)), m.group(2), length, offset)
        else:
            return self.__read_svn(self.rev, path, length, offset)
        
        e = OSError("Nothing found at %s " % path)
        e.errno = errno.ENOENT
        raise e
    
    @print_caught_exception
    def write(self, path, buf, off):
        e = OSError("Read-only view, can't mkdir %s " % path)
        e.errno = errno.EROFS
        raise e
    
    @print_caught_exception
    def release(self, path, flags):
        return 0

    @print_caught_exception
    def statfs(self):
        st = fuse.StatVfs()
        
        st.f_bsize = 1024
        st.f_blocks = 0
        st.f_bfree = 0
        st.f_files = 0
        st.f_ffree = 0
        st.f_namelen = 80 # TODO
        
        return st

    @print_caught_exception
    def fsync(self, path, isfsyncfile):
        return 0

if __name__ == '__main__':
    usage = ("Usage: %prog svn_repository_dir mountpoint [options]\n"
             "    or\n"
             "       %prog mountpoint -o svnrepo=SVN-REPO-DIR [options]\n")
    svnfs = SvnFS(version="%prog " + fuse.__version__, dash_s_do='setsingle', usage=usage)
    
    svnfs.parser.add_option(mountopt="svnrepo", dest="repospath", metavar="SVN-REPO-DIR",
        help="path to subversion reposiotory")
    svnfs.parser.add_option(mountopt="revision", dest="revision", default="all", metavar="REV",
        help="revision specification: 'all', 'HEAD' or number [default: %default]")
    svnfs.parser.add_option(mountopt="uid", dest="uid", metavar="UID",
        help="run daemon under different user ID")
    svnfs.parser.add_option(mountopt="gid", dest="gid", metavar="GID",
        help="run daemon under different group ID")

    svnfs.parser.add_option(mountopt="logfile", dest="logfile", metavar="PATH-TO-LOG-FILE",
        help="output stdout/stderr into file")
    
    svnfs.parse(values=svnfs, errex=1)
    
    # Redirect output at early stage
    if svnfs.logfile is not None:
        svnfs.logfile = os.path.abspath(svnfs.logfile)
        redirect_output(svnfs.logfile)
        print "Log opened at {0}".format(str(datetime.datetime.now()))
        sys.stdout.flush()
    
    if svnfs.parser.fuse_args.mount_expected():
        if len(svnfs.cmdline[1]) > 1:
            sys.stderr.write("Error: Too much positional arguments\n")
            sys.exit(1)
        elif len(svnfs.cmdline[1]) == 1:
            if svnfs.repospath:
                sys.stderr.write("Error: Subversion repository directory specified multiple times.\n")
                sys.exit(1)
            svnfs.repospath = svnfs.cmdline[1][0]
    
        if not svnfs.repospath:
            sys.stderr.write(
                "Error: Subversion repository directory is required option, please specify it\n"
                "using '-o svnrepo=/var/lib/svn/path-to-repository' option.\n")
            sys.exit(1)
        else:
            svnfs.repospath = os.path.abspath(svnfs.repospath)
        
            # When FUSE daemonizes it changes CWD to root, do it manually.
            os.chdir("/")
            
            if svnfs.gid is not None:
                # Convert GID to numeric
                
                try:
                    svnfs.gid = int(svnfs.gid)
                except ValueError:
                    svnfs.gid = grp.getgrnam(svnfs.gid).gr_gid
            
            if svnfs.uid is not None:
                # Convert UID to numeric
                
                try:
                    svnfs.uid = int(svnfs.uid)
                except ValueError:
                    svnfs.uid = pwd.getpwnam(svnfs.uid).pw_uid

            if svnfs.revision is None:
                svnfs.revision = "all"
            svnfs.revision = svnfs.revision.lower()
            try:
                svnfs.revision = int(svnfs.revision)
            except ValueError:
                if svnfs.revision not in ['all', 'head']:
                    sys.stderr.write("Error: Invalid revision specification. Should be number, 'all' or 'HEAD'.\n")
                    sys.exit(1)

            # Open subversion repository before going to FUSE main loop, to handle obvious
            # repository access errors.
            try:
                svnfs.init_repo()
            except svn.core.SubversionException as e:
                sys.stderr.write("Subversion repository opening failed: {0}\n".format(str(e)))
                sys.exit(1)

    # Flush output before daemonizing
    sys.stdout.flush()
    sys.stderr.flush()
    
    try:
        svnfs.main()
    except fuse.FuseError as e:
        sys.stderr.write("Fuse failed: {0}\n".format(str(e)))
        sys.exit(1)

# vim: set ts=4 sw=4 et:
