import os
import re
import time
import json
import uuid
import dateutil
import urllib, urllib2
import urlparse
from datetime import datetime, timedelta
from dateutil import parser as dateParser
from FbBase import FbBase, FbErrorCode
from FbUserInfo import FbUserInfo

class FbImporter(FbBase):
    def __init__(self, *args, **kwargs):
        """
        Constructor of FbBase

        In:
            tmpFolder           --  tmp folder to store photo files *optional* default is /tmp 

        """
        FbBase.__init__(self, *args, **kwargs)

        self._tmpFolder = kwargs['tmpFolder'] if 'tmpFolder' in kwargs else '/tmp'

    def getData(self, since=None, until=None):
        """
        Get data from Facebook feed

        In:
            since           --  The start time to get data
                                given None means current time
                                or given python's datetime instance as input
            until           --  The end time to get date
                                given None means yesterday
                                or given python's datetime instance as input

            Example: (Please note that the direction to retrieve data is backward)
                Now   --->   2012/04/01   --->   2012/01/01
                You can specify since=None and until=<datetime of 2012/01/01>
                or since=<datetime of 2012/04/01> until=<datetime of 2012/01/01>

        Out:
            Return a python dict object
            {
                'data': [               # List of data
                    {
                        'id': 'postId',
                        'message': 'Text',
                        'links': [ 'uri' ],
                        'photos': [ '/path/to/file' ],
                        'createdTime': <datetime object>,
                        'updatedTime': <datetime object>,
                    },
                ],
                'count': 30,                    # count in data list
                'retCode': FbErrorCode.S_OK,    # returned code which is instance of FbErrorCode

            }
        """
        retDict = {
            'retCode': FbErrorCode.E_FAILED,
            'count': 0,
            'data': [],
        }

        if not until:
            until = datetime.now() - timedelta(1)

        errorCode, feedData = self._pageCrawler(since, until)
        failoverCount = 0
        failoverThreshold = 3
        while errorCode != FbErrorCode.E_NO_DATA:
            if FbErrorCode.IS_FAILED(errorCode):
                failoverCount += 1
                # If crawling failed (which is not no data), wait and try again
                if failoverCount <= failoverThreshold:
                    time.sleep(2)
                    errorCode, feedData = self._pageCrawler(since, until)
                    continue
                else:
                    # FIXME: For over threshold case, need to consider how to crawl following data
                    # Currently return error 
                    retDict['retCode'] = errorCode
                    return retDict

            feedHandler = FbFeedsHandler(tmpFolder=self._tmpFolder,
                myFbId=FbUserInfo(accessToken=self._accessToken, logger=self._logger).getMyId(),
                accessToken=self._accessToken,
                feeds=feedData,
                logger=self._logger,
                )
            parsedData = feedHandler.parse()
            retDict['data'] += parsedData

            since = urlparse.parse_qs(urlparse.urlsplit(feedData['paging']['next']).query)['until'][0]
            since = datetime.fromtimestamp(int(since))
            errorCode, feedData = self._pageCrawler(since, until)


        retDict['count'] = len(retDict['data'])
        retDict['retCode'] = FbErrorCode.S_OK
        return retDict

    def _datetime2Timestamp(self, datetimeObj):
        return int(time.mktime(datetimeObj.timetuple()))

    def _pageCrawler(self, since, until):
        params = {
            'access_token' : self._accessToken,
        }

        # Handle since/until parameters, please note that our definitions of since/until are totally different than Facebook
        if since:
            params['until'] = self._datetime2Timestamp(since)
        if until:
            params['since'] = self._datetime2Timestamp(until)
        if since and until and since < until:
            raise ValueError('since cannot older than until')

        uri = '{0}me/feed?{1}'.format(self._graphUri, urllib.urlencode(params))
        self._logger.debug('URI to retrieve [%s]' % uri)
        try:
            conn = urllib2.urlopen(uri, timeout=self._timeout)
        except: 
            self._logger.exception('Unable to get data from Facebook')
            return FbErrorCode.E_FAILED, {}
        retDict = json.loads(conn.read())
        if 'data' not in retDict or 'paging' not in retDict:
            return FbErrorCode.E_NO_DATA, {}
        return FbErrorCode.S_OK, retDict


