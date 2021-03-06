import unittest
import os
import logging
import re
import tempfile

import oeqa.utils.ftools as ftools
from oeqa.selftest.base import oeSelfTest
from oeqa.utils.commands import runCmd, bitbake, get_bb_var, create_temp_layer
from oeqa.utils.decorators import testcase
from oeqa.selftest.devtool import DevtoolBase


templayerdir = ''

def setUpModule():
    global templayerdir
    templayerdir = tempfile.mkdtemp(prefix='recipetoolqa')
    create_temp_layer(templayerdir, 'selftestrecipetool')
    result = runCmd('bitbake-layers add-layer %s' % templayerdir)
    # Ensure we have the right data in shlibs/pkgdata
    logger = logging.getLogger("selftest")
    logger.info('Running bitbake to generate pkgdata')
    bitbake('base-files coreutils busybox selftest-recipetool-appendfile')

def tearDownModule():
    runCmd('bitbake-layers remove-layer %s' % templayerdir, ignore_status=True)
    runCmd('rm -rf %s' % templayerdir)
    # Shouldn't leave any traces of this artificial recipe behind
    bitbake('-c cleansstate selftest-recipetool-appendfile')


class RecipetoolTests(DevtoolBase):

    def setUpLocal(self):
        self.tempdir = tempfile.mkdtemp(prefix='recipetoolqa')
        self.track_for_cleanup(self.tempdir)
        self.testfile = os.path.join(self.tempdir, 'testfile')
        with open(self.testfile, 'w') as f:
            f.write('Test file\n')

    def tearDownLocal(self):
        runCmd('rm -rf %s/recipes-*' % templayerdir)

    def _try_recipetool_appendfile(self, testrecipe, destfile, newfile, options, expectedlines, expectedfiles):
        result = runCmd('recipetool appendfile %s %s %s %s' % (templayerdir, destfile, newfile, options))
        self.assertNotIn('Traceback', result.output)
        # Check the bbappend was created and applies properly
        recipefile = get_bb_var('FILE', testrecipe)
        bbappendfile = self._check_bbappend(testrecipe, recipefile, templayerdir)
        # Check the bbappend contents
        with open(bbappendfile, 'r') as f:
            self.assertEqual(expectedlines, f.readlines())
        # Check file was copied
        filesdir = os.path.join(os.path.dirname(bbappendfile), testrecipe)
        for expectedfile in expectedfiles:
            self.assertTrue(os.path.isfile(os.path.join(filesdir, expectedfile)), 'Expected file %s to be copied next to bbappend, but it wasn\'t' % expectedfile)
        # Check no other files created
        createdfiles = []
        for root, _, files in os.walk(filesdir):
            for f in files:
                createdfiles.append(os.path.relpath(os.path.join(root, f), filesdir))
        self.assertTrue(sorted(createdfiles), sorted(expectedfiles))
        return bbappendfile, result.output

    def _try_recipetool_appendfile_fail(self, destfile, newfile, checkerror):
        cmd = 'recipetool appendfile %s %s %s' % (templayerdir, destfile, newfile)
        result = runCmd(cmd, ignore_status=True)
        self.assertNotEqual(result.status, 0, 'Command "%s" should have failed but didn\'t' % cmd)
        self.assertNotIn('Traceback', result.output)
        for errorstr in checkerror:
            self.assertIn(errorstr, result.output)


    def test_recipetool_appendfile_basic(self):
        # Basic test
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                        '\n']
        _, output = self._try_recipetool_appendfile('base-files', '/etc/motd', self.testfile, '', expectedlines, ['motd'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_invalid(self):
        # Test some commands that should error
        self._try_recipetool_appendfile_fail('/etc/passwd', self.testfile, ['ERROR: /etc/passwd cannot be handled by this tool', 'useradd', 'extrausers'])
        self._try_recipetool_appendfile_fail('/etc/timestamp', self.testfile, ['ERROR: /etc/timestamp cannot be handled by this tool'])
        self._try_recipetool_appendfile_fail('/dev/console', self.testfile, ['ERROR: /dev/console cannot be handled by this tool'])

    def test_recipetool_appendfile_alternatives(self):
        # Now try with a file we know should be an alternative
        # (this is very much a fake example, but one we know is reliably an alternative)
        self._try_recipetool_appendfile_fail('/bin/ls', self.testfile, ['ERROR: File /bin/ls is an alternative possibly provided by the following recipes:', 'coreutils', 'busybox'])
        corebase = get_bb_var('COREBASE')
        # Need a test file - should be executable
        testfile2 = os.path.join(corebase, 'oe-init-build-env')
        testfile2name = os.path.basename(testfile2)
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://%s"\n' % testfile2name,
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${base_bindir}\n',
                         '    install -m 0755 ${WORKDIR}/%s ${D}${base_bindir}/ls\n' % testfile2name,
                         '}\n']
        self._try_recipetool_appendfile('coreutils', '/bin/ls', testfile2, '-r coreutils', expectedlines, [testfile2name])
        # Now try bbappending the same file again, contents should not change
        bbappendfile, _ = self._try_recipetool_appendfile('coreutils', '/bin/ls', self.testfile, '-r coreutils', expectedlines, [testfile2name])
        # But file should have
        copiedfile = os.path.join(os.path.dirname(bbappendfile), 'coreutils', testfile2name)
        result = runCmd('diff -q %s %s' % (testfile2, copiedfile), ignore_status=True)
        self.assertNotEqual(result.status, 0, 'New file should have been copied but was not')

    def test_recipetool_appendfile_binary(self):
        # Try appending a binary file
        result = runCmd('recipetool appendfile %s /bin/ls /bin/ls -r coreutils' % templayerdir)
        self.assertIn('WARNING: ', result.output)
        self.assertIn('is a binary', result.output)

    def test_recipetool_appendfile_add(self):
        corebase = get_bb_var('COREBASE')
        # Try arbitrary file add to a recipe
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/something\n',
                         '}\n']
        self._try_recipetool_appendfile('netbase', '/usr/share/something', self.testfile, '-r netbase', expectedlines, ['testfile'])
        # Try adding another file, this time where the source file is executable
        # (so we're testing that, plus modifying an existing bbappend)
        testfile2 = os.path.join(corebase, 'oe-init-build-env')
        testfile2name = os.path.basename(testfile2)
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile \\\n',
                         '            file://%s \\\n' % testfile2name,
                         '            "\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/something\n',
                         '    install -m 0755 ${WORKDIR}/%s ${D}${datadir}/scriptname\n' % testfile2name,
                         '}\n']
        self._try_recipetool_appendfile('netbase', '/usr/share/scriptname', testfile2, '-r netbase', expectedlines, ['testfile', testfile2name])

    def test_recipetool_appendfile_add_bindir(self):
        # Try arbitrary file add to a recipe, this time to a location such that should be installed as executable
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${bindir}\n',
                         '    install -m 0755 ${WORKDIR}/testfile ${D}${bindir}/selftest-recipetool-testbin\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('netbase', '/usr/bin/selftest-recipetool-testbin', self.testfile, '-r netbase', expectedlines, ['testfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_add_machine(self):
        # Try arbitrary file add to a recipe, this time to a location such that should be installed as executable
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'PACKAGE_ARCH = "${MACHINE_ARCH}"\n',
                         '\n',
                         'SRC_URI_append_mymachine = " file://testfile"\n',
                         '\n',
                         'do_install_append_mymachine() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/something\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('netbase', '/usr/share/something', self.testfile, '-r netbase -m mymachine', expectedlines, ['mymachine/testfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_orig(self):
        # A file that's in SRC_URI and in do_install with the same name
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-orig', self.testfile, '', expectedlines, ['selftest-replaceme-orig'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_todir(self):
        # A file that's in SRC_URI and in do_install with destination directory rather than file
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-todir', self.testfile, '', expectedlines, ['selftest-replaceme-todir'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_renamed(self):
        # A file that's in SRC_URI with a different name to the destination file
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-renamed', self.testfile, '', expectedlines, ['file1'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_subdir(self):
        # A file that's in SRC_URI in a subdir
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/selftest-replaceme-subdir\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-subdir', self.testfile, '', expectedlines, ['testfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_src_glob(self):
        # A file that's in SRC_URI as a glob
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/selftest-replaceme-src-globfile\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-src-globfile', self.testfile, '', expectedlines, ['testfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_inst_glob(self):
        # A file that's in do_install as a glob
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-inst-globfile', self.testfile, '', expectedlines, ['selftest-replaceme-inst-globfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_inst_todir_glob(self):
        # A file that's in do_install as a glob with destination as a directory
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-inst-todir-globfile', self.testfile, '', expectedlines, ['selftest-replaceme-inst-todir-globfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_patch(self):
        # A file that's added by a patch in SRC_URI
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${sysconfdir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${sysconfdir}/selftest-replaceme-patched\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/etc/selftest-replaceme-patched', self.testfile, '', expectedlines, ['testfile'])
        for line in output.splitlines():
            if line.startswith('WARNING: '):
                self.assertIn('add-file.patch', line, 'Unexpected warning found in output:\n%s' % line)
                break
        else:
            self.assertTrue(False, 'Patch warning not found in output:\n%s' % output)

    def test_recipetool_appendfile_script(self):
        # Now, a file that's in SRC_URI but installed by a script (so no mention in do_install)
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/selftest-replaceme-scripted\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-scripted', self.testfile, '', expectedlines, ['testfile'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_inst_func(self):
        # A file that's installed from a function called by do_install
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-inst-func', self.testfile, '', expectedlines, ['selftest-replaceme-inst-func'])
        self.assertNotIn('WARNING: ', output)

    def test_recipetool_appendfile_postinstall(self):
        # A file that's created by a postinstall script (and explicitly mentioned in it)
        # First try without specifying recipe
        self._try_recipetool_appendfile_fail('/usr/share/selftest-replaceme-postinst', self.testfile, ['File /usr/share/selftest-replaceme-postinst may be written out in a pre/postinstall script of the following recipes:', 'selftest-recipetool-appendfile'])
        # Now specify recipe
        expectedlines = ['FILESEXTRAPATHS_prepend := "${THISDIR}/${PN}:"\n',
                         '\n',
                         'SRC_URI += "file://testfile"\n',
                         '\n',
                         'do_install_append() {\n',
                         '    install -d ${D}${datadir}\n',
                         '    install -m 0644 ${WORKDIR}/testfile ${D}${datadir}/selftest-replaceme-postinst\n',
                         '}\n']
        _, output = self._try_recipetool_appendfile('selftest-recipetool-appendfile', '/usr/share/selftest-replaceme-postinst', self.testfile, '-r selftest-recipetool-appendfile', expectedlines, ['testfile'])

    def test_recipetool_appendfile_extlayer(self):
        # Try creating a bbappend in a layer that's not in bblayers.conf and has a different structure
        exttemplayerdir = os.path.join(self.tempdir, 'extlayer')
        self._create_temp_layer(exttemplayerdir, False, 'oeselftestextlayer', recipepathspec='metadata/recipes/recipes-*/*')
        result = runCmd('recipetool appendfile %s /usr/share/selftest-replaceme-orig %s' % (exttemplayerdir, self.testfile))
        self.assertNotIn('Traceback', result.output)
        createdfiles = []
        for root, _, files in os.walk(exttemplayerdir):
            for f in files:
                createdfiles.append(os.path.relpath(os.path.join(root, f), exttemplayerdir))
        createdfiles.remove('conf/layer.conf')
        expectedfiles = ['metadata/recipes/recipes-test/selftest-recipetool-appendfile/selftest-recipetool-appendfile.bbappend',
                         'metadata/recipes/recipes-test/selftest-recipetool-appendfile/selftest-recipetool-appendfile/selftest-replaceme-orig']
        self.assertEqual(sorted(createdfiles), sorted(expectedfiles))

    def test_recipetool_appendfile_wildcard(self):

        def try_appendfile_wc(options):
            result = runCmd('recipetool appendfile %s /etc/profile %s %s' % (templayerdir, self.testfile, options))
            self.assertNotIn('Traceback', result.output)
            bbappendfile = None
            for root, _, files in os.walk(templayerdir):
                for f in files:
                    if f.endswith('.bbappend'):
                        bbappendfile = f
                        break
            if not bbappendfile:
                self.assertTrue(False, 'No bbappend file created')
            runCmd('rm -rf %s/recipes-*' % templayerdir)
            return bbappendfile

        # Check without wildcard option
        recipefn = os.path.basename(get_bb_var('FILE', 'base-files'))
        filename = try_appendfile_wc('')
        self.assertEqual(filename, recipefn.replace('.bb', '.bbappend'))
        # Now check with wildcard option
        filename = try_appendfile_wc('-w')
        self.assertEqual(filename, recipefn.split('_')[0] + '_%.bbappend')



    def test_recipetool_create(self):
        # Try adding a recipe
        tempsrc = os.path.join(self.tempdir, 'srctree')
        os.makedirs(tempsrc)
        recipefile = os.path.join(self.tempdir, 'logrotate_3.8.7.bb')
        srcuri = 'https://fedorahosted.org/releases/l/o/logrotate/logrotate-3.8.7.tar.gz'
        result = runCmd('recipetool create -o %s %s -x %s' % (recipefile, srcuri, tempsrc))
        self.assertTrue(os.path.isfile(recipefile))
        checkvars = {}
        checkvars['LICENSE'] = 'GPLv2'
        checkvars['LIC_FILES_CHKSUM'] = 'file://COPYING;md5=18810669f13b87348459e611d31ab760'
        checkvars['SRC_URI'] = 'https://fedorahosted.org/releases/l/o/logrotate/logrotate-${PV}.tar.gz'
        checkvars['SRC_URI[md5sum]'] = '99e08503ef24c3e2e3ff74cc5f3be213'
        checkvars['SRC_URI[sha256sum]'] = 'f6ba691f40e30e640efa2752c1f9499a3f9738257660994de70a45fe00d12b64'
        self._test_recipe_contents(recipefile, checkvars, [])

    def test_recipetool_create_git(self):
        # Ensure we have the right data in shlibs/pkgdata
        bitbake('libpng pango libx11 libxext jpeg')
        # Try adding a recipe
        tempsrc = os.path.join(self.tempdir, 'srctree')
        os.makedirs(tempsrc)
        recipefile = os.path.join(self.tempdir, 'libmatchbox.bb')
        srcuri = 'git://git.yoctoproject.org/libmatchbox'
        result = runCmd('recipetool create -o %s %s -x %s' % (recipefile, srcuri, tempsrc))
        self.assertTrue(os.path.isfile(recipefile), 'recipetool did not create recipe file; output:\n%s' % result.output)
        checkvars = {}
        checkvars['LICENSE'] = 'LGPLv2.1'
        checkvars['LIC_FILES_CHKSUM'] = 'file://COPYING;md5=7fbc338309ac38fefcd64b04bb903e34'
        checkvars['S'] = '${WORKDIR}/git'
        checkvars['PV'] = '1.0+git${SRCPV}'
        checkvars['SRC_URI'] = srcuri
        checkvars['DEPENDS'] = 'libpng pango libx11 libxext jpeg'
        inherits = ['autotools', 'pkgconfig']
        self._test_recipe_contents(recipefile, checkvars, inherits)
