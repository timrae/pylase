# Python imports
from __future__ import division
from hakkipaoli import HakkiPaoli, peakDetect, peakClean
import gainmedium
from numpy import *
from matplotlib import pyplot as pp
pp.ion()
from scipy import constants as scipycsts
import pylab
import sys,os,sqlite3,json,legacy,tables
import warnings
warnings.filterwarnings('ignore', category=tables.NaturalNameWarning)
from string import lower
import cPickle as pickle
from time import sleep, clock, time, strptime, mktime
from datetime import datetime
from scipy import io as scipyio, optimize, interpolate
from filter import savitzky_golay, smooth
from functools import partial
from multiprocessing import Pool, cpu_count
# QT imports
from PyQt4.QtCore import QCoreApplication,Qt,QTimer, QReadLocker
from PyQt4 import QtGui,QtCore
# Try to import visa library. Don't do anything if there is an import error since this is already dealt with in main
try:
    from drivepy import visaconnection
    NO_VISA=False
except (ImportError, WindowsError) as e:
    NO_VISA=True
# Import the rest of the instruments if visa library exists, otherwise don't bother since no real tests can be done without this library
if not NO_VISA:
    # SMU
    from drivepy.keithley.smu import SMU
    # Flags for instrument to use for power meters. Can take values ("Newport", "DMM", "Winspec", None)
    POWER_METERS={"primary":"Agilent","secondary":"Agilent","prealign":"Newport","roughAlign":"Agilent","fineAlign":"Agilent"}
       
    """ Import all the instruments which can be used as a power meter"""
    try:
        # Main Agilent power meter
        from drivepy.agilent.powermeter import PowerMeter as AgilentPowerMeter
    except Exception as e:
        print("Error: Agilent power meter could not be imported")
    try:
        # Newport power meter
        from drivepy.newport.powermeter import PowerMeter as NewportPowerMeter
    except Exception as e:
        print("Error: Newport power meter could not be imported")
    try:
        # Newfocus power meter via DMM
        from drivepy.newfocus.powermeter import PowerMeter as NewfocusPowerMeter
    except Exception as e:
        print("Error: Newfocus power meter could not be imported")
    try:
        # Winspec used as a power meter
        from winspecanalyzer import WinspecAnalyzer as WinspecPowerMeter
    except Exception as e:
        print("Error: Winspec power meter could not be imported")

    def getPowerMeterLib(flag):
        """ Return the intended module for the chosen power meter"""
        if flag=="Agilent": 
            return AgilentPowerMeter
        elif flag=="Newport": 
            return NewportPowerMeter
        elif flag=="Newfocus": 
            return NewfocusPowerMeter
        elif flag=="Winspec": 
            return WinspecPowerMeter
        else:
            print("Flag " + flag + " not found")

    PrimaryPowerMeter = getPowerMeterLib(POWER_METERS["primary"])
    SecondaryPowerMeter = getPowerMeterLib(POWER_METERS["secondary"])
    PrealignPowerMeter = getPowerMeterLib(POWER_METERS["prealign"])
    RoughAlignPowerMeter = getPowerMeterLib(POWER_METERS["roughAlign"])
    FineAlignPowerMeter = getPowerMeterLib(POWER_METERS["fineAlign"])


    from winspecanalyzer import WinspecAnalyzer, MAX_COUNTS
    from drivepy.anritsu.spectrumanalyzer import SpectrumAnalyzer
    from drivepy.keithley.dmm import DMM
    #from drivepy.advantest.spectrumanalyzer import SpectrumAnalyzer
    from drivepy.scientificinstruments.temperaturecontroller import TemperatureController
    from align import PiezoAlign, MotorAlign
    try:
        from drivepy.thorlabs.fw102c import FilterWheel
    except:
        pass
 
# Global variables
NO_TEMP_SENSOR=False                # Flag to remember if the user chose not to measure temperature
MAX_CPS_PER_NANOWATT_LOW_GAIN=50e3  # Assumption for max counts per second per nanowatt input with detector on low gain setting. Measure close to threshold.
SPECTRUM_TAU=1                      # Minimum time in ms to meas over necessary to average temporal effects
SPECTRUM_TAU_LOWTEMP=500            # Minimum time in ms to meas over necessary to average temporal effects with cryostat on
WINSPEC_MIN_EXPOSURE=1e-6           # Minimum exposure time possible in Winspec before problems occur (not the same as total measurement time above)
WINSPEC_MIN_EXPOSURE_HIGAIN=50e-3   # Minimum exposure time we want to use under high gain setting
WINSPEC_MAX_ACCUMULATIONS=2000      # Maximum number of accumulations in Winspec before errors start to occur
WINSPEC_DEFAULT_EXPOSURE=0.3        # Default exposure time for Winspec when we have no information to start with
WINSPEC_MAX_TEMPERATURE=-30         # Maximum detector temperature we can get reliable data from
WINSPEC_DEFAULT_EFFICIENCY=1.8e-13  # Default value for num input photons per detector count
ALIGNMENT_CURRENT=80e-3             # Current to set for the device when using autoalign
ALIGNMENT_TAU=400                   # Averaging time in ms for power meter measurements (normal conditions)
ALIGNMENT_TAU_LOWTEMP=500           # Averaging time in ms for power meter measurements (low temperature conditions)
ALIGNMENT_FINE_RES=0.50             # Resolution of search grid for fine alignment in um
ALIGNMENT_FINE_SPAN=1.0             # Half-span of search grid for fine alignment in um (1=> +/- 1um)
ALIGNMENT_FINE_CURRENT_DEFAULT=5e-3 # Current to set for the device when using autoalign with fine grid
ALIGNMENT_ROUGH_RES=0.002           # Resolution of search grid for rough alignment in mm
PRE_ALIGNMENT_ROUGH_RES=0.02        # Resolution of search grid for pre-align optimization in mm
PRE_ALIGNMENT_SEARCH_RES=0.04       # Resolution for signal search during pre-align in mm
PREALIGNMENT_SOFT_SEARCH_THRESH = 100e-9
ALIGNMENT_SIGNAL_SEARCH_RES=0.004   # Resolution for signal search in mm
ALIGNMENT_SIGNAL_SEARCH_THRESH=1e-6 # Power threshold for detected signal
ALIGNMENT_SOFT_SEARCH_THRESH=1e-9   # Power threshold before we even attempt optimization during signal search
FEEDBACK_CALIBRATION_CURRENT=60e-3  # Drive current used when calibrating the feedback amount for RIN
LIV_TAU=20                          # Averaging time in ms for power meter measurements (normal conditions)
LIV_TAU_LOWTEMP=500                 # Averaging time in ms for power meter measurements (low temperature conditions)
LIV_MIN_MAX_POWER=0.5e-6              # The threshold for max(power), below which the measurement is considered unsuccessful
LOWTEMP_THRESHOLD=295               # Temperature in Kelvin, below which we assume the cryostat is on and use a longer measurement time to average vibration
SPECTRUM_MIN_CURRENT=0.01e-3         # Currents below this point will be clipped
MIN_REALIGNMENT_TIME=15             # Minimum time before re-checking the alignment (minutes)
RIN_MIN_FREQ=500e6                  # Lower cutoff frequency for RIN plotting and noise floor calculation
AUTO_ALIGN=False
__DBPATH__=None                     # Path to the database file

