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
    xargs -n1 readlink -f | tee >(sed -e 's:$:/git/objects:' > objects/info/alternates) ) )
for x in "${targets[@]}"; do
  rev=$(git --git-dir $x/git rev-list -1 master 2> /dev/null)
  [ -z "$rev" ] && { echo "no content: $x"; continue; }
  x="refs/heads/source/$(basename $x)"
  git update-ref "$x" $rev
done

echo "linearizing history, and rewriting messages..."

time (
  git fast-export --progress=1000 --all --reverse --date-order --no-data | \
    tee ../export-stream-raw | \
    "${root}/rewrite-commit-dump.py" | \
    tee ../export-stream-rewritten | \
    git fast-import
) 2>&1 | tee git-creation.log

echo "recomposed; repacking and breaking alternate linkage..."
# Wipe the strong refs to the other repos...
git ls-remote . refs/heads/source/'*' | awk '{print $2;}' | xargs -n1 git update-ref -d
# Localize the content...
time git repack -Adf --window=100 --depth=100
# Wipe the alternates.
rm objects/info/alternates
echo "doing cleanup..."
time git prune
echo "doing basic sanity check"
time git log -p refs/heads/master > /dev/null || echo "non zero exit code from git log run..."
echo "Done"
