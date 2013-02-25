#!/usr/bin/env python

import os
import sys
import time
import shutil
import signal
import tempfile
import threading
import subprocess
import multiprocessing

# TODO: check Python version and import unittest2 module, if version is less
# than 2.7
import unittest
import argparse


# TODO: always check that output doesn't contains exceptions
# TODO: test simultaneous read of big file from many threads

test_repo = "test_repo"
svnfs_script = "../svnfs.py"
interactive_mnt = "mnt"


def is_mounted(directory):
    with open("/etc/mtab") as f:
        mtab = f.read()
    return mtab.find(" " + os.path.abspath(directory) + " ") >= 0


def wait_mount(directory):
    while True:
        if is_mounted(directory):
            return
        else:
            time.sleep(0.001)


def umount(directory, lazy=False):
    assert is_mounted(directory)
    
    cmd = ["fusermount", "-u"]
    if lazy:
        cmd.append("-z")
    cmd.append(directory)
    return subprocess.call(cmd)


def umount_safe(directory):
    if is_mounted(directory):
        umount(directory)
        if is_mounted(directory):
            subprocess.call(["fuser", "-m", directory])  # Debug
            umount(directory, lazy=True)
    
    assert not is_mounted(directory)


def temp_mount_dir():
    return os.path.abspath(tempfile.mkdtemp(prefix="mnt_", dir=os.curdir))