class Session(QtCore.QObject):
    finished=QtCore.pyqtSignal()
    finishedPlottingSignal=QtCore.pyqtSignal()
    plotDataReady=QtCore.pyqtSignal(dict)
    progress=QtCore.pyqtSignal(float)
    plotProgress=QtCore.pyqtSignal(float)
    aborted=QtCore.pyqtSignal()
    """ Measurement 'session' is a group that holds all the measurements and talks to the database etc """
    def __init__(self,newDB,fname,parent=None):
        self.main=parent
        super(Session, self).__init__()
        self.activeMeasList=None
        if lower(os.path.splitext(fname)[-1])==".db":
            # support opening of legacy db files if they have the *.db extension
            self.db=db=sqlite3.connect(fname)
            h5fname=os.path.splitext(fname)[0]+".h5"
            if os.path.exists(h5fname):
                raise DatabaseWriteException, "Please delete or rename the file '" + h5fname + "' so that the selected legacy .db sqlite database can be converted to HDF5."
            else:
                self.h5db=tables.openFile(h5fname, mode = "w")               
        else:
            # Treat all other files as HDF5 files, or more generally as pytables files (the default extension is h5). Open in append mode so that any existing data isn't overwritten.
            if newDB:
                self.db=db=tables.openFile(fname, mode = "w")
            else:
                self.db=db=tables.openFile(fname, mode = "a")

        if not db:
            # Exit the application if there was an error opening the database for some reason
            QtGui.QMessageBox.warning(None,"Database Error",("There was a database error... exiting the application"))
            sys.exit(1)
        if newDB:
            # create new database
            self.initializeDatabase_()
            self.measurements=[]
        else:
            # open existing database
            self.measurements=self.fetchAllMeasurements()
        # set global variable for the database directory
        global __DBPATH__
        __DBPATH__=os.path.normpath(fname)
    def __del__(self):
        """ Close the database when the session object is deleted """
        self.db.close()
    def plot(self,groupName=None,plotType=None):
        """ Plots the threshold current vs temperature """
        self.plotProgress.emit(0)
        # choose a default plot type if none was specified
        if plotType is None:
            if isinstance(self.activeMeasList[0], LIV): 
                plotType="ThresholdCurrent"
            elif isinstance(self.activeMeasList[0], RinSpectrum):
                plotType="PeakRIN"
            elif isinstance(self.activeMeasList[0], Spectrum):
                plotType="LasingWavelength"
            else: 
                plotType="ThresholdCurrent"
        # Get the list of current measurements sorted by temperature
        measList=self.sortByTemperature() if self.activeMeasList is None else self.sortByTemperature(self.activeMeasList)
        # Generate plot dictionaries according to specified plotType for compatible measurement types
        if plotType=="ThresholdCurrent":
            tree=self.getMeasTree()
            xAll=[]
            yAll=[]
            legendStrings=[]
            # Extract the LIV data for each group and get plot data vs. temperature
            for group in (tree if groupName is None else [groupName,]):
                #if tree[group].has_key("LIV") and group in ['QD Laser Unit 5097','QD Laser Unit 5098','QD Laser Unit 5781','QD Laser Unit 5782']:
                if tree[group].has_key("LIV"):
                    #livMeas=self.getEnabled(self.sortByTemperature(tree[group]["LIV"]))
                    livMeas=self.getEnabled(self.sortByTime(tree[group]["LIV"]))
                    x=array([mean(m.data["temperature"]) for m in livMeas])
                    y=array([m.getThresholdCurrent()[0] for m in livMeas])*1e3
                    xAll.append(x)
                    yAll.append(y)
                    legendStrings.append(group)
            # legendStrings=["8 layers", "8 layers", "6 layers", "7 layers", "6 layers", "7 layers"]
            xAxis={"data":tuple(xAll),"label":"Temperature [K]"}
            yAxis={"data":tuple(yAll),"lineProp":tuple(["x-" for x in xAll]),"label":"Threshold Current [mA]", "legend":legendStrings}
            plotDictionary={"x":xAxis,"y":yAxis,"title":"Threshold current vs temperature"}
        elif plotType=="LasingWavelength":
            # Lasing wavelength vs temperature plot
            tree=self.getMeasTree()
            xAll=[]
            yAll=[]
            legendStrings=[]
            # Extract the lasing wavelength data for each group and get plot data vs. temperature
            for group in (tree if groupName is None else [groupName,]):
                if tree[group].has_key("WinspecGainSpectrum") and group in ['QD Laser Unit 5097','QD Laser Unit 5098','QD Laser Unit 5781','QD Laser Unit 5782']:
                    specMeas=self.getEnabled(self.sortByTemperature(tree[group]["WinspecGainSpectrum"]))
                    x=array([mean(m.data["temperature"]) for m in specMeas])
                    y=array([m.getLasingWavelength() for m in specMeas])*1e9
                    xAll.append(x)
                    yAll.append(y)
                    legendStrings.append(group)
            # legendStrings=["8 layers", "8 layers", "6 layers", "7 layers", "6 layers", "7 layers"]
            xAxis={"data":tuple(xAll),"label":"Temperature [K]"}
            yAxis={"data":tuple(yAll),"lineProp":tuple(["x-" for x in xAll]),"label":"Lasing Wavelength [nm]", "legend":legendStrings}
            plotDictionary={"x":xAxis,"y":yAxis,"title":"Lasing wavelength vs temperature"}
        elif plotType=="PeakGainEnergy" or plotType=="PeakGainEnergyDelta":
            # Difference in energy between the absorption peak at lowest current and gain peak at max current vs temperature
            gainMeas=self.dataByClassHandle(WinspecGainSpectrum,measList)
            outArgs=[m.getAllGainPeakEnergies() for m in gainMeas]
            # Separate the currents and the gain peak positions
            xraw=[xy[0] for xy in outArgs]
            yraw=[xy[1] for xy in outArgs]
            # If there is a NaN value in any of the peak energy values, then remove it and the corresponding current value
            current=tuple([xraw[idx][logical_not(isnan(yraw[idx]))] for idx in range(len(xraw))])
            peakEnergy=tuple([yi[logical_not(isnan(yi))] for yi in yraw])
            temperature=array([mean(m.data["temperature"]) for m in gainMeas])
            # Make the plotDictionary
            if plotType=="PeakGainEnergyDelta":
                x=temperature
                y=array([(yi.max()-yi.min())*1e3 if len(yi) >1 else nan for yi in peakEnergy])
                xAxis={"data":(x,),"label":"Temperature [K]"}
                yAxis={"data":(y,),"lineProp":('x-',),"label":"Max gain peak energy difference [meV]"}
                plotDictionary={"x":xAxis,"y":yAxis,"title":"Threshold gain energy shift vs temperature"}
            else:
                x=current
                y=peakEnergy
                legend=["{:0.1f}".format(T)+"K" for T in temperature]
                lineProp=tuple(["x-" for idx in range(len(y))])
                xAxis={"data":x,"label":"I/$I_{th}$"}
                yAxis={"data":y,"lineProp":lineProp,"label":"Gain peak energy [meV]","legend":legend}
                plotDictionary={"x":xAxis,"y":yAxis,"title":"Threshold gain energy shift vs current and temperature"}
        elif plotType=="PeakRIN":
            rinMeas=self.dataByClassHandle(RinSpectrum,measList)
            feedback=[]
            peakRin=[]
            # Get list of all unique current set points in set of measurements
            current=unique(hstack(array([linspace(m.info["Istart"],m.info["Istop"],m.info["numCurrPoints"]) for m in rinMeas])))
            # Get all feedback levels
            feedback=array([10*log10(m.data["feedbackAmount"]) if "feedbackAmount" in m.data else NaN for m in rinMeas])
            # Sort measurement list by feedback level
            sortIdx=feedback.argsort()
            feedback=feedback[sortIdx]
            rinMeas=[rinMeas[i] for i in sortIdx]
            # Create array of peak RIN for each current and feedback level
            for m in rinMeas:
                # Calculate start index to trim all frequencies below RIN_MIN_FREQ
                s=where(m.data["wavelength"] >= RIN_MIN_FREQ)[0][0]
                # Get current set points for current meas
                ism=linspace(m.info["Istart"],m.info["Istop"],m.info["numCurrPoints"])
                # Calculate peak rin at each current in allCurr, setting a dummy value if the current value wasn't included in m
                peakRinIdx=[]
                for idx in range(len(current)):
                    try:
                        idx2=where(ism==current[idx])[0][0]
                        rin=m.powerDensityToRin(m.data["intensity"][s:,idx2],m.data["thermalNoisePower"][s:],m.data["photoCurrent"][idx2])
                        peakRinIdx.append(max(rin))
                    except IndexError:
                        peakRinIdx.append(NaN)
                # Append to main arrays
                peakRin.append(array(peakRinIdx))
            # Convert to numpy arrays
            feedback=array(feedback)-6-8
            peakRin=array(peakRin)
            # Make plot dictionary
            x=tuple(tile(feedback,(len(current),1)))
            y=tuple(transpose(peakRin))
            legend=["{:0.0f}".format(i*1000)+"mA" for i in current]
            lineProp=tuple(["x-" for idx in range(len(y))])
            xAxis={"data":x,"label":"Feedback amount (dB)"}
            yAxis={"data":y,"lineProp":lineProp,"label":"Peak RIN (dB/Hz)","legend":legend}
            plotDictionary={"x":xAxis,"y":yAxis,"title":"Peak RIN vs feedback level at varying currents"}
        else:
            return
        # Emit a signal with data dictionary for the GUI to know what to plot
        self.plotProgress.emit(100)
        self.plotDataReady.emit(plotDictionary)

    def initializeDatabase_(self):
        """ Initializes the database. Doesn't do anything atm but could specify a table structure in the future if necessary """
        pass

    def fetchAllMeasurements(self):
        """ Fetch all the data from the database, and convert into list of measurements """
        measObjects=[]
        if type(self.db)==sqlite3.Connection:
            # Allow loading of data from legacy sqlite database
            measObjects=legacy.fetchAllMeasurements(self)
            self.db=self.h5db
            self.measurements=measObjects
            self.saveToDB()
            # Save the imported data as an h5 database and replace self.db with this new database
        else:
            # Traverse first 3 levels of file heirarchy assuming pytables group structure in format \groupName\testType\testName\
            groupNameDic=self.db.root._v_children
            for groupName in groupNameDic:
                testTypeDic=groupNameDic[groupName]._v_children
                for testType in testTypeDic:
                    testNameDic=testTypeDic[testType]._v_children
                    for testName in testNameDic:
                        # Put all the user attributes into the info dictionary
                        attrs=testNameDic[testName]._v_attrs
                        infoDic={}
                        for attrName in attrs._v_attrnamesuser:
                            infoDic[attrName]=attrs[attrName]
                        # Create an empty object of the specified test type if there is no "deleted" attribute set to true
                        if not infoDic.get("deleted",False):
                            if testType=="LIV":
                                meas=LIV(infoDic,dummy=False,parent=self.main)
                            elif testType=="Spectrum":
                                # This is a hack for backwards compatibility
                                meas=WinspecGainSpectrum(infoDic,dummy=False,parent=self.main)
                                meas.info["type"]="WinspecGainSpectrum"
                            elif testType=="AdvantestSpectrum":
                                # This is a hack for backwards compatibility
                                meas=AdvantestSpectrum(infoDic,dummy=False,parent=self.main)
                            elif testType=="WinspecSpectrum":
                                # This is a hack for backwards compatibility
                                meas=WinspecSpectrum(infoDic,dummy=False,parent=self.main)
                            elif testType=="WinspecGainSpectrum":
                                # This is a hack for backwards compatibility
                                meas=WinspecGainSpectrum(infoDic,dummy=False,parent=self.main)
                            elif testType=="ManualWinspecSpectrum":
                                # This is a hack for backwards compatibility
                                meas=WinspecGainSpectrum(infoDic,dummy=False,parent=self.main)
                            elif testType=="RinSpectrum":
                                meas=RinSpectrum(infoDic,dummy=False,parent=self.main)
                            else:
                                raise Exception, "An unknown test type was specified in the HDF5 database"
                            # Assume there's a folder called "data" and set each child data node as an attribute of the measurement object
                            #dataNodeDic=testNameDic[testName].data._v_children
                            for dataNodeName in groupNameDic[groupName]._v_children[testType]._v_children[testName].data._v_children:
                                #meas.data[dataNodeName]=dataNodeDic[dataNodeName][:]
                                dataNodeObj=groupNameDic[groupName]._v_children[testType]._v_children[testName].data._v_children[dataNodeName].read()
                                meas.data[dataNodeName]=dataNodeObj
                                # The below approach doesn't work well when the number of measurement points is set to 1
                                #if dataNodeObj.size>1:
                                #    meas.data[dataNodeName]=dataNodeObj
                                #else:
                                #    meas.data[dataNodeName]=float(dataNodeObj)


                            # Append the newly created measurement object to the main list
                            measObjects.append(meas)
        return measObjects

    def getMeasTree(self,measObject=None):
        """ Convert self.measurements list into a dictionary representing the object hierarchy """       
        measDic={}
        # Create some empty dictionaries to hold the parents for items at each level on the tree
        parentFromGroup = {}
        parentFromGroupType = {}
        parentFromGroupTypeName = {}
        # Get the list of all the measurement objects in the current session
        allMeasurements=self.measurements if measObject is None else [measObject]
        # From the top to the bottom of the tree, create QTreeWidgetItems and fill the dictionary with parent info
        for meas in allMeasurements:
            # Get the top level characteristics from the object
            groupName=meas.info["groupName"]
            typeName=meas.info["type"]
            testID=meas.getID()
            if groupName not in measDic:
                measDic[groupName]={}
            if typeName not in measDic[groupName]:
                measDic[groupName][typeName]={}
            measDic[groupName][typeName][testID]=meas
        return measDic

    def saveToDB(self,measObject=None):
        """ Saves the current list of measurements to the database """
        measDic=self.getMeasTree(measObject)
        for groupName in measDic:
            for typeName in measDic[groupName]:
                for testId in measDic[groupName][typeName]:
                    # create a new group called groupName if it doesn't already exist
                    if groupName not in self.db.root._v_children:
                        groupNode=self.db.createGroup(self.db.root,groupName)
                    else:
                        groupNode=self.db.getNode(self.db.root,groupName)
                    # create a new group called typeName if it doesn't already exist
                    if typeName not in groupNode._v_children:
                        typeNode=self.db.createGroup(groupNode,typeName)
                    else:
                        typeNode=self.db.getNode(groupNode,typeName)
                    # create a new group for the testID if it doesn't already exist                  
                    if testId not in typeNode._v_children:
                        measNode=self.db.createGroup(typeNode,testId)
                        # Create a new group for the data
                        dataNode=self.db.createGroup(measNode,"data")
                        # Add all of the members of the data dictionary as arrays in dataNode
                        data=measDic[groupName][typeName][testId].data
                        for dataName in data:
                            if data!=None:
                                try:
                                    self.db.createArray(dataNode,dataName,data[dataName])
                                except:
                                    pass
                    else:
                        measNode=self.db.getNode(typeNode,testId)
                    # Set all of the members of the info dictionary as attributes of measNode (overwriting any existing attributes)
                    info=measDic[groupName][typeName][testId].info
                    for attrName in info:
                        self.db.setNodeAttr(measNode,attrName,info[attrName])
        # force changes to be commited
        self.db.flush()


    def saveAs(self,groupName):
        # This needs to export the threshold current vs temperature for LIV data with groupName as well as raw data for .mat and .pickle
        pass
    def convertToStr(self,input):
        """ converts the json.loads objects from unicode names to str """
        if isinstance(input, dict):
            #return {self.convertToStr(key): self.convertToStr(value) for key, value in input.iteritems()}
            return {self.convertToStr(key): value for key, value in input.iteritems()}
        elif isinstance(input, list):
            return [self.convertToStr(element) for element in input]
        elif isinstance(input, unicode):
            return input.encode('utf-8')
        else:
            return input
    def toFloatOrNull(self,QVariantNumber):
        """ Convenience function returns a float if QVariant valid, otherwise None """
        temp=QVariantNumber.toFloat()
        x=temp[0] if temp[1] else None
        return x
    def unserializeArray(self,numpyVector,sizeTuple):
        """ Reverses the function of Spectrum.serializeArray() for getting the data back from the database into a matrix """
        return reshape(numpyVector,(sizeTuple[1],sizeTuple[0])).transpose()
    def getGroupNames(self):
        """ Convenience function which returns array of all the measurement groupNames in the session """
        groupNames=[]
        for m in self.measurements:
            groupNames.append(m.info["groupName"])
        return list(set(groupNames))
    def append(self,m):
        self.measurements.append(m)

    def dataByMeasType(self,measType,measList=None):
        """ Return all active measurements matching measType """
        if measList is None: measList=self.measurements
        outList=[]
        for m in measList:
            if m.info["type"]==measType and m.info["enabled"]:
                outList.append(m)
        return outList

    def dataByClassHandle(self,classHandle,measList=None):
        """ Return all active measurements inheriting from classHandle """
        if measList is None: measList=self.measurements
        outList=[]
        for m in measList:
            if isinstance(m,classHandle) and m.info["enabled"]:
                outList.append(m)
        return outList

    def sortByTemperature(self,measList=None):
        """ Return all the measurements in optional measList sorted by temperature"""
        if measList is None: measList=self.measurements
        try:
            # measList is dictionary / tree structure
            measList=[measList[m] for m in measList]
        except TypeError:
            pass
        temp=array([mean(m.data["temperature"]) for m in measList])
        sortIdx=temp.argsort()
        return [measList[idx] for idx in sortIdx]

    def sortByTime(self, measList=None):
        """ Return all the measurements in optional measList sorted by creation time"""
        if measList is None: measList=self.measurements
        try:
            # measList is dictionary / tree structure
            measList=[measList[m] for m in measList]
        except TypeError:
            pass
        t=array([mktime(strptime(m.info["creationTime"], "%Y-%m-%d %H:%M:%S")) for m in measList])
        sortIdx=t.argsort()
        return [measList[idx] for idx in sortIdx]

    def getEnabled(self,measList):
        """ Return only the enabled tests from measList """
        try:
            # measList is dictionary / tree structure
            measList=[measList[m] for m in measList]
        except TypeError:
            pass
        outList=[]
        for m in measList:
            if m.info["enabled"]:
                outList.append(m)
        return outList


    def dataByTimestamp(self,measType=None):
        """ Return array of all the measurements sorted by timestamp, optionally limited to a certain measurement type, 
        with the type specified by the string in the info dictionary "type" field """
        timeStamps=[strptime(m.info["creationTime"],"%Y-%m-%d %H:%M:%S") for m in self.measurements]
        measSorted=[self.measurements[i[0]] for i in sorted(enumerate(timeStamps), key=lambda x:x[1])]
        if measType!=None:
            isType=array([m.info["type"]==measType for m in measSorted])
            return array(measSorted)[isType]
        return array(measSorted)

class DatabaseWriteException(Exception): pass

