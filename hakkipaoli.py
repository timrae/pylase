from __future__ import division
from PyQt4 import QtCore
from numpy import *
from scipy import optimize
from scipy import constants as scipycsts
import pylab
from filter import savitzky_golay

# Define some global variables
DEBUG=0  # Debug mode can take values (0,1,2). 0 plots no intermediary results. 1 plots intermediary plots when the canvas is free. 2 plots all intermediary plots
METHOD='hybrid' # Calculation method: ('maxmin','modesum','hybrid','fit')
CONVOLVE=False # Whether to convolve the fit function with the response function when METHOD=='fit'
MINSMOOTH=None # use 5 sample smoothing in calculating the minimum. Set to None to disable
MIN_MODE_INTENSITY=20/65536    # Minimum difference in counts between max and min value of a mode to be recognized as legit
#DEFAULT_PARAM={"R1":.997,"R2":.322,"L":375e-6,"n":3.619}
#DEFAULT_PARAM={"R1":.94,"R2":.3,"L":600e-6,"n":3.619}
DEFAULT_PARAM={"R1":.94,"R2":.3,"L":375e-6,"n":3.619}
MIN_MODE_SPACING=0.4e-9*(375e-6/DEFAULT_PARAM["L"])         # Minimum spacing in nm between each mode used for peakClean algorithm

