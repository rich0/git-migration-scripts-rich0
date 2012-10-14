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
  # Note- this must be canonical path, else it screws up our $Header rewriting.
  cd "$(readlink -f "${output}" )"
  time cvs2git --options config -vv
  cd git
  git init --bare
  { "${base}/rewrite-blob-data.py" ../cvs2svn-tmp/git-blob.dat;
    cat ../cvs2svn-tmp/git-dump.dat;
  } | git fast-import
  rm -rf "${final}" git-work
  cd "$root"
  mv "$output" "${final}"
  set +x
}

[ $# -ne 1 ] && { echo "need an argument..."; exit 1; }

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
