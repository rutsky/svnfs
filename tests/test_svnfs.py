#!/usr/bin/env python

import os
import sys
import tempfile
import subprocess

# TODO: check Python version and import unittest2 module, if version is less
# than 2.7
import unittest
import argparse

test_repo = "test_repo"
svnfs_script = "../svnfs.py"
interactive_mnt = "mnt"

def is_mounted(directory):
    with open("/etc/mtab") as f:
        return f.read().find(" " + os.path.abspath(directory) + " ") >= 0

def umount(directory, lazy=False):
    cmd = ["fusermount", "-u"]
    if lazy:
        cmd.append("-z")
    cmd.append(directory)
    return subprocess.call(cmd)

def umount_safe(directory):
    if is_mounted(directory):
        umount(directory)
        if is_mounted(directory):
            umount(directory, lazy=True)

class TestRun(unittest.TestCase):
    def test_wo_args(self):
        # Run without arguments - error and help message
        p = subprocess.Popen([svnfs_script],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        self.assertEqual(out, "")
        self.assertTrue(err.find("Error") >= 0)
    
class TestMount(unittest.TestCase):
    def setUp(self):
        self.mnt = tempfile.mkdtemp(prefix="mnt_")
    
    def tearDown(self):
        umount_safe(self.mnt)
        os.rmdir(self.mnt)
        
    def test_mount(self):
        p = subprocess.Popen([svnfs_script, test_repo, self.mnt],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(p.returncode, 0)
        
        self.assertEqual(umount(self.mnt), 0)

class TestContent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mnt = tempfile.mkdtemp(prefix="mnt_")
        
        r = subprocess.call([svnfs_script, test_repo, cls.mnt])
        assert r == 0
    
    @classmethod
    def tearDownClass(cls):
        umount_safe(cls.mnt)
        os.rmdir(cls.mnt)
    
    def test_content(self):
        self.assertTrue(os.path.isdir(os.path.join(self.mnt, "1")))
        self.assertTrue(os.path.isfile(os.path.join(self.mnt, "1", "test.txt")))
        with open(os.path.join(self.mnt, "1", "test.txt"), "r") as f:
            self.assertEqual(f.read().strip(), "Test file")
        
        self.assertTrue(os.path.isdir(os.path.join(self.mnt, "2")))
        self.assertTrue(os.path.isfile(os.path.join(self.mnt, "2", "test.txt")))
        with open(os.path.join(self.mnt, "2", "test.txt"), "r") as f:
            self.assertEqual(f.read().strip(), "First change")
    
    def test_read_only_revs(self):
        with self.assertRaises(IOError) as cm:
            open(os.path.join(self.mnt, "test"), "w")
        
        ex = cm.exception
        self.assertTrue(ex.strerror.find("Read-only file system") >= 0, 
                        msg="Unexpected exception text: '{0}'".format(ex.strerror))
        self.assertEqual(ex.errno, 30)
    
    def test_read_only_files(self):
        with self.assertRaises(IOError) as cm:
            open(os.path.join(self.mnt, "2", "newfile"), "w")
        
        ex = cm.exception
        self.assertTrue(ex.strerror.find("Read-only file system") >= 0, 
                        msg="Unexpected exception text: '{0}'".format(ex.strerror))
        self.assertEqual(ex.errno, 30)
        
    # TODO: test not existing revision
    # TODO: test single revision, and head revision mounting
    # TODO: always check that output doesn't contains exceptions
        
def run_tests():
    if not os.path.isdir(test_repo):
        sys.stderr.write("Error: Test repository not found.\n"
            "Create test repository first using ./create_test_repo.sh script.\n")
        sys.exit(1)

    unittest.main()

def run_mount():
    """Mount test repository for interactive testing"""
    
    if not os.path.isdir(interactive_mnt):
        os.mkdir(interactive_mnt)
    
    if is_mounted(interactive_mnt):
        umount_safe(interactive_mnt)
    
    r = subprocess.call([svnfs_script, test_repo, interactive_mnt])
    assert r == 0
    
    print(("Test repository mounted under '{mnt}'.\n"
           "To unmount run:\n"
           "  fusermount -u {mnt}").format(mnt=interactive_mnt))

def main():
    parser = argparse.ArgumentParser(description='Test runner for SVNFS')
    parser.add_argument('--run-mount', action='store_true',
                        help='Mount test repository for interactive testing')
    
    args = parser.parse_args()
    if args.run_mount:
        run_mount()
    else:
        run_tests()

if __name__ == '__main__':
    main()
