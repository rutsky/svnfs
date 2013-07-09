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

import svn
import svn.fs
import svn.repos

# TODO: test simultaneous read of big file from many threads

test_repo = "test_repo"
svnfs_script = "../svnfs.py"
interactive_mnt = "mnt"

sys.path.append("..")
import svnfs


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

    result = subprocess.call(cmd)

    if result != 0:
        subprocess.call(["fuser", "-m", directory])  # Debug

    return result


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
        self.mount_thread = RunInThread(self.mnt,
            [svnfs_script, test_repo, self.mnt, "-f", "-o", "send_sigstop"],
            wait_sigstop=True)
        self.mount_thread.start()

        self.assertEqual(umount(self.mnt), 0)

        self.mount_thread.join()

        self.assertEqual(self.mount_thread.out, "")
        self.assertEqual(self.mount_thread.err, "")
        self.assertEqual(self.mount_thread.returncode, 0)

    def test_mount_rev1(self):
        self.mount_thread = RunInThread(self.mnt,
            [svnfs_script, test_repo, self.mnt, "-f", "-o", "send_sigstop,revision=1"],
            wait_sigstop=True)
        self.mount_thread.start()

        # TODO: invoking umount just after mounting leads to Device or resource busy error
        time.sleep(0.05)

        self.assertEqual(umount(self.mnt), 0)

        self.mount_thread.join()

        self.assertEqual(self.mount_thread.out, "")
        self.assertEqual(self.mount_thread.err, "")
        self.assertEqual(self.mount_thread.returncode, 0)


class RunInThread(threading.Thread):
    def __init__(self, mnt, run_args, *args, **kwargs):
        self.mnt = mnt
        self.wait_sigstop = kwargs.pop("wait_sigstop", False)

        if self.wait_sigstop:
            assert filter(lambda x: x.find("send_sigstop") >= 0, run_args), \
                "wait_sigstop must be used with send_sigstop SvnFS option"
            assert "-f" in run_args, \
                "wait_sigstop must be used with -f SvnFS option"

        super(RunInThread, self).__init__(*args, **kwargs)
        self.run_args = run_args
        assert len(self.run_args) > 0

        self.err = None
        self.out = None
        self.returncode = None

        # This variable tested and modified in different threads and I rely
        # on Python's GIL here.  I don't use locking primitives, because main
        # thread can lock them and be interrupted by signal, where it will try
        # to lock them again and deadlock will occur.
        self.ready = False

    def _sigchld_handler(self, signum, frame):
        try:
            signal.signal(signal.SIGCHLD, self.old_sigchld_handler)
            try:
                os.kill(self.process.pid, signal.SIGCONT)
            except OSError:
                # Process probably dead. It should be seen in
                # it's return code or output.
                pass
        finally:
            self.ready = True

    def run(self):
        try:
            self.process = subprocess.Popen(self.run_args,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except:
            # Set thread as ready to prevent deadlock
            self.ready = True
            raise

        if self.wait_sigstop:
            self.err, self.out = self.process.communicate()
            # ready.set() should be called from SIGCHLD handler
        else:
            self.ready = True
            self.err, self.out = self.process.communicate()

        self.returncode = self.process.returncode

    def start(self):
        if self.wait_sigstop:
            self.old_sigchld_handler = signal.signal(signal.SIGCHLD, self._sigchld_handler)

        super(RunInThread, self).start()

        while not self.ready:
            time.sleep(0.001)

        if self.wait_sigstop:
            # Restore handler one more time
            signal.signal(signal.SIGCHLD, self.old_sigchld_handler)

        # to be sure, that FS is up
        #os.stat(self.mnt) # causes FUSE failures: Software caused connection abort

        # TODO: invoking umount just after mounting leads to "Device or resource busy" error
        time.sleep(0.05)


class BaseTestContent(unittest.TestCase):
    def __init__(self, *args, **kwargs):
        self.svnfs_options = kwargs.pop("svnfs_options", "")
        super(BaseTestContent, self).__init__(*args, **kwargs)

    def setUp(self):
        self.mnt = temp_mount_dir()

        options = "send_sigstop"
        if self.svnfs_options:
            options += "," + self.svnfs_options
        self.mount_thread = RunInThread(self.mnt,
            [svnfs_script, test_repo, self.mnt, "-o", options, "-f"],
                                        wait_sigstop=True)
        self.mount_thread.start()

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
            with open(os.path.join(self.mnt, "test"), "w") as _:
                pass

        ex = cm.exception
        self.assertTrue(ex.strerror.find("Read-only file system") >= 0,
                        msg="Unexpected exception text: '{0}'".format(ex.strerror))
        self.assertEqual(ex.errno, 30)

    def test_read_only_files(self):
        with self.assertRaises(IOError) as cm:
            with open(os.path.join(self.mnt, "2", "newfile"), "w") as _:
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
            for _ in xrange(10000):
                os.stat(file_path)
                os.stat(file_path)
                os.stat(file_path)

        processes = [multiprocessing.Process(target=call_getattr, args=(file_path,))
                     for _ in xrange(20)]

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

    def test_file_stat(self):
        file_path = os.path.join(self.mnt, "test.txt")

        stat = os.stat(file_path)

        self.assertNotEqual(stat.st_mtime, 0)
        self.assertNotEqual(stat.st_atime, 0)
        self.assertNotEqual(stat.st_ctime, 0)


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


class TestSVN(unittest.TestCase):
    def setUp(self):
        self.fs_ptr = svn.repos.svn_repos_fs(svn.repos.svn_repos_open(svn.core.svn_path_canonicalize(test_repo)))

    def test_revision_id(self):
        def node_id(rev, path):
            root = svn.fs.revision_root(self.fs_ptr, rev)
            node_id = svn.fs.node_id(root, path)
            return svn.fs.unparse_id(node_id)

        self.assertTrue(isinstance(node_id(1, "/test.txt"), basestring))
        self.assertEqual(node_id(1, "/test.txt"), node_id(1, "/test.txt"))
        self.assertEqual(node_id(2, "/test.txt"), node_id(3, "/test.txt"))
        self.assertNotEqual(node_id(2, "/test.txt"), node_id(2, "/"))
        self.assertNotEqual(node_id(2, "/test.txt"), node_id(4, "/a/test.txt"))
        self.assertNotEqual(node_id(2, "/test.txt"), node_id(5, "/file"))


class TestRevisionEncoding(unittest.TestCase):
    def test_main(self):
        node_revision_id = '0-1.0.r2/45'
        encoded = svnfs.encode_node_revision_id(node_revision_id)
        self.assertFalse(encoded.find("/") >= 0)
        self.assertFalse(encoded.find("..") >= 0)


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
