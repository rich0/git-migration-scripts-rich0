#!/bin/bash

f() {
  set -x
  mkdir -p "${output}"/{git,cvs-repo/gentoo-x86/Attic}
  ln -s "${cvsroot}" "${output}/cvs-repo/CVSROOT"
  ln -s "${root}/gentoo-x86/$1" "${output}/cvs-repo/gentoo-x86/$1"
  #ln -s "${root}/gentoo-x86/Attic" "${output}/cvs-repo/gentoo-x86/Attic"
  ln -s "${base}/config" "${output}/config"
  ln -s "${base}/gentoo_mailmap.py" "${output}/gentoo_mailmap.py"
  # Note- this must be canonical path, else it screws up our $Header rewriting.
  pushd "$(readlink -f "${output}" )"
  export PYTHONPATH="${output}${PYTHONPATH:+:${PYTHONPATH}}"
  time cvs2git --options config -v
  cd git
  git init --bare
  # Note we're only pull in blob data here; this intentional- we need to
  # interlace the commit objects together, these git object pools will be
  # be used as alternates for the final repo combination.
  "${base}/rewrite-git-blob.py" \
    ../cvs2svn-tmp/git-blob.dat "${output}/cvs-repo" | \
    tee ../cvs2svn-tmp/rewritten-blob.dat | \
    git fast-import --export-marks=../cvs2svn-tmp/git-blob.idx
  popd
  rm -rf "${final}"
  mv "$output" "${final}"
  set +x
}

[ $# -lt 1 ] && { echo "need an argument..."; exit 1; }

cd "$(readlink -f "$(pwd)")"
base="$(pwd)"
root="${base}/cvs-repo"
cvsroot="${root}/CVSROOT"
repo="${root}/gentoo-x86"
output="${base}/output/${1%,v}"
final="${base}/final/$1"
mkdir -p "$(dirname "${final}")"

rm -rf "${output}"
mkdir -p "${output}"
echo "processing ${1%,v}" >&2
time f "$1" &> "${output}/"log || { echo "failed $1"; exit 1; }
echo "processed  $1" >&2

# Echo the completed pathway if we're in fast mode; this allows
# create-git.sh to get a head start on this repo once we've finished.
[ $# -eq 2 ] && echo "$(readlink -f "$final")" >&$2
