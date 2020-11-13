import sys
import os

pythonVersion = sys.version.split()[0]
if not pythonVersion.startswith('3.'):
    sys.stderr.write("\nFEHLER: es wird Python 3 benoetigt, nicht " + pythonVersion + ".\n\n")
    os._exit(0)

import os.path
import runpy
import argparse
import json
import traceback
import shutil
import site
import importlib
import re

# Simulates that wypp cannot be imported so that we can test the code path where
# wypp is directly loaded from the writeYourProgram.py file. The default is False.
SIMULATE_LIB_FROM_FILE = False
ASSERT_INSTALL = False # if True, then a failing installation causes a total failure
VERBOSE = False # set via commandline
LIB_DIR = os.path.dirname(__file__)

INSTALLED_MODULE_NAME = 'wypp'
MODULES_TO_INSTALL = ['writeYourProgram.py', 'drawingLib.py', '__init__.py']

def verbose(s):
    if VERBOSE:
        print(f'[V] {s}')

def parseCmdlineArgs():
    parser = argparse.ArgumentParser(description='Run Your Program!')
    parser.add_argument('file', metavar='FILE',
                        help='The file to run')
    parser.add_argument('--check-runnable', dest='checkRunnable', action='store_const',
                        const=True, default=False,
                        help='Abort with exit code 1 if loading the file raises errors')
    parser.add_argument('--check', dest='check', action='store_const',
                        const=True, default=False,
                        help='Abort with exit code 1 if there are test errors.')
    parser.add_argument('--install-mode', dest='installMode', type=str,
                        help='One of "regular", "assertInstall", "libFromFile"')
    parser.add_argument('--verbose', dest='verbose', action='store_const',
                        const=True, default=False,
                        help='Be verbose')
    parser.add_argument('--test-file', dest='testFile',
                        type=str, help='Run additional tests contained in this file.')
    try:
        args = parser.parse_args()
    except SystemExit as ex:
        os._exit(ex.code)
    if not args.file.endswith('.py'):
        print("FEHLER: die angegebene Datei ist keine Python Datei.")
        os._exit(0)
    return args

def readFile(f):
    with open(f) as file:
        return file.read()

def readVersion():
    version = None
    try:
        content = readFile(os.path.join(LIB_DIR, '..', '..', 'package.json'))
        d = json.loads(content)
        version = d['version']
    except:
        pass
    return version

def printWelcomeString(file, version):
    cwd = os.getcwd() + "/"
    if file.startswith(cwd):
        file = file[len(cwd):]
    versionStr = '' if not version else f'Version {version}, '
    print(f'=== WILLKOMMEN zu "Schreibe Dein Programm!" ' +
          f'({versionStr}Python {pythonVersion}, {file}) ===')

def isSameFile(f1, f2):
    x = readFile(f1)
    y = readFile(f2)
    return x == y

def installLib():
    userDir = site.USER_SITE
    installDir = os.path.join(userDir, INSTALLED_MODULE_NAME)
    try:
        os.makedirs(installDir, exist_ok=True)
        installedFiles = sorted([f for f in os.listdir(installDir)
                                   if os.path.isfile(os.path.join(installDir, f))])
        wantedFiles = sorted(MODULES_TO_INSTALL)
        if installedFiles == wantedFiles:
            for i in range(len(installedFiles)):
                f1 = os.path.join(installDir, installedFiles[i])
                f2 = os.path.join(LIB_DIR, wantedFiles[i])
                if not isSameFile(f1, f2):
                    break
            else:
                # no break, all files equal
                verbose(f'All wypp files already installed in {userDir}')
                return
        for f in installedFiles:
            p = os.path.join(installDir, f)
            os.remove(p)
        d = os.path.join(installDir, 'wypp')
        for m in MODULES_TO_INSTALL:
            src = os.path.join(LIB_DIR, m)
            tgt = os.path.join(installDir, m)
            shutil.copyfile(src, tgt)
        print(f'Die Python-Bibliothek wurde erfolgreich in {userDir} installiert.\n' +
              'Bitte starten Sie Visual Studio Code neu, um sicherzustellen, dass überall\n' +
              'die neueste Version verwendet wird.\n')
    except Exception as e:
        print(f'Die Installation der Python-Bibliothek ist fehlgeschlagen: {e}')
        if ASSERT_INSTALL:
            raise e

class Lib:
    def __init__(self, mod, properlyImported):
        self.properlyImported = properlyImported
        if not properlyImported:
            self.initModule = mod['initModule']
            self.resetTestCount = mod['resetTestCount']
            self.printTestResults = mod['printTestResults']
            self.dict = mod
        else:
            self.initModule = mod.initModule
            self.resetTestCount = mod.resetTestCount
            self.printTestResults = mod.printTestResults
            d = {}
            self.dict = d
            for name in dir(mod):
                if name and name[0] != '_':
                  d[name] = getattr(mod, name)

