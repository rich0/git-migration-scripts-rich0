#!/bin/bash

proc_count=$(grep -c MHz /proc/cpuinfo)
[ ${proc_count} -eq 0 ] && proc_count=1
root="$(pwd)"
mkdir -p git
rm -rf git/* git/.git
set -f
mkdir -p git
cd git
git_root="$(pwd)"
git init --bare
git config core.logAllRefUpdates false
git config prune.expire now
mkdir -p objects/info

update_alternates() {
  local alternates="$(readlink -f objects/info)/alternates"
  cd "${root}"
  while read l; do
    l=$(readlink -f "$l")
    [ -e "$l/cvs2svn-tmp/git-dump.dat" ] || { echo "ignoring nonexistant alternates source $l" >&2; continue; }
    echo "$l/git/objects" >> "${alternates}"
    echo "$l"
  done
  echo "starting history linearizing/rewriting" >&2
}

standalone_mode() {
  echo "loading all commits" >&2
  find ../final/ -maxdepth 1 -mindepth 1 -printf '../final/%P/\n' | \
    xargs -n1 readlink -f | update_alternates
}

if [ "$1" == --fast ]; then
  command=update_alternates
else
  command=standalone_mode
  echo "loading all commits in parallel to their generation..." >&2
fi

# Roughly; since alternates are updated as we go- and since rewrite-commit-dump
# doesn't actually output anything till it's linearized the history, we have
# to delay fast-import's startup until we know we have data (meaning linearize
# has finished- thus the alternates are all in place).
# Bit tricky, but the gains have been worth it.
time {
  ${command} | \
  "${root}/rewrite-commit-dump.py" | \
  ( read line; { echo "$line"; cat; } | \
      tee ../export-stream-rewritten |\
      time git fast-import
  )
} 2>&1 > >(tee git-creation.log)
ret=$?
[ $ret -eq 0 ] || { echo "none zero exit... the hell? $ret"; exit 1; }

echo "recomposed; repacking and breaking alternate linkage..."
# Localize the content we actual use out of the alternates...
time git repack -Adf --window=100 --depth=100
# Wipe the alternates.
rm objects/info/alternates || { echo "no alternates means no sources..."; exit 2; }
echo "doing cleanup..."
time git prune
echo "doing basic sanity check"
time git log -p refs/heads/master > /dev/null || echo "non zero exit code from git log run..."
echo "Done"
