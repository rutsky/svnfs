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
import sys
import textwrap
import datetime
import grp
import pwd

import fuse
import svn

from svnfs.fuse_client import SvnFS
from svnfs.daemon_utils import redirect_output
from svnfs.svn_pools import SvnPoolStorage


__all__ = ["run"]


def run():
    usage = textwrap.dedent("""\
        Usage: %prog svn_repository_dir mountpoint [options]
            or
               %prog mountpoint -o svnrepo=SVN-REPO-DIR [options]
        """)
    svnfs = SvnFS(version="%prog " + fuse.__version__, dash_s_do='setsingle', usage=usage)

    svnfs.parser.add_option(mountopt="svnrepo", dest="repospath", metavar="SVN-REPO-DIR",
        help="path to subversion repository")
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
    # TODO: use logging
    if svnfs.logfile is not None:
        svnfs.logfile = os.path.abspath(svnfs.logfile)
        redirect_output(svnfs.logfile)
        sys.stdout.write("Log opened at {0}\n".format(str(datetime.datetime.now())))
        sys.stdout.flush()

    svnfs.pool_storage = SvnPoolStorage()

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
