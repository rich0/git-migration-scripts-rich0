#!/bin/bash

proc_count=$(grep -c MHz /proc/cpuinfo)
[ $proc_count -eq 0 ] && proc_count=1

rm -rf git/* git/.git final/*
mkdir git -p
./create-mailmap.py userinfo.xml > gentoo_mailmap.py || { echo "failed to create mailmap."; exit 1; }
# Prioritize the larger categories first; they typically will have
# the most revs, thus start them first.
f() {
  time { \
    find cvs-repo/gentoo-x86 -maxdepth 1 -mindepth 1 -printf '%P\n' | \
    xargs -n1 -I{} --  du -cs "cvs-repo/gentoo-x86/{}" | grep -v 'total$' | \
    sort -gr | awk '{print $2;}' | xargs -n1 basename | \
    xargs -n1 -P${proc_count} -I{} ./process_directory.sh "{}" $1
  }
}
fast=false
if [ "$1" == --fast ]; then
  f 300 300> >(time ./create-git.sh --fast)
else
  f && ./create-git.sh
fi
