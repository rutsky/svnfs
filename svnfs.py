#!/usr/bin/env python
#
#  Copyright (C) 2001  Jeff Epler  <jepler@unpythonic.dhs.org>
#  Copyright (C) 2005  Daniel Patterson  <danpat@danpat.net>
#  Copyright (C) 2013  Vladimir Rutsky  <rutsky.vladimir@gmail.com>
#
#  This program can be distributed under the terms of the GNU GPL.
#  See the file COPYING.
#
#  This program was adapted from xmp.py included with the FUSE Python bindings.
#
#  This is a FUSE module using the Python bindings.  It allows you to mount
#  a local subversion repository file system into the host file system, read-only.
#
#  TODO: - support symlinks
#        - support following HEAD as it moves, or pegging to a revision
#          (right now, we're pegged to youngest_rev when we start)
#        - support some kind of "magic" meta syntax, i.e. "cat trunk@@log", a-la
#          clearcase MVFS
#        - mount arbitary sub-trees within the repository
#        - work out a better way to represent inodes than binascii.crc32()
#
#  bob TODO:
#        - use logging
#        - check is current way of reporting errors (by throwing exception
#          with errno is correct)
#        - don't read whole file on first read - implement opened streams
#          storing and caching
#        - create cache in /tmp by default
#
#  USAGE:
#        - install and load the "fuse" kernel module
#        - run "svnfs.py /mnt/wherever -o svnrepo=/var/lib/svn/repodir" or
#          "svnfs.py /var/lib/svn/repodir /mnt/wherever"
#        - run "fusermount -u /mnt/wherever" to unmount

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


revision_dir_re = re.compile(r"^/(\d+|head)$")
file_re = re.compile(r"^/(\d+|head)(/.*)$")


def redirect_output(output_file):
    # Flush output before setting redirection
    sys.stdout.flush()
    sys.stderr.flush()

    # Redirect stdout and stderr to log file
    log_fd = os.open(output_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)


