#!/usr/bin/python
from xml.etree import ElementTree as etree

def main(source):
  root = etree.parse(source).getroot()
  for user in root.findall('user'):
    fullname = user.findall('realname')[0].get('fullname')
    # note we don't actually know jerrym's name; thus just leave
    # it empty.
    if fullname.lower() == 'unknown':
      fullname = ''
    # Compute email ourselves...
    username = user.get('username')
    if username in ('luke-jr',):
      fullname = ''
    assert username
    email = '%s@gentoo.org' % username
    yield username, (fullname, email)
    # Handle aliases...
    for alias in user.findall('alias'):
      yield alias.text, (fullname, email)


if __name__ == '__main__':
  import sys
  if len(sys.argv) != 2:
    sys.stderr.write("path to userinfo.xml required\n")
    sys.exit(1)
  
  mailmap = dict(main(open(sys.argv[1], 'rb')))
  # Add some known missing aliases.
  mailmap['uid2078'] = mailmap['jer']
  mailmap['uid2153'] = mailmap['remi']
  mailmap['uid2162'] = mailmap['bicatali']
  mailmap['uid895'] = mailmap['genstef']
  sys.stdout.write("mailmap=%r\n" % (mailmap,))
  sys.exit(0)