class TestRun(unittest.TestCase):
    def test_wo_args(self):
        # Run without arguments - error and help message
        p = subprocess.Popen([svnfs_script],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        self.assertEqual(out, "")
        self.assertTrue(err.find("Error") >= 0)
        self.assertNotEqual(p.returncode, 0)


class TestMount(unittest.TestCase):
    def setUp(self):
        self.mnt = temp_mount_dir()
    
    def tearDown(self):
        umount_safe(self.mnt)
        shutil.rmtree(self.mnt)
        
    def test_mount_all(self):
        p = subprocess.Popen([svnfs_script, test_repo, self.mnt],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(p.returncode, 0)
        
        time.sleep(0.001) # TODO: wait for FS
        
        self.assertEqual(umount(self.mnt), 0)
    
    def test_mount_rev1(self):
        p = subprocess.Popen([svnfs_script, test_repo, self.mnt,
                              "-o", "revision=1"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        
        self.assertEqual(out, "")
        self.assertEqual(err, "")
        self.assertEqual(p.returncode, 0)

        time.sleep(0.001) # TODO: wait for FS
        
        self.assertEqual(umount(self.mnt), 0)


class RunInThread(threading.Thread):
    def __init__(self, run_args, *args, **kwargs):
        self.wait_sigstop = kwargs.pop("wait_sigstop", False)
        
        super(RunInThread, self).__init__(*args, **kwargs)
        self.run_args = run_args
        assert len(self.run_args) > 0
        
        self.err = None
        self.out = None
        
        self.ready = threading.Event()
        
        if self.wait_sigstop:
            self.old_sigchld_handler = signal.signal(signal.SIGCHLD, self._sigchld_handler)
        
    def _sigchld_handler(self, signum, frame):
        signal.signal(signal.SIGCHLD, self.old_sigchld_handler)
        os.kill(self.process.pid, signal.SIGCONT)
        self.ready.set()
    
    def run(self):
        self.process = subprocess.Popen(self.run_args,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if self.wait_sigstop:
            self.err, self.out = self.process.communicate()
            # ready.set() should be called from SIGCHLD handler
        else:
            self.ready.set()
            self.err, self.out = self.process.communicate()


class BaseTestContent(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        self.svnfs_options = kwargs.pop("svnfs_options", "")
        super(BaseTestContent, self).__init__(*args, **kwargs)
    
    def setUp(self):
        self.mnt = temp_mount_dir()
        
        options = "send_sigstop"
        if self.svnfs_options:
            options += "," + self.svnfs_options
        self.mount_thread = RunInThread([svnfs_script, test_repo, self.mnt, 
                                         "-o", options, "-f"],
                                        wait_sigstop=True)
        self.mount_thread.start()
        while not self.mount_thread.ready.wait(0.001):
            pass
    
    def tearDown(self):
        umount_safe(self.mnt)
        self.mount_thread.join()
        shutil.rmtree(self.mnt)
        
        self.assertEqual(self.mount_thread.err, "")
        self.assertEqual(self.mount_thread.out, "")
        self.assertEqual(self.mount_thread.process.returncode, 0)


class BaseTestAllContent(BaseTestContent):
    def __init__(self, *args, **kwargs):
        super(BaseTestAllContent, self).__init__(*args, **kwargs)


class BaseTestRev1Content(BaseTestContent):
    def __init__(self, *args, **kwargs):
        super(BaseTestRev1Content, self).__init__(*args, 
                                                 svnfs_options="revision=1", 
                                                 **kwargs)


class BaseTestRev2Content(BaseTestContent):
    def __init__(self, *args, **kwargs):
        super(BaseTestRev2Content, self).__init__(*args, 
                                                 svnfs_options="revision=2", 
                                                 **kwargs)

class TestAllContent(BaseTestAllContent):
    def test_content(self):
        self.assertTrue(os.path.isdir(os.path.join(self.mnt, "1")))
        self.assertTrue(os.path.isfile(os.path.join(self.mnt, "1", "test.txt")))
        with open(os.path.join(self.mnt, "1", "test.txt"), "r") as f:
            self.assertEqual(f.read(), "Test file\n")
        
        self.assertTrue(os.path.isdir(os.path.join(self.mnt, "2")))
        self.assertTrue(os.path.isfile(os.path.join(self.mnt, "2", "test.txt")))
        with open(os.path.join(self.mnt, "2", "test.txt"), "r") as f:
            self.assertEqual(f.read(), "First change\n")
    
    def test_read_only_revs(self):
        with self.assertRaises(IOError) as cm:
            with open(os.path.join(self.mnt, "test"), "w") as f:
                pass
        
        ex = cm.exception
        self.assertTrue(ex.strerror.find("Read-only file system") >= 0, 
                        msg="Unexpected exception text: '{0}'".format(ex.strerror))
        self.assertEqual(ex.errno, 30)
    
    def test_read_only_files(self):
        with self.assertRaises(IOError) as cm:
            with open(os.path.join(self.mnt, "2", "newfile"), "w") as f:
                pass
        
        ex = cm.exception
        self.assertTrue(ex.strerror.find("Read-only file system") >= 0, 
                        msg="Unexpected exception text: '{0}'".format(ex.strerror))
        self.assertEqual(ex.errno, 30)
        
    def test_file_stat(self):
        file_path = os.path.join(self.mnt, "2", "test.txt")
        
        stat = os.stat(file_path)
        
        self.assertNotEqual(stat.st_mtime, 0)
        self.assertNotEqual(stat.st_atime, 0)
        self.assertNotEqual(stat.st_ctime, 0)
        
        self.assertEqual(stat.st_size, len("First change\n"))
        
    def test_concurrent_getattr(self):
        file_path = os.path.join(self.mnt, "2", "test.txt")
        
        # Check if stat works
        stat = os.stat(file_path)
        self.assertEqual(stat.st_size, len("First change\n"))
        
        def call_getattr(file_path):
            for i in xrange(10000):
                os.stat(file_path)
                os.stat(file_path)
                os.stat(file_path)
        
        processes = [multiprocessing.Process(target=call_getattr, args=(file_path,))
                     for i in xrange(20)]
        
        for p in processes:
            p.start()
        
        for p in processes:
            p.join()

    # TODO: test not existing revision
    # TODO: test single revision, and head revision mounting


class TestRev1Content(BaseTestRev1Content):
    def test_content(self):
        self.assertTrue(os.path.isfile(os.path.join(self.mnt, "test.txt")))
        with open(os.path.join(self.mnt, "test.txt"), "r") as f:
            self.assertEqual(f.read(), "Test file\n")
        
        self.assertFalse(os.path.isdir(os.path.join(self.mnt, "2")))


class TestRev2Content(BaseTestRev2Content):
    def test_content(self):
        self.assertTrue(os.path.isfile(os.path.join(self.mnt, "test.txt")))
        with open(os.path.join(self.mnt, "test.txt"), "r") as f:
            self.assertEqual(f.read(), "First change\n")
        
        self.assertFalse(os.path.isdir(os.path.join(self.mnt, "2")))


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
