#!/usr/bin/python
import functools
import os
import re
import sys

# $Header: /usr/local/ssd/gentoo-x86/output/.*/.*/cvs-repo/
# $Header: /usr/local/ssd/gentoo-x86/output/app-accessibility/cvs-repo/gentoo-x86/app-accessibility/SphinxTrain/ChangeLog,v
base = os.path.dirname(os.path.abspath(__file__))
mangler = functools.partial(
  re.compile(r"\$Header: %s/output/.*/cvs-repo/" % base).sub,
  r"$Header: /var/cvsroot/")

write = sys.stdout.write
source = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
for x in source:
  write(mangler(x))
