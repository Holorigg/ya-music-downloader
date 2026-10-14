"""Read connection state from Windows WLAN; do not inspect network names."""
import ctypes
from ctypes import wintypes

class Interface(ctypes.Structure):
    _fields_=[('guid',ctypes.c_byte*16),('description',wintypes.WCHAR*256),('state',wintypes.DWORD)]

def app_identity():
    try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('holorigg.MyMusic')
    except (AttributeError,OSError):pass

def wifi_connected():
    handle=wintypes.HANDLE();data=ctypes.c_void_p();version=wintypes.DWORD()
    try:
        dll=ctypes.WinDLL('wlanapi');dll.WlanOpenHandle.argtypes=[wintypes.DWORD,ctypes.c_void_p,ctypes.POINTER(wintypes.DWORD),ctypes.POINTER(wintypes.HANDLE)];dll.WlanEnumInterfaces.argtypes=[wintypes.HANDLE,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)];dll.WlanFreeMemory.argtypes=[ctypes.c_void_p];dll.WlanCloseHandle.argtypes=[wintypes.HANDLE,ctypes.c_void_p]
        if dll.WlanOpenHandle(2,None,ctypes.byref(version),ctypes.byref(handle))!=0:return False
        if dll.WlanEnumInterfaces(handle,None,ctypes.byref(data))!=0 or not data.value:return False
        count=ctypes.cast(data,ctypes.POINTER(wintypes.DWORD))[0]
        if count>64:return False
        entries=(Interface*count).from_address(data.value+8)
        return any(item.state==1 for item in entries)
    except (OSError,AttributeError):return False
    finally:
        if data.value:dll.WlanFreeMemory(data)
        if handle.value:dll.WlanCloseHandle(handle,None)