class Measurement(QtCore.QObject):
    """Super class for all laser measurement types"""
    # pyqt signals (mainly for multithreading purposes)
    finished=QtCore.pyqtSignal()
    finishedPlottingSignal=QtCore.pyqtSignal()
    plotDataReady=QtCore.pyqtSignal(dict)
    progress=QtCore.pyqtSignal(float)
    progressMessage=QtCore.pyqtSignal(str)
    plotProgress=QtCore.pyqtSignal(float)
    aborted=QtCore.pyqtSignal()
    measError=QtCore.pyqtSignal(str)
    # hold main data in numpy.ndarray
    def __init__(self,info,dummy,parent=None,lock=None):
        super(Measurement, self).__init__()
        self.main=parent
        self.DUMMY_MODE=dummy
        self.info=info
        self.data={}
        if "creationTime" not in self.info:
            self.info["creationTime"]=str(datetime.now().replace(microsecond=0))
        if "enabled" not in self.info:
            self.info["enabled"]=True
        self.fitParameters=None
        self.running=True
        self.rendering=False
        self.cryostatOff=False
        self.lock=lock
        # Do rough align if specified
        self.preAlignFlag=self.info.get("preAlign",True)
        self.roughAlignFlag=self.info.get("roughAlign",False)
        self.fineAlignFlag=self.info.get("fineAlign",False)
        # Set filter wheel position to 1
        try:
            attentuator=FilterWheel()
            attenuator.setPosition(1)
            del attenuator
        except:
            pass

    @QtCore.pyqtSlot()
    def canceled(self):
        """ Slot which cancels the measurement """
        self.running=False
    @QtCore.pyqtSlot()
    def readyToDraw(self):
        """ Slot which allows the figure canvas to say when it's ready to draw again """
        self.rendering=False
    @QtCore.pyqtSlot(float)
    def subProgressAvailable(self,subprogress):
        """ Slot which accepts subprogress from subroutines """
        self.sendProgress(self.mainProgress+self.mainProgressStep*subprogress)
    @QtCore.pyqtSlot(float)
    def plotSubProgressAvailable(self,subprogress):
        """ Slot which accepts subprogress from subroutines """
        self.sendPlotProgress(self.mainPlotProgress+self.mainPlotProgressStep*subprogress)
    def finishedWork(self):
        """ Ensure the thread has been moved back to its parent and emit the finished signal """
        self.moveToThread(self.main.thread())
        self.finished.emit()
    def finishedPlotting(self):
        """ Ensure the thread has been moved back to its parent and emit the finished signal """
        self.moveToThread(self.main.thread())
        self.finishedPlottingSignal.emit()

    def getID(self):
        """ Returns a human intelligible unique ID for usage in the database"""
        return self.info["Name"]+" "+self.info["creationTime"]
        
       
    def roughAlign(self, preAlign = True):
        smu = self._setAlignmentCurrent()
        pm = RoughAlignPowerMeter()
        motorAlignObject=MotorAlign()
        if preAlign:
            # If the rough align power meter is below the search threshold then use a pre-align to get the interesting search range
            if pm.readPowerAuto(mode='max') < ALIGNMENT_SIGNAL_SEARCH_THRESH: 
                xm, xM, ym, yM = self._preAlign(motorAlignObject)
                span = max((xM - xm)/2, (yM - ym)/2)
            else:
                span = None
        self.sendStatusMessage("\nMain align (rough):\n")
        self._roughAlign(motorAlignObject, pm, ALIGNMENT_SIGNAL_SEARCH_RES, ALIGNMENT_ROUGH_RES, ALIGNMENT_SIGNAL_SEARCH_THRESH, ALIGNMENT_SOFT_SEARCH_THRESH, span = span)

    def _setAlignmentCurrent(self):
        smu = SMU()
        smu.setCurrent(ALIGNMENT_CURRENT)
        smu.setOutputState("ON")
        return smu    
        
    def _preAlign(self, motorAlignObject):
        """ If there is a power meter in front of the fiber / spatial filter and we don't have first light yet,
        a pre-align should be done to figure out the range that we should search over """
        def scan(chan, sign):
            # Move in steps of 50um away from pre-align peak to find valid scan range
            pos = p[chan]
            motorAlignObject.moveTo(p)
            while pm.readPowerAuto() > preAlignPower*0.75:
                pos += sign*PRE_ALIGNMENT_SEARCH_RES
                motorAlignObject.move1d(chan, pos)
            return pos        
        self.sendStatusMessage("Prealign:\n")
        pm = PrealignPowerMeter()
        p, preAlignPower = self._roughAlign(motorAlignObject, pm, PRE_ALIGNMENT_SEARCH_RES, PRE_ALIGNMENT_ROUGH_RES, ALIGNMENT_SIGNAL_SEARCH_THRESH, PREALIGNMENT_SOFT_SEARCH_THRESH)
        self.sendStatusMessage("Pre align power meter measured %f uW"%(preAlignPower*1e6))
        limits = (scan(0, -1), scan(0, 1), scan(1, -1), scan(1, 1))
        self.sendStatusMessage("Pre align determined scan range: x: (%f, %f) y: (%f, %f)"%limits)
        return limits

    def _roughAlign(self, motorAlignObject, pm, searchRes, res, threshold, softThreshold = None, span = None):
        """ Run findFirstSignal() and then do a rough align """
        self.sendStatusMessage("Initializing motor controller...")
        # Search for the first sign of signal over wide coarse grid using motor controller
        self.sendStatusMessage("Searching for the signal...")
        p0=self.main.motorCoordinates
        profitFunc=lambda : pm.readPowerAuto(tau=1,mode="max")
        p,power=motorAlignObject.findFirstSignal(p0,res=searchRes,profitFunction=profitFunc,threshold=threshold, span = span, softThreshold = softThreshold)
        with QReadLocker(self.lock):
            self.main.motorCoordinates=p
        # Rough align to get the rough optimum position over wide but coarse grid
        self.sendStatusMessage("Signal found at "+"(%.3f,%.3f)"%p+"mm.\nNow performing rough alignment...")
        tau=ALIGNMENT_TAU if self.cryostatOff else ALIGNMENT_TAU_LOWTEMP
        p0=p
        profitFunc=lambda : pm.readPowerAuto(tau=tau)
        p,power=motorAlignObject.autoalign(p0,res=res,profitFunction=profitFunc)
        with QReadLocker(self.lock):
            self.main.motorCoordinates=p
        settings=QtCore.QSettings()
        settings.setValue("MotorCoordinates",p)
        self.sendStatusMessage("Rough alignment completed with peak at "+"(%.3f,%.3f)"%p+"mm.")
        return p, power

    def fineAlign(self, piezoAlignObject = None, smu = None):
        """ Perform a fine alignment using the piezoelectric actuators, and only the power as the optimization conditions"""
        self.sendStatusMessage("Doing fine align with power meter and piezo actuators...")
        alignmentCurrent=self.info.get("fineAlignCurrent",ALIGNMENT_CURRENT)
        if smu is None: smu = SMU()
        if piezoAlignObject is None:
            if self.piezoAlignObject is None:
                piezoAlignObject=PiezoAlign()
            else:
                piezoAlignObject = self.piezoAlignObject
        pm=FineAlignPowerMeter()
        smu.setCurrent(alignmentCurrent)
        p0=self.main.piezoCoordinates
        tau=ALIGNMENT_TAU if self.cryostatOff else ALIGNMENT_TAU_LOWTEMP
        profitFunc=lambda : pm.readPowerAuto(tau=tau)
        p,power=piezoAlignObject.autoalign(p0,ALIGNMENT_FINE_RES,ALIGNMENT_FINE_SPAN,profitFunction=profitFunc)
        with QReadLocker(self.lock):
            self.main.piezoCoordinates=p
        self.sendStatusMessage("Fine alignment completed with peak at "+"(%.3f,%.3f)"%p+"um.")
        #del PiezoAlignObject, smu, profitFunc

    def initTempController(self):
        """ Initializes the temperature controller. """
        # NEED TO ACCESS THE TEMPERATURE THROUGH THE SAME INTERFACE AS THE TEMPERATURE WIDGET!!!
        if not self.main.tempController is None:
            self.tempController=self.main.tempController
        else:
            try:
                self.tempController=TemperatureController()
            except IOError, e:
                reply=QtGui.QMessageBox.question(None,"Do you want to proceed?","There was an IO communication error with the temperature controller. Do you want to proceed without measuring the temperature for the rest of this session?",QtGui.QMessageBox.Yes|QtGui.QMessageBox.No)
                if reply==QtGui.QMessageBox.Yes:
                    self.tempController=None
                    global NO_TEMP_SENSOR
                    NO_TEMP_SENSOR=True
                elif reply==QtGui.QMessageBox.No:
                    QtGui.QMessageBox.warning(None,"VisaIOError",("Please check that the temperature controller is turned on and connected properly:\n %1").arg(e.args[0]))
                    raise MeasurementAbortedError

    def serializeArray(self,numpyArray):
        """ Serializes numpy array into vector for database """
        return reshape(numpyArray.transpose(),-1)
    def tileVector(self,numpyVector,m):
        """ Tiles a numpy vector into repeated vector for database """
        #return tile(numpyVector,(m,1)).transpose()
        return reshape(tile(numpyVector,(m,1)).transpose(),-1)
    def gridVector(self,numpyVector,m):
        """ Tiles a numpy vector into a repeated grid for plotting """
        return tile(numpyVector,(m,1))

    def dataSummary(self):
        """ Returns a list of tuples which summarizes the test data via strings in a logically structured way. Format example is as follows:
        [([data1_col1,data1_col2],),([data2_col1,data2_col2],optionsDictionary: {"isCheckable":True,"clickMethod":meas.plot}),([data1_col1,data1_col2],childDataList: [(dataLabel4,data4),(dataLabel5,data5)])] """
        toStr=self.numToString # method in parent class which converts float,int,list,numpy.ndarray,str to string
        dataSummaryList=[]
        dataSummaryList.append((["Enabled"],{"isCheckable":True,"isChecked":self.info["enabled"]}))
        # Set information as child so that it doesn't clog up the display
        infoList=[]
        infoList.append((["time stamp",toStr(self.info["creationTime"])]))
        infoList.append((["num curr points",toStr(self.info["numCurrPoints"])]))
        infoList.append((["compliance (V)",toStr(self.info["Vcomp"])]))
        dataSummaryList.append((["Info"],infoList))
        try:
            dataSummaryList.append((["Temperature [K]",toStr(self.data["temperature"])]))        
            dataSummaryList.append((["current (mA)",toStr(self.data["iMeas"]*1000)]))
            dataSummaryList.append((["voltage (V)",toStr(self.data["vMeas"])]))
        except KeyError as e:
            pass
        return dataSummaryList

    def numToString(self,data,numDigits=2,maxElements=2):
        """ Take variable data type and format it as a string appropriate for displaying in a QTreeWidget in main"""       
        if type(data)==str or type(data)==unicode:
            return data
        if type(data)==string_:
            return str(data)
        if data is None:
            return "N/A"
        elif type(data)==int:
             return str(data)
        elif type(data)==float or type(data)==float64:
            return ("{:0."+str(numDigits)+"f}").format(data)
        # If list of n numbers then format as "[data_1, data_2, ..., data_n]" with number shown depending on maxElements
        elif type(data)==list or type(data)==ndarray:           
            outString=['[']
            for i in range(len(data)):
                if i<maxElements:
                    outString.append(self.numToString(data[i],numDigits))
                    outString.append(', ')
                else:
                    break
            if len(data)>(maxElements+1):
                # Replace remaining elements with ellipsis except for final element
                outString.append("... , ")
                outString.append(self.numToString(data[-1],numDigits))
                outString.append(']')
            else:
                # Change last comma + space to right square bracket
                del outString[-1]
                outString.append("]")
            return "".join(outString)

    def sendProgress(self,progress):
        """ Emit a signal indicating the progress, as percentage"""
        self.progress.emit(progress*100)
        #self.emit(QtCore.SIGNAL("progress"),progress*100)

    def sendStatusMessage(self,msg):
        """ Send a status message to the user """
        print(msg)
        self.progressMessage.emit(msg)
        QtCore.QCoreApplication.processEvents()
        # In addition to printing, ideally also want to send something to the GUI

    def sendPlotProgress(self,progress):
        """ Emit a signal indicating the progress for plotting, as percentage"""
        self.plotProgress.emit(progress*100)

    def sendPlotData(self,plotDictionary):
        """ Emit a signal with a plot dictionary """
        self.plotDataReady.emit(plotDictionary)
        #self.emit(QtCore.SIGNAL("plotDataReady"),plotDictionary)

    def sendVarToTerminal(self,varName,var):
        """ Debug helper function which sends a variable to the console workspace """
        self.main.showConsoleDialog()
        try:
            self.main.debugVars[varName]=var.copy()
        except:
            self.main.debugVars[varName]=var
        self.main.consoleDialog.updateNamespace(varName,self.main.debugVars[varName])

