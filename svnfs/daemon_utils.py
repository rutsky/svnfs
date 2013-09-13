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


__all__ = ["redirect_output"]


def redirect_output(output_file_name):
    """Redirect stdout and stderr to log file"""

    # Flush output before setting redirection
    sys.stdout.flush()
    sys.stderr.flush()

    # Redirect
    log_fd = os.open(output_file_name, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
