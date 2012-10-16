#!/usr/bin/python
import collections
import functools
import itertools
import operator
import os
import re
import sys
from collections import namedtuple

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

def mangle_portage(match, allowed=frozenset('abcdef0123456789')):
  content = match.group()
  assert isinstance(content, (unicode, str))
  content = content.strip()
  assert ('(', ')') == (content[0], content[-1]), content
  content = content[1:-1]
  values = [x.strip() for x in content.split(',')]
  # portage version: blah
  version = values[0].split(':', 1)[1].strip()
  results = ['Package-Manager: portage-' + version]
  values = [x for x in values if 'unsigned manifest' not in x.lower()]
  repoman = [x for x in values if 'repoman options:' in x.lower()]
  assert len(repoman) <= 1, content
  if repoman:
    repoman = ' '.join(repoman[0].split(':', 1)[1].split())
    results.append('RepoMan-Options: ' + repoman)
  values = [x.lower() for x in values]
  signage = [x for x in values if 'key' in x and 'signed' in x and 'unsigned' not in x]
  assert len(signage) <= 1, content
  if signage:
    signage = signage[0].rstrip().rsplit(None, 1)[1]
    if signage.startswith('0x'):
      signage = signage[2:]
    if signage in ('key', 'ultrabug'):
      # Known bad keys; this is why portage needs to do basic enforcement...
      signage = None
    elif '@' in signage:
      # Bleh.  be paranoid, ensure case wasn't affected.
      assert signage in content, (signage, content)
      signage = '<%s>' % signage
    elif signage.endswith('!'):
      assert allowed.issuperset(signage[:-1]), content
    else:
      assert allowed.issuperset(signage), content
    if signage:
      results.append('Manifest-Sign-Key: 0x' + signage.upper())
  return "\n".join(results)

# the TM/R is for crap like this:
# (Portage version: 2.2_pre7/cvs/Linux 2.6.25.4 Intel(R) Core(TM)2 Duo CPU E6750 @ 2.66GHz)
mangler.append(functools.partial(
  re.compile(r'^\(portage version: +(?:\((?:tm|r)\)|[^\)\n])+\)$', re.M|re.I).sub,
    mangle_portage))

known_footers = ('Package-Manager', 'RepoMan-Options', 'Manifest-Sign-Key')
fields = ('author', 'msg', 'files', 'timestamp', 'footerless_msg')
fields_map = dict((attr, idx) for idx, attr in enumerate(fields))
fake_fields = ('footerless_msg', 'timestamp')
file_idx = fields_map['files']
class record(namedtuple('record', fields)):
  def safe_combine(self, other):
    files = self.files.copy()
    assert not set(files).intersection(other.files), (files, other.files)
    files.update(other.files)
    items = list(self)
    items[file_idx] = files
    return self.__class__(*items)

  def update_files(self, other):
    files = self.files.copy()
    files.update(other.files)
    items = list(self)
    items[file_idx] = files
    return self.__class__(*items)

  @staticmethod
  def calculate_footerless_msg(msg):
    return tuple(x for x in msg.splitlines()
                 if x.split(':', 1)[0] not in known_footers)

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
      # Throw away the prefixed/trailing whitespace- some of our manglers leave those behind
      # unfortunately.  For fast-export reasons, a newline trailing is needed- but that should be it.
      d['msg'] = data.strip() + "\n"
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
        files[intern(os.path.normpath(mode[1]))] = (mode[0], line)
      elif mode[0] == 'M':
        # M 100644 e8b9ed651c6209820779382edee2537209aba4ae dev-cpp/gtkmm/ChangeLog
        # if it's not a sha1, but startswith ':'... then it's an index.
        chunks = line.split(None, 4)
        assert len(chunks) == 4, line
        fname = intern(os.path.normpath(chunks[3]))
        if chunks[2][0] == ':':
          line = ' '.join(chunks[:2] + [blob_idx[int(chunks[2][1:])], fname])
        files[fname] = (mode[0], line)
      else:
        raise AssertionError("got unknown file op: mode=%r, line:\n%r" % (mode[0], line))
      line = source.readline()
    d['files'] = files
    # Basic sanity check for the code above...
    d.setdefault('author', d.get('committer'))
    assert d['author'] is not None
    assert d['author'] == d['committer'], d
    d.pop('committer')
    # Skank the timestamp out...
    chunks = d['author'].rsplit(None, 1)
    assert len(chunks) == 2 and chunks[1] == '+0000', d['author']
    chunks = chunks[0].rsplit(None, 1)
    d['timestamp'] = long(chunks[1])
    d['author'] = intern(chunks[0])
    d['footerless_msg'] = record.calculate_footerless_msg(d['msg'])
    assert set(fields).issuperset(d), d
    yield record(*[d.get(x) for x in fields])
    # Bleh... of course namedtuple doesn't make this easy.
    line = source.readline()