class LIV(Measurement):
    """ Subclass of main measurement type to hold data for LIV measurement """
    def __init__(self, info, dummy=False, parent = None, lock=None):
        info["type"]="LIV"
        super(LIV, self).__init__(info, dummy,parent=parent, lock=lock)
    
    def plot(self,maxIndex=None,offset=False,logscale=False):
        """ Prepares the LIV data for plotting, and emits a signal when finished for the mainwindow to draw the plot """
        # trim the data if a maxIndex is specified, otherwise plot the full data using mA and uW as default
        self.sendPlotProgress(0)
        x=self.data["iMeas"]*1e3
        y1=self.data["lMeas"]*1e6
        y2=self.data["vMeas"]
        if maxIndex!=None:
            x=x[0:maxIndex+1]
            y1=y1[0:maxIndex+1]
            y2=y2[0:maxIndex+1]
            (xth,yth)=(None,None)
        else:
            try:
                (xth,yth)=self.getThresholdCurrent()
                xth=xth*1e3
                yth=yth*1e6
            except Exception:
                xth=0
                yth=0
        # Add the plot data to the dictionary
        xAxis={"data":(x,xth),"label":"I [mA]"}
        if maxIndex!=None:
            xAxis["limit"]=(self.iSet[0]*1000,self.iSet[-1]*1000)
        yAxis={"data":(y1,yth),"lineProp":("k","ko"),"label":"L [uW]"}
        x2Axis={"data":(x,)} # to allow for multiple lines on second axis as well
        y2Axis={"data":(y2,),"lineProp":("r-"),"label":"V [V]","color":"r"}
        plotDictionary={"x":xAxis,"y":yAxis,"x2":x2Axis,"y2":y2Axis,"title":"Light output and voltage vs current"}
        # Emit a signal with data dictionary for the GUI to know what to plot
        #self.emit(QtCore.SIGNAL("plotDataReady"),plotDictionary)
        self.sendPlotData(plotDictionary)
        self.finishedPlotting()
        self.sendPlotProgress(1)

    def acquireData(self):
        """ Cycles through each current point and does Source/Measure of IV, then power measurement. I'd like to refactor some of this code into the Measurement class 
       to avoid duplication with acquireData() method in the Spectrum class"""
        if not self.DUMMY_MODE:
            if self.roughAlignFlag:
                self.sendStatusMessage("Initializing piezo controller to center for rough align...")
                piezoAlignObject=PiezoAlign()
                self.roughAlign(self.preAlignFlag)
            self.initTempController()
            n=self.info["numCurrPoints"]
            #self.iSet=around(linspace(self.info["Istart"],self.info["Istop"],n),5)
            self.iSet=linspace(self.info["Istart"],self.info["Istop"],n)
            pm=PrimaryPowerMeter()
            smu=SMU(autoZero=False,disableScreen=True,defaultCurrent=ALIGNMENT_CURRENT)
            self.data["lMeas"]=zeros(n)
            self.data["iMeas"]=zeros(n)
            self.data["vMeas"]=zeros(n)
            with QReadLocker(self.lock):
                self.data["temperature"]=self.tempController.getTemperature() if not NO_TEMP_SENSOR else None
            self.cryostatOff=True if self.data["temperature"] > LOWTEMP_THRESHOLD else False
            self.sendStatusMessage("Acquiring LIV data...")
            for i in range(n):
                # Cancel the measurement if it has been aborted
                QtCore.QCoreApplication.processEvents()
                if not self.running:
                    self.aborted.emit()
                    #self.emit(QtCore.SIGNAL("aborted"))
                    return
                # Emit progress
                self.sendProgress(i/n)
                # Set current, then measure V/I/L
                smu.setCurrent(self.iSet[i],self.info["Vcomp"])
                self.data["vMeas"][i],self.data["iMeas"][i]=smu.measure()
                sleep(20e-3) # 20ms wait to account for 1kHz analog filter on power meter + digital filter(10 samples)
                try:
                    tau=LIV_TAU if self.cryostatOff else LIV_TAU_LOWTEMP
                    powerMeas=pm.readPowerAuto(tau=tau)
                except Exception as e:                
                    QtGui.QMessageBox.warning(None,"CommError",("There was a persistent problem with the power meter:\n %1").arg(e.args[0]))
                    self.aborted.emit()
                    return
                self.data["lMeas"][i]=powerMeas                   
                # Update the plot if not already rendering
                QtCore.QCoreApplication.processEvents()
                if not self.rendering:
                    self.rendering=True
                    self.plot(i)

        else:
            nCurr=self.info["numCurrPoints"]
            self.acquireDummyData()
            for i in range(nCurr):
                # Cancel the measurement if it has been aborted
                if not self.running:
                    self.aborted.emit()
                    return
                self.sendProgress(i/nCurr)
                sleep(20e-3)
                # Update the plot if not already rendering
                QtCore.QCoreApplication.processEvents()
                if not self.rendering:
                    self.rendering=True
                    self.plot(i)
        # Emit 100% progress and finished message
        if max(self.data["lMeas"]) > LIV_MIN_MAX_POWER: 
            self.sendProgress(1)
            self.finishedWork()
        else:
            try:
                del piezoAlignObject
            except NameError:
                pass
            raise SignalTooWeakError


    def doWork(self):
        """ Test function for QThread """
        n=200000
        for i in range(n):
            self.emit(QtCore.SIGNAL("progress"),i/n*100)
        self.emit(QtCore.SIGNAL("progress"),100)
        self.finishedWork()

    def correctOffset(self,limit=16e-6):
        """ Subtract the noise floor at zero if within limit """
        if min(self.data["lMeas"])<limit and min(self.data["lMeas"])>0:
            self.data["lMeas"]=self.data["lMeas"]-min(self.data["lMeas"])

    def bilinearFunction(self,x,b,m1,m2,xt):
        """ bilinear function for calculating threshold current (deprecated) """
        return b+m1*x+[max(m2*(xi-xt),0) for xi in x]
    
    def fitCurrent(self,maxLight=200e-6):
        """ Calculates the fit parameters from the LIV data up to maxLight (noise floor of Newport detector is 20uW, so 200uW is reasonable.
        Fit a maximum 5 segment cubic spline and take the peak of the second derivative as the threshold current (deprecated)"""
        x=self.data["iMeas"][self.data["lMeas"]<=maxLight]*1e3
        y=self.data["lMeas"][self.data["lMeas"]<=maxLight]*1e6
        #p=optimize.curve_fit(self.bilinearFunction,x,y,(16,.1,40,10))[0] # do nonlinear fit and extract bilinear parameters            
        # Set uniform knots for spline fit
        t=linspace(min(x),max(x),min(floor(len(x)/5)+1,6))
        p=interpolate.LSQUnivariateSpline(x,y,t[1:-1])
        self.fitFunction=p

    def getFittedLI(self):
        """ returns the fitted L data in W (deprecated)"""
        #return self.bilinearFunction(self.data["iMeas"]*1e3,*self.getFitParameters())*1e-6
        return self.fitFunction(self.data["iMeas"])

    def getFitParameters(self,recalculate=True):
        """ returns the fit parameters, calculating if necessary """
        if recalculate or self.fitParameters is None:
            self.fitCurrent()
        return self.fitParameters

    def getThresholdCurrent(self,maxLight=1e-6,INTERPOLATE=True):
    #def getThresholdCurrent(self,maxLight=5e-3,INTERPOLATE=True):
        """ Smooth data and take the peak of the second derivative as the threshold current.
        First trim the data to the range below where lMeas first goes abive maxLight. The noise floor of Newport detector is 20uW, so 200uW is reasonable starting point."""
        x=self.data["iMeas"]
        y=self.data["lMeas"]
        # Calculate the second derivative from a Savitky-Golay filter
        if y.max() < (y.min() + maxLight):
            maxLight=6e-10
        window=round(len(x)/8)
        window=window-1 if window%2 else window # window must be odd number
        yprime=savitzky_golay(y,31,4,1) # first derivative from smoothed data
        yprime2=savitzky_golay(y,31,4,2) # second derivative from smoothed data
        if size(yprime2)>size(y):
            # This seems to happen when the length of y is too small!
            raise Exception
        if INTERPOLATE:
            p=interpolate.interp1d(x,y,'cubic')
            pp=interpolate.interp1d(x,yprime,'cubic')
            ppp=interpolate.interp1d(x,yprime2,'cubic')
            # Get the interpolated second derivative vs x
            xx=linspace(min(x),max(x),1e5)
            yy=p(xx)
            yyprime=pp(xx)
            # Trim to the bottom of the tail
            maxIndex=where(yy>=(maxLight+y.min()))[0]
            if len(maxIndex)>0:
                xxx=xx[0:maxIndex[0]-1]
                yyy=yy[0:maxIndex[0]-1]
            else:
                xxx=xx
                yyy=yy
            # Get the final threshold current value
            yyyprime2=ppp(xxx)
            xyTuple=(xxx[yyyprime2==max(yyyprime2)][0],yyy[yyyprime2==max(yyyprime2)][0])
            # Plot the first and second derivatives for debugging
            #self.main.canvas.plot(xxx,yyyprime2)
            #QtCore.QCoreApplication.processEvents()
            pass
        else:
            # take the first value where the second derivative is maximum (may be a nicer way to force uniqueness)
            maxIndex=where(y>=(maxLight+y.min()))[0]
            x=x[0:maxIndex[0]-1]
            y=y[0:maxIndex[0]-1]
            yprime2=yprime2[0:maxIndex[0]-1]
            xyTuple=(x[yprime2==max(yprime2)][0],y[yprime2==max(yprime2)][0])
        return xyTuple

    def acquireDummyData(self):
        """ sets some dummy LIV data for remote development with no GPIB """
        self.iSet=linspace(self.info["Istart"],self.info["Istop"],self.info["numCurrPoints"])
        self.data["vMeas"]=log(self.iSet/1e-9/random.random())*25e-3
        self.data["vMeas"]=self.data["vMeas"]*(self.data["vMeas"]<=self.info["Vcomp"])+self.info["Vcomp"]*(self.data["vMeas"]>self.info["Vcomp"])        
        self.data["iMeas"]=1e-9*exp(self.data["vMeas"]/25e-3)
        It=10e-3
        self.data["lMeas"]=self.data["iMeas"]*(self.data["iMeas"]>It)-It*(self.data["iMeas"]>It)
        self.data["temperature"]=300+random.rand()
    
    def saveAs(self,fname,index=None):
        """ Exports the raw data to specified file, with format inferred from extension"""
        fileExtension=os.path.splitext(fname)[1]
        if fileExtension==".mat":
            # Export a matlab file with data and info
            outData={"current":self.data["iMeas"],"voltage":self.data["vMeas"],"light":self.data["lMeas"],"info":self.info}
            scipyio.savemat(fname,outData)
        elif fileExtension==".csv":
            # Export raw data as a csv file
            outData=transpose(vstack((self.data["iMeas"],self.data["vMeas"],self.data["lMeas"])))
            savetxt(fname, outData, delimiter=",")
        elif fileExtension==".pickle":
            # Pickle the measurement object as (info,iMeas,vMeas,lMeas) tuple
            outData=(self.info,self.data["iMeas"],self.data["vMeas"],self.data["lMeas"])
            pickle.dump(outData,open(fname, "wb" ))

    def dataSummary(self):
        """ Returns a list of tuples which summarizes the test data via strings in a logically structured way. Format example is as follows:
        [([data1_col1,data1_col2],),([data2_col1,data2_col2],optionsDictionary: {"isCheckable":True,"clickMethod":meas.plot}),([data1_col1,data1_col2],childDataList: [(dataLabel4,data4),(dataLabel5,data5)])] """
        dataSummaryList=super(LIV,self).dataSummary()
        toStr=self.numToString # method in parent class which converts float,int,list,numpy.ndarray,str to string
        dataSummaryList.append((["light (mW)",toStr(self.data["lMeas"]*1000)],))
        return dataSummaryList