def trace_exceptions(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ManagedOSError:
            # Skip exceptions about read only file system
            raise
        except:
            sys.stderr.write("\n"
                             "    *** EXCEPTION ***:\n")
            traceback.print_exc()

            try:
                f_file = inspect.getfile(function)
            #except TypeError:
            except:
                f_file = "unknown"

            try:
                lines, f_line = inspect.getsourcelines(function)
            #except IOError:
            except:
                lines, f_line = ["<unknown>\n"], "unknown"

            sys.stderr.write("\nWhen invoking\n  File \"{file}\", line {line} in {name}\n    {code}".format(
                name=function.__name__, file=f_file, line=f_line,
                code=lines[0]))

            sys.stderr.write("    ***    END    ***\n"
                             "\n")
            sys.stderr.flush()
            raise
    return wrapper


def is_write_mode(flags):
    return ((flags & os.O_WRONLY) or
            (flags & os.O_RDWR) or
            (flags & os.O_APPEND) or
            (flags & os.O_CREAT) or
            (flags & os.O_TRUNC))


class ManagedOSError(OSError):
    pass

def raise_read_only_error(msg=None):
    if msg is not None:
        error_msg = msg
    else:
        error_msg = "Read-only file system"
    e = ManagedOSError(error_msg)
    e.errno = errno.EROFS
    raise e


def raise_no_such_entry_error(msg=None):
    if msg is not None:
        error_msg = msg
    else:
        error_msg = "No such entry."
    e = ManagedOSError(error_msg)
    e.errno = errno.ENOENT
    raise e


def encode_node_revision_id(node_revision_id):
    """Encode node revision id string correct file name"""
    return node_revision_id.encode("hex")


class FilesCache(object):
    # TODO: store files not in plain directory, but in equally distributed
    # tree.
    # TODO: touch opened files, to allow implementing external cache
    # cleaning.

    cache_version = 1

    def __init__(self, cache_dir):
        self.cache_dir = cache_dir

        if not os.path.isdir(self.cache_dir):
            os.makedirs(self.cache_dir)

        self.cache_db = shelve.open(os.path.join(self.cache_dir, "db"), protocol=pickle.HIGHEST_PROTOCOL)
        if "version" not in self.cache_db:
            self.cache_db["version"] = self.cache_version
        elif self.cache_db["version"] != self.cache_version:
            raise RuntimeError("Cache version mismatch")

        self.cache_db.sync()

        self.cache_db_lock = synch.RWLock()

        self.cache_files_dir = os.path.join(self.cache_dir, "cache")
        self.cache_temp_dir = os.path.join(self.cache_dir, "tmp")

        if not os.path.isdir(self.cache_files_dir):
            os.mkdir(self.cache_files_dir)
        if not os.path.isdir(self.cache_temp_dir):
            os.mkdir(self.cache_temp_dir)

        assert self.check_integrity()

    def check_integrity(self):
        with self.cache_db_lock.read_lock():
            dir_cache_files = os.listdir(self.cache_files_dir)
            db_cache_files = []
            for key, value in self.cache_db.iteritems():
                if key != "version":
                    db_cache_files.append(value["cache_file"])

            return set(dir_cache_files) == set(db_cache_files)

    def fix_integrity(self):
        """Check non-existing or not-registered items and removes them"""
        # TODO
        pass

    def build_db_from_cache(self):
        """Built cache database from existing files cache"""
        # TODO
        pass

    def get_file_path(self, node_revision_id):
        with self.cache_db_lock.read_lock():
            if node_revision_id in self.cache_db:
                cache_file = self.cache_db[node_revision_id]["cache_file"]
                return os.path.join(self.cache_files_dir, cache_file)
            else:
                return None

    def put_file(self, node_revision_id, temp_file_path):
        with self.cache_db_lock.write_lock():
            if node_revision_id not in self.cache_db:
                # File still not cached
                cache_file = encode_node_revision_id(node_revision_id)
                full_path = os.path.join(self.cache_files_dir, cache_file)

                shutil.move(temp_file_path, full_path)

                self.cache_db[node_revision_id] = dict(cache_file=cache_file)
                self.cache_db.sync()

                return full_path
            else:
                # Someone else cached file

                os.remove(temp_file_path)

                cache_file = self.cache_db[node_revision_id]["cache_file"]
                return os.path.join(self.cache_files_dir, cache_file)


class SvnFSFileBase(object):
    def __init__(self, path, flags, *mode):
        super(SvnFSFileBase, self).__init__()

        # TODO: not sure is this needed and what it does
        self.keep = True
        self.keep_cache = True
        self.direct_io = False

        if is_write_mode(flags):
            raise_read_only_error("Read-only file system. Can't create '{0}'".format(path))

    def svnfs_init(self, rev, path):
        # Revision and path in revision must exists

        self.rev = rev
        self.path = path

    @trace_exceptions
    def read(self, length, offset):
        return self.svnfs.svnfs_read(self.rev, self.path, length, offset)

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

        rev = int(m.group(1))
        if rev > svn.fs.youngest_rev(self.svnfs.fs_ptr):
            raise_no_such_entry_error("Nonexistent (yet) revision {0}".format(rev))

        svn_path = m.group(2)

        if not self.svnfs.svnfs_file_exists(rev, svn_path):
            raise_no_such_entry_error("Path not found in {0} revision: {1}".format(rev, svn_path))

        self.svnfs_init(rev, svn_path)


class SvnFSSingleRevisionFile(SvnFSFileBase):
    @trace_exceptions
    def __init__(self, path, flags, *mode):
        super(SvnFSSingleRevisionFile, self).__init__(path, flags, *mode)

        if not self.svnfs.svnfs_file_exists(self.svnfs.rev, path):
            raise_no_such_entry_error("Path not found in {0} revision: {1}".format(self.svnfs.rev, path))

        self.svnfs_init(self.svnfs.rev, path)


class SvnFS(Fuse):
    def __init__(self, *args, **kw):
        Fuse.__init__(self, *args, **kw)

        self.repospath = None
        self.revision = None

        self.uid = None
        self.gid = None

        self.logfile = None
        self.send_sigstop = None
        self.cache_dir = None

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

    def init_repo(self):
        assert self.repospath is not None

        self.fs_ptr = svn.repos.svn_repos_fs(svn.repos.svn_repos_open(svn.core.svn_path_canonicalize(self.repospath)))

        # revision -> revision_root object
        self.roots = {}

        if self.revision != 'all':
            self.rev = svn.fs.youngest_rev(self.fs_ptr) if self.revision == 'head' else self.revision
            self.file_class = SvnFSSingleRevisionFile
        else:
            self.file_class = SvnFSAllRevisionsFile
        self.file_class.svnfs = self

        # revision -> time
        self.revision_creation_time_cache = {}

        self.files_cache = FilesCache(self.cache_dir)

    # TODO?
    #def access(self, path, mode):
    #    if not os.access("." + path, mode):
    #        return -EACCES

    def __revision_creation_time_impl(self, rev):
        date = svn.fs.revision_prop(self.fs_ptr, rev,
            svn.core.SVN_PROP_REVISION_DATE)
        return svn.core.secs_from_timestr(date)

    def __revision_creation_time(self, rev):
        return self.revision_creation_time_cache.setdefault(rev, self.__revision_creation_time_impl(rev))

    def svnfs_get_root(self, rev):
        return self.roots.setdefault(rev, svn.fs.revision_root(self.fs_ptr, rev))

    def svnfs_file_exists(self, rev, svn_path):
        kind = svn.fs.check_path(self.svnfs_get_root(rev), svn_path)
        return kind != svn.core.svn_node_none

    def svnfs_node_revision_id(self, rev, path):
        return svn.fs.unparse_id(svn.fs.node_id(self.svnfs_get_root(rev), path))

    def svnfs_getattr(self, rev, path):
        st = fuse.Stat()

        root = self.svnfs_get_root(rev)

        kind = svn.fs.check_path(root, path)
        if kind == svn.core.svn_node_none:
            e = OSError("Nothing found at {0}".format(path))
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
            st.st_mode = stat.S_IFDIR | 0o555
            st.st_size = 512
        else:
            st.st_mode = stat.S_IFREG | 0o444
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

        st.st_mode = stat.S_IFDIR | 0o555
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

        st.st_mode = stat.S_IFDIR | 0o555
        st.st_size = 512

        return st

    def getattr(self, path):
        if self.revision == 'all':
            if path == "/":
                return self.__getattr_root()

            m = revision_dir_re.match(path)
            if m:
                return self.__getattr_rev(self._get_rev(m.group(1)))

            m = file_re.match(path)
            if m:
                return self.svnfs_getattr(self._get_rev(m.group(1)), m.group(2))
        else:
            return self.svnfs_getattr(self.rev, path)

        e = OSError("Nothing found at {0}".format(path))
        e.errno = errno.ENOENT
        raise e

    def _get_rev(self, rev):
        if rev == 'head':
            return svn.fs.youngest_rev(self.fs_ptr)
        return int(rev)

    # TODO: support this
    @trace_exceptions
    def readlink(self, path):
        e = OSError("Not supported yet, readlink on {0}".format(path))
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

            m = revision_dir_re.match(path)
            if m:
                return self.__get_files_list_svn(self.svnfs_get_root(self._get_rev(m.group(1))), "/")

            m = file_re.match(path)
            if m:
                return self.__get_files_list_svn(self.svnfs_get_root(self._get_rev(m.group(1))), m.group(2))
        else:
            return self.__get_files_list_svn(self.svnfs_get_root(self.rev), path)

        e = OSError("Nothing found at {0}".format(path))
        e.errno = errno.ENOENT
        raise e

    @trace_exceptions
    def getdir(self, path):
        return map(lambda x: (x, 0), self.__get_files_list(path))

    @trace_exceptions
    def readdir(self, path, offset):
        # TODO: offset?
        if path == '/':
            yield fuse.Direntry('head')

        for f in  self.__get_files_list(path) + [".", ".."]:
            yield fuse.Direntry(f)

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

    @trace_exceptions
    def utime(self, path, times):
        return os.utime(path, times)

    def svnfs_read(self, rev, path, length, offset):
        node_revision_id = self.svnfs_node_revision_id(rev, path)

        cache_file = self.files_cache.get_file_path(node_revision_id)

        if not cache_file:
            # File not cached - get it and cache it
            src_stream = svn.fs.file_contents(self.svnfs_get_root(rev), path)
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

def main():
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
    svnfs.parser.add_option(mountopt="send_sigstop", dest="send_sigstop",
        action="store_true",
        help="send SIGSTOP signal when file system is initialized (useful with -f)")
    svnfs.parser.add_option(mountopt="cache_dir", dest="cache_dir", default=os.curdir, metavar="PATH-TO-CACHE",
        help="use file cache for retrieved Subversion objects [default: %default]")

    svnfs.parse(values=svnfs, errex=1)

    # Redirect output at early stage
    if svnfs.logfile is not None:
        svnfs.logfile = os.path.abspath(svnfs.logfile)
        redirect_output(svnfs.logfile)
        sys.stdout.write("Log opened at {0}\n".format(str(datetime.datetime.now())))
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

            if svnfs.cache_dir is None:
                svnfs.cache_dir = os.curdir
            svnfs.cache_dir = os.path.abspath(svnfs.cache_dir)

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

if __name__ == '__main__':
    main()

# vim: set ts=4 sw=4 et:
