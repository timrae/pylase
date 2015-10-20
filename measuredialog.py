from __future__ import division
from PyQt4 import QtGui,QtCore
from winspecanalyzer import getNumberOfPixels, getPixelResolutions

class MeasureDialog(QtGui.QDialog):
    """ Dialog shown to the user when they call the measure action """
    def  __init__(self,defaultTest=0,parent=None):
        super(MeasureDialog, self).__init__(parent)
        self.setWindowTitle("New Measurement")
        # Load the previous settings for size and position and test name
        settings=self.loadSettings()
        if settings["size"] and settings["pos"]:
            self.resize(settings["size"])
            self.move(settings["pos"])
        # Load all the group names from the session object
        self.allGroupNames=parent.session.getGroupNames()
        # Build a widget for each test type containing all of the controls required to set the parameters of the test
        self.allTestWidgets=[livWidget(),osaSpectrumWidget(),winspecSpectrumWidget(),winspecGainSpectrumWidget(),ManualWinspecSpectrumWidget(), RinSpectrumWidget()]
        # Build a widget for the test setup at the top of the dialog and the button boxes down the bottom
        testSetupWidget=self.buildTestSetupWidget()
        buttonBoxWidget=self.buildButtonBoxWidget()
        # Put the different tests inside a stacked widget so that only the appropriate settings are shown
        self.stackedWidget=QtGui.QStackedWidget()
        self.addWidgets(self.stackedWidget,self.allTestWidgets)
        # Set the previous value for the test type
        self.testSelector.setCurrentIndex(settings["testIndex"])
        # Setup the main layout
        mainLayout=QtGui.QVBoxLayout()
        mainLayout.addWidget(testSetupWidget)
        mainLayout.addWidget(self.stackedWidget)
        mainLayout.addWidget(buttonBoxWidget)
        self.setLayout(mainLayout)
        # Highlight (i.e. select the text of) the group name if first test, otherwise highlight the test description
        if len(self.allGroupNames):
            self.testNameText.setFocus()
            self.testNameText.selectAll()
        else:
            self.groupNameCombo.lineEdit().selectAll()
        # Create empty testParameters dictionary
        self.testParameters={}
        # Show the dialog and widgets
        self.setModal(True)
        self.show()
    def addWidgets(self,parentWidget,childWidgets):
        """ Calls the addWidget(child) method on parentWidget for each of the child widgets """
        for child in childWidgets:
            parentWidget.addWidget(child)
    def buildTestSetupWidget(self):
        """ Build the main test setup widget which defines the name, test type etc """
        # Load the last settings for the sub-widgets
        settings=self.loadSettings()
        groupName=settings["groupName"]
        testName=settings["testName"]
        # Create all the sub-widgets
        groupNameLabel=QtGui.QLabel("Group Name")
        self.groupNameCombo=QtGui.QComboBox()
        self.groupNameCombo.setEditable(True)
        self.groupNameCombo.addItems(self.allGroupNames)
        try:
            index=self.allGroupNames.index(groupName)
            self.groupNameCombo.setCurrentIndex(index)
        except ValueError:
            self.groupNameCombo.setEditText(groupName)
        testNameLabel=QtGui.QLabel("Test Description")
        self.testNameText=QtGui.QLineEdit(testName)
        testSelectorLabel=QtGui.QLabel("Type of test")
        self.testSelector=QtGui.QComboBox()
        for testWidget in self.allTestWidgets:
            self.testSelector.addItem(testWidget.measurementLabel)
        self.measureButton=QtGui.QPushButton("Acquire Data")
        self.cancelButton=QtGui.QPushButton("Cancel")
        # Create layout and add the above sub-widgets to it
        topLayout=QtGui.QGridLayout()
        topLayout.addWidget(groupNameLabel,0,0,1,1)
        topLayout.addWidget(self.groupNameCombo,1,0,1,1)
        topLayout.addWidget(testNameLabel,2,0,1,1)
        topLayout.addWidget(self.testNameText,3,0,1,1)
        topLayout.addWidget(testSelectorLabel,4,0,1,1)
        topLayout.addWidget(self.testSelector,5,0,1,1)
        # Attach the layout to a widget and return it
        testSetupWidget=QtGui.QWidget()
        testSetupWidget.setLayout(topLayout)
        return testSetupWidget
    def buildButtonBoxWidget(self):
        """ Build a widget containing the main buttons for the dialog """
        buttonBoxLayout=QtGui.QHBoxLayout()
        buttonBoxLayout.addWidget(self.measureButton)
        buttonBoxLayout.addWidget(self.cancelButton)
        # Connect the buttons and combobox to appropriate methods
        self.connect(self.measureButton,QtCore.SIGNAL("clicked()"),self.accept)
        self.connect(self.cancelButton,QtCore.SIGNAL("clicked()"),self.reject)
        self.connect(self.testSelector,QtCore.SIGNAL("currentIndexChanged(int)"),self.changeTestType)
        # Add the layout to a widget
        buttonBoxWidget=QtGui.QWidget()
        buttonBoxWidget.setLayout(buttonBoxLayout)
        return buttonBoxWidget


    def changeTestType(self,testNumber):
        """ Called when testType combo box is changed. Sets the tab of the stacked widget to show corresponding test parameters"""
        self.stackedWidget.setCurrentIndex(testNumber)
        self.testNameText.selectAll()
        self.testNameText.setFocus()

    def accept(self):
        """ Override the accept method to do some data checking and update the testParameters dictionary """
        # Spacer to implement some data checking

        # Add the appropriate test parameters to the dictionary
        self.testParameters["groupName"]=unicode(self.groupNameCombo.currentText())
        self.testParameters["Name"]=unicode(self.testNameText.text())
        # Get the parameters for the test
        testWidget=self.allTestWidgets[self.testSelector.currentIndex()]
        self.testParameters.update(testWidget.getParameters())
        # Save the parameters for the next time the form is loaded
        self.saveSettings()
        # Run the normal accept method for QDialog
        QtGui.QDialog.accept(self)

    def getTestParameters(self):
        """ Return the test parameters dictionary for correct test from the testParameters array """
        return self.testParameters
    def getTestMeasClass(self):
        """ Return the test type (LIV/Spectrum) as a string """
        testWidget=self.allTestWidgets[self.testSelector.currentIndex()]
        return testWidget.measurementClass

    def saveSettings(self):
        """ Save all the settings for the form and widgets """
        settings=QtCore.QSettings()
        # Save size/pos and all widget settings which contain useful data
        settings.setValue("MeasurementDialog/Size",(self.size()))
        settings.setValue("MeasurementDialog/Position",(self.pos()))        
        settings.setValue("testName",(self.testNameText.text()))
        settings.setValue("groupName",(self.groupNameCombo.currentText()))
        settings.setValue("testIndex",(self.testSelector.currentIndex()))
        testWidget=self.allTestWidgets[self.testSelector.currentIndex()]
        testWidget.saveSettings()

    def loadSettings(self):
        """ Load last values from QSettings"""
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["size"]=s.value("MeasurementDialog/Size")
        settingsDict["pos"]=s.value("MeasurementDialog/Position")
        # Should probably add MeasurementDialog/... to these
        settingsDict["testIndex"]=s.value("testIndex",(0))
        settingsDict["groupName"]=s.value("groupName",("Unit 1"))
        settingsDict["testName"]=s.value("testName",("25"+u'\u00B0'+"C"))
        return settingsDict
            
    def closeEvent(self,event):
        # Override the close event to save position etc
        settings=QtCore.QSettings()
        settings.setValue("MeasurementDialog/Size",(self.size()))
        settings.setValue("MeasurementDialog/Position",(self.pos()))

