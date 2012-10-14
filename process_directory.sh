#!/bin/bash
f() {
  set -x
  mkdir -p "${output}"/{git,cvs-repo/gentoo-x86/Attic}
  ln -s "${cvsroot}" "${output}/cvs-repo/CVSROOT"
  ln -s "${root}/gentoo-x86/$1" "${output}/cvs-repo/gentoo-x86/$1"
  #ln -s "${root}/gentoo-x86/Attic" "${output}/cvs-repo/gentoo-x86/Attic"
  ln -s "$(pwd)/config" "${output}/config"
  cd "${output}"
  time cvs2git --options config -vv
  cd git
  git init --bare
  cat ../cvs2svn-tmp/git-{blob,dump}.dat | git fast-import
  rm -rf "${final}"
  cd "$root"
  mv "$output" "${final}"
  git --git-dir "${final}/git" log --pretty=tformat:"%at %H" > "${final}/git-hashes"
  set +x
}

[ $# -ne 1 ] && { echo "need an argument..."; exit 1; }

root="$(pwd)/cvs-repo"
cvsroot="${root}/CVSROOT"
repo="${root}/gentoo-x86"
output="$(pwd)/output/${1%,v}"
final="$(pwd)/final/$1"
mkdir -p "$(dirname "${final}")"

rm -rf "${output}"
mkdir -p "${output}"
echo "processing ${1%,v} ${1}"
time f "$1" &> "${output}/"log || { echo "failed $1"; exit 1; }
echo "processed  $1"
