from __future__ import division   
from PyQt4 import QtCore
from drivepy.thorlabs.aptlib import AptPiezo, AptMotor
from drivepy.thorlabs.aptlib import aptconsts as consts
#from drivepy.newfocus.powermeter import PowerMeter
from drivepy.newport.powermeter import PowerMeter
from numpy import *
from scipy import optimize
import matplotlib.pyplot as plt

X_CHANNEL=0
Y_CHANNEL=1
MOTOR_TRAVEL=4.0
FIRST_SIGNAL_RESOLUTION=0.02  # default resolution in mm for first signal search

class SignalTooWeakError(Exception): pass
class PiezoControl(AptPiezo):
    """ Convenience class inherited from aptlib.AptPiezo to allow customization""" 
    def __init__(self,autoZero,*args,**kwargs):
        super(PiezoControl, self).__init__(*args,**kwargs)      
        for ch in range(len(self.channelAddresses)):
            # Set controller channels to closed loop (position) mode
            self.SetControlMode(ch,consts.PIEZO_CLOSED_LOOP_MODE)
            # Autozero if argument was specified
            if autoZero: self.zero(ch)
            # Initialize to center
            self.moveToCenter(ch)

class MotorControl(AptMotor):
    """ Convenience class inherited from aptlib.AptMotor to allow customization"""
    def __init__(self,autoZero,*args,**kwargs):
        super(MotorControl, self).__init__(*args,**kwargs)
        for ch in range(len(self.channelAddresses)):
            if autoZero: 
                self.zero(ch)
                self.setPosition(ch,self.GetMaxTravel()/2)
    def GetMaxTravel(self,channel=0):
        """ Get the max travel of the stepper motor stage """
        return MOTOR_TRAVEL
    def getCoordinates(self):
        x=self.getPosition(X_CHANNEL)
        y=self.getPosition(Y_CHANNEL)
        return (x,y)

