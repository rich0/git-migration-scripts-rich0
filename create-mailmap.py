#!/usr/bin/python
from xml.etree import ElementTree as etree

def main(source):
  root = etree.parse(source).getroot()
  for user in root.findall('user'):
    fullname = user.findall('realname')[0].get('fullname')
    # Compute email ourselves...
    username = user.get('username')
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
  sys.stdout.write("mailmap=%r\n" % (mailmap,))
  sys.exit(0)