class Spectrum(Measurement):
    """ Subclass of main measurement type to hold data for spectrum measurement vs current. 
    A single current measurement is acheived by setting the number of sweep points to 1"""
    measError=QtCore.pyqtSignal(str)
    def __init__(self, info, dummy=False, parent = None, lock=None, controlCurrent=True, currRange=0.1):
        info["type"]="Spectrum"
        super(Spectrum, self).__init__(info, dummy,parent=parent, lock=lock)
        self.laserParam={"R1":.997,"R2":.322,"L":375e-6,"n":3.619}
        self.controlCurrent=controlCurrent
   
    def acquireData(self,canvas=None,dummy=False):
        """ Acquire data """
        if not self.DUMMY_MODE:
            if self.roughAlignFlag or self.fineAlignFlag:
                self.sendStatusMessage("Initializing piezo controller to center for rough align...")
                self.piezoAlignObject=PiezoAlign()
                self.roughAlign(self.preAlignFlag)
            else:
                self.piezoAlignObject=None
            self.initTempController()
            # Get some parameters
            nCurr=self.info["numCurrPoints"]
            mLambda=self.info["numLambdaPoints"]
            self.iSet=maximum(around(linspace(self.info["Istart"],self.info["Istop"],nCurr),5),SPECTRUM_MIN_CURRENT)
            # Setup the spectrum analyzer and SMU and take measurements
            try:
                # Create instance and initialize instrument for capturing spectral data
                instrument=self.initInstrument()
                # Create empty data arrays
                self.data["wavelength"]=zeros((mLambda,nCurr))
                self.data["intensity"]=zeros((mLambda,nCurr))
                self.data["iMeas"]=zeros(nCurr)
                self.data["vMeas"]=zeros(nCurr)
                self.data["temperature"]=zeros(nCurr)
                self.data["SNR"]=zeros(nCurr)
                # Start measurement process
                self.mainProgressStep=1/nCurr
                # Measure spectrum for each current
                alignTime=0
                for i in range(nCurr):
                    # Cancel the measurement if it has been aborted
                    QtCore.QCoreApplication.processEvents()
                    try:
                        if not self.osa.tempLocked():
                            print("WARNING: Winspec temperature not locked!!!")
                    except AttributeError as e:
                        pass
                    if not self.running:
                        self.aborted.emit()
                        return
                    # Fine-adjust the alignment to compensate for thermal/mechanical drift
                    if self.fineAlignFlag and POWER_METERS["fineAlign"]:
                        if (time()-alignTime)>MIN_REALIGNMENT_TIME*60:
                            self.fineAlign(smu=self.smu)
                            alignTime=time()
                    else:
                        if i>1:
                            #self.manualAlign()
                            pass
                    # Send the main progress and assign to self so that subprogress can be taken into account if available
                    self.mainProgress=self.mainProgressStep*i
                    self.sendProgress(self.mainProgress)
                    # Set current, then measure V/I/L
                    if not NO_TEMP_SENSOR:
                        with QReadLocker(self.lock):
                            self.data["temperature"][i]=self.tempController.getTemperature()                        
                        self.cryostatOff=True if self.data["temperature"][i] > LOWTEMP_THRESHOLD else False                            
                    else:
                        self.cryostatOff=False
                        self.data["temperature"]=None
                    self.smu.setCurrent(self.iSet[i],self.info["Vcomp"])
                    self.data["vMeas"][i],self.data["iMeas"][i]=self.smu.measure()
                    self.currentIndex=i
                    try:
                        self.acquireSingleSpectrum(instrument,i)
                    except MeasurementAbortedError:
                        # If measurement aborted cancel everything immediately without saving any data
                        self.sendStatusMessage("Aborting spectrum measurement...")
                        self.aborted.emit()
                        return
                    except SignalTooStrongError as e:
                        # If signal too strong to proceed then salvage previous measurements and notify the user with message box
                        self.savePartialData(i)
                        self.measError.emit("Signal Too Strong... Saving data collected so far and aborting measurement")
                        return
                    except Exception as e:
                        # For other exceptions, salvage data then re-raise the existing error with proper call stack
                        self.savePartialData(i)
                        raise
                    self.sendStatusMessage("Finished acquiring data for spectrum "+str(self.currentIndex+1)+"/"+str(size(self.iSet)))
                    self.plot(i)
            except IOError, e:
                QtGui.QMessageBox.warning(None,"VisaIOError",("There was an instrument communication error. Please check all the instruments are connected properly:\n %1").arg(e.args[0]))
            finally:
                # remove the smu so that it returns to user control
                try: 
                    del self.dmm
                except Exception as e:
                    pass
                del self.smu, self.osa, self.piezoAlignObject
        else:
            nCurr=self.info["numCurrPoints"]
            self.acquireDummyData()
            for i in range(nCurr):
                # Cancel the measurement if it has been aborted
                if not self.running:
                    self.aborted.emit()
                    return
                # Update the progress
                self.sendProgress(i/nCurr)
                sleep(0.2)
                self.plot(i)
        # Emit 100% progress so that any progress dialogs disappear
        self.finishedWork()
        self.sendProgress(1)

    def savePartialData(self,i):
        if i > 0:
            self.data["wavelength"]=self.data["wavelength"][:,0:i]
            self.data["intensity"]=self.data["intensity"][:,0:i]
            self.data["iMeas"]=self.data["iMeas"][0:i]
            self.data["vMeas"]=self.data["vMeas"][0:i]
            self.data["temperature"]=self.data["temperature"][0:i]
            self.data["SNR"]=self.data["SNR"][0:i]
            self.finishedWork()

    def manualAlign(self):
        """ Give the user a chance to readjust the alignment. Wait for predefined time before automatically continuing """
        TIMEOUT=15                      # Time to wait (in seconds) before automatically resuming measurement
        msgBox=QtGui.QMessageBox()
        msgBox.setText("Do you want to pause measurement for realignment?")
        msgBox.addButton("No",QtGui.QMessageBox.NoRole)
        msgBox.addButton("Yes",QtGui.QMessageBox.YesRole)
        QTimer.singleShot(TIMEOUT*1000, msgBox, QtCore.SLOT('hide()'))
        pause=msgBox.exec_()
        if pause:
            msgBox=QtGui.QMessageBox()
            msgBox.setText("Waiting for alignment to be completed... Click OK when finished")
            answer=msgBox.exec_()
            print("alignment complete, proceeding")

    def acquireDummyData(self):
        """ sets some dummy spectrum data for remote development with no GPIB """
        with open('examplespectrum.pickle') as f:
            d0,d1=pickle.load(f)
        n=self.info["numCurrPoints"]
        self.data["wavelength"]=tile(array(d0),(n,1)).transpose()
        self.data["intensity"]=tile(array(d1),(n,1)).transpose()
        self.info["numLambdaPoints"]=m=len(d0)
        self.iSet=linspace(self.info["Istart"],self.info["Istop"],self.info["numCurrPoints"])
        self.data["iMeas"]=self.iSet
        self.data["vMeas"]=log(self.iSet/1e-9/random.random())*25e-3
        self.data["temperature"]=[300.0]*n+random.rand(n)
        #self.data["iMeas"]=tile(self.iSet,(m,1)).transpose()
        #self.data["vMeas"]=tile(log(self.iSet/1e-9/random.random())*25e-3,(m,1)).transpose()
        #self.data["temperature"]=tile(array(None),(n,1))

    def saveAs(self,fname,index=None):
        """ Exports the raw data to specified file, with format inferred from extension"""
        fileExtension=os.path.splitext(fname)[1]
        if fileExtension==".mat":
            # Export a matlab file with data and info
            if index!=None:
                # Allow for a single spectrum to be exported when an index is specified
                outData={}
                for dataArrayName in self.data:
                    # Take an array slice from the n-1 highest dimensions at index
                    if ndim(self.data[dataArrayName])==1:
                        outData[dataArrayName]=self.data[dataArrayName][index]
                    elif ndim(self.data[dataArrayName])==2:
                        outData[dataArrayName]=self.data[dataArrayName][:,index]
                    else:
                        raise TypeError,"Please implement support for numpy arrays greater than 2D in the .mat export routine."
            else:
                outData=self.data
            outData["info"]=self.info
            scipyio.savemat(fname,outData)
        elif fileExtension==".csv":
            # Export raw data as a csv file
            if index!=None:
                outData=transpose(vstack((self.data["wavelength"][:,index],self.data["intensity"][:,index])))
            else:
                n=len(self.data["wavelength"])
                outData=transpose(vstack((self.tileVector(self.data["iMeas"],n),self.tileVector(self.data["vMeas"],n),self.serializeArray(self.data["wavelength"]),self.serializeArray(self.data["intensity"]),self.tileVector(self.data["SNR"],n))))
            savetxt(fname, outData, delimiter=",")
        elif fileExtension==".pickle":
            # Pickle the measurement object as (info,data) tuple. Ignore any index for now
            pickle.dump((self.info,self.data),open(fname, "wb" ))

    def plot(self,index=None,xLim=None,pLim=None,xAxisUnit="energy",title=None,offset=False,logscale=True):
        """ Prepares the Spectrum data for plotting, and emits a signal when finished for the mainwindow to draw the plot.
       Input parameters are:
       index=None -> index from data array to plot
       xLim=None -> tuple of min and max energies / wavelengths on x-axis relative to center point (in meV / nm respectively)
       gLim=None -> tuple of min and max gains on y-axis
       pLim1=None -> tuple of min and max values for spectrum power on y-axis (if included)
       xAxisUnit="energy" -> string to specify "energy" or "wavelength" as unit for x-axis
       title=None -> string to use for title if non-default title is desired
       offset=False -> flag whether to allow axis to be specified relative to some offset
       logscale=False -> flag whether to allow spectrum power to be plotted on log-scale
       """
        # Get the plot index from self.main (note: this is just a hack because I can't seem to get it through the started signal of the QThread
        if index is None:
            try:
                index=self.main.currentPlotIndex
            except AttributeError as e:
                pass
        # Chop up the array if required
        if index!=None and type(index)==int:
            numSpectra=1
            x=self.data["wavelength"][:,index]
            y=self.data["intensity"][:,index]
            iMeas=array([self.data["iMeas"][index]])
            T=self.data["temperature"][index]
        else:
            numSpectra=shape(self.data["wavelength"])[1]
            x=self.data["wavelength"]
            y=self.data["intensity"]
            iMeas=self.data["iMeas"]
            T=min(self.data["temperature"]) if self.data["temperature"]!=None else None
        # Prepare plot for case of single spectrum
        if numSpectra==1:
            # I think this flattening was added as a dirty fix because I was seeing embedded single element arrays in x and y
            x=x.flatten()
            y=y.flatten()
            x0=self.info["Center"]
            if logscale:
                y=10*log10(y/1000) # dBm
                ylabel="Optical power (dBm)"
            else:
                if max(y)>1e-9:
                    y=y*1e9
                    ylabel="Optical power (nW)"
                else:
                    y=y*1e12
                    ylabel="Optical power (pW)"
            if title is None: title="Optical power vs wavelength spectrum: I = " + "{:0.2f}".format(iMeas[0]*1000) +"mA"
            # Add the plot data to the dictionary
            if xAxisUnit=="energy":
                E0=self.lambdaToE(x0)*1000
                xAxis={"data":(self.lambdaToE(x)*1000,),"label":"Emission energy [meV]"}
                if xLim!=None: xAxis["limit"]=(E0-xLim[0],E0+xLim[1])
            else:
                xAxis={"data":((x-x0)*1e9,),"label":(str(x0*1e6)+ "um wavelength offset [nm]")}
                if xLim!=None: xAxis["limit"]=xLim
            yAxis={"data":(y,),"lineProp":("-",),"label":ylabel}
            plotDictionary={"x":xAxis,"y":yAxis,"title":title}
        # Prepare plot for case of multi-spectra
        elif numSpectra>1 and self.laserParam!=None:
            # Setup some progress tracking variables
            x=[self.data["wavelength"][:,i] for i in range(numSpectra)]
            # TO DO: Take the envelope of the y data
            y=[self.data["intensity"][:,i] for i in range(numSpectra)]
            # order in values of decreasing current
            order=argsort(iMeas)[::-1]
            iMeas=iMeas[order]
            x=[x[i] for i in order]
            y=[y[i] for i in order]
            lineProp=["-" for i in self.data["iMeas"]]
            legend=["{:0.2f}".format(i*1000)+"mA" for i in iMeas]
            # Scale y-axis
            if logscale:
                y=[10*log10(yi/1000) for yi in y] # dBm
                ylabel="Optical power (dBm)"
            else:
                if max(y)>1e-9:
                    y=[yi*1e9 for yi in y]
                    ylabel="Optical power (nW)"
                else:
                    y=[yi*1e12 for yi in y]
                    ylabel="Optical power (pW)"
            # Add the data to plot dictionary
            x0=self.info["Center"]
            if xAxisUnit=="energy":
                E0=self.lambdaToE(x0)*1000
                xAxis={"data":tuple([self.lambdaToE(xi)*1000 for xi in x]),"label":"Emission energy [meV]"}
                if xLim!=None: xAxis["limit"]=(E0-xLim[0],E0+xLim[1])
            else:
                # scale / shift data
                x0=self.info["Center"]
                x=[(xi-x0)*1e9 for xi in x]
                xAxis={"data":tuple(x),"label":(str(x0*1e6)+ "um wavelength offset [nm]")}
                if xLim!=None: xAxis["limit"]=xLim
            # Create dictionary specifying axis parameters
            yAxis={"data":tuple(y),"label":ylabel,"legend":legend,"lineProp":lineProp}
            if pLim!=None: yAxis["limit"]=pLim
            # Include temperature in title if it's included
            if title is None:
                title=r"Lasing spectral intensity vs wavelength"
                if T!=None:
                    title+=" @ {:0.1f}".format(T) +"K"
            plotDictionary={"x":xAxis,"y":yAxis,"title":title}
        else:
            return
        # Emit a signal with data dictionary for the GUI to know what to plot
        self.sendPlotData(plotDictionary)
        # Need to fix this so that moveToThread() doesn't interfere with measurement
        self.finishedPlotting()
        self.sendPlotProgress(1)

    def lambdaToE(self,wavelength):
        """ Given the wavelength in m, return the photon energy in eV"""
        if type(wavelength)==ndarray or type(wavelength)==float or type(wavelength)==float64:
            return scipycsts.h*scipycsts.c/wavelength/scipycsts.e
        elif type(wavelength)==list:
            return [self.lambdaToE(x) for x in wavelength]
        else:
           raise TypeError, "Unsupported data type: expected float or numpy.ndarray"     

    def getLasingWavelength(self,idx=-1,method="fit"):
        """ Gets the wavelength where the intensity is maximum of specified current
        (largest current by default) """
        if method=="peak":
            return self.data["wavelength"][self.data["intensity"][:,idx].argsort()[-1],-1]
        elif method=="fit":
            # note: lambdaToE() also works in reverse... i.e. E -> lambda
            try:
                return self.lambdaToE(self.fitSpectrum(idx,0.7)[0])
            except Exception:
                print("warning: error occured fitting gaussian in getLasingWavelength()... using peak value instead")
                return self.getLasingWavelength(idx,method="peak")

    def dataSummary(self):
        """ Returns a list of tuples which summarizes the test data via strings in a logically structured way. Format example is as follows:
        [([data1_col1,data1_col2],),([data2_col1,data2_col2],optionsDictionary: {"isCheckable":True,"clickMethod":meas.plot}),([data1_col1,data1_col2],childDataList: [(dataLabel4,data4),(dataLabel5,data5)])] """
        # Add the common parameters for all tests
        dataSummaryList=super(Spectrum,self).dataSummary()        
        toStr=self.numToString # method in parent class which converts float,int,list,numpy.ndarray,str to string
        # Add the rest of the data
        try:
            for index in range(len(self.data["iMeas"])):
                dataSummaryList.append(([toStr(self.data["iMeas"][index]*1000)+" mA"],{"index":index}))
                #if meas.data["temperature"][index]!=None:
                #    tempItem = QTreeWidgetMeasItem(currItem, ["Temperature [K]","{:3.2f}".format(meas.data["temperature"][index])])
        except KeyError:
            pass
        return dataSummaryList

    def fitSpectrum(self,idx,threshold=0):
        """ Fit a gaussian to the envelope of the spectrum """
        # Get raw data
        wavelength=self.data["wavelength"][:,idx]
        power=self.data["intensity"][:,idx]
        # Do peak detection and use this to extract the envelope. Also convert wavelength to energy
        maxIdxRaw=peakDetect(power)
        maxIdx=peakClean(wavelength,power,maxIdxRaw)
        y=power[maxIdx]
        x=self.lambdaToE(wavelength[maxIdx])
        return self.fitGaussian(x,y,threshold)

    def fitGaussian(self,x,y,threshold):
        # Normalize and trim the data
        y=y/abs(y.max())
        inRange=y>=threshold
        y=y[inRange]
        x=x[inRange]
        # Give some reasonable starting parameters
        maxIdx=where(y==y.max())[0][0]       
        p0=(x[maxIdx],5e-3,1.0)
        # Do Gaussian fit
        returnParam=optimize.curve_fit(self.gaussian,x,y,p0)
        p=returnParam[0]
        # Plot the data
        self.main.canvas.plot(x,y,'x',x,self.gaussian(x,*p))
        QtCore.QCoreApplication.processEvents()
        return p


    def gaussian(self,x,x0,sigma,A):
        return A*exp(-(x-x0)**2/2/sigma**2)
        

