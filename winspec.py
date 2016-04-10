from __future__ import division
import win32com.client as w32c
winspecTypeLib=w32c.gencache.EnsureModule("{1A762221-D8BA-11CF-AFC2-508201C10000}",0,3,12)
if winspecTypeLib is None:
    raise ImportError("The Winspec type library was not found. If using windows 7 then try running winspec once as an administrator")
from win32com.client import constants as csts
from ctypes import c_long, c_float, c_bool
from numpy import *
import os,string,struct,ast

# By default store spectrum files in $USER_HOME_DIR\Winspec
WINSPEC_DEFAULT_DIR = os.path.join(os.path.expanduser('~'), 'Winspec')
 # Assume 16-bit detector, so maximum number of counts is 2^16
MAX_COUNTS=2**16
# Maximum tolerable level for the DC background
MAX_BACKGROUND_LEVEL = MAX_COUNTS/2
# Percentage of full range the maximum sample should take for spectrum to be defined as saturating
SATURATION_THRESHOLD=0.99               
# Behavior when the detector temperature is not locked: (0: do nothing, 1: print warning, 2: throw TempNotLockedWarning)
DET_TEMP_LOCK_BEHAVIOR = 1
# Default exposure time to set in the object destructor
DEFAULT_EXPOSURE = 0.2
# Default wavelength range to measure calibration over
DEFAULT_CAL_RANGE = {0:(900, 1100), 1:(1100, 1500), 2:(1100, 1500)}
# Name of detector definition file used to store calibration data, etc
DETECTOR_DEF_FILE = 'detector.txt'
# Flag to enable reading spectra from the file (i.e. from disk) instead of reading via ActiveX. MUCH faster when large numFrames
READ_FROM_FILE=False                     

