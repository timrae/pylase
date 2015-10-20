# pylase
Extensible python software that I've used for automating measurements of LIV curves and lasing spectra of semiconductor lasers during my PhD research. 

Here are some of it's other capabilities:
* Pyqt GUI for easily plotting and switching between different measurement data
* Data stored in convenient HDF5 heirarchical database that can be read directly by almost any scientific software
* Embedded iPython terminal that you can use to do custom data manipulation and plotting
* Hakki-Paoli gain spectrum measurements (requires a compatible optical spectrum analyzer)
* Control the software "Winspec" as if it were an optical spectrum analyzer (requires a compatible spectrometer and camera)
* Temperature sweeps (requires a compatible temperature controller)
* Semi-automatic optical alignment (requires a compatible flexure stage)

This software is intended to be used together with my library of python drivers for communicating with scientific instruments called "drivepy". It's provided entirely as-is with the hope that someone somewhere finds it useful.