class AdvantestSpectrum(Spectrum):
    """ Subclass of Spectrum for the Advantest Q8384 OSA """
    def __init__(self, info, dummy=False, parent = None, lock=None):
        super(AdvantestSpectrum, self).__init__(info, dummy, parent=parent, lock=lock)
        self.info["type"]="AdvantestSpectrum"
    def initInstrument(self):
        """ Creates a reference to the instrument and initializes it to settings required before the start of a measurement """
        osa=SpectrumAnalyzer()
        osa.setCenter(self.info["Center"]*1e9)
        osa.setNumPoints(self.info["numLambdaIndex"])
        osa.setResolution(self.info["Resolution"]*1e9)
        osa.setSpan(self.info["Span"]*1e9)
        osa.setSweepMode(self.info["SweepMode"])
        return osa
    def acquireSingleSpectrum(self,osa,index):
        """ Acquires a single spectrum and sets data in self.data["wavelength"], self.data["intensity"] """
        self.data["wavelength"][:,idx],self.data["intensity"][:,idx]=osa.obtainSpectrum()

class WinspecSpectrum(Spectrum):
    """ Subclass of Spectrum using the Winspec COM Type Library """
    def __init__(self, *args, **kwargs):
        super(WinspecSpectrum, self).__init__(*args, **kwargs)
        self.info["type"]="WinspecSpectrum"

    def initInstrument(self):
        """ Creates a reference to the instrument and initializes it to settings required before the start of a measurement """
        if self.controlCurrent:
            # Create new object for winspec analyzer and set it up for the specified measurement
            self.smu=SMU(autoZero=True,defaultCurrent=ALIGNMENT_CURRENT)
        else:
            self.smu=DummySMU()
        # Create a directory structure for the raw winspec data files if one doesn't already exist
        winspecDataPath=os.path.join(os.path.dirname(__DBPATH__),os.path.splitext(os.path.split(__DBPATH__)[1])[0]+"_winspec")
        if not os.path.exists(winspecDataPath):
            os.makedirs(winspecDataPath)
        winspecDataPath=os.path.join(winspecDataPath,self.info["groupName"].replace(" ","_"))
        if not os.path.exists(winspecDataPath):
            os.makedirs(winspecDataPath)
        dateTimeStr=self.info["creationTime"].replace(":","").replace("-","").replace(" ","_")
        winspecDataPath=os.path.join(winspecDataPath,self.info["Name"].replace(" ","_")+"_"+dateTimeStr)
        if not os.path.exists(winspecDataPath):
            os.makedirs(winspecDataPath)
        self.winspecDataPath=winspecDataPath
        self.osa=osa=WinspecAnalyzer(self.smu.setOutputState,winspecDataPath)
        osa.setResolution(self.info["Resolution"]*1e9)
        osa.setCenter(self.info["Center"]*1e9)
        osa.setNumPoints(self.info["numLambdaPoints"])
        if osa.has2dDetector(): osa.autoSetROI()
        if self.info["optimizeCenter"]:
            self.smu.setCurrent(self.iSet[-1],self.info["Vcomp"])
            newCenter = osa.measureOptimalCenter()
            osa.setCenter(newCenter)
            self.info["Center"], self.info["CenterSet"] = newCenter*1e-9, self.info["Center"]
        return osa

    def acquireData(self,canvas=None,dummy=False):
        if POWER_METERS["secondary"]:
            # always store the assumed efficiency converting photons at input to counts at the detector
            self.data["opticalEfficiency"]=zeros(self.info["numCurrPoints"])
            # keep track of the gain used for the measurement to improve learning condition for detector saturation
            self.gainSetting=zeros(self.info["numCurrPoints"])
        # call the acquireData() method of the main Spectrum parent class
        super(WinspecSpectrum, self).acquireData(canvas,dummy)
        # finally take note of the measured CPS data vs input power so it can be used to estimate exposure time next measurement
        #if POWER_METERS["secondary"]:
        #    self.savePowerVsCPS()

    def acquireSingleSpectrum(self,osa,idx):
        """ Finds the optimal exposure time, and acquires a single spectrum
        then sets the data in self.data["wavelength"], self.data["intensity"] """
        # Measure the power using a calibrated source as reference for absolute power
        if POWER_METERS["secondary"]:
            tau=ALIGNMENT_TAU if self.cryostatOff else ALIGNMENT_TAU_LOWTEMP
            pm=SecondaryPowerMeter()
            self.smu.setOutputState("OFF")
            bg=pm.readPowerAuto(tau=tau)
            self.smu.setOutputState("ON")
            totalInputPower=max(pm.readPowerAuto(tau=tau)-bg,1e-12)
        # Specify the filename for the raw data
        self.osa.setDataFilename(str(self.iSet[self.currentIndex]*1e3).replace(".","p")+"mA")
        self.sendStatusMessage("Acquiring data for spectrum "+str(self.currentIndex+1)+"/"+str(size(self.iSet))+" starting with rangeIndex = " + str(osa.rangeIndex))
        tau=SPECTRUM_TAU if self.cryostatOff else SPECTRUM_TAU_LOWTEMP
        calibratedPower=totalInputPower if POWER_METERS["secondary"] else None
        wavelength,intensity,info=osa.obtainSpectrum(tau,calibratedPower)
        self.data["opticalEfficiency"][self.currentIndex]=info["efficiency"]
        self.data["SNR"][self.currentIndex]=info["SNR"]
        # return the data output
        # TODO: Do something more useful with info instead of discarding it here
        self.data["wavelength"][:,idx]=wavelength
        self.data["intensity"][:,idx]=intensity   

    def estimateCPS(self,inputPower,gain):
        """ Helper function which estimates what the CPS at the detector should be given the inputPower """
        # Flag to control whether or not we measure the calibration data
        s=QtCore.QSettings()
        if gain==1:
            p=s.value("WINSPEC_EXPOSURE_DATA_LOWGAIN",array([MAX_CPS_PER_NANOWATT_LOW_GAIN*1e9,0]))
        else:
            p=s.value("WINSPEC_EXPOSURE_DATA_HIGAIN",array([MAX_CPS_PER_NANOWATT_LOW_GAIN*1e9*winspec.HI_GAIN_MULT,0]))
        cps=polyval(p,inputPower)
        return cps

    def savePowerVsCPS(self,polynomialOrder=2):
        """ Fit a polynomial to the cps vs power data, in order to reduce time required to find optimal exposure time.
        Also, save the data to QSettings so that it can be retrieved and modified anytime the program is run"""
        s=QtCore.QSettings()      
        # Get the data from the object
        wavelength=self.data["wavelength"]
        efficiency=self.data["opticalEfficiency"]
        spectrumPower=self.data["intensity"]
        totalPower=sum(spectrumPower,0)
        maxIndex=argmax(spectrumPower,0)
        maxPower=diag(spectrumPower[maxIndex,:])
        maxCpsWavelength=diag(wavelength[maxIndex,:])
        maxCPS=self.wattsToCPS(maxCpsWavelength,maxPower,efficiency)
        # low gain fitting
        lowGainIdx=equal(self.gainSetting,2)
        if sum(lowGainIdx)> polynomialOrder+1 :
            # fit polynomial of specified order to max CPS vs total input power [low gain setting] and save to QSettings
            s.setValue("WINSPEC_EXPOSURE_DATA_LOWGAIN",polyfit(totalPower[lowGainIdx],maxCPS[lowGainIdx],polynomialOrder))
        # high gain fitting
        highGainIdx=equal(self.gainSetting,1)
        if sum(highGainIdx) > polynomialOrder + 1:
            # fit polynomial of specified order to max CPS vs total input power [high gain setting] and save to QSettings
            s.setValue("WINSPEC_EXPOSURE_DATA_HIGHGAIN",polyfit(totalPower[highGainIdx],maxCPS[highGainIdx],polynomialOrder))


    def derivativeSum(self,signal):
        """ A metric for estimating if the signal looks like noise """
        return sum(diff(signal))/sum(signal)

    def timeToStr(self,t):
        """ make a nicely formatted string from a time in seconds """
        if t>=1.0:
            return str(round(t,2))+"s"
        elif t>=1e-3:
            return str(round(t*1000,2))+"ms"
        else:
            return str(round(t*1e6,2))+"us"