class testWidget(QtGui.QWidget):
    """ Subclass QWidget for each test type which we hope to run. This is the parent class which holds common methods and properties """
    def  __init__(self,defaultTest=0,parent=None):
        super(testWidget, self).__init__(parent)

class livWidget(testWidget):
    def  __init__(self,defaultTest=0,parent=None):
        super(livWidget, self).__init__(parent)
        self.measurementLabel="LIV"
        # Link the class which will hold the measurement data
        from measurement import LIV
        self.measurementClass=LIV
        self.build()

    def build(self):
        """ Build the widget holding the controls for LIV measurements with SMU and power meter """
        # Load last settings for LIV test
        settings=self.loadSettings()
        # Create the sub-widgets for LIV test
        livStartCurrentLabel=QtGui.QLabel("Start I (mA)")
        self.livStartCurrentText=QtGui.QLineEdit(settings["startCurrent"])
        livStopCurrentLabel=QtGui.QLabel("Stop I (mA)")
        self.livStopCurrentText=QtGui.QLineEdit(settings["stopCurrent"])
        livNumCurrPointsLabel=QtGui.QLabel("Num I points")
        self.livNumCurrPointsText=QtGui.QLineEdit(settings["numCurrPoints"])
        livCompVoltageLabel=QtGui.QLabel("Compliance (V)")
        self.livCompVoltageText=QtGui.QLineEdit(settings["Vcomp"])
        self.roughAlignCheckbox=QtGui.QCheckBox("Rough Alignment")
        self.roughAlignCheckbox.setCheckState(settings["roughAlign"])
        self.fineAlignCheckbox=QtGui.QCheckBox("Fine Alignment")
        self.fineAlignCheckbox.setCheckState(settings["fineAlign"])
        #  Put the sub-widgets for LIV test inside a layout and set that as the QWidget layout
        livLayout=QtGui.QGridLayout()
        livLayout.addWidget(livStartCurrentLabel,0,0)
        livLayout.addWidget(livStopCurrentLabel,0,1)
        livLayout.addWidget(livCompVoltageLabel,0,2)
        livLayout.addWidget(livNumCurrPointsLabel,0,3)
        livLayout.addWidget(self.livStartCurrentText,1,0)
        livLayout.addWidget(self.livStopCurrentText,1,1)
        livLayout.addWidget(self.livCompVoltageText,1,2)
        livLayout.addWidget(self.livNumCurrPointsText,1,3)
        livLayout.addWidget(self.roughAlignCheckbox,2,0,1,1)
        livLayout.addWidget(self.fineAlignCheckbox,4,0,1,1)
        self.setLayout(livLayout)  
    def getParameters(self):
        """ return a dictionary containing all of the parameters for the test object """
        testParameters={}
        testParameters["Label"]=self.measurementLabel
        testParameters["Istart"]=float(self.livStartCurrentText.text())/1000 # mA
        testParameters["Istop"]=float(self.livStopCurrentText.text())/1000   # mA
        testParameters["numCurrPoints"]=int(self.livNumCurrPointsText.text())
        testParameters["Vcomp"]=float(self.livCompVoltageText.text())
        testParameters["roughAlign"]=self.roughAlignCheckbox.isChecked()
        testParameters["fineAlign"]=self.fineAlignCheckbox.isChecked()
        return testParameters
    def saveSettings(self):
        # Save current values to QSettings
        settings=QtCore.QSettings()
        settings.setValue("LIV/startCurrent",(self.livStartCurrentText.text()))
        settings.setValue("LIV/stopCurrent",(self.livStopCurrentText.text()))
        settings.setValue("LIV/numCurrPoints",(self.livNumCurrPointsText.text()))
        settings.setValue("LIV/Vcomp",(self.livCompVoltageText.text()))
        settings.setValue("LIV/roughAlign",(self.roughAlignCheckbox.checkState()))
        settings.setValue("LIV/fineAlign",(self.fineAlignCheckbox.checkState()))   

    def loadSettings(self):
        """ Load last values from QSettings"""
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["startCurrent"]=s.value("LIV/startCurrent",("5"))
        settingsDict["stopCurrent"]=s.value("LIV/stopCurrent",("30"))
        settingsDict["numCurrPoints"]=s.value("LIV/numCurrPoints",("101"))
        settingsDict["Vcomp"]=s.value("LIV/Vcomp",("2.0"))
        settingsDict["roughAlign"]=s.value("LIV/roughAlign",False)
        settingsDict["fineAlign"]=s.value("LIV/fineAlign",False)
        return settingsDict

