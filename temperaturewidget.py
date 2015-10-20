from __future__ import division
import sip
sip.setapi("QString", 2)
sip.setapi('QVariant', 2)
class TempMonitorError(Exception): pass
import PyQt4, sys, os
from PyQt4 import QtGui, QtCore
from PyQt4.QtCore import Qt, QThread
from drivepy.scientificinstruments.temperaturecontroller import TemperatureController


from numpy import *

__version__="0.0.1"
appName="Temperature Control Software"
INTERVAL=500

class TemperatureMonitor(QtGui.QDockWidget):
    """ Main window shown to the user"""
    def __init__(self, parent = None):
        super(TemperatureMonitor,self).__init__(parent)
        self.initializeWindow_()
        QtCore.QCoreApplication.processEvents()
        try:
            self.tcThread=QtCore.QThread()
            self.tempController=TemperatureController()
            self.tempController.moveToThread(self.tcThread)
            self.tcThread.started.connect(self.tempController.getTemperature)
            self.connect(self.tempController,QtCore.SIGNAL("tempDataReady"),self.updateTemperature)
            self.connect(self.tempController,QtCore.SIGNAL("setTempDataReady"),self.updateSetTemperature)
            self.tcThread.start() 
            self.live=True
            self.timerID=self.startTimer(INTERVAL)          
        except Exception, e:
            self.live=False
            raise TempMonitorError,e

    def initializeWindow_(self):
        # Set window name and setup size
        self.setWindowTitle(appName + " Version " + __version__)
        settings=QtCore.QSettings()
        try:
            self.restoreGeometry(settings.value("Geometry"))
        except Exception as e:
            print(e.args[0])
        # Create the GUI widgets
        mainWidget=QtGui.QWidget()
        tempLabel=QtGui.QLabel("Temperature (K):")
        setTempLabel=QtGui.QLabel("Set Temp (K):")
        self.temperatureDisplay=QtGui.QLabel()
        self.temperatureDisplay.setFont(QtGui.QFont("Arial", 20))
        self.temperatureDisplay.setAlignment(Qt.AlignCenter)
        self.setTemperatureDisplay=QtGui.QLabel()
        self.setTemperatureDisplay.setFont(QtGui.QFont("Arial", 20))		
        self.setTemperatureDisplay.setAlignment(Qt.AlignCenter)
        setTemperatureLabel=QtGui.QLabel("Set Temp (K):")
        self.setTemperatureEdit=QtGui.QLineEdit()
        self.setTemperatureButton=QtGui.QPushButton("Set")
        self.connect(self.setTemperatureButton,QtCore.SIGNAL("clicked()"),self.setTemperature)
        layout=QtGui.QVBoxLayout()
        layout.addWidget(tempLabel)
        layout.addWidget(self.temperatureDisplay)
        layout.addWidget(setTempLabel)
        layout.addWidget(self.setTemperatureDisplay)		
        layout.addWidget(setTemperatureLabel)
        layout.addWidget(self.setTemperatureEdit)
        layout.addWidget(self.setTemperatureButton)
        layout.addStretch()
        #layout.addItem(QtGui.QSpacerItem(50,1,QtGui.QSizePolicy.Expanding))
        mainWidget.setLayout(layout)
        self.setWidget(mainWidget)

    def timerEvent(self,event=None):
        """ Call the getTemperature and getSetTemperature methods from the temperature controller which runs in a separate thread, 
        and wait for the new data signal to be emitted before updating the GUI """
        #self.tempController.getTemperature()
        #self.tempController.getSetTemperature()
        QtCore.QMetaObject.invokeMethod(self.tempController, "getTemperature", Qt.QueuedConnection)
        QtCore.QMetaObject.invokeMethod(self.tempController, "getSetTemperature", Qt.QueuedConnection)
        #self.temperatureDisplay.setText(str(self.tempController.getTemperature()))
        #self.setTemperatureDisplay.setText(str(self.tempController.getSetTemperature()))
        #QtCore.QCoreApplication.processEvents()
    def updateTemperature(self,newTemp):
        """ Update the temperature when new temperature data available """
        self.temperatureDisplay.setText(str(newTemp))
    def updateSetTemperature(self,newSetTemp):
        """ Update the set temperature when new temperature data available """
        self.setTemperatureDisplay.setText(str(newSetTemp))
            
    def setTemperature(self):
        setTemperatureValue=float(self.setTemperatureEdit.text())
        self.tempController.setTemperature(setTemperatureValue)
        self.tempController.getSetTemperature()
    def closeEvent(self, event):
        self.killTimer(self.timerID)
        self.tcThread.wait(10*INTERVAL)
        self.tcThread.exit()        
        event.accept()           


if __name__=="__main__":
	app=QtGui.QApplication(sys.argv)
	app.setApplicationName(appName)  
	app.setOrganizationName("University of Tokyo")
	app.setOrganizationDomain("u-tokyo.ac.jp")
	app.setWindowIcon(QtGui.QIcon(":\laser.png"))
	# Spacer to show an initial dialog asking if the user wants to create a new, or open existing session  
	form=TemperatureMonitor()
	form.show()
	app.exec_()