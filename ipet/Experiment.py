'''
The MIT License (MIT)

Copyright (c) 2016 Zuse Institute Berlin, www.zib.de

Permissions are granted as stated in the license file you have obtained
with this software. If you find the library useful for your purpose,
please refer to README.md for how to cite IPET.

@author: Gregor Hendel
'''
from ipet.parsing.ReaderManager import ReaderManager
from .TestRun import TestRun
from ipet import misc
import pandas
from ipet.parsing import SolvingTimeReader

import pickle
from ipet.concepts.Manager import Manager

from ipet.parsing import PrimalBoundReader, DualBoundReader, ErrorFileReader, \
    BestSolInfeasibleReader, LimitReachedReader, ObjlimitReader, \
    ObjsenseReader

from ipet.misc.integrals import calcIntegralValue, getProcessPlotData
from pandas import Panel
import pandas as pd
import os
import sys
import logging

class Experiment:
    '''
    an Experiment represents a collection of TestRun objects and the routines for parsing
    '''
    
    Status_Ok = 'ok'
    Status_SolvedNotVerified = "solved_not_verified"
    Status_Better = "better"
    Status_Unknown = "unknown"
    Status_FailDualBound = "fail_dual_bound"
    Status_FailObjectiveValue = "fail_objective_value"
    Status_FailSolInfeasible = "fail_solution_infeasible"
    Status_FailSolOnInfeasibleInstance = "fail_solution_on_infeasible_instance"
    Status_Fail = "fail"
    Status_FailAbort = "fail_abort"
    datakey_gap = 'SoluFileGap'
    
    
    _status2Priority = {Status_Ok : 1000,
                        Status_SolvedNotVerified : 500,
                        Status_Better : 250,
                        Status_Unknown : 100,
                        Status_FailDualBound : -250,
                        Status_FailObjectiveValue : -500,
                        Status_FailSolInfeasible : -1000,
                        Status_FailSolOnInfeasibleInstance : -2000,
                        Status_Fail : -3000,
                        Status_FailAbort : -10000}
    
    
    @staticmethod
    def getBestStatus(*args):
        '''
        returns the best status among a list of status codes given as args
        '''
        return max(*args, key = lambda x : Experiment._status2Priority.get(x, 0))
    
    @staticmethod
    def getWorstStatus(*args):
        '''
        return the worst status among a list of status codes
        '''
        return min(*args, key = lambda x : Experiment._status2Priority.get(x, 0)) 
                        

    def __init__(self, files=[], listofreaders=[]):
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

    def addOutputFile(self, filename, testrun=None):
        """
        adds an output file for a testrun or create a new testrun object with the specified filename

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
        elif testrun is None:
            testrun = self.basename2testrun.setdefault(filebasename, TestRun())

        if fileextension != TestRun.FILE_EXTENSION:
            testrun.appendFilename(filename)

        if testrun not in self.testrunmanager.getManageables():
            self.testrunmanager.addAndActivate(testrun)

        self.updateDatakeys()

    def addSoluFile(self, solufilename):
        '''
        associate a solu file with all testruns
        '''
        if solufilename not in self.solufiles:
            self.solufiles.append(solufilename)

    def removeTestrun(self, testrun):
        '''
        remove a testrun object from the experiment
        '''
        self.testrunmanager.deleteManageable(testrun)

    def addReader(self, reader):
        '''
        add a reader to the experiments reader manager
        '''
        self.readermanager.registerReader(reader)

    def hasReader(self, reader):
        '''
        return True if reader is already present
        '''
        return self.readermanager.hasReader(reader)

    def getProblems(self):
        '''
        returns the list of problem names
        '''
        return self.probnamelist

    def getTestRuns(self):
        return self.testrunmanager.getManageables()
    
    def getReaderManager(self):
        return self.readermanager

    def updateDatakeys(self):
        '''
        union of all data keys over all instances
        '''
        keyset = set()
        for testrun in self.testrunmanager.getManageables():
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
        problemset = set()
        for testrun in self.testrunmanager.getManageables():
            for problem in testrun.getProblems():
                problemset.add(problem)

        self.probnamelist = sorted(list(problemset))

    def getManager(self, managedclass):
        '''
        get a specific manager of the experiment manager set. if managedclass is 'Testrun' or 'testrun',
        this will return the testrun manager object of this experiment
        '''
        lowerclass = managedclass.lower()
        if hasattr(self, lowerclass + 'manager'):
            return getattr(self, lowerclass + 'manager')

    def getManagers(self):
        '''
        returns a dictionary of all managers of this experiment object
        '''
        managernames = [name for name in dir(self) if name.endswith('manager')]
        return {name:getattr(self, name) for name in managernames}

    def addExternalDataFile(self, filename):
        '''
        add a filename pointing to an external file, eg a solu file with additional information
        '''
        try:
            self.externaldata = pd.read_table(filename, sep = " *", engine = 'python', header = 1, skipinitialspace = True)
            self.updateDatakeys()
            logging.debug("Experiment read external data file %s" % filename)
            logging.debug("%s" % self.externaldata.head(5))
        except:
            raise ValueError("Error reading file name %s"%filename)


    def collectData(self):
        '''
        iterate over log files and solu file and collect data via installed readers
        '''

        # add solu file to testrun if it's not yet done
        testruns = self.testrunmanager.getManageables()
        for testrun in testruns:
            for solufilename in self.solufiles:
                testrun.appendFilename(solufilename)

        for testrun in testruns:
            self.readermanager.setTestRun(testrun)
            testrun.setupForDataCollection()
            self.readermanager.collectData()

        self.makeProbNameList()
        self.calculateGaps()
        self.calculateIntegrals()
        self.checkProblemStatus()

        for testrun in testruns:
            testrun.finalize()

        for tr in testruns:
            self.testrunmanager.reinsertManageable(tr)


        
        # post processing steps: things like primal integrals depend on several, independent data
        self.updateDatakeys()

    def getDatakeys(self):
        return self.datakeymanager.getAllRepresentations()

    def concatenateData(self):
        self.data = pandas.concat([tr.data for tr in self.testrunmanager.getManageables()])

    def calculateGaps(self):
        '''
        calculate and store primal and dual gap
        '''
        for testrun in self.testrunmanager.getManageables():
            for probname in self.probnamelist:

                optval = testrun.problemGetData(probname, "OptVal")
                if optval is not None:
                    for key in ["PrimalBound", "DualBound"]:
                        val = testrun.problemGetData(probname, key)
                        if val is not None:
                            gap = misc.getGap(val, optval, True)
                            # subtract 'Bound' and add 'Gap' from Key
                            thename = key[:-5] + "Gap"
                            testrun.addData(probname, thename, gap)



    def getJoinedData(self):
        '''
        concatenate the testrun data (possibly joined with external data)

        '''
        datalist = []
        for tr in self.testrunmanager.getManageables():
            trdata = tr.data
            if self.externaldata is not None:
                trdata = trdata.merge(self.externaldata, left_index = True, right_index = True, how = "left", suffixes = ("", "_ext"))
            datalist.append(trdata)

        return pd.concat(datalist)



    def calculateIntegrals(self):
        '''
        calculates and stores primal and dual integral values for every problem under 'PrimalIntegral' and 'DualIntegral'
        '''
        dualargs = dict(historytouse='dualboundhistory', boundkey='DualBound')
        for testrun in self.testrunmanager.getManageables():

            # go through problems and calculate both primal and dual integrals
            for probname in self.probnamelist:
                processplotdata = getProcessPlotData(testrun, probname)

                #check for well defined data (may not exist sometimes)

                if processplotdata:
                    try:
                        testrun.addData(probname, 'PrimalIntegral', calcIntegralValue(processplotdata))
                        logging.debug("Computed primal integral %.1f for problem %s, data %s"  % (testrun.problemGetData(probname, 'PrimalIntegral'), probname, repr(processplotdata)))
                    except AssertionError as e:
                        logging.error("Error for primal bound on problem %s, list: %s"%(probname, processplotdata))

                processplotdata = getProcessPlotData(testrun, probname, **dualargs)
                # check for well defined data (may not exist sometimes)
                if processplotdata:
                    try:
                        testrun.addData(probname, 'DualIntegral', calcIntegralValue(processplotdata, pwlinear=True))
                    except AssertionError as e:
                        logging.error("Error for dual bound on problem %s, list: %s "%(probname, processplotdata))


    def writeSolufile(self):
        '''
        write a solu file based on the parsed results
        '''
        # ## collect data
        solufiledata = {}
        for testrun in self.testrunmanager.getManageables():
            for probname in testrun.getProblems():
                pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
                db = testrun.problemGetData(probname, DualBoundReader.datakey)
                if pb is None or db is None:
                    continue
                status = '=unkn='
                infinite = (pb >= misc.FLOAT_INFINITY or pb <= -misc.FLOAT_INFINITY)
                sense = 0
                if pb < db:
                    sense = 1
                else: sense = -1

                if not infinite and misc.getGap(pb, db, True) <= 1e-5:
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
        for prob in sorted(list(solufiledata.keys()), reverse=False):
            solustatus, solupb = solufiledata.get(prob)
            f.write("%s %s" % (solustatus, prob))
            if solustatus in ['=best=', '=opt=']:
                f.write(" %g" % solupb)
            f.write("\n")

        f.close()


    def testrunGetProbGapToOpt(self, testrun, probname):
        optsol = testrun.problemGetOptimalSolution(probname)
        status = testrun.problemGetSoluFileStatus(probname)
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
        if status == 'opt' or status == 'best':
            return misc.getGap(float(pb), float(optsol))
        else:
            return misc.FLOAT_INFINITY

    def checkForFails(self):
        '''
        all testruns and instances go through fail check.

        returns a dictionary to contain all instances which failed
        '''
        faildict = {}
        for testrun in self.testrunmanager.getManageables():
            for probname in self.probnamelist:
                if testrun.problemCheckFail(probname) > 0:
                    faildict.setdefault(testrun.getIdentification(), []).append(probname)
        return faildict

    def isPrimalBoundBetter(self, testrun, probname):
        """
        returns True if the primal bound for the given problem exceeds the best known solution value
        """
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
        objsense = testrun.problemGetData(probname, ObjsenseReader.datakey)
        optval = testrun.problemGetData(probname, "OptVal")

        if pb is None:
            return False

        reltol = 1e-5 * max(abs(pb), 1.0)

        if objsense == ObjsenseReader.minimize and optval - pb > reltol:
            return True
        elif objsense == ObjsenseReader.maximize and pb - optval > reltol:
            return True
        return False

    def isDualBoundBetter(self, testrun, probname):
        """
        returns True if the dual bound for the given problem exceeds the best known solution value
        """
        db = testrun.problemGetData(probname, DualBoundReader.datakey)
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)

        if db is None:
            return False

        objsense = testrun.problemGetData(probname, ObjsenseReader.datakey)
        optval = testrun.problemGetData(probname, "OptVal")

        if pb is not None:
            reltol = 1e-5 * max(abs(pb), 1.0)
        else:
            reltol = 1e-5 * max(abs(optval), 1.0)

        if objsense == ObjsenseReader.minimize and db - optval > reltol:
            return True
        elif objsense == ObjsenseReader.maximize and optval - db > reltol:
            return True
        return False

    def determineStatusForOptProblem(self, testrun, probname):
        """
        determine status for a problem for which we know the optimal solution value
        """
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
        db = testrun.problemGetData(probname, DualBoundReader.datakey)
        limitreached = testrun.problemGetData(probname, LimitReachedReader.datakey)
        objlimitreached = (limitreached == "objectiveLimit")
        optval = testrun.problemGetData(probname, "OptVal")
        objsense = testrun.problemGetData(probname, ObjsenseReader.datakey)
        solfound = True if pb is not None else False

        # the run failed because the primal or dual bound were better than the known optimal solution value
        if solfound and (self.isPrimalBoundBetter(testrun, probname) or self.isDualBoundBetter(testrun, probname)):
            testrun.addData(probname, 'Status', self.Status_FailObjectiveValue)

        # the run finished correctly if an objective limit was given and the solver reported infeasibility
        elif not solfound and objlimitreached:
            objlimit = testrun.problemGetData(probname, ObjlimitReader.datakey)
            reltol = 1e-5 * max(abs(optval), 1.0)

            if (objsense == ObjsenseReader.minimize and optval - objlimit >= -reltol) or \
                  (objsense == ObjsenseReader.maximize and objlimit - optval >= -reltol):
                testrun.addData(probname, 'Status', self.Status_Ok)
            else:
                testrun.addData(probname, 'Status', self.Status_FailObjectiveValue)
        # the solver reached a limit
        elif limitreached:
            testrun.addData(probname, 'Status', limitreached.lower())

        # the solver reached
        elif (db is None or misc.getGap(pb, db) < 1e-4) and not self.isPrimalBoundBetter(testrun, probname):
            testrun.addData(probname, 'Status', self.Status_Ok)
        else:
            testrun.addData(probname, 'Status', self.Status_Fail)

    def determineStatusForBestProblem(self, testrun, probname):
        """
        determine status for a problem for which we only know a best solution value
        """
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
        db = testrun.problemGetData(probname, DualBoundReader.datakey)
        limitreached = testrun.problemGetData(probname, LimitReachedReader.datakey)

        # we failed because dual bound is higher than the known value of a primal bound
        if self.isDualBoundBetter(testrun, probname):
            testrun.addData(probname, 'Status', self.Status_FailDualBound)

        # solving reached a limit
        elif limitreached:
            testrun.addData(probname, 'Status', limitreached.lower())
            if self.isPrimalBoundBetter(testrun, probname):
                testrun.addData(probname, 'Status', self.Status_Better)

        # primal and dual bound converged
        elif misc.getGap(pb, db) < 1e-4:
            testrun.addData(probname, 'Status', self.Status_SolvedNotVerified)
        else:
            testrun.addData(probname, 'Status', self.Status_Fail)

    def determineStatusForUnknProblem(self, testrun, probname):
        """
        determine status for a problem for which we don't know anything about the feasibility or optimality
        """
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
        db = testrun.problemGetData(probname, DualBoundReader.datakey)
        limitreached = testrun.problemGetData(probname, LimitReachedReader.datakey)

        if limitreached:
            testrun.addData(probname, 'Status', limitreached.lower())

            if pb is not None:
                testrun.addData(probname, 'Status', self.Status_Better)
        elif misc.getGap(pb, db) < 1e-4:
            testrun.addData(probname, 'Status', self.Status_SolvedNotVerified)
        else:
            testrun.addData(probname, 'Status', self.Status_Unknown)

    def determineStatusForInfProblem(self, testrun, probname):
        """
        determine status for a problem for which we know it's infeasible
        """
        pb = testrun.problemGetData(probname, PrimalBoundReader.datakey)
        solfound = True if pb is not None else False

        # no solution was found
        if not solfound:
            limitreached = testrun.problemGetData(probname, LimitReachedReader.datakey)
            if limitreached in ['TimeLimit', 'MemoryLimit', 'NodeLimit']:
                testrun.addData(probname, 'Status', limitreached.lower())
            else:
                testrun.addData(probname, 'Status', self.Status_Ok)
        # a solution was found, that's not good
        else:
            testrun.addData(probname, 'Status', self.Status_FailSolOnInfeasibleInstance)


    def checkProblemStatus(self):
        '''
        checks a problem solving status

        checks whether the solver's return status matches the information about the instances
        '''
        logging.debug('Checking problem status')
        for testrun in self.testrunmanager.getManageables():
            for probname in testrun.getProblems():
                solustatus = testrun.problemGetSoluFileStatus(probname)
                errcode = testrun.problemGetData(probname, ErrorFileReader.datakey)

                # an error code means that the instance aborted
                if errcode is not None or testrun.problemGetData(probname, SolvingTimeReader.datakey) is None:
                    testrun.addData(probname, 'Status', self.Status_FailAbort)

                # if the best solution was not feasible in the original problem, it's a fail
                elif testrun.problemGetData(probname, BestSolInfeasibleReader.datakey) == True:
                    testrun.addData(probname, 'Status', self.Status_FailSolInfeasible)

                # go through the possible solution statuses and determine the Status of the run accordingly
                elif solustatus == 'opt':
                    self.determineStatusForOptProblem(testrun, probname)
                elif solustatus == "best":
                    self.determineStatusForBestProblem(testrun, probname)
                elif solustatus == "inf":
                    self.determineStatusForInfProblem(testrun, probname)
                else:
                    self.determineStatusForUnknProblem(testrun, probname)

                logging.debug("Problem %s in testrun %s solustatus %s, errorcode %s -> Status %s" % (probname, testrun.getName(), repr(solustatus), repr(errcode), testrun.problemGetData(probname, "Status")))

    def saveToFile(self, filename):
        '''
           save the experiment instance to a file specified by 'filename'.
           Save comprises testruns and their collected data as well as custom built readers.

           @note: works for any file extension, preferred extension is '.cmp'
        '''

        print("Saving Data")
        if not filename.endswith(".cmp"):
            print("Preferred file extension for experiment instances is '.cmp'")

        try:
            f = open(filename, "wb")
        except IOError:
            print("Could not open file named", filename)
            return
        pickle.dump(self, f, protocol=2)

        f.close()

    @staticmethod
    def loadFromFile(filename):
        '''
        loads a experiment instance from the file specified by filename. This should work for all files
        generated by the saveToFile command.

        @return: a Experiment instance, or None if errors occured
        '''
        try:
            f = open(filename, "rb")
        except IOError:
            print("Could not open file named", filename)
            return
#      try:
        comp = pickle.load(f)
#      except:
#         print "Error occurred : Could not load experiment instance"
#         comp = None
        f.close()

        if not isinstance(comp, Experiment):
            print("the loaded data is not a experiment instance!")
            return None
        else:
            return comp

    def getDataPanel(self, onlyactive=False):
        """
        returns a pandas Data Panel of testrun data
        creates a panel from testrun data, using the testrun settings as key
        set onlyactive to True to only get active testruns as defined by the testrun manager
        """
        trdatadict = {tr.getSettings():tr.data for tr in self.testrunmanager.getManageables(onlyactive)}
        return Panel(trdatadict)