class spectrumWidget(testWidget):
    def  __init__(self,defaultTest=0,parent=None):
        super(spectrumWidget, self).__init__(parent)

class osaSpectrumWidget(spectrumWidget):
    def  __init__(self,defaultTest=0,parent=None):
        super(osaSpectrumWidget, self).__init__(parent)
        self.measurementLabel="Spectrum (OSA)"
        # Link the class which will hold the measurement data
        from measurement import AdvantestSpectrum
        self.measurementClass=AdvantestSpectrum               
        self.build()
    def build(self):
        """ Build the widget holding the controls for a spectrum measurements with the OSA """
        settings=self.loadSettings()
        # Create the sub-widgets for OSA spectrum test
        self.specStartCurrentLabel=QtGui.QLabel("Start I (mA)")
        self.specStartCurrentText=QtGui.QLineEdit(settings["startCurrent"])
        self.specStopCurrentLabel=QtGui.QLabel("Stop I (mA)")
        self.specStopCurrentText=QtGui.QLineEdit(settings["stopCurrent"])
        self.specNumCurrPointsLabel=QtGui.QLabel("Num I points")
        self.specNumCurrPointsText=QtGui.QLineEdit(settings["numCurrPoints"])
        self.specCompVoltageLabel=QtGui.QLabel("Compliance (V)")
        self.specCompVoltageText=QtGui.QLineEdit(settings["Vcomp"])
        self.specCenterLambdaLabel=QtGui.QLabel("Center &lambda; (um)")
        self.specCenterLambdaLabel.setTextFormat(1)
        self.specCenterLambdaText=QtGui.QLineEdit(settings["centerLambda"])
        self.specNumLambdaLabel=QtGui.QLabel("Num &lambda; points")
        self.specNumLambdaLabel.setTextFormat(1)
        self.specNumLambdaCombo=QtGui.QComboBox()
        self.specNumLambdaCombo.addItems(["101","201","501","1001","2001","5001","10001"])
        self.specNumLambdaCombo.setCurrentIndex(int(settings["numLambdaIndex"]))
        self.specResLabel=QtGui.QLabel("Resolution (nm)")
        self.specResCombo=QtGui.QComboBox()
        self.specResCombo.addItems([".01",".02",".05",".1",".2",".5"])
        self.specResCombo.setCurrentIndex(int(settings["resolutionIndex"]))
        self.specSpanLabel=QtGui.QLabel("Span (nm)")
        self.specSpanText=QtGui.QLineEdit(settings.get("span","0"))
        self.roughAlignCheckbox=QtGui.QCheckBox("Rough Alignment")
        self.roughAlignCheckbox.setCheckState(settings["roughAlign"])
        self.fineAlignCheckbox=QtGui.QCheckBox("Fine Alignment")
        self.fineAlignCheckbox.setCheckState(settings["fineAlign"])
        # Connect the resolution and number of points combo boxes to auto-complete the span based on the product of their respective values
        self.updateSpan()
        self.specSpanText.setEnabled(False)
        self.connect(self.specResCombo,QtCore.SIGNAL("currentIndexChanged(int)"),self.updateSpan)
        self.connect(self.specNumLambdaCombo,QtCore.SIGNAL("currentIndexChanged(int)"),self.updateSpan)
        #  Put the sub-widgets inside a parent widget / layout and return it
        spectrumWidget=QtGui.QWidget()
        self.spectrumLayout=spectrumLayout=QtGui.QGridLayout()
        spectrumLayout.addWidget(self.specStartCurrentLabel,0,0)
        spectrumLayout.addWidget(self.specStopCurrentLabel,0,1)
        spectrumLayout.addWidget(self.specCompVoltageLabel,0,2)
        spectrumLayout.addWidget(self.specNumCurrPointsLabel,0,3)
        spectrumLayout.addWidget(self.specStartCurrentText,1,0)
        spectrumLayout.addWidget(self.specStopCurrentText,1,1)
        spectrumLayout.addWidget(self.specCompVoltageText,1,2)
        spectrumLayout.addWidget(self.specNumCurrPointsText,1,3)
        spectrumLayout.addWidget(self.specCenterLambdaLabel,2,0)
        spectrumLayout.addWidget(self.specResLabel,2,1)
        spectrumLayout.addWidget(self.specSpanLabel,2,2)
        spectrumLayout.addWidget(self.specNumLambdaLabel,2,3)
        spectrumLayout.addWidget(self.specCenterLambdaText,3,0)
        spectrumLayout.addWidget(self.specResCombo,3,1)
        spectrumLayout.addWidget(self.specSpanText,3,2)
        spectrumLayout.addWidget(self.specNumLambdaCombo,3,3)
        alignWidget=QtGui.QWidget()
        alignWidgetLayout=QtGui.QHBoxLayout()
        alignWidget.setLayout(alignWidgetLayout)
        alignWidgetLayout.addWidget(self.roughAlignCheckbox,0)
        alignWidgetLayout.addWidget(self.fineAlignCheckbox,1)
        spectrumLayout.addWidget(alignWidget,4,0,1,2)
        self.setLayout(spectrumLayout)
    def updateSpan(self,dummyIndex=None):
        """ Helper function to update the span text box by multiplying the resolution and number of points """
        try:
            self.specSpanText.setText(str(int(float(self.specResCombo.currentText())*(int(self.specNumLambdaCombo.currentText())-1))))
        except Exception as e:
            print(e.args[0])
    def getParameters(self):
        """ return a dictionary containing all of the parameters for the test object """
        testParameters={}
        testParameters["Label"]=self.measurementLabel
        testParameters["Istart"]=float(self.specStartCurrentText.text())/1000 # mA
        testParameters["Istop"]=float(self.specStopCurrentText.text())/1000   # mA
        testParameters["numCurrPoints"]=int(self.specNumCurrPointsText.text())
        testParameters["Vcomp"]=float(self.specCompVoltageText.text())
        testParameters["Center"]=float(self.specCenterLambdaText.text())/1e6 #um
        testParameters["Resolution"]=float(self.specResCombo.currentText())/1e9 #nm
        testParameters["numLambdaPoints"]=int(self.specNumLambdaCombo.currentText())
        testParameters["numLambdaIndex"]=int(self.specNumLambdaCombo.currentIndex())
        testParameters["Span"]=float(self.specSpanText.text())/1e9 #nm
        # Hard code the sweep mode for now, need to add it to the measurement dialog
        # (0=Normal,1=Adaptive,2=Hi-sens 1,3=Hi-sens 2,Pulse,Hi-Dynamic 1,Hi-Dynamic 2)
        testParameters["SweepMode"]=2
        testParameters["roughAlign"]=self.roughAlignCheckbox.isChecked()
        testParameters["fineAlign"]=self.fineAlignCheckbox.isChecked()
        testParameters
        return testParameters
    def saveSettings(self):
        # Save current values to QSettings
        settings=QtCore.QSettings()
        settings.setValue("Spectrum/osa/startCurrent",(self.specStartCurrentText.text()))
        settings.setValue("Spectrum/osa/stopCurrent",(self.specStopCurrentText.text()))
        settings.setValue("Spectrum/osa/numCurrPoints",(self.specNumCurrPointsText.text()))
        settings.setValue("Spectrum/osa/Vcomp",(self.specCompVoltageText.text()))
        settings.setValue("Spectrum/osa/centerLambda",(self.specCenterLambdaText.text()))
        settings.setValue("Spectrum/osa/numLambdaIndex",(self.specNumLambdaCombo.currentIndex()))
        settings.setValue("Spectrum/osa/resolutionIndex",(self.specResCombo.currentIndex()))
        settings.setValue("Spectrum/osa/roughAlign",(self.roughAlignCheckbox.checkState()))
        settings.setValue("Spectrum/osa/fineAlign",(self.fineAlignCheckbox.checkState()))   

    def loadSettings(self):
        """ Load last values from QSettings"""
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["startCurrent"]=s.value("Spectrum/osa/startCurrent",("5"))
        settingsDict["stopCurrent"]=s.value("Spectrum/osa/stopCurrent",("10"))
        settingsDict["numCurrPoints"]=s.value("Spectrum/osa/numCurrPoints",("11"))
        settingsDict["Vcomp"]=s.value("Spectrum/osa/Vcomp",("1.5"))
        settingsDict["centerLambda"]=s.value("Spectrum/osa/centerLambda",("1.3"))
        settingsDict["numLambdaIndex"]=s.value("Spectrum/osa/numLambdaIndex",("3"))
        settingsDict["resolutionIndex"]=s.value("Spectrum/osa/resolutionIndex",("1"))
        settingsDict["roughAlign"]=s.value("Spectrum/osa/roughAlign",False)
        settingsDict["fineAlign"]=s.value("Spectrum/osa/fineAlign",False)
        return settingsDict


