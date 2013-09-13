import unittest
import subprocess


class TestRun(unittest.TestCase):
    def test_wo_args(self):
        # Run without arguments - error and help message
        p = subprocess.Popen([svnfs_script],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        self.assertEqual(out, "")
        self.assertTrue(err.find("Error") >= 0)
        self.assertNotEqual(p.returncode, 0)