class Winspec(object):
    """ Wrapper around the Winspec COM object which provides high level methods to move and measure spectra with Winspec.
    The software has been tested and optimized for the PI Acton Spectrometer range, together with the following detectors:
        'OMA-V-1024' liquid nitrogen cooled 1024x1 NIR detector
        'NIRvana 640G' TEC cooled 640x512 NIR detector operated in Spectroscopy mode (i.e. using vertical binning to get single spectrum).
    Other 16-bit 1-d detectors and 2-d detectors operated in spectroscopy mode are also expected to work.

   This software was last tested with Winspec v2.6.22.0. Older versions of Winpec may have some bugs. """

    def __init__(self):
        # Connect to COM object
        self.connectToWinspec()
        self.setExpSetupProfile("automatic.EXS")
        # Read the detector calibration data necessary to do a step and glue
        try:
            self.detector = readDetectorDefinition()
        except IOError:
            self.detector = {"calibrationRange":DEFAULT_CAL_RANGE, "width":self.getNumberOfPixels(), "height":self.getDetectorHeight()}
            self.measureCalibration()
    def connectToWinspec(self):
        """ Make new connection to Winspec """
        w32c.pythoncom.CoInitialize() # Initialize COM libraries
        # Create objects for the experiment, spectrometer, and data document
        self.expSetup = w32c.Dispatch("WinX32.ExpSetup")
        self.spectroObj = w32c.Dispatch("WinX32.SpectroObjMgr").Current

    def setExpSetupProfile(self,fname):
        """ Initializes the experiment setup by loading a default file. 
        Unfortunately saving and loading this file is only available indirectly through the GUI..."""
        ExpSetupUI=w32c.Dispatch("WinX32.ExpSetupUI")
        page=ExpSetupUI.GetPageObj(7)
        dir=os.path.join(os.getcwd(),"winspec_config")+os.sep
        success=page.LoadExperimentSetup(dir,fname) # note: this seems to return true even if the file wasn't found
        del ExpSetupUI

    def acquireBackgroundSpectrum(self,exposureTime=None):
        """ Acquire a background """
        def acquisition():
            success=self.expSetup.AcquireBackground()
            if not success:
                raise CommError, "Acquisition of background in Winspec was not successful "
            bg=self.readBackground()
            attempts=1
            # Remeasure if the background level looks suspiciously high
            while mean(bg) > MAX_BACKGROUND_LEVEL and attempts<=3:
                attempts+=1
                self.expSetup.AcquireBackground()
            if attempts>1: self.sendStatusMessage("The background level looks too high... check signal strength.")
        
        # Make sure we're using spectroscopy mode    
        self.setSpectroscopyMode(True)
        # Check the temperature is locked
        if DET_TEMP_LOCK_BEHAVIOR and not self.checkIfTempLocked():
            MSG = "The detector temperature is not locked"
            self.sendStatusMessage(MSG)
            if DET_TEMP_LOCK_BEHAVIOR==2: raise TempNotLockedWarning, MSG
        # Set the exposure time if specified
        if exposureTime:
            self.setExposureTime(exposureTime)
        # Acquire a few times if neccessary incase something goes wrong
        try:
            acquisition()
        except Exception as e:
            # try two more times if there was an error
            try:
                # need to reconnect to winspec incase program crashed
                self.connectToWinspec()
                acquisition()
            except Exception as e:
                self.connectToWinspec()
                try:
                    self.deleteBackgroundFile()
                except WindowsError:
                    pass
                acquisition()

    def readBackground(self, row = 0):
        # The only way to get the background data seems to be by reading the file from disk (~1ms latency)
        noiseFloorSpectrum=array(read_spe(self.getExpParamSafe(csts.EXP_DARKNAME))["data"])
        return noiseFloorSpectrum[0, row, :]
    def deleteBackgroundFile(self):
        os.remove(self.getExpParamSafe(csts.EXP_DARKNAME))
    def deleteDataFile(self):
        os.remove(self.getExpParamSafe(csts.EXP_DATFILENAME))

    def acquireSpectrum(self,numFrames=1,exposureTime=None,cleanup=True):
        """ Obtain a single spectrum from winspec over specified number of accumulations, 
        and optionally set the exposureTime before measuring. All other settings are left unchanged.
        If safeMode is specified, some checks on the data quality are done, and measurement repeated
        a number of times if it looks like there was a measurement error."""
        # Set the exposure time
        if exposureTime: self.setExposureTime(exposureTime)
        # Set the number of repetitive frames to average over
        self.setNumFrames(numFrames)
        # Make sure we're in spectroscopy mode
        self.setSpectroscopyMode(True)
        assert self.getRoiHeight() == 1, "Not in spectroscopy mode"
        # Acquire the actual data
        wavelengthData,counts,outDict=self._getWinspecSpectrum(numFrames)
        # close open documents and delete the current docFile
        if cleanup:
            docFiles=w32c.Dispatch("WinX32.DocFiles")
            docFiles.CloseAll()
            del self.docFile
        # return the data
        return wavelengthData,counts,outDict

    def _getWinspecSpectrum(self,numFrames=1):
        """ Acquire a spectrum from winspec numRepetetions times and return the average.
        Also check to see if the data was saturating or if there was anything abnormal with it """
        # Get Winspec to start the acquisition and wait for it to finish
        # Set the docfile
        assert self.getNumAccumulations()==1, "The automatic detection of saturation requires no more than 1 accumulation"
        self.docFile = w32c.Dispatch("WinX32.DocFile")
        if self.expSetup.Start(self.docFile)[0]:
            EXP_RUNNING=csts.EXP_RUNNING
            # Check the status of the acquisition
            exptIsRunning, status = self.expSetup.GetParam(EXP_RUNNING)
            # Wait for acquisition to finish while continuously checking for errors
            while exptIsRunning and status == 0:
                exptIsRunning, status = self.expSetup.GetParam(EXP_RUNNING)
            # Check that the acquisition occured without error
            if status != 0:
                raise CommError, 'Could not obtain status of experiment from Winspec while obtaining spectrum'
        else:
            raise CommError, 'Could not initiate acquisition in Winspec while trying to obtaining spectrum'
        if not READ_FROM_FILE:
            # Read each frame of the data file from Winspec by passing a pointer to a memory location where Python can find it
            datapointer = c_float()
            for idx in range(int(numFrames)):
                # Extract frame of data via datapointer
                try:
                    frameCounts = array(self.docFile.GetFrame(idx+1, datapointer))
                except Exception as e:
                    raise CommError, "Could not read data from Winspec: " + str(e.args[0])
                # Raise error if no data was read back
                if frameCounts is None: raise CommError,"No data returned from Winspec"
                # If a 2D sensor then take the maximum row
                rowMax = argmax(sum(frameCounts, 0)) if shape(frameCounts)[0] > 1 else 0
                frameCounts = frameCounts[:, rowMax]
                # If first frame then create a numpy array where we will store the data
                if idx==0: counts=zeros((len(frameCounts),numFrames))
                # Put the frame into the numpy array
                counts[:,idx] = frameCounts
        else:
            # Read directly from spectrum file, as this can be much faster than COM interface for large num frames
            fname=self.getDataFilename()
            if string.lower(fname[-4:])!=".spe": fname=fname+".spe"
            dataList=read_spe(fname)["data"]
            # If a 2D sensor then take the maximum row
            rowMax = argmax(sum(array(dataList)[0,:,:], 1)) if shape(dataList)[1] > 1 else 0
            counts=array(dataList)[:,rowMax,:].transpose()
        # Convert the pixel data to wavelength using calibration data from Winspec
        p=self.getCalibrationCoeffs()
        wavelengthData=polyval(p,range(1,1+counts.shape[0]))
        # Get the background data and return the std of it back so we know the noise floor
        assert self.backgroundSubtractFlag(), "The background subtract flag was not set for current Winspec file"
        noiseFloor=self.readBackground(rowMax)
        # check if any frame of the file is saturating
        saturating=self.isSaturating(counts+tile(noiseFloor,(numFrames,1)).transpose())
        # return three arguments giving lambda, counts (averaged over each frame), and some extra stuff in a dictionary
        avgCounts=sum(counts,1)/numFrames
        avgCounts[avgCounts<0]=0    # make sure no entries are below zero in final data
        outDict={"saturating":saturating, "noiseFloor":noiseFloor, "maxSample":amax(counts)}
        return (wavelengthData,avgCounts,outDict)

    def acquireImageBackground(self, exposureTime=None):
        """ Takes a 2D background reading. Requires a 2D detector """
        assert self.getDetectorHeight() > 1, "acquireImage() requires a 2D detector"
        if exposureTime: self.setExposureTime(exposureTime)
        self.setSpectroscopyMode(False)
        success=self.expSetup.AcquireBackground()
        if not success:
            raise CommError, "Acquisition of background in Winspec was not successful "

    def acquireImage(self, exposureTime=None):
        """ Gets a 2D image and returns it as a numpy Array. Requires a 2D detector """
        assert self.getDetectorHeight() > 1, "acquireImage() requires a 2D detector"
        self.setNumFrames(1)
        if exposureTime: self.setExposureTime(exposureTime)
        self.setSpectroscopyMode(False)
        datapointer = c_float()
        self.docFile = w32c.Dispatch("WinX32.DocFile")
        return array(self.docFile.GetFrame(1, datapointer))
        
    def isSaturating(self,countData):
        """ Checks if the max value of the data is above a threshold defined as saturating. """
        countMax=amax(countData)
        assert countMax<=MAX_COUNTS, "Signal read from Winspec is larger than physically possible"
        return countMax>=SATURATION_THRESHOLD*MAX_COUNTS

    def isNoSignal(self,counts):
        """ check to see if there was likely a measurement error 
        (if the signal looks like noise <sum(diff(counts)) abnormally large> despite a strong SNR)
        Not currently using this, but it is sometimes necessary """
        return sum(abs(diff(counts)))/sum(counts) > 0.4 and max(counts)>10*std(noiseFloor)

    def setGain(self,gain):
        """ Sets the analog gain of the detector (can have value 1 or 2).
        Doesn't seem to be available through the direct interface, so have to use the GUI"""
        ExpSetupUI=w32c.Dispatch("WinX32.ExpSetupUI")
        page=ExpSetupUI.GetPageObj(4)
        page.ControllerGain(gain)
        del ExpSetupUI        

    def setExposureTime(self,expTime):
        """ Sets the exposure time """
        self.setExpParamSafe(csts.EXP_EXPOSURE,expTime)
    
    def getExposureTime(self):
        """ Sets the exposure time """
        return self.getExpParamSafe(csts.EXP_EXPOSURE)

    def setNumAccumulations(self,numAccums):
        """ Sets the number of accumulations """
        self.setExpParamSafe(csts.EXP_ACCUMS,numAccums)

    def setNumFrames(self,numFrames):
        """ Sets the number of frames to acquire """
        self.setExpParamSafe(csts.EXP_SEQUENTS,numFrames)

    def getNumAccumulations(self):
        """ Gets the number of accumulations """
        return self.getExpParamSafe(csts.EXP_ACCUMS)
        
    def checkIfTempLocked(self):
       """ Checks to see if the detector temperature is locked at its target value. Raise exception if it's not """
       return self.getExpParamSafe(csts.EXP_TEMP_STATUS)

    def getDetectorTemperature(self):
        """ Get the detector temperature """
        return self.getExpParamSafe(csts.EXP_ACTUAL_TEMP)
    
    def setPosition(self,center,gratingNum=None):
        """ Sets the position of the spectrometer """
        # make sure the mirror is set to come out the front instead of the side
        self.setMirrorState(True)
        if gratingNum!=None:
            self.spectroObj.SetParam(csts.SPT_NEW_GRATING,gratingNum)
        self.spectroObj.SetParam(csts.SPT_NEW_POSITION,center)
        self.spectroObj.Move()
    
    def setMirrorState(self,state=True):
        """ Sets the state of the final mirror. If state=True the mirror is set to the front, otherwise the side """
        if state:
            self.spectroObj.SetParam(csts.SPT_MIRROR_NEWPOSITION,1)
        else:
            self.spectroObj.SetParam(csts.SPT_MIRROR_NEWPOSITION,2)

    def setCenter(self,center):
        """ Sets the center wavelength for Winspec in nm """
        # DEPRECATED :: USE setPosition() instead
        self.spectroObj.SetParam(csts.SPT_NEW_POSITION,center)
        self.spectroObj.Move()

    def getCenter(self):
        """ Get the center wavelength """
        return self.spectroObj.GetParam(csts.SPT_INST_CUR_GRAT_POS)[0]

    def setGrating(self,gratingNum):
        self.spectroObj.SetParam(csts.SPT_NEW_GRATING,gratingNum)
        self.spectroObj.Move()

    def getGrating(self):
        return self.spectroObj.GetParam(csts.SPT_CUR_GRATING)[0]

    def getCalibrationCoeffs(self):
        """ Return a numpy array of poynomial coefficients for the calibration at current position """
        calibration = self.docFile.GetCalibration()
        p=array([])
        for idx in range(calibration.Order+1)[::-1]:
            p=append(p,calibration.PolyCoeffs(idx))
        return p

    def getNumberOfPixels(self):
        return self.getExpParamSafe(csts.EXP_XDIMDET)

    def getDetectorHeight(self):
        return self.getExpParamSafe(csts.EXP_YDIMDET)

    def getRoiHeight(self):
        return self.getExpParamSafe(csts.EXP_YDIM)

    def getMeanPixelBandwidth(self):
        """ Returns the mean spectral width of one pixel at current center position """
        numPixels=self.docFile.GetParam(csts.DM_XDIM)[0]
        p=self.getCalibrationCoeffs()
        mean(diff(polyval(p,xrange(1,1+numPixels))))

    def getExpParamSafe(self,paramNum):
        """ Gets a parameter from Winspec experiment and raises an exception if there was an error """
        paramValue,status=self.expSetup.GetParam(paramNum)
        if status==0:
            return paramValue
        else:
            raise CommError, "There was an error getting an experimental parameter from Winspec"

    def setExpParamSafe(self,paramNum,paramValue):
        """ Sets a parameter from Winspec experiment and raises an exception if there was an error """
        status=self.expSetup.SetParam(paramNum,paramValue)
        if status==0:
            return True
        else:
            raise CommError, "There was an error getting an experimental parameter from Winspec"

    def setOverwriteWarning(self,state=0):
        """ Enable or disable the warning to overwrite files """
        if state:
            self.setExpParamSafe(csts.EXP_OVERWRITECONFIRM,1)
        else:
            self.setExpParamSafe(csts.EXP_OVERWRITECONFIRM,0)

    def setDataFilename(self,dir,fname,direct=True):
        """ Sets the experiment filename."""
        if direct:
            self.setExpParamSafe(csts.EXP_DATFILENAME,os.path.join(dir,fname))
        else:
            #  Attempt at workaround for a bug where direct setting occasionally complains about file not existing.
            ExpSetupUI=w32c.Dispatch("WinX32.ExpSetupUI")
            page=ExpSetupUI.GetPageObj(1)
            dir=dir+os.sep if dir[-1]!=os.sep else dir
            page.SetDataFilePathAndName(dir,fname)
            del ExpSetupUI

    def getDataFilename(self):
        return self.getExpParamSafe(csts.EXP_DATFILENAME)
        
    def setBackgroundFilename(self,dir,fname,direct=True):
        """ Sets the background filename for the experiment."""
        if direct:
            self.setExpParamSafe(csts.EXP_DARKNAME,os.path.join(dir,fname))
        else:
            #  Attempt at workaround for a bug where direct setting occasionally complains about file not existing.
            ExpSetupUI=w32c.Dispatch("WinX32.ExpSetupUI")
            page=ExpSetupUI.GetPageObj(3)
            dir=dir+os.sep if dir[-1]!=os.sep else dir
            page.SetBackgroundFilePathAndName(dir,fname)
            del ExpSetupUI   

    def enableFileIncrement(self):
        """ Enabled file increment """
        self.setExpParamSafe(csts.EXP_FILEINCENABLE,1)

    def resetFileIncrement(self):
        """ Enabled file increment """
        self.setExpParamSafe(csts.EXP_FILEINCCOUNT,1)

    def backgroundSubtractFlag(self):
        """ Returns the value of the background subtraction file for the current document """
        return self.docFile.GetParam(csts.DM_BACKGROUNDAPPLIED)[0]==1

    def setBackgroundSubtract(self,state=True):
        """ Sets whether or not background subtraction is enabled. Unfortunately we have to do it via the GUI """
        ExpSetupUI=w32c.Dispatch("WinX32.ExpSetupUI")
        page=ExpSetupUI.GetPageObj(3)
        page.BackgroundSubtraction(state)
        del ExpSetupUI

    def getVerticalROI(self):
        """ Get the top and bottom pixels that define the ROI """
        roi=self.expSetup.GetROI(1)
        top,left,bottom,right,xg,yg = roi.Get()
        return (top,bottom)

    def setVerticalROI(self, top, bottom):
        """ Sets the top and bottom pixels that define the ROI """
        assert top <= bottom, "top index must be smaller than bottom index"
        width = self.getNumberOfPixels()
        self.expSetup.ClearROIs()
        roi = w32c.Dispatch("WinX32.ROIRect")
        roi.Set(top, 1, bottom, width, 1, bottom-top+1)
        self.expSetup.SetROI(roi)

    def setSpectroscopyMode(self, mode=True):
        """ Enables or disables the use of the ROI to do hardware binning (necessary for 2D detectors) """
        if mode:
            self.setExpParamSafe(csts.EXP_USEROI, 1)
        else:
            self.setExpParamSafe(csts.EXP_USEROI, 0)

    def getDispersionCalibration(self):
        """ Returns polynomials specifying how to go between the left and right extreme wavelengths from the center wavelength """
        g = self.getGrating() - 1
        cal = self.detector["calibration"]
        return (cal["centerFromLeft"][g],cal["centerFromRight"][g],cal["leftFromCenter"][g],cal["rightFromCenter"][g])

    def measureCalibration(self):
        """ Measure the calibration data from Winspec necessary to do a step and glue, and store it in DETECTOR_DEF_FILE.
       Works by scanning the spectrometer through some wavelength range, and extracting min and max wavelengths from dummy data """
        self.sendStatusMessage("Extracting the calibration data from Winspec")
        self.setExposureTime(1e-6)  # only dummy data so make measurement as fast as possible
        self.acquireBackgroundSpectrum()
        # Initialize calibration data
        self.detector["calibration"] = {}
        self.detector["calibration"]["leftFromCenter"] = [None]*3
        self.detector["calibration"]["rightFromCenter"] = [None]*3
        self.detector["calibration"]["centerFromLeft"] = [None]*3
        self.detector["calibration"]["centerFromRight"] = [None]*3
        self.detector["resolution"] = [None]*3
        for grating in [0,1,2]:
            calRange = self.detector["calibrationRange"][grating]
            lambdaCenter=linspace(calRange[0],calRange[1],100)
            lambdaMin=zeros(size(lambdaCenter))
            lambdaMax=zeros(size(lambdaCenter))
            self.setGrating(grating+1)
            for lambdaIdx in range(len(lambdaCenter)):
                self.setPosition(lambdaCenter[lambdaIdx])
                x,y,s=self.acquireSpectrum(cleanup=False) # get dummy spectrum
                p=self.getCalibrationCoeffs()
                lambdaMin[lambdaIdx]=polyval(p,1)
                lambdaMax[lambdaIdx]=polyval(p,len(x))
            # Fit 5th order polynomial to the data for left and right ends of the spectrum
            lfc=self.detector["calibration"]["leftFromCenter"][grating]=list(polyfit(lambdaCenter,lambdaMin,5))
            rfc=self.detector["calibration"]["rightFromCenter"][grating]=list(polyfit(lambdaCenter,lambdaMax,5))
            self.detector["calibration"]["centerFromLeft"][grating]=list(polyfit(lambdaMin,lambdaCenter,5))
            self.detector["calibration"]["centerFromRight"][grating]=list(polyfit(lambdaMax,lambdaCenter,5))
            self.detector["resolution"][grating] = (polyval(rfc, mean(calRange))-polyval(lfc, mean(calRange)))/self.detector["width"]
        f=open(DETECTOR_DEF_FILE,'w')
        f.write(str(self.detector))
        f.close()

    def sendStatusMessage(self,msg):
        """ Send a status message to the user """
        print(msg)
        # In addition to printing, ideally also want to send something to the GUI

    def __del__(self):
        """ restore the filename and exposure settings to useful values """
        if not os.path.exists(WINSPEC_DEFAULT_DIR): os.makedirs(WINSPEC_DEFAULT_DIR)
        self.setBackgroundFilename(WINSPEC_DEFAULT_DIR, 'background.spe')
        self.setDataFilename(WINSPEC_DEFAULT_DIR, 'spectrum.spe')
        self.setExposureTime(DEFAULT_EXPOSURE)
        docFiles=w32c.Dispatch("WinX32.DocFiles")
        docFiles.CloseAll()