class WinspecGainSpectrum(WinspecSpectrum):
    """ Subclass of Spectrum using the Winspec COM Type Library """
    def __init__(self, *args, **kwargs):
        super(WinspecGainSpectrum, self).__init__(*args, **kwargs)
        self.info["type"]="WinspecGainSpectrum"

    def getGain(self,x,y,param):
        """ Calculates the Hakki-Paoli gain """
        hp=HakkiPaoli(x,y,param)
        hp.updateProgress.connect(self.plotSubProgressAvailable)
        hp.plotDataReady.connect(self.sendPlotData)
        self.main.canvas.readyToDraw.connect(hp.readyToDraw)
        g=hp.gainCalculation()
        return g

    def getAllGains(self):
        """ Gets the Hakki-Paoli gain for each current and returns it as a list """
        numSpectra=len(self.data["iMeas"])
        x=[None]*numSpectra
        y=[None]*(numSpectra)
        self.mainPlotProgressStep=1/numSpectra
        for index in range(numSpectra):
            self.mainPlotProgress=index/numSpectra
            # Calculate the gain. In the future I'd like each iteration to work in a different thread, and for everything to just come together
            x[index],y[index]=self.getGain(self.data["wavelength"][:,index],self.data["intensity"][:,index],self.laserParam)
        return (x,y)

    def alphaParameterFromGain(self,x,y):
        """ Calculate the alpha parameter from the gain spectrum vs wavelength at different currents """
        # define a helper function
        def modeAlign(x1,x2,y1,y2):
            """ Aligns the modes of two Hakki-Paoli spectra so that they have same number of data points, and are at same position """
            # Trim x2 down to the same wavelength range as x1
            x2=x2[logical_and(x2<=max(x1),x2>=min(x1))]
            y2=y2[logical_and(x2<=max(x1),x2>=min(x1))]
            # x1 should now have one extra data point compared to x2, except for one special case
            if len(x1)==(len(x2)+1):
                # if left edges further apart than right, then remove the left mode from x1,y1
                if (x2[0]-x1[0]) >= (x1[-1]-x2[-1]):
                    x1=x1[1:]
                    y1=y1[1:]
                # otherwise remove the right mode from x1,y1
                else:
                    x1=x1[:-1]
                    y1=y1[:-1]
            # Special case: If measurement error on both sides, in opposite directions, possible for both left and right mode to be cut out from x2,y2
            elif len(x1)==len(x2)+2:
                # remove both the left and right mode from x1,y1 to match x2,y2
                x1=x1[1:-1]
                y1=y1[1:-1]
            else:
                self.main.canvas.plot(x1,y1,'o',x2,y2,'x')
                QtCore.QCoreApplication.processEvents()
                raise FabryPerotAlignmentError, "Aligning of Fabry-Perot modes failed"
            return (x1,x2,y1,y2)
        # calculate for each
        alpha=[] 
        for idx in range(len(x)-1):
            # Get the pair of currents to compare; here we reference everything to the first measurement instead of extracting incremental change
            x1=x[0]
            y1=y[0]
            x2=x[idx+1]
            y2=y[idx+1]
            # Trim down to the wavelength region of the shorter vector
            if len(x1) <= len(x2):
                x1,x2,y1,y2=modeAlign(x1,x2,y1,y2)
            else:
                x2,x1,y2,y1=modeAlign(x2,x1,y2,y1)
            # calculate alpha parameter
            alpha.append(-2*pi/self.laserParam["L"]*((x2-x1)/(y2-y1)/mean(diff(x2))))
        return alpha


    def fineAlign(self,method="powermeter",*args,**kwargs):
        """ Perform a fine align using the piezo controller, and include the amount of multimode interference in the optimization conditions"""
        if method=="powermeter":
            return super(WinspecGainSpectrum,self).fineAlign(*args,**kwargs)
        elif method=="winspec":
            self.sendStatusMessage("Checking the fine alignment...")
            winspecAnalyzer=self.osa
            winspecAnalyzer.setNumPoints(3072)
            winspecAnalyzer.setDataFilename()
            alignmentCurrent=self.info.get("fineAlignCurrent",ALIGNMENT_FINE_CURRENT_DEFAULT)
            self.smu.setCurrent(alignmentCurrent)
            tau=ALIGNMENT_TAU if self.cryostatOff else ALIGNMENT_TAU_LOWTEMP
            p0=self.main.piezoCoordinates
            # profitFunction=powerMeter.readPowerAuto(tau=tau)
            def profitFuncRipple():
                """ returns the peak intensity minus the sum of the ripple in each of the modes in the Fabry-Perot spectrum """
                wavelength,intensity,dict=winspecAnalyzer.obtainSpectrum(tau)
                maxIdxRaw=peakDetect(intensity)
                maxIdx=peakClean(wavelength,intensity,maxIdxRaw)
                ripplePeakIdx=setdiff1d(maxIdxRaw,maxIdx)
                #self.main.canvas.plot(wavelength,intensity,wavelength[maxIdxRaw],intensity[maxIdxRaw],"x",wavelength[maxIdx],intensity[maxIdx],"o")
                #QtCore.QCoreApplication.processEvents()
                # Go through each mode and calculate the magnitude of the ripple
                rippleSum=0.0
                for M in range(len(maxIdx)-1):
                    ripplePeakIdxM=ripplePeakIdx[logical_and(ripplePeakIdx>maxIdx[M],ripplePeakIdx<maxIdx[M+1])]
                    if len(ripplePeakIdxM)>0:
                        # Calculate difference between maximum ripple peak and minimum value of the current mode
                        rippleMagM=max(intensity[ripplePeakIdxM])-min(intensity[maxIdx[M]:maxIdx[M+1]])
                        peakMagM=intensity[maxIdx[M]]-min(intensity[maxIdx[M]:maxIdx[M+1]])
                        rippleSum+=rippleMagM
                return intensity.max()-10*rippleSum/len(maxIdx)
            p,power=self.piezoAlignObject.autoalign(p0,ALIGNMENT_FINE_RES,ALIGNMENT_FINE_SPAN,profitFunction=profitFuncRipple)
            finalProfit=profitFuncRipple()
            # Save the coodinates to the main object using a mutex in-case multi-threading is enabled
            with QReadLocker(self.lock):
                self.main.piezoCoordinates=p
            self.sendStatusMessage("Optimal position found at ("+str(round(p[0][0],3))+","+str(round(p[1][0],3))+") um with detected power of "+str(round(power*1e6,3))+"uW")
            winspecAnalyzer.setNumPoints(self.info["numLambdaPoints"])

    def getAllGainPeakEnergies(self,threshold=0):
        """ Returns the energies of the gain peaks for each current"""
        ir=self.data["iMeas"]/self.info["thresholdCurrent"]
        #hwp=array([self.fitGainPeak(idx)[0] for idx in range(len(self.data["iMeas"]))])
        #hwp=array([self.fitGainPeak(idx)[0] for idx in range(6,11)])
        hwp=array([self.fitGainPeak(idx)[0] for idx in where(logical_and(ir>0.55,ir<1.05))[0]])
        
        sleep(0.5)
        # TO DO: remove explicit dependence on thresholdCurrent being set
        return (self.data["iMeas"]/self.info["thresholdCurrent"],hwp)

    def fitGainPeak(self,idx,threshold=0):
        """ Fit a gaussian to the envelope of the spectrum """
        # Some constants which are necessary to get clean reliable results
        INTERNAL_LOSS=1200           # Laser internal loss in 1/m
        WINDOW_BANDWIDTH=20e-9      # Bandwidth in m for window of interest around peak wavelength
        MIN_LENGTH=25               # Minimum length of gain spectrum to consider worth fitting
        nullValue=(float('NaN'),float('NaN'),float('NaN'))
        inWindow=abs(self.data["wavelength"][:,idx]-self.getLasingWavelength(idx,method="peak"))<WINDOW_BANDWIDTH
        x,y=self.getGain(self.data["wavelength"][inWindow,idx],self.data["intensity"][inWindow,idx],self.laserParam)
        y+=INTERNAL_LOSS
        #self.main.canvas.plot(self.lambdaToE(x),y,'x')
        #QtCore.QCoreApplication.processEvents()
        if len(y)>MIN_LENGTH and sum((y/abs(y.max()))>threshold)>MIN_LENGTH:
            try:
                return self.fitGaussian(self.lambdaToE(x),y,threshold)
            except Exception as e:
                return nullValue
        else:
            return nullValue


    def plot(self,index=None,xLim=(-30,70),gLim=(-80,20),pLim=None,xAxisUnit="energy",title=None,offset=False,logscale=False):
        """ Prepares the Spectrum data for plotting, and emits a signal when finished for the mainwindow to draw the plot.
       Input parameters are:
       index=None -> index from data array to plot
       xLim=None -> tuple of min and max energies / wavelengths on x-axis relative to center point (in meV / nm respectively)
       gLim=None -> tuple of min and max gains on y-axis
       pLim1=None -> tuple of min and max values for spectrum power on y-axis (if included)
       xAxisUnit="energy" -> string to specify "energy" or "wavelength" as unit for x-axis
       title=None -> string to use for title if non-default title is desired
       offset=False -> flag whether to allow axis to be specified relative to some offset
       logscale=False -> flag whether to allow spectrum power to be plotted on log-scale
       """
        # Laser parameters for gain calculation. Set to None to disable plotting of the gain       
        # Mirror loss of cavity
        if self.laserParam!=None:
            alpham=1/2/self.laserParam["L"]*log(1/self.laserParam["R1"]/self.laserParam["R2"])
        # Get the plot index from self.main (note: this is just a hack because I can't seem to get it through the started signal of the QThread
        if index is None:
            try:
                index=self.main.currentPlotIndex
            except AttributeError as e:
                pass
        # Chop up the array if required
        if index!=None:
            numSpectra=1
            x=self.data["wavelength"][:,index]
            y=self.data["intensity"][:,index]
            iMeas=array([self.data["iMeas"][index]])
            T=self.data["temperature"][index]
        else:
            numSpectra=shape(self.data["wavelength"])[1]
            x=self.data["wavelength"]
            y=self.data["intensity"]
            iMeas=self.data["iMeas"]
            T=None if self.data["temperature"] is None else min(self.data["temperature"])
        # Get the threshold current if it was specified
        thresholdCurrent=self.info.get("thresholdCurrent",None)
        # Prepare plot for case of single spectrum
        if numSpectra==1:
            # I think this flattening was added as a dirty fix because I was seeing embedded single element arrays in x and y
            x=x.flatten()
            y=y.flatten()
            x0=self.info["Center"]
            if logscale:
                y=10*log10(y/1000) # dBm
                ylabel="Optical power (dBm)"
            else:
                if max(y)>1e-9:
                    y=y*1e9
                    ylabel="Optical power (nW)"
                else:
                    y=y*1e12
                    ylabel="Optical power (pW)"
            if title is None: 
                title="["+self.info["groupName"]+"] "
                if thresholdCurrent is None:
                    title="Optical power and gain vs wavelength spectrum: I = " + "{:0.2f}".format(iMeas[0]*1000) +"mA"
                else:
                    title="Optical power and gain vs wavelength spectrum: I = " + "{:0.2f}".format(iMeas[0]*1000) +"mA ("+"{:0.2f}".format(iMeas[0]/thresholdCurrent)+" $I_{th}$)"
            # Add the plot data to the dictionary
            if xAxisUnit=="energy":
                E0=self.lambdaToE(x0)*1000
                xAxis={"data":(self.lambdaToE(x)*1000,),"label":"Emission energy [meV]"}
                if xLim!=None: xAxis["limit"]=(E0+xLim[0],E0+xLim[1])
            else:
                xAxis={"data":((x-x0)*1e9,),"label":(str(x0*1e6)+ "um wavelength offset [nm]")}
                if xLim!=None: xAxis["limit"]=xLim
            yAxis={"data":(y,),"lineProp":("-",),"label":ylabel}
            # Include gain calculation if the laser parameters (L,R1,R2,n) are included
            if self.laserParam!=None:
                # Setup some progress tracking variables
                self.mainPlotProgress=0
                self.mainPlotProgressStep=1
                # Calculate the gain
                x2,y2=self.getGain(x,y,self.laserParam)
                # Add the data to a second axis
                if xAxisUnit=="energy":
                    x2Axis={"data":(self.lambdaToE(x2)*1000,self.lambdaToE(x2)*1000)}
                else:
                    x2Axis={"data":((x2-x0)*1e9,(x2-x0)*1e9)}
                y2Axis={"data":(y2/100,alpham/100*y2/y2),"lineProp":("ro-","r--"),"label":r"Net modal gain [cm$^{-1}$]","color":"r"}
                plotDictionary={"x":xAxis,"y":yAxis,"x2":x2Axis,"y2":y2Axis,"title":title}
            else:
                plotDictionary={"x":xAxis,"y":yAxis,"title":title}
        # Prepare plot for case of multi-spectra (here we don't bother plotting raw data since it would be too ugly, and instead just plot the gain)
        elif numSpectra>1 and self.laserParam!=None:
            # Setup some progress tracking variables
            x,y=self.getAllGains()
            # order in values of decreasing current
            order=argsort(iMeas)[::-1]
            iMeas=iMeas[order]
            x=[x[i] for i in order]
            y=[y[i] for i in order]
            lineProp=["o" for i in self.data["iMeas"]]
            if thresholdCurrent is None:
                legend=["{:0.2f}".format(i*1000)+"mA" for i in iMeas]
            else:
                legend=["{:0.2f}".format(i/thresholdCurrent)+"$I_{th}$" for i in iMeas]
            # Add the mirror loss term as well as the first element
            x.insert(0,array([(self.data["wavelength"]).min(),(self.data["wavelength"]).max()]))
            y.insert(0,array([(alpham),(alpham)]))
            lineProp.insert(0,"k--")
            legend.insert(0,r"$\alpha_m$")
            # Scale y-axis
            y=[yi/100 for yi in y]
            # Add the data to plot dictionary
            x0=self.info["Center"]
            if xAxisUnit=="energy":
                E0=self.lambdaToE(x0)*1000
                xAxis={"data":tuple([self.lambdaToE(xi)*1000 for xi in x]),"label":"Emission energy [meV]"}
                if xLim!=None: xAxis["limit"]=(E0+xLim[0],E0+xLim[1])
            else:
                # scale / shift data
                x0=self.info["Center"]
                x=[(xi-x0)*1e9 for xi in x]
                xAxis={"data":tuple(x),"label":(str(x0*1e6)+ "um wavelength offset [nm]")}
                if xLim!=None: xAxis["limit"]=xLim
            # Create dictionary specifying axis parameters
            yAxis={"data":tuple(y),"label":r"Net modal gain [cm$^{-1}$]","legend":legend,"lineProp":lineProp}
            if gLim!=None: yAxis["limit"]=gLim
            # Include temperature in title if it's included
            if title is None:
                title="["+self.info["groupName"]+"] "
                if T!=None:
                    title+=r"Net modal gain ($\Gamma g - \alpha_i$) vs wavelength spectrum" + " @ {:0.1f}".format(T) +"K"
                else:
                    title+=r"Net modal gain ($\Gamma g - \alpha_i$) vs wavelength spectrum"
            plotDictionary={"x":xAxis,"y":yAxis,"title":title}
        else:
            return
        # Emit a signal with data dictionary for the GUI to know what to plot
        self.sendPlotData(plotDictionary)
        # Need to fix this so that moveToThread() doesn't interfere with measurement
        self.finishedPlotting()
        self.sendPlotProgress(1)

    def curveFit(self,index=None):
        """ Return a function handle for gain spectrum from curve fit """
        # I'd like to move the plotting of the gain spectrum itself into this method so that I don't need to assume any arbitrary parameters
        index=range(size(self.data["wavelength"],1)) if index is None else array([index])
        xdata=[]
        ydata=[]
        iMeas=self.data["iMeas"]
        # Calculate gain spectrum
        for idx in index:
            lambdai,gi=self.getGain(self.data["wavelength"][:,idx],self.data["intensity"][:,idx],self.laserParam)
            Ei=self.lambdaToE(lambdai)
            xdata.append(Ei)
            ydata.append(gi)
        # Trim the data if needed
        xRange=[.92,.99]
        if xRange != None:
            for idx in range(len(xdata)):            
                inRange=logical_and(xdata[idx]>=xRange[0],xdata[idx]<=xRange[1])
                xdata[idx]=xdata[idx][inRange]
                ydata[idx]=ydata[idx][inRange]
        # Reverse the data in order of decreasing current so that the legend lines up with the data on the graph
        xdata=xdata[::-1]
        ydata=ydata[::-1]
        iMeas=iMeas[::-1]
        # Fit the gain spectra
        material=gainmedium.InAs()
        param=gainmedium.DEFAULT_PARAM
        param["material"]=material.consts
        medium=gainmedium.QDGainMedium(param)
        T=self.data["temperature"][idx]
        medium.setTemperature(T)
        netgainfit,param=gainmedium.fitGainSpectrum(medium,xdata,ydata,iMeas[index])        
        # Add the data to plot dictionary
        E0=self.lambdaToE(self.info["Center"])*1000
        legend=["{:0.2f}".format(i*1000)+"mA" for i in iMeas[index]]
        #lineProp=["o" for i in iMeas[index]]
        colorOrder=['b','g','r','c','m','y','k']
        numCurr=len(iMeas[index])
        lineProp=["o"+colorOrder[mod(i,len(colorOrder))] for i in range(numCurr)]+["-"+colorOrder[mod(i,len(colorOrder))] for i in range(numCurr)]
        x=[xi*1000 for xi in xdata]
        x=x+x               
        y=[yi/100 for yi in ydata]
        yfit=[yi/100 for yi in netgainfit]
        y=y+yfit
        # DEBUG ONLY
        #alphaI=500
        #Gamma=.06
        #y=medium.netToMaterialGain(ydata)
        #y=medium.gainFromCurrent(medium.jFromI(1e-3),x)
        #y=[(ydata[0]+alphaI)/Gamma]
        #x=[x[0]]
        # END DEBUG ONLY
        xAxis={"data":tuple(x),"label":"Emission energy [meV]","limit":((E0-50,E0+50) if xRange is None else [xi*1000 for xi in xRange])}
        #yAxis={"data":tuple(y),"label":r"Net modal gain [cm$^{-1}$]","limit":(-80,20)} #"legend":legend,"lineProp":lineProp,
        yAxis={"data":tuple(y),"label":r"Net modal gain [cm$^{-1}$]","limit":(-80,20),"legend":legend,"lineProp":lineProp}
        title=r"Net modal gain ($\Gamma g - \alpha_i$) vs wavelength spectrum" + " @ {:0.1f}".format(T) +"K" + " optimization parameters: " + str(param)
        plotDictionary={"x":xAxis,"y":yAxis,"title":title}
        # Emit a signal with data dictionary for the GUI to know what to plot
        self.sendPlotData(plotDictionary)
        self.sendPlotProgress(1)