class winspecSpectrumWidget(spectrumWidget):
    def  __init__(self,defaultTest=0,parent=None):
        super(winspecSpectrumWidget, self).__init__(parent)
        self.measurementLabel="Spectrum (Winspec)"
        # Link the class which will hold the measurement data
        from measurement import WinspecSpectrum
        self.measurementClass=WinspecSpectrum
        self.build()        

    def build(self):
        """ Build the widget holding the controls for a spectrum measurements with the OSA """
        # Load last settings for OSA spectrum test
        settings=self.loadSettings()
        # Create the sub-widgets for OSA spectrum test
        specStartCurrentLabel=QtGui.QLabel("Start I (mA)")
        self.specStartCurrentText=QtGui.QLineEdit(settings["startCurrent"])
        specStopCurrentLabel=QtGui.QLabel("Stop I (mA)")
        self.specStopCurrentText=QtGui.QLineEdit(settings["stopCurrent"])
        specNumCurrPointsLabel=QtGui.QLabel("Num I points")
        self.specNumCurrPointsText=QtGui.QLineEdit(settings["numCurrPoints"])
        specCompVoltageLabel=QtGui.QLabel("Compliance (V)")
        self.specCompVoltageText=QtGui.QLineEdit(settings["Vcomp"])
        specCenterLambdaLabel=QtGui.QLabel("Center &lambda; (um)")
        specCenterLambdaLabel.setTextFormat(1)
        self.specCenterLambdaText=QtGui.QLineEdit(settings["centerLambda"])
        specNumLambdaLabel=QtGui.QLabel("Num &lambda; points")
        specNumLambdaLabel.setTextFormat(1)
        self.specNumLambdaCombo=QtGui.QComboBox()
        self.roughAlignCheckbox=QtGui.QCheckBox("Rough Alignment")
        self.roughAlignCheckbox.setCheckState(settings["roughAlign"])
        self.fineAlignCheckbox=QtGui.QCheckBox("Fine Alignment")
        self.fineAlignCheckbox.setCheckState(settings["fineAlign"])
        # Allow up to 15 spectra to be glued together (must be odd number so that center isn't a transition)
        numPointsStr=[str(x*getNumberOfPixels()) for x in range(1,16,2)]
        self.specNumLambdaCombo.addItems(numPointsStr)
        self.specNumLambdaCombo.setCurrentIndex(settings["numLambdaIndex"])
        specResLabel=QtGui.QLabel("Resolution (nm)")
        self.specResCombo=QtGui.QComboBox()
        resolutions=getPixelResolutions()
        self.specResCombo.addItems([str(num) for num in resolutions])
        self.specResCombo.setCurrentIndex(settings["resolutionIndex"])
        specSpanLabel=QtGui.QLabel("Span (nm)")
        self.specSpanText=QtGui.QLineEdit()
        # Connect the resolution and number of points combo boxes to auto-complete the span based on the product of their respective values
        self.updateSpan()
        self.specSpanText.setEnabled(False)
        self.connect(self.specResCombo,QtCore.SIGNAL("currentIndexChanged(int)"),self.updateSpan)
        self.connect(self.specNumLambdaCombo,QtCore.SIGNAL("currentIndexChanged(int)"),self.updateSpan)
        #  Put the sub-widgets inside a parent widget / layout and return it
        spectrumWidget=QtGui.QWidget()
        self.spectrumLayout=spectrumLayout=QtGui.QGridLayout()
        spectrumLayout.addWidget(specStartCurrentLabel,0,0)
        spectrumLayout.addWidget(specStopCurrentLabel,0,1)
        spectrumLayout.addWidget(specCompVoltageLabel,0,2)
        spectrumLayout.addWidget(specNumCurrPointsLabel,0,3)
        spectrumLayout.addWidget(self.specStartCurrentText,1,0)
        spectrumLayout.addWidget(self.specStopCurrentText,1,1)
        spectrumLayout.addWidget(self.specCompVoltageText,1,2)
        spectrumLayout.addWidget(self.specNumCurrPointsText,1,3)
        spectrumLayout.addWidget(specCenterLambdaLabel,2,0)
        spectrumLayout.addWidget(specResLabel,2,1)
        spectrumLayout.addWidget(specSpanLabel,2,2)
        spectrumLayout.addWidget(specNumLambdaLabel,2,3)
        spectrumLayout.addWidget(self.specCenterLambdaText,3,0)
        spectrumLayout.addWidget(self.specResCombo,3,1)
        spectrumLayout.addWidget(self.specSpanText,3,2)
        spectrumLayout.addWidget(self.specNumLambdaCombo,3,3)
        spectrumLayout.addWidget(self.roughAlignCheckbox,4,0,1,2)
        spectrumLayout.addWidget(self.fineAlignCheckbox,5,0,1,2)
        self.setLayout(spectrumLayout)
    def updateSpan(self,dummyIndex=None):
        """ Helper function to update the span text box by multiplying the resolution and number of points """
        self.specSpanText.setText(str(int(float(self.specResCombo.currentText())*(int(self.specNumLambdaCombo.currentText())-1))))
    def getParameters(self):
        """ return a dictionary containing all of the parameters for the test object """
        testParameters={}
        testParameters["Label"]=self.measurementLabel
        testParameters["Istart"]=float(self.specStartCurrentText.text())/1000 # mA
        testParameters["Istop"]=float(self.specStopCurrentText.text())/1000   # mA
        testParameters["numCurrPoints"]=int(self.specNumCurrPointsText.text())
        testParameters["Vcomp"]=float(self.specCompVoltageText.text())
        testParameters["Center"]=float(self.specCenterLambdaText.text())/1e6 #um
        testParameters["Resolution"]=float(self.specResCombo.currentText())/1e9 #nm
        testParameters["numLambdaPoints"]=int(self.specNumLambdaCombo.currentText())
        testParameters["numLambdaIndex"]=int(self.specNumLambdaCombo.currentIndex())
        testParameters["Span"]=float(self.specSpanText.text())/1e9 #nm
        testParameters["roughAlign"]=self.roughAlignCheckbox.isChecked()
        testParameters["fineAlign"]=self.fineAlignCheckbox.isChecked()
        return testParameters   
    def saveSettings(self):
        # Save current values to QSettings
        settings=QtCore.QSettings()
        settings.setValue("Spectrum/Winspec/startCurrent",(self.specStartCurrentText.text()))
        settings.setValue("Spectrum/Winspec/stopCurrent",(self.specStopCurrentText.text()))
        settings.setValue("Spectrum/Winspec/numCurrPoints",(self.specNumCurrPointsText.text()))
        settings.setValue("Spectrum/Winspec/Vcomp",(self.specCompVoltageText.text()))
        settings.setValue("Spectrum/Winspec/centerLambda",(self.specCenterLambdaText.text()))
        settings.setValue("Spectrum/Winspec/numLambdaIndex",(self.specNumLambdaCombo.currentIndex()))
        settings.setValue("Spectrum/Winspec/resolutionIndex",(self.specResCombo.currentIndex()))
        settings.setValue("Spectrum/Winspec/roughAlign",(self.roughAlignCheckbox.checkState()))
        settings.setValue("Spectrum/Winspec/fineAlign",(self.fineAlignCheckbox.checkState()))   

    def loadSettings(self):
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["startCurrent"]=s.value("Spectrum/Winspec/startCurrent",("5"))
        settingsDict["stopCurrent"]=s.value("Spectrum/Winspec/stopCurrent",("10"))
        settingsDict["numCurrPoints"]=s.value("Spectrum/Winspec/numCurrPoints",("11"))
        settingsDict["Vcomp"]=s.value("Spectrum/Winspec/Vcomp",("1.5"))
        settingsDict["centerLambda"]=s.value("Spectrum/Winspec/centerLambda",("1.3"))
        settingsDict["numLambdaIndex"]=int(s.value("Spectrum/Winspec/numLambdaIndex",("3")))
        settingsDict["resolutionIndex"]=int(s.value("Spectrum/Winspec/resolutionIndex",("1")))
        settingsDict["roughAlign"]=s.value("Spectrum/Winspec/roughAlign",False)
        settingsDict["fineAlign"]=s.value("Spectrum/Winspec/fineAlign",False)
        return settingsDict

