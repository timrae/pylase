from __future__ import division
import numpy as np
import os, time
from scipy import constants as scipycsts
# Ignore import errors so that the public methods can be used even when winspec isn't installed
try:
    from winspec import Winspec, CommError, readDetectorDefinition, WINSPEC_DEFAULT_DIR
    from drivepy.thorlabs.fw102c import FilterWheel
except ImportError as e:
    print("Error importing from winspec... \n" + e.args[0])
from PyQt4 import QtCore

# Block size to use for finding the peak luminesence
PEAK_LUM_BLOCK_SIZE = 5
# Window defining the min and max boundaries for the optimal signal strength
MAX_COUNTS=2**16            # 16-bit detector, so maximum number of counts is 2^16
OPTIMAL_SIGNAL_WIN=(0.5*MAX_COUNTS,0.9*MAX_COUNTS)
# Max measurement time we are willing to accept
WINSPEC_MAX_MEAS_TIME=100.0
# List of tuples containing the filter wheel position, gain, and exposure time
GAIN_SETTINGS=[(1, 2, WINSPEC_MAX_MEAS_TIME), (1, 2, 10.0), (1, 2, 1.0), (1, 2, 0.1), (1, 1, 0.2), (1, 1, 0.02), (2, 1, 0.2), (3, 1, 0.2), (4, 1, 0.2), (5, 1, 0.2), (5, 1, 2e-2), (5, 1, 2e-3), (5, 1, 2e-4), (5, 1, 2e-5), (5, 1, 10e-6), (5, 1, 1e-6)]
# Dictionary giving the attenuation of each filter wheel position for absolute power comparisons
ATTENUATION={1:1,2:1e-2,3:1e-3,4:1e-4,5:1e-5,6:1}
# Dictionary giving the approximate gain of each Winspec gain setting
# TO DO: Make a more accurate model for the absolute gain, because this is shit!
DETECTOR_GAIN={1:1,2:30}
""" Default values """
DEFAULT_RANGE=4                 # Default value for the range
DEFAULT_TAU=1                   # Default time constant [ms]
DEFAULT_TIMEOUT=60              # Default timeout [s]
DEFAULT_EFFICIENCY=0.05         # Default value for the efficiency for conversion between cps and power

# Some helper methods which can also be imported from the module
def photonEnergy(wavelength):
    """ energy of a single photon with specified wavelength """
    return scipycsts.h*scipycsts.c/wavelength

def calculateOpticalEfficiency(wavelength,cps,totalPower):
    """ Calculate optical efficiency assuming the whole spectrum has been captured, and 
    define efficiency as the ratio between spectral power sum and power meter reading"""
    return sum(np.max(cps,0)*photonEnergy(wavelength))/totalPower

def cpsToWatts(wavelength,cps,efficiency):
    """ Convert from counts per second to watts (= numPhotons/s *photonEnergy) """
    # TODO: take into account measurement function
    return photonEnergy(wavelength)*cps/efficiency

def wattsToCPS(wavelength,watts,efficiency):
    """ Convert from watts to counts per second """
    return watts*efficiency/photonEnergy(wavelength)