def serialize_records(records, handle, target='refs/heads/master', progress=100):
  write = handle.write
  write('reset %s\n' % target)
  total = len(records)
  total_len = len(str(total))
  progress_interval = max(1, total // progress)
  for idx, record in enumerate(records, 1):
    if idx % progress_interval == 0:
      write('progress %02.0f%%: %s of %i commits\n'
        % ((100 * float(idx))/total, str(idx).rjust(total_len), total))
    write('commit %s\n' % target)
    write('mark :%i\n' % idx)
    # fields = ('mark', 'author', 'committer', 'msg', 'files')
    for name, value in zip(fields, record):
      if name in fake_fields:
        continue
      elif name == 'mark':
        write("%s %s\n" % (name, value))
      elif name == 'author':
        val = "%s %i +0000" % (value, record.timestamp)
        write('author %s\ncommitter %s\n' % (val, val))
      elif name == 'msg':
        write("data %i\n%s" % (len(value), value))
      elif name == 'files':
        for filename in sorted(value):
          write("%s\n" % (value[filename][1],))
      else:
        raise AssertionError("serialize is out of sync; don't know field %s" % name)
    write("\n")

def deserialize_blob_map(source):
  source = (x.strip().split() for x in source)
  return dict((int(x[0].lstrip(':')), x[1]) for x in source)

def simple_dedup(records):
  # dedup via timestamp/author/msg
  dupes = collections.defaultdict(list)
  for idx, record in enumerate(records):
    dupes[(record.timestamp, record.author, record.footerless_msg)].append((idx, record))
  mangled = []
  for key, value in dupes.iteritems():
    if len(value) == 1:
      continue
    value.sort(key=operator.itemgetter(0))
    combined = value[0][1]
    for idx, item in value[1:]:
      combined = combined.safe_combine(item)
    value[:] = [(value[0][0], combined)]
    mangled.append((key, value))
  l = itertools.imap(operator.itemgetter(0), dupes.itervalues())
  return itertools.imap(operator.itemgetter(1), sorted(l, key=operator.itemgetter(0)))

def manifest_dedup(records, backwards=(5*60)):
  # While searching back 5 minutes is a bit much... it's happened more than one might
  # think sadly.
  slots = collections.defaultdict(list)
  for idx, record in enumerate(records):
    if len(record.files) != 1:
      slots[record.timestamp].append((idx, record))
      continue
    manifest = record.files.items()[0]
    # if it's a deletion, we don't care...
    if not manifest[0].endswith('/Manifest') or manifest[1][0] == 'D':
      slots[record.timestamp].append((idx, record))
      continue
    manifest_dir = os.path.dirname(manifest[0])
    update = True
    for timestamp in xrange(record.timestamp, max(0, record.timestamp - backwards), -1):
      potential = slots.get(timestamp)
      if potential is None:
        continue
      for update_pos, (idx, target) in enumerate(reversed(potential), 1):
        # while intersecting pathways first is slower... we do it this way so that we can
        # spot if another author stepped in for a directory- if that occurs, manifest recommit
        # or not, we shouldn't mangle that history.
        if all(manifest_dir != os.path.dirname(x) for x in target.files):
          potential[0 - update_pos] = (idx, target.update_files(record))
          continue
        if (target.author == record.author and
            target.footerless_msg == record.footerless_msg):
          potential[-update_pos] = (idx, target.update_files(record))
          # same author/msg; allow the combination.
          update = False
        # note if author/msg didn't match, this becomes a forced injection.
        break

    if update:
      slots[record.timestamp].append((idx, record))
  # And... do the collapse.
  l = []
  for value in slots.itervalues():
    l.extend(value)
  # Sort by idx, but strip idx on the way out.
  return itertools.imap(operator.itemgetter(1), sorted(l, key=operator.itemgetter(0)))

def main(argv):
  records = []
  # Be careful here to just iterate over source; doing so allows this script
  # to do basic processing as it goes (specifically while it's being fed from
  # the mainline cvs2git parallelized repo creator).
  source = argv if argv else sys.stdin
  for directory in source:
    directory = directory.strip()
    tmp = os.path.join(directory, 'cvs2svn-tmp')
    commits = os.path.join(tmp, 'git-dump.dat')
    if not os.path.exists(commits):
      sys.stderr.write("skipping %s; no commit data\n" % directory)
      continue
    records.extend(manifest_dedup(
      deserialize_records(
        open(commits, 'r'),
        deserialize_blob_map(open(os.path.join(tmp, 'git-blob.idx'))))
      )
    )
  sorter = operator.attrgetter('timestamp')
  # Get them into timestamp ordering first; this is abusing python stable
  # sort pretty much since any commits to the same repo w/ the same timestamp
  # will still have their original ordering (just that chunk will be moved).
  # This allows us to combine the history w/out losing the ordering per repo.
  records.sort(key=sorter)
  records[:] = simple_dedup(records)
#  records[:] = manifest_dedup(records)
  serialize_records(records, sys.stdout)
  return 0

if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