class FbFeedsHandler(FbBase):
    def __init__(self, *args, **kwargs):
        FbBase.__init__(self, *args, **kwargs)
        self._tmpFolder = kwargs.get('tmpFolder', '/tmp')
        self._feeds = kwargs['feeds']
        self._myFbId = kwargs['myFbId']

    def parse(self):
        if 'data' not in self._feeds:
            raise ValueError()

        retData = []
        for feed in self._feeds['data']:
            if not self._feedFilter(feed):
                continue
            parsedData = self._feedParser(feed)
            if parsedData:
                #self._dumpData(parsedData)
                retData.append(parsedData)
        return retData

    def _convertTimeFormat(self, fbTime):
        return dateParser.parse(fbTime)

    def _storeFileToTemp(self, fileUri):
        fileExtName = fileUri[fileUri.rfind('.') + 1:]
        newFileName = os.path.join(self._tmpFolder, "{0}.{1}".format(str(uuid.uuid1()), fileExtName))
        try:
            conn = urllib2.urlopen(fileUri)
            fileObj = file(newFileName, 'w')
            fileObj.write(conn.read())
            fileObj.close()
        except:
            return None
        return newFileName

    def _feedFilter(self, feed):
        # Strip contents which not posted by me
        if feed['from']['id'] != self._myFbId:
            return False

        # Type filter
        if 'type' not in feed:
            raise ValueError()
        fType = feed['type']
        if fType == 'status':
            # For status + story case, it might be event commenting to friend or adding friend
            # So we filter message field
            if 'message' in feed:
                return True
        elif fType == 'link':
            if 'message' in feed:
                return True
        elif fType == 'photo':
            # photo + link: Please note that repost of others' link will also be in 
            return True
        return False

    def _dumpData(self, data):
        self._logger.debug((u"\nid[%s]\ncreatedTime[%s]\nupdatedTime[%s]\nmessage[%s]\nlinks[%s]\nphotos[%s]\n" % (
                data['id'],
                data['createdTime'].isoformat(),
                data['updatedTime'].isoformat(),
                data['message'],
                data['links'],
                data['photos'],
        )).encode('utf-8'))

    def _imgLinkHandler(self, uri):
        fPath = None
        # Strip safe_image.php
        urlsplitObj = urlparse.urlsplit(uri)
        if urlsplitObj.path == '/safe_image.php':
            queryDict = urlparse.parse_qs(urlsplitObj.query)
            if 'url' in queryDict:
                uri = queryDict['url'][0]

        # Replace subfix to _o, e.g. *_s.jpg to *_o.jpg
        rePattern = re.compile('(_\w)(\.\w+?$)')
        if re.search(rePattern, uri):
            origPic = re.sub(rePattern, '_o\\2', uri)
            fPath = self._storeFileToTemp(origPic)
            if fPath:
                return fPath
        # If we cannot retrieve original picture, turn to use the link Facebook provided instead.
        fPath = self._storeFileToTemp(uri)
        return fPath

    def _feedParser(self, feed):
        ret = None
        if 'message' in feed:
            ret = {}
            ret['id'] = feed['id']
            ret['message'] = feed['message']
            ret['createdTime'] = self._convertTimeFormat(feed['created_time'])
            ret['updatedTime'] = self._convertTimeFormat(feed['updated_time'])
            ret['links'] = []
            if 'link' in feed:
                ret['links'].append(feed['link'])
            ret['photos'] = []
            if 'picture' in feed:
                imgPath = self._imgLinkHandler(feed['picture'])
                if imgPath:
                    ret['photos'].append(imgPath)
        return ret
