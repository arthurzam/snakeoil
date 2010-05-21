# Copyright: 2005 Marien Zwart <marienz@gentoo.org>
# License: BSD/GPL2


import tempfile, os
from StringIO import StringIO
from snakeoil import compatibility
from snakeoil.test.mixins import mk_named_tempfile
from snakeoil.test import TestCase

pjoin = os.path.join

from snakeoil.fileutils import (
    iter_read_bash, read_bash, read_dict, AtomicWriteFile, read_bash_dict,
    ParseError)
from snakeoil.test.mixins import TempDirMixin


class TestBashCommentStripping(TestCase):

    def test_iter_read_bash(self):
        self.assertEqual(
            list(iter_read_bash(StringIO(
                        '\n'
                        '# hi I am a comment\n'
                        'I am not \n'
                        ' asdf # inline comment\n'))),
            ['I am not', 'asdf'])
        self.assertEqual(
            list(iter_read_bash(StringIO(
                'inline # comment '), allow_inline_comments=False)),
            ['inline # comment'])

    def test_read_bash(self):
        self.assertEqual(
            read_bash(StringIO(
                    '\n'
                    '# hi I am a comment\n'
                    'I am not\n')),
            ['I am not'])


class TestReadBashConfig(TestCase):

    def test_read_dict(self):
        self.assertEqual(
            read_dict(StringIO(
                    '\n'
                    '# hi I am a comment\n'
                    'foo1=bar\n'
                    'foo2="bar"\n'
                    'foo3=\'bar"\n'
                    )),
            {'foo1': 'bar',
             'foo2': 'bar',
             'foo3': '\'bar"',
             })
        self.assertEqual(
            read_dict(['foo=bar'], source_isiter=True), {'foo': 'bar'})
        self.assertRaises(
            ParseError, read_dict, ['invalid'], source_isiter=True)
        self.assertEqual(
            read_dict(StringIO("foo bar\nfoo2  bar\nfoo3\tbar\n"),
                splitter=None),
            {}.fromkeys(('foo', 'foo2', 'foo3'), 'bar'))



