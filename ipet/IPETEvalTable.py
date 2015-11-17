'''
Created on 24.02.2015

@author: Gregor Hendel
'''
import pandas as pd
from Aggregation import Aggregation
import xml.etree.ElementTree as ElementTree
from ipet.IPETFilter import IPETFilterGroup
import numpy
from ipet.Editable import Editable
from ipet.IpetNode import IpetNode

class IPETEvaluationColumn(Editable, IpetNode):

    nodetag = "Column"

    editableAttributes = ["name", "origcolname", "formatstr","transformfunc", "constant",
                 "nanrep", "minval", "maxval", "comp", "translevel", "regex"]

    possibletransformations = [None, "sum", "subtract", "divide", "log10", "log", "mean", "median", "std", "min", "max"]

    requiredOptions = {"origcolname":"datakey", "translevel":[0,1], "transformfunc":possibletransformations}

    def __init__(self, origcolname=None, name=None, formatstr=None, transformfunc=None, constant=None,
                 nanrep=None, minval=None, maxval=None, comp=None, regex=None, translevel=None):
        '''
        constructor of a column for the IPET evaluation

        Parameters
        ----------
        origcolname : column name in the original data frame
        name : column name that will be displayed for this column
        formatstr : a format string to define how the column gets printed, if no format

        transformfunc : a transformation function, that should be applied to all children
                        columns of this column recursively. See also the 'translevel' attribute

        constant : should this column represent a constant value?

        nanrep : replacement of nan-values for this column

        minval : a minimum value for all elements in this column

        maxval : a maximum value for all elements in this column

        comp : should a comparison for this column with the 'comp'-group be made? This will append one column per group with this column
               name and a 'Q'-Suffix. Use comp="default" if it should be compared with the setting 'default', if existent. Any nonexistent
               comp will be silently skipped

        regex : use for selecting a set of columns at once by including regular expression wildcards such as '*+?' etc.

        translevel : Specifies the level on which to apply the defined transformation for this column. Use translevel=0 to handle every instance
                     and group separately, and translevel=1 for an instance-wise transformation over all groups, e.g., the mean solving time
                     if five permutations were tested. Columns with translevel=1 are appended at the end of the instance-wise table
        '''

        self.origcolname = origcolname
        self.name = name

        self.formatstr = formatstr
        self.transformfunc = transformfunc
        self.constant = constant

        self.nanrep = nanrep
        self.minval = minval
        self.maxval = maxval
        self.translevel = translevel
        self.comp = comp
        self.regex = regex


        self.aggregations = []
        self.children = []

    def checkAttributes(self):
        if self.origcolname is None and self.regex is None and self.transformfunc is None and self.constant is None:
            raise AttributeError("Error constructing this column: No origcolname, regex, constant, or transformfunction specified")

    def addChild(self, child):
        if not self.acceptsAsChild(child):
            raise ValueError("Cannot accept child %s as child of a column node"%child)
        if child.__class__ is IPETEvaluationColumn:
            self.children.append(child)
        elif child.__class__ is Aggregation:
            self.aggregations.append(child)

    def getChildren(self):
        return self.children + self.aggregations

    def acceptsAsChild(self, child):
        return child.__class__ in (IPETEvaluationColumn, Aggregation)

    def removeChild(self, child):
        if child.__class__ is IPETEvaluationColumn:
            self.children.remove(child)
        elif child.__class__ is Aggregation:
            self.aggregations.remove(child)

    @staticmethod
    def getNodeTag():
        return IPETEvaluationColumn.nodetag

    def getEditableAttributes(self):
        return self.editableAttributes

    def getRequiredOptionsByAttribute(self, attr):
        return self.requiredOptions.get(attr, None)

    def getName(self):
        '''
        infer the name for this column

        if this column was constructed with a column name, the name is used
        else if this column represents an original column of the data frame,
        the original column name is used, otherwise, we construct an
        artificial name that represents how this column is constructed
        '''
        if self.name is not None:
            return self.name
        elif self.origcolname is not None:
            return self.origcolname
        elif self.constant is not None:
            return "Const_%s"%self.constant
        else:
            return self.transformfunc + ','.join((child.getName() for child in self.children))

    def parseValue(self, val):
        '''
        parse a value into an integer (prioritized) or float
        '''
        for conversion in [int, float]:
            try:
                return conversion(val)
            except:
                pass
        return None

    def parseConstant(self):
        '''
        parse the constant attribute, which is a string, into an integer (prioritized) or float
        '''
        return self.parseValue(self.constant)

    def addAggregation(self, agg):
        self.aggregations.append(agg)

    def getFormatString(self):
        return self.formatstr

    def getTransLevel(self):
        if self.translevel is None or int(self.translevel) == 0:
            return 0
        else:
            return 1

    def toXMLElem(self):
        '''
        convert this Column into an XML node
        '''

        # keep only non NAN elements
        myelements = {k:self.__dict__[k] for k in self.getEditableAttributes() if self.__dict__.get(k) is not None}


        me = ElementTree.Element(IPETEvaluationColumn.getNodeTag(), myelements)

        # iterate through children and aggregations and convert them to xml nodes
        for child in self.children:
            me.append(child.toXMLElem())

        for agg in self.aggregations:
            me.append(agg.toXMLElem())

        return me

    @staticmethod
    def processXMLElem(elem):

        if elem.tag == IPETEvaluationColumn.getNodeTag():
            column = IPETEvaluationColumn(**elem.attrib)
            for child in elem:
                if child.tag == 'Aggregation':
                    column.addAggregation(Aggregation.processXMLElem(child))
                elif child.tag == IPETEvaluationColumn.getNodeTag():
                    column.addChild(IPETEvaluationColumn.processXMLElem(child))
            return column

    def getColumnData(self, df):
        '''
        Retrieve the data associated with this column
        '''

        # if no children are associated with this column, it is either
        # a column represented in the data frame by an 'origcolname',
        # or a constant
        if len(self.children) == 0:
            if self.origcolname is not None:
                try:
                    result = df[self.origcolname]
                except KeyError, e:
                    print e
                    print "Could not retrieve data %s"%self.origcolname
                    #try to get data from the second data frame
                    
            elif self.regex is not None:
                result = df.filter(regex = self.regex)
            elif self.constant is not None:
                df[self.getName()] = self.parseConstant()
                result = df[self.getName()]
        else:
            # try to apply an element-wise transformation function to the children of this column
            transformfunc = getattr(numpy, self.transformfunc)

            # concatenate the children data into a new data frame object
            argdf = pd.concat([child.getColumnData(df) for child in self.children], axis=1)

            if self.getTransLevel() == 1:

                # group the whole table per instance #

                argdf = argdf.groupby(level=0)

                #determine the axis along which to apply the transformation later on
                applydict={}
            else:
                applydict=dict(axis=1)

            try:
                # try to directly apply the transformation function, this might fail for
                # some transformations, e.g., the 'divide'-function of numpy because it
                # requires two arguments instead of the series associated with each row
                result = argdf.apply(transformfunc, **applydict)
            except ValueError:

                # try to wrap things up in a temporary wrapper function that unpacks
                # the series argument into its single values
                def tmpwrapper(*args):
                    return transformfunc(*(args[0].values))

                # apply the wrapper function instead
                result = argdf.apply(tmpwrapper, **applydict)

        if self.nanrep is not None:
            nanrep = self.parseValue(self.nanrep)
            if nanrep is not None:
                result = result.fillna(nanrep)
            elif self.nanrep in df.columns:
                result = result.fillna(df[self.nanrep])
        if self.minval is not None:
            minval = self.parseValue(self.minval)
            if minval is not None:
                result = numpy.maximum(result, minval)
        if self.maxval is not None:
            maxval = self.parseValue(self.maxval)
            if maxval is not None:
                result = numpy.minimum(result, maxval)

        return result


    def getStatsTests(self):
        return [agg.getStatsTest() for agg in self.aggregations if agg.getStatsTest() is not None]


