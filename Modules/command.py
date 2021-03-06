#!/usr/bin/env python3
# coding: utf-8 -*-
#
# Author: zaraki673 & pipiche38
#
"""
    Module: z_command.py

    Description: Implement the onCommand() 

"""

import Domoticz
import binascii
import time
import struct
import json

from Modules.actuators import actuators
from Modules.tools import Hex_Format, rgb_to_xy, rgb_to_hsl
from Modules.logging import loggingCommand
from Modules.basicOutputs import sendZigateCmd
from Modules.thermostats import thermostat_Setpoint, thermostat_Mode
from Modules.livolo import livolo_OnOff
from Modules.tuya import tuya_trv_mode
from Modules.legrand_netatmo import  legrand_fc40
from Modules.schneider_wiser import schneider_EHZBRTS_thermoMode, schneider_hact_fip_mode, schneider_set_contract, schneider_temp_Setcurrent, schneider_hact_heater_type
from Modules.profalux import profalux_stop, profalux_MoveToLiftAndTilt
from Modules.domoTools import UpdateDevice_v2, RetreiveSignalLvlBattery, RetreiveWidgetTypeList
from Classes.IAS import IAS_Zone_Management
from Modules.zigateConsts import THERMOSTAT_LEVEL_2_MODE, ZIGATE_EP
from Modules.widgets import SWITCH_LVL_MATRIX
from Modules.cmdsDoorLock import cluster0101_lock_door, cluster0101_unlock_door

def debugDevices( self, Devices, Unit):

    Domoticz.Log("Device Name: %s" %Devices[Unit].Name)
    Domoticz.Log("       DeviceId: %s" %Devices[Unit].DeviceID)
    Domoticz.Log("       Type: %s" %Devices[Unit].Type)
    Domoticz.Log("       Subtype: %s" %Devices[Unit].SubType)
    Domoticz.Log("       SwitchType: %s" %Devices[Unit].SwitchType)
    Domoticz.Log("       Options: %s" %Devices[Unit].Options)
    Domoticz.Log("       LastLevel: %s" %Devices[Unit].LastLevel)
    Domoticz.Log("       LastUpdate: %s" %Devices[Unit].LastUpdate)

# Matrix between Domoticz Type, Subtype, SwitchType and Plugin DeviceType
# Type, Subtype, Switchtype
DEVICE_SWITCH_MATRIX = {
    ( 242,  1,   ): ('ThermoSetpoint', 'TempSetCurrent'),

    ( 241,  2,  7): ('ColorControlRGB',),
    ( 241,  4,  7): ('ColorControlRGBWW',),
    ( 241,  7,  7): ('ColorControlFull',),
    ( 241,  8,  7): ('ColorControlWW',),

    ( 244, 62, 18): ('Switch Selector',), 
    ( 244, 73,  0): ('Switch', '' 'LivoloSWL', 'LivoloSWR' , 'SwitchButton', 'Water', 'Plug'),
    ( 244, 73,  5): ('Smoke',),
    ( 244, 73,  7): ('LvlControl',),
    ( 244, 73,  9): ('Button',),
    ( 244, 73, 13): ('BSO',),
    ( 244, 73, 15): ('VenetianInverted', 'Venetian'),
    ( 244, 73, 16): ('BlindInverted','WindowCovering'),

}

ACTIONATORS = [ 'Switch', 'Plug', 'SwitchAQ2', 'Smoke', 'DSwitch', 'LivoloSWL', 'LivoloSWR', 'Toggle',
            'Venetian', 'VenetianInverted', 'WindowCovering', 'BSO', 'BSO-Orientation', 'BSO-Volet',
            'LvlControl', 'ColorControlRGB', 'ColorControlWW', 'ColorControlRGBWW', 'ColorControlFull', 'ColorControl',
            'ThermoSetpoint', 'ThermoMode', 'ThermoMode_2', 'ThermoModeEHZBRTS', 'TempSetCurrent', 'AlarmWD',
            'LegrandFilPilote', 'FIP', 'HACTMODE','ContractPower','HeatingSwitch', 'DoorLock' ]
            
