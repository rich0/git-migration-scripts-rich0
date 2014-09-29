#!/usr/bin/python
import contextlib
import collections
import functools
import itertools
import mmap
import multiprocessing
import operator
import os
import re
import subprocess
import sys

@contextlib.contextmanager
def mmap_open(path):
  handle = fd = None
  try:
    fd = os.open(path, os.O_RDONLY)
    handle = mmap.mmap(fd, os.fstat(fd).st_size, mmap.MAP_SHARED, mmap.PROT_READ)
    os.close(fd)
    fd = None
    yield handle
  finally:
    if fd:
      os.close(fd)
    if handle:
      handle.close()

def readline_iterate(handle):
  line = handle.readline()
  while line:
    yield line
    line = handle.readline()

mangler = []
mangler.append(functools.partial(
  re.compile(r"^\(paludis (0.1.*)\)$", re.M|re.I).sub,
    r"Package-Manager: paludis-\1/"))
# Special case not covered by the main portage mangler.
mangler.append(functools.partial(
  re.compile('r^\(Portage (2\.1\.2[^\)]+)\)$', re.M|re.I).sub,
    r'Package-Manager: portage-\1'))
mangler.append(functools.partial(
  re.compile(r' *\((?:manifest +recommit|(?:un)?signed +manifest +commit)\) *$', re.M|re.I).sub,
    r''))

def process_stream(source, output_dir, output):
  header = os.path.normpath(os.path.abspath(output_dir))
  header = "$Header: %s" % output_dir
  sourcekeyword = "$Source: %s" % output_dir
  line = source.readline()
  while line:
    chunks = line.split()
    if chunks[0:1] == ['data']:
      # Process the commit message...
      size = int(chunks[1])
      data = source.read(size)
      assert len(data) == size, (line, data)
      data = data.replace(header, "$Header: /var/cvsroot")
      data = data.replace(sourcekeyword, "$Source: /var/cvsroot")
      data = data.replace("$Name: not supported by cvs2svn $", "$Name:  $")
      line = 'data %i\n%s' % (len(data), data)
    output.write(line)
    line = source.readline()

def main(blob_file, output_dir, output):
  # allocate the pool now, before we start getting memory abusive; this is
  # used for thin-manifest conversion if active/enabled.
  #clean_pool = multiprocessing.Pool()

  # Be careful here to just iterate over source; doing so allows this script
  # to do basic processing as it goes (specifically while it's being fed from
  # the mainline cvs2git parallelized repo creator).
  with mmap_open(blob_file) as data:
    process_stream(data, output_dir, sys.stdout)

if __name__ == '__main__':
  sys.exit(main(sys.argv[1], sys.argv[2], sys.stdout))
