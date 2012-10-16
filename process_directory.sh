#!/bin/bash
command='
  sed -re "s/^\(paludis (0.1.*)\)$/Package-manager: Paludis \1/" \
       -e "s/^\([Pp]ortage version: (.*)\)$/Package-manager: Portage \1/"'
f() {
  set -x
  mkdir -p "${output}"/{git{,-work},cvs-repo/gentoo-x86/Attic}
  ln -s "${cvsroot}" "${output}/cvs-repo/CVSROOT"
  ln -s "${root}/gentoo-x86/$1" "${output}/cvs-repo/gentoo-x86/$1"
  #ln -s "${root}/gentoo-x86/Attic" "${output}/cvs-repo/gentoo-x86/Attic"
  ln -s "$(pwd)/config" "${output}/config"
  ln -s "$(pwd)/gentoo_mailmap.py" "${output}/gentoo_mailmap.py"
  # Note- this must be canonical path, else it screws up our $Header rewriting.
  cd "$(readlink -f "${output}" )"
  export PYTHONPATH="${output}${PYTHONPATH:+:${PYTHONPATH}}"
  time cvs2git --options config -vv
  cd git
  git init --bare
  # Note we're only pull in blob data here; this intentional- we need to
  # interlace the commit objects together, these git object pools will be
  # be used as alternates for the final repo combination.
  "${base}/rewrite-blob-data.py" ../cvs2svn-tmp/git-blob.dat | \
    git fast-import --export-marks=../cvs2svn-tmp/git-blob.idx
  rm -rf "${final}"
  cd "$root"
  mv "$output" "${final}"
  set +x
}

[ $# -lt 1 ] && { echo "need an argument..."; exit 1; }

base="$(pwd)"
root="$(pwd)/cvs-repo"
cvsroot="${root}/CVSROOT"
repo="${root}/gentoo-x86"
output="$(pwd)/output/${1%,v}"
final="$(pwd)/final/$1"
mkdir -p "$(dirname "${final}")"

rm -rf "${output}"
mkdir -p "${output}"
echo "processing ${1%,v}" >&2
time f "$1" &> "${output}/"log || { echo "failed $1"; exit 1; }
echo "processed  $1" >&2

# Echo the completed pathway if we're in fast mode; this allows
# create-git.sh to get a head start on this repo once we've finished.
[ $# -eq 2 ] && echo "$(readlink -f "$final")" >&$2