def readDetectorDefinition():
    """ Read the detector definition from the file 'detector.txt'
    TODO: try get all of the same information directly from Winspec """
    try:
        f=open(DETECTOR_DEF_FILE,'r')
    except IOError as e:
        raise IOError, "Could not read Winspec detector definition from detector.txt.\n" + str(e.args[0])
    s = f.read()
    f.close()
    return ast.literal_eval(s)


def read_spe(spefilename, verbose=False):
    """ 
    Read a binary PI SPE file into a python dictionary

    Inputs:

        spefilename --  string specifying the name of the SPE file to be read
        verbose     --  boolean print debug statements (True) or not (False)

        Outputs
        spedict     
        
            python dictionary containing header and data information
            from the SPE file
            Content of the dictionary is:
            spedict = {'data':[],    # a list of 2D numpy arrays, one per image
            'IGAIN':pimaxGain,
            'EXPOSURE':exp_sec,
            'SPEFNAME':spefilename,
            'OBSDATE':date,
            'CHIPTEMP':detectorTemperature
            }

    I use the struct module to unpack the binary SPE data.
    Some useful formats for struct.unpack_from() include:
    fmt   c type          python
    c     char            string of length 1
    s     char[]          string (Ns is a string N characters long)
    h     short           integer 
    H     unsigned short  integer
    l     long            integer
    f     float           float
    d     double          float

    The SPE file defines new c types including:
        BYTE  = unsigned char
        WORD  = unsigned short
        DWORD = unsigned long


    Example usage:
    Given an SPE file named test.SPE, you can read the SPE data into
    a python dictionary named spedict with the following:
    >>> import piUtils
    >>> spedict = piUtils.readSpe('test.SPE')
    """
  
    # open SPE file as binary input
    spe = open(spefilename, "rb")
    
    # Header length is a fixed number
    nBytesInHeader = 4100

    # Read the entire header
    header = spe.read(nBytesInHeader)
    
    # version of WinView used
    swversion = struct.unpack_from("16s", header, offset=688)[0]
    
    # version of header used
    # Eventually, need to adjust the header unpacking
    # based on the headerVersion.  
    headerVersion = struct.unpack_from("f", header, offset=1992)[0]
  
    # which camera controller was used?
    controllerVersion = struct.unpack_from("h", header, offset=0)[0]
    if verbose:
        print "swversion         = ", swversion
        print "headerVersion     = ", headerVersion
        print "controllerVersion = ", controllerVersion
    
    # Date of the observation
    # (format is DDMONYYYY  e.g. 27Jan2009)
    date = struct.unpack_from("9s", header, offset=20)[0]
    
    # Exposure time (float)
    exp_sec = struct.unpack_from("f", header, offset=10)[0]
    
    # Intensifier gain
    pimaxGain = struct.unpack_from("h", header, offset=148)[0]

    # Not sure which "gain" this is
    gain = struct.unpack_from("H", header, offset=198)[0]
    
    # Data type (0=float, 1=long integer, 2=integer, 3=unsigned int)
    data_type = struct.unpack_from("h", header, offset=108)[0]

    comments = struct.unpack_from("400s", header, offset=200)[0]

    # CCD Chip Temperature (Degrees C)
    detectorTemperature = struct.unpack_from("f", header, offset=36)[0]

    # The following get read but are not used
    # (this part is only lightly tested...)
    analogGain = struct.unpack_from("h", header, offset=4092)[0]
    noscan = struct.unpack_from("h", header, offset=34)[0]
    pimaxUsed = struct.unpack_from("h", header, offset=144)[0]
    pimaxMode = struct.unpack_from("h", header, offset=146)[0]

    ########### here's from Kasey
    #int avgexp 2 number of accumulations per scan (why don't they call this "accumulations"?)