class ReadBashDictTest(TestCase):

    def setUp(self):
        self.valid_file = mk_named_tempfile()
        self.valid_file.write(
            '# hi I am a comment\n'
            'foo1=bar\n'
            "foo2='bar'\n"
            'foo3="bar"\n'
            'foo4=-/:j4\n'
            'foo5=\n')
        self.valid_file.flush()
        self.sourcing_file = mk_named_tempfile()
        self.sourcing_file.write('source "%s"\n' % self.valid_file.name)
        self.sourcing_file.flush()
        self.advanced_file = mk_named_tempfile()
        self.advanced_file.write(
            'one1=1\n'
            'one_=$one1\n'
            'two1=2\n'
            'two_=${two1}\n'
            )
        self.advanced_file.flush()
        self.env_file = mk_named_tempfile()
        self.env_file.write(
            'imported=${external}\n'
            )
        self.env_file.flush()
        self.escaped_file = mk_named_tempfile()
        self.escaped_file.write(
            'end=bye\n'
            'quoteddollar="\${dollar}"\n'
            'quotedexpansion="\${${end}}"\n'
            )
        self.escaped_file.flush()
        self.unclosed_file = mk_named_tempfile()
        self.unclosed_file.write('foo="bar')
        self.unclosed_file.flush()

    def tearDown(self):
        del self.valid_file
        del self.sourcing_file
        del self.advanced_file
        del self.env_file
        del self.escaped_file
        del self.unclosed_file

    def test_read_bash_dict(self):
        # TODO this is not even close to complete
        self.assertEqual(
            read_bash_dict(self.valid_file.name),
            {'foo1': 'bar', 'foo2': 'bar', 'foo3': 'bar', 'foo4': '-/:j4',
                'foo5': ''})
        s = "a=b\ny='"
        self.assertRaises(ParseError, read_bash_dict, StringIO(s))

    def test_var_read(self):
        self.assertEqual(read_bash_dict(StringIO("x=y@a\n")),
            {'x':'y@a'})
        self.assertEqual(read_bash_dict(StringIO("x=y~a\n")),
            {'x':'y~a'})
        self.assertEqual(read_bash_dict(StringIO("x=y^a\n")),
            {'x':'y^a'})
        self.assertEqual(read_bash_dict(StringIO('x="\nasdf\nfdsa"')),
            {'x':'\nasdf\nfdsa'})

    def test_empty_assign(self):
        open(self.valid_file.name, 'w').write("foo=\ndar=blah\n")
        self.assertEqual(read_bash_dict(self.valid_file.name),
            {'foo':'', 'dar':'blah'})
        open(self.valid_file.name, 'w').write("foo=\ndar=\n")
        self.assertEqual(read_bash_dict(self.valid_file.name),
            {'foo':'', 'dar':''})
        open(self.valid_file.name, 'w').write("foo=blah\ndar=\n")
        self.assertEqual(read_bash_dict(self.valid_file.name),
            {'foo':'blah', 'dar':''})

    def test_quoting(self):
        self.assertEqual(read_bash_dict(StringIO("x='y \\\na'")),
            {'x':'y \\\na'})
        self.assertEqual(read_bash_dict(StringIO("x='y'a\n")),
            {'x':"ya"})
        self.assertEqual(read_bash_dict(StringIO('x="y \\\nasdf"')),
            {'x':'y asdf'})

    def test_eof_without_newline(self):
        self.assertEqual(read_bash_dict(StringIO("x=y")), {'x':'y'})
        self.assertEqual(read_bash_dict(StringIO("x='y'a")), {'x':'ya'})

    def test_sourcing(self):
        # TODO this is not even close to complete
        self.assertEqual(
            read_bash_dict(self.sourcing_file.name, sourcing_command='source'),
            {'foo1': 'bar', 'foo2': 'bar', 'foo3': 'bar', 'foo4': '-/:j4',
                'foo5':''})

    def test_read_advanced(self):
        self.assertEqual(
            read_bash_dict(self.advanced_file.name),
            {'one1': '1',
             'one_': '1',
             'two1': '2',
             'two_': '2',
             })

    def test_env(self):
        self.assertEqual(
            read_bash_dict(self.env_file.name),
            {'imported': ''})
        env = {'external': 'imported foo'}
        env_backup = env.copy()
        self.assertEqual(
            read_bash_dict(self.env_file.name, env),
            {'imported': 'imported foo'})
        self.assertEqual(env_backup, env)

    def test_escaping(self):
        self.assertEqual(
            read_bash_dict(self.escaped_file.name), {
                'end': 'bye',
                'quoteddollar': '${dollar}',
                'quotedexpansion': '${bye}',
                })

    def test_unclosed(self):
        self.assertRaises(ParseError, read_bash_dict, self.unclosed_file.name)

    def test_wordchards(self):
        self.assertEqual(read_bash_dict(StringIO("x=-*")), {"x":"-*"})


class TestAtomicWriteFile(TempDirMixin, TestCase):

    def test_normal_ops(self):
        fp = pjoin(self.dir, "target")
        open(fp, "w").write("me")
        af = AtomicWriteFile(fp)
        af.write("dar")
        self.assertEqual(open(fp, "r").read(), "me")
        af.close()
        self.assertEqual(open(fp, "r").read(), "dar")

    def test_perms(self):
        fp = pjoin(self.dir, 'target')
        orig_um = os.umask(0777)
        try:
            af = AtomicWriteFile(fp, perms=0644)
            af.write("dar")
            af.close()
        finally:
            exiting_umask = os.umask(orig_um)
        self.assertEqual(exiting_umask, 0777)
        self.assertEqual(os.stat(fp).st_mode & 04777, 0644)

    def test_del(self):
        fp = pjoin(self.dir, "target")
        open(fp, "w").write("me")
        self.assertEqual(open(fp, "r").read(), "me")
        af = AtomicWriteFile(fp)
        af.write("dar")
        del af
        self.assertEqual(open(fp, "r").read(), "me")
        self.assertEqual(len(os.listdir(self.dir)), 1)

    def test_close(self):
        # verify that we handle multiple closes; no exception is good.
        af = AtomicWriteFile(pjoin(self.dir, "target"))
        af.close()
        af.close()

    def test_discard(self):
        fp = pjoin(self.dir, "target")
        open(fp, "w").write("me")
        self.assertEqual(open(fp, "r").read(), "me")
        af = AtomicWriteFile(fp)
        af.write("dar")
        af.discard()
        self.assertFalse(os.path.exists(af._temp_fp))
        af.close()
        self.assertEqual(open(fp, "r").read(), "me")

        # finally validate that it handles multiple discards properly.
        af = AtomicWriteFile(fp)
        af.write("dar")
        af.discard()
        af.discard()
        af.close()
