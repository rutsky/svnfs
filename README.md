svnfs
=====

FUSE-filesystem over Subversion repository.

svnfs provides virtual filesytem over Subversion tree for specific revision
or for all revisions.

Usage
-----

svnfs runs on GNU/Linux with Python 2.7 with Subversion and FUSE ctypes 
bindings.

    # Share all revisions under /mnt
    $ ./svnfs.py /var/lib/svn/somerepo /mnt -o cache_dir=/tmp/svnfs_cache

    # Now all repository revisions are available under /mnt
    $ tree /mnt
    /mnt
    ├── 1
    │   └── test.txt
    ├── 2
    │   └── test.txt
    ├── 3
    │   ├── a
    │   │   ├── b
    │   │   │   └── c
    │   │   └── b1
    │   │       └── c1
    │   └── test.txt
    ...
    # To unmount file system use fusermount:
    $ fusermount -u /mnt

Specific revision can be mounted by specifying "-o revision=REV" option.

Try "./svnfs.py -h" for more information about available options.

Limitations
-----------

svnfs requires access to Subversion repository raw files, which is not always
available.

Alternatives
------------

I haven't found any implementation that supports mounting of all revisions in 
same tree with effective caching of duplicate between revision files. But if
you need to mount only signle specific revision I found following 
alternatives (also they don't require direct access to raw repository files): 

1. Subversion's WebDAV

   Subversion provides remote access to repository tree through WebDAV protocol,
   so specific revision can be mounted to local directory by using for example 
   davfs.

2. FUSE-based implementation by John Madden: 
   <http://www.jmadden.eu/index.php/svnfs/>

   And it's forks:
   - <https://code.google.com/p/subversionfs/>
   - <https://github.com/akesterson/svnfs>

License
-------

svnfs is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Copyright (C) 2001  Jeff Epler  <jepler@unpythonic.dhs.org>

Copyright (C) 2005  Daniel Patterson  <danpat@danpat.net>

Copyright (C) 2013  Vladimir Rutsky  <rutsky.vladimir@gmail.com>