class HakkiPaoli(QtCore.QObject):
    updateProgress=QtCore.pyqtSignal(float)
    plotDataReady=QtCore.pyqtSignal(dict)
    """ Class which holds the code for Hakki-Paoli gain calculation """
    def __init__(self,x,y,param=DEFAULT_PARAM,parent=None):
        super(HakkiPaoli, self).__init__()
        self.x=x
        self.y=y
        self.param=param # holds some parameters defining the cavity
        self.rendering=False # flag which says whether the canvas is ready to draw again
        self.parent=parent

    def restoreThreadAffinity(self):
        """ move back to parent thread if multithreading was invoked by the parent """
        self.moveToThread(self.parent.thread())

    def gainCalculation(self):
        """ Tries to calculate the gain from the spectrum using the Hakki-Paoli technique. R1 and R2 are the reflectivities of the mirrors """
        # Detect all of the peaks in y
        maxIdxRaw=peakDetect(self.y)
        maxIdx=peakClean(self.x,self.y,maxIdxRaw)
        # calculate cavity length using FSR[nm]=lambda0^2/2/n/L (note: this is not accurate since we need to use the unknown wavlength dependent effective index)
        #L=mean((x[maxIdx[1:]]-diff(x[maxIdx])/2)**2/2/n/diff(x[maxIdx]))
        # Loop through each mode and calculate Pmax, Pmin, and the lambda we use for that mode idx
        modeGain=array([])
        modeWavelength=array([])
        for modeIdx in range(len(maxIdx)-2):
            try:
                self.updateProgress.emit(modeIdx/(len(maxIdx)-2))
                # Slice off the section in x and y corresponding to current mode (ignore first two modes)
                modeSpacing=(maxIdx[modeIdx+2]-maxIdx[modeIdx])/2 # average mode spacing based on next two peaks
                startIdx=maxIdx[modeIdx+1]-round(modeSpacing/2)
                stopIdx=stopIdx=maxIdx[modeIdx+1]+round(modeSpacing/2)
                xCurrMode=self.x[startIdx:stopIdx]
                yCurrMode=self.y[startIdx:stopIdx]
                # Set Pmax as power at central peak of mode
                Pmax=self.y[maxIdx[modeIdx+1]]
                # Set Pmin as minimum power over the whole space. This is less accurate, but more robust than making assumptions about where the min should be and averaging
                if MINSMOOTH!=None:
                    ysmooth=savitzky_golay(yCurrMode,MINSMOOTH,1,0) # linear polynomial with MINSMOOTH points
                    Pmin=max(min(ysmooth),0)
                    """if DEBUG==2 or (DEBUG and not self.rendering):
                        xAxis={"data":(xCurrMode*1e9,xCurrMode*1e9),"label":"wavelength [nm]"}
                        yAxis={"data":(yCurrMode,ysmooth),"lineProp":("xk","ko"),"label":"Mode intensity [a.u.]"}
                        plotDictionary={"x":xAxis,"y":yAxis}
                        self.emit(QtCore.SIGNAL("plotDataReady"),plotDictionary)
                        self.rendering=True"""
                else:
                    Pmin=min(yCurrMode)
                # Set the gain using Hakki-Paoli or Hakki-Paoli-Cassidy method or nonlinear curve fit from Wang, Cassidy paper
                if METHOD == "maxmin":
                    # Standard Hakki-Paoli:                    
                    currModeWavelength,currModeGain=self.maxMinGain(xCurrMode,yCurrMode)
                elif METHOD == "modesum":
                    # Cassidy modification:
                    currModeWavelength,currModeGain=self.modeSumGain(xCurrMode,yCurrMode)
                elif METHOD == "hybrid":
                    # Cassidy modification close to threshold, Standard Hakki-Paoli gain everywhere else
                    currModeWavelength,currModeGain=self.maxMinGain(xCurrMode,yCurrMode)
                    # If gain close to threshold then use Cassidy modification
                    mirrorLoss=1/2/self.param["L"]*log(1/self.param["R1"]/self.param["R2"])
                    if currModeGain > 0.3*mirrorLoss:
                        currModeWavelength,currModeGain=self.modeSumGain(xCurrMode,yCurrMode)
                elif METHOD == "fit":
                    # Nonlinear curve-fit method:
                    currModeWavelength,currModeGain=self.modeFitGain(xCurrMode,yCurrMode)
                # Add calculated gain for current mode to main array if it wasn't skipped
                if currModeGain!=None:
                    # add the gain for current mode to main array
                    modeGain=append(modeGain,currModeGain)
                    # add wavelength for current mode as the wavelength at central peak
                    modeWavelength=append(modeWavelength,currModeWavelength)
                else:
                    # add the gain for current mode to main array
                    modeGain=append(modeGain,NaN)
                    # add wavelength for current mode as the wavelength at central peak
                    modeWavelength=append(modeWavelength,currModeWavelength)
            except (RuntimeError,ValueError) as e:
                # don't add the mode to list if there was a runtime error calculating the gain
                print(e.args[0])
        # TODO: I need to implement convolution to improve the accuracy, and averaging to improve minima calculation
        return (modeWavelength,modeGain)

    def maxMinGain(self,modeLambda,modeI):
        """ Return the standard Hakki-Paoli (max/min) Gain """
        Pmax=modeI.max()
        Pmin=modeI.min()
        if (Pmax-Pmin)>0:
            avgModeGain=-(1/self.param["L"])*log(sqrt(self.param["R1"]*self.param["R2"])*(sqrt(Pmax)+sqrt(Pmin))/(sqrt(Pmax)-sqrt(Pmin)))
        else:
            avgModeGain=None
        avgModeLambda=modeLambda[modeI==Pmax][0]
        return (avgModeLambda,avgModeGain)

    def modeSumGain(self,modeLambda,modeI):
        """ Return the modified Cassidy version of Hakki-Paoli Gain (mode sum) """
        Pmax=modeI.max()
        Pmin=modeI.min()
        if Pmin>0:
            avgModeGain = -(1/self.param["L"])*log(sqrt(self.param["R1"]*self.param["R2"])*((sum(modeI)/Pmin/size(modeI) + 1)/
                                                                                         (sum(modeI)/Pmin/size(modeI) - 1)))
        else:
            avgModeGain=None
        avgModeLambda=modeLambda[modeI==Pmax][0]
        return (avgModeLambda,avgModeGain)

    def modeFitGain(self,modeLambda,modeI):
        """ Return the mode gain by fitting the mode to ideal FP resonator:
        Wang, H., & Cassidy, D. T. (2005). Gain measurements of Fabry-Perot semiconductor lasers using a nonlinear least-squares fitting method.
        Quantum Electronics, IEEE Journal of, 41(4), 532-540."""
        Pmax=modeI.max()
        Pmin=modeI.min()
        # Use standard Hakki-Paoli calculation as starting point for nonlinear fit
        PRG0=(sqrt(Pmax)-sqrt(Pmin))/(sqrt(Pmax)+sqrt(Pmin))
        # Define the starting point for optimization [PRG,lambda0,n,C,beta,gamma]
        lambda0=modeLambda[modeI==Pmax][0]
        #p0=[G0*sqrt(R1*R2),x[maxIdx[modeIdx+1]],n,Pmax*(1+G0*sqrt(R1*R2))**2,0,0]
        p0=[PRG0,lambda0,self.param["n"],Pmax*(1-PRG0)**2]
        # Do nonlinear curve fit to modeFitFunc and return the fit parameters
        modeFitFunc=self.makeModeFitFunc(self.param["L"],x,startIdx,stopIdx)
        p=optimize.curve_fit(modeFitFunc,xCurrMode,yCurrMode,p0)[0]
        avgModeGain = (1/self.param["L"])*log(p[0]/sqrt(self.param["R1"]*self.param["R2"]))
        avgModeWavelength=p[1]
        QtCore.QCoreApplication.processEvents()
        if DEBUG==2 or (DEBUG and not self.rendering):
            xAxis={"data":(modeLambda*1e9,modeLambda*1e9,array([p[1],p[1]])*1e9),"label":"Wavelength [nm]"}
            yAxis={"data":(modeI/max(modeI),modeFitFunc(modeLambda,*p)/max(modeI),array([min(modeI),max(modeI)])/max(modeI)),"lineProp":("xk","bo-",":^"),"label":"Mode intensity [a.u.]"}
            plotDictionary={"x":xAxis,"y":yAxis}
            self.rendering=True
            self.plotDataReady.emit(plotDictionary)
        return (avgModeLambda,avgModeGain)


    def makeModeFitFunc(self,L,xAll=None,startIdx=None,stopIdx=None):
        """ scipy.optimize.curve_fit doesn't let us pass additional arguments, so we use Currying via this intermediary function to give xAll which represents the whole spectrum across all modes."""
        def modeFitFunc(xm,*param):
            """ Does least-squres fit of fabryPerotFunc for a single Fabry-Perot mode """
            # Calculate the Fabry-Perot spectrum for ALL modes using the input parameters
            return self.fabryPerotFunc(xm,L,*param)
        def modeFitFuncConv(xm,*param):
            """ Does least-squres fit of fabryPerotFunc convolved with responseFunc to the data for a single Fabry-Perot mode """
            # Calculate the Fabry-Perot spectrum for ALL modes using the input parameters
            fpSpectrum=self.fabryPerotFunc(xAll,L,*param)
            # Convolve fbSpectrum with resonseFunc
            yhat=convolve(fpSpectrum,self.responseFunc(xm,param[1]),'same')       # 'same' does the same as taking the region [x0Idx:(x0Idx+len(x))] with x0Idx=(abs(x-x0)==min(abs(x-x0))).nonzero()[0]
            # trim off the current mode from the data
            ymhat=yhat[startIdx:stopIdx]
            return ymhat
        # Return a different function depending on whether or not convolution was specified
        if CONVOLVE:
            return modeFitFuncConv
        else:
            return modeFitFunc

    def fabryPerotFunc(self,x,L,*param):
        """ Function which defines what the Fabry-Perot mode function should look like. This function is copied directly from the paper:
       ' Gain Measurements of Fabry-Perot Semiconductor Lasers Using a Nonlinear Least-Sqares Fitting Method in IEEE JQE vol. 41, 532 by Wang and Cassidy"""
        PRG0=param[0]       # product of RG at lambda0
        x0=param[1]         # wavelength at center of the mode
        n=param[2]          # effective mode index
        C0=param[3]         # value of fitting parameter related to the Einstein B coefficient at lambda0
        #beta=param[4]       # linear slope of change in gain over the mode
        #gamma=param[5]      # linear slope of change in fitting parameter C over the mode
        PRG=PRG0#+beta*(x-x0)
        C=C0#+gamma*(x-x0)   
        denominator=(1-PRG)**2+4*PRG*sin(2*pi*n*L*(1/x-1/x0))**2
        I=C/denominator     # calculated intensity
        return I

    def responseFunc(self,x,x0,sigma=25e-12):
        """ Gaussian response function for the spectrometer which can be used as a convolution kernel """
        m=exp(-(x-x0)**2/sigma**2)
        return m/sum(m)

    @QtCore.pyqtSlot()
    def readyToDraw(self):
        """ Slot which allows the figure canvas to say when it's ready to draw again """
        self.rendering=False