class FormatFunc:

    def __init__(self, formatstr):
        self.formatstr = formatstr[:]

    def beautify(self, x):
        return (self.formatstr%x)



class IPETEvaluation(Editable, IpetNode):
    '''
    evaluates for a comparator with given group keys, columns, and filter groups
    '''
    nodetag = "Evaluation"
    #todo put tex, csv etc. here as other possible streams for filter group output
    possiblestreams=['stdout', 'tex', 'txt', 'csv']
    DEFAULT_GROUPKEY="Settings"
    DEFAULT_DEFAULTGROUP="default"
    DEFAULT_COMPARECOLFORMAT="%.3f"
    ALLTOGETHER="_alltogether_"

    editableAttributes = ["groupkey", "defaultgroup", "evaluateoptauto", "sortlevel", "comparecolformat"]
    attributes2Options = {"evaluateoptauto":[True, False], "sortlevel":[0,1]}
    def __init__(self, groupkey=DEFAULT_GROUPKEY, defaultgroup=DEFAULT_DEFAULTGROUP, evaluateoptauto=True,
                 sortlevel=0, comparecolformat=DEFAULT_COMPARECOLFORMAT):
        '''
        constructs an Ipet-Evaluation

        Parameters
        ----------
        groupkey : the key by which groups should be built, eg, 'Settings'
        defaultgroup : the name of the default group
        evaluateoptauto : should optimal auto settings be calculated?
        sortlevel : level on which to base column sorting, '0' for group level, '1' for column level
        '''
        self.filtergroups = []
        self.groupkey = groupkey
        self.defaultgroup = defaultgroup
        self.comparecolformat = comparecolformat[:]
        self.columns = []
        self.evaluateoptauto = bool(evaluateoptauto)
        self.sortlevel = int(sortlevel)


    def getName(self):
        return self.nodetag

    def set_evaluateoptauto(self, evaluateoptauto):
        self.evaluateoptauto = bool(evaluateoptauto)

    def set_sortlevel(self, sortlevel):
        self.sortlevel = int(sortlevel)

    def setCompareColFormat(self, comparecolformat):
        self.comparecolformat = comparecolformat[:]

    @staticmethod
    def getNodeTag():
        return IPETEvaluation.nodetag

    def getEditableAttributes(self):
        return self.editableAttributes

    def getChildren(self):
        return self.columns + self.filtergroups
    

    def acceptsAsChild(self, child):
        return child.__class__ in (IPETEvaluationColumn, IPETFilterGroup)

    def addChild(self, child):
        if not self.acceptsAsChild(child):
            raise ValueError("Cannot accept child %s as child of an evaluation node"%child)
        if child.__class__ is IPETEvaluationColumn:
            self.columns.append(child)
        elif child.__class__ is IPETFilterGroup:
            self.filtergroups.append(child)

    def removeChild(self, child):
        if child.__class__ is IPETEvaluationColumn:
            self.columns.remove(child)
        elif child.__class__ is IPETFilterGroup:
            self.filtergroups.remove(child)

    def getRequiredOptionsByAttribute(self, attr):
        return self.attributes2Options.get(attr)

    def addFilterGroup(self, fg):
        self.filtergroups.append(fg)
    def removeFilterGroup(self, fg):
        self.filtergroups.remove(fg)

    def setGroupKey(self, gk):
        self.groupkey = gk


    def setDefaultGroup(self, dg):
        self.defaultgroup = dg

    def addColumn(self, col):
        self.columns.append(col)

    def removeColumn(self, col):
        self.columns.remove(col)

    def setEvaluateOptAuto(self, evaloptauto):
        '''
        should the evaluation calculate optimal auto settings?
        '''
        self.set_evaluateoptauto(evaloptauto)

    def reduceToColumns(self, df):
        usercolumns = []

        lvlonecols = [col for col in self.columns if col.getTransLevel() == 1]
        if len(lvlonecols) > 0:
            self.levelonedf = pd.concat([col.getColumnData(df) for col in lvlonecols], axis=1)
            self.levelonedf.columns = [col.getName() for col in lvlonecols]
        else:
            self.levelonedf = None
        #treat columns differently for level=0 and level=1
        for col in self.columns:
            if col.getTransLevel() == 0:
                df[col.getName()] = col.getColumnData(df)
                usercolumns.append(col.getName())

                if col.comp is not None and col.comp in df[self.groupkey].unique():
                    compcol = dict(list(df.groupby(self.groupkey)[col.getName()]))[col.comp]
                    df["_tmpcol_"] = compcol
                    df[col.getName() + "Q"] = df[col.getName()] / df["_tmpcol_"]
                    usercolumns.append(col.getName() + "Q")



        # concatenate level one columns into a new data frame and treat them as the altogether setting

        neededcolumns = [col for col in [self.groupkey, 'Status', 'SolvingTime', 'TimeLimit'] if col not in usercolumns]

        additionalfiltercolumns = []
        for fg in self.filtergroups:
            additionalfiltercolumns += fg.getNeededColumns(df)

        additionalfiltercolumns = list(set(additionalfiltercolumns))
        additionalfiltercolumns = [afc for afc in additionalfiltercolumns if afc not in set(usercolumns + neededcolumns)]

        result = df.loc[:,usercolumns + neededcolumns + additionalfiltercolumns]
        self.usercolumns = usercolumns
        return result

    def calculateNeededData(self, df):
        df['_solved_'] = (df.SolvingTime < df.TimeLimit) & (df.Status != 'fail') & (df.Status != 'abort')
        df['_time_'] = (df.Status == 'timelimit')
        df['_fail_'] = (df.Status == 'fail')
        df['_abort_'] = (df.Status == 'abort')
        df['_count_'] = 1
        df['_unkn_'] = (df.Status == 'unknown')
        df['ProblemNames'] = df.index

        return df

    def toXMLElem(self):
        me = ElementTree.Element(IPETEvaluation.getNodeTag(), {'groupkey':self.groupkey, 'defaultgroup':self.defaultgroup})
        for col in self.columns:
            me.append(col.toXMLElem())
        for fg in self.filtergroups:
            fgelem = fg.toXMLElem()
            me.append(fgelem)

        return me

    @staticmethod
    def fromXML(xmlstring):
        tree = ElementTree.fromstring(xmlstring)
        return IPETEvaluation.processXMLElem(tree)

    @staticmethod
    def fromXMLFile(xmlfilename):
        tree = ElementTree.parse(xmlfilename)
        return IPETEvaluation.processXMLElem(tree.getroot())

    @staticmethod
    def processXMLElem(elem):
        if elem.tag == IPETEvaluation.getNodeTag():
            ev = IPETEvaluation()
            ev.setGroupKey(elem.attrib.get('groupkey', IPETEvaluation.DEFAULT_GROUPKEY))
            ev.setDefaultGroup(elem.attrib.get('defaultgroup', IPETEvaluation.DEFAULT_DEFAULTGROUP))

        for child in elem:
            if child.tag == IPETFilterGroup.getNodeTag():
                # add the filter group to the list of filter groups
                fg = IPETFilterGroup.processXMLElem(child)
                ev.addFilterGroup(fg)

            elif child.tag == IPETEvaluationColumn.getNodeTag():
                ev.addColumn(IPETEvaluationColumn.processXMLElem(child))
        return ev

    def convertToHorizontalFormat(self, df):
        horidf = df[self.usercolumns + ['ProblemNames', self.groupkey]].pivot('ProblemNames', self.groupkey).swaplevel(0, 1, axis=1)
        horidf.sortlevel(axis=1, level=self.sortlevel)
        return horidf

    def checkStreamType(self, streamtype):
        if streamtype not in self.possiblestreams:
            return False
        else:
            return True

    def getColumnFormatters(self, df):
        '''
        returns a formatter dictionary for all columns of this data frame

        expects a Multiindex column data frame df
        '''
        formatters = {}

        thelevel = 0

        # temporary hack to test which level is the maximum level
        try:
            df.columns.get_level_values(1)
            thelevel = 1
        except IndexError, AttributeError:
            pass

        comptuples = []
        # loop over columns
        for col in self.columns:

            #determine all possible comparison columns and append them to the list
            try:
                if thelevel == 1:
                    comptuples += df.xs(col.getName() + 'Q', axis=1, level=thelevel, drop_level=False).columns.values.tolist()
                else:
                    comptuples += [dfcol for dfcol in df.columns if dfcol.startswith(col.getName()) and dfcol.endswith("Q")]
            except:
                pass

            # if the column has no formatstr attribute, continue
            if not col.getFormatString():
                continue

            # retrieve all columns as tuples that contain the column name, ie. for column 'Time' and
            # settings 'default' and 'heuroff', the result should be [('default', 'Time'),('heuroff', 'Time')]
            try:
                if thelevel == 1:
                    tuples = df.xs(col.getName(), axis=1, level=thelevel, drop_level=False).columns.values.tolist()

                else:
                    tuples = [dfcol for dfcol in df.columns if dfcol.startswith(col.getName()) and not dfcol.endswith("Q")]
            except KeyError:
                # the column name is not contained in the final df
                continue



            # add new formatting function to the map of formatting functions
            for thetuple in tuples:
                formatters.update({thetuple:FormatFunc(col.getFormatString()).beautify})


        for comptuple in comptuples:
            formatters.update({comptuple:FormatFunc(self.comparecolformat).beautify})

        return formatters

    def streamDataFrame(self, df, filebasename, streamtype):
        if not self.checkStreamType(streamtype):
            raise ValueError("Stream error: Unknown stream type %s"%streamtype)
        streammethod = getattr(self, "streamDataFrame_%s"%streamtype)

        formatters = self.getColumnFormatters(df)

        streammethod(df, filebasename, formatters)

    def streamDataFrame_stdout(self, df, filebasename, formatters = {}):
        '''
        print to console
        '''
        print "Data for %s:"%filebasename
        print df.to_string(formatters=formatters)

    def streamDataFrame_tex(self, df, filebasename, formatters = {}):
        '''
        write tex output
        '''
        with open("%s.tex"%filebasename, "w") as texfile:
            texfile.write(df.to_latex(formatters = formatters))

    def streamDataFrame_csv(self, df, filebasename, formatters = {}):
        with open("%s.csv"%filebasename, "w") as csvfile:
            df.to_csv(csvfile, formatters = formatters)

    def streamDataFrame_txt(self, df, filebasename, formatters = {}):
        '''
        write txt output
        '''
        with open("%s.txt"%filebasename, "w") as txtfile:
            df.to_string(txtfile, formatters = formatters)

    def findStatus(self, statuscol):
        uniques = set(statuscol.unique())
        for status in ["ok", "timelimit", "nodelimit", "memlimit", "unknown", "fail", "abort"]:
            if status in uniques:
                return status
        else:
            return statuscol.unique()[0]

    def calculateOptimalAutoSettings(self, df):
        '''
        calculate optimal auto settings instancewise
        '''
        aggfuncs = {'solved':numpy.max}
        print df.head(5)
        grouped = df.groupby(level=0)

        optstatus = grouped["Status"].apply(self.findStatus)
        opttime = grouped["SolvingTime"].apply(numpy.min)
        opttimelim = grouped["TimeLimit"].apply(numpy.mean)

        optdf = pd.concat([optstatus, opttime, opttimelim], axis=1)
        optdf[self.groupkey] = "OPT. AUTO"

        useroptdf = pd.concat([grouped[col].apply(numpy.min) for col in self.usercolumns if col not in ["Status", "SolvingTime", "TimeLimit"]], axis=1)
        optdf = pd.concat([optdf, useroptdf], axis=1)


        return optdf



    def evaluate(self, comp):
        '''
        evaluate the data of a Comparator instance comp

        Parameters
        ----------
        comp : a Comparator instance for which data has already been collected

        Returns
        -------
        rettab : an instance-wise table of the specified columns
        retagg : aggregated results for every filter group and every entry of the specified
        '''

        #data is concatenated along the rows and eventually extended by external data
        data = comp.getJoinedData()

        columndata = self.reduceToColumns(data)

        if self.evaluateoptauto:
            opt = self.calculateOptimalAutoSettings(columndata)
            columndata = pd.concat([columndata, opt])

        columndata = self.calculateNeededData(columndata)

        # compile a results table containing all instances
        ret = self.convertToHorizontalFormat(columndata)
        if self.levelonedf is not None:
            self.levelonedf.columns = pd.MultiIndex.from_product([[IPETEvaluation.ALLTOGETHER], self.levelonedf.columns])
            rettab = pd.concat([ret, self.levelonedf], axis=1)
        else:
            rettab = ret


        self.instance_wise = ret
        self.agg = self.aggregateToPivotTable(columndata)

        self.filtered_agg = {}
        self.filtered_instancewise = {}
        # filter column data and group by group key #
        for fg in self.filtergroups:
            # iterate through filter groups, thereby aggregating results for every group
            reduceddata = self.applyFilterGroup(columndata, fg)
            self.filtered_instancewise[fg.name] = self.convertToHorizontalFormat(reduceddata)
            self.filtered_agg[fg.name] = self.aggregateToPivotTable(reduceddata)

        if len(self.filtergroups) > 0:
            dfs = [self.filtered_agg[fg.name] for fg in self.filtergroups if not self.filtered_agg[fg.name].empty]
            names = [fg.name for fg in self.filtergroups if not self.filtered_agg[fg.name].empty]
            retagg = pd.concat(dfs, keys=names, names=['Group'])
        else:
            retagg = pd.DataFrame()

        return rettab, retagg
    '''
        for fg in self.filtergroups:
            self.applyFilterGroup(columndata, fg, comp)
    '''
    def applyFilterGroup(self, df, fg):
        return fg.filterDataFrame(df)

    def aggregateToPivotTable(self, df):
        # the general part sums up the number of instances falling into different categories
        generalpart = df[['_count_', '_solved_', '_time_', '_fail_', '_abort_', '_unkn_'] + [self.groupkey]].pivot_table(index=self.groupkey, aggfunc=sum)

        # test if there is any aggregation to be calculated
        hasaggregation = False
        stop = False
        for col in self.columns:
            for agg in col.aggregations:
                hasaggregation = True
                stop = True
                break
            if stop:
                break
        # if no aggregation was specified, print only the general part
        if not hasaggregation:
            return generalpart

        # column aggregations aggregate every column and every column aggregation
        colaggpart = pd.concat([df[[col.getName(), self.groupkey]].pivot_table(index=self.groupkey, aggfunc=agg.aggregate) for col in self.columns for agg in col.aggregations], axis=1)

        # rename the column aggregations
        colaggpart.columns = ['_'.join((col.getName(), agg.getName())) for col in self.columns for agg in col.aggregations]

        # determine the row in the aggregated table corresponding to the default group
        if self.defaultgroup in colaggpart.index:
            defaultrow = colaggpart.loc[self.defaultgroup, :]
        else:
            # if there is no default setting, take the first group as default group
            try:
                defaultrow = colaggpart.iloc[0, :]
            except:
                defaultrow = numpy.nan

        # determine quotients
        comppart = colaggpart / defaultrow
        comppart.columns = [col + 'Q' for col in colaggpart.columns]

        #apply statistical tests, whereever possible
        statspart = self.applyStatsTests(df)

        #glue the parts together
        parts = [generalpart, colaggpart, comppart]
        if statspart is not None:
            parts.append(statspart)

        return pd.concat(parts, axis = 1)

    def applyStatsTests(self, df):
        '''
        apply statistical tests defined by each column
        '''

        # group the data by the groupkey
        groupeddata = dict(list(df.groupby(self.groupkey)))
        stats = []
        names = []
        for col in self.columns:
            # iterate through the columns
            defaultvalues = None
            try:
                defaultvalues = groupeddata[self.defaultgroup][col.getName()]
            except KeyError:
                print "Sorry, cannot retrieve default values for column %s, key %s"%(col.getName(), self.defaultgroup)
                continue

            # iterate through the stats tests associated with each column
            for statstest in col.getStatsTests():
                stats.append(df[[self.groupkey, col.getName()]].pivot_table(index=self.groupkey, aggfunc=lambda x:statstest(x, defaultvalues)))
                names.append('_'.join((col.getName(), statstest.__name__)))

        if len(stats) > 0:
            stats = pd.concat(stats, axis=1)
            stats.columns = names

            return stats
        else:
            return None
    def aggregateTable(self, df):
        results = {}
        columnorder = []
        for col in self.columns:
            origcolname = col.getName()
            partialdf = df.xs(origcolname, level=1, axis=1, drop_level=False)

            for partialcol in partialdf.columns:
                columnorder.append(partialcol)
                results[partialcol] = {}
                for agg in col.aggregations:
                    results[partialcol][agg.getName()] = agg.aggregate(df[partialcol])

        return pd.DataFrame(results)[columnorder]

