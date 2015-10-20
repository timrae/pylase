from __future__ import division
import win32com.client as w32c
winspecTypeLib=w32c.gencache.EnsureModule("{1A762221-D8BA-11CF-AFC2-508201C10000}",0,3,12)
if winspecTypeLib is None:
    raise ImportError("The Winspec type library was not found. If using windows 7 then try running winspec once as an administrator")
from win32com.client import constants as csts
from ctypes import byref, pointer, c_long, c_float, c_bool
from numpy import *
import os,string
import WinspecUtils  # this allows reading from Winspec SPE files


MAX_COUNTS=2**16            # 16-bit detector, so maximum number of counts is 2^16
HI_GAIN_MULT=30             # Multiplier when using hi-gain mode in Winspec
SATURATION_THRESHOLD=0.99   # Percentage of full range the maximum sample should take for spectrum to be defined as saturating
READ_FROM_FILE=True         # Flag to enable reading from the file (i.e. from disk) instead of reading via ActiveX. MUCH faster when large numFrames

class Winspec(object):
    """ Wrapper around the Winspec COM object which provides high level methods to move and measure spectra with Winspec """
    def __init__(self):
        self.connectToWinspec()
        self.setExpSetupProfile("automatic.EXS")
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

    def acquireBackground(self,exposureTime=None):
        """ Acquire a background """
        def acquisition():
            success=self.expSetup.AcquireBackground()
            if not success:
                raise CommError, "Acquisition of background in Winspec was not successful "
            bg=self.readBackground()
            attempts=1
            # Remeasure if the background level looks suspiciously high
            while mean(bg)>6000 and attempts<=3:
                attempts+=1
                self.expSetup.AcquireBackground()
            if attempts>1: self.sendStatusMessage("The background level is too high... check signal strength and detector cooling. Proceeding anyway...")
        # Chance the exposure time if specified
        if exposureTime!=None:
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

    def readBackground(self):
        # The only way to get the background data seems to be by reading the file from disk (~1ms latency)
        noiseFloorSpectrum=WinspecUtils.Spectrum(self.getExpParamSafe(csts.EXP_DARKNAME))
        return noiseFloorSpectrum.lum
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
        if exposureTime!=None:
            self.setExposureTime(exposureTime)
        # Set the number of repetitive frames to average over
        self.setNumFrames(numFrames)
        wavelengthData,counts,outDict=self.getWinspecData(numFrames)
        # close open documents and delete the current docFile
        if cleanup:
            docFiles=w32c.Dispatch("WinX32.DocFiles")
            docFiles.CloseAll()
            del self.docFile
        # return the data
        return wavelengthData,counts,outDict

    def getWinspecData(self,numFrames=1):
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
            for idx in range(numFrames):
                # Extract frame of data via datapointer
                try:
                    frameCounts = self.docFile.GetFrame(idx+1, datapointer)
                except Exception as e:
                    raise CommError, "Could not read data from Winspec: " + e.args[0]
                # Raise error if no data was read back
                if frameCounts==None: raise CommError,"No data returned from Winspec"
                # If first frame then create a numpy array where we will store the data
                if idx==0: counts=zeros((len(frameCounts),numFrames))
                # Put the frame into the numpy array
                counts[:,idx] = [frameCounts[i][0] for i in range(len(frameCounts))]
        else:
            # Read directly from the file if specified, as this can be much faster for a large number of frames
            fname=self.getDataFilename()
            if string.lower(fname[-4:])!=".spe": fname=fname+".spe"
            dataList=WinspecUtils.read_spe(fname)["data"]
            counts=array(dataList)[:,0,:].transpose()
        # Convert the pixel data to wavelength using calibration data from Winspec
        p=self.getCalibrationCoeffs()
        wavelengthData=polyval(p,range(1,1+counts.shape[0]))
        # Get the background data and return the std of it back so we know the noise floor
        assert self.backgroundSubtractFlag(), "The background subtract flag was not set for current Winspec file"
        noiseFloor=self.readBackground()
        # check if any frame of the file is saturating
        saturating=self.isSaturating(counts+tile(noiseFloor,(numFrames,1)).transpose())
        # return three arguments giving lambda, counts (averaged over each frame), and some extra stuff in a dictionary
        avgCounts=sum(counts,1)/numFrames
        avgCounts[avgCounts<0]=0    # make sure no entries are below zero in final data
        outDict={"saturating":saturating, "noiseFloor":noiseFloor, "maxSample":amax(counts)}
        return (wavelengthData,avgCounts,outDict)
        
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
       #if not self.expSetup.GetParam(csts.EXP_TEMP_STATUS):
       #    raise TempNotLockedWarning, "The detector temperature is not locked"

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

    def getDispersionCalibration(self,MEASURE=False):
        """ Returns polynomials specifying how to go between the left and right extreme wavelengths from the center wavelength, measuring if MEASURE flag is specified """
        if MEASURE:
            # measure by scanning the spectrometer through some wavelength range and using Winspec, and extracting min and max wavelengths from dummy data
            lambdaCenter=linspace(1100,1500,100)
            lambdaMin=zeros(size(lambdaCenter))
            lambdaMax=zeros(size(lambdaCenter))
            for lambdaIdx in range(len(lambdaCenter)):
                self.setPosition(lambdaCenter[lambdaIdx])
                x,y,s=self.acquireSpectrum(cleanup=False) # get dummy spectrum
                p=self.getCalibrationCoeffs()
                lambdaMin[lambdaIdx]=polyval(p,1)
                lambdaMax[lambdaIdx]=polyval(p,1024)
            # Fit 5th order polynomial to the data for left and right ends of the spectrum
            leftFromCenter=polyfit(lambdaCenter,lambdaMin,5)
            rightFromCenter=polyfit(lambdaCenter,lambdaMax,5)
            centerFromLeft=polyfit(lambdaMin,lambdaCenter,5)
            centerFromRight=polyfit(lambdaMax,lambdaCenter,5)
        else:
            gratingNum=self.getGrating()
            # use pre-measured coefficients
            if gratingNum==1:
                centerFromLeft=array([ -8.76754521e-14,   5.22736157e-10,  -1.25717343e-06, 1.51231359e-03,   8.18700991e-02,   2.42843468e+02])
                centerFromRight=array([  1.31440746e-13,  -8.03938743e-10,   1.97940406e-06, -2.43870473e-03,   2.51150337e+00,  -3.94632472e+02])
                leftFromCenter=array([  1.05334207e-13,  -6.35426534e-10,   1.54472144e-06, -1.87880789e-03,   2.15127597e+00,  -3.02205261e+02])
                rightFromCenter=array([ -1.09192089e-13,   6.60688938e-10,  -1.61057344e-06, 1.96429025e-03,  -2.06842219e-01,   3.16349585e+02])           
            elif gratingNum==2:
                centerFromLeft=array([  2.01449970e-15,  -1.28513008e-11,   3.23350048e-08, -4.25934602e-05,   1.02329050e+00,   3.62890039e+01])
                centerFromRight=array([  2.26609046e-15,  -1.49925836e-11,   3.99380253e-08, -5.09508121e-05,   1.03712621e+00,  -5.18505187e+01])
                leftFromCenter=array([ -2.10542984e-15,   1.38205868e-11,  -3.58032220e-08, 4.82954659e-05,   9.72120713e-01,  -3.50494608e+01])
                rightFromCenter=array([ -2.15858732e-15,   1.38961016e-11,  -3.60234505e-08, 4.44726545e-05,   9.67846854e-01,   5.01830295e+01])    
            elif gratingNum==3:
                centerFromLeft=array([  2.09982327e-15,  -1.19065340e-11,   2.68847609e-08, -3.07052437e-05,   1.01494475e+00,   1.65114549e+02])
                centerFromRight=array([  2.16900052e-15,  -1.58864768e-11,   4.64278226e-08, -6.71752727e-05,   1.05115080e+00,  -1.83149485e+02])
                leftFromCenter=array([ -2.13897870e-15,   1.39041153e-11,  -3.60302054e-08, 4.70177437e-05,   9.71859363e-01,  -1.61518332e+02])
                rightFromCenter=array([ -2.12519778e-15,   1.38130348e-11,  -3.57977089e-08, 4.57450984e-05,   9.68114969e-01,   1.76176642e+02])
        return (centerFromLeft,centerFromRight,leftFromCenter,rightFromCenter)

    def sendStatusMessage(self,msg):
        """ Send a status message to the user """
        print(msg)
        # In addition to printing, ideally also want to send something to the GUI

    def __del__(self):
        """ restore the filename and exposure settings to useful values """
        self.setExpSetupProfile("manual.EXS")
        docFiles=w32c.Dispatch("WinX32.DocFiles")
        docFiles.CloseAll()

class CommError(Exception): pass
class noBackgroundError(Exception): pass
class noSignalError(Exception): pass
class TempNotLockedWarning(Exception): pass