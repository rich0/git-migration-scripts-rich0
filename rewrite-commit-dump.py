#!/usr/bin/python
import functools
import re
import sys

mangler = []
mangler.append(functools.partial(
  re.compile(r"^\(paludis (0.1.*)\)$", re.M|re.I).sub,
    r"Package-Manager: paludis-\1/"))
mangler.append(functools.partial(
  re.compile(r"^\(portage version: (.*)\)$", re.M|re.I).sub,
    r"Package-Manager: portage-\1"))

write = sys.stdout.write
source = open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin
write('reset refs/heads/master\n')
while True:
  x = source.readline()
  if not x:
    break
  chunked = x.split()
  if not chunked:
    write(x)
    continue
  elif chunked[0] in ('reset', 'from'):
    continue
  elif chunked[0] == 'commit':
    write('commit refs/heads/master\n')
    continue
  elif chunked[0] != 'data':
    write(x)
    continue
  assert len(chunked) == 2
  size = int(chunked[1])
  data = source.read(size)
  assert len(data) == size
  for func in mangler:
    data = func(data)
  write("data %i\n%s" % (len(data), data))