#TODO: this isn't actually accumulations, so fix it...    
    accumulations = struct.unpack_from("h", header, offset=668)[0]
    if accumulations == -1:
        # if > 32767, set to -1 and 
        # see lavgexp below (668) 
        #accumulations = struct.unpack_from("l", header, offset=668)[0]
        # or should it be DWORD, NumExpAccums (1422): Number of Time experiment accumulated        
        accumulations = struct.unpack_from("l", header, offset=1422)[0]
        
    """Start of X Calibration Structure (although I added things to it that I thought were relevant,
       like the center wavelength..."""
    xcalib = {}
    
    #SHORT SpecAutoSpectroMode 70 T/F Spectrograph Used
    xcalib['SpecAutoSpectroMode'] = bool( struct.unpack_from("h", header, offset=70)[0] )

    #float SpecCenterWlNm # 72 Center Wavelength in Nm
    xcalib['SpecCenterWlNm'] = struct.unpack_from("f", header, offset=72)[0]
    
    #SHORT SpecGlueFlag 76 T/F File is Glued
    xcalib['SpecGlueFlag'] = bool( struct.unpack_from("h", header, offset=76)[0] )

    #float SpecGlueStartWlNm 78 Starting Wavelength in Nm
    xcalib['SpecGlueStartWlNm'] = struct.unpack_from("f", header, offset=78)[0]

    #float SpecGlueEndWlNm 82 Starting Wavelength in Nm
    xcalib['SpecGlueEndWlNm'] = struct.unpack_from("f", header, offset=82)[0]

    #float SpecGlueMinOvrlpNm 86 Minimum Overlap in Nm
    xcalib['SpecGlueMinOvrlpNm'] = struct.unpack_from("f", header, offset=86)[0]

    #float SpecGlueFinalResNm 90 Final Resolution in Nm
    xcalib['SpecGlueFinalResNm'] = struct.unpack_from("f", header, offset=90)[0]

    #  short   BackGrndApplied              150  1 if background subtraction done
    xcalib['BackgroundApplied'] = struct.unpack_from("h", header, offset=150)[0]
    BackgroundApplied=False
    if xcalib['BackgroundApplied']==1: BackgroundApplied=True

    #  float   SpecGrooves                  650  Spectrograph Grating Grooves
    xcalib['SpecGrooves'] = struct.unpack_from("f", header, offset=650)[0]

    #  short   flatFieldApplied             706  1 if flat field was applied.
    xcalib['flatFieldApplied'] = struct.unpack_from("h", header, offset=706)[0]
    flatFieldApplied=False
    if xcalib['flatFieldApplied']==1: flatFieldApplied=True
    
    #double offset # 3000 offset for absolute data scaling */
    xcalib['offset'] = struct.unpack_from("d", header, offset=3000)[0]

    #double factor # 3008 factor for absolute data scaling */
    xcalib['factor'] = struct.unpack_from("d", header, offset=3008)[0]
    
    #char current_unit # 3016 selected scaling unit */
    xcalib['current_unit'] = struct.unpack_from("c", header, offset=3016)[0]

    #char reserved1 # 3017 reserved */
    xcalib['reserved1'] = struct.unpack_from("c", header, offset=3017)[0]

    #char string[40] # 3018 special string for scaling */
    xcalib['string'] = struct.unpack_from("40c", header, offset=3018)
    
    #char reserved2[40] # 3058 reserved */
    xcalib['reserved2'] = struct.unpack_from("40c", header, offset=3058)

    #char calib_valid # 3098 flag if calibration is valid */
    xcalib['calib_valid'] = struct.unpack_from("c", header, offset=3098)[0]

    #char input_unit # 3099 current input units for */
    xcalib['input_unit'] = struct.unpack_from("c", header, offset=3099)[0]
    """/* "calib_value" */"""

    #char polynom_unit # 3100 linear UNIT and used */
    xcalib['polynom_unit'] = struct.unpack_from("c", header, offset=3100)[0]
    """/* in the "polynom_coeff" */"""

    #char polynom_order # 3101 ORDER of calibration POLYNOM */
    xcalib['polynom_order'] = struct.unpack_from("c", header, offset=3101)[0]

    #char calib_count # 3102 valid calibration data pairs */
    xcalib['calib_count'] = struct.unpack_from("c", header, offset=3102)[0]

    #double pixel_position[10];/* 3103 pixel pos. of calibration data */
    xcalib['pixel_position'] = struct.unpack_from("10d", header, offset=3103)

    #double calib_value[10] # 3183 calibration VALUE at above pos */
    xcalib['calib_value'] = struct.unpack_from("10d", header, offset=3183)

    #double polynom_coeff[6] # 3263 polynom COEFFICIENTS */
    xcalib['polynom_coeff'] = struct.unpack_from("6d", header, offset=3263)

    #double laser_position # 3311 laser wavenumber for relativ WN */
    xcalib['laser_position'] = struct.unpack_from("d", header, offset=3311)[0]

    #char reserved3 # 3319 reserved */
    xcalib['reserved3'] = struct.unpack_from("c", header, offset=3319)[0]

    #unsigned char new_calib_flag # 3320 If set to 200, valid label below */
    #xcalib['calib_value'] = struct.unpack_from("BYTE", header, offset=3320)[0] # how to do this?

    #char calib_label[81] # 3321 Calibration label (NULL term'd) */
    xcalib['calib_label'] = struct.unpack_from("81c", header, offset=3321)

    #char expansion[87] # 3402 Calibration Expansion area */
    xcalib['expansion'] = struct.unpack_from("87c", header, offset=3402)
    ########### end of Kasey's addition

    if verbose:
        print "date      = ["+date+"]"
        print "exp_sec   = ", exp_sec
        print "pimaxGain = ", pimaxGain
        print "gain (?)  = ", gain
        print "data_type = ", data_type
        print "comments  = ["+comments+"]"
        print "analogGain = ", analogGain
        print "noscan = ", noscan
        print "detectorTemperature [C] = ", detectorTemperature
        print "pimaxUsed = ", pimaxUsed

    # Determine the data type format string for
    # upcoming struct.unpack_from() calls
    if data_type == 0:
        # float (4 bytes)
        dataTypeStr = "f"  #untested
        bytesPerPixel = 4
        dtype = "float32"
    elif data_type == 1:
        # long (4 bytes)
        dataTypeStr = "l"  #untested
        bytesPerPixel = 4
        dtype = "int32"
    elif data_type == 2:
        # short (2 bytes)
        dataTypeStr = "h"  #untested
        bytesPerPixel = 2
        dtype = "int32"
    elif data_type == 3:  
        # unsigned short (2 bytes)
        dataTypeStr = "H"  # 16 bits in python on intel mac
        bytesPerPixel = 2
        dtype = "int32"  # for numpy.array().
        # other options include:
        # IntN, UintN, where N = 8,16,32 or 64
        # and Float32, Float64, Complex64, Complex128
        # but need to verify that pyfits._ImageBaseHDU.ImgCode cna handle it
        # right now, ImgCode must be float32, float64, int16, int32, int64 or uint8
    else:
        print "unknown data type"
        print "returning..."
        sys.exit()
  
    # Number of pixels on x-axis and y-axis
    nx = struct.unpack_from("H", header, offset=42)[0]
    ny = struct.unpack_from("H", header, offset=656)[0]
    
    # Number of image frames in this SPE file
    nframes = struct.unpack_from("l", header, offset=1446)[0]

    if verbose:
        print "nx, ny, nframes = ", nx, ", ", ny, ", ", nframes
    
    npixels = nx*ny
    npixStr = str(npixels)
    fmtStr  = npixStr+dataTypeStr
    if verbose:
        print "fmtStr = ", fmtStr
    
    # How many bytes per image?
    nbytesPerFrame = npixels*bytesPerPixel
    if verbose:
        print "nbytesPerFrame = ", nbytesPerFrame

    # Create a dictionary that holds some header information
    # and contains a placeholder for the image data
    spedict = {'data':[],    # can have more than one image frame per SPE file
                'IGAIN':pimaxGain,
                'EXPOSURE':exp_sec,
                'SPEFNAME':spefilename,
                'OBSDATE':date,
                'CHIPTEMP':detectorTemperature,
                'COMMENTS':comments,
                'XCALIB':xcalib,
                'ACCUMULATIONS':accumulations,
                'FLATFIELD':flatFieldApplied,
                'BACKGROUND':BackgroundApplied
                }
    
    # Now read in the image data
    # Loop over each image frame in the image
    if verbose:
        print "Reading image frames number ",
    for ii in range(nframes):
        iistr = str(ii)
        data = spe.read(nbytesPerFrame)
        if verbose:
            print ii," ",
    
        # read pixel values into a 1-D numpy array. the "=" forces it to use
        # standard python datatype size (4bytes for 'l') rather than native
        # (which on 64bit is 8bytes for 'l', for example).
        # See http://docs.python.org/library/struct.html
        dataArr = array(struct.unpack_from("="+fmtStr, data, offset=0),
                            dtype=dtype)

        # Resize array to nx by ny pixels
        # notice order... (y,x)
        dataArr.resize((ny, nx))
        #print dataArr.shape

        # Push this image frame data onto the end of the list of images
        # but first cast the datatype to float (if it's not already)
        # this isn't necessary, but shouldn't hurt and could save me
        # from doing integer math when i really meant floating-point...
        spedict['data'].append( dataArr.astype(float) )

    if verbose:
        print ""
  
    return spedict

class CommError(Exception): pass
class noBackgroundError(Exception): pass
class noSignalError(Exception): pass
class TempNotLockedWarning(Exception): pass