class winspecGainSpectrumWidget(winspecSpectrumWidget):
    def  __init__(self,*args,**kwargs):
        super(winspecGainSpectrumWidget, self).__init__(*args,**kwargs)
        self.measurementLabel="Gain Spectrum (Winspec)"
        # Link the class which will hold the measurement data
        from measurement import WinspecGainSpectrum
        self.measurementClass=WinspecGainSpectrum
        #self.build()

    def saveSettings(self):
        # Save current values to QSettings
        settings=QtCore.QSettings()
        settings.setValue("Spectrum/WinspecGain/startCurrent",(self.specStartCurrentText.text()))
        settings.setValue("Spectrum/WinspecGain/stopCurrent",(self.specStopCurrentText.text()))
        settings.setValue("Spectrum/WinspecGain/numCurrPoints",(self.specNumCurrPointsText.text()))
        settings.setValue("Spectrum/WinspecGain/Vcomp",(self.specCompVoltageText.text()))
        settings.setValue("Spectrum/WinspecGain/centerLambda",(self.specCenterLambdaText.text()))
        settings.setValue("Spectrum/WinspecGain/numLambdaIndex",(self.specNumLambdaCombo.currentIndex()))
        settings.setValue("Spectrum/WinspecGain/resolutionIndex",(self.specResCombo.currentIndex()))
        settings.setValue("Spectrum/WinspecGain/roughAlign",(self.roughAlignCheckbox.checkState()))
        settings.setValue("Spectrum/WinspecGain/fineAlign",(self.fineAlignCheckbox.checkState()))        

    def loadSettings(self):
        """ Load the last used or default settings """
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["startCurrent"]=s.value("Spectrum/WinspecGain/startCurrent",("5"))
        settingsDict["stopCurrent"]=s.value("Spectrum/WinspecGain/stopCurrent",("10"))
        settingsDict["numCurrPoints"]=s.value("Spectrum/WinspecGain/numCurrPoints",("11"))
        settingsDict["Vcomp"]=s.value("Spectrum/WinspecGain/Vcomp",("1.5"))
        settingsDict["centerLambda"]=s.value("Spectrum/WinspecGain/centerLambda",("1.3"))
        settingsDict["numLambdaIndex"]=int(s.value("Spectrum/WinspecGain/numLambdaIndex",("3")))
        settingsDict["resolutionIndex"]=int(s.value("Spectrum/WinspecGain/resolutionIndex",("1")))
        settingsDict["roughAlign"]=s.value("Spectrum/WinspecGain/roughAlign",False)
        settingsDict["fineAlign"]=s.value("Spectrum/WinspecGain/fineAlign",False)
        return settingsDict


