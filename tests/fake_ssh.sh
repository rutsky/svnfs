#!/bin/bash

# This is fake SSH client for commiting in local Subversion repository.

set -e

# $0 host svnserve -t

pushd `dirname $0` > /dev/null
SCRIPTPATH=`pwd -P`
popd > /dev/null

svnserve -t -r $SCRIPTPATH/$1
