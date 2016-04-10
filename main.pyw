#!/usr/bin/env
from __future__ import division
import os, sip
os.environ['QT_API'] = 'pyqt'
sip.setapi("QString", 2)
sip.setapi("QVariant", 2)
from numpy import *
from ipyconsole import QIPythonWidget
import PyQt4, sys
import qrc_resources
from PyQt4 import QtGui, QtCore, QtCore
from PyQt4.QtCore import Qt, QCoreApplication
from matplotlib.backends.backend_qt4agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt4agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.pyplot import legend
from measuredialog import MeasureDialog
from profile import Profile, ProfileProgressDialog

from datetime import datetime, timedelta
import traceback,measurement

try:
    from drivepy import visaconnection
    DUMMY_MODE=False
except ImportError as e:
    # Assume that if VISA module not installed then none of the instrumentation imports will work
    print("Error importing visaconnection from drivepy... \n"+e.args[0])
    DUMMY_MODE=True
except WindowsError as e:
# Assume that if VISA module not installed then none of the instrumentation imports will work
    print("Error importing visaconnection from drivepy... \n"+e.args[1])
    DUMMY_MODE=True

try:
    from winspec import Winspec, readDetectorDefinition
    WINSPEC_AVAILABLE = True
except ImportError:
    WINSPEC_AVAILABLE = False

# Flag to switch on autoalign. Turn off if no piezo actuators or fiber tap + power meter available
AUTO_ALIGN=True
if not DUMMY_MODE:
    from temperaturewidget import TempMonitorError
    from temperaturewidget import TemperatureMonitor    
    if AUTO_ALIGN:
        import align
        from align import PiezoAlign, MotorAlign
else:
    # Force AUTO_ALIGN to be false if dummy-mode
    AUTO_ALIGN=False


__version__="0.0.2"
appName="Laser Measurement Software"
AUTOMEASURE_INTERVAL=1000*60*(7)  # measure every (n) minutes
MULTI_THREADING=False

