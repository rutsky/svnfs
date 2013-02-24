#!/usr/bin/env python

import os
import sys
import unittest
import tempfile
import subprocess

test_repo = "test_repo"
svnfs_script = "../svnfs.py"

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

if __name__ == '__main__':
    if not os.path.isdir(test_repo):
        sys.stderr.write("Error: Test repository not found.\n"
            "Create test repository first using ./create_test_repo.sh script.\n")
        sys.exit(1)

    unittest.main()
