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
    elif signage in ('williamh@gentoo.org', 'w.d.hubbs@gmail.com'):
      signage = '30C46538'
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
class record(collections.namedtuple('record', fields)):
  def safe_combine(self, other):
    files = self.files.copy()
    assert not set(files).intersection(other.files), (files, other.files)
    files.update(other.files)
    items = list(self)
    items[file_idx] = files
    return self.__class__(*items)

  def update_files(self, other):
    files = self.files.copy()
    files.update(other.files if isinstance(other, record) else other)
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
  for idx, record in enumerate(sorted(records, key=lambda x:(x.timestamp,sorted(x.files),x.author,x.footerless_msg)), 1):
    if idx % progress_interval == 0:
      write('progress %s%%: %s of %i commits\n'
        % (str(int(100 * (float(idx)/total))).rjust(2), str(idx).rjust(total_len), total))
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

def deserialize_blob_map(path):
  with mmap_open(path) as handle:
    source = (x.strip().split() for x in readline_iterate(handle))
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

def get_blob(sha1):
  return subprocess.check_output(['git', 'show', sha1], cwd='git')

import traceback
def process_record(data):
  try:
    return _process_record(data)
  except Exception:
    return traceback.format_exc()

def _process_record(data):
  idx, manifests, record = data
  rewritten_record = record
  for fname, data in manifests:
    # Hacky, but it's just a test..
    chunked = data[1].split()
    sha1 = chunked[2]
    blob = get_blob(sha1)
    if '-----BEGIN PGP SIGNATURE-----' in blob:
      continue
    # Don't touch any old v1 manifests...
    blob = [x for x in blob.splitlines() if x]
    if not blob:
      # Empty manifest?  The hell?
      continue
    if any(x.startswith('MD5') for x in blob):
      continue
    blob2 = [x for x in blob if x.startswith('DIST')]
    if not blob or blob2 != blob:
      if blob2:
        p = subprocess.Popen(['git', 'hash-object', '-w', '--stdin', '--path', fname],
                             cwd='git', stdout=subprocess.PIPE, stdin=subprocess.PIPE)
        stdout, _ = p.communicate("\n".join(blob2))
        assert p.wait() == 0
        new_sha1 = stdout.strip()
        assert len(new_sha1) == 40, new_sha1
        rewritten_record = rewritten_record.update_files(
          {fname:(data[0], " ".join(chunked[:2] + [new_sha1, fname]))})
      else:
        rewritten_record = rewritten_record.update_files({})
        del rewritten_record.files[fname]
  if rewritten_record is not record:
    return (idx, record)
  else:
    return None

def thin_manifest_conversion(records, processing_pool):
  potentials = []
  for idx, record in enumerate(records):
    manifests = [(fname, data) for fname, data in record.files.iteritems()
                 if fname.endswith('/Manifest') and data[0] != 'D']
    if manifests:
      potentials.append((idx, manifests, record))

  rewrites = deletes = 0
  for result in processing_pool.imap_unordered(
      process_record, potentials, chunksize=30):
    if result is not None:
      if not isinstance(result, tuple):
        raise Exception(result)

      idx, value = result
      if not value.files:
        # Just drop the commit.
        value = None
        deletes += 1
      else:
        records[idx] = value
        rewrites += 1
  sys.stderr.write("potential:%i, deletes: %i, rewrites:%i\n" % (len(potentials), deletes, rewrites))
  return itertools.ifilter(None, records)

def process_directory(paths):
  commit_path, idx_path = paths
  with mmap_open(commit_path) as data:
    return tuple(manifest_dedup(
        deserialize_records(data, deserialize_blob_map(idx_path))))

def main(argv):
  # allocate the pool now, before we start getting memory abusive; this is
  # used for thin-manifest conversion if active/enabled.
  #clean_pool = multiprocessing.Pool()

  # Be careful here to just iterate over source; doing so allows this script
  # to do basic processing as it goes (specifically while it's being fed from
  # the mainline cvs2git parallelized repo creator).
  source = argv
  if not argv:
    # See python manpage for details; stdin buffers if you iterate over it;
    # we want each line as they're available, thus use this form.
    source = readline_iterate(sys.stdin)
  def consumable():
    for directory in source:
      directory = directory.strip()
      tmp = os.path.join(directory, 'cvs2svn-tmp')
      commits = os.path.join(tmp, 'git-dump.dat')
      if not os.path.exists(commits):
        sys.stderr.write("skipping %s; no commit data\n" % directory)
        sys.stderr.flush()
        continue
      yield (commits, os.path.join(tmp, 'git-blob.idx'))
  records = []
  record_generator = multiprocessing.Pool()
  for result in record_generator.imap_unordered(process_directory, consumable()):
    records.extend(result)
  record_generator.close()
  record_generator.join()
  del record_generator
  sys.stderr.write("All commits loaded.. starting dedup runs\n")
  sys.stderr.flush()
  sorter = operator.attrgetter('timestamp')
  # Get them into timestamp ordering first; this is abusing python stable
  # sort pretty much since any commits to the same repo w/ the same timestamp
  # will still have their original ordering (just that chunk will be moved).
  # This allows us to combine the history w/out losing the ordering per repo.
  records.sort(key=sorter)
  records[:] = simple_dedup(records)
#  records[:] = manifest_dedup(records)
#  records[:] = thin_manifest_conversion(records, clean_pool)
  serialize_records(records, sys.stdout)
  return 0

if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
