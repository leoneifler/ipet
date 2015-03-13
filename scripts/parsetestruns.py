'''
Created on 24.02.2015

@author: bzfhende
'''

from ipet.IpetApplication import IpetApplication
from ipet.Comparator import Comparator
from ipet.ReaderManager import ReaderManager
from ipet.TestRun import TestRun
import argparse
import sys
from ipet.IPETEvalTable import IPETEvaluation
import pandas as pd

# possible arguments in the form name,default,short,description #
clarguments = []

argparser = argparse.ArgumentParser(prog="Ipet Startup Script", \
                                 description="starts the IPET graphical user interface")
for name, default, short, description in clarguments:
    argparser.add_argument(short, name, default=default,help=description)

argparser.add_argument('outfiles', nargs='*', help="list of outfiles that should be parsed")
argparser.add_argument('-r','--readers', nargs='*', default=[], help="list of additional readers in xml format that should be used for parsing")
argparser.add_argument('-s','--solufiles', nargs='*', default=[], help="list of solu files that should be taken into account")


if __name__ == '__main__':
    try:
        n = vars(argparser.parse_args())
        globals().update(n)
    except:
        print "Wrong Usage"
    #if globals().get("help") is not None:
    print globals()
    if outfiles is None:
        print "We need out files"
        sys.exit(0)


    #initialize a comparator
    comparator = Comparator()

    for additionalfile in readers:
        rm = ReaderManager.fromXMLFile(additionalfile)
        for reader in rm.getManageables(False):
            comparator.readermanager.registerReader(reader)

    for outfile in outfiles:
        comparator.addLogFile(outfile)

    for solufile in solufiles:
        comparator.addSoluFile(solufile)

    comparator.collectData()

    for tr in comparator.testrunmanager.getManageables():
        tr.saveToFile("%s%s"%(tr.getIdentification(),TestRun.FILE_EXTENSION))