class MainWindow(QtGui.QMainWindow):
    """ Main window shown to the user"""
    def __init__(self, parent = None,fname=":memory:",createNew=True):
        #Init the base class
        super(MainWindow,self).__init__(parent)
        self.debugVars={}  # Place holder which holds debug variables, useful for sending variables here from other modules
        # Ask if the user wants to create new or open existing database
        s=QtCore.QSettings()
        # Open the database connection and add session object to self
        self.session=measurement.Session(createNew,fname,parent=self)
        s.setValue("LastOpenedFile",(fname))
        # Initialize the main window
        self.initializeWindow()
        self.populateTree()
        # Connect plotDataReady signal of each of the measurement objects to the renderPlot slot of the canvas
        self.session.plotDataReady.connect(self.canvas.renderPlot)
        for meas in self.session.measurements:
            meas.plotDataReady.connect(self.canvas.renderPlot)
        # If AUTO_ALIGN then create the align object , which will initialize the piezoactuators to be at their central position        
        if AUTO_ALIGN:
            motorAlignObject=MotorAlign(autoZero=True)
            self.motorCoordinates=p=s.value("MotorCoordinates",(2.0,2.0))
            motorAlignObject.moveTo(p)
            # When we use the motor align object the exact position of Piezo is basically arbitrary so no autozero
            piezoAlignObject=PiezoAlign(autoZero=False)
            self.piezoCoordinates=piezoAlignObject.coordinates
        else:
            piezoAlignObject=None
            motorAlignObject=None
            self.piezoCoordinates=None
            self.motorCoordinates=None
        self.lock=QtCore.QReadWriteLock()

    def initializeWindow(self):
        # Set window name and setup size
        self.setWindowTitle(appName + " Version " + __version__)
        settings=QtCore.QSettings()
        if settings.value("Geometry"):
            self.restoreGeometry(settings.value("Geometry"))
        # Create the GUI widgets
        self.mainSplitter=QtGui.QSplitter(QtCore.Qt.Horizontal)
        self.dataTree=QtGui.QTreeWidget()
        p = QtGui.QPalette()
        p.setColor(QtGui.QPalette.Base, QtGui.QColor("#d6dde0"))
        self.dataTree.setPalette(p)
        self.dataTree.setHeaderLabel("Measurement Sets")
        self.dataTree.setMinimumSize(QtCore.QSize(120,0))
        self.connect(self.dataTree,QtCore.SIGNAL("itemClicked(QTreeWidgetItem*,int)"),self.treeItemClicked)
        self.connect(self.dataTree,QtCore.SIGNAL("itemChanged(QTreeWidgetItem*,int)"),self.treeItemChanged)
        self.canvas=MplCanvas(self,width=5, height=4, dpi=100)
        self.canvas.setMinimumSize(QtCore.QSize(500,400))
        # Add the widgets to the mainSplitter layout
        self.mainSplitter.addWidget(self.dataTree)
        self.mainSplitter.addWidget(self.canvas)
        self.setCentralWidget(self.mainSplitter)
        # Create some actions
        quitAction=self.createAction("&Quit",self.close,"Ctrl+Q","application-exit","Close the application")
        measureAction=self.createAction("&Measure",self.measureDialog,"Ctrl+M","measure_small","Show the new measurement dialog")
        exportAction=self.createAction("&Export",self.exportDialog,"Ctrl+E","export","Show the export dialog for exporting data")
        openAction=self.createAction("&Open",self.openDialog,QtGui.QKeySequence.Open,"open-file-icon","Open an existing measurement session")
        consoleAction=self.createAction("&Console",self.showConsoleDialog,"Ctrl+X","console","Show the iPython console")
        curveFitAction=self.createAction("&Fitting",self.showCurveFitDialog,"Ctrl+F","curvefit","Fit theoretical model to current data")
        alignAction=self.createAction("&Alignment",self.autoAlign,"Ctrl+A","xy_motor","Align the objective lens to get maximum signal (via motors)")
        fineAlignAction=self.createAction("Fine Alignment",self.autoFineAlign,"Ctrl+Shift+A","xy_piezo","Align the objective lens to get maximum signal (via piezo)")
        profileAction=self.createAction("&Profile",self.startTemperatureProfile,"Ctrl+P","cooler","Start a fixed measurement vs. temperature profile")
        winspecCalibrationAction=self.createAction("&Winspec Calibration",self.winspecCalibration,"Ctrl+W","Measure Winspec Calibration data")
        self.consoleDialog=None
        # Create a toolbar and add actions/widgets to it
        self.mainToolBar=mainToolBar=QtGui.QToolBar()
        self.addToolBar(mainToolBar)
        mainToolBar.setObjectName("MainToolbar")
        mainToolBar.addAction(measureAction)
        mainToolBar.addAction(openAction)
        mainToolBar.addAction(exportAction)
        mainToolBar.addAction(consoleAction)
        mainToolBar.addAction(curveFitAction)
        mainToolBar.addAction(alignAction)
        mainToolBar.addAction(fineAlignAction)
        mainToolBar.addAction(profileAction)
        mainToolBar.setMovable(False)
        self.addToolBar(self.canvas.mplToolbar)
        self.canvas.mplToolbar.setObjectName("mplToolbar")
        #self.canvas.mplToolbar.setMovable(False)
        self.canvas.mplToolbar.setAllowedAreas(QtCore.Qt.TopToolBarArea)
        # Add some menus
        self.fileMenu = QtGui.QMenu('&File', self)
        self.fileMenu.addAction(openAction)
        self.fileMenu.addAction(measureAction)
        self.fileMenu.addAction(exportAction)
        self.fileMenu.addAction(quitAction)
        if WINSPEC_AVAILABLE:
            self.fileMenu.addAction(winspecCalibrationAction)
        self.menuBar().addMenu(self.fileMenu)
        # Show temperature monitor dock widget
        self.tempController = None
        if not DUMMY_MODE:
            try:
                # Show any delayed errors from import 
                self.tempMonWidget=TemperatureMonitor()
                self.tempMonWidget.setObjectName("TempMonWidget")
                self.tempController=self.tempMonWidget.tempController
                self.addDockWidget(Qt.RightDockWidgetArea,self.tempMonWidget)
                self.tempMonWidget.setAllowedAreas(Qt.RightDockWidgetArea)
            except TempMonitorError as e: 
                self.tempController=None
                QtGui.QMessageBox.warning(None,"Error","There was an error communicating with the temperature controller. The temperature monitor widget has been disabled:\n %s" % (e.args[0]))
        # Show status bar
        self.status=self.statusBar()
        self.status.showMessage("Ready",5000)
        # Set size of splitter
        self.mainSplitter.setStretchFactor(0,1)  # default setting to 1/4 for left size first time program is run
        self.mainSplitter.setStretchFactor(1,3)  # default setting to 3/4 for right size first time program is run
        if settings.value("MainSplitter"):
            # reload last splittler state if it was set
            self.mainSplitter.restoreState(settings.value("MainSplitter"))
        # Restore state of main window
        if settings.value("State"):
            self.restoreState(settings.value("State"))

    def measureDialog(self):
        """ Call the measurement dialog and start testing process based on user selection """
            # Show a warning window if pyvisa library wasn't imported successfuly
        PROCEED=True
        if DUMMY_MODE:       
            reply=QtGui.QMessageBox.question(None,"Warning",("The pyvisa library is not installed; no instrument communication is possible. Do you want to continue in Dummy mode?"),QtGui.QMessageBox.Yes|QtGui.QMessageBox.No)
            PROCEED=(reply==QtGui.QMessageBox.Yes)
        if PROCEED:
            self.AUTOMEASURE=False
            self.TEMP_STEP=5
            md=MeasureDialog(parent=self)
            if md.exec_(): 
                # Get the class which the measurment links to, as well as the test parameters which are used later in the singleMeasurement() method
                self.testMeasClass=md.getTestMeasClass()
                self.testDic=md.getTestParameters()                     
                if self.AUTOMEASURE:
                    lastMeasTime=datetime.now()
                    self.autoMeasureProgDialog=progDialog=QtGui.QProgressDialog("Automeasure on...","Abort",0,100,self)
                    #progDialog.setWindowModality(Qt.WindowModal)
                    progDialog.show()
                    self.measureTimer=self.startTimer(AUTOMEASURE_INTERVAL)
                    self.singleMeasurement()
                    self.autoMeasureProgDialog.setValue(1)
                    self.updateAutomeasureParams(lastMeasTime)
                else:
                    self.singleMeasurement()

    
    def showConsoleDialog(self):
        """ Shows the iPython console in a QDialog """
        if self.consoleDialog==None:
            self.consoleDialog=ConsoleDialog(self)
        self.consoleDialog.show()

    def showCurveFitDialog(self):
        self.currentMeas.curveFit(self.currentPlotIndex)

    def autoAlign(self, fineAlign = False):
        self.measProgDialog=QtGui.QProgressDialog("Performing automatic alignment... Please wait","Abort",0,100)
        self.measProgDialog.setWindowModality(Qt.WindowModal)
        self.measProgDialog.show()
        # Connect some signals and slots
        meas=measurement.Measurement({},False,parent=self,lock=self.lock)
        meas.progress.connect(self.updateProgressDialog)
        meas.progressMessage.connect(self.updateProgressMessage)
        meas.aborted.connect(self.measAborted)
        meas.measError.connect(self.measError)
        meas.finished.connect(self.measurementPostProcess)
        # Use the current coordinates as starting point rather than self.motorCoordinates
        # to allow for manual positioning by user via joystick
        m=MotorAlign()
        x0=m.ctrl.getPosition(align.X_CHANNEL)
        y0=m.ctrl.getPosition(align.Y_CHANNEL)
        self.motorCoordinates=(x0,y0)
        del m
        # Reset the Piezos to the center
        p=PiezoAlign()
        # Do either rough align or fine align depending on flag
        if fineAlign:
            # Move piezos to last known coordinates
            p.ctrl.setPosition(align.X_CHANNEL,self.piezoCoordinates[0])
            p.ctrl.setPosition(align.Y_CHANNEL,self.piezoCoordinates[1])
            # Start alignment process
            meas.fineAlign(p)
        else:
            # Reset piezo to center
            x0=p.ctrl.getPosition(align.X_CHANNEL)
            y0=p.ctrl.getPosition(align.Y_CHANNEL)
            self.piezoCoordinates=(x0,y0)
            del p
            meas.roughAlign()
        del self.measProgDialog

    def autoFineAlign(self):
        self.autoAlign(True)

    def startTemperatureProfile(self):
        # Create profile object
        self.profile=profile=Profile(self.tempController,self,self.lock)
        # Create custom progress dialog for profile
        self.profileProgressDialog=ProfileProgressDialog()
        # Connect the progress indicators from profile object to the dialog widgets
        profile.testProgress.connect(self.profileProgressDialog.testProgressBar.setValue)
        profile.testStatus.connect(self.profileProgressDialog.testProgressLabel.setText)
        profile.profileProgress.connect(self.profileProgressDialog.profileProgressBar.setValue)
        profile.profileStatus.connect(self.profileProgressDialog.profileProgressLabel.setText)
        self.profileProgressDialog.canceled.connect(profile.canceled)
        profile.finished.connect(self.profilePostProcess)
        # Connect forwarding signals between main and measurement object
        profile.plotDataReady.connect(self.canvas.renderPlot)
        profile.profileAborted.connect(self.profileAborted)
        profile.profileError.connect(self.profileError)
        self.canvas.readyToDraw.connect(profile.readyToDraw)
        profile.run()

    def winspecCalibration(self):
        """ Measure the Winspec calibration data necessary to capture a Winspec spectrum """
        try:
            readDetectorDefinition()
            w = Winspec()
            w.measureCalibration()
        except IOError:
            w = Winspec()

    def profileError(self,message=None):
        """ called from the profile object when it recognizes that there was a measurement error """
        del self.profileProgressDialog
        del self.profile
        QtGui.QMessageBox.warning(None,"Measurement error",("The current measurement was aborted due to a measurement error \n"+message))
    def profileAborted(self):
        """ called from the profile object when it recognizes that the user asked to abort the measurement """
        del self.profile
        QtGui.QMessageBox.warning(None,"Measurement aborted",("The current measurement was aborted by the user"))

    def profilePostProcess(self):
        del self.profileProgressDialog

    def timerEvent(self,event=None):
        """ Method called by form's QTimer event """
        if self.autoMeasureProgDialog.wasCanceled():
            self.AUTOMEASURE=False
            self.killTimer(self.measureTimer)
        lastMeasTime=datetime.now()
        temperature=self.tempController.getTemperature()
        self.testDic=self.testDic.copy()
        self.testDic["Name"]="{:3.1f}".format(temperature)+"K"
        self.singleMeasurement()
        value=self.autoMeasureProgDialog.value()
        self.autoMeasureProgDialog.setValue(value+1)
        self.updateAutomeasureParams(lastMeasTime)
    def singleMeasurement(self):
        """ makes a single measurement """
        # Create an object of the class specified in self.testMeasClass using the parameters in self.testDic
        testDic=self.testDic
        self.currentMeas=meas=self.testMeasClass(testDic,DUMMY_MODE,parent=self,lock=self.lock)
        # Show a progress dialog
        self.measProgDialog=QtGui.QProgressDialog("Measuring " + testDic["Label"] + " data... Please wait","Abort",0,100)
        self.measProgDialog.setWindowModality(Qt.WindowModal)
        self.measProgDialog.show()
        # Connect some signals and slots
        meas.progress.connect(self.updateProgressDialog)
        meas.progressMessage.connect(self.updateProgressMessage)
        meas.plotDataReady.connect(self.canvas.renderPlot)
        meas.aborted.connect(self.measAborted)
        meas.measError.connect(self.measError)
        meas.finished.connect(self.measurementPostProcess)
        self.canvas.readyToDraw.connect(meas.readyToDraw)
        self.measProgDialog.canceled.connect(meas.canceled)
        # TODO: Try get this working using a lambda function to pass the meas object to measurementPostProcess to aid trash collection
        
        # Create a new measurement thread if MULTI_THREADING flag set
        if MULTI_THREADING:
            self.measThread = measThread=QtCore.QThread()
            meas.moveToThread(measThread)
            # Connect the signals from measurement object to methods for multithreading to work
            measThread.started.connect(meas.acquireData)
            meas.aborted.connect(self.closeMeasThread)
            meas.finished.connect(self.closeMeasThread)
            # Start the thread and measurement
            measThread.start()
        else:
            # If no multithreading then just call acquireData directly
            meas.acquireData()
    def measError(self,message=None):
        """ called from the measurement object when it recognizes that there was a measurement error """
        del self.measProgDialog
        del self.currentMeas
        QtGui.QMessageBox.warning(None,"Measurement error",("The current measurement was aborted due to a measurement error \n"+message))
    def measAborted(self):
        """ called from the measurement object when it recognizes that the user asked to abort the measurement """
        del self.currentMeas
        QtGui.QMessageBox.warning(None,"Measurement aborted",("The current measurement was aborted by the user"))
    def measurementPostProcess(self):
        meas=self.currentMeas
        # Add the acquired data to the database
        #meas.insertIntoDatabase(self.session.db)
        self.session.saveToDB(meas)
        # Plot the data on the canvas
        meas.plot()        
        # add the measurement object to the session object
        self.session.append(meas)
        # repopulate the measurement tree
        self.populateTree(id(meas))
        QCoreApplication.processEvents()
    def updateProgressDialog(self,progress):
        """ Updates the progress dialog with progress """
        self.measProgDialog.setValue(progress)
        QCoreApplication.processEvents()
    def updateProgressMessage(self,message):
        """Updates the message shown by the progress dialog to give feedback to the user """
        self.measProgDialog.setLabelText(message)

    def updateAutomeasureParams(self,lastMeasTime):
        """ Updates the set temperature and next measurement time etc """
        setTemp=self.tempController.getSetTemperature()
        self.tempController.setTemperature(setTemp+self.TEMP_STEP)
        nextMeasTime=lastMeasTime+timedelta(milliseconds=AUTOMEASURE_INTERVAL)
        self.status.showMessage("Next measurement will occur at " + nextMeasTime.strftime("%H:%M:%S"))
        QCoreApplication.processEvents()


    def exportDialog(self):
        """ Exports the data for the currently selected test in self.dataTree. Would be better to show a custom dialog which allows bulk export """
        selectedTreeItems=self.dataTree.selectedItems()
        if len(selectedTreeItems) > 0 and selectedTreeItems[0].measurementObject!=None:
            selectedTreeItem=selectedTreeItems[0]
            # Load the directory from the last saved file in the QSettings structure
            s=QtCore.QSettings()
            dir=os.path.dirname(str(s.value("LastExportedFile",("."))))
            # Show save file dialog
            fname=unicode(QtGui.QFileDialog.getSaveFileName(self,"Choose Filename",dir,"Matlab data files (*.mat);; CSV text files (*.csv);; Numpy data file (*.pickle)"))
            if fname:
                index=selectedTreeItem.plotIndex
                selectedTreeItem.measurementObject.saveAs(fname,index)
                s.setValue("LastExportedFile",(fname))
        else:
            QtGui.QMessageBox.warning(None,"No item selected",("Please select an item to export from the tree on the left"))

    def openDialog(self):
        # Load the directory from the last opened file in the QSettings structure
        s=QtCore.QSettings()
        dir=os.path.dirname(str(s.value("LastOpenedFile",("."))))
        # Show an open file dialog 
        fname=unicode(QtGui.QFileDialog.getOpenFileName(self,"Choose Session File",dir,"HDF5 Database (*.h5);; Legacy sqlite database (*.db);; All Files (*)"))
        if fname:
            # Close the current console session if it's open
            if self.consoleDialog!=None:
                self.consoleDialog.close()
                self.consoleDialog=None
            # Open the database connection and add session object to self
            self.session=measurement.Session(False,fname,parent=self)
            self.session.plotDataReady.connect(self.canvas.renderPlot)
            self.canvas.axes.plot(0,0)
            self.populateTree()                
            s.setValue("LastOpenedFile",(fname))
            for meas in self.session.measurements:
                meas.plotDataReady.connect(self.canvas.renderPlot)
 
    def createAction(self, text, slot=None, shortcut=None, icon=None,
                    tip=None, checkable=False, signal="triggered()"):
        """Helper method to create a new action"""
        action =QtGui.QAction(text, self)
      
        if icon is not None:
            action.setIcon(QtGui.QIcon(":/%s.png" % icon))
        if shortcut is not None:
            action.setShortcut(shortcut)
        if tip is not None:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        if slot is not None:
            self.connect(action, QtCore.SIGNAL(signal), slot)
        if checkable:
            action.setCheckable(True)
        return action
    
    def closeEvent(self, event):
        """ Overrides the QMainWindow closeEvent() """
        if self.okToContinue():
            settings=QtCore.QSettings()
            settings.setValue("Geometry",(self.saveGeometry()))
            settings.setValue("State",(self.saveState()))
            settings.setValue("MainSplitter",(self.mainSplitter.saveState()))
        else:
            event.ignore()
    
    def okToContinue(self):
        """ Shows a confirmation dialog to check if the user wants to do anything before they quit """
        reply=QtGui.QMessageBox.question(None,"Do you want to proceed?","Are you sure you want to close the database? You can re-open it at any time.",QtGui.QMessageBox.Yes|QtGui.QMessageBox.No)
        if reply==QtGui.QMessageBox.Yes:
            return True
        elif reply==QtGui.QMessageBox.No:
            return False

    def populateTree(self, selectedMeasurement=None):
        """ Method which populates self.dataTree widget with all the items from top level (0) down to bottom level"""
        selected = None
        # Initialize the data tree
        self.dataTree.clear()
        self.dataTree.setColumnCount(2)
        self.dataTree.setHeaderLabels(["Test Property", "Value"])
        self.dataTree.setItemsExpandable(True)
        # Create some empty dictionaries to hold the parents for items at each level on the tree
        parentFromGroup = {}
        parentFromGroupType = {}
        parentFromGroupTypeName = {}
        # Get the list of all the measurement objects in the current session
        allMeasurements=self.session.dataByTimestamp()
        # Mark the last measurement as selected if selectedMeasurement not provided
        selectedMeasurement=id(allMeasurements[-1]) if (selectedMeasurement==None and size(allMeasurements)!=0) else selectedMeasurement
        # From the top to the bottom of the tree, create QTreeWidgetItems and fill the dictionary with parent info
        # TO DO: switch over to the new method session.getMeasTree() which should make this code significantly more readable
        for meas in allMeasurements:
            # Get the top level characteristics from the object
            groupName=meas.info["groupName"]
            typeName=meas.info["type"]
            testName=meas.info["Name"]
            # Retrieve or create new top level item for each measurement
            parent0 = parentFromGroup.get(groupName)
            if parent0 is None:
                parent0 = QTreeWidgetMeasItem(self.dataTree,[groupName],self.session)
                parentFromGroup[groupName] = parent0
            # Retrieve or create new second level item for each measurement
            groupType = groupName + "/" + typeName
            parent1 = parentFromGroupType.get(groupType)
            if parent1 is None:
                parent1 = QTreeWidgetMeasItem(parent0, [typeName],self.session,groupName=groupName)
                parentFromGroupType[groupType] = parent1
            # Retrieve or create new third level item for each measurement
            groupTypeName = groupName + "/" + typeName + "/" + testName
            parent2 = parentFromGroupTypeName.get(groupTypeName)
            if parent2 is None:
                parent2 = QTreeWidgetMeasItem(parent1, [testName],meas)
                parentFromGroupType[groupTypeName] = parent2
                # Get list of items for the data tree and add them
                for item in meas.dataSummary():    
                    child=self.addTreeItem(parent2,item,meas)
            # Check if the current item should be selected or expanded
            if selectedMeasurement is not None and selectedMeasurement == id(meas):
                selected = parent2
            # Expand all the top two level parent groups
            self.dataTree.expandItem(parent0)
            self.dataTree.expandItem(parent1)
        # Finish up configuring how the tree displays
        if selected is not None:
            selected.setSelected(True)
            self.dataTree.setCurrentItem(selected)
            self.dataTree.expandItem(selected)
        if len(self.session.dataByTimestamp()):
            self.dataTree.expandItem(parent2)
            self.dataTree.resizeColumnToContents(0)
            self.dataTree.resizeColumnToContents(1)
            #self.dataTree.collapseItem(parent2)
    def treeItemClicked(self,item,column):
        """ Catches the itemClicked() event in the data tree and plots accordingly """
        self.currentMeas=meas=item.measurementObject
        self.currentPlotIndex=item.plotIndex
        if meas!=None:
            # If the current measurement type is Session then give it a list with all the children meas objects in next branch of tree
            if type(item.measurementObject)==measurement.Session:
                if type(item.children()[0].measurementObject)!=measurement.Session:
                    self.session.activeMeasList=[child.measurementObject for child in item.children()]
                else:
                    self.session.activeMeasList=[child.measurementObject for child in item.children()[0].children()]
            # Setup progress dialog
            self.measProgDialog=QtGui.QProgressDialog("Plotting data... Please wait","Dismiss",0,100)
            self.measProgDialog.setWindowModality(Qt.WindowModal)
            self.measProgDialog.show()
            meas.plotProgress.connect(self.updateProgressDialog)
            meas.finishedPlottingSignal.connect(self.measProgDialog.hide)
            # Do the plot calculation either with single or multhreading depending on MULTI_THREADING flag
            if MULTI_THREADING:
                self.measThread=measThread=QtCore.QThread()
                meas.moveToThread(measThread)
                # Connect the signals from measurement object to methods for multithreading to work
                measThread.started.connect(meas.plot) # use lambda: meas.plot(item.plotIndex) instead?
                meas.finished.connect(self.closeMeasThread) 
                # Start the thread and measurement
                self.measThread.start()
            else:
                # Call the main plot command                
                if item.plotIndex != None:
                    item.measurementObject.plot(index=item.plotIndex)
                elif item.groupName != None:
                    item.measurementObject.plot(groupName=item.groupName)
                else:
                    item.measurementObject.plot()
                # also update the current meas in the console if it's open
                if self.consoleDialog!=None:
                    self.consoleDialog.updateCurrentMeas(item.measurementObject)

    def makeMeasPlotFunc(self):
        return lambda: self.currentMeas.plot(item.plotIndex)

    def closeMeasThread(self):
        """ Deletes the measurement thread """
        try:
            # I'm not sure if this is necessary, but not disconnecting finished seems to cause some problems
            self.currentMeas.finished.disconnect()
            self.currentMeas.aborted.disconnect()
            self.currentMeas.measError.disconnect()
        except TypeError:
            pass
        self.measThread.quit()
        self.measThread.wait()
        del self.measThread
    def treeItemChanged(self,item,column):
        """ Catches the itemChanged() event in the data tree and updates the info dictionary for the corresponding object in the database accordingly """
        if item.measurementObject!=None:
            if item.text(0)=="Enabled" and column==1:
                item.measurementObject.info["enabled"]=(item.checkState(column)==Qt.Checked)
                #self.session.updateDatabaseDictionary()
                self.session.saveToDB(item.measurementObject)

    def addTreeItem(self,parent,data,meas=None):
        """ Creates a QTreeWidgetMeasItem to parent with data list for each column and link to measurement object meas """
        if type(data)!=tuple:
            # If not tuple then data should just be of form [col1String,col2String]
            treeItem= QTreeWidgetMeasItem(parent,data,meas)      
            # Set right horizontal alignment / center vertical alignment
            treeItem.setTextAlignment(1, Qt.AlignRight|Qt.AlignVCenter)
            return treeItem
        else:
            # If tuple then data should be in form ([col1String,col2String],optionsDictionary,children)
            colData=data[0]
            treeItem=QTreeWidgetMeasItem(parent,colData,meas)
            for d in data[1:]:
                # extract the data from each remaining element in the tuple (allow order of options and children arbitrary)
                if type(d)==dict:
                    # If dictionary then we take various options and implement special features depending on the values set
                    if "index" in d:
                        treeItem.addPlotIndex(d["index"])
                    if "isCheckable" in d and d["isCheckable"]:
                        treeItem.setFlags(treeItem.flags()|Qt.ItemIsUserCheckable )
                    if "isChecked" in d:
                        treeItem.setCheckState(1,Qt.Checked if d["isChecked"] else Qt.Unchecked)
                elif type(d)==list:
                    # If list then assume it's a list of children, and we add child to current tree item for each element
                    for listElement in d:
                        self.addTreeItem(treeItem,listElement,meas)
                else:
                    raise TypeError,("Expected dictionary or list, received "+ str(type(element)))
            # Set right horizontal alignment / center vertical alignment
            treeItem.setTextAlignment(1, Qt.AlignRight|Qt.AlignVCenter)
            return treeItem


