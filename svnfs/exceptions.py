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

import sys
import errno
import functools
import traceback
import inspect


__all__ = [
    "ManagedOSError", "raise_read_only_error", "raise_no_such_entry_error",
    "trace_exceptions"]


class ManagedOSError(OSError):
    """Exception that should be handled by FUSE
    
    E.g. when client tries to write into read only file svnfs raises such
    exception and it should be correctly handled by FUSE"""


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


def trace_exceptions(function):
    """Decorator for FUSE methods for tracing unexpected exceptions"""

    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except ManagedOSError:
            # Skip exceptions about read only file system
            raise
        except:
            # TODO: use logging
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