if __name__ == '__main__':
    ev = IPETEvaluation.fromXMLFile('../test/testevaluate.xml')
#     ev.addColumn(IPETEvaluationColumn('SolvingTime'))
#     ev.addColumn(IPETEvaluationColumn('Nodes'))
#     group = IPETFilterGroup('new')
#     filter1 = IPETFilter('SolvingTime', '0.01', 'ge', True)
#     filter2 = IPETFilter('Nodes', '10', 'le', True)
#     group.addFilter(filter1)
#     group.addFilter(filter2)
    agg = Aggregation('shmean', shiftby=10)
    #ev.columns[0].addAggregation(agg)
    #print ElementTree.tostring(agg.toXMLElem())

    from ipet.Comparator import Comparator
    comp = Comparator.loadFromFile('../test/.testcomp.cmp')
    comp.externaldata = None
    rettab, retagg = ev.evaluate(comp)
    print rettab.to_string()
    print retagg.to_string()
    xml = ev.toXMLElem()
    from xml.dom.minidom import parseString
    dom = parseString(ElementTree.tostring(xml))
    with open("myfile.xml", 'w') as myfile:
        myfile.write(dom.toprettyxml())
#     xml = ev.toXMLElem()
#     dom = parseString(ElementTree.tostring(xml))
#     print dom.toprettyxml()
#