class QTreeWidgetMeasItem(QtGui.QTreeWidgetItem):
    """ Subclass of QTreeWidgetItem containing the parent object """
    def __init__(self,parent,data,meas=None,index=None, groupName=None):
        QtGui.QTreeWidgetItem.__init__(self,parent,data)
        self.measurementObject=meas
        self.plotIndex=index
        self.groupName=groupName
    def children(self):
        """ returns a list with all the children """
        numChildren=self.childCount()
        children=[]
        for index in range(numChildren):
            children.append(self.child(index))
        return children
    def addPlotIndex(self,index):
        self.plotIndex=index


class ConsoleDialog(QtGui.QDockWidget):
    """ Dialog which holds the console window """
    def __init__(self,parent=None):
        super(ConsoleDialog, self).__init__(parent)
        self.setWindowTitle("IPython Console")
        # Load the previous settings for size and position and test name
        s=QtCore.QSettings()
        size=s.value("ConsoleDialog/Size")
        pos=s.value("ConsoleDialog/Position")
        try:
            self.resize(size)
            self.move(pos)
        except TypeError as e:
            pass
        # Add the console to a layout
        layout = QtGui.QVBoxLayout(self)
        self.consoleWidget=QIPythonWidget()
        self.setWidget(self.consoleWidget)
        # Setup the namespace of the console with convenient values
        self.updateNamespace({'main':parent,"session":parent.session,"plot":parent.canvas.plot})
        self.consoleWidget.executeCommand("from __future__ import division",hide=True)
        self.consoleWidget.executeCommand("from numpy import *",hide=True)
        self.consoleWidget.printText("Welcome to the custom IPython QT console. In addition to numpy, the following variables are available: \n")
        self.consoleWidget.printText("'meas': the currently selected measurement object\n")
        self.consoleWidget.printText("'session': the session object (session.measurements contains the list of all measurement objects)\n")
        self.consoleWidget.printText("'main': the MainWindow object which holds all references\n")
        self.consoleWidget.printText("'plot()': a convenience method which plots arguments to the main canvas\n")
        self.consoleWidget._hidden=False
        # Add currently selected measurement to namespace
        selectedTreeItems=parent.dataTree.selectedItems()
        if len(selectedTreeItems) > 0 and selectedTreeItems[0] !=None and selectedTreeItems[0].measurementObject!=None:
            self.updateCurrentMeas(selectedTreeItems[0].measurementObject)

    def updateNamespace(self,variableDict):
        """ updates the namespace with name + value pairs given in arguments """
        self.consoleWidget.pushVariables(variableDict)
    def updateCurrentMeas(self,meas):
        """ sends meas to the namespace """
        self.updateNamespace({"meas":meas})

    def closeEvent(self,event):
        # Override the close event to save position etc
        settings=QtCore.QSettings()
        settings.setValue("ConsoleDialog/Size",(self.size()))
        settings.setValue("ConsoleDialog/Position",(self.pos()))