class ManualWinspecSpectrumWidget(winspecSpectrumWidget):
    def  __init__(self,*args,**kwargs):
        super(ManualWinspecSpectrumWidget, self).__init__(*args,**kwargs)
        self.measurementLabel="Manual Spectrum (Winspec)"
        # Link the class which will hold the measurement data
        from measurement import ManualWinspecSpectrum
        self.measurementClass=ManualWinspecSpectrum
        #self.build()

    def build(self):
        super(ManualWinspecSpectrumWidget, self).build()
        #self.specStopCurrentText.setEnabled(False)
        #specNumCurrPointsText.setEnabled(False)
        self.specCompVoltageText.setEnabled(False)

    def saveSettings(self):
        # Save current values to QSettings
        settings=QtCore.QSettings()
        settings.setValue("Spectrum/WinspecManual/startCurrent",(self.specStartCurrentText.text()))
        settings.setValue("Spectrum/WinspecManual/stopCurrent",(self.specStopCurrentText.text()))
        settings.setValue("Spectrum/WinspecManual/numCurrPoints",(self.specNumCurrPointsText.text()))
        #settings.setValue("Spectrum/WinspecManual/Vcomp",(self.specCompVoltageText.text()))
        settings.setValue("Spectrum/WinspecManual/centerLambda",(self.specCenterLambdaText.text()))
        settings.setValue("Spectrum/WinspecManual/numLambdaIndex",(self.specNumLambdaCombo.currentIndex()))
        settings.setValue("Spectrum/WinspecManual/resolutionIndex",(self.specResCombo.currentIndex()))
        settings.setValue("Spectrum/WinspecManual/roughAlign",(self.roughAlignCheckbox.checkState()))
        settings.setValue("Spectrum/WinspecManual/fineAlign",(self.fineAlignCheckbox.checkState()))        

    def loadSettings(self):
        """ Load the last used or default settings """
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["startCurrent"]=s.value("Spectrum/WinspecManual/startCurrent",("5"))
        settingsDict["stopCurrent"]=s.value("Spectrum/WinspecManual/stopCurrent",("10"))
        settingsDict["numCurrPoints"]=s.value("Spectrum/WinspecManual/numCurrPoints",("11"))
        settingsDict["Vcomp"]=s.value("Spectrum/WinspecManual/Vcomp",("1.5"))
        settingsDict["centerLambda"]=s.value("Spectrum/WinspecManual/centerLambda",("1.3"))
        settingsDict["numLambdaIndex"]=int(s.value("Spectrum/WinspecManual/numLambdaIndex",("3")))
        settingsDict["resolutionIndex"]=int(s.value("Spectrum/WinspecManual/resolutionIndex",("1")))
        settingsDict["roughAlign"]=s.value("Spectrum/WinspecManual/roughAlign",False)
        settingsDict["fineAlign"]=s.value("Spectrum/WinspecManual/fineAlign",False)
        return settingsDict

