# Copyright: 2005-2006 Brian Harring <ferringb@gmail.com>
# License: GPL2

"""
file related operations, mainly reading
"""

import re, os
from shlex import shlex
from snakeoil.mappings import ProtectedDict
from snakeoil.osutils import readlines

class AtomicWriteFile(file):

    """File class that stores the changes in a tempfile.

    Upon close call, uses rename to replace the destination.

    Similar to file protocol behaviour, except for the C{__init__}, and
    that close *must* be called for the changes to be made live,

    if C{__del__} is triggered it's assumed that an exception occured,
    thus the changes shouldn't be made live.
    """
    def __init__(self, fp, binary=False, perms=None, uid=-1, gid=-1, **kwds):
        self.is_finalized = False
        if binary:
            file_mode = "wb"
        else:
            file_mode = "w"
        fp = os.path.realpath(fp)
        self.original_fp = fp
        self.temp_fp = os.path.join(
            os.path.dirname(fp), ".update.%s" % os.path.basename(fp))
        old_umask = None
        if perms:
            # give it just write perms
            old_umask = os.umask(0200)
        try:
            file.__init__(self, self.temp_fp, mode=file_mode, **kwds)
        finally:
            if old_umask is not None:
                os.umask(old_umask)
        if perms:
            os.chmod(self.temp_fp, perms)
        if (gid, uid) != (-1, -1):
            os.chown(self.temp_fd, uid, gid)

    def close(self):
        file.close(self)
        os.rename(self.temp_fp, self.original_fp)
        self.is_finalized = True

    def __del__(self):
        file.close(self)
        if not self.is_finalized:
            os.unlink(self.temp_fp)


def iter_read_bash(bash_source):
    """
    Read file honoring bash commenting rules.

    Note that it's considered good behaviour to close filehandles, as
    such, either iterate fully through this, or use read_bash instead.
    Once the file object is no longer referenced the handle will be
    closed, but be proactive instead of relying on the garbage
    collector.

    @param bash_source: either a file to read from
        or a string holding the filename to open.
    """
    if isinstance(bash_source, basestring):
        bash_source = readlines(bash_source, True)
    for s in bash_source:
        s = s.strip()
        if s and s[0] != "#":
            yield s


def read_bash(bash_source):
    return list(iter_read_bash(bash_source))
read_bash.__doc__ = iter_read_bash.__doc__


def read_dict(bash_source, splitter="=", source_isiter=False):
    """
    read key value pairs, ignoring bash-style comments.

    @param splitter: the string to split on.  Can be None to
        default to str.split's default
    @param bash_source: either a file to read from,
        or a string holding the filename to open.
    """
    d = {}
    if not source_isiter:
        filename = bash_source
        i = iter_read_bash(bash_source)
    else:
        # XXX what to do?
        filename = '<unknown>'
        i = bash_source
    line_count = 1
    try:
        for k in i:
            line_count += 1
            try:
                k, v = k.split(splitter, 1)
            except ValueError:
                raise ParseError(filename, line_count)
            if len(v) > 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            d[k] = v
    finally:
        del i
    return d