class MplCanvas(FigureCanvas):
    """Ultimately, this is a QWidget (as well as a FigureCanvasAgg, etc.)."""
    readyToDraw=QtCore.pyqtSignal()
    def __init__(self, parent=None, width=5, height=4, dpi=100):
        fig = Figure(figsize=(width, height), dpi=dpi)
        FigureCanvas.__init__(self, fig)
        self.setParent(parent)
        self.initialize(fig)
        self.addTwinAxis()
        self.compute_initial_figure()
        FigureCanvas.setSizePolicy(self,QtGui.QSizePolicy.Expanding,QtGui.QSizePolicy.Expanding)
        self.mplToolbar = NavigationToolbar(self,parent)
        FigureCanvas.updateGeometry(self)
        self.rendering=False
   
    def compute_initial_figure(self):
        """ Setup a default empty figure """
        self.axes.grid("on")
        self.axes.set_title("Light output and voltage vs. current")
        self.axes.set_ylabel("L [mW]")
        self.axes.set_xlabel("I [mA]")
        self.ax2.set_ylabel("V [V]")

    def initialize(self,fig):
        """ Clear and initialize the figure to most basic state """
        fig.clf()
        self.axes = fig.add_subplot(111)
        fig.subplots_adjust(bottom=0.11)
        fig.subplots_adjust(left=0.15)
        fig.subplots_adjust(right=0.85)
        #self.axes.hold(False)
    def addTwinAxis(self):
        """ Add a twin axis for showing two datasets on the same plot """
        self.ax2=self.axes.twinx()
        #self.ax2.hold(False)
    def renderPlot(self,dic):
        """ Renders the plot given dictionary containing necessary information """
        # Initialize the figure
        self.initialize(self.figure)
        if "title" in dic:
            self.axes.set_title(dic["title"])
        # Plot the data for first axis
        for idx in range(len(dic["y"]["data"])):
            if not dic["x"]["data"][idx] is None and not dic["y"]["data"][idx] is None:
                if "lineProp" in dic["y"]:
                    self.axes.plot(dic["x"]["data"][idx],dic["y"]["data"][idx],dic["y"]["lineProp"][idx])
                else:
                    self.axes.plot(dic["x"]["data"][idx],dic["y"]["data"][idx])
        self.axes.set_xlabel(dic["x"]["label"])
        self.axes.set_ylabel(dic["y"]["label"])
        self.axes.grid("on")
        # Set optional limits
        if "limit" in dic["x"]:
            self.axes.set_xlim(dic["x"]["limit"])
        if "limit" in dic["y"]:
            self.axes.set_ylim(dic["y"]["limit"])
        # Plot legend if given
        if "legend" in dic["y"]:
            l=self.axes.legend(dic["y"]["legend"],loc=(1.03,0.2))
            l.draggable(True)
        # Plot data for second y-axis if specified
        if "x2" in dic and "y2" in dic:
            self.addTwinAxis()
            self.ax2.set_ylabel(dic["y2"]["label"])
            for idx in range(len(dic["y2"]["data"])):
                if "lineProp" in dic["y2"]:
                    self.ax2.plot(dic["x2"]["data"][idx],dic["y2"]["data"][idx],dic["y2"]["lineProp"][idx])
                else:
                    self.ax2.plot(dic["x2"]["data"][idx],dic["y2"]["data"][idx])
            if "limit" in dic["y2"]:
                self.ax2.set_ylim(dic["y2"]["limit"])
            if "color" in dic["y2"]:
                self.ax2.set_ylabel(dic["y2"]["label"],color=dic["y2"]["color"])
                for tl in self.ax2.get_yticklabels():
                    tl.set_color(dic["y2"]["color"])
        # draw the canvas
        self.axes.ticklabel_format(useOffset=False)
        self.draw()
        QCoreApplication.processEvents()
        self.readyToDraw.emit()
    def plot(self,*args):
        """ Quick and dirty plot method for debugging purposes """
        self.initialize(self.figure)
        self.axes.plot(*args)
        self.axes.grid("on")
        self.draw()
        return self.axes

       
