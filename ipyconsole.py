import IPython, sys
from qtconsole.rich_ipython_widget import RichIPythonWidget
from qtconsole.inprocess import QtInProcessKernelManager
from IPython.lib import guisupport

class QIPythonWidget(RichIPythonWidget):
    """ Convenience class for a live IPython console widget. We can replace the standard banner using the customBanner argument"""
    def __init__(self,*args,**kwargs):
        self.banner="IPython %s on Python %s" % (IPython.__version__,sys.version)+"\n\n"
        super(QIPythonWidget, self).__init__(*args,**kwargs)
        self.kernel_manager = kernel_manager = QtInProcessKernelManager()
        kernel_manager.start_kernel()
        kernel_manager.kernel.gui = 'qt4'
        self.kernel_client = kernel_client = self._kernel_manager.client()
        kernel_client.start_channels()
       
        def stop():
            kernel_client.stop_channels()
            kernel_manager.shutdown_kernel()
            guisupport.get_app_qt4().exit()            
        self.exit_requested.connect(stop)
        
    def pushVariables(self,variableDict):
        """ Given a dictionary containing name / value pairs, push those variables to the IPython console widget """
        self.kernel_manager.kernel.shell.push(variableDict)
    def clearTerminal(self):
        """ Clears the terminal """
        self._control.clear()    
    def printText(self,text):
        """ Prints some plain text to the console """
        self._append_plain_text(text)        
    def executeCommand(self,command,hide=False):
        """ Execute a command in the frame of the console widget """
        self._execute(command,hide)

# Obsolete version which works with IPython 0.13.1 
"""import atexit
from IPython.zmq.ipkernel import IPKernelApp
from IPython.lib.kernel import find_connection_file
from IPython.frontend.qt.kernelmanager import QtKernelManager
from IPython.frontend.qt.console.rich_ipython_widget import RichIPythonWidget
from IPython.config.application import catch_config_error
from PyQt4.QtCore import QTimer


class QIPythonWidgetOld(RichIPythonWidget):

    class KernelApp(IPKernelApp):
        @catch_config_error
        def initialize(self, argv=[]):
            super(QIPythonWidget.KernelApp, self).initialize(argv)
            self.kernel.eventloop = self.loop_qt4_nonblocking
            self.kernel.start()
            self.start()

        def loop_qt4_nonblocking(self, kernel):
            kernel.timer = QTimer()
            kernel.timer.timeout.connect(kernel.do_one_iteration)
            kernel.timer.start(1000*kernel._poll_interval)

        def get_connection_file(self):
            return self.connection_file

        def get_user_namespace(self):
            return self.kernel.shell.user_ns

    def __init__(self, parent=None, colors='linux', instance_args=[]):
        super(QIPythonWidget, self).__init__()
        self.app = self.KernelApp.instance(argv=instance_args)
        self.app.initialize()
        self.set_default_style(colors=colors)
        self.connect_kernel(self.app.get_connection_file())

    def connect_kernel(self, conn, heartbeat=False):
        km = QtKernelManager(connection_file=find_connection_file(conn))
        km.load_connection_file()
        km.start_channels(hb=heartbeat)
        self.kernel_manager = km
        atexit.register(self.kernel_manager.cleanup_connection_file)

    def get_user_namespace(self):
        return self.app.get_user_namespace() """