def mgtCommand( self, Devices, Unit, Command, Level, Color ):

    if Devices[Unit].DeviceID not in self.IEEE2NWK:
        Domoticz.Error("mgtCommand - something strange the Device %s DeviceID: %s Unknown" %(Devices[Unit].Name, Devices[Unit].DeviceID))
        return

    NWKID = self.IEEE2NWK[Devices[Unit].DeviceID]
    loggingCommand( self, 'Debug', "mgtCommand (%s) Devices[%s].Name: %s Command: %s Level: %s Color: %s" 
        %(NWKID, Unit , Devices[Unit].Name, Command, Level, Color ), NWKID)
  
    deviceType = Devices[Unit].Type
    deviceSubType = Devices[Unit].SubType
    deviceSwitchType = Devices[Unit].SwitchType

    if ( deviceType, deviceSubType, deviceSwitchType ) in DEVICE_SWITCH_MATRIX:
        domoticzType = DEVICE_SWITCH_MATRIX[ ( deviceType, deviceSubType, deviceSwitchType ) ] 
        loggingCommand( self, "Debug", "--------->   DeviceType: %s" %str( domoticzType ), NWKID)

    SignalLevel, BatteryLevel =  RetreiveSignalLvlBattery( self, NWKID)

    # Now we have to identify the Endpoint, DeviceType to be use for that command
    # inputs are : Device.ID
    # For each Ep of this Device we should find an entry ClusterType where is store Device.ID and DeviceType

    ClusterTypeList = RetreiveWidgetTypeList( self, Devices, NWKID, Unit )

    if len(ClusterTypeList) == 0 :    # No match with ClusterType
        # Should not happen. We didn't find any Widget references in the Device ClusterType!
        Domoticz.Error("mgtCommand - no ClusterType found !  "  +str(self.ListOfDevices[NWKID]) )
        return

    loggingCommand( self, 'Debug', "--------->   ClusterType founds: %s for Unit: %s" %( ClusterTypeList, Unit), NWKID)

    actionable = False
    if len(ClusterTypeList) != 1:
        Domoticz.Error("mgtCommand - Not Expected. ClusterType: %s for NwkId: %s" %(ClusterTypeList,NWKID ))
        return

    if ClusterTypeList[0][0] == '00':
        EPout = '01'

    # One element found, we have Endpoint and DevicetypeÒ
    EPout , DeviceTypeWidgetId, DeviceType = ClusterTypeList[0]

    loggingCommand( self, "Debug", "--------->   EPOut: %s DeviceType: %s WidgetID: %s" %( EPout , DeviceType, DeviceTypeWidgetId ), NWKID)
    # Sanity Check
    forceUpdateDev = False
    if DeviceType in SWITCH_LVL_MATRIX:
        if 'ForceUpdate' in SWITCH_LVL_MATRIX[DeviceType ]:
            forceUpdateDev = SWITCH_LVL_MATRIX[DeviceType ]['ForceUpdate']

    if DeviceType not in ACTIONATORS and not self.pluginconf.pluginConf['forcePassiveWidget']:
        loggingCommand( self, "Log", "mgtCommand - You are trying to action not allowed for Device: %s Type: %s and DeviceType: %s Command: %s Level:%s" 
                %( Devices[Unit].Name, ClusterTypeList, DeviceType , Command, Level), NWKID )
        return
    
    profalux = False
    if 'Manufacturer' in self.ListOfDevices[NWKID]:
        profalux = ( self.ListOfDevices[NWKID]['Manufacturer'] == '1110' and self.ListOfDevices[NWKID]['ZDeviceID'] in ('0200', '0202') )

    if 'Health' in self.ListOfDevices[NWKID]:
        # If Health is Not Reachable, let's give it a chance to be updated
        if self.ListOfDevices[NWKID]['Health'] == 'Not Reachable':
            self.ListOfDevices[NWKID]['Health'] = ''

    if Command == 'Stop':  # Manage the Stop command. For known seen only on BSO and Windowcoering
        loggingCommand( self, 'Debug', "mgtCommand : Stop for Device: %s EPout: %s Unit: %s DeviceType: %s" %(NWKID, EPout, Unit, DeviceType), NWKID)
        if profalux:
            # Profalux offer a Manufacturer command to make Stop on Cluster 0x0008
            profalux_stop( self, NWKID)

        elif DeviceType in ( "WindowCovering", "VenetianInverted", "Venetian"):
            # https://github.com/fairecasoimeme/ZiGate/issues/125#issuecomment-456085847
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "02")
            UpdateDevice_v2(self, Devices, Unit, 2, "50", BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                    
        # Let's force a refresh of Attribute in the next Heartbeat 
        self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

    if Command == "Off" :  # Manage the Off command. 
        # Let's force a refresh of Attribute in the next Heartbeat  
        self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

        loggingCommand( self, 'Debug', "mgtCommand : Off for Device: %s EPout: %s Unit: %s DeviceType: %s" %(NWKID, EPout, Unit, DeviceType), NWKID)
        if DeviceType == 'LivoloSWL':
            livolo_OnOff( self, NWKID , EPout, 'Left', 'Off')
            UpdateDevice_v2(self, Devices, Unit, 0, "Off",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                        
            # Let's force a refresh of Attribute in the next Heartbeat 
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'LivoloSWR':
            livolo_OnOff( self, NWKID , EPout, 'Right', 'Off')
            UpdateDevice_v2(self, Devices, Unit, 0, "Off",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                        
            # Let's force a refresh of Attribute in the next Heartbeat 
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'ThermoMode_2':
            loggingCommand( self, 'Debug', "mgtCommand : Set Level for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            loggingCommand( self, 'Debug', "ThermoMode - requested Level: %s" %Level, NWKID)
            tuya_trv_mode( self, NWKID, 0 )

        if DeviceType == 'ThermoModeEHZBRTS':
            loggingCommand( self, 'Debug', "MajDomoDevice EHZBRTS Schneider Thermostat Mode Off", NWKID )
            schneider_EHZBRTS_thermoMode( self, NWKID, 0 )
            UpdateDevice_v2(self, Devices, Unit, 0, "Off",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat 
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'BSO-Volet':
            if profalux:
                profalux_MoveToLiftAndTilt( self, NWKID, level=1 )

        elif DeviceType == "WindowCovering":
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "01") # Blind inverted (On, for Close)

        elif DeviceType == "VenetianInverted":
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "01") # Venetian Inverted/Blind (On, for Close)

        elif DeviceType == "Venetian":
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "00") # Venetian /Blind (Off, for Close)
                
        elif DeviceType == "AlarmWD":
            Domoticz.Log("Alarm WarningDevice - value: %s" %Level)
            self.iaszonemgt.alarm_off( NWKID, EPout)

        elif DeviceType == "HeatingSwitch":
            thermostat_Mode( self, NWKID, 'Off' )

        elif DeviceType == 'DoorLock':
            # Widget Doorlock seems to work in the oposit
            cluster0101_unlock_door( self, NWKID)
            UpdateDevice_v2(self, Devices, Unit, 0, "Closed",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
            self.ListOfDevices[NWKID]['Heartbeat'] = '0' 
            return

        else:
            # Remaining Slider widget
            if profalux: # Profalux are define as LvlControl but should be managed as Blind Inverted
                sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + '01' + '%02X' %0 + "0000")
            else:
                sendZigateCmd(self, "0092","02" + NWKID + ZIGATE_EP + EPout + "00")
        
            if 'Model' in self.ListOfDevices[NWKID]: # Making a trick for the GLEDOPTO LED STRIP.
                if self.ListOfDevices[NWKID]['Model'] == 'GLEDOPTO' and EPout == '0a':
                    # When switching off the WW channel, make sure to switch Off the RGB channel
                    sendZigateCmd(self, "0092","02" + NWKID + ZIGATE_EP + '0b' + "00")

        # Update Devices
        if Devices[Unit].SwitchType in (13,14,15,16):
            UpdateDevice_v2(self, Devices, Unit, 0, "0",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
        else :
            UpdateDevice_v2(self, Devices, Unit, 0, "Off",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                    
        # Let's force a refresh of Attribute in the next Heartbeat 
        self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

    if Command == "On" :
        # Let's force a refresh of Attribute in the next Heartbeat  
        self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
        loggingCommand( self, 'Debug', "mgtCommand : On for Device: %s EPout: %s Unit: %s DeviceType: %s" %(NWKID, EPout, Unit, DeviceType), NWKID)

        if DeviceType == 'LivoloSWL':
            livolo_OnOff( self, NWKID , EPout, 'Left', 'On')
            UpdateDevice_v2(self, Devices, Unit, 1, "On",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                        
            # Let's force a refresh of Attribute in the next Heartbeat 
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'LivoloSWR':
            livolo_OnOff( self, NWKID , EPout, 'Right', 'On')
            UpdateDevice_v2(self, Devices, Unit, 1, "On",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat 
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'BSO-Volet':
            if profalux:
                # On translated into a Move to 254
                profalux_MoveToLiftAndTilt( self, NWKID, level=255 )

        elif DeviceType == "WindowCovering":
            # https://github.com/fairecasoimeme/ZiGate/issues/125#issuecomment-456085847
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "00") # Blind inverted (Off, for Open)

        elif DeviceType == "VenetianInverted":
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "00") # Venetian inverted/Blind (Off, for Open)

        elif DeviceType == "Venetian":
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + '01') # Venetian/Blind (On, for Open)

        elif DeviceType == "HeatingSwitch":
            thermostat_Mode( self, NWKID, 'Heat' )

        elif DeviceType == 'DoorLock':
            cluster0101_lock_door( self, NWKID)
            UpdateDevice_v2(self, Devices, Unit, 1, "Open",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
            self.ListOfDevices[NWKID]['Heartbeat'] = 0 
            return
        else:
            # Remaining Slider widget
            if profalux:
                sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + '01' + '%02X' %255 + "0000")
            else:
                sendZigateCmd(self, "0092","02" + NWKID + ZIGATE_EP + EPout + "01")

        if Devices[Unit].SwitchType in (13,14,15,16):
            UpdateDevice_v2(self, Devices, Unit, 1, "100",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
        else:
            UpdateDevice_v2(self, Devices, Unit, 1, "On",BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

        # Let's force a refresh of Attribute in the next Heartbeat  
        self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

    if Command == "Set Level" :
        #Level is normally an integer but may be a floating point number if the Unit is linked to a thermostat device
        #There is too, move max level, mode = 00/01 for 0%/100%
        loggingCommand( self, 'Debug', "mgtCommand : Set Level for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
            %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
        
        if DeviceType == 'ThermoSetpoint':
            loggingCommand( self, 'Debug', "mgtCommand : Set Level for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            value = int(float(Level)*100)
            thermostat_Setpoint( self, NWKID, value )
            Level = round(float(Level),2)
            # Normalize SetPoint value with 2 digits
            Round = lambda x, n: eval('"%.' + str(int(n)) + 'f" % ' + repr(x))
            Level = Round( float(Level), 2 )
            UpdateDevice_v2(self, Devices, Unit, 0, str(Level),BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'TempSetCurrent':
            loggingCommand( self, 'Debug', "mgtCommand : Set Temp for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            value = int(float(Level)*100)
            schneider_temp_Setcurrent( self, NWKID, value )
            Level = round(float(Level),2)
            # Normalize SetPoint value with 2 digits
            Round = lambda x, n: eval('"%.' + str(int(n)) + 'f" % ' + repr(x))
            Level = Round( float(Level), 2 )
            UpdateDevice_v2(self, Devices, Unit, 0, str(Level),BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'ThermoModeEHZBRTS':
            loggingCommand( self, 'Debug', "MajDomoDevice EHZBRTS Schneider Thermostat Mode %s" %Level, NWKID)
            schneider_EHZBRTS_thermoMode( self, NWKID, Level)
            UpdateDevice_v2(self, Devices, Unit, int(Level)//10, Level,BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'HACTMODE':
            loggingCommand( self, 'Debug', "mgtCommand : Set Level for HACT Mode: %s EPout: %s Unit: %s DeviceType: %s Level: %s" %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            if 'Schneider Wiser' not in self.ListOfDevices[NWKID]:
                self.ListOfDevices[NWKID]['Schneider Wiser'] ={}

            if Level == 10: # Conventional
                UpdateDevice_v2(self, Devices, Unit, int(Level)//10, Level,BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                self.ListOfDevices[NWKID]['Schneider Wiser']['HACT Mode'] = 'conventionel'
                schneider_hact_heater_type( self, NWKID, 'conventional')

            elif Level == 20: # fip
                UpdateDevice_v2(self, Devices, Unit, int(Level)//10, Level,BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)
                self.ListOfDevices[NWKID]['Schneider Wiser']['HACT Mode'] = 'fip'
                schneider_hact_heater_type( self, NWKID, 'fip')

            else:
                Domoticz.Error("Unknown mode %s for HACTMODE for device %s" %( Level, NWKID))

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'ContractPower':
            loggingCommand( self, 'Debug', "mgtCommand : Set Level for ContractPower Mode: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            CONTRACT_MODE = {
                10: 3,
                20: 6,
                30: 9,
                40: 12,
                50: 15,
                }
            if 'Schneider Wiser' not in self.ListOfDevices[NWKID]:
                self.ListOfDevices[NWKID]['Schneider Wiser'] ={}

            if Level in CONTRACT_MODE:
                loggingCommand( self, 'Log', "mgtCommand : -----> Contract Power : %s - %s KVA" %(Level, CONTRACT_MODE[ Level ]), NWKID)
                if 'Model' in self.ListOfDevices[NWKID]:
                    if self.ListOfDevices[NWKID]['Model'] == 'EH-ZB-BMS':
                        self.ListOfDevices[NWKID]['Schneider Wiser']['Contract Power'] = CONTRACT_MODE[ Level ]
                        schneider_set_contract( self, NWKID, EPout, CONTRACT_MODE[ Level ] )
                        UpdateDevice_v2(self, Devices, Unit, int(Level)//10, Level,BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'FIP':
            FIL_PILOT_MODE = {
                10: 'Confort',
                20: 'Confort -1',
                30: 'Confort -2',
                40: 'Eco',
                50: 'Frost Protection',
                60: 'Off',
                }
            loggingCommand( self, 'Log', "mgtCommand : Set Level for FIP: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            if 'Schneider Wiser' not in self.ListOfDevices[NWKID]:
                self.ListOfDevices[NWKID]['Schneider Wiser'] ={}

            if Level in FIL_PILOT_MODE:
                loggingCommand( self, 'Log', "mgtCommand : -----> Fil Pilote mode: %s - %s" %(Level, FIL_PILOT_MODE[ Level ]), NWKID)
                if 'Model' in self.ListOfDevices[NWKID]:
                    if self.ListOfDevices[NWKID]['Model'] == 'EH-ZB-HACT':
                        self.ListOfDevices[NWKID]['Schneider Wiser']['HACT FIP Mode'] = FIL_PILOT_MODE[ Level ]
                        schneider_hact_fip_mode( self, NWKID,  FIL_PILOT_MODE[ Level ] )
                        UpdateDevice_v2(self, Devices, Unit, int(Level)//10, Level,BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'LegrandFilPilote':
            FIL_PILOTE_MODE = {
                10: 'Confort',
                20: 'Confort -1',
                30: 'Confort -2',
                40: 'Eco',
                50: 'Hors Gel',
                60: 'Off',
                }

            loggingCommand( self, 'Log', "mgtCommand : Set Level for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            if Level in FIL_PILOTE_MODE:
                loggingCommand( self, 'Log', "mgtCommand : -----> Fil Pilote mode: %s - %s" %(Level, FIL_PILOTE_MODE[ Level ]), NWKID)
                legrand_fc40( self, FIL_PILOTE_MODE[ Level ])
                UpdateDevice_v2(self, Devices, Unit, int(Level)//10, Level,BatteryLevel, SignalLevel,  ForceUpdate_=forceUpdateDev)

            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  
            return

        if DeviceType == 'ThermoMode':
            loggingCommand( self, 'Debug', "mgtCommand : Set Level for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            loggingCommand( self, 'Debug', "ThermoMode - requested Level: %s" %Level, NWKID)
            if Level in THERMOSTAT_LEVEL_2_MODE:
                loggingCommand( self, 'Debug', " - Set Thermostat Mode to : %s / %s" %( Level, THERMOSTAT_LEVEL_2_MODE[Level]), NWKID)
                thermostat_Mode( self, NWKID, THERMOSTAT_LEVEL_2_MODE[Level] )

        if DeviceType == 'ThermoMode_2':
            loggingCommand( self, 'Debug', "mgtCommand : Set Level for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s" 
                %(NWKID, EPout, Unit, DeviceType, Level), NWKID)
            loggingCommand( self, 'Debug', "ThermoMode_2 - requested Level: %s" %Level, NWKID)
            tuya_trv_mode( self, NWKID, Level )


        elif DeviceType == 'BSO-Volet':
            if profalux:
                # Transform slider % into analog value
                lift = ( 255 * Level ) // 100
                if Level == 0:
                    lift = 1
                elif Level > 255:
                    lift = 255
                
                loggingCommand( self, 'Log', "mgtCommand : profalux_MoveToLiftAndTilt: %s BSO-Volet Lift: Level:%s Lift: %s" %(NWKID, Level, lift), NWKID)
                profalux_MoveToLiftAndTilt( self, NWKID, level=lift)

        elif DeviceType == 'BSO-Orientation':
             if profalux:
                Tilt = Level - 10
                loggingCommand( self, 'Log', "mgtCommand : profalux_MoveToLiftAndTilt:  %s BSO-Orientation : Level: %s Tilt: %s" %(NWKID, Level, Tilt), NWKID)
                profalux_MoveToLiftAndTilt( self, NWKID, tilt=Tilt)           

        elif DeviceType == "WindowCovering": # Blind Inverted
            if Level == 0:
                Level = 1
            elif Level >= 100:
                Level = 99
            value = '%02x' %Level
            loggingCommand( self, 'Debug', "WindowCovering - Lift Percentage Command - %s/%s Level: 0x%s %s" %(NWKID, EPout, value, Level), NWKID)
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "05" + value)

        elif DeviceType == "Venetian":
            if Level == 0:
                Level = 1
            elif Level >= 100:
                Level = 99
            value = '%02x' %Level
            loggingCommand( self, 'Debug', "Venetian blind - Lift Percentage Command - %s/%s Level: 0x%s %s" %(NWKID, EPout, value, Level), NWKID)
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "05" + value)

        elif DeviceType == "VenetianInverted":
            Level = 100 - Level
            if Level == 0:
                Level = 1
            elif Level >= 100:
                Level = 99
            value = '%02x' %Level
            loggingCommand( self, 'Debug', "VenetianInverted blind - Lift Percentage Command - %s/%s Level: 0x%s %s" %(NWKID, EPout, value, Level), NWKID)
            sendZigateCmd(self, "00FA","02" + NWKID + ZIGATE_EP + EPout + "05" + value)

        elif DeviceType == "AlarmWD":
            loggingCommand( self, 'Debug', "Alarm WarningDevice - value: %s" %Level)
            if Level == 0: # Stop
                self.iaszonemgt.alarm_off( NWKID, EPout)
            elif Level == 10: # Alarm
                self.iaszonemgt.alarm_on(  NWKID, EPout)
            elif Level == 20: # Siren
                self.iaszonemgt.siren_only( NWKID, EPout)
            elif Level == 30: # Strobe
                self.iaszonemgt.strobe_only( NWKID, EPout)
            elif Level == 40: # Armed - Squawk
                self.iaszonemgt.write_IAS_WD_Squawk( NWKID, EPout, 'armed')
            elif Level == 50: # Disarmed
                self.iaszonemgt.write_IAS_WD_Squawk( NWKID, EPout, 'disarmed')

        elif DeviceType == 'Toggle':
            loggingCommand( self, 'Debug', "Toggle switch - value: %s" %Level)
            if Level == 10: # Off
                actuators( self, NWKID, EPout, 'Off', 'Switch')
            elif Level == 20: # On
                actuators( self, NWKID, EPout, 'On', 'Switch')
            elif Level == 30: # Toggle
                actuators( self, NWKID, EPout, 'Toggle', 'Switch')

        else:
            # Remaining Slider widget
            OnOff = '01' # 00 = off, 01 = on
            if Level == 100: 
                value = 255
            elif Level == 0: 
                value = 0
            else:
                value = round( (Level*255)/100)
                if Level > 0 and value == 0: 
                    value = 1

            value=Hex_Format(2, value)
            if profalux:
                sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + OnOff + value + "0000")
            else:
                sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + OnOff + value + "0010")

        if Devices[Unit].SwitchType in (13,14,15,16):
            UpdateDevice_v2(self, Devices, Unit, 2, str(Level) ,BatteryLevel, SignalLevel) 
        else:
            # A bit hugly, but '1' instead of '2' is needed for the ColorSwitch dimmer to behave correctky
            UpdateDevice_v2(self, Devices, Unit, 1, str(Level) ,BatteryLevel, SignalLevel)

        # Let's force a refresh of Attribute in the next Heartbeat  
        self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

    if Command == "Set Color" :
        loggingCommand( self, 'Debug', "mgtCommand : Set Color for Device: %s EPout: %s Unit: %s DeviceType: %s Level: %s Color: %s" %(NWKID, EPout, Unit, DeviceType, Level, Color), NWKID)
        Hue_List = json.loads(Color)
        loggingCommand( self, 'Debug', "-----> Hue_List: %s" %str(Hue_List), NWKID)

        #Color 
        #    ColorMode m;
        #    uint8_t t;     // Range:0..255, Color temperature (warm / cold ratio, 0 is coldest, 255 is warmest)
        #    uint8_t r;     // Range:0..255, Red level
        #    uint8_t g;     // Range:0..255, Green level
        #    uint8_t b;     // Range:0..255, Blue level
        #    uint8_t cw;    // Range:0..255, Cold white level
        #    uint8_t ww;    // Range:0..255, Warm white level (also used as level for monochrome white)
        #
        transitionRGB = '%04x' %self.pluginconf.pluginConf['moveToColourRGB']
        transitionMoveLevel = '%04x' %self.pluginconf.pluginConf['moveToLevel']
        transitionHue = '%04x' %self.pluginconf.pluginConf['moveToHueSatu']
        transitionTemp = '%04x' %self.pluginconf.pluginConf['moveToColourTemp']

        #First manage level
        if Hue_List['m'] != 9998:
            # In case of m ==3, we will do the Setlevel
            OnOff = '01' # 00 = off, 01 = on
            value=Hex_Format(2,round(1+Level*254/100)) #To prevent off state
            loggingCommand( self, 'Debug', "---------- Set Level: %s" %(value), NWKID)
            # u16TransitionTime is the time taken, in units of tenths of a second, to reach the target level 
            # (0xFFFF means use the u16OnOffTransitionTime attribute instead
            transitionONOFF = 'ffff' 
            sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + OnOff + value + transitionMoveLevel)
            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

        #Now colorgrep 
        #ColorModeNone = 0   // Illegal
        #ColorModeNone = 1   // White. Valid fields: none

        if Hue_List['m'] == 1:
            ww = int(Hue_List['ww']) # Can be used as level for monochrome white
            #TODO : Jamais vu un device avec ca encore
            loggingCommand( self, 'Log', "Not implemented device color 1", NWKID)

        #ColorModeTemp = 2   // White with color temperature. Valid fields: t
        if Hue_List['m'] == 2:
            #Value is in mireds (not kelvin)
            #Correct values are from 153 (6500K) up to 588 (1700K)
            # t is 0 > 255
            TempKelvin = int(((255 - int(Hue_List['t']))*(6500-1700)/255)+1700)
            TempMired = 1000000 // TempKelvin
            loggingCommand( self, 'Debug', "---------- Set Temp Kelvin: %s-%s" %(TempMired, Hex_Format(4,TempMired)), NWKID)
            #u16TransitionTime is the time period, in tenths of a second, over which the change in hue should be implemented

            sendZigateCmd(self, "00C0","02" + NWKID + ZIGATE_EP + EPout + Hex_Format(4,TempMired) + transitionTemp)

        #ColorModeRGB = 3    // Color. Valid fields: r, g, b.
        elif Hue_List['m'] == 3:
            x, y = rgb_to_xy((int(Hue_List['r']),int(Hue_List['g']),int(Hue_List['b'])))
            #Convert 0>1 to 0>FFFF
            x = int(x*65536)
            y = int(y*65536)
            strxy = Hex_Format(4,x) + Hex_Format(4,y)
            loggingCommand( self, 'Debug', "---------- Set Temp X: %s Y: %s" %(x, y), NWKID)
            sendZigateCmd(self, "00B7","02" + NWKID + ZIGATE_EP + EPout + strxy + transitionRGB)

        #ColorModeCustom = 4, // Custom (color + white). Valid fields: r, g, b, cw, ww, depending on device capabilities
        elif Hue_List['m'] == 4:
            #Gledopto GL_008
            # Color: {"b":43,"cw":27,"g":255,"m":4,"r":44,"t":227,"ww":215}
            loggingCommand( self, 'Log', "Not fully implemented device color 4", NWKID)

            # Process White color
            cw = int(Hue_List['cw'])   # 0 < cw < 255 Cold White
            ww = int(Hue_List['ww'])   # 0 < ww < 255 Warm White
            if cw != 0 and ww != 0:
                TempKelvin = int(((255 - int(ww))*(6500-1700)/255)+1700)
                TempMired = 1000000 // TempKelvin
                loggingCommand( self, 'Log', "---------- Set Temp Kelvin: %s-%s" %(TempMired, Hex_Format(4,TempMired)), NWKID)
                sendZigateCmd(self, "00C0","02" + NWKID + ZIGATE_EP + EPout + Hex_Format(4,TempMired) + transitionTemp)
            else:
                # How to powerOff the WW/CW channel ?
                pass

            # Process Colour
            h, s, l = rgb_to_hsl((int(Hue_List['r']),int(Hue_List['g']),int(Hue_List['b'])))
            saturation = s * 100   #0 > 100
            hue = h *360           #0 > 360
            hue = int(hue*254//360)
            saturation = int(saturation*254//100)
            loggingCommand( self, 'Log', "---------- Set Hue X: %s Saturation: %s" %(hue, saturation), NWKID)
            sendZigateCmd(self, "00B6","02" + NWKID + ZIGATE_EP + EPout + Hex_Format(2,hue) + Hex_Format(2,saturation) + transitionRGB)

            #value = int(l * 254//100)
            #OnOff = '01'
            #loggingCommand( self, 'Debug', "---------- Set Level: %s instead of Level: %s" %(value, Level), NWKID)
            #sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + OnOff + Hex_Format(2,value) + "0000")
            # Let's force a refresh of Attribute in the next Heartbeat  
            #self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

        #With saturation and hue, not seen in domoticz but present on zigate, and some device need it
        elif Hue_List['m'] == 9998:
            h, s, l = rgb_to_hsl((int(Hue_List['r']),int(Hue_List['g']),int(Hue_List['b'])))
            saturation = s * 100   #0 > 100
            hue = h *360           #0 > 360
            hue = int(hue*254//360)
            saturation = int(saturation*254//100)
            loggingCommand( self, 'Debug', "---------- Set Hue X: %s Saturation: %s" %(hue, saturation), NWKID)
            sendZigateCmd(self, "00B6","02" + NWKID + ZIGATE_EP + EPout + Hex_Format(2,hue) + Hex_Format(2,saturation) + transitionHue)

            value = int(l * 254//100)
            OnOff = '01'
            loggingCommand( self, 'Debug', "---------- Set Level: %s instead of Level: %s" %(value, Level), NWKID)
            sendZigateCmd(self, "0081","02" + NWKID + ZIGATE_EP + EPout + OnOff + Hex_Format(2,value) + transitionMoveLevel)
            # Let's force a refresh of Attribute in the next Heartbeat  
            self.ListOfDevices[NWKID]['Heartbeat'] = '0'  

        UpdateDevice_v2(self, Devices, Unit, 1, str(Level) ,BatteryLevel, SignalLevel, str(Color))