class WinspecAnalyzer(QtCore.QObject):
    """ High level convenience class for Winspec which gives it auto-range capability and conversion from cps to watts etc """
    updateProgress=QtCore.pyqtSignal(float)
    statusMessage=QtCore.pyqtSignal(str)
    plotDataReady=QtCore.pyqtSignal(dict)
    def __init__(self,inputStateSwitch=None,rawDataDir=WINSPEC_DEFAULT_DIR,*args,**kwargs):
        super(WinspecAnalyzer, self).__init__(*args,**kwargs)
        self._connection=Winspec()
        # self.inputStateSwitch allows the analyzer to turn on and off the optical signal
        self.inputStateSwitch=inputStateSwitch if inputStateSwitch!=None else self._connection.setMirrorState
        # self.attenuator controls an external attenuator with controllable attenuation
        self.attentuator=FilterWheel()
        # Set some default values
        self.setRange(DEFAULT_RANGE,forceSet=True)        
        self.efficiency=DEFAULT_EFFICIENCY
        self.running=True
        self.numSpectra=1
        self.gratingNumber=self._getGratingNumber()
        self.centerLambda=self.getCenter()
        # Set the Winspec filename to temporary
        self.rawDataDir=rawDataDir
        self.setDataFilename()
        self.setBackgroundFilename()
        self._connection.setOverwriteWarning(False)
        self.roi = None
     
    def readPowerAuto(self,*args, **kwargs):
        """ Read a Winspec spectrum, automatically setting the gain and exposure time to reasonable values, and return the power """
        wavelength,counts, dict=self.readSingleWinspecSpectrumAuto(*args,**kwargs)
        cps=counts/self.getExposureTime()
        return sum(cpsToWatts(wavelength,cps,self.efficiency))

    def obtainSpectrum(self,tau=DEFAULT_TAU,calibratedPower=None,timeout=DEFAULT_TIMEOUT):
        """ Acquire a spectrum by gluing together as many sub-spectra as necessary to get the full span.
        Uses the currently set center,span,and resolution in the instance object.
        Return the wavelength [m], power [W], and a dictionary containing useful information about the measurement for storage """
        # Force the physical settings of Winspec to be that of current range
        self.setRange(self.rangeIndex,forceSet=True)
        self.inputStateSwitch(True)
        # Acquire measurements
        if self.numSpectra == 1:
            wavelength,counts,spectrumDict=self.readSingleWinspecSpectrumAuto(tau)
        else:
            # Setup empty variables to hold the data
            pixels=self._connection.getNumberOfPixels()
            wavelength=np.zeros(self.numSpectra*pixels)
            counts=np.zeros(self.numSpectra*pixels)
            # Acquire the central spectrum
            assert (self.numSpectra % 2)!=0
            centerIndex=int((self.numSpectra-1)/2)
            self._setDataFilename(self.dataFilename+"_"+str(centerIndex))
            wavelength_i,counts_i,spectrumDict=self.readSingleWinspecSpectrumAuto(tau)
            wavelength[pixels*centerIndex:pixels*(centerIndex+1)]=wavelength_i
            counts[pixels*centerIndex:pixels*(centerIndex+1)]=counts_i
            # Find the center position we need to get all the other spectra to lineup nicely
            allCenterLambda=self.findCenterWavelengths(self.numSpectra,self.centerLambda,min(wavelength_i),max(wavelength_i))
            # Now measure the rest of the spectra, but using identical settings from the central spectrum
            for idx in range(self.numSpectra):
                if idx != centerIndex:
                    # abort the test if that's what the user wants
                    if not self.running:
                        raise MeasurementAbortedError
                    # update sub-progress
                    self.updateProgress.emit((idx+1.0)/(self.numSpectra+1))
                    # set the filename
                    self._setDataFilename(self.dataFilename+"_"+str(idx))
                    self.statusMessage.emit("Acquiring data for subspectrum " + str(idx+1)+"/"+str(self.numSpectra))
                    self._setCenter(allCenterLambda[idx])
                    wavelength_i,counts_i,spectrumDict_i=self.readSingleWinspecSpectrumAuto(tau,rangeMode="fixed")
                    wavelength[pixels*idx:pixels*(idx+1)]=wavelength_i
                    counts[pixels*idx:pixels*(idx+1)]=counts_i
                    self.plotDataReady.emit({"x":{"data":wavelength_i,"label":"Wavelength [nm]"},"y":{"data":counts_i,"label":"counts"}})
                    QtCore.QCoreApplication.processEvents()
            # move the spectrometer back to the center
            self._setCenter(self.centerLambda)
        # convert wavelength from nm to m
        wavelength=wavelength/1e9
        # Calculate CPS
        cps=counts/self.getExposureTime()/self.getAttenuation()/self.getAbsoluteGain()
        # If a calibration power was specified then calculate the efficiency from it
        if calibratedPower!=None:
            self.efficiency=calculateOpticalEfficiency(wavelength,cps,calibratedPower)
        # Calculate the absolute power using the efficiency (a default value is used if calibratedPower not given)
        intensity=cpsToWatts(wavelength,cps,self.efficiency)
        # Add some more stuff to spectrumDict
        spectrumDict["efficiency"]=self.efficiency
        spectrumDict["SNR"]=max(counts)/np.std(spectrumDict["noiseFloor"])
        # Return the final result
        return (wavelength,intensity,spectrumDict)                    

    def readSingleWinspecSpectrumAuto(self,tau=DEFAULT_TAU,timeout=DEFAULT_TIMEOUT,rangeMode="auto", mode=None):
        """ Reads the counts using auto-range functionality and averaged over specified time interval tau in ms, remeasuring as required if any errors.
        A timeout can be specified in seconds for the auto-range and re-measure, where we give up on trying to find a more accurate reading. 
        If timeout occurs during auto-ranging, it probably means the power is fluctuating too much with time, and so tau should be increased."""
        if mode: print("Mode argument " + mode + " ignored... winspec automatically returns mean")
        if self.has2dDetector() and not self.roi: raise ValueError, "You must set the ROI when using a 2D detector"
        self.t0=time.time()
        # Automatically remeasure if there was a comm. error until timeout occurs
        while 1:
            try:
                wavelength,counts,spectrumDict=self._readSingleWinspecSpectrumAuto(tau,timeout,rangeMode)
                break
            except CommError as e:
                if time.time()-self.t0 < timeout:
                    pass
                else:
                    # If timeout occurs, re-raise the (same) error
                    raise
        del self.t0
        return (wavelength, counts, spectrumDict)

    def _readSingleWinspecSpectrumAuto(self,tau,timeout,rangeMode):
        """ Read a single spectrum with the current range. If the SNR is sub-optimal then change range and recurse.
        tau defines the minimum integration period in ms
        timeout defines a timeout for the auto-range to prevent oscillation between different range states
        rangeMode can take values ('auto','fixed','optimum') where optimum uses a custom exposure time to get best SNR """
        # Read a single spectrum, averaged of time interval tau
        if self.bgMeasRequired:
            # Turn off the input signal, measure background, then turn it back on again
            self.inputStateSwitch(False)
            self._connection.acquireBackgroundSpectrum()
            self.inputStateSwitch(True) 
            self.bgMeasRequired = False
        wavelengthData,counts,spectrumDict=self._connection.acquireSpectrum(self.accumulations(tau))
        # Increase the range if signal too large
        if spectrumDict["saturating"] or (rangeMode=="auto" and max(counts) > 0.9*(2**16 - max(spectrumDict["noiseFloor"]))):
            if self.rangeIndex<(len(GAIN_SETTINGS)-1) and rangeMode!="fixed":
                self.setRange(self.rangeIndex+1)
                return self._readSingleWinspecSpectrumAuto(tau,timeout,rangeMode)
            else:
                raise CommError, "The measured power was outside the measurement range with rangeMode=%s"%rangeMode
        # Reduce the range if power smaller than 5% of the measurement range and no timeout has occured
        elif rangeMode!="fixed" and spectrumDict["maxSample"] < .05*MAX_COUNTS and self.rangeIndex > 0 and (time.time()-self.t0)<timeout:
            self.setRange(self.rangeIndex-1)
            return self._readSingleWinspecSpectrumAuto(tau,timeout,rangeMode)
        # If rangeMode=="optimum" and no timeout, check the signal is inside optimal SNR window, setting custom exposure if required
        elif rangeMode=="optimum" and self.rangeIndex > 0 and (spectrumDict["maxSample"] < OPTIMAL_SIGNAL_WIN[0] or spectrumDict["maxSample"] > OPTIMAL_SIGNAL_WIN[1]) and (time.time()-self.t0)<timeout:
            maxCPS=spectrumDict["maxSample"]/getExposureTime()
            noiseMaxCPS=max(spectrumDict["noiseFloor"])/getExposureTime()
            t=min(0.8*MAX_COUNTS/(maxCPS+noiseMaxCPS),WINSPEC_MAX_MEAS_TIME)
            self.setExposureTime(t)
            return self._readSingleWinspecSpectrumAuto(tau,timeout,rangeMode)
        # Otherwise return the measured data
        else:
            return (wavelengthData,counts,spectrumDict)

    def setRange(self,rangeIndex,forceSet=False):
        """ Set the power range, where rangeIndex is the index in the global variable GAIN_SETTINGS, which gives a tuple specifying gain parameters"""
        assert type(rangeIndex)==int
        attenuation,gain,exposure=GAIN_SETTINGS[rangeIndex]
        if forceSet or attenuation!=self.getAttenuatorPosition(): 
            self.attentuator.setPosition(attenuation)
        if forceSet or gain!=self.getGainSetting(): 
            self._connection.setGain(gain)
            self.bgMeasRequired = True
        if forceSet or exposure!=self.getExposureTime():
            self._connection.setExposureTime(exposure)
            self.bgMeasRequired = True
        self.rangeIndex=rangeIndex

    def autoSetROI(self):
        # TODO: implement this
        # image = self._connection.acquireImage()
        # Find either max x pixel strip or the middle of the saturating strip
        # Need to acquire image background before entering this method
        roi = (222,229)
        self.setROI(roi)
        
    def setROI(self, roi):
        self.roi = roi
        if self.has2dDetector(): self._connection.setVerticalROI(*roi)

    def measureOptimalCenter(self, tau = DEFAULT_TAU):
        """ Use the lowest resolution grating to find the wavelength of maximum luminesence """
        grating = self._getGratingNumber()
        self._setGratingNumber(3)
        wavelength,counts,spectrumDict=self.readSingleWinspecSpectrumAuto(tau)
        maxIdx = self._argMaxBlock(counts, PEAK_LUM_BLOCK_SIZE)
        self._setGratingNumber(grating)
        return wavelength[maxIdx]

    def _argMaxBlock(self, data, blockSize):
        """ Find the index of the data array such that the sum of the elements in the block centred at the index is global max """
        if len(data) < blockSize: return np.argmax(data)
        blockSum = np.sum(data[:blockSize])
        maxSum = blockSum
        maxIdx = blockSize - 1
        for i in xrange(blockSize, len(data)):
            blockSum -= data[i-blockSize]
            blockSum += data[i]
            if blockSum > maxSum:
                maxSum = blockSum
                maxIdx = i
        return maxIdx - blockSize//2


    def setDataFilename(self,filename="temp"):
        """ Sets the main filename relative to self.rawDataDir """
        self.dataFilename=filename
        self._setDataFilename(filename)        
    
    def _setDataFilename(self,filename):
        """ Sets the data filename without modifying self.dataFilename """
        self._connection.setDataFilename(self.rawDataDir,filename+".SPE")

    def setBackgroundFilename(self,filename="background"):
        """ Sets the background filename relative to self.rawDataDir """
        self._connection.setBackgroundFilename(self.rawDataDir,filename+".SPE")

    def setCenter(self,center):
        """ Set the center wavelength to be measured """
        self.centerLambda=center
        self._setCenter(self.centerLambda)

    def _setCenter(self,center):
        """ Set the center wavelength of Winspec itself """
        self._connection.setCenter(center)

    def getCenter(self):
        """ Gets the center wavlength """
        return self._connection.getCenter()
        
    def setNumPoints(self,numPoints):
        """ Set the number of points (i.e. spectra) to measure... must be a multiple of the number of pixels """
        self.numSpectra=int(numPoints/self._connection.getNumberOfPixels())
        
    def setResolution(self,resolution):
        """ Set the resolution in nm (i.e. the most appropriate grating) to use for measurements """
        bestGratingIndex = np.argmin(np.abs(np.array(self._connection.detector["resolution"])-resolution))
        self._setGratingNumber(bestGratingIndex+1)
    
    def _setGratingNumber(self,gratingNum):
        """ Sets the grating number """
        self.gratingNumber=gratingNum
        self._connection.setGrating(gratingNum)

    def _getGratingNumber(self):
        """ Gets the grating number """
        return self._connection.getGrating()

    def getAttenuatorPosition(self):
        """ Get attenuator setting """
        return GAIN_SETTINGS[self.rangeIndex][0]

    def getAttenuation(self):
        """ Get attenuator gain """
        return ATTENUATION[self.getAttenuatorPosition()]

    def getGainSetting(self):
        """ Return the current gain setting (i.e. the value of gain set in Winspec)"""
        return GAIN_SETTINGS[self.rangeIndex][1]

    def getAbsoluteGain(self):
        """ Return the approximate absolute gain """
        return DETECTOR_GAIN[self.getGainSetting()]

    def getExposureTime(self):
        """ Return the current exposure time setting in seconds"""
        return self._connection.getExposureTime()

    def setExposureTime(self,exposure):
        """ Return the current exposure time setting in seconds"""
        self._connection.setExposureTime(exposure)
        self.bgMeasRequired = True

    def accumulations(self,tau):
        """ Calculate the number of accumulations necessary to keep the measurement time above tau given current exposure time """
        return int(np.ceil(tau/1000/GAIN_SETTINGS[self.rangeIndex][2]))

    def tempLocked(self):
        return self._connection.checkIfTempLocked()

    def has2dDetector(self):
        return self._connection.getDetectorHeight() > 1

    def findCenterWavelengths(self,numSpectra,centerLambda,leftMinima,rightMaxima):
        """ Given numSpectra, finds the position to set the spectrometer at for each spectrum.
        Also requires the center, min, and max lambda for the central starting point [all in m]"""
        # Get some polynomials which specify the relation between the center wavelength and the real measured wavelength minima/maxima
        pCenterFromMinima,pCenterFromMaxima,pMinimaFromCenter,pMaximaFromCenter=self._connection.getDispersionCalibration()
        # Set the center wavelength of the central spectrum to the user specified center wavelength (numSpectra must be odd)
        allCenterLambda=np.zeros(numSpectra)
        numSideSpectra=int((numSpectra-1)/2) # number of spectra on either side of the central one
        allCenterLambda[numSideSpectra]=centerLambda*1e9
        # Step through the side spectra outwards from the central spectrum in pairs (left and right) and calculate the desired center wavelengths
        for idx in range(numSideSpectra):
            # Want the maxima/minima of each spectra to line up with the minima/maxima of the next spectra
            idealLeftMaxima=leftMinima
            idealRightMinima=rightMaxima
            # Calculate where we should center the spectrometer to get the edges to line up
            leftCenter=np.polyval(pCenterFromMaxima,idealLeftMaxima)
            rightCenter=np.polyval(pCenterFromMinima,idealRightMinima)
            # assign these to the allCenterLambda arrays
            allCenterLambda[numSideSpectra-idx-1]=leftCenter
            allCenterLambda[numSideSpectra+idx+1]=rightCenter
            # Calculate the outer edge for both of the current spectra
            leftMinima=np.polyval(pMinimaFromCenter,leftCenter)
            rightMaxima=np.polyval(pMaximaFromCenter,rightCenter)
        return allCenterLambda