def read_bash_dict(bash_source, vars_dict=None, sourcing_command=None):
    """
    read bash source, yielding a dict of vars

    @param bash_source: either a file to read from
        or a string holding the filename to open
    @param vars_dict: initial 'env' for the sourcing.
        Is protected from modification.
    @type vars_dict: dict or None
    @param sourcing_command: controls whether a source command exists.
        If one does and is encountered, then this func is called.
    @type sourcing_command: callable
    @raise ParseError: thrown if invalid syntax is encountered.
    @return: dict representing the resultant env if bash executed the source.
    """

    # quite possibly I'm missing something here, but the original
    # portage_util getconfig/varexpand seemed like it only went
    # halfway. The shlex posix mode *should* cover everything.

    if vars_dict is not None:
        d, protected = ProtectedDict(vars_dict), True
    else:
        d, protected = {}, False
    if isinstance(bash_source, basestring):
        f = open(bash_source, "r")
    else:
        f = bash_source
    s = bash_parser(f, sourcing_command=sourcing_command, env=d)

    try:
        tok = ""
        try:
            while tok is not None:
                key = s.get_token()
                if key is None:
                    break
                elif key.isspace():
                    # we specifically have to check this, since we're
                    # screwing with the whitespace filters below to
                    # detect empty assigns
                    continue
                eq = s.get_token()
                if eq != '=':
                    raise ParseError(bash_source, s.lineno,
                        "got token %r, was expecting '='" % eq)
                val = s.get_token()
                if val is None:
                    val = ''
                # look ahead to see if we just got an empty assign.
                next_tok = s.get_token()
                if next_tok == '=':
                    # ... we did.
                    # leftmost insertions, thus reversed ordering
                    s.push_token(next_tok)
                    s.push_token(val)
                    val = ''
                else:
                    s.push_token(next_tok)
                d[key] = val
        except ValueError, e:
            raise ParseError(bash_source, s.lineno, str(e))
    finally:
        del f
    if protected:
        d = d.new
    return d


var_find = re.compile(r'\\?(\${\w+}|\$\w+)')
backslash_find = re.compile(r'\\.')
def nuke_backslash(s):
    s = s.group()
    if s == "\\\n":
        return "\n"
    try:
        return chr(ord(s))
    except TypeError:
        return s[1]

class bash_parser(shlex):
    def __init__(self, source, sourcing_command=None, env=None):
        self.__dict__['state'] = ' '
        shlex.__init__(self, source, posix=True)
        self.wordchars += "@${}/.-+/:~^"
        self.wordchars = frozenset(self.wordchars)
        if sourcing_command is not None:
            self.source = sourcing_command
        if env is None:
            env = {}
        self.env = env
        self.__pos = 0

    def __setattr__(self, attr, val):
        if attr == "state":
            if (self.state, val) in (
                ('"', 'a'), ('a', '"'), ('a', ' '), ("'", 'a')):
                strl = len(self.token)
                if self.__pos != strl:
                    self.changed_state.append(
                        (self.state, self.token[self.__pos:]))
                self.__pos = strl
        self.__dict__[attr] = val

    def sourcehook(self, newfile):
        try:
            return shlex.sourcehook(self, newfile)
        except IOError, ie:
            raise ParseError(newfile, 0, str(ie))

    def read_token(self):
        self.changed_state = []
        self.__pos = 0
        tok = shlex.read_token(self)
        if tok is None:
            return tok
        self.changed_state.append((self.state, self.token[self.__pos:]))
        tok = ''
        for s, t in self.changed_state:
            if s in ('"', "a"):
                tok += self.var_expand(t).replace("\\\n", '')
            else:
                tok += t
        return tok

    def var_expand(self, val):
        prev, pos = 0, 0
        l = []
        match = var_find.search(val)
        while match is not None:
            pos = match.start()
            if val[pos] == '\\':
                # it's escaped. either it's \\$ or \\${ , either way,
                # skipping two ahead handles it.
                pos += 2
            else:
                var = val[match.start():match.end()].strip("${}")
                if prev != pos:
                    l.append(val[prev:pos])
                if var in self.env:
                    if not isinstance(self.env[var], basestring):
                        raise ValueError(
                            "env key %r must be a string, not %s: %r" % (
                                var, type(self.env[var]), self.env[var]))
                    l.append(self.env[var])
                else:
                    l.append("")
                prev = pos = match.end()
            match = var_find.search(val, pos)

        # do \\ cleansing, collapsing val down also.
        val = backslash_find.sub(nuke_backslash, ''.join(l) + val[prev:])
        return val


class ParseError(Exception):

    def __init__(self, filename, line, errmsg=None):
        if errmsg is not None:
            Exception.__init__(self,
                               "error parsing '%s' on or before %i: err %s" %
                               (filename, line, errmsg))
        else:
            Exception.__init__(self,
                               "error parsing '%s' on or before %i" %
                               (filename, line))
        self.file, self.line, self.errmsg = filename, line, errmsg
