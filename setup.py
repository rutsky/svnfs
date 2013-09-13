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


# Use setuptools for `python setup.py develop`
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(
    name='svnfs',
    version='0.1',
    description='FUSE-filesystem over Subversion repository',
    author='Vladimir Rutsky',
    author_email='rutsky.vladimir@gmail.com',
    license='GNU GPLv3+',
    # TODO: should use reStructured text according to
    # <http://docs.python.org/2/distutils/setupscript.html#meta-data>
    long_description=open('README.md').read(),
    url='https://github.com/rutsky/svnfs/',  # TODO
    
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: No Input/Output (Daemon)',
        'Environment :: Console',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: POSIX :: Linux'
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: System :: Filesystems',
        'Topic :: Software Development :: Version Control',
        ],
    # TODO: specify platforms
    #platform='any',

    packages=[
        'svnfs',
        'svnfs.test',
        'svnfs.utils',
        'svnfs.scripts',
        ],
    scripts=['scripts/svnfs'],

    install_requires=[
        'fuse-python == 0.2',
        # TODO: subversion python bindings
        'repoze.lru',
        ],
)
