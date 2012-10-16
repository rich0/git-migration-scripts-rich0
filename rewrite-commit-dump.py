#!/usr/bin/python
import functools
import operator
import os
import re
import sys
from collections import namedtuple

mangler = []
mangler.append(functools.partial(
  re.compile(r"^\(paludis (0.1.*)\)$", re.M|re.I).sub,
    r"Package-Manager: paludis-\1/"))
mangler.append(functools.partial(
  re.compile(r"^\(portage version: (.*)\)$", re.M|re.I).sub,
    r"Package-Manager: portage-\1"))

fields = ('author', 'committer', 'msg', 'files', 'timestamp')
record = namedtuple('record', fields)

def deserialize_records(source, blob_idx):
  line = source.readline()
  while line:
    while line.split()[0] in ('reset', 'progress'):
      line = source.readline()

    # First get the free form fields; stop after we get the commit msg.
    assert line.split()[0] == 'commit', line
    d = {}
    while True:
      line = source.readline()
      chunks = line.split(None, 1)
      assert len(chunks) == 2, line
      if chunks[0] in ('from', 'mark'):
        continue
      assert chunks[0] in ('author', 'committer', 'data')
      if chunks[0] != 'data':
        d[chunks[0]] = chunks[1].strip()
        continue
      # Process the commit message...
      size = int(chunks[1])
      data = source.read(size)
      assert len(data) == size, (line, data)
      for func in mangler:
        data = func(data)
      d['msg'] = data
      line = source.readline()
      # Note that cvs2git writes slightly funky data statements; the byte count
      # doesn't necessarily include the trailing newline.
      if line == '\n':
        line = source.readline()
      break

    assert line
    # From can show up here on occasion... annoying.
    if line.split()[0:1] == ['from']:
      line = source.readline()
    files = {}
    while line != '\n':
      # Two types I can spot; M=modify, and D=delete.
      assert line[-1] == '\n'
      line = line[:-1]
      mode = line.split(None, 1)
      assert len(mode) == 2, line
      if mode[0] == 'D':
        files[mode[1]] = (mode[0], line)
      elif mode[0] == 'M':
        # M 100644 e8b9ed651c6209820779382edee2537209aba4ae dev-cpp/gtkmm/ChangeLog
        # if it's not a sha1, but startswith ':'... then it's an index.
        chunks = line.split(None, 4)
        assert len(chunks) == 4, line
        fname = chunks[3]
        if chunks[2][0] == ':':
          line = ' '.join(chunks[:2] + [blob_idx[int(chunks[2][1:])], fname])
        files[fname] = (mode[0], line)
      else:
        raise AssertionError("got unknown file op: mode=%r, line:\n%r" % (mode[0], line))
      line = source.readline()
    d['files'] = files
    # Basic sanity check for the code above...
    assert set(fields).issuperset(d), d
    d.setdefault('author', d.get('committer'))
    assert d['author'] is not None
    # Skank the timestamp out...
    chunks = d['author'].rsplit(None, 1)
    assert len(chunks) == 2 and chunks[1] == '+0000', d['author']
    d['timestamp'] = long(chunks[0].rsplit(None, 1)[1])
    yield record(*[d.get(x) for x in fields])
    # Bleh... of course namedtuple doesn't make this easy.
    line = source.readline()

def serialize_records(records, handle, target='refs/heads/master', progress=5000):
  write = handle.write
  write('reset %s\n' % target)
  total = len(records)
  for idx, record in enumerate(records, 1):
    if idx % progress == 0:
      write('progress %02.1f%%: %i of %i commits\n'
        % ((100 * float(idx))/total, idx, total))
    write('commit %s\n' % target)
    write('mark :%i\n' % idx)
    # fields = ('mark', 'author', 'committer', 'msg', 'files')
    for name, value in zip(fields, record):
      if name == 'files':
        for filename in sorted(value):
          write("%s\n" % (value[filename][1],))
      elif name in ('mark', 'author', 'committer'):
        write("%s %s\n" % (name, value))
      elif name == 'msg':
        write("data %i\n%s" % (len(value), value))
      elif name == 'timestamp':
        continue
      else:
        raise AssertionError("serialize is out of sync; don't know field %s" % name)
    write("\n")

def deserialize_blob_map(source):
  source = (x.strip().split() for x in source)
  return dict((int(x[0].lstrip(':')), x[1]) for x in source)

def main(argv):
  records = []
  source = argv if argv else sys.stdin
  directories = [x.strip() for x in source]
  for directory in directories:
    tmp = os.path.join(directory, 'cvs2svn-tmp')
    commits = os.path.join(tmp, 'git-dump.dat')
    if not os.path.exists(commits):
      sys.stderr.write("skipping %s; no commit data\n" % directory)
      continue
    blob_index = deserialize_blob_map(open(os.path.join(tmp, 'git-blob.idx')))
    records.extend(deserialize_records(open(commits, 'r'), blob_index))
  records.sort(key=operator.attrgetter('timestamp'))
  #records = list(deserialize_records(source))
  serialize_records(records, sys.stdout)
  return 0

if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
