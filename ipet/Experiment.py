"""
The MIT License (MIT)

Copyright (c) 2016 Zuse Institute Berlin, www.zib.de

Permissions are granted as stated in the license file you have obtained
with this software. If you find the library useful for your purpose,
please refer to README.md for how to cite IPET.

@author: Gregor Hendel
"""
from ipet import misc, Key
from .TestRun import TestRun
from ipet.concepts.Manager import Manager
from ipet.misc.integrals import calcIntegralValue, getProcessPlotData
from ipet.parsing import ErrorFileReader, BestSolInfeasibleReader, ObjlimitReader, ObjsenseReader
from ipet.parsing.ReaderManager import ReaderManager
from pandas import Panel

import pandas as pd
import pickle
import os
import sys
import logging

class Experiment:
    """
    an Experiment represents a collection of TestRun objects and the routines for parsing
    """
    DEFAULT_GAPTOL = 1e-4
    DEFAULT_VALIDATEDUAL = False

    def __init__(self, files = [], listofreaders = [], gaptol = DEFAULT_GAPTOL, validatedual = DEFAULT_VALIDATEDUAL):
        self.testrunmanager = Manager()
        self.datakeymanager = Manager()

        self.readermanager = ReaderManager()
        self.readermanager.registerDefaultReaders()
        self.solufiles = []
        self.externaldata = None
        self.basename2testrun = {}
        self.probnamelist = []

        for filename in files:
            self.addOutputFile(filename)

        self.gaptol = gaptol
        self.validatedual = validatedual

    def set_gaptol(self, gaptol : float):
        """
        Set the relative gap tolerance for the solver validation
        """
        self.gaptol = gaptol

    def set_validatedual(self, validatedual : bool):
        """Enable or disable validation of the primal dual gap
        """
        self.validatedual = validatedual

    #def addOutputFile(self, filename, testrun = None): # testrun parameter is unused
    def addOutputFile(self, filename):
        """ Add an output file for a testrun or create a new testrun object with the specified filename

        this method handles all types of feasible file types for an experiment, either preparsed
        TestRun files or raw solver output files or .solu files with additional information.

        If a file with an unrecognized file extension is passed to this method, a ValueError is raised.

        For a list of allowed file extensions, see ipet.parsing.ReaderManager.
        """

        filebasename = os.path.splitext(os.path.basename(filename))[0]
        fileextension = os.path.splitext(filename)[-1]

        if not fileextension in [TestRun.FILE_EXTENSION] + self.readermanager.getFileExtensions():
            raise ValueError("Experiment cannot handle extension '%s' of file '%s'" % (fileextension, filename))

        if fileextension == TestRun.FILE_EXTENSION:
            try:
                testrun = TestRun.loadFromFile(filename)
            except IOError as e:
                sys.stderr.write(" Loading testrun from file %s caused an exception\n%s\n" % (filename, e))
                return
        else: #if testrun is None:
            testrun = self.basename2testrun.setdefault(filebasename, TestRun())

        if fileextension != TestRun.FILE_EXTENSION:
            testrun.appendFilename(filename)

        if testrun not in self.getTestRuns():
            self.testrunmanager.addAndActivate(testrun)

        self.updateDatakeys()

    def addStdinput(self):
        """ Add stdin as input (for piping from terminal)
        """
        # TODO how to handle misbehaving input?
        testrun = TestRun()
        testrun.setInputFromStdin()
        self.testrunmanager.addAndActivate(testrun)
        self.updateDatakeys()

    def addSoluFile(self, solufilename):
        """ Associate a solu file with all testruns
        """
        if solufilename not in self.solufiles:
            self.solufiles.append(solufilename)

    def removeTestrun(self, testrun):
        """ Remove a testrun object from the experiment
        """
        self.testrunmanager.deleteManageable(testrun)

    def addReader(self, reader):
        """ Add a reader to the experiments reader manager
        """
        self.readermanager.registerReader(reader)

    def hasReader(self, reader):
        """ Return True if reader is already present
        """
        return self.readermanager.hasReader(reader)

    def getProblemNames(self):
        """ Return the list of problem Names
        """
        return self.probnamelist

    def getTestRuns(self):
        """ Returns all TestRuns
        """
        return self.testrunmanager.getManageables()

    def getReaderManager(self):
        """ Return the Readermanager
        """
        return self.readermanager

    def updateDatakeys(self):
        """ Union of all data keys over all instances
        """
        keyset = set()
        for testrun in self.getTestRuns():
            for key in testrun.getKeySet():
                keyset.add(key)
        for key in keyset:
            try:
                self.datakeymanager.addManageable(key)
            except KeyError:
                pass
        if self.externaldata is not None:
            for key in self.externaldata.columns:
                try:
                    self.datakeymanager.addManageable(key)
                except KeyError:
                    pass

    def makeProbNameList(self):
        """ Return a list of names of problems that have been run
        """
        problemset = set()
        for testrun in self.getTestRuns():
            for problem in testrun.getProblemNames():
                problemset.add(problem)
        self.probnamelist = sorted(list(problemset))

    def getManager(self, managedclass):
        """ Get a specific manager of the experiment manager set. if managedclass is 'Testrun' or 'testrun',
        this will return the testrun manager object of this experiment
        """
        lowerclass = managedclass.lower()
        if hasattr(self, lowerclass + 'manager'):
            return getattr(self, lowerclass + 'manager')

    def getManagers(self):
        """ Return a dictionary of all managers of this experiment object
        """
        managernames = [name for name in dir(self) if name.endswith('manager')]
        return {name:getattr(self, name) for name in managernames}

    def addExternalDataFile(self, filename):
        """ Add a filename pointing to an external file, eg a solu file with additional information
        """
        try:
            self.externaldata = pd.read_table(filename, sep = " *", engine = 'python', header = 1, skipinitialspace = True)
            self.updateDatakeys()
            logging.debug("Experiment read external data file %s" % filename)
            logging.debug("%s" % self.externaldata.head(5))
        except:
            raise ValueError("Error reading file name %s" % filename)

    def collectData(self):
        """ Iterate over log files and solu file and collect data via installed readers
        """
        # add solu file to testrun if it's not yet done
        testruns = self.getTestRuns()
        for testrun in testruns:
            for solufilename in self.solufiles:
                testrun.appendFilename(solufilename)

        for testrun in testruns:
            self.readermanager.setTestRun(testrun)
            testrun.setupForDataCollection()
            self.readermanager.collectData()

        # TODO Is this calculated only for validation?
        self.makeProbNameList()
        self.calculateGaps()
        self.calculateIntegrals()

        self.checkProblemStatus()

        for testrun in testruns:
            testrun.setupAfterDataCollection()

        for tr in testruns:
            self.testrunmanager.reinsertManageable(tr)

        # post processing steps: things like primal integrals depend on several, independent data
        self.updateDatakeys()

    def getDatakeys(self):
        return self.datakeymanager.getAllRepresentations()

    def concatenateData(self):
        """ Concatenate data over all run TestRuns
        """
        self.data = pd.concat([tr.data for tr in self.getTestRuns()])

    def calculateGaps(self):
        """ Calculate and store primal and dual gap
        """
        for testrun in self.getTestRuns():
            for problemid in testrun.getProblemIds():
            
                optval = testrun.getProblemDataById(problemid, Key.OptimalValue)
                if optval is not None:
                    for key in [Key.PrimalBound, Key.DualBound]:
                        val = testrun.getProblemDataById(problemid, key)
                        if val is not None:
                            gap = misc.getGap(val, optval, True)
                            # subtract 'Bound' and add 'Gap' from Key
                            thename = key[:-5] + "Gap"
                            testrun.addDataById(thename, gap, problemid)

    def getJoinedData(self):
        """ Concatenate the testrun data (possibly joined with external data)
        
        this may result in nonunique index, the data is simply concatenated
        """
        datalist = []
        for tr in self.getTestRuns():
            trdata = tr.data
            if self.externaldata is not None:
                # Suggestion:
                # trdata = trdata.join(self.externaldata, on=Key.ProblemName, suffixes = ("", "_ext"))
                trdata = trdata.merge(self.externaldata, left_index = True, right_index = True, how = "left", suffixes = ("", "_ext"))
            datalist.append(trdata)

        return pd.concat(datalist)

    def calculateIntegrals(self):
        """ Calculate and store primal and dual integral values

        ... for every problem under 'PrimalIntegral' and 'DualIntegral'
        """
        dualargs = dict(historytouse = Key.DualBoundHistory, boundkey = Key.DualBound)
        for testrun in self.getTestRuns():

            # go through problems and calculate both primal and dual integrals
            for problemid in testrun.getProblemIds():
                processplotdata = getProcessPlotData(testrun, problemid)

                # check for well defined data (may not exist sometimes)
                if processplotdata:
                    try:
                        testrun.addDataById(Key.PrimalIntegral, calcIntegralValue(processplotdata), problemid)
                        logging.debug("Computed primal integral %.1f for problem %s, data %s" % (testrun.getProblemDataById(problemid, 'PrimalIntegral'), problemid, repr(processplotdata)))
                    except AssertionError as e:
                        logging.error("Error for primal bound on problem %s, list: %s" % (problemid, processplotdata))

                processplotdata = getProcessPlotData(testrun, problemid, **dualargs)
                # check for well defined data (may not exist sometimes)
                if processplotdata:
                    try:
                        testrun.addDataById(Key.DualIntegral, calcIntegralValue(processplotdata, pwlinear = True), problemid)
                    except AssertionError as e:
                        logging.error("Error for dual bound on problem %s, list: %s " % (problemid, processplotdata))

    def writeSolufile(self):
        """ Write a solu file based on the parsed results
        """
        # ## collect data
        solufiledata = {}
        for testrun in self.getTestRuns():
            for probname in testrun.getProblemIds():
                pb = testrun.getProblemDataById(probname, Key.PrimalBound)
                db = testrun.getProblemDataById(probname, Key.DualBound)
                if pb is None or db is None:
                    continue
                status = '=unkn='
                infinite = (pb >= misc.FLOAT_INFINITY or pb <= -misc.FLOAT_INFINITY)
                sense = 0
                if pb < db:
                    sense = 1
                else: sense = -1

                if not infinite and misc.getGap(pb, db, True) <= self.gaptol:
                    status = '=opt='
                elif not infinite:
                    status = '=best='
                elif pb == db:
                    status = '=inf='

                currentsolufileentry = solufiledata.get(probname)
                if currentsolufileentry == None:
                    solufiledata[probname] = (status, pb)
                else:
                    solustatus, solupb = currentsolufileentry
                    if solustatus == '=best=':
                        assert sense != 0
                        if not infinite and sense * (solupb - pb) < 0 or status == '=opt=':
                            solufiledata[probname] = (status, pb)
                    elif solustatus == '=unkn=':
                        solufiledata[probname] = (status, pb)

        # # write solufiledata to file
        newsolufilename = 'newsolufile.solu'
        f = open(newsolufilename, 'w')
        for prob in sorted(list(solufiledata.keys()), reverse = False):
            solustatus, solupb = solufiledata.get(prob)
            f.write("%s %s" % (solustatus, prob))
            if solustatus in ['=best=', '=opt=']:
                f.write(" %g" % solupb)
            f.write("\n")

        f.close()

    def testrunGetProbGapToOpt(self, testrun, problemid):
        """ Return the gap between found an solufile-solution
        """
        optsol = testrun.problemGetOptimalSolution(problemid)
        status = testrun.problemGetSoluFileStatus(problemid)
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)
        if status == 'opt' or status == 'best':
            return misc.getGap(float(pb), float(optsol))
        else:
            return misc.FLOAT_INFINITY