class ManualWinspecSpectrum(WinspecGainSpectrum):
    """ Subclass of Spectrum using the Winspec COM Type Library and allowing manual switching of the current"""
    def __init__(self, *args, **kwargs):
        kwargs["controlCurrent"]=False
        super(ManualWinspecSpectrum, self).__init__(*args, **kwargs)
        self.info["type"]="ManualWinspecSpectrum"

class RinSpectrum(Spectrum):
    """ Subclass of Spectrum using the Anritsu ESA and SMU to do perform Relative Intensity Noise measurement vs. current """
    def __init__(self, *args, **kwargs):
        super(RinSpectrum, self).__init__(*args, **kwargs)
        self.info["type"]="RinSpectrum"
        self.data["photoCurrent"]=zeros(self.info["numCurrPoints"])
        self.info["highResMode"]=True
        self.info["measureFeedback"]=True

    def finishedWork(self, *args, **kwargs):
        if self.info["highResMode"]:
            # do a second high res measurement before finishing the measurement
            self.sendStatusMessage("Taking high resolution measurements...")
            self.acquireHighResData()
        super(RinSpectrum, self).finishedWork(*args, **kwargs)

    def acquireData(self,*args, **kwargs):
        if self.info["measureFeedback"]:
            pm=PrimaryPowerMeter()
            smu=SMU(defaultCurrent=FEEDBACK_CALIBRATION_CURRENT)
            smu.setCurrent(FEEDBACK_CALIBRATION_CURRENT)
            smu.setOutputState(True)
            power=pm.readPowerAuto()
            defaultReferencePower=1.616e-3  # TODO: store/restore this from preferences
            defaultFeedback=10*log10(power/defaultReferencePower)
            # Ask user to confirm the reference level for feedback measurement
            feedbackRefPower,status=QtGui.QInputDialog.getDouble(None,"Ref power",
                    "Enter the 0dB ref power (mW) \nCurrent feedback level = "+"{:0.2f}".format(defaultFeedback)+" dB",
                        defaultReferencePower*1000,0,inf,3)
            # Measure the feeback amount if the user didn't abort
            if status:
                smu.setOutputState(True)
                self.data["feedbackAmount"]=fb=pm.readPowerAuto()*1000/feedbackRefPower
                self.info["Name"]=self.info["Name"]+" ({:0.2f}dB feedback)".format(10*log10(fb))
            else:
                print("Measurement aborted")
                return

        return super(RinSpectrum, self).acquireData(*args,**kwargs)

    def acquireHighResData(self):
        # setup high res measurement
        nCurr=self.info["numCurrPoints"]
        mLambda=self.info["numLambdaPoints"]
        # Setup the spectrum analyzer and SMU and take measurements
        try:
            # Create instance and initialize instrument for capturing spectral data
            instrument=self.initInstrument()
            # Set higher resolution values for frequency and span
            self.osa.setCenter(0.9)
            self.osa.setSpan(1.8)
            # Create empty data arrays for high res data
            self.data["freqHighRes"]=zeros((mLambda,nCurr))
            self.data["powerHighRes"]=zeros((mLambda,nCurr))
            for i in range(nCurr):
                # Cancel the measurement if it has been aborted
                QtCore.QCoreApplication.processEvents()
                self.smu.setCurrent(self.iSet[i],self.info["Vcomp"])
                try:
                    # Use highResMode flag to indicate that the data should be put into special arrays
                    self.acquireSingleSpectrum(instrument,i,highResMode=True)
                except MeasurementAbortedError:
                    # If measurement aborted cancel everything immediately without saving any data
                    self.sendStatusMessage("Aborting spectrum measurement...")
                    self.aborted.emit()
                    return
                except Exception as e:
                    # For other exceptions, salvage data then re-raise the existing error with proper call stack
                    self.savePartialData(i)
                    raise
        except IOError, e:
            QtGui.QMessageBox.warning(None,"VisaIOError",("There was an instrument communication error. Please check all the instruments are connected properly:\n %1").arg(e.args[0]))
                # remove the smu so that it returns to user control
        del self.smu, self.osa
        try: 
            del self.dmm
        except Exception as e:
            pass

    def initInstrument(self):
        """ Creates a reference to the instrument and initializes it to settings required before the start of a measurement """
        self.smu=SMU(autoZero=True,defaultCurrent=ALIGNMENT_CURRENT,currRange=1)
        self.osa=osa=SpectrumAnalyzer()
        osa.setCenter(self.info["Center"]/1e9)
        osa.setSpan(self.info["Span"]/1e9)
        osa.setAttenuator(False,0)
        osa.setRbw(14) # 3MHz
        osa.setVbw(4) # 10kHz
        # leave sweep time set to auto. osa.setSweepTime(False,1000)
        self.dmm=DMM()
        self.dmm.setAuto()
        return osa
    def acquireSingleSpectrum(self,osa,idx,highResMode=False):
        """ Acquires a single spectrum and sets data in self.data["wavelength"], self.data["intensity"] """
        noiseBandwidth=self.osa.getNoiseBandwidth()
        if idx == 0:
            # Acquire background level on first measurement
            self.smu.setOutputState("OFF")
            f,bkg=self.osa.obtainSpectrum()
            thermalNoisePower=bkg/noiseBandwidth
            self.smu.setOutputState("ON")
        x,y=self.osa.obtainSpectrum()
        photoCurrent = self.dmm.measure()/self.info["dcConversion"]
        if highResMode:
            # Optionally store the data in a separate array from main data for high resolution window
            self.data["freqHighRes"][:,idx]=x
            self.data["powerHighRes"][:,idx]=y/noiseBandwidth
            if idx==0: self.data["thermalNoisePowerHighRes"]=thermalNoisePower
        else:
            # Store the data in the main array
            self.info["noiseBandwidth"]=noiseBandwidth
            if idx==0: self.data["thermalNoisePower"]=thermalNoisePower
            # Measure DC component and calculate shot noise component. Assume 50ohm matched load
            self.data["photoCurrent"][idx]=photoCurrent
            # Measure AC component. NOTE: using "wavelength" key, but actually frequency!
            # TODO: Change key names!
            self.data["wavelength"][:,idx]=x
            self.data["intensity"][:,idx]=y/noiseBandwidth
        

    def plot(self,index=None,xLim=None,pLim=None,xAxisUnit="energy",title=None,offset=False,logscale=True, highResMode=False, reverse=False):
        numSpectra=shape(self.data["wavelength"])[1]
        if index is None:
            if (not highResMode or not "freqHighRes" in self.data):
                # Use ordinary data
                startIdx=nonzero(self.data["wavelength"] >= RIN_MIN_FREQ)[0][0]
                x=[self.data["wavelength"][startIdx:,i]/1e9 for i in range(numSpectra)]
                y=[self.powerDensityToRin(self.data["intensity"][startIdx:,i],self.data["thermalNoisePower"][startIdx:],self.data["photoCurrent"][i])
                    for i in range(numSpectra)]
            else:
                # Use high resolution data
                startIdx=nonzero(self.data["freqHighRes"] >= RIN_MIN_FREQ)[0][0]
                x=[self.data["freqHighRes"][startIdx:,i]/1e9 for i in range(numSpectra)]
                y=[self.powerDensityToRin(self.data["powerHighRes"][startIdx:,i],self.data["thermalNoisePowerHighRes"][startIdx:],self.data["photoCurrent"][i])
                    for i in range(numSpectra)]
            iMeas=self.data["iMeas"]
            if reverse:
                order=argsort(iMeas)[::-1]
                iMeas=iMeas[order]
                x=[x[i] for i in order]
                y=[y[i] for i in order]
            lineProp=["x-" for i in self.data["iMeas"]]
            legend=["{:0.0f}".format(iMeas[i]*1000)+"mA" for i in range(len(iMeas))]
            yAxis={"data":tuple(y),"label":"Relative Intensity Noise (dB/Hz)","legend":legend,"lineProp":lineProp}
            if title is None:
                title=r"RIN vs frequency and current"
        else:
            if (not highResMode or not "freqHighRes" in self.data):
                startIdx=nonzero(self.data["wavelength"] >= RIN_MIN_FREQ)[0][0]
                x=(self.data["wavelength"][startIdx:,index]/1e9,)
                y=(self.powerDensityToRin(self.data["intensity"][startIdx:,index],self.data["thermalNoisePower"][startIdx:],self.data["photoCurrent"][index]),)
            else:
                startIdx=nonzero(self.data["freqHighRes"] >= RIN_MIN_FREQ)[0][0]
                x=(self.data["freqHighRes"][startIdx:,index]/1e9,)
                y=(self.powerDensityToRin(self.data["powerHighRes"][startIdx:,index],self.data["thermalNoisePowerHighRes"][startIdx:],self.data["photoCurrent"][index]),)
            #iMeas=[self.data["iMeas"][index]]
            yAxis={"data":tuple(y),"label":"Relative Intensity Noise (dB/Hz)"}
            if title is None:
                title=r"RIN vs frequency @ " + str(self.data["iMeas"][index]*1000) + "mA"
        xAxis={"data":tuple(x),"label":"frequency [GHz]"}
        # Include temperature in title if it's included

            #if T!=None:
            #    title+=" @ {:0.1f}".format(T) +"K"
        plotDictionary={"x":xAxis,"y":yAxis,"title":title}
        # Emit a signal with data dictionary for the GUI to know what to plot
        self.sendPlotData(plotDictionary)
        # Need to fix this so that moveToThread() doesn't interfere with measurement
        self.finishedPlotting()
        self.sendPlotProgress(1)
    
    def wattsToDbm(self,power):
        """ Return the power in Watts given power in dBm """
        return 10*log10(power/1e-3)

    def powerDensityToRin(self,power,thermalNoise, photoCurrent, filter=True):
        """ Return the relative intensity noise given:
         power: spectral power density due to light in W/Hz
         thermalNoise: SPD due to thermal noise in specan, etc in W/Hz
         photoCurrent: photocurrent in amperes generated by photodetector
         """
        # Laser Noise
        Pl = self.wattsToDbm(abs(power-thermalNoise))
        # Electrical power in dBm of photocurrent into matched 50ohms
        Pe = self.wattsToDbm((photoCurrent)**2*50/2*self.info["preampGain"])
        # Laser RIN
        rin = Pl - Pe
        # Filter values below the noise floor, replacing with noise floor
        if filter:
            noiseMean=mean(thermalNoise)
            noiseStd=std(thermalNoise)
            noiseThreshold=2*noiseStd
            valid = (power-thermalNoise) > noiseThreshold
            for idx in range(len(valid)):
                if not valid[idx]: rin[idx]=self.wattsToDbm(noiseThreshold)-Pe
        return rin

class MeasurementAbortedError(Exception): pass
class SignalTooStrongError(Exception): pass
class SignalTooWeakError(Exception): pass
class FabryPerotAlignmentError(Exception): pass

def peakGainWorker(idx,objList):
    """ Wrapper around WinspecGainSpectrum.getAllGainPeakEnergies() for use with multiprocessing module """
    print(str(idx)+" started")
    result=objList[idx].getAllGainPeakEnergies()
    print(str(idx)+" finished")
    return result

def peakGainWrapper(objList):
    pool = Pool(processes=cpu_count())
    # Run calculation on pool, sending the index of current value to worker function to use
    wrapperFunction=partial(peakGainWorker,objList=objList)
    outArgs=pool.map(wrapperFunction,range(len(objList)))
    pool.close()
    pool.join()
    return outArgs

class DummySMU(object):
    def __init__(self):
        self.current=0
    def setCurrent(self,current,vComp=None):
        newCurrent,status=QtGui.QInputDialog.getDouble(None,"Enter the measured value of the current (mA): ", "Set Current",current*1000,0,inf,3)
        self.current=newCurrent/1000
    def measure(self):
        return (0,self.current)
    def setOutputState(self,state):
        result=QtGui.QMessageBox.information(None,"Set output state","Set the state of the current source to "+str(state),QtGui.QMessageBox.Ok|QtGui.QMessageBox.Cancel)