class RinSpectrumWidget(osaSpectrumWidget):
    """ Class for setting up electrical spectrum analyzer for RIN measurement """
    def  __init__(self,*args,**kwargs):
        super(RinSpectrumWidget, self).__init__(*args,**kwargs)
        self.measurementLabel="RIN Spectrum"
        # Link the class which will hold the measurement data
        from measurement import RinSpectrum
        self.measurementClass=RinSpectrum
        #self.build()

    def build(self):
        super(RinSpectrumWidget,self).build()
        self.specResCombo.currentIndexChanged.disconnect()
        self.specNumLambdaCombo.currentIndexChanged.disconnect()
        s = self.loadSettings()
        self.specCenterLambdaLabel.setText("Center (GHz)")
        self.specResLabel.setText("Resolution (GHz)")
        self.specResCombo.clear()
        self.specResCombo.addItems(["0"])
        self.specResCombo.setDisabled(True)
        self.specSpanLabel.setText("Span (GHz)")
        self.specSpanText.setEnabled(True)
        self.specSpanText.setText(s["span"])
        self.specSpanText.textEdited.connect(self.updateRes)
        self.specNumLambdaCombo.clear()
        self.specNumLambdaCombo.addItems(["501"])
        self.specNumLambdaCombo.setDisabled(True)
        self.updateRes("")
        # Special components for RIN measurement
        rinLayout=QtGui.QGridLayout()
        rinLayoutWidget=QtGui.QWidget()
        rinLayoutWidget.setLayout(rinLayout)
        rinDcConversionLabel = QtGui.QLabel("DC Conversion (V/A)")
        self.rinDcConversionText = QtGui.QLineEdit(s["dcConversion"])
        rinPreampGainLabel = QtGui.QLabel("Preamp Gain (dB)")
        self.rinPreampGainText = QtGui.QLineEdit(s["preampGain"])
        rinLayout.addWidget(rinDcConversionLabel,0,0)
        rinLayout.addWidget(rinPreampGainLabel,0,1)
        rinLayout.addWidget(self.rinDcConversionText,1,0)
        rinLayout.addWidget(self.rinPreampGainText,1,1)
        self.spectrumLayout.addWidget(rinLayoutWidget,5,0,2,2)
        

    def updateRes(self, dummyString):
        """ Helper function to update the resolution by dividing the span by number of points """
        try:
            self.specResCombo.setItemText(0, str(float(self.specSpanText.text())/(int(self.specNumLambdaCombo.currentText())-1)))
        except Exception as e:
            print(e.args[0])

    def getParameters(self):
        """ return a dictionary containing all of the parameters for the test object """
        testParameters={}
        testParameters["Label"]=self.measurementLabel
        testParameters["Istart"]=float(self.specStartCurrentText.text())/1000 # mA
        testParameters["Istop"]=float(self.specStopCurrentText.text())/1000   # mA
        testParameters["numCurrPoints"]=int(self.specNumCurrPointsText.text())
        testParameters["Vcomp"]=float(self.specCompVoltageText.text())
        testParameters["Center"]=float(self.specCenterLambdaText.text())*1e9 #GHz
        testParameters["Resolution"]=float(self.specResCombo.currentText())*1e9 #GHz
        testParameters["numLambdaPoints"]=int(self.specNumLambdaCombo.currentText())
        testParameters["numLambdaIndex"]=int(self.specNumLambdaCombo.currentIndex())
        testParameters["Span"]=float(self.specSpanText.text())*1e9 #GHz
        testParameters["roughAlign"]=self.roughAlignCheckbox.isChecked()
        testParameters["fineAlign"]=self.fineAlignCheckbox.isChecked()
        testParameters["dcConversion"]=float(self.rinDcConversionText.text())
        testParameters["preampGain"]=10**(float(self.rinPreampGainText.text())/10)  #dB
        return testParameters   

    def saveSettings(self):
        # Save current values to QSettings
        settings=QtCore.QSettings()
        settings.setValue("Spectrum/RinSpectrum/startCurrent",(self.specStartCurrentText.text()))
        settings.setValue("Spectrum/RinSpectrum/stopCurrent",(self.specStopCurrentText.text()))
        settings.setValue("Spectrum/RinSpectrum/numCurrPoints",(self.specNumCurrPointsText.text()))
        settings.setValue("Spectrum/RinSpectrum/Vcomp",(self.specCompVoltageText.text()))
        settings.setValue("Spectrum/RinSpectrum/centerLambda",(self.specCenterLambdaText.text()))
        settings.setValue("Spectrum/RinSpectrum/span",(self.specSpanText.text()))
        #settings.setValue("Spectrum/RinSpectrum/numLambdaIndex",(self.specNumLambdaCombo.currentIndex()))
        #settings.setValue("Spectrum/RinSpectrum/resolutionIndex", (self.specResCombo.currentIndex()))
        settings.setValue("Spectrum/RinSpectrum/roughAlign",(self.roughAlignCheckbox.checkState()))
        settings.setValue("Spectrum/RinSpectrum/fineAlign",(self.fineAlignCheckbox.checkState()))
        settings.setValue("Spectrum/RinSpectrum/dcConversion",(self.rinDcConversionText.text()))
        settings.setValue("Spectrum/RinSpectrum/preampGain",(self.rinPreampGainText.text()))

    def loadSettings(self):
        """ Load the last used or default settings """
        s=QtCore.QSettings()
        settingsDict={}
        settingsDict["startCurrent"]=s.value("Spectrum/RinSpectrum/startCurrent",("5"))
        settingsDict["stopCurrent"]=s.value("Spectrum/RinSpectrum/stopCurrent",("10"))
        settingsDict["numCurrPoints"]=s.value("Spectrum/RinSpectrum/numCurrPoints",("11"))
        settingsDict["Vcomp"]=s.value("Spectrum/RinSpectrum/Vcomp",("1.5"))
        settingsDict["centerLambda"]=s.value("Spectrum/RinSpectrum/centerLambda",("9"))
        settingsDict["span"]=s.value("Spectrum/RinSpectrum/span",("18"))
        settingsDict["numLambdaIndex"]=0
        settingsDict["resolutionIndex"]=0
        settingsDict["roughAlign"]=s.value("Spectrum/RinSpectrum/roughAlign",False)
        settingsDict["fineAlign"]=s.value("Spectrum/RinSpectrum/fineAlign",False)
        settingsDict["dcConversion"]=s.value("Spectrum/RinSpectrum/dcConversion","1000")
        settingsDict["preampGain"]=s.value("Spectrum/RinSpectrum/preampGain","25")
        return settingsDict