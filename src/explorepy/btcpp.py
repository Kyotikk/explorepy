# -*- coding: utf-8 -*-
"""A module for bluetooth connection"""
import abc
import logging
import sys
import threading
import time
from queue import Queue

from bleak import BleakClient, BleakScanner, BLEDevice, AdvertisementData
import asyncio

from explorepy import (
    exploresdk,
    settings_manager
)
from explorepy._exceptions import (
    DeviceNotFoundError,
    InputError
)

logger = logging.getLogger(__name__)


class BTClient(abc.ABC):
    @abc.abstractmethod
    def __init__(self, device_name=None, mac_address=None):
        if (mac_address is None) and (device_name is None):
            raise InputError("Either name or address options must be provided!")
        self.is_connected = False
        self.mac_address = mac_address
        self.device_name = device_name
        self.bt_serial_port_manager = None
        self.device_manager = None

    @abc.abstractmethod
    def connect(self):
        """Connect to the device and return the socket

        Returns:
            socket (bluetooth.socket)
        """

    @abc.abstractmethod
    def reconnect(self):
        """Reconnect to the last used bluetooth socket.

        This function reconnects to the last bluetooth socket. If after 1 minute the connection doesn't succeed,
        program will end.
        """

    @abc.abstractmethod
    def disconnect(self):
        """Disconnect from the device"""

    @abc.abstractmethod
    def _find_mac_address(self):
        pass

    @abc.abstractmethod
    def read(self, n_bytes):
        """Read n_bytes from the socket

            Args:
                n_bytes (int): number of bytes to be read

            Returns:
                list of bytes
        """

    @abc.abstractmethod
    def send(self, data):
        """Send data to the device

        Args:
            data (bytearray): Data to be sent
        """

    @staticmethod
    def _check_mac_address(device_name, mac_address):
        return (device_name[-4:-2] == mac_address[-5:-3]) and (device_name[-2:] == mac_address[-2:])


class SDKBtClient(BTClient):
    """ Responsible for Connecting and reconnecting explore devices via bluetooth"""

    def __init__(self, device_name=None, mac_address=None):
        """Initialize Bluetooth connection

        Args:
            device_name(str): Name of the device (either device_name or device address should be given)
            mac_address(str): Devices MAC address
        """
        if (mac_address is None) and (device_name is None):
            raise InputError("Either name or address options must be provided!")
        self.is_connected = False
        self.mac_address = mac_address
        self.device_name = device_name
        self.bt_serial_port_manager = None
        self.device_manager = None

    def connect(self):
        """Connect to the device and return the socket

        Returns:
            socket (bluetooth.socket)
        """
        config_manager = settings_manager.SettingsManager(self.device_name)
        mac_address = config_manager.get_mac_address()

        if mac_address is None:
            self._find_mac_address()
            config_manager.set_mac_address(self.mac_address)
        else:
            self.mac_address = mac_address
            self.device_name = "Explore_" + str(self.mac_address[-5:-3]) + str(self.mac_address[-2:])

        for _ in range(5):
            try:
                self.bt_serial_port_manager = exploresdk.BTSerialPortBinding_Create(self.mac_address, 5)
                return_code = self.bt_serial_port_manager.Connect()
                logger.debug("Return code for connection attempt is : {}".format(return_code))

                if return_code == 0:
                    self.is_connected = True
                    return
                else:
                    self.is_connected = False
                    logger.warning("Could not connect; Retrying in 2s...")
                    time.sleep(2)

            except SystemError as error:
                self.is_connected = False
                logger.debug(
                    "Got an exception while connecting to the device: {} of type: {}".format(error, type(error)))

            except TypeError as error:
                self.is_connected = False
                logger.debug(
                    "Got an exception while connecting to the device: {} of type: {}".format(error, type(error))
                )
                raise ConnectionRefusedError("Please unpair Explore device manually or use a Bluetooth dongle")
            except Exception as error:
                self.is_connected = False
                logger.debug(
                    "Got an exception while connecting to the device: {} of type: {}".format(error, type(error))
                )
                logger.warning("Could not connect; Retrying in 2s...")
                time.sleep(2)

        self.is_connected = False
        raise DeviceNotFoundError(
            "Could not find the device! Please make sure the device is on and in advertising mode."
        )

    def reconnect(self):
        """Reconnect to the last used bluetooth socket.

        This function reconnects to the last bluetooth socket. If after 1 minute the connection doesn't succeed,
        program will end.
        """
        self.is_connected = False
        for _ in range(5):
            self.bt_serial_port_manager = exploresdk.BTSerialPortBinding_Create(self.mac_address, 5)
            connection_error_code = self.bt_serial_port_manager.Connect()
            logger.debug("Got an exception while connecting to the device: {}".format(connection_error_code))
            if connection_error_code == 0:
                self.is_connected = True
                logger.info('Connected to the device')
                return self.bt_serial_port_manager
            else:
                self.is_connected = False
                logger.warning("Couldn't connect to the device. Trying to reconnect...")
                time.sleep(2)
        logger.error("Could not reconnect after 5 attempts. Closing the socket.")
        return None

    def disconnect(self):
        """Disconnect from the device"""
        self.is_connected = False
        self.bt_serial_port_manager.Close()

    def _find_mac_address(self):
        self.device_manager = exploresdk.ExploreSDK_Create()
        for _ in range(5):
            available_list = self.device_manager.PerformDeviceSearch()
            logger.debug("Number of devices found: {}".format(len(available_list)))
            for bt_device in available_list:
                if bt_device.name == self.device_name:
                    self.mac_address = bt_device.address
                    return

            logger.warning("No device found with the name: %s, searching again...", self.device_name)
            time.sleep(0.1)
        raise DeviceNotFoundError("No device found with the name: {}".format(self.device_name))

    def read(self, n_bytes):
        """Read n_bytes from the socket

            Args:
                n_bytes (int): number of bytes to be read

            Returns:
                list of bytes
        """
        try:
            read_output = self.bt_serial_port_manager.Read(n_bytes)
            actual_byte_data = read_output.encode('utf-8', errors='surrogateescape')
            return actual_byte_data
        except OverflowError as error:
            if not self.is_connected:
                raise IOError("connection has been closed")
            else:
                logger.debug(
                    "Got an exception while reading data from "
                    "socket which connection is open: {} of type:{}".format(error, type(error)))
                raise ConnectionAbortedError(error)
        except IOError as error:
            if not self.is_connected:
                raise IOError(str(error))
        except (MemoryError, OSError) as error:
            logger.debug("Got an exception while reading data from socket: {} of type:{}".format(error, type(error)))
            raise ConnectionAbortedError(str(error))
        except Exception as error:
            print(error)
            logger.error(
                "unknown error occured while reading bluetooth data by "
                "exploresdk {} of type:{}".format(error, type(error))
            )

    def send(self, data):
        """Send data to the device

        Args:
            data (bytearray): Data to be sent
        """
        self.bt_serial_port_manager.Write(data)


