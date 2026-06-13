# Dummy resource module for Windows
RLIMIT_NOFILE = 7

def getrlimit(resource):
    return (4096, 4096)

def setrlimit(resource, limits):
    pass
