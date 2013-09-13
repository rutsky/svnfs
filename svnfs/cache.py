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
import shelve
import pickle
import shutil

from svnfs.utils.synch import RWLock


__all__ = ["FilesCache"]


def encode_node_revision_id(node_revision_id):
    """Encode node revision id string to correct file name"""
    return node_revision_id.encode("hex")


class FilesCache(object):
    # TODO: store files not in plain directory, but in equally distributed
    # tree.
    # TODO: touch opened files, to allow implementing external cache
    # cleaning.
    # TODO: maybe use beaker cache or other caching solution?

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

        self.cache_db_lock = RWLock()

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