#
#    def checkForFails(self):
#        """ All testruns and instances go through fail check.
#
#        returns a dictionary to contain all instances which failed
#        """
#        faildict = {}
#        for testrun in self.getTestRuns():
#            for probname in self.probnamelist:
#                if testrun.problemCheckFail(probname) > 0:
#                    faildict.setdefault(testrun.getIdentification(), []).append(probname)
#        return faildict

    def isPrimalBoundBetter(self, testrun, problemid):
        """ Return True if the primal bound for the given problem exceeds the best known solution value
        """
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)
        objsense = testrun.getProblemDataById(problemid, Key.ObjectiveSense)
        optval = testrun.getProblemDataById(problemid, Key.OptimalValue)

        if pb is None:
            return False

        reltol = self.gaptol * max(abs(pb), 1.0)

        if objsense == ObjsenseReader.minimize and optval - pb > reltol:
            return True
        elif objsense == ObjsenseReader.maximize and pb - optval > reltol:
            return True
        return False

    def isDualBoundBetter(self, testrun, problemid):
        """ Return True if the dual bound for the given problem exceeds the best known solution value
        """
        db = testrun.getProblemDataById(problemid, Key.DualBound)
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)

        if db is None:
            return False

        objsense = testrun.getProblemDataById(problemid, Key.ObjectiveSense)
        optval = testrun.getProblemDataById(problemid, Key.OptimalValue)

        if pb is not None:
            reltol = self.gaptol * max(abs(pb), 1.0)
        else:
            reltol = self.gaptol * max(abs(optval), 1.0)

        if objsense == ObjsenseReader.minimize and db - optval > reltol:
            return True
        elif objsense == ObjsenseReader.maximize and optval - db > reltol:
            return True
        return False


    def validateDual(self, pb, db):
        """validate the relative gap between the primal and dual bound if dual validation is enabled
        """
        if self.validatedual:
            return misc.getGap(pb, db) < self.gaptol
        return True

    def determineStatusForOptProblem(self, testrun, problemid):
        """ Determine status for a problem for which we know the optimal solution value
        """
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)
        db = testrun.getProblemDataById(problemid, Key.DualBound)
        solverstatus = testrun.getProblemDataById(problemid, Key.SolverStatus)
        # TODO What is this "objectiveLimit", where is it set and what does it imply?
        objlimitreached = (solverstatus == "objectiveLimit")
        optval = testrun.getProblemDataById(problemid, Key.OptimalValue)
        objsense = testrun.getProblemDataById(problemid, Key.ObjectiveSense)
        solfound = True if pb is not None and not misc.isInfinite(pb) else False

        # the run failed because the primal or dual bound were better than the known optimal solution value
        if solfound and (self.isPrimalBoundBetter(testrun, problemid) or self.isDualBoundBetter(testrun, problemid)):
            code = Key.ProblemStatusCodes.FailObjectiveValue
        # the run finished correctly if an objective limit was given and the solver reported infeasibility
        elif not solfound and objlimitreached:
            objlimit = testrun.getProblemDataById(problemid, ObjlimitReader.datakey)
            reltol = self.gaptol * max(abs(optval), 1.0)

            if (objsense == ObjsenseReader.minimize and optval - objlimit >= -reltol) or \
                  (objsense == ObjsenseReader.maximize and objlimit - optval >= -reltol):
                code = Key.ProblemStatusCodes.Ok
            else:
                code = Key.ProblemStatusCodes.FailObjectiveValue
        # the solver reached a limit
        elif solverstatus in [Key.SolverStatusCodes.MemoryLimit, Key.SolverStatusCodes.TimeLimit, Key.SolverStatusCodes.NodeLimit]:
            code = Key.solverToProblemStatusCode(solverstatus)

        # the solver reached
        elif (db is None or self.validateDual(pb, db)) and not self.isPrimalBoundBetter(testrun, problemid):
            code = Key.ProblemStatusCodes.Ok
        else:
            code = Key.ProblemStatusCodes.Fail

        return code

    def determineStatusForBestProblem(self, testrun, problemid):
        """ Determine status for a problem for which we only know a best solution value
        """
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)
        db = testrun.getProblemDataById(problemid, Key.DualBound)
        solverstatus = testrun.getProblemDataById(problemid, Key.SolverStatus)

        # we failed because dual bound is higher than the known value of a primal bound
        if self.isDualBoundBetter(testrun, problemid):
            code = Key.ProblemStatusCodes.FailDualBound

        # solving reached a limit
        elif solverstatus in [Key.SolverStatusCodes.MemoryLimit, Key.SolverStatusCodes.TimeLimit, Key.SolverStatusCodes.NodeLimit]:
            code = Key.solverToProblemStatusCode(solverstatus)

            if self.isPrimalBoundBetter(testrun, problemid):
                code = Key.ProblemStatusCodes.Better

        # primal and dual bound converged
        elif self.validateDual(pb, db):
            code = Key.ProblemStatusCodes.SolvedNotVerified
        else:
            code = Key.ProblemStatusCodes.Fail

        return code

    def determineStatusForUnknProblem(self, testrun, problemid):
        """ Determine status for a problem for which we don't know anything about the feasibility or optimality
        """
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)
        db = testrun.getProblemDataById(problemid, Key.DualBound)
        solverstatus = testrun.getProblemDataById(problemid, Key.SolverStatus)

        if solverstatus:
            code = Key.solverToProblemStatusCode(solverstatus)

            if pb is not None:
                code = Key.ProblemStatusCodes.Better
        elif misc.getGap(pb, db) < self.gaptol:
            code = Key.ProblemStatusCodes.SolvedNotVerified
        else:
            code = Key.ProblemStatusCodes.Unknown

        return code

    def determineStatusForInfProblem(self, testrun, problemid):
        """ Determine status for a problem for which we know it's infeasible
        """
        pb = testrun.getProblemDataById(problemid, Key.PrimalBound)
        solfound = True if pb is not None and not misc.isInfinite(pb) else False

        # no solution was found
        if not solfound:
            solverstatus = testrun.getProblemDataById(problemid, Key.SolverStatus)
            # calc was inconclusive
            if solverstatus in [Key.SolverStatusCodes.TimeLimit, Key.SolverStatusCodes.MemoryLimit, Key.SolverStatusCodes.NodeLimit]:
                code = Key.solverToProblemStatusCode(solverstatus)
            else:
                code = Key.ProblemStatusCodes.Ok
        # a solution was found, that's not good
        else:
            code = Key.ProblemStatusCodes.FailSolOnInfeasibleInstance

        return code

    def checkProblemStatus(self):
        """ Check a problem solving status

        Check whether the solver's return status matches the information about the instances
        """
        logging.debug('Checking problem status')
        for testrun in self.getTestRuns():
            for problemid in testrun.getProblemIds():
                solustatus = testrun.problemGetSoluFileStatus(problemid)
                errcode = testrun.getProblemDataById(problemid, ErrorFileReader.datakey)

                # an error code means that the instance aborted
                if errcode is not None or testrun.getProblemDataById(problemid, Key.SolvingTime) is None:
                    code = Key.ProblemStatusCodes.FailAbort

                # if the best solution was not feasible in the original problem, it's a fail
                elif testrun.getProblemDataById(problemid, BestSolInfeasibleReader.datakey) == True:
                    code = Key.ProblemStatusCodes.FailSolInfeasible

                # go through the possible solution statuses and determine the Status of the run accordingly
                elif solustatus == 'opt':
                    code = self.determineStatusForOptProblem(testrun, problemid)
                elif solustatus == "best":
                    code = self.determineStatusForBestProblem(testrun, problemid)
                elif solustatus == "inf":
                    code = self.determineStatusForInfProblem(testrun, problemid)
                else:
                    code = self.determineStatusForUnknProblem(testrun, problemid)

                testrun.addDataById(Key.ProblemStatus, code, problemid)

                logging.debug("Problem %s in testrun %s solustatus %s, errorcode %s -> Status %s" % (problemid, testrun.getName(), repr(solustatus), repr(errcode), testrun.getProblemDataById(problemid, "Status")))

    def printToConsole(self, formatstr = "{idx} {d}"):
        for tr in self.testrunmanager.getActiveSet():
            tr.printToConsole(formatstr)

    def saveToFile(self, filename):
        """ Save the experiment instance to a file specified by 'filename'.

        Save comprises testruns and their collected data as well as custom built readers.
        @note: works for any file extension, preferred extension is '.cmp'
        """
        if not filename.endswith(".cmp"):
            print("Preferred file extension for experiment instances is '.cmp'")

        try:
            f = open(filename, "wb")
        except IOError:
            print("Could not open file named", filename)
            return
        pickle.dump(self, f, protocol = 2)

        f.close()

    @staticmethod
    def loadFromFile(filename):
        """ Load an experiment instance from the file specified by filename.

        This should work for all files generated by the saveToFile command.
        @return: a Experiment instance, or None if errors occured
        """
        try:
            f = open(filename, "rb")
        except IOError:
            print("Could not open file named", filename)
            return
        comp = pickle.load(f)
        f.close()

        if not isinstance(comp, Experiment):
            print("the loaded data is not a experiment instance!")
            return None
        else:
            return comp

    def getDataPanel(self, onlyactive = False):
        """ Return a pandas Data Panel of testrun data

        Create a panel from testrun data, using the testrun settings as key
        Set onlyactive to True to only get active testruns as defined by the testrun manager
        """
        trdatadict = {tr.getSettings():tr.data for tr in self.getTestRuns(onlyactive)}
        return Panel(trdatadict)
