"""Normal CPU/memory scheduling for the current service process only.

Task Scheduler's default background priority is unsuitable for the live price
receiver. No task/password, system power profile or other process is changed.
"""
import ctypes
from ctypes import wintypes
import os

NORMAL_PRIORITY_CLASS = 0x20
MEMORY_PRIORITY_NORMAL = 5


class MemoryPriority(ctypes.Structure):
    _fields_ = [('MemoryPriority', wintypes.ULONG)]


class WindowsScheduling:
    def __init__(self):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetCurrentProcess.argtypes = []
        self.kernel.GetCurrentProcess.restype = wintypes.HANDLE
        self.kernel.GetPriorityClass.argtypes = [wintypes.HANDLE]
        self.kernel.GetPriorityClass.restype = wintypes.DWORD
        self.kernel.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.SetPriorityClass.restype = wintypes.BOOL
        for name in ('GetProcessInformation', 'SetProcessInformation'):
            function = getattr(self.kernel, name)
            function.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.POINTER(MemoryPriority), wintypes.DWORD]
            function.restype = wintypes.BOOL
        self.handle = self.kernel.GetCurrentProcess()

    def read(self):
        cpu = self.kernel.GetPriorityClass(self.handle)
        memory = MemoryPriority()
        if not cpu or not self.kernel.GetProcessInformation(self.handle, 0, ctypes.byref(memory), ctypes.sizeof(memory)):
            raise OSError('SERVICE_SCHEDULING_READ_FAILED')
        return dict(cpu_class=int(cpu), memory_priority=int(memory.MemoryPriority))

    def apply_normal(self):
        if not self.kernel.SetPriorityClass(self.handle, NORMAL_PRIORITY_CLASS):
            raise OSError('SERVICE_CPU_PRIORITY_FAILED')
        memory = MemoryPriority(MEMORY_PRIORITY_NORMAL)
        if not self.kernel.SetProcessInformation(self.handle, 0, ctypes.byref(memory), ctypes.sizeof(memory)):
            raise OSError('SERVICE_MEMORY_PRIORITY_FAILED')


def normalize_service_priority(*, adapter=None):
    if adapter is None and os.name != 'nt':
        return dict(state='NOT_WINDOWS', changed=False)
    api = adapter if adapter is not None else WindowsScheduling()
    before = api.read()
    api.apply_normal()
    after = api.read()
    if after != dict(cpu_class=NORMAL_PRIORITY_CLASS, memory_priority=MEMORY_PRIORITY_NORMAL):
        raise OSError('SERVICE_SCHEDULING_NOT_NORMAL')
    return dict(state='NORMAL_VERIFIED', changed=before != after, before=before, after=after)
