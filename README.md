# pymlocate
A small library for python that reads an mlocate database
The implementation has been done according to the man page mlocate.db(5).

Note that the mlocate database is usually residing in /var/lib/mlocate
which is only readable for group 'locate'.

Written by Alexander Schlemmer, 2016

This library can make use of the chardet module for recognizing character
encodings: https://pypi.python.org/pypi/chardet


## Example:
import pymlocate
ml = pymlocate.open_locate_db("mlocate.db", True)
print(ml[0].dirname)
