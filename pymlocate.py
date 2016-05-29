#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ------------------------------------------------------------------------------
# pymlocate - A small library to read an mlocate database
# The implementation has been done according to the man page mlocate.db(5).
#
# Copyright (C) 2016 Alexander Schlemmer

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301  USA
# ------------------------------------------------------------------------------

import os
import sys
from struct import unpack
try:
    import chardet
except ImportError:
    print("Module chardet not found. Limited charset recognition.")


def detect_encoding(filename):
    '''
    Try to decode the filename (a byte buffer) with the two most
    common encodings for filenames: UTF-8 and windows-1252

    If both fail, use the chardet module to detect the encoding.

    Return the charset which has been detected.
    '''
    try:
        filename.decode("UTF-8")
        charset = "UTF-8"
    except UnicodeDecodeError:
        try:
            filename.decode("windows-1252")
            charset = "windows-1252"
        except UnicodeDecodeError:
            charsetdet = chardet.detect(filename)
            charset = charsetdet["encoding"]
    return charset
            
            
            

class LocateDBSubEntry(object):
    '''
    Stores the individual file entries within dir entries.
    '''
    def __init__(self, entry_type, filename, charset):
        '''
        Initialize this entry with:
        entry_type:
                - file: a regular file entry
                - subdir: a sub directory
        filename: The (relative) filename of this entry
        charset: The charset in which the filename is encoded

        entry_type can also be "dirterm", but this is only used
        during reading the database and will not be stored in the
        list of sub entries. It marks the end of the file list of
        a LocateDBEntry within the mlocate database.
        '''
        self.entry_type = entry_type
        self.filename = filename
        self.charset = charset

class LocateDBEntry(object):
    '''
    Stores dir entries (the topmost structure within the mlocate db).
    '''
    def __init__(self, dirname, subentries, time_1, time_2):
        '''
        Initialize this dir entry with:
        dirname: Absolute filename of this directory
        subentries: A list of LocateDBSubEntrys
        time_1: Directory time (seconds)
        time_2: Directory time (nanoseconds)

        See mlocate.db(5) for detailed descriptions.
        '''
        self.dirname = dirname
        self.subentries = subentries
        self.time_1 = time_1
        self.time_2 = time_2

def zts(f):
    '''
    Read one zero terminated string from the file f.

    Return a tuple:
            - The decoded filename
            - The number of bytes which have been read
            - The charset which has been used for decoding the filename
    '''
    buf = b''
    l = 1
    c, = unpack("c", f.read(1))
    while c != b'\x00':
        buf += c
        c, = unpack("c", f.read(1))
        l += 1

    if len(buf) == 0:
        return ("", l)
    bytebuf = bytes(buf)
    charset = detect_encoding(bytebuf)
    if charset is None:
        return (str(bytebuf), l)
    return (bytebuf.decode(charset), l, charset)

def zts_list(f):
    '''
    Read a list of zero terminated strings from the file f.

    Return a tuple:
            - The list of strings
            - The number of bytes which have been read
    '''
    lst = []
    l = 1
    c, = unpack("c", f.read(1))
    while c != b'\x00':
        s = zts(f)
        # Is charset detection also needed here?
        entry = c.decode("UTF-8") + s[0]
        lst.append(entry)
        c, = unpack("c", f.read(1))
        l += s[1] + 1
    return (lst, l)

def read_file_entry(f):
    '''
    Reads one file entry from the file f and returns a new LocateDBSubEntry.
    '''
    typef, = unpack("c", f.read(1))
    stype = None
    path = None
    charset = None
    if typef == b'\x00':
        stype = "file"
        res = zts(f)
        path = res[0]
        charset = res[2]
    elif typef == b'\x01':
        stype = "subdir"
        res = zts(f)
        path = res[0]
        charset = res[2]
    elif typef == b'\x02':
        stype = "dirterm"
    else:
        raise RuntimeError("Wrong type detected.")
    return LocateDBSubEntry(stype, path, charset)

def read_content_entry(f):
    '''
    Reads a full directory entry from the file f and returns a new LocateDBEntry.
    '''
    time_1, = unpack(">Q", f.read(8))
    time_2, = unpack(">i", f.read(4))
    padding, = unpack("4s", f.read(4))
    pname = zts(f)[0]
    pcontents = []
    entryf = read_file_entry(f)
    while entryf.entry_type != "dirterm":
        pcontents.append(entryf)
        entryf = read_file_entry(f)
    return LocateDBEntry(pname, pcontents, time_1, time_2)

def fast_reader(f):
    '''
    The fast reader uses a different strategy for reading in the whole database:
    Instead of reading each directory and file entry one by one
    it completely reads the whole file and splits the buffer into
    the respective chunks. This method is about 3-4 times faster
    than the straight forward method, but can fail in rare cases
    (e.g. when the split characters might be used as characters
    in filenames, for some encodings).
    '''
    # Read all contents:
    bs = 65536
    buf = f.read(bs)
    full_file = bytes()
    while len(buf) > 0:
        full_file += buf
        buf = f.read(bs)

    contents = list()
    # Split by dirterm:
    dtsplit = full_file.split(b'\x02')[:-1]
    j = 0
    while j < len(dtsplit):
        dt = dtsplit[j]
        while len(dt) < 16:
            j += 1
            dt += b'\x02' + dtsplit[j]
        time_1, = unpack(">Q", dt[0:8])
        time_2, = unpack(">i", dt[8:12])
        padding, = unpack("4s", dt[12:16])
        filesplit = dt[16:].split(b'\x00')[:-1]
        bpname = filesplit[0]
        charset = detect_encoding(bpname)
        if charset is None:
            pname = str(bpname)
        else:
            pname = bpname.decode(charset)
        i = 1
        pcontents = []
        while i < len(filesplit):
            if filesplit[i] == b'':
                stype = "file"
                bytebuf = filesplit[i+1]
                i += 2
            else:
                stype = "subdir"
                bytebuf = filesplit[i][1:]
                i += 1
            charset = detect_encoding(bytebuf)
            if charset is None:
                path = str(bytebuf)
            else:
                path = bytebuf.decode(charset)
            pcontents.append(LocateDBSubEntry(stype, path, charset))
        contents.append(LocateDBEntry(pname, pcontents, time_1, time_2))
        j += 1
    return contents

def open_locate_db(filename, fast_mode=False):
    '''
    Read an mlocate database from filename (e.g. mlocate.db).
    fast_mode: Use the fast mode (see description of function fast_reader)

    Returns a list of LocateDBEntries.
    '''
    with open(filename, "rb") as f:
        mcode, = unpack("8s", f.read(8))
        if mcode != b'\x00mlocate':
            print("Not an mlocate database.")
            sys.exit(1)
        cblocksize, = unpack(">i", f.read(4))
        fversion, = unpack("c", f.read(1))
        rvis, = unpack("c", f.read(1))
        padding, = unpack("2s", f.read(2))
        basepath = zts(f)
        l = 0
        full_config = []
        while l < cblocksize:
            config, ll = zts_list(f)
            full_config.extend(config)
            l += ll

        if not fast_mode:
            contents = []
            while f.tell() < os.stat(filename).st_size:
                entry = read_content_entry(f)
                contents.append(entry)
            return contents

        return fast_reader(f)
