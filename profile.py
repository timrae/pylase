from __future__ import division
from PyQt4 import QtCore, QtGui
import time, inspect
import numpy as np
from measurement import LIV, AdvantestSpectrum, WinspecSpectrum, WinspecGainSpectrum, SignalTooWeakError



TEMPERATURE_ERROR_THRESHOLD=5          # Temperature error below which we start to count waitTime [K]
TEMP_STABILITY_THRESHOLD=0.1
TEMP_REMEASUREMENT_INTERVAL=1          # Interval at which we remeasure the temperature to see if the set point has been reached [s]
BUFFER_LEN=20
           
class Profile(QtCore.QObject):
    """ Class which controls a specific measurement profile """
    testProgress=QtCore.pyqtSignal(float)
    testStatus=QtCore.pyqtSignal(str)
    profileProgress=QtCore.pyqtSignal(float)
    profileStatus=QtCore.pyqtSignal(str)
    # Forwarding signals
    finished=QtCore.pyqtSignal()
    canceled=QtCore.pyqtSignal()
    profileAborted=QtCore.pyqtSignal()
    profileError=QtCore.pyqtSignal()
    readyToDraw=QtCore.pyqtSignal()
    subProgressAvailable=QtCore.pyqtSignal(float)
    plotSubProgressAvailable=QtCore.pyqtSignal(float)
    plotDataReady=QtCore.pyqtSignal(dict)

    def __init__(self,tempController,parent,lock,*args, **kwargs):
        super(Profile, self).__init__(*args, **kwargs)
        self.tempController=tempController
        self.main=parent
        self.lock=lock
        self.tempSetPoints=np.array([])

    @QtCore.pyqtSlot()
    def canceled(self):
        """ Slot which cancels the measurement """
        self.running=False

    def sendProfileStatus(self,msg):
        print(msg)
        self.profileStatus.emit(msg)

    def moveToTemp(self,temperature,waitTime):
        """ Set the temperature, wait for it to reach its set point, then wait waitTime [minutes] for everything to stabilize """
        self.tempController.setTemperature(temperature)
        measBuffer=np.array([])
        measBuffer=np.append(measBuffer,self.tempController.getTemperature())
        self.testProgress.emit(0)
        self.testStatus.emit("Waiting for temperature to reach set-point")
        while not self.temperatureStable(temperature,measBuffer):
            time.sleep(TEMP_REMEASUREMENT_INTERVAL)
            QtCore.QCoreApplication.processEvents()
            measBuffer=np.append(measBuffer,self.tempController.getTemperature())[-BUFFER_LEN:]            
        self.testStatus.emit("Waiting "+str(waitTime)+" minutes for temperature to stabilize")
        t0=time.time()
        while (time.time()-t0) < waitTime*60:
            self.testProgress.emit((time.time()-t0)/waitTime/60*100)
            time.sleep(TEMP_REMEASUREMENT_INTERVAL)
            QtCore.QCoreApplication.processEvents()
        self.testProgress.emit(1)
        self.testStatus.emit("Temperature stabilized!")

    def temperatureStable(self,setTemperature,measBuffer):
        if len(measBuffer)<BUFFER_LEN:
            return False
        else:
            return abs(setTemperature-measBuffer[-1])<=TEMPERATURE_ERROR_THRESHOLD and \
                (measBuffer.max()-measBuffer.min()) <= TEMP_STABILITY_THRESHOLD



    def renderDictionary(self,rawDict,idx):
        """ Render any functions specified in dict """
        dict=rawDict.copy()
        for key in dict:
            if inspect.isfunction(dict[key]):
                dict[key]=dict[key](idx)
        return dict

    def run(self):
        """ Run the profile set by define() method """
        # Step through each temperature point
        self.define()
        self.numPoints=numPoints=len(self.tempSetPoints)
        self.allMeasurements=[]
        for idx in range(numPoints):
            self.idx=idx
            self.profileProgress.emit(idx/numPoints*100)
            self.sendProfileStatus("Moving to "+str(self.tempSetPoints[idx])+"K temperature point "+str(idx+1)+"/"+str(numPoints))
            self.moveToTemp(self.tempSetPoints[idx],self.tempWaitTimes[idx])
            # After setting the temperature, step through each measurement type
            self.allMeasurements.append([])
            for specIdx in range(len(self.measurementSpecs)):                
                # Initialize progress indicators
                self.testProgress.emit(0)
                # Get the specifications for and create the current measurement object
                spec=self.measurementSpecs[specIdx]
                measurement=spec["class"](self.renderDictionary(spec["info"],idx),parent=self.main,lock=self.lock)
                self.profileProgress.emit((idx+specIdx/len(self.measurementSpecs))/numPoints*100)
                self.sendProfileStatus("Test "+str(specIdx+1)+"/"+str(len(self.measurementSpecs))+" ("+spec["info"]["Label"]+ ") at "+str(self.tempSetPoints[idx])+ "K temperature point "+str(idx+1)+"/"+str(numPoints))
                # Forwarded signals
                measurement.progressMessage.connect(self.testStatus)
                measurement.progress.connect(self.testProgress)
                measurement.plotDataReady.connect(self.plotDataReady)
                measurement.aborted.connect(self.profileAborted)
                measurement.measError.connect(self.profileError)
                self.readyToDraw.connect(measurement.readyToDraw)
                # Acquire data and save each to db
                try:
                    measurement.acquireData()
                except SignalTooWeakError as e:
                    t0=time.time()
                    while (time.time()-t0) < 60*60:
                        self.sendProfileStatus("SignalTooWeakError occured; waiting 60min and trying again")
                        self.testProgress.emit((time.time()-t0)/60/60*100)
                        time.sleep(TEMP_REMEASUREMENT_INTERVAL)
                        QtCore.QCoreApplication.processEvents()
                    try:
                        measurement.acquireData()
                    except SignalTooWeakError as e:
                        raise
                self.main.session.saveToDB(measurement)
                self.allMeasurements[idx].append(measurement)
                # Plot the measurement
                measurement.plot()
                QtCore.QCoreApplication.processEvents()
                # Add each measurement the session object and re-render the tree
                self.main.session.append(measurement)
                self.main.populateTree(id(measurement))
                QtCore.QCoreApplication.processEvents()
        # Move back to room temperature and emit finished signal at end of the test
        #self.moveToTemp(300,0)
        self.finished.emit()

    ####### ---------------- Only modify code below -------------  ###################
    def define(self):
        """ User-editable definition of the temperature profile.
       Required variables to set: 
       self.tempSetPoints  -> temperature set points (in Kelvin)
       self.tempWaitTimes -> time to wait after the temperature set point has been reached (in minutes)
       self.measurementSpecs -> List of dictionaries, each dictionary having:
             "class" -> reference to the class from the measurement module
             "info" -> a dictionary with the usual info parameters.
                A function can be provided vs index number which allows for different parameter values at different temperatures
       """
        # List with a dictionary for each test type giving the test specifications
        self.measurementSpecs=specs=[]
        # Set the temperature set points and wait times
        self.tempSetPoints=np.hstack((np.flipud(np.arange(30,310,10)),(np.arange(20,410,10))))
        #self.tempSetPoints=np.arange(20,300,20)
        self.tempWaitTimes=np.ones(len(self.tempSetPoints))*90
        self.tempWaitTimes[0]=60*12
        # Setup some common values used in multiple specifications
        groupName="QLF1326-AA-1 Sample 3820 hysteresis test"
        testName = lambda idx: str(self.tempSetPoints[idx])+"K"
        plambda=np.array([  5.57345718e-07,   1.74291749e-04,   1.19294891e+00-.02])
        centerLambda= lambda idx: round(np.polyval(plambda,self.tempSetPoints[idx]),3)/1e6
        def istartGainSpectrum(idx):
            return 0.1*getThresholdCurrent(idx)
        def istopGainSpectrum(idx):
            return 1.1*getThresholdCurrent(idx)
        def istartSpectrum(idx):
            return 0.9*getThresholdCurrent(idx)
        def istopSpectrum(idx):
            return 1.1*getThresholdCurrent(idx)
        def fineAlignCurrent(idx):
            return 0.6*getThresholdCurrent(idx)
        def getThresholdCurrent(idx):
            LIV_TEST_POS=0    # index of LIV test in self.allMeasurements... set to 0 if LIV is first test
            i0=self.allMeasurements[idx][LIV_TEST_POS].getThresholdCurrent()[0]
            return i0
        # LIV Test
        specs.append({"class":LIV,"info":{"Label":"LIV","groupName":groupName,"Name":testName,"Istart":0.1e-3,"Istop":20e-3,"numCurrPoints":100,"Vcomp":4,"roughAlign":True}})
        #specs.append({"class":LIV,"info":{"Label":"LIV","groupName":groupName,"Name":testName,"Istart":1e-3,"Istop":50e-3,"numCurrPoints":200,"Vcomp":4,"roughAlign":True}})
        # Gain Spectrum
        """specs.append({"class":WinspecGainSpectrum,"info":{
            "Label":"Gain Spectrum (Winspec)","groupName":groupName,"Name":testName,"Istart":istartGainSpectrum,"Istop":istopGainSpectrum,
                "numCurrPoints":11,"Vcomp":3.5,"Center":centerLambda,"Resolution":.0208/1e9,"numLambdaPoints":11264,"roughAlign":True,
                    "thresholdCurrent":getThresholdCurrent,"fineAlign":True,"fineAlignCurrent":fineAlignCurrent}})"""
        
        # Lasing Spectrum
        
        """specs.append({"class":WinspecSpectrum,"info":{
            "Label":"Spectrum (Winspec)","groupName":groupName,"Name":testName,"Istart":istartSpectrum,"Istop":istopSpectrum,
                "numCurrPoints":3,"Vcomp":5,"Center":centerLambda,"Resolution":0.0711/1e9,"numLambdaPoints":3072,"thresholdCurrent":getThresholdCurrent}})"""
        


class ProfileProgressDialog(QtGui.QDialog):
    canceled=QtCore.pyqtSignal()
    def __init__(self,*args,**kwargs):
        super(ProfileProgressDialog, self).__init__(*args,**kwargs)
        self.setWindowTitle("Temperature Profile Progress")
        mainLayout=QtGui.QVBoxLayout()
        self.testProgressLabel=QtGui.QLabel("Test progress: ")
        self.testProgressBar=QtGui.QProgressBar()
        self.testProgressBar.setMaximum(100)
        self.profileProgressLabel=QtGui.QLabel("Profile progress: ")
        self.profileProgressBar=QtGui.QProgressBar()
        self.profileProgressBar.setMaximum(100)
        self.abortedButton=QtGui.QPushButton("Abort Test")
        self.abortedButton.clicked.connect(self.canceled)
        mainLayout.addWidget(self.profileProgressLabel)
        mainLayout.addWidget(self.profileProgressBar)
        mainLayout.addWidget(self.testProgressLabel)
        mainLayout.addWidget(self.testProgressBar)
        mainLayout.addWidget(self.abortedButton)
        #self.lock=QtCore.QReadWriteLock()
        self.setLayout(mainLayout)
        self.show()
        