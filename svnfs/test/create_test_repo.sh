#!/bin/bash

set -e

# TODO: create repository using libsvn API. Current implementation is slow 
# (on Gentto) and buggy (svn ls, svn log don't work).

TESTS=`pwd`
REPO=test_repo
WC=test_wc

export SVN_SSH=$TESTS/fake_ssh.sh

# Remove old repository if exists
rm -rf $REPO
rm -rf $WC

svnadmin create $REPO

# Enable pre-revprop-change to allow changing commit time
cp $REPO/hooks/pre-revprop-change.tmpl $REPO/hooks/pre-revprop-change
cat <<EOF > $REPO/hooks/pre-revprop-change
#!/bin/bash

REPOS="$1"
REV="$2"
USER="$3"
PROPNAME="$4"
ACTION="$5"

if [ "$ACTION" = "M" -a "$PROPNAME" = "svn:log" ]; then exit 0; fi

exit 0 # Allow any property change
EOF
chmod +x $REPO/hooks/pre-revprop-change

svn co svn+ssh://$REPO/ $WC

pushd $WC > /dev/null

echo "Test file" > test.txt
svn add test.txt
svn ci -m "Add test.txt"
svn propset svn:date --revprop -r 1 2013-00-00T00:00:00.000000Z

echo "First change" > test.txt
svn ci test.txt -m "First change"
svn propset svn:date --revprop -r 2 2013-00-01T00:00:00.000000Z

mkdir -p a/b/c
mkdir -p a/b1/c1
svn add a
svn ci a -m "Add empty directories"

svn copy test.txt a/test.txt
svn copy test.txt a/b/test.txt
svn copy test.txt a/b/test2.txt
svn ci a -m"Copy test.txt"

echo "More files" > file
svn add file
svn ci file -m "Add more files"

popd > /dev/null