class _Align(QtCore.QObject):
    def __init__(self,*args,**kwargs):
        super(_Align, self).__init__(*args,**kwargs)
      
    def autoalign(self,p0=None,res=1,span=None,profitFunction=None):
        """ Automatically align the piezo stage to get maximum value from profitFunction using a discrete search algorithm
        input arguments are starting position p0 (x,y) tuple in um
        grid resolution in um
        grid span (i.e. +/- how much to search over) in um
        a profitFunction method which gives the profit for optimization (e.g. the total power) """
        # Setup the input variables properly
        if p0 is None: p0=self.coordinates
        if span is None: span=self.ctrl.GetMaxTravel()/2
        if profitFunction is None: 
            pm=PowerMeter()
            profitFunction=lambda : pm.readPowerAuto()
        # Create a discrete grid with specified span and resolution centered at p0
        x,y=self.gridPoints(span,res,p0)
        #x,y=self.gridPoints(maxTravel/2,ROUGH_GRID_RES,(maxTravel/2,maxTravel/2))
        ix, iy = self.searchGrid(x,y,p0,profitFunction)
        self.coordinates = (x[ix], y[iy])
        self.moveTo(self.coordinates)
        finalProfit=profitFunction()
        # TO DO: send a pyqt signal when finished so it can be run in a separate thread
        return (self.coordinates,finalProfit)

    def findFirstSignal(self,p0=None,res=FIRST_SIGNAL_RESOLUTION,span=None,profitFunction=None,threshold=None, softThreshold=None, plotFlag=False):
        """ Automatically look for the first sign of a signal by measuring across a grid, outwards from the center
        point, and stopping the measurement prematurely if the threshold is exceeded for profitFunction """
        if p0 is None: p0=self.ctrl.getCoordinates()
        if span is None: span=self.ctrl.GetMaxTravel()/2
        if profitFunction is None: 
            pm=PowerMeter()
            profitFunction=lambda : pm.readPowerAuto(tau=1)
        # If the current center point already has a signal then stop the search before it begins
        profit=profitFunction()
        if profit >threshold: return (self.ctrl.getCoordinates(),profit)
        # Create grid points evenly spaced according to span and resolution about p0
        x,y=self.gridPoints(span,res,p0)
        #x=x[logical_and(x>=0,x<=self.ctrl.GetMaxTravel())]
        #y=y[logical_and(y>=0,y<=self.ctrl.GetMaxTravel())]
        # Permute the x values so that they start at the center and move outwards
        xp,xip=self.permuteOutwards(x)
        #yp,yip=self.permuteOutwards(y) # This may significantly slow down the motor movement
        P=self.measureGrid(x,y,xip,profitFunction,threshold,softThreshold)
        # Optionally plot the grid
        if plotFlag:
            plt.imshow(P,extent=[min(x),max(x),max(y),min(y)])
            plt.show()
        # Extract the maximum value
        maxIdx=where(P==P.max())
        self.coordinates=(x[maxIdx[1][0]],y[maxIdx[0][0]])
        # Move to the position of max value
        self.moveTo(self.coordinates)
        # Measure the profit again
        finalProfit=profitFunction()
        return (self.coordinates,finalProfit)


    def searchGrid(self,x,y,p0,profitFunction, I=None):
        """ Use a discrete search algorithm which creates a grid specified by the x,y vectors, starts at a point p0 on the grid,
        then measures the profit at each of the 8 immediately adjacent grid points. If any of these points have a greater profit then
        repeat the process with this maximum point as the new center. Continue until all grid points have been measured once,
        or a local maxima has been found. Return a tuple with (x,y) coordinate of maxmima"""
        # Create empty array for intensity over the grid and boolean array to keep track of which points have been measured
        if I is None: I=zeros((len(y),len(x)))
        Imask=I!=I
        # Find the x and y indices for the closest point on the grid to p0
        ix0=argmin(abs(x-p0[0]))
        iy0=argmin(abs(y-p0[1]))
        # Measure profit at this point
        self.moveTo(p0)
        I[iy0,ix0]=profitFunction()
        Imask[iy0,ix0]=True
        while Imask.any():
            # Measure all points immediately adjacent to current index if they haven't been measured yet
            for ix in [-1,0,1]+array(ix0):
                for iy in [-1,0,1]+array(iy0):
                    try:
                        if not Imask[iy,ix]:
                            rMax=self.ctrl.GetMaxTravel()
                            if ix >= 0 and iy >= 0 and ix < len(x) and iy < len(y):
                                if x[ix]>=0 and y[iy]>=0 and x[ix]<=rMax and y[iy]<=rMax:
                                    self.moveTo((x[ix],y[iy]))
                                    I[iy,ix]=profitFunction()
                                Imask[iy,ix]=True
                            else:
                                print('Index out of bounds: (%d, %d)'%(ix, iy))
                    except IndexError:
                        # Just ignore any points which are out of bounds
                        pass
            # Find the point with maximum profit on the grid measured so far
            iyMax,ixMax=where(I==I.max())
            ixMax=ixMax[0]
            iyMax=iyMax[0]
            # If the center of the grid is the maximum then stop the optimization here, otherwise set maximum point as new center
            if I.max() > 0:
                if iyMax==iy0 and ixMax==ix0:
                    break
                else:
                    ix0=ixMax
                    iy0=iyMax
            else:
                test=profitFunction()
                pass
        # Set maximum point from optimization as new coordinates
        assert ixMax==ix0 and iyMax==iy0
        return (ixMax, iyMax)
   
    def measureLine(self,channel,r,profitFunction,threshold=None):
        """ Given a channel, and a vector of positions, measure the profit function at all points on the given channel. 
        Stop the measurement prematurely if a threshold is given and the profit exceeds it"""
        profit=zeros(shape(r))
        for idx in range(len(r)):
            if r[idx]>=0 and r[idx]<=self.ctrl.GetMaxTravel():
                self.move1d(channel,r[idx])
                profit[idx]=profitFunction()
            if threshold!=None and profit[idx]>=threshold:
                return profit
        return profit

    def measureGrid(self,x,y,xOrder,profitFunction,threshold=None, softThreshold=None):
        """ Measure the profit vs position on a grid specified by x and y vectors and optionally stop if the profit is above a certain threshold"""
        profit=zeros((len(y),len(x)))
        for ix in xOrder:
            if x[ix]>=0 and x[ix]<=self.ctrl.GetMaxTravel():
                self.move1d(X_CHANNEL,x[ix])
                profit[:,ix]=self.measureLine(Y_CHANNEL,y,profitFunction,threshold)
            if not threshold is None and max(profit[:,ix])>=threshold:
                return profit
            if not threshold is None and not softThreshold is None and max(profit[:,ix]) >= softThreshold:
                # If we have a reasonable signal, but not high enough to be sure that it's not a local maxima then attempt an optimization
                iy = argmax(profit[:, ix])
                p0 = (x[ix], y[iy])
                print('Attempting micro-optimization at (%f, %f)...'%p0)
                ixNew , iyNew = self.searchGrid(x, y, p0, profitFunction)
                self.moveTo((x[ixNew], y[iyNew]))
                newProfit = profitFunction()
                if newProfit >= threshold:
                    # if we're now at an optimal position then return profit
                    print('Micro-optimization successful: found signal at (%f, %f)...'%(x[ixNew],y[iyNew]))
                    profit[iyNew, ixNew] = newProfit
                    return profit
                else:
                    # otherwise go back to previous search position and increase soft threshold
                    print('Micro-optimization failed')
                    softThreshold = softThreshold*2
                    self.moveTo(p0)
        return profit

    def move1d(self,channel,r):
        """ Move coordinate of given channel to r """
        self.ctrl.setPosition(channel,r)

    def moveX(self,x):
        """ Move x coordinate to x """
        self.move1d(X_CHANNEL,x)
    def moveY(self,y):
        """ Move y coordinate to y """
        self.move1d(Y_CHANNEL,y)
    def moveTo(self,pos):
        """ Move to x,y coords given by pos """
        self.moveX(pos[0])
        self.moveY(pos[1])
    def gridPoints(self,span,res,center):
        """ Return (x,y) points for square grid with extent +/- span spaced at res, and centered at center """
        d=linspace(-span,span,round(2*span/res+1))
        return (center[0]+d,center[1]+d)

    def permuteOutwards(self,x):
        """ Permute vector x so that its values move outwards from the center, and return the original indices that put it that way"""
        # If just a single value then it doesn't need permuting
        if len(x)==1: return (x,range(1))
        # Choose a middle index (only unique if odd)
        middleIndex=int(len(x)/2)
        # Initialize a vector of indices for x
        xi=range(len(x))
        # Initialize lists for the permuted versions of x and xi
        xip=[xi[middleIndex]]
        # Step through the values on each side of middle index and append until the end points
        for i in range(middleIndex-1):
            xip.append(xi[middleIndex-i-1])
            xip.append(xi[middleIndex+i+1])
        # Append the end points depending on whether len(x) is even or odd
        xip.append(xi[0])
        if len(x)%2:
            xip.append(xi[-1])
        return (x[xip],xip)