def main():
    app=QtGui.QApplication(sys.argv)
    app.setApplicationName(appName)  
    app.setOrganizationName("University of Tokyo")
    app.setOrganizationDomain("u-tokyo.ac.jp")
    app.setWindowIcon(QtGui.QIcon(":\laser.png"))
    # Show a message box asking if the user wants to create a new, or open existing session. TODO: Make a nicer dialog in the future.
    s=QtCore.QSettings()
    msgBox=QtGui.QMessageBox()
    msgBox.setText("A database connection is required for saving the data.")
    msgBox.addButton("Open Existing Database",QtGui.QMessageBox.NoRole)
    msgBox.addButton("Create New Database",QtGui.QMessageBox.YesRole)
    createNew=msgBox.exec_()
    dir=os.path.dirname(str(s.value("LastOpenedFile",".")))
    if createNew:
        # Show save file dialog
        fname=unicode(QtGui.QFileDialog.getSaveFileName(None,"Choose Filename",dir,"HDF5 Database (*.h5)"))
    else:
        # Show open file dialog
        fname=unicode(QtGui.QFileDialog.getOpenFileName(None,"Choose Database File",dir,"HDF5 Database (*.h5);; Legacy sqlite database (*.db);; All Files (*)"))
    if fname:
        # Execute the app if cancel wasn't pressed
        form=MainWindow(None,fname,createNew)
        form.show()
        app.exec_()


def handleException(exc_type, exc_value, exc_traceback):
  """ handle all exceptions """

  ## KeyboardInterrupt is a special case.
  ## We don't raise the error dialog when it occurs.
  if issubclass(exc_type, KeyboardInterrupt):
    if QtGui.qApp:
      QtGui.qApp.quit()
    return

  filename, line, dummy, dummy = traceback.extract_tb( exc_traceback ).pop()
  filename = os.path.basename( filename )
  error    = "%s: %s" % ( exc_type.__name__, exc_value )

  QtGui.QMessageBox.critical(None,"Error",
    "<html>A critical error has occured.<br/> "
  + "<b>%s</b><br/><br/>" % error
  + "It occurred at <b>line %d</b> of file <b>%s</b>.<br/>" % (line, filename)
  + "</html>")

  print "Closed due to an error. This is the full error report:"
  print
  print "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
  sys.exit(1)

if __name__=="__main__":
    # get any command line arguments
    argv=sys.argv
    # install handler for exceptions and run it if -Debug is not specified as command-line argument
    if not "-QTDebug" in argv:
        sys.excepthook = handleException
    # start the app
    main()
