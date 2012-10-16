#!/bin/bash

proc_count=$(grep -c MHz /proc/cpuinfo)
[ ${proc_count} -eq 0 ] && proc_count=1
root="$(pwd)"
mkdir -p git
rm -rf git/* git/.git
set -f
mkdir -p git
cd git
git init --bare
git config core.logAllRefUpdates false
git config prune.expire now
mkdir -p objects/info
targets=( $(find ../final/ -maxdepth 1 -mindepth 1 -printf '../final/%P/\n' | \
  xargs -n1 readlink -f | \
    while read l; do
      [ -e "$l/cvs2svn-tmp/git-dump.dat" ] || continue;
      echo "$l/git/objects" >> objects/info/alternates
      echo "$l"
    done
  )
)

echo "loading all commits, linearizing, and rewriting history..."
time (
  "${root}/rewrite-commit-dump.py" "${targets[@]}" | \
    tee ../export-stream-rewritten | \
    git fast-import
) 2>&1 | tee git-creation.log

echo "recomposed; repacking and breaking alternate linkage..."
# Localize the content we actual use out of the alternates...
time git repack -Adf --window=100 --depth=100
# Wipe the alternates.
rm objects/info/alternates
echo "doing cleanup..."
time git prune
echo "doing basic sanity check"
time git log -p refs/heads/master > /dev/null || echo "non zero exit code from git log run..."
echo "Done"