class PiezoAlign(_Align):
    """Class that does automatic alignment by using a piezo controller to set the position to optimize a profitFunction.
    The position should be specified in um """
    def __init__(self,autoZero=False,*args,**kwargs):
        super(PiezoAlign, self).__init__(*args,**kwargs)
        self.ctrl=PiezoControl(autoZero)
        self.coordinates=(self.ctrl.getPosition(X_CHANNEL),self.ctrl.getPosition(Y_CHANNEL))

class MotorAlign(_Align):
    """Class that does automatic alignment by using a stepping motor controller to set the position to optimize a profitFunction 
    The position should be specified in mm"""
    def __init__(self,autoZero=False,*args,**kwargs):
        super(MotorAlign, self).__init__(*args,**kwargs)
        self.ctrl=MotorControl(autoZero)
        self.coordinates=(self.ctrl.getPosition(X_CHANNEL),self.ctrl.getPosition(Y_CHANNEL))

if __name__== '__main__': 
    piezo1=PiezoControl()
    #print 'current position:', piezo1.ctrl.GetPosOutput()
    print("zeroing channel 1....")
    piezo1.zero(X_CHANNEL)
    print("zeroing channel 2....")
    piezo1.zero(Y_CHANNEL)
    print("zeroing complete")
    piezo1.moveToCenter(X_CHANNEL)
    piezo1.moveToCenter(Y_CHANNEL)