#!/bin/bash

set -e

TESTS=`pwd`
REPO=test_repo
WC=test_wc

export SVN_SSH=$TESTS/fake_ssh.sh

# Remove old repository if exists
rm -rf $REPO
rm -rf $WC

svnadmin create $REPO

svn co svn+ssh://$REPO/ $WC

pushd $WC > /dev/null

echo "Test file" > test.txt
svn add test.txt
svn ci -m "Add test.txt"

echo "First change" > test.txt
svn ci test.txt -m "First change"

popd > /dev/null