# Some helper methods which can be imported from the module
def peakDetect(y):
    """ Given a vector y, return the indices of all the peaks without applying any filtering or special criteria """
    yd=diff(y) # calculate 1st derivative
    # define maxima as points where there is a zero crossing of first derivative and first deriviative is decreasing
    ydZero=(yd==0)[0:-1]      # first check for the case where the first derivative is exactly zero
    ydNegativeSoon=yd[1:]<0  # check if next sample of first derivative is negative
    ydZeroCross=yd[0:-1]*yd[1:]<0   # check if first derivative crosses through zero (i.e. between samples)
    ydDecreasing=(yd[1:]-yd[0:-1])<0  # check if first derivative is decreasing
    maxIdx=((ydZero&ydNegativeSoon)|(ydZeroCross&ydDecreasing)).nonzero()[0]+1
    return maxIdx

def peakClean(x,y,maxIdx,xth=MIN_MODE_SPACING,yth=None):
    """ runs through each of the indices for peaks in y data, and if any two points closer than xth, remove the point with smaller y value """
    i=1
    while i<(len(maxIdx)):
        dx=x[maxIdx[i]]-x[maxIdx[i-1]]
        if dx<xth:
            if y[maxIdx[i]] > y[maxIdx[i-1]]:
                maxIdx=delete(maxIdx,i-1)
            else:
                maxIdx=delete(maxIdx,i)
        else:
            i=i+1
    # if specified, also check that the peak to peak difference of y is bigger than yth
    if yth!=None:
        maxIdxClean=[]
        for i in range(len(maxIdx)-1) :
            dy=(max(y[maxIdx[i]:maxIdx[i+1]])-min(y[maxIdx[i]:maxIdx[i+1]]))/max(y)
            if dy > yth:
                maxIdxClean.append(maxIdx[i])
        maxIdx=maxIdxClean

    return maxIdx