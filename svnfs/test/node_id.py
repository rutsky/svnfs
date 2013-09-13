#!/usr/bin/env python

import svn.fs
import svn.repos

repospath = "test_repo"
fs_ptr = svn.repos.svn_repos_fs(svn.repos.svn_repos_open(svn.core.svn_path_canonicalize(repospath)))

def node_id(rev, path):
    root = svn.fs.revision_root(fs_ptr, rev)
    node_id = svn.fs.node_id(root, path)
    return svn.fs.unparse_id(node_id)

def print_node_id(rev, path):
   print("r{0} {1}: {2}".format(rev, path, node_id(rev, path)))

print_node_id(0, "/")
print_node_id(1, "/")
print_node_id(1, "/test.txt")
print_node_id(2, "/")
print_node_id(2, "/test.txt")
print_node_id(4, "/test.txt")
print_node_id(4, "/a/test.txt")
print_node_id(4, "/a/b/test.txt")
print_node_id(4, "/a/b/test2.txt")