class BLEClient(BTClient):
    """ Responsible for Connecting and reconnecting explore devices via bluetooth"""

    def __init__(self, device_name=None, mac_address=None):
        """Initialize Bluetooth connection

        Args:
            device_name(str): Name of the device (either device_name or device address should be given)
            mac_address(str): Devices MAC address
        """
        super().__init__(device_name=device_name, mac_address=mac_address)

        self.ble_device = None
        self.eeg_service_uuid = "FFFE0001-B5A3-F393-E0A9-E50E24DCCA9E"
        self.eeg_tx_char_uuid = "FFFE0003-B5A3-F393-E0A9-E50E24DCCA9E"
        self.eeg_rx_char_uuid = "FFFE0002-B5A3-F393-E0A9-E50E24DCCA9E"
        self.rx_char = None
        self.loop = None
        self.buffer = Queue()
        self.try_disconnect = False
        self.try_send = None
        self.notification_thread = None
        self.copy_buffer = bytearray()

    async def stream(self):

        async with BleakClient(self.ble_device) as client:
            def handle_packet(sender, bt_byte_array):
                # write packet to buffer
                self.buffer.put(bt_byte_array)

            await client.start_notify(self.eeg_tx_char_uuid, handle_packet)
            loop = asyncio.get_running_loop()
            self.rx_char = client.services.get_service(self.eeg_service_uuid).get_characteristic(self.eeg_rx_char_uuid)
            while True:
                # This waits until you type a line and press ENTER.
                # A real terminal program might put stdin in raw mode so that things
                # like CTRL+C get passed to the remote device.
                data = await loop.run_in_executor(None, sys.stdin.buffer.readline)

                # data will be empty on EOF (e.g. CTRL+D on *nix)
                if not data:
                    break

            # self.try_disconnect = False
            # self.is_connected = False

    def connect(self):
        """Connect to the device and return the socket

        Returns:
            socket (bluetooth.socket)
        """
        asyncio.run(self._discover_device())
        if self.ble_device is None:
            print('No device found!!')
        else:
            logger.info('Device is connected')
            self.is_connected = True
            self.notification_thread = threading.Thread(target=self.start_read_loop, daemon=True)
            self.notification_thread.start()

    def start_read_loop(self):
        asyncio.run(self.stream())

    def stop_read_loop(self):
        self.notification_thread.join()

    async def _discover_device(self):
        if self.mac_address:
            self.ble_device = await BleakScanner.find_device_by_address(self.mac_address)
        else:
            logger.info('Commencing device discovery')
            self.ble_device = await BleakScanner.find_device_by_name(self.device_name, timeout=15)

        if self.ble_device is None:
            print('No device found!!!!!')
            raise DeviceNotFoundError(
                "Could not discover the device! Please make sure the device is on and in advertising mode."
            )

    def reconnect(self):
        """Reconnect to the last used bluetooth socket.

        This function reconnects to the last bluetooth socket. If after 1 minute the connection doesn't succeed,
        program will end.
        """
        self.connect()

    def disconnect(self):
        """Disconnect from the device"""
        self.try_disconnect = True

    def _find_mac_address(self):
        raise NotImplementedError

    def read(self, n_bytes):
        """Read n_bytes from the socket

            Args:
                n_bytes (int): number of bytes to be read

            Returns:
                list of bytes
        """
        if len(self.copy_buffer) < n_bytes:
            get_item = self.buffer.get()
            self.copy_buffer.extend(get_item)
        ret = self.copy_buffer[:n_bytes]
        self.copy_buffer = self.copy_buffer[n_bytes:]
        return ret

    def send(self, data):
        """Send data to the device

        Args:
            data (bytearray): Data to be sent
        """
        asyncio.run(self.write_ble_data(data))


    def write_ble_data(self, data):
        async with BleakClient(self.ble_device) as client:
            await client.write_gatt_char(self.rx_char, data, response=False)

    def match_eeg_uuid(self, device: BLEDevice, adv: AdvertisementData):
        # This assumes that the device includes the EEG service UUID in the
        # advertising data. This test may need to be adjusted depending on the
        # actual advertising data supplied by the device.
        if self.eeg_service_uuid.lower() in adv.service_uuids and adv.local_name == self.device_name:
            print('name is {}'.format(adv.local_name))
            return True
