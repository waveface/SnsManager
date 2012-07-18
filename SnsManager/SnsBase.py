import urllib3

class SnsBase(object):
    class MockLogger(object):
        def __init__(self, *args, **kwargs):
            return None
        def __call__(self, *args, **kwargs):
            return self
        def __getattr__(self, key):
            return self

    def __init__(self, *args, **kwargs):
        """
        Constructor of SnsBase

        In:
            accessToken         --  accessToken
            logger              --  logger *optional*

        """
        if 'accessToken' not in kwargs:
            raise ValueError('Invalid parameters.')
        self._accessToken = kwargs['accessToken']
        self._logger = kwargs.get('logger', SnsBase.MockLogger())

        self._httpConn = urllib3.PoolManager()
        self._timeout = 60
        self._timeout = kwargs.get('timeout', 60)

class ErrorCode(object):
    S_OK=                   (0x00000000,    'Success')

    E_FAILED=               (0x10000000,    'Generic error')
    E_NO_DATA=              (0x10000001,    'No more data')
    E_INVALID_TOKEN=        (0x10000002,    'Invalid access token')

    @classmethod
    def IS_SUCCEEDED(cls, errorCode):
        return not cls.IS_FAILED(errorCode)

    @classmethod
    def IS_FAILED(cls, errorCode):
        if (errorCode[0] >> 28) & 1:
            return True
        return False