def loadLib(onlyCheckRunnable):
    libDefs = None
    mod = INSTALLED_MODULE_NAME
    verbose(f'Attempting to import {mod}')
    try:
        if SIMULATE_LIB_FROM_FILE:
            raise ImportError(f'deliberately failing when import {mod}')
        # It's the prefered way to properly import wypp. With this setup, student's code
        # may or may not import wypp. And if it does import wypp, there is no suffering from
        # module schizophrenia.
        wypp = importlib.import_module(mod)
        libDefs = Lib(wypp, True)
        verbose(f'Successfully imported {mod} module')
    except Exception as e:
        verbose(f'Failed to import {mod}: {e}')
        pass
    if not libDefs:
        # This code path is only here to support the case that installation fails.
        libFile = os.path.join(LIB_DIR, 'writeYourProgram.py')
        d = runpy.run_path(libFile)
        verbose(f'Successfully loaded library code from {libFile}')
        libDefs = Lib(d, False)
    libDefs.initModule(enableChecks=not onlyCheckRunnable,
                       quiet=onlyCheckRunnable)
    return libDefs

importRe = importRe = re.compile(r'^import\s+wypp\s*$|^from\s+wypp\s+import\s+\*\s*$')

def findWyppImport(fileName):
    lines = []
    try:
        with open(fileName) as f:
            lines = f.readlines()
    except Exception as e:
        verbose(f'Failed to read code from {fileName}: {e}')
    for l in lines:
        if importRe.match(l):
            return True
    return False

def runCode(fileToRun, libDefs, onlyCheckRunnable):
    importsWypp = findWyppImport(fileToRun)
    globalsForRun = {}
    if importsWypp:
        if not libDefs.properlyImported:
            globalsForRun = {INSTALLED_MODULE_NAME: libDefs.dict}
    else:
        # This case will go away once we required students to import wypp explicitly
        globalsForRun = libDefs.dict
    doRun = lambda: runpy.run_path(fileToRun, globalsForRun)
    if onlyCheckRunnable:
        try:
            doRun()
        except Exception as e:
            print(f'Loading file {fileToRun} crashed')
            traceback.print_exc()
            os._exit(1)
        else:
            os._exit(0)
    userDefs = doRun()
    return userDefs

def runTestsInFile(testFile, libDefs):
    allDefs = {}
    for k, v in libDefs.items():
        allDefs[k] = v
    for k, v in userDefs.items():
        allDefs[k] = v
    libDefs.resetTestCount()
    runpy.run_path(testFile, allDefs)
    return libDefs['printTestResults']('Dozent:  ')

def performChecks(check, testFile, libDefs):
    prefix = ''
    if check and testFile:
        prefix = 'Student: '
    testResultsStudent = libDefs.printTestResults(prefix)
    if check:
        testResultsInstr = {'total': 0, 'failing': 0}
        if testFile:
            testResultsInstr = runTestsInFile(args.testFile, libDefs)
        failingSum = testResultsStudent['failing'] + testResultsInstr['failing']
        os._exit(0 if failingSum < 1 else 1)

def prepareInteractive():
    print('\n')
    # clear the terminal, reset on Mac OSX and Linux. This prevents strange history bugs where
    # the command just entered is echoed again (2020-10-14).
    os.system('cls' if os.name == 'nt' else 'reset')

def enterInteractive(userDefs):
    for k, v in userDefs.items():
        globals()[k] = v
    print()

def main():
    args = parseCmdlineArgs()
    global VERBOSE, SIMULATE_LIB_FROM_FILE, ASSERT_INSTALL
    if args.verbose:
        VERBOSE = True
    if args.installMode == 'regular' or args.installMode is None:
        pass
    elif args.installMode == 'libFromFile':
        SIMULATE_LIB_FROM_FILE = True
    elif args.installMode == 'assertInstall':
        ASSERT_INSTALL = True
    else:
        print(f'Invalid value for --install-mode: {args.installMode}')
        sys.exit(1)
    fileToRun = args.file
    isInteractive = sys.flags.interactive
    version = readVersion()
    if isInteractive:
        prepareInteractive()
    installLib()
    if not args.checkRunnable:
        printWelcomeString(fileToRun, version)
    libDefs = loadLib(onlyCheckRunnable=args.checkRunnable)
    userDefs = runCode(fileToRun, libDefs, args.checkRunnable)
    performChecks(args.check, args.testFile, libDefs)
    if isInteractive:
        enterInteractive(userDefs)

if __name__ == '__main__':
